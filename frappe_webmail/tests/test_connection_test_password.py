# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The connection test of a saved mailbox signs in with the password the mailbox keeps, not with the asterisks its form
shows.

Frappe hands a saved password to the form as asterisks (its length of them): the form had nothing else to send, so the
test signed in to both servers with the asterisks, and told a mailbox that works that its password was wrong.

- A password the person did not touch (asterisks) is read from the saved mailbox, for its owner.
- Administrator and a colleague the mailbox is shared with can open the mailbox and press the button too (maintenance
  #2595): for them the saved password is used when the form names the very servers the mailbox signs in to (servers,
  ports, encryption, certificate check, login names). Change any of them and the stored password does not move: they
  type it, and what they type is tested as typed.
- A password typed is tested as typed, on a saved mailbox too (the person is checking the new one before saving it).
- Asterisks with no saved mailbox behind them, or a mailbox that is not the person's, are no password: nothing is
  signed in with them, and no stored password is tested against a server the person names.

Run with:
    bench --site prodclone.local run-tests --module frappe_webmail.tests.test_connection_test_password
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api

OWNER = "webmail-pwtest-owner@yopmail.com"
OTHER = "webmail-pwtest-other@yopmail.com"
SHARED = "webmail-pwtest-shared@yopmail.com"
BOX = "webmail-pwtest-box@connection-test.test"
IMAP_STORED = "imap-Stored-1"
SMTP_STORED = "smtp-Stored-22"
IMAP_STARS = "*" * len(IMAP_STORED)
SMTP_STARS = "*" * len(SMTP_STORED)

# The form as the saved mailbox fills it in
FORM = {
	"email": BOX,
	"imap_host": "imap.connection-test.test",
	"imap_port": 993,
	"imap_ssl": 1,
	"smtp_host": "smtp.connection-test.test",
	"smtp_port": 587,
	"smtp_ssl": 0,
	"smtp_starttls": 1,
	"auth_type": "Password",
	"smtp_verify_certificate": 1,
}

# Each one edited in the form before the button is pressed: where the test would sign in, or as whom, is no longer
# what the mailbox keeps
EDITS = (
	{"imap_host": "imap.elsewhere.test"},
	{"imap_port": 143},
	{"imap_ssl": 0},
	{"smtp_host": "smtp.elsewhere.test"},
	{"smtp_port": 25},
	{"smtp_ssl": 1},
	{"smtp_starttls": 0},
	{"smtp_verify_certificate": 0},
	{"login_id": "someone-else"},
	{"smtp_login_id": "relay-account"},
	{"email": "another@connection-test.test"},
)


@contextmanager
def as_administrator():
	"""The one person besides a mailbox's owner who may edit it, so open its form and press the button."""
	previous = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(previous)


def _test_the_form(account_name=None, imap_password=IMAP_STARS, smtp_password=SMTP_STARS, **edited):
	"""What the desk form sends when its button is pressed; `edited` are the settings changed before pressing it."""
	return webmail_api.test_connection_live(
		**{
			**FORM,
			"imap_password": imap_password,
			"smtp_password": smtp_password,
			"account_name": account_name,
			**edited,
		}
	)


class TestConnectionTestPassword(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		with as_role("sales_user", email=OWNER):
			pass
		with as_role("purchase_user", email=OTHER):
			pass
		with as_role("purchase_user", email=SHARED):
			pass
		if frappe.db.exists("Webmail Account", BOX):
			frappe.delete_doc("Webmail Account", BOX, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": BOX,
				"user": OWNER,
				"sender_name": "Password test",
				"auth_type": "Password",
				"imap_host": "imap.connection-test.test",
				"imap_port": 993,
				"imap_ssl": 1,
				"imap_password": IMAP_STORED,
				"smtp_host": "smtp.connection-test.test",
				"smtp_port": 587,
				"smtp_ssl": 0,
				"smtp_starttls": 1,
				"smtp_password": SMTP_STORED,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		if frappe.db.exists("Webmail Account", BOX):
			frappe.delete_doc("Webmail Account", BOX, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		imap = patch("frappe_webmail.webmail_api.IMAPClient")
		smtp = patch("frappe_webmail.webmail_api.smtplib.SMTP")
		self.imap_class = imap.start()
		self.smtp_class = smtp.start()
		self.addCleanup(imap.stop)
		self.addCleanup(smtp.stop)
		self.imap = MagicMock()
		self.smtp = MagicMock()
		self.imap_class.return_value.__enter__ = MagicMock(return_value=self.imap)
		self.imap_class.return_value.__exit__ = MagicMock(return_value=False)
		self.smtp_class.return_value.__enter__ = MagicMock(return_value=self.smtp)
		self.smtp_class.return_value.__exit__ = MagicMock(return_value=False)

	def test_a_saved_mailbox_is_tested_with_its_stored_passwords_when_the_form_sends_asterisks(self):
		with as_role("sales_user", email=OWNER):
			result = _test_the_form(account_name=BOX)
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with(BOX, IMAP_STORED)
		self.smtp.login.assert_called_once_with(BOX, SMTP_STORED)

	def test_a_password_typed_is_tested_as_typed_on_a_saved_mailbox(self):
		with as_role("sales_user", email=OWNER):
			result = _test_the_form(account_name=BOX, imap_password="typed-New-1")
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with(BOX, "typed-New-1")
		# The SMTP one was not touched: the stored one is still the one tested
		self.smtp.login.assert_called_once_with(BOX, SMTP_STORED)

	def test_asterisks_with_no_saved_mailbox_are_no_password(self):
		with as_role("sales_user", email=OWNER), self.assertRaises(frappe.ValidationError):
			_test_the_form(account_name=None)
		self.imap_class.assert_not_called()
		self.imap.login.assert_not_called()
		self.smtp.login.assert_not_called()

	def test_a_mailbox_that_is_not_the_persons_gives_no_password_to_test(self):
		with as_role("purchase_user", email=OTHER), self.assertRaises(frappe.ValidationError):
			_test_the_form(account_name=BOX)
		self.imap_class.assert_not_called()
		self.imap.login.assert_not_called()
		self.smtp.login.assert_not_called()

	def _share_with(self, user):
		frappe.get_doc(
			{
				"doctype": "Webmail Account User",
				"parent": BOX,
				"parenttype": "Webmail Account",
				"parentfield": "allowed_users",
				"user": user,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "Webmail Account User", {"parent": BOX, "user": user})

	def _the_ones_who_may_open_it_without_owning_it(self):
		"""Administrator, who may edit any mailbox, and a colleague it is shared with."""
		self._share_with(SHARED)
		return (
			("Administrator", as_administrator),
			("shared", lambda: as_role("purchase_user", email=SHARED)),
		)

	def test_administrator_tests_a_colleagues_mailbox_with_its_stored_passwords(self):
		# The case that failed: an administrator adds the mailbox for a colleague, fixes its password, saves, presses
		# the button on the form (asterisks) and was told to enter the IMAP password
		with as_administrator():
			result = _test_the_form(account_name=BOX)
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with(BOX, IMAP_STORED)
		self.smtp.login.assert_called_once_with(BOX, SMTP_STORED)

	def test_a_colleague_the_mailbox_is_shared_with_tests_it_with_its_stored_passwords(self):
		self._share_with(SHARED)
		with as_role("purchase_user", email=SHARED):
			result = _test_the_form(account_name=BOX)
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with(BOX, IMAP_STORED)
		self.smtp.login.assert_called_once_with(BOX, SMTP_STORED)

	def test_someone_other_than_the_owner_who_edits_a_server_must_type_the_password(self):
		# Their edit could send the stored password to a server they name: it stays where it is, whatever they edit
		for who, acting in self._the_ones_who_may_open_it_without_owning_it():
			for edited in EDITS:
				with (
					self.subTest(who=who, edited=edited),
					acting(),
					self.assertRaises(frappe.ValidationError),
				):
					_test_the_form(account_name=BOX, **edited)
		self.imap_class.assert_not_called()
		self.imap.login.assert_not_called()
		self.smtp.login.assert_not_called()

	def test_what_someone_other_than_the_owner_types_is_tested_as_typed_and_no_stored_password_follows_it(
		self,
	):
		# A password typed on another server is theirs to test; the stored one never takes the place of the other
		# (the sending password left as asterisks falls back on the one typed, not on a stored one)
		for who, acting in self._the_ones_who_may_open_it_without_owning_it():
			with self.subTest(who=who), acting():
				self.imap.reset_mock()
				self.smtp.reset_mock()
				result = _test_the_form(
					account_name=BOX, imap_password="typed-New-1", imap_host="imap.elsewhere.test"
				)
				self.assertTrue(result["success"], result)
				self.imap.login.assert_called_once_with(BOX, "typed-New-1")
				self.smtp.login.assert_called_once_with(BOX, "typed-New-1")

	def test_the_owner_who_edits_a_server_still_tests_with_their_own_stored_password(self):
		with as_role("sales_user", email=OWNER):
			result = _test_the_form(account_name=BOX, imap_host="imap.elsewhere.test")
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with(BOX, IMAP_STORED)
		self.smtp.login.assert_called_once_with(BOX, SMTP_STORED)
