# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
An accented word can be searched.

IMAPClient encodes the text of a SEARCH as US-ASCII unless it is given a charset, so "démonstration"
raised UnicodeEncodeError in the webmail search box and in every search NORA runs for a
French-speaking person. The criteria now name UTF-8 as soon as one of them needs it, and an
all-ASCII search is sent as before.

IMAPClient 3.x also drops the charset inside a nested criteria list, so a mock of `search()` would
have let a half fix through. The tests below therefore run the real `IMAPClient.search` over a
connection that only records what it would send, and check the words that reach the wire.

Run with:
    bench --site [sitename] run-tests --app frappe_webmail --module frappe_webmail.tests.test_search_accents
"""

import unittest
from unittest.mock import MagicMock, patch

from imapclient import IMAPClient

from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.webmail_api import _search_charset, get_emails, search_emails

WORD = "démonstration"


class _Wire(IMAPClient):
	"""The real IMAPClient.search, with no socket: what it would send is kept in `sent`."""

	def __init__(self):
		self.sent = []

	def _raw_command_untagged(self, command, args, **kwargs):
		self.sent.append((command, list(args)))
		return [b""]


class TestSearchCharset(unittest.TestCase):
	def test_ascii_criteria_need_no_charset(self):
		self.assertIsNone(_search_charset(["NOT", "DELETED"]))
		self.assertIsNone(_search_charset(["OR", "OR", "SUBJECT", "invoice", "FROM", "invoice"]))

	def test_an_accented_word_asks_for_utf8(self):
		self.assertEqual(_search_charset(["SUBJECT", WORD]), "UTF-8")

	def test_the_accent_is_found_whatever_the_nesting(self):
		criteria = ["OR", ["OR", ["SUBJECT", "Müller"], ["FROM", "Müller"]], ["TO", "Müller"]]
		self.assertEqual(_search_charset(criteria), "UTF-8")
		self.assertEqual(_search_charset(("TEXT", "café")), "UTF-8")

	def test_what_is_not_text_is_ignored(self):
		self.assertIsNone(_search_charset(["SINCE", "12-Oct-2026"]))
		self.assertIsNone(_search_charset([5, ["UID", 7]]))
		self.assertIsNone(_search_charset(None))


class TestAccentedSearchReachesTheWire(TestWebmailAPIBase):
	"""Whichever door the words come through, the library accepts them and sends them as UTF-8."""

	def _search(self, call, **kwargs):
		wire = _Wire()
		client = MagicMock()
		client.search.side_effect = wire.search
		with patch("frappe_webmail.webmail_api.IMAPClient") as imap_class:
			imap_class.return_value.__enter__ = MagicMock(return_value=client)
			imap_class.return_value.__exit__ = MagicMock(return_value=False)
			call(self.test_account_email, **kwargs)
		self.assertEqual(len(wire.sent), 1, wire.sent)
		command, args = wire.sent[0]
		self.assertEqual(command, b"SEARCH")
		return args

	def test_search_emails_sends_the_accented_query_as_utf8(self):
		args = self._search(search_emails, query=WORD)
		word = WORD.encode("utf-8")
		self.assertEqual(
			args,
			[b"CHARSET", b"UTF-8", b"OR", b"OR", b"SUBJECT", word, b"FROM", word, b"TO", word],
		)

	def test_search_emails_sends_an_accent_in_a_field_filter_and_keeps_the_other_criteria(self):
		args = self._search(search_emails, subject_filter="Réunion", from_filter="Müller", is_unread=True)
		self.assertEqual(args[:2], [b"CHARSET", b"UTF-8"])
		self.assertIn("Réunion".encode(), args)
		self.assertIn("Müller".encode(), args)
		self.assertEqual(args[-1], b"UNSEEN")

	def test_search_emails_sends_a_phrase_with_an_accent_and_a_space_whole(self):
		args = self._search(search_emails, query="réunion client")
		# a quoted word keeps the text it was made from; IMAPClient sends that text as a literal when it is 8-bit
		texts = [getattr(arg, "original", arg) for arg in args]
		self.assertEqual(texts.count("réunion client".encode()), 3, args)

	def test_search_emails_with_plain_ascii_names_no_charset(self):
		args = self._search(search_emails, query="invoice", is_unread=True)
		self.assertNotIn(b"CHARSET", args)
		self.assertEqual(
			args, [b"OR", b"OR", b"SUBJECT", b"invoice", b"FROM", b"invoice", b"TO", b"invoice", b"UNSEEN"]
		)

	def test_get_emails_sends_the_accented_search_as_utf8(self):
		args = self._search(get_emails, search=WORD)
		word = WORD.encode("utf-8")
		self.assertEqual(
			args,
			[b"CHARSET", b"UTF-8", b"OR", b"OR", b"SUBJECT", word, b"FROM", word, b"TO", word],
		)

	def test_get_emails_without_a_search_names_no_charset(self):
		args = self._search(get_emails)
		self.assertEqual(args, [b"NOT", b"DELETED"])
