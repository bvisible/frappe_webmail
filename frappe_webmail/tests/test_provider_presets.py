# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""A password account can take its IMAP/SMTP settings from a provider preset (14.10.2026).

Gmail and Outlook already fill their servers when the account signs in with OAuth. A provider that signs in with an
address and a password had nothing: the servers were typed by hand. Infomaniak is the first: its mailboxes are read at
`mail.infomaniak.com` (IMAP 993 SSL, SMTP 587 STARTTLS; 465 SSL works too), checked live with this app's own IMAP
client on 14.10.2026.

These tests need no site.
"""

import unittest

import frappe

from frappe_webmail.frappe_webmail.doctype.webmail_account.webmail_account import (
	PASSWORD_PROVIDERS,
	WebmailAccount,
)


def _account(**values):
	doc = object.__new__(WebmailAccount)
	doc.flags = frappe._dict()
	defaults = {
		"auth_type": "Password",
		"provider_preset": None,
		"oauth_provider": None,
		"imap_host": None,
		"imap_port": 993,
		"imap_ssl": 1,
		"smtp_host": None,
		"smtp_port": 587,
		"smtp_ssl": 0,
		"smtp_starttls": 1,
	}
	for key, value in {**defaults, **values}.items():
		setattr(doc, key, value)
	return doc


class TestPasswordProviderPreset(unittest.TestCase):
	def test_infomaniak_fills_the_servers_of_a_password_account(self):
		doc = _account(provider_preset="Infomaniak")

		doc.apply_password_provider_settings()

		self.assertEqual(doc.imap_host, "mail.infomaniak.com")
		self.assertEqual((doc.imap_port, doc.imap_ssl), (993, 1))
		self.assertEqual(doc.smtp_host, "mail.infomaniak.com")
		self.assertEqual((doc.smtp_port, doc.smtp_ssl, doc.smtp_starttls), (587, 0, 1))

	def test_the_preset_replaces_servers_typed_before_it_was_chosen(self):
		doc = _account(provider_preset="Infomaniak", imap_host="old.example.com", smtp_host="old.example.com")

		doc.apply_password_provider_settings()

		self.assertEqual((doc.imap_host, doc.smtp_host), ("mail.infomaniak.com", "mail.infomaniak.com"))

	def test_without_a_preset_the_servers_are_left_alone(self):
		doc = _account(imap_host="imap.example.com", smtp_host="smtp.example.com")

		doc.apply_password_provider_settings()

		self.assertEqual((doc.imap_host, doc.smtp_host), ("imap.example.com", "smtp.example.com"))

	def test_an_oauth_account_ignores_a_password_preset(self):
		doc = _account(auth_type="OAuth2", provider_preset="Infomaniak", imap_host="imap.gmail.com")

		doc.apply_password_provider_settings()

		self.assertEqual(doc.imap_host, "imap.gmail.com")

	def test_an_unknown_preset_changes_nothing(self):
		doc = _account(provider_preset="Nobody", imap_host="imap.example.com")

		doc.apply_password_provider_settings()

		self.assertEqual(doc.imap_host, "imap.example.com")

	def test_emailarray_fills_its_servers_with_ssl_on_both(self):
		# The settings the user manual gives for the mailboxes it hosts: 993 and 465, SSL/TLS on both
		doc = _account(provider_preset="EmailArray")

		doc.apply_password_provider_settings()

		self.assertEqual((doc.imap_host, doc.imap_port, doc.imap_ssl), ("imap.emailarray.com", 993, 1))
		self.assertEqual(
			(doc.smtp_host, doc.smtp_port, doc.smtp_ssl, doc.smtp_starttls),
			("smtp.emailarray.com", 465, 1, 0),
		)

	def test_the_smtp_password_left_empty_is_the_imap_one(self):
		"""One password typed once: the same address signs in to both servers at every preset's provider."""
		doc = _account(imap_password="typed once", smtp_password=None)
		doc.validate_auth()
		self.assertEqual(doc.smtp_password, "typed once")
		# One typed for SMTP stays its own
		doc = _account(imap_password="for imap", smtp_password="for smtp")
		doc.validate_auth()
		self.assertEqual(doc.smtp_password, "for smtp")
		# A stored password is shown as asterisks: never copied, and an SMTP one is still asked for
		with self.assertRaises(frappe.ValidationError):
			_account(imap_password="*********", smtp_password=None).validate_auth()
		with self.assertRaises(frappe.ValidationError):
			_account(imap_password=None, smtp_password="for smtp").validate_auth()

	def test_a_port_from_a_link_is_read_as_a_number(self):
		"""A form opened from a link (`/app/webmail-account/new?imap_port=993`) holds its fields as the text of the
		address: the ports are checked and kept as the numbers they are (11.11.2026: such a link made every save a server
		error, `'<' not supported between instances of 'str' and 'int'`)."""
		doc = _account(imap_port="993", smtp_port=" 465 ")
		doc.validate_ports()
		self.assertEqual((doc.imap_port, doc.smtp_port), (993, 465))
		# A port that is no port is refused, typed or from a link
		for wrong in ("99999", "abc", "-1", "0x3e1", 70000):
			with self.assertRaises(frappe.ValidationError):
				_account(imap_port=wrong).validate_ports()
		# An empty one stays empty, as a number typed in the form stays the number it is
		doc = _account(imap_port="", smtp_port=587)
		doc.validate_ports()
		self.assertEqual((doc.imap_port, doc.smtp_port), (None, 587))

	def test_the_presets_are_declared_for_the_form_script_to_mirror(self):
		import json
		import os

		from frappe_webmail.frappe_webmail.doctype import webmail_account

		self.assertIn("Infomaniak", PASSWORD_PROVIDERS)
		self.assertIn("EmailArray", PASSWORD_PROVIDERS)
		folder = os.path.dirname(webmail_account.__file__)
		with open(os.path.join(folder, "webmail_account.json")) as handle:
			field = next(f for f in json.load(handle)["fields"] if f["fieldname"] == "provider_preset")
		# The Select offers every preset, and only them
		self.assertEqual(set(filter(None, field["options"].split("\n"))), set(PASSWORD_PROVIDERS))
		# The form script fills the same servers as the controller
		with open(os.path.join(folder, "webmail_account.js")) as handle:
			script = handle.read()
		for name, settings in PASSWORD_PROVIDERS.items():
			self.assertIn(f"{name}: {{", script)
			for value in (settings["imap_host"], settings["smtp_host"]):
				self.assertIn(f'"{value}"', script)
			self.assertIn(f"smtp_port: {settings['smtp_port']},", script)


if __name__ == "__main__":
	unittest.main()
