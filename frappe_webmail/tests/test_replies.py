# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Who an answer goes to, and drafts that save themselves while the person writes (the webmail made complete, 14.10.2026).

Reply all answered the sender alone in the desk (its flag was never read) and was missing from the desktop app; a draft
saved again became one more draft each time, because the server never said which UID the last copy got.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_replies
"""

import email
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from frappe_webmail.replies import addresses, appended_uid, reply_recipients
from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import UID, imap_client, mocked_imap

OWN = "test_account@webmail.test"


class TestWhoAnAnswerGoesTo(FrappeTestCase):
	def test_reply_goes_to_the_reply_to_else_the_sender(self):
		self.assertEqual(reply_recipients(OWN, "marc@example.com")["to"], "marc@example.com")
		self.assertEqual(
			reply_recipients(OWN, "noreply@shop.example", reply_to="orders@shop.example")["to"],
			"orders@shop.example",
		)
		self.assertEqual(reply_recipients(OWN, "marc@example.com", to=f"{OWN}, lea@example.com")["cc"], "")

	def test_reply_all_adds_everyone_else_never_the_mailbox_nor_anyone_twice(self):
		answer = reply_recipients(
			OWN,
			"Marc Rey <marc@example.com>",
			to=f"{OWN.upper()}, lea@example.com, Marc@Example.com",
			cc=f"info@example.com, lea@example.com, {OWN}",
			reply_all=True,
		)
		self.assertEqual(answer, {"to": "marc@example.com, lea@example.com", "cc": "info@example.com"})

	def test_ones_own_sent_message_is_answered_to_whom_it_went(self):
		self.assertEqual(reply_recipients(OWN, OWN, to="marc@example.com")["to"], "marc@example.com")
		answer = reply_recipients(
			OWN, OWN, to="marc@example.com, lea@example.com", cc="info@example.com", reply_all=True
		)
		self.assertEqual(answer, {"to": "marc@example.com, lea@example.com", "cc": "info@example.com"})

	def test_addresses_are_read_from_header_fields(self):
		self.assertEqual(
			addresses(
				"Marc Rey <marc@example.com>, lea@example.com", None, "not an address, MARC@example.com"
			),
			["marc@example.com", "lea@example.com"],
		)

	def test_the_uid_of_an_appended_draft(self):
		self.assertEqual(appended_uid(b"[APPENDUID 1695 77] Append completed."), 77)
		self.assertEqual(appended_uid("[APPENDUID 1 9] APPEND completed"), 9)
		self.assertIsNone(appended_uid(b"APPEND completed"))
		self.assertIsNone(appended_uid(None))


def drafts_client(append_response=b"[APPENDUID 1 77] Append completed."):
	client = imap_client()
	client.list_folders.return_value = [
		((b"\\HasNoChildren",), b"/", "INBOX"),
		((b"\\HasNoChildren", b"\\Drafts"), b"/", "Drafts"),
	]
	client.append.return_value = append_response
	return client


class TestAnswersAndDrafts(TestWebmailAPIBase):
	def test_a_message_comes_with_the_recipients_of_its_answers(self):
		from frappe_webmail.api import get_email_content

		client = imap_client()
		# The fake serves one envelope object: what it says is changed in place
		envelope = client.fetch.side_effect([UID], ["ENVELOPE"])[UID][b"ENVELOPE"]
		envelope.to = [
			SimpleNamespace(name=None, mailbox=b"test_account", host=b"webmail.test"),
			SimpleNamespace(name=None, mailbox=b"lea", host=b"example.com"),
		]
		envelope.cc = [SimpleNamespace(name=None, mailbox=b"info", host=b"example.com")]
		with mocked_imap(client):
			message = get_email_content(self.test_account_email, UID, "INBOX", mark_read=False)
		self.assertEqual(message["reply"], {"to": "supplier@example.com", "cc": ""})
		self.assertEqual(
			message["reply_all"], {"to": "supplier@example.com, lea@example.com", "cc": "info@example.com"}
		)

	def test_a_draft_saved_again_replaces_itself_and_says_its_uid(self):
		from frappe_webmail.api import save_draft_imap

		with mocked_imap(drafts_client()) as client:
			result = save_draft_imap(
				self.test_account_email,
				to="marc@example.com",
				bcc="archive@example.com",
				subject="Re: Devis",
				html_content="<p>Bonjour</p>",
				reply_to_message_id="<abc@example.com>",
				attachments='[{"filename": "plan.pdf", "content_type": "application/pdf", "data": "JVBERi0="}]',
				draft_uid=12,
				draft_folder="Drafts",
			)
		self.assertEqual((result["uid"], result["folder"]), (77, "Drafts"))
		# The new copy first, then the old one deleted: a failure never loses the text
		calls = [c[0] for c in client.mock_calls]
		self.assertLess(calls.index("append"), calls.index("delete_messages"))
		client.delete_messages.assert_called_once_with([12])
		saved = email.message_from_bytes(client.append.call_args.args[1])
		self.assertEqual(saved["Bcc"], "archive@example.com")
		self.assertEqual(saved["In-Reply-To"], "<abc@example.com>")
		self.assertTrue(saved["Message-ID"])
		self.assertEqual(
			[p.get_filename() for p in saved.walk() if p.get_content_disposition() == "attachment"],
			["plan.pdf"],
		)

	def test_without_appenduid_the_draft_is_found_by_its_message_id(self):
		from frappe_webmail.api import save_draft_imap

		client = drafts_client(append_response=b"APPEND completed")
		client.search.return_value = [80, 81]
		with mocked_imap(client):
			result = save_draft_imap(self.test_account_email, to="marc@example.com", html_content="<p>x</p>")
		self.assertEqual(result["uid"], 81)
		self.assertEqual(client.search.call_args.args[0][:2], ["HEADER", "Message-ID"])
		client.delete_messages.assert_not_called()

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_a_sent_message_takes_its_draft_with_it(self, smtp_class):
		from frappe_webmail.api import send_email

		smtp_class.return_value = MagicMock()
		with mocked_imap(drafts_client()) as client:
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Re: Devis",
				html_content="<p>Bonjour</p>",
				draft_uid=77,
				draft_folder="Drafts",
			)
		client.delete_messages.assert_any_call([77])
