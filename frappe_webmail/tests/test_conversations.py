# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""A message's conversation, read while the message is (« 2 messages plus anciens dans cette conversation »), and a
folder listed by what the person asks: the unread or the followed ones only, the oldest first (the webmail's lot 2,
« retrouver », 14.10.2026).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_conversations
"""

from datetime import datetime
from types import SimpleNamespace

from frappe.tests.utils import FrappeTestCase

from frappe_webmail.conversations import (
	HEADERS,
	HEADERS_KEY,
	conversation_places,
	criteria_for,
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


def envelope(subject, day, sender="marc"):
	return SimpleNamespace(
		subject=subject.encode(),
		date=datetime(2026, 10, day, 9, 0),
		from_=[SimpleNamespace(name=None, mailbox=sender.encode(), host=b"example.com")],
		to=[SimpleNamespace(name=None, mailbox=b"test_account", host=b"webmail.test")],
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
