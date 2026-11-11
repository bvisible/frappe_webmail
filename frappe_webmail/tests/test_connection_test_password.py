# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The connection test of a saved mailbox signs in with the password the mailbox keeps, not with the asterisks its form
shows.

Frappe hands a saved password to the form as asterisks (its length of them): the form had nothing else to send, so the
test signed in to both servers with the asterisks, and told a mailbox that works that its password was wrong.

- A password the person did not touch (asterisks) is read from the saved mailbox, for its owner.
- A password typed is tested as typed, on a saved mailbox too (the person is checking the new one before saving it).
- Asterisks with no saved mailbox behind them, or a mailbox that is not the person's, are no password: nothing is
  signed in with them, and no stored password is tested against a server the person names.

Run with:
    bench --site prodclone.local run-tests --module frappe_webmail.tests.test_connection_test_password
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api

OWNER = "webmail-pwtest-owner@yopmail.com"
OTHER = "webmail-pwtest-other@yopmail.com"
BOX = "webmail-pwtest-box@connection-test.test"
IMAP_STORED = "imap-Stored-1"
SMTP_STORED = "smtp-Stored-22"
IMAP_STARS = "*" * len(IMAP_STORED)
SMTP_STARS = "*" * len(SMTP_STORED)


def _test_the_form(account_name=None, imap_password=IMAP_STARS, smtp_password=SMTP_STARS):
	"""What the desk form sends when its button is pressed."""
	return webmail_api.test_connection_live(
		email=BOX,
		imap_host="imap.connection-test.test",
		imap_port=993,
		imap_ssl=1,
		smtp_host="smtp.connection-test.test",
		smtp_port=587,
		smtp_ssl=0,
		smtp_starttls=1,
		auth_type="Password",
		imap_password=imap_password,
		smtp_password=smtp_password,
		smtp_verify_certificate=1,
		account_name=account_name,
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
