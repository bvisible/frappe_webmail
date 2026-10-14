# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""A message's conversation, read while the message is (« 2 messages plus anciens dans cette conversation »), and a
folder listed by what the person asks: the unread or the followed ones only, the oldest first (the webmail's lot 2,
« retrouver », 14.10.2026). A message sent to oneself is one message of its conversation, though it sits in two
folders; an answer carries the whole chain of the message it answers, its date and its Message-ID.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_conversations
"""

import email
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from frappe_webmail.conversations import (
	HEADERS,
	HEADERS_KEY,
	MAX_CHAIN,
	conversation_places,
	criteria_for,
	one_per_message,
	references_for,
	sent_folder,
	thread_ids,
)
from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import mocked_imap

FOLDERS = [
	((b"\\HasNoChildren",), b"/", "INBOX"),
	((b"\\HasNoChildren", b"\\Sent"), b"/", "Envoyés"),
	((b"\\HasNoChildren",), b"/", "Archives"),
]


def envelope(subject, day, sender="marc", message_id=None):
	return SimpleNamespace(
		subject=subject.encode(),
		date=datetime(2026, 10, day, 9, 0),
		from_=[SimpleNamespace(name=None, mailbox=sender.encode(), host=b"example.com")],
		to=[SimpleNamespace(name=None, mailbox=b"test_account", host=b"webmail.test")],
		message_id=message_id.encode() if message_id else None,
	)


class FakeMailbox:
	"""A mailbox with folders: what `fetch` and `search` answer depends on the folder selected."""

	def __init__(self, headers, found, envelopes, folders=FOLDERS):
		self.headers = headers  # {uid: raw headers} of the message whose conversation is asked
		self.found = found  # {folder: [uids]} a search finds there
		self.envelopes = envelopes  # {(folder, uid): envelope}
		self.folders = folders
		self.selected = None
		self.searched = []
		self.readonly = []
		self.appended = []

	def __getattr__(self, name):
		# login, logout, noop…: nothing to do in a fake mailbox
		return lambda *args, **kwargs: None

	def select_folder(self, name, readonly=False):
		self.selected = name
		self.readonly.append(readonly)

	def list_folders(self):
		return self.folders

	def fetch(self, uids, items):
		if items == [HEADERS]:
			return {u: {HEADERS_KEY: self.headers[u]} for u in uids if u in self.headers}
		return {
			u: {b"ENVELOPE": self.envelopes[(self.selected, u)], b"FLAGS": (b"\\Seen",)}
			for u in uids
			if (self.selected, u) in self.envelopes
		}

	def search(self, criteria, charset=None):
		self.searched.append((self.selected, criteria))
		return list(self.found.get(self.selected, []))

	def append(self, folder, data, flags=None, msg_time=None):
		self.appended.append((folder, data))


HEADERS_OF_5 = (
	b"Message-ID: <five@example.com>\r\n"
	b"In-Reply-To: <two@example.com>\r\n"
	b"References: <one@example.com>\r\n <two@example.com>\r\n\r\n"
)


class TestWhatTiesAConversation(FrappeTestCase):
	def test_a_message_names_itself_and_what_it_answers_newest_last_each_once(self):
		self.assertEqual(
			thread_ids(HEADERS_OF_5), ("<five@example.com>", ["<one@example.com>", "<two@example.com>"])
		)
		self.assertEqual(thread_ids(b""), (None, []))

	def test_the_search_asks_for_what_it_answers_and_what_answers_it(self):
		criteria = criteria_for("<five@example.com>", ["<one@example.com>"])
		self.assertEqual(
			criteria,
			[
				"OR",
				["HEADER", "Message-ID", "<one@example.com>"],
				[
					"OR",
					["HEADER", "References", "<five@example.com>"],
					["HEADER", "In-Reply-To", "<five@example.com>"],
				],
			],
		)
		self.assertIsNone(criteria_for(None, []))

	def test_the_sent_folder_is_the_one_marked_sent_else_one_of_the_usual_names(self):
		self.assertEqual(sent_folder(FOLDERS), "Envoyés")
		self.assertEqual(sent_folder([((), b"/", "INBOX"), ((), b"/", "Sent Items")]), "Sent Items")
		self.assertIsNone(sent_folder([((), b"/", "INBOX")]))


class TestAConversationRead(TestWebmailAPIBase):
	def mailbox(self):
		return FakeMailbox(
			headers={5: HEADERS_OF_5},
			found={"INBOX": [3, 5, 9], "Envoyés": [2]},
			envelopes={
				("INBOX", 3): envelope("Devis chaudière", 10),
				("INBOX", 9): envelope("Re: Re: Devis chaudière", 14),
				("Envoyés", 2): envelope("Re: Devis chaudière", 12, sender="test_account"),
			},
		)

	def test_the_other_messages_of_the_inbox_and_the_sent_the_message_left_out(self):
		client = self.mailbox()
		self.assertEqual(
			conversation_places(client, "INBOX", 5), [("INBOX", 3), ("INBOX", 9), ("Envoyés", 2)]
		)
		# Read only, everywhere
		self.assertTrue(all(client.readonly))

	def test_they_come_oldest_first_each_with_its_folder(self):
		from frappe_webmail.api import get_conversation

		with mocked_imap(self.mailbox()):
			answer = get_conversation(self.test_account_email, "INBOX", 5)
		self.assertEqual(
			[(m["folder"], m["uid"], m["subject"]) for m in answer["messages"]],
			[
				("INBOX", 3, "Devis chaudière"),
				("Envoyés", 2, "Re: Devis chaudière"),
				("INBOX", 9, "Re: Re: Devis chaudière"),
			],
		)

	def test_a_message_tied_to_none_has_no_conversation(self):
		from frappe_webmail.api import get_conversation

		client = FakeMailbox(headers={7: b"Subject: Seul\r\n\r\n"}, found={}, envelopes={})
		with mocked_imap(client):
			self.assertEqual(get_conversation(self.test_account_email, "INBOX", 7), {"messages": []})
		self.assertEqual(client.searched, [])


class TestAFolderListedAsAsked(TestWebmailAPIBase):
	def mailbox(self):
		return FakeMailbox(
			headers={},
			found={"INBOX": [11, 12, 13]},
			envelopes={("INBOX", uid): envelope(f"Message {uid}", uid - 10) for uid in (11, 12, 13)},
		)

	def test_the_followed_or_the_unread_only_are_asked_of_the_server(self):
		from frappe_webmail.api import get_emails

		client = self.mailbox()
		with mocked_imap(client):
			get_emails(self.test_account_email, "INBOX", only="flagged")
			get_emails(self.test_account_email, "INBOX", only="unread")
		self.assertEqual(client.searched[0][1][-1], "FLAGGED")
		self.assertEqual(client.searched[1][1][-1], "UNSEEN")

	def test_the_oldest_first_when_asked_the_newest_otherwise(self):
		from frappe_webmail.api import get_emails

		with mocked_imap(self.mailbox()):
			newest = get_emails(self.test_account_email, "INBOX")
			oldest = get_emails(self.test_account_email, "INBOX", order="oldest")
		self.assertEqual([m["uid"] for m in newest["emails"]], [13, 12, 11])
		self.assertEqual([m["uid"] for m in oldest["emails"]], [11, 12, 13])


class TestAMessageInTwoFolders(TestWebmailAPIBase):
	def test_a_message_sent_to_oneself_is_one_message_of_its_conversation(self):
		from frappe_webmail.api import get_conversation

		client = FakeMailbox(
			headers={5: HEADERS_OF_5},
			found={"INBOX": [3, 5], "Envoyés": [2, 4]},
			envelopes={
				("INBOX", 3): envelope("Devis chaudière", 10, message_id="<one@example.com>"),
				# The same message sent to oneself, its copy in « Envoyés »
				("Envoyés", 2): envelope(
					"Devis chaudière", 10, sender="test_account", message_id="<one@example.com>"
				),
				# The message read itself, its copy in « Envoyés »
				("Envoyés", 4): envelope(
					"Re: Devis chaudière", 12, sender="test_account", message_id="<five@example.com>"
				),
			},
		)
		with mocked_imap(client):
			answer = get_conversation(self.test_account_email, "INBOX", 5)
		self.assertEqual([(m["folder"], m["uid"]) for m in answer["messages"]], [("INBOX", 3)])

	def test_the_copy_kept_is_the_folder_reads_then_the_inboxs(self):
		found = [
			("<a@example.com>", {"folder": "Envoyés", "uid": 2}),
			("<a@example.com>", {"folder": "INBOX", "uid": 3}),
			(None, {"folder": "Archives", "uid": 9}),
			("<own@example.com>", {"folder": "INBOX", "uid": 7}),
		]
		self.assertEqual(
			one_per_message(found, "<own@example.com>", "INBOX"),
			[{"folder": "INBOX", "uid": 3}, {"folder": "Archives", "uid": 9}],
		)
		self.assertEqual(
			one_per_message(found, "<own@example.com>", "Envoyés")[0], {"folder": "Envoyés", "uid": 2}
		)


class TestAnAnswerKeepsItsConversation(TestWebmailAPIBase):
	def test_an_answer_names_the_whole_chain_of_the_message_it_answers(self):
		client = FakeMailbox(headers={5: HEADERS_OF_5}, found={}, envelopes={})
		self.assertEqual(
			references_for(client, "INBOX", 5, "<five@example.com>"),
			"<one@example.com> <two@example.com> <five@example.com>",
		)
		# Without References, its In-Reply-To; a message that cannot be read, the message answered alone
		client = FakeMailbox(
			headers={6: b"Message-ID: <six@example.com>\r\nIn-Reply-To: <two@example.com>\r\n\r\n"},
			found={},
			envelopes={},
		)
		self.assertEqual(
			references_for(client, "INBOX", 6, "<six@example.com>"), "<two@example.com> <six@example.com>"
		)
		empty = FakeMailbox(headers={}, found={}, envelopes={})
		self.assertEqual(references_for(empty, "INBOX", 8, "<eight@example.com>"), "<eight@example.com>")

	def test_a_long_chain_keeps_its_start_and_its_newest(self):
		chain = " ".join(f"<m{i}@example.com>" for i in range(40))
		client = FakeMailbox(
			headers={9: f"Message-ID: <answered@example.com>\r\nReferences: {chain}\r\n\r\n".encode()},
			found={},
			envelopes={},
		)
		kept = references_for(client, "INBOX", 9, "<answered@example.com>").split()
		self.assertEqual(len(kept), MAX_CHAIN)
		self.assertEqual(kept[0], "<m0@example.com>")
		self.assertEqual(kept[-2:], ["<m39@example.com>", "<answered@example.com>"])

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_a_message_sent_carries_its_date_its_id_and_the_chain(self, smtp_class):
		from frappe_webmail.api import send_email

		server = MagicMock()
		smtp_class.return_value = server
		client = FakeMailbox(headers={5: HEADERS_OF_5}, found={}, envelopes={})
		with mocked_imap(client):
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Re: Devis chaudière",
				html_content="<p>Le mardi 27 nous convient.</p>",
				reply_to_message_id="<five@example.com>",
				reply_to_uid=5,
				reply_to_folder="INBOX",
			)
		sent = email.message_from_string(server.sendmail.call_args.args[2])
		self.assertEqual(sent["In-Reply-To"], "<five@example.com>")
		self.assertEqual(
			" ".join(sent["References"].split()), "<one@example.com> <two@example.com> <five@example.com>"
		)
		self.assertTrue(sent["Date"])
		self.assertRegex(sent["Message-ID"], r"^<.+@.+>$")
		# The copy kept in « Envoyés » is the same message: its answers find it by its Message-ID
		folder, copy = client.appended[-1]
		self.assertEqual(folder, "Envoyés")
		self.assertEqual(email.message_from_bytes(copy)["Message-ID"], sent["Message-ID"])
