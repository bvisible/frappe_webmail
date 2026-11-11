# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""A mailbox whose IMAP server starts in the clear and switches to TLS on request (STARTTLS, usually on port 143).

IMAP only knew « SSL or nothing »: a server that offers TLS by STARTTLS on the port it listens on (company servers,
Dovecot, Exchange on site) could not be reached encrypted, and the box left unticked sent the password in the clear.
SMTP had the choice already.

- STARTTLS is asked before anything is signed in, with the server's certificate and its name checked.
- Not when the connection is TLS from its first byte (SSL ticked), when it is not asked, or for a mailbox made before
  the field existed.
- The form's connection test does the same, and says STARTTLS when the server refuses it.

Run with:
    bench --site prodclone.local run-tests --module frappe_webmail.tests.test_imap_starttls
"""

import json
import os
import ssl
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api

OWNER = "webmail-starttls-owner@yopmail.com"
ADDRESS = "box@starttls.test"


def _account(**fields):
	values = {
		"email": ADDRESS,
		"auth_type": "Password",
		"imap_host": "imap.starttls.test",
		"imap_port": 143,
		"imap_ssl": 0,
		"imap_starttls": 1,
		"smtp_host": "smtp.starttls.test",
		"smtp_port": 587,
		"smtp_ssl": 0,
		"smtp_starttls": 1,
		"smtp_verify_certificate": 1,
		"get_password": lambda fieldname: "imap-secret",
		"get_oauth_access_token": lambda: "access-token",
	}
	values.update(fields)
	return SimpleNamespace(**values)


def _calls(client):
	return [call[0] for call in client.mock_calls]


class TestImapStarttls(FrappeTestCase):
	def test_the_connection_is_switched_to_tls_before_anything_is_signed_in(self):
		client = MagicMock()
		webmail_api._imap_login_raw(client, _account())
		self.assertEqual(_calls(client), ["starttls", "login"])
		context = client.starttls.call_args.kwargs["ssl_context"]
		self.assertIsInstance(context, ssl.SSLContext)
		# The server's certificate and its name are checked, as a browser checks them
		self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
		self.assertTrue(context.check_hostname)

	def test_an_oauth_mailbox_is_switched_to_tls_before_its_token_is_given(self):
		client = MagicMock()
		webmail_api._imap_login_raw(client, _account(auth_type="OAuth2"))
		self.assertEqual(_calls(client), ["starttls", "oauth2_login"])

	def test_a_connection_that_is_tls_from_its_first_byte_is_not_switched(self):
		client = MagicMock()
		webmail_api._imap_login_raw(client, _account(imap_ssl=1))
		self.assertEqual(_calls(client), ["login"])

	def test_a_mailbox_that_does_not_ask_for_it_is_not_switched(self):
		client = MagicMock()
		webmail_api._imap_login_raw(client, _account(imap_starttls=0))
		self.assertEqual(_calls(client), ["login"])

	def test_a_mailbox_made_before_the_field_existed_is_not_switched(self):
		client = MagicMock()
		account = _account()
		del account.imap_starttls
		webmail_api._imap_login_raw(client, account)
		self.assertEqual(_calls(client), ["login"])

	def test_a_server_that_refuses_to_switch_is_not_signed_in_and_the_error_says_so(self):
		client = MagicMock()
		client.starttls.side_effect = Exception("STARTTLS not supported by this server")
		with self.assertRaises(Exception):
			webmail_api._imap_login_raw(client, _account())
		client.login.assert_not_called()
		with (
			patch("frappe_webmail.webmail_api.IMAPClient") as imap,
			patch("frappe_webmail.webmail_api.smtplib"),
		):
			imap.return_value.__enter__ = MagicMock(return_value=client)
			imap.return_value.__exit__ = MagicMock(return_value=False)
			result = webmail_api._test_connection_internal(_account())
		self.assertTrue(any("STARTTLS" in error for error in result["errors"]), result)

	def test_the_form_declares_the_box_next_to_ssl_and_only_when_ssl_is_off(self):
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
		self.assertEqual(fields["imap_starttls"]["fieldtype"], "Check")
		self.assertEqual(str(fields["imap_starttls"].get("default", "0")), "0")
		self.assertIn("imap_ssl", fields["imap_starttls"]["depends_on"])
		self.assertEqual(order.index("imap_starttls"), order.index("imap_ssl") + 1)


class TestConnectionTestStarttls(FrappeTestCase):
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
			imap_host="imap.starttls.test",
			imap_port=143,
			imap_ssl=0,
			smtp_host="smtp.starttls.test",
			smtp_port=587,
			smtp_ssl=0,
			smtp_starttls=1,
			auth_type="Password",
			imap_password="typed-imap",
			smtp_password="typed-smtp",
			smtp_verify_certificate=1,
			**more,
		)

	def test_the_connection_test_switches_to_tls_when_the_form_asks_for_it(self):
		with as_role("sales_user", email=OWNER):
			result = self._test_the_form(imap_starttls=1)
		self.assertTrue(result["success"], result)
		self.assertEqual(self.imap_class.call_args.kwargs["ssl"], 0)
		self.assertEqual(_calls(self.imap), ["starttls", "login"])

	def test_the_connection_test_does_not_switch_when_the_form_does_not_ask(self):
		with as_role("sales_user", email=OWNER):
			result = self._test_the_form()
		self.assertTrue(result["success"], result)
		self.assertEqual(_calls(self.imap), ["login"])
