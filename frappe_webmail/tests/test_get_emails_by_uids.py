# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt
"""get_emails reads the messages a client names by their UIDs, and says the folder's UIDVALIDITY.

The phone's Mail tab lists « Prioritaire » from Nora's sorting, which names messages by their place (folder,
UIDVALIDITY, UID): it asks the rows of those UIDs, whatever their rank in the folder, and needs the folder's
UIDVALIDITY to name a message back."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.webmail_api import _listed_uids, _validity_of, get_emails


def _envelope(subject):
	envelope = MagicMock()
	envelope.subject = subject.encode()
	envelope.date = datetime(2026, 11, 16, 9, 30)
	sender = MagicMock(mailbox=b"sender", host=b"example.com")
	sender.name = b"Sender"
	envelope.from_ = [sender]
	envelope.to = [MagicMock(mailbox=b"me", host=b"example.com")]
	return envelope


class TestListedUids(TestWebmailAPIBase):
	def test_nothing_asked_is_none(self):
		self.assertIsNone(_listed_uids(None))
		self.assertIsNone(_listed_uids(""))

	def test_a_json_list_or_numbers_separated_by_commas(self):
		self.assertEqual(_listed_uids("[3, 7]"), {3, 7})
		self.assertEqual(_listed_uids("3,7, 9"), {3, 7, 9})
		self.assertEqual(_listed_uids([4, "5"]), {4, 5})

	def test_what_is_not_a_uid_is_left_out(self):
		self.assertEqual(_listed_uids('[0, -2, "x", 8]'), {8})

	def test_more_than_a_hundred_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_listed_uids(list(range(1, 102)))

	def test_the_validity_of_a_selected_folder(self):
		self.assertEqual(_validity_of({b"UIDVALIDITY": 1723456789, b"EXISTS": 4}), 1723456789)
		self.assertIsNone(_validity_of({b"EXISTS": 4}))
		self.assertIsNone(_validity_of(None))


class TestGetEmailsByUids(TestWebmailAPIBase):
	def _list(self, found, fetched, **kwargs):
		client = MagicMock()
		client.select_folder.return_value = {b"UIDVALIDITY": 42, b"EXISTS": len(found)}
		client.search.return_value = found
		client.fetch.side_effect = lambda page, _parts: {
			uid: {
				b"ENVELOPE": _envelope(f"Message {uid}"),
				b"FLAGS": [],
				b"BODYSTRUCTURE": None,
				b"RFC822.SIZE": 100 + uid,
			}
			for uid in page
			if uid in fetched
		}
		with (
			patch("frappe_webmail.webmail_api.IMAPClient") as imap_class,
			patch("frappe_webmail.webmail_api._list_previews", return_value={}),
		):
			imap_class.return_value.__enter__ = MagicMock(return_value=client)
			imap_class.return_value.__exit__ = MagicMock(return_value=False)
			return get_emails(self.test_account_email, folder="INBOX", **kwargs), client

	def test_only_the_messages_named_are_listed_newest_first(self):
		listed, client = self._list(list(range(1, 201)), set(range(1, 201)), uids="[5, 150, 3]")
		self.assertEqual([e["uid"] for e in listed["emails"]], [150, 5, 3])
		self.assertEqual(listed["total"], 3)
		self.assertFalse(listed["has_more"])
		# The UIDs are never sent as a search criterion of their own
		self.assertEqual(client.search.call_args[0][0], ["NOT", "DELETED"])

	def test_a_message_no_longer_in_the_folder_is_simply_not_listed(self):
		listed, _client = self._list([1, 2, 4], {1, 2, 4}, uids="2,3")
		self.assertEqual([e["uid"] for e in listed["emails"]], [2])

	def test_the_answer_says_the_folders_uidvalidity(self):
		listed, _client = self._list([1, 2], {1, 2})
		self.assertEqual(listed["uidvalidity"], 42)
		empty, _client = self._list([1, 2], {1, 2}, uids="[9]")
		self.assertEqual((empty["emails"], empty["uidvalidity"]), ([], 42))

	def test_without_uids_the_list_is_as_before(self):
		listed, _client = self._list(list(range(1, 61)), set(range(1, 61)), limit=50)
		self.assertEqual(len(listed["emails"]), 50)
		self.assertEqual(listed["emails"][0]["uid"], 60)
		self.assertTrue(listed["has_more"])
