# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""A mailbox that signs in with something other than its address.

Some servers sign a mailbox in with a username or an account number, not with its address. The mailbox says so (a box
to tick and a login ID), and the same one signs it in to IMAP and to SMTP; the address stays the one mail is sent from.

- Left unticked (every mailbox made before), the servers are signed in with the address, as always.
- OAuth2 mailboxes are signed in with their address: the provider knows them by it.
- The form's connection test signs in with the login ID too, or it would fail on a mailbox that works.

Run with:
    bench --site prodclone.local run-tests --module frappe_webmail.tests.test_login_id
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api

OWNER = "webmail-loginid-owner@yopmail.com"
ADDRESS = "box@login-id.test"
PASSWORDS = {"imap_password": "imap-secret", "smtp_password": "smtp-secret"}


def _account(**fields):
	values = {
		"email": ADDRESS,
		"auth_type": "Password",
		"login_id_is_different": 0,
		"login_id": "",
		"get_password": lambda fieldname: PASSWORDS[fieldname],
		"get_oauth_access_token": lambda: "access-token",
	}
	values.update(fields)
	return SimpleNamespace(**values)


class TestLoginId(FrappeTestCase):
	def test_the_address_is_the_login_unless_the_mailbox_says_otherwise(self):
		from frappe_webmail.utils.login_id import login_id_of

		self.assertEqual(login_id_of(_account()), ADDRESS)
		# Ticked and empty: nothing to sign in with but the address
		self.assertEqual(login_id_of(_account(login_id_is_different=1, login_id="  ")), ADDRESS)
		# Unticked: a login ID left behind is not used
		self.assertEqual(login_id_of(_account(login_id_is_different=0, login_id="user42")), ADDRESS)
		self.assertEqual(login_id_of(_account(login_id_is_different=1, login_id=" user42 ")), "user42")
		# A mailbox made before the field existed has no such attribute
		self.assertEqual(login_id_of(SimpleNamespace(email=ADDRESS)), ADDRESS)

	def test_imap_is_signed_in_with_the_login_id(self):
		client = MagicMock()
		webmail_api._imap_login_raw(client, _account(login_id_is_different=1, login_id="user42"))
		client.login.assert_called_once_with("user42", "imap-secret")

	def test_imap_is_signed_in_with_the_address_when_the_login_is_not_different(self):
		client = MagicMock()
		webmail_api._imap_login_raw(client, _account(login_id="left-behind"))
		client.login.assert_called_once_with(ADDRESS, "imap-secret")

	def test_smtp_is_signed_in_with_the_same_login_id(self):
		server = MagicMock()
		webmail_api._smtp_login_raw(server, _account(login_id_is_different=1, login_id="user42"))
		server.login.assert_called_once_with("user42", "smtp-secret")

	def test_an_oauth_mailbox_is_signed_in_with_its_address(self):
		account = _account(auth_type="OAuth2", login_id_is_different=1, login_id="user42")
		client = MagicMock()
		webmail_api._imap_login_raw(client, account)
		client.oauth2_login.assert_called_once_with(ADDRESS, "access-token")
		client.login.assert_not_called()

	def test_the_form_declares_the_login_id_next_to_the_password_and_asks_for_it_when_ticked(self):
		path = os.path.join(
			os.path.dirname(webmail_api.__file__),
			"frappe_webmail",
			"doctype",
			"webmail_account",
			"webmail_account.json",
		)
		with open(path) as f:
			doctype = json.load(f)
		fields = {df["fieldname"]: df for df in doctype["fields"]}
		order = doctype["field_order"]
		self.assertEqual(fields["login_id_is_different"]["fieldtype"], "Check")
		self.assertEqual(fields["login_id"]["fieldtype"], "Data")
		self.assertIn("login_id_is_different", fields["login_id"]["depends_on"])
		self.assertIn("login_id_is_different", fields["login_id"]["mandatory_depends_on"])
		# Both are for a password mailbox only
		self.assertIn("Password", fields["login_id_is_different"]["depends_on"])
		# The login ID is read before the password it goes with
		self.assertLess(order.index("login_id_is_different"), order.index("login_id"))
		self.assertLess(order.index("login_id"), order.index("imap_password"))


class TestConnectionTestLoginId(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		with as_role("sales_user", email=OWNER):
			pass

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

	def _test_the_form(self, **more):
		return webmail_api.test_connection_live(
			email=ADDRESS,
			imap_host="imap.login-id.test",
			imap_port=993,
			imap_ssl=1,
			smtp_host="smtp.login-id.test",
			smtp_port=587,
			smtp_ssl=0,
			smtp_starttls=1,
			auth_type="Password",
			imap_password="typed-imap",
			smtp_password="typed-smtp",
			smtp_verify_certificate=1,
			**more,
		)

	def test_the_connection_test_signs_in_with_the_login_id_the_form_gives(self):
		with as_role("sales_user", email=OWNER):
			result = self._test_the_form(login_id="user42")
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with("user42", "typed-imap")
		self.smtp.login.assert_called_once_with("user42", "typed-smtp")

	def test_the_connection_test_signs_in_with_the_address_when_no_login_id_is_given(self):
		with as_role("sales_user", email=OWNER):
			result = self._test_the_form()
		self.assertTrue(result["success"], result)
		self.imap.login.assert_called_once_with(ADDRESS, "typed-imap")
		self.smtp.login.assert_called_once_with(ADDRESS, "typed-smtp")
