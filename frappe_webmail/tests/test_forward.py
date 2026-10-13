# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What leaves with a message (send_email): the files the person joined, of their own type and with their accented
names, and the attachments of a forwarded message they kept, read again on the server (plan Neodesk W3).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_forward
"""

import base64
import email
import json
from unittest.mock import MagicMock, patch

from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import PDF, UID, imap_client, mocked_imap


def files_of(server):
	"""(name, type, bytes) of each file of the message the mocked SMTP server was handed."""
	sent = email.message_from_string(server.sendmail.call_args.args[2])
	return [
		(part.get_filename(), part.get_content_type(), part.get_payload(decode=True))
		for part in sent.walk()
		if part.get_content_disposition() == "attachment"
	]


class TestWhatLeavesWithAMessage(TestWebmailAPIBase):
	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_the_kept_attachments_of_a_forwarded_message_go_with_it(self, smtp_class):
		from frappe_webmail.api import send_email

		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()) as client:
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Fwd: Invoice 2026-118",
				html_content="<p>Voici la facture.</p>",
				forward_uid=UID,
				forward_folder="INBOX",
				forward_attachments=json.dumps(["0", "logo@example.com"]),
			)
		files = files_of(server)
		self.assertEqual([name for name, _type, _data in files], ["Relevé 2026-118.pdf", "logo.png"])
		self.assertEqual(files[0][1:], ("application/pdf", PDF))
		self.assertEqual(files[1][1], "image/png")
		# Read without marking it read: EXAMINE, BODY.PEEK
		client.select_folder.assert_any_call("INBOX", readonly=True)
		self.assertIn((([UID], ["BODY.PEEK[]"]),), [(call.args,) for call in client.fetch.call_args_list])

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_a_joined_file_keeps_its_type_and_its_accented_name(self, smtp_class):
		from frappe_webmail.api import send_email

		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()):
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Devis",
				html_content="<p>Le devis.</p>",
				attachments=json.dumps(
					[
						{
							"filename": "Devis été.pdf",
							"data": base64.b64encode(PDF).decode(),
							"content_type": "application/pdf",
						}
					]
				),
			)
		self.assertEqual(files_of(server), [("Devis été.pdf", "application/pdf", PDF)])

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_without_a_forwarded_message_nothing_is_read_again(self, smtp_class):
		from frappe_webmail.api import send_email

		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()) as client:
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Bonjour",
				html_content="<p>Bonjour.</p>",
				forward_attachments=json.dumps(["0"]),
			)
		self.assertEqual(files_of(server), [])
		self.assertNotIn((([UID], ["BODY.PEEK[]"]),), [(call.args,) for call in client.fetch.call_args_list])
