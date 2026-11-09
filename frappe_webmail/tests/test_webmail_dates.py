# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The date of a message says its zone (neoffice-maintenance#1599).

imapclient hands an ENVELOPE date over naive, in the local time of the server process, and the fleet runs in UTC.
A browser or a phone reads a zone-less ISO text as its own local time: a message received at 10:34 in Switzerland in
summer was shown at 08:34. The lists, the opened message and the search now give the date with its offset.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_webmail_dates
"""

import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import UID, imap_client, mocked_imap
from frappe_webmail.webmail_api import _iso_with_zone, _summary, get_emails, search_emails

# What imapclient gives for a message received at 10:34:21 Swiss summer time on a server running in UTC
RECEIVED = datetime(2026, 10, 15, 8, 34, 21)


@contextmanager
def process_zone(name):
	"""The time zone of this process, as the server's would be."""
	old = os.environ.get("TZ")
	os.environ["TZ"] = name
	time.tzset()
	try:
		yield
	finally:
		if old is None:
			os.environ.pop("TZ", None)
		else:
			os.environ["TZ"] = old
		time.tzset()


def envelope(date):
	return SimpleNamespace(
		subject=b"Devis chaudiere",
		date=date,
		from_=[SimpleNamespace(name=b"Marc", mailbox=b"marc", host=b"example.com")],
		to=[SimpleNamespace(name=None, mailbox=b"test_account", host=b"webmail.test")],
		cc=None,
		reply_to=None,
	)


def listing_client(date):
	"""A mailbox holding one message, as a list or a search finds it."""
	client = MagicMock()
	client.search.return_value = [7]
	client.fetch.side_effect = lambda uids, items: {
		uid: {b"ENVELOPE": envelope(date), b"FLAGS": (b"\\Seen",)} for uid in uids
	}
	return client


class TestADateSaysItsZone(FrappeTestCase):
	def test_a_naive_date_gets_the_zone_of_the_process(self):
		with process_zone("UTC"):
			self.assertEqual(_iso_with_zone(RECEIVED), "2026-10-15T08:34:21+00:00")
		with process_zone("Europe/Zurich"):
			self.assertEqual(_iso_with_zone(datetime(2026, 10, 15, 10, 34, 21)), "2026-10-15T10:34:21+02:00")

	def test_a_date_that_has_a_zone_is_left_as_it_is(self):
		two_hours_ahead = datetime(2026, 10, 15, 10, 34, 21, tzinfo=timezone(timedelta(hours=2)))
		with process_zone("UTC"):
			self.assertEqual(_iso_with_zone(two_hours_ahead), "2026-10-15T10:34:21+02:00")

	def test_no_date_stays_no_date(self):
		self.assertIsNone(_iso_with_zone(None))

	def test_the_dates_of_a_list_sort_in_time_order_as_text(self):
		with process_zone("UTC"):
			dates = [_iso_with_zone(datetime(2026, 10, day, 9, 0)) for day in (14, 9, 12)]
		self.assertEqual(sorted(dates), [dates[1], dates[2], dates[0]])

	def test_a_row_of_a_list_carries_it(self):
		with process_zone("UTC"):
			row = _summary(1, {b"ENVELOPE": envelope(RECEIVED), b"FLAGS": ()}, {})
			dateless = _summary(2, {b"ENVELOPE": envelope(None), b"FLAGS": ()}, {})
		self.assertEqual(row["date"], "2026-10-15T08:34:21+00:00")
		self.assertIsNone(dateless["date"])


class TestEveryDoorGivesTheZone(TestWebmailAPIBase):
	def test_the_list_of_a_folder(self):
		with process_zone("UTC"), mocked_imap(listing_client(RECEIVED)):
			with patch("frappe_webmail.webmail_api._list_previews", return_value={}):
				listed = get_emails(self.test_account_email, folder="INBOX")
		self.assertEqual(listed["emails"][0]["date"], "2026-10-15T08:34:21+00:00")

	def test_the_search(self):
		with process_zone("UTC"), mocked_imap(listing_client(RECEIVED)):
			found = search_emails(self.test_account_email, folder="INBOX", query="chaudiere")
		self.assertEqual(found["emails"][0]["date"], "2026-10-15T08:34:21+00:00")

	def test_the_message_opened(self):
		from frappe_webmail.api import get_email_content

		with process_zone("UTC"), mocked_imap(imap_client()):
			# the fixture's message was received at 10:42 on 13 October
			message = get_email_content(self.test_account_email, UID, "INBOX", mark_read=False)
		self.assertEqual(message["date"], "2026-10-13T10:42:00+00:00")
