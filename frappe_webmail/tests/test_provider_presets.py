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

	def test_the_presets_are_declared_for_the_form_script_to_mirror(self):
		self.assertIn("Infomaniak", PASSWORD_PROVIDERS)


if __name__ == "__main__":
	unittest.main()
