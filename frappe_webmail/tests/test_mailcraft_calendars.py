# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The person's calendars as NeoMail's (mailcraft_calendars, JMAP for Calendars; maintenance#1630, step 3).

Read on the calendar the Suite keeps in the instance for a person without a mailbox server account (the clone's
mailboxes have no password, so their calendars cannot be reached): its events of a window, each occurrence apart, with
their start and end in UTC worked out from their zone, summer time included. Only the person's own calendar, chosen
by the facade; read-only.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_calendars
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_calendars as calendars
from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail.tests.test_mailcraft_contacts import _mailbox, _user

PERSON = "mailcraft_calendars_person@example.com"  # of the desk, a calendar kept in the instance
NOBODY = "mailcraft_calendars_nobody@example.com"  # of the desk, no calendar at all
BOX = "mailcraft_calendars_box@webmail.test"
NOBODY_BOX = "mailcraft_calendars_nobody@webmail.test"
JANUARY = {"after": "2030-01-01T00:00:00Z", "before": "2030-02-01T00:00:00Z"}
JULY = {"after": "2030-07-01T00:00:00Z", "before": "2030-08-01T00:00:00Z"}


@unittest.skipUnless("suite" in frappe.get_installed_apps(), "the calendars are the Suite's")
class TestMailCraftCalendars(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from suite.calendar.jmap_events import create_events
		from suite.calendar.local import get_local_account
		from suite.mail.jmap import get_account_client

		frappe.set_user("Administrator")
		_user(PERSON, ["Sales User"])
		_user(NOBODY, ["Sales User"])
		_mailbox(BOX, PERSON)
		_mailbox(NOBODY_BOX, NOBODY)
		cls.account = get_local_account(PERSON, create=True)
		frappe.set_user(PERSON)
		client = get_account_client(cls.account)
		row = {"time_zone": "Europe/Zurich", "show_without_time": False}
		create_events(
			client,
			cls.account,
			[
				{
					**row,
					"creation_id": "weekly",
					"uid": "mc-cal-weekly",
					"title": "Point chantier",
					"start": "2030-01-14T09:00:00",
					"duration": "PT1H30M",
					"recurrence_rule": {"@type": "RecurrenceRule", "frequency": "weekly", "count": 3},
				},
				{
					**row,
					"creation_id": "summer",
					"uid": "mc-cal-summer",
					"title": "Été",
					"start": "2030-07-15T09:00:00",
					"duration": "PT1H",
				},
				{
					"creation_id": "day",
					"uid": "mc-cal-day",
					"title": "Fermeture",
					"start": "2030-01-20T00:00:00",
					"duration": "P1D",
					"show_without_time": True,
				},
				# The night summer time ends (27.10.2030 at 03:00, back to 02:00): three hours as they pass.
				{
					**row,
					"creation_id": "dst",
					"uid": "mc-cal-dst",
					"title": "Nuit",
					"start": "2030-10-27T01:00:00",
					"duration": "PT3H",
				},
			],
		)
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for doctype in ("Local Calendar Event", "Local Calendar"):
			for name in frappe.get_all(doctype, filters={"account": cls.account}, pluck="name"):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.delete_doc("Local Calendar Account", cls.account, ignore_permissions=True, force=True)
		frappe.db.commit()  # nosemgrep: what the Suite's calendar committed goes too
		super().tearDownClass()

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"mailcraft_trial": 1})
		self.trial.start()

	def tearDown(self):
		self.trial.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.set_user("Administrator")

	def _as(self, user):
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = user
		frappe.local.request_cache.clear() if hasattr(frappe.local, "request_cache") else None

	def _calls(self, *calls):
		body = json.dumps(
			{
				"using": [jmap.CORE, calendars.CALENDARS],
				"methodCalls": [[name, args, f"c{n}"] for n, (name, args) in enumerate(calls)],
			}
		).encode()
		with patch.object(frappe.local, "request", SimpleNamespace(get_data=lambda: body), create=True):
			answer = jmap.api()
		self.assertEqual(answer.status_code, 200, answer.get_data())
		return json.loads(answer.get_data())["methodResponses"]

	def _window(self, window):
		aid = jmap.account_id(BOX)
		query, got = self._calls(
			("CalendarEvent/query", {"accountId": aid, "filter": window, "expandRecurrences": True}),
			(
				"CalendarEvent/get",
				{"accountId": aid, "#ids": {"resultOf": "c0", "name": "CalendarEvent/query", "path": "/ids"}},
			),
		)
		self.assertEqual(query[0], "CalendarEvent/query", query)
		return got[1]["list"]

	def test_the_persons_own_mailbox_offers_the_calendars(self):
		self._as(PERSON)
		aid = jmap.account_id(BOX)
		session = json.loads(jmap.session(BOX).get_data())
		self.assertIn(calendars.CALENDARS, session["capabilities"])
		self.assertEqual(session["primaryAccounts"][calendars.CALENDARS], aid)
		listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
		self.assertTrue(listed and all(c["id"].startswith("C") for c in listed))
		self.assertFalse(listed[0]["myRights"]["mayWriteOwn"], "read-only")

	def test_without_a_calendar_none_is_offered(self):
		self._as(NOBODY)
		session = json.loads(jmap.session(NOBODY_BOX).get_data())
		self.assertNotIn(calendars.CALENDARS, session["capabilities"])
		refused = self._calls(("Calendar/get", {"accountId": jmap.account_id(NOBODY_BOX), "ids": None}))[0]
		self.assertEqual((refused[0], refused[1]["type"]), ("error", "accountNotSupportedByMethod"))

	def test_each_occurrence_comes_apart_with_its_utc_times(self):
		self._as(PERSON)
		events = self._window(JANUARY)
		weekly = sorted((e for e in events if e.get("uid") == "mc-cal-weekly"), key=lambda e: e["utcStart"])
		self.assertEqual(
			[e["utcStart"] for e in weekly],
			["2030-01-14T08:00:00Z", "2030-01-21T08:00:00Z", "2030-01-28T08:00:00Z"],
		)
		self.assertEqual(
			weekly[0]["utcEnd"], "2030-01-14T09:30:00Z", "an hour and a half, winter time (UTC+1)"
		)
		self.assertTrue(all(e["id"].startswith("V") for e in weekly))
		self.assertTrue(
			all(set(e["calendarIds"]) and all(k.startswith("C") for k in e["calendarIds"]) for e in weekly)
		)
		day = next(e for e in events if e.get("uid") == "mc-cal-day")
		self.assertTrue(day["showWithoutTime"])
		self.assertNotIn("utcStart", day, "a day-long event keeps its days")
		self.assertNotIn("mc-cal-summer", {e.get("uid") for e in events}, "outside the window")

	def test_summer_time_is_worked_out(self):
		self._as(PERSON)
		summer = next(e for e in self._window(JULY) if e.get("uid") == "mc-cal-summer")
		self.assertEqual(
			(summer["utcStart"], summer["utcEnd"]), ("2030-07-15T07:00:00Z", "2030-07-15T08:00:00Z")
		)

	def test_a_window_is_required_and_bounded_and_nothing_is_written(self):
		self._as(PERSON)
		aid = jmap.account_id(BOX)
		for criteria in (
			{},
			{"after": JANUARY["after"]},
			{"after": "2030-01-01T00:00:00Z", "before": "2032-01-01T00:00:00Z"},
			{"text": "x", **JANUARY},
		):
			answer = self._calls(("CalendarEvent/query", {"accountId": aid, "filter": criteria}))[0]
			self.assertEqual((answer[0], answer[1]["type"]), ("error", "unsupportedFilter"), criteria)
		refused = self._calls(("CalendarEvent/get", {"accountId": aid, "ids": None}))[0]
		self.assertEqual((refused[0], refused[1]["type"]), ("error", "requestTooLarge"), "never every event")
		changed = self._calls(("CalendarEvent/set", {"accountId": aid, "create": {"k": {"title": "x"}}}))[0][
			1
		]
		self.assertEqual(changed["notCreated"]["k"]["type"], "forbidden")

	def test_the_queries_follow_rfc_8620(self):
		self._as(PERSON)
		aid = jmap.account_id(BOX)
		window = {"accountId": aid, "filter": JANUARY, "expandRecurrences": True}
		none, counted, last, plain, changes, wrong = self._calls(
			("CalendarEvent/query", {**window, "limit": 0, "calculateTotal": True}),
			("CalendarEvent/query", {**window, "calculateTotal": True}),
			("CalendarEvent/query", {**window, "position": -1}),
			("CalendarEvent/query", window),
			("CalendarEvent/changes", {"accountId": aid, "sinceState": "0"}),
			("CalendarEvent/get", {"accountId": aid, "ids": ["Vx"], "properties": [{"x": 1}]}),
		)
		self.assertEqual(none[1]["ids"], [], "a limit of 0 is none")
		self.assertEqual(none[1]["total"], counted[1]["total"])
		self.assertEqual(counted[1]["total"], len(counted[1]["ids"]))
		self.assertGreaterEqual(counted[1]["total"], 4, "three weekly occurrences and the day-long event")
		self.assertEqual(last[1]["ids"], counted[1]["ids"][-1:], "from the end")
		self.assertEqual(last[1]["position"], counted[1]["total"] - 1)
		self.assertNotIn("total", plain[1], "only when asked")
		self.assertEqual(plain[1]["limit"], calendars.MAX_EVENTS)
		self.assertEqual((changes[0], changes[1]["type"]), ("error", "cannotCalculateChanges"))
		self.assertEqual((wrong[0], wrong[1]["type"]), ("error", "invalidArguments"))

	def test_mailcrafts_window_and_the_night_summer_time_ends(self):
		self._as(PERSON)
		# MailCraft reads 456 days at once: 90 days back, a year and a day ahead (crates/jmap/src/calendars.rs).
		events = self._window({"after": "2029-12-01T00:00:00Z", "before": "2031-03-02T00:00:00Z"})
		uids = {e.get("uid") for e in events}
		self.assertTrue({"mc-cal-weekly", "mc-cal-summer", "mc-cal-day", "mc-cal-dst"} <= uids, uids)
		night = next(e for e in events if e.get("uid") == "mc-cal-dst")
		self.assertEqual(
			(night["utcStart"], night["utcEnd"]),
			("2030-10-26T23:00:00Z", "2030-10-27T02:00:00Z"),
			"01:00 summer time, plus three hours as they pass",
		)

	def test_ids_that_are_not_strings_are_none_of_ours(self):
		self._as(PERSON)
		aid = jmap.account_id(BOX)
		listed, got, changed = self._calls(
			("Calendar/get", {"accountId": aid, "ids": [{"x": 1}]}),
			("CalendarEvent/get", {"accountId": aid, "ids": [{"x": 1}, "Vbm9uZQ"]}),
			("CalendarEvent/set", {"accountId": aid, "destroy": [{"x": 1}, "Vbm9uZQ"]}),
		)
		self.assertEqual((listed[0], listed[1]["list"]), ("Calendar/get", []))
		self.assertEqual((got[0], got[1]["list"], got[1]["notFound"]), ("CalendarEvent/get", [], ["Vbm9uZQ"]))
		self.assertEqual((changed[0], list(changed[1]["notDestroyed"])), ("CalendarEvent/set", ["Vbm9uZQ"]))
