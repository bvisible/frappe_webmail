# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The address headers of a message the webmail sends (webmail_api.sender_header, address_header): each address stays
bare, a name that is not plain ASCII becomes an encoded word. Before (17.11.2026), a sender name with an accent
(« Jérémy Christillin ») made Python encode the whole From, address included, into one encoded word, and Gmail refused the
message: « Messages missing a valid address in From: header » (550 5.7.1).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_address_headers
"""

import email
import email.policy
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import imap_client, mocked_imap
from frappe_webmail.webmail_api import address_header, sender_header


def read(header_value: str, name: str = "From"):
	"""The addresses a reader's program finds in a header written so."""
	parsed = email.message_from_string(f"{name}: {header_value}\n\n", policy=email.policy.default)
	return [(a.display_name, a.addr_spec) for a in parsed[name].addresses]


class TestTheAddressHeaders(FrappeTestCase):
	def test_a_name_with_an_accent_keeps_its_address_readable(self):
		written = sender_header(frappe._dict(sender_name="Jérémy Christillin", email="jeremy@example.org"))
		self.assertTrue(written.endswith(" <jeremy@example.org>"), written)
		self.assertTrue(written.isascii(), written)
		self.assertEqual(read(written), [("Jérémy Christillin", "jeremy@example.org")])

	def test_a_plain_name_and_no_name(self):
		self.assertEqual(
			read(sender_header(frappe._dict(sender_name="Daniel  Moret ", email="d@example.org"))),
			[("Daniel Moret", "d@example.org")],
		)
		self.assertEqual(sender_header(frappe._dict(sender_name="", email="d@example.org")), "d@example.org")

	def test_recipients_as_typed_are_written_each_with_its_address(self):
		written = address_header(
			'André Simone <andre@example.org>, bob@example.com, "Doe, John" <john@example.ch>'
		)
		self.assertTrue(written.isascii(), written)
		self.assertEqual(
			read(written, "To"),
			[
				("André Simone", "andre@example.org"),
				("", "bob@example.com"),
				("Doe, John", "john@example.ch"),
			],
		)
		self.assertEqual(address_header("no address here"), "no address here", "left as it was")
		self.assertEqual(address_header(""), "")


class TestAMessageSentKeepsItsSenderReadable(TestWebmailAPIBase):
	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_the_from_of_a_message_sent_names_its_address(self, smtp_class):
		from frappe_webmail.api import send_email

		frappe.db.set_value("Webmail Account", self.test_account_email, "sender_name", "Jérémy Christillin")
		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()):
			send_email(
				account_name=self.test_account_email,
				to="André Simone <andre@example.org>",
				subject="Essai",
				html_content="<p>Bonjour</p>",
			)
		raw = server.sendmail.call_args.args[2]
		sent = email.message_from_string(raw, policy=email.policy.default)
		self.assertEqual(
			[(a.display_name, a.addr_spec) for a in sent["From"].addresses],
			[("Jérémy Christillin", self.test_account_email)],
		)
		self.assertIn(f"<{self.test_account_email}>", raw, "the address bare in the header")
		self.assertEqual([a.addr_spec for a in sent["To"].addresses], ["andre@example.org"])
