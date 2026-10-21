# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The person's calendars as NeoMail's (mailcraft_calendars, JMAP for Calendars; maintenance#1630, step 3).

Read on the calendar the Suite keeps in the instance for a person without a mailbox server account (the clone's
mailboxes have no password, so their calendars cannot be reached): its events of a window, each occurrence apart, with
their start and end in UTC worked out from their zone, summer time included. Only the person's own calendar, chosen
by the facade. NeoMail does what the desk does (Jérémy, 17.10): events created, changed and deleted there, a series or
one of its occurrences, through the Suite's own calendar functions.

Beside them, read-only, what the desk's calendar shows the person too: the dates of the ERP (a to-do and an Event of the
person's, read by the Suite's provider as them) and a calendar a colleague shares with them (a second calendar kept in
the instance stands in for the colleague's account on the mail server, its share faked). A desk user without the roles
behind most dates, and a Website User, get none of what the desk would not show them.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_calendars
"""

import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
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
# Of the desk with only the Blogger role: none of the documents behind most of the ERP's dates; a calendar kept in the
# instance, which stands in for a colleague's account when one is shared.
READER = "mailcraft_calendars_reader@example.com"
READER_BOX = "mailcraft_calendars_reader@webmail.test"
PORTAL = "mailcraft_calendars_portal@example.com"  # a Website User
PORTAL_BOX = "mailcraft_calendars_portal@webmail.test"
JANUARY = {"after": "2030-01-01T00:00:00Z", "before": "2030-02-01T00:00:00Z"}
FEBRUARY = {"after": "2030-02-01T00:00:00Z", "before": "2030-03-01T00:00:00Z"}
JULY = {"after": "2030-07-01T00:00:00Z", "before": "2030-08-01T00:00:00Z"}
NOVEMBER = {"after": "2030-11-01T00:00:00Z", "before": "2030-12-01T00:00:00Z"}
# What the dates of the ERP that are the person's say (a to-do on a day, an Event at an hour).
TODO_TITLE = "Call the supplier back (mailcraft calendars)"
FAIR_TITLE = "Trade fair (mailcraft calendars)"


def _read_only(jmap_id):
	"""The kind ("erp", "shared") of a calendar or an event the person only reads, by its facade id; None for theirs."""
	raw = calendars._raw(jmap_id, "C") if jmap_id[:1] == "C" else calendars._event_raw(jmap_id)
	return calendars._read_only_kind(raw)


def _erp_dates_offered():
	"""Whether the Suite shows the ERP's dates here: its sources, and an app that provides them (neoffice_theme)."""
	try:
		found = importlib.util.find_spec("suite.calendar.sources")
	except ModuleNotFoundError:
		found = None
	return bool(found and frappe.get_hooks("suite_calendar_sources"))


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
					"title": "Site meeting",
					"start": "2030-01-14T09:00:00",
					"duration": "PT1H30M",
					"recurrence_rule": {"@type": "RecurrenceRule", "frequency": "weekly", "count": 3},
				},
				{
					**row,
					"creation_id": "summer",
					"uid": "mc-cal-summer",
					"title": "Summer café",
					"start": "2030-07-15T09:00:00",
					"duration": "PT1H",
				},
				{
					"creation_id": "day",
					"uid": "mc-cal-day",
					"title": "Closed",
					"start": "2030-01-20T00:00:00",
					"duration": "P1D",
					"show_without_time": True,
				},
				# The night summer time ends (27.10.2030 at 03:00, back to 02:00): three hours as they pass.
				{
					**row,
					"creation_id": "dst",
					"uid": "mc-cal-dst",
					"title": "Night",
					"start": "2030-10-27T01:00:00",
					"duration": "PT3H",
				},
			],
		)
		frappe.set_user("Administrator")
		_user(READER, ["Blogger"])
		_mailbox(READER_BOX, READER)
		_user(PORTAL, [])
		_mailbox(PORTAL_BOX, PORTAL)
		cls.reader_account = get_local_account(READER, create=True)
		# A calendar account of the portal user's own, which the Suite never makes for one: what it is asked as them
		# is then theirs to ask.
		cls.portal_account = (
			frappe.db.get_value("Local Calendar Account", {"user": PORTAL})
			or frappe.get_doc({"doctype": "Local Calendar Account", "user": PORTAL})
			.insert(ignore_permissions=True)
			.name
		)
		# The person's dates in the ERP, made as fixtures are (the facade reads them as the person): a to-do allocated
		# to them, and an Event of theirs (no mailbox: the calendar bridge copies it nowhere).
		cls.todo = cls.fair = None
		if _erp_dates_offered():
			cls.todo = (
				frappe.get_doc(
					{
						"doctype": "ToDo",
						"description": TODO_TITLE,
						"date": "2030-02-11",
						"allocated_to": PERSON,
						"status": "Open",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.set_user(PERSON)
			cls.fair = (
				frappe.get_doc(
					{
						"doctype": "Event",
						"subject": FAIR_TITLE,
						"starts_on": "2030-02-12 10:00:00",
						"ends_on": "2030-02-12 11:30:00",
						"event_type": "Private",
					}
				)
				.insert()
				.name
			)
			frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for account in (cls.account, cls.reader_account, cls.portal_account):
			for doctype in ("Local Calendar Event", "Local Calendar"):
				for name in frappe.get_all(doctype, filters={"account": account}, pluck="name"):
					frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.delete_doc("Local Calendar Account", account, ignore_permissions=True, force=True)
		for doctype, name in (("ToDo", cls.todo), ("Event", cls.fair)):
			if name and frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		frappe.db.commit()  # nosemgrep: what the Suite's calendar committed goes too
		super().tearDownClass()

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
		self.trial.start()
		self.lang = frappe.local.lang
		# What an earlier test kept of the read-only windows, and the silences of their failures.
		frappe.cache().delete_keys("mailcraft_calendar_")

	def tearDown(self):
		self.trial.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.local.lang = self.lang
		frappe.set_user("Administrator")

	def _as(self, user):
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = user
		frappe.local.request_cache.clear() if hasattr(frappe.local, "request_cache") else None

	def _calls(self, *calls):
		answer = self._request(*calls)
		self.assertEqual(answer.status_code, 200, answer.get_data())
		return json.loads(answer.get_data())["methodResponses"]

	def _request(self, *calls):
		body = json.dumps(
			{
				"using": [jmap.CORE, calendars.CALENDARS],
				"methodCalls": [[name, args, f"c{n}"] for n, (name, args) in enumerate(calls)],
			}
		).encode()
		# A request as the facade reads it, with the headers the Suite's rate limit reads when an event is written.
		request = SimpleNamespace(
			get_data=lambda: body,
			headers={},
			host="webmail.test",
			method="POST",
			path="/api/method/" + jmap.METHOD_PREFIX + "api",
		)
		with patch.object(frappe.local, "request", request, create=True):
			return jmap.api()

	def _window(self, window, box=BOX):
		aid = jmap.account_id(box)
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
		written = session["accounts"][aid]["accountCapabilities"][calendars.CALENDARS]["writableProperties"]
		self.assertEqual(
			written,
			[
				"alerts",
				"calendarIds",
				"description",
				"duration",
				"freeBusyStatus",
				"links",
				"locations",
				"participants",
				"privacy",
				"recurrenceRule",
				"showWithoutTime",
				"start",
				"status",
				"timeZone",
				"title",
				"useDefaultAlerts",
			],
			"what an event keeps when it is written here, said in advance",
		)
		self.assertNotIn("keywords", written)
		listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
		self.assertTrue(listed and all(c["id"].startswith("C") for c in listed))
		self.assertTrue(listed[0]["myRights"]["mayWriteOwn"], "the person's own calendar, as in the desk")
		self.assertEqual(sum(1 for c in listed if c["isDefault"]), 1)

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
		# An occurrence is named by its series and its start (the mail server renumbers its own id), its series by its own.
		self.assertTrue(all(e["id"].startswith("O") and e["baseEventId"].startswith("V") for e in weekly))
		self.assertEqual(
			{calendars._occurrence_of(e["id"]) for e in weekly},
			{(calendars._raw(e["baseEventId"], "V"), e["recurrenceId"]) for e in weekly},
		)
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
		self.assertEqual(
			changed["notCreated"]["k"]["type"], "invalidProperties", "an event needs its start and length"
		)
		self.assertIn("start and its duration", changed["notCreated"]["k"]["description"])

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

	def _set(self, **changes):
		aid = jmap.account_id(BOX)
		answer = self._calls(("CalendarEvent/set", {"accountId": aid, **changes}))[0]
		self.assertEqual(answer[0], "CalendarEvent/set", answer)
		return answer[1]

	def _calendar(self):
		aid = jmap.account_id(BOX)
		return self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"][0]["id"]

	def test_an_event_is_created_changed_and_deleted_as_in_the_desk(self):
		self._as(PERSON)
		calendar = self._calendar()
		uid = f"mc-test-{frappe.generate_hash(length=10)}"
		event = {
			"@type": "Event",
			"uid": uid,
			"calendarIds": {calendar: True},
			"title": "Site visit",
			"start": "2030-03-04T10:00:00",
			"duration": "PT2H",
			"timeZone": "Europe/Zurich",
			"showWithoutTime": False,
			"description": "With the project owner",
			"locations": {"l1": {"@type": "Location", "name": "12 Lake Street, Vevey"}},
		}
		made = self._set(create={"k": event})
		self.assertEqual(made["notCreated"], {})
		vid = made["created"]["k"]["id"]
		march = {"after": "2030-03-01T00:00:00Z", "before": "2030-04-01T00:00:00Z"}
		found = next(e for e in self._window(march) if e["id"] == vid)
		# The client's uid is the event's: its next read knows the event it made.
		self.assertEqual((made["created"]["k"]["uid"], found["uid"]), (uid, uid))
		self.assertEqual(
			(found["title"], found["utcStart"], found["utcEnd"]),
			("Site visit", "2030-03-04T09:00:00Z", "2030-03-04T11:00:00Z"),
		)
		self.assertEqual([place["name"] for place in found["locations"].values()], ["12 Lake Street, Vevey"])
		# Sent again (its answer lost on the way): the same event, not a second one.
		again = self._set(create={"k2": event})
		self.assertEqual(again["created"]["k2"]["id"], vid)
		self.assertEqual(sum(1 for e in self._window(march) if e.get("title") == "Site visit"), 1)
		# Changed: the properties named replace the stored ones, the others stay.
		changed = self._set(update={vid: {"title": "Site visit (moved)", "start": "2030-03-05T14:00:00"}})
		self.assertEqual((changed["updated"], changed["notUpdated"]), ({vid: None}, {}))
		moved = next(e for e in self._window(march) if e["id"] == vid)
		self.assertEqual(
			(moved["title"], moved["utcStart"], moved["duration"]),
			("Site visit (moved)", "2030-03-05T13:00:00Z", "PT2H"),
		)
		self.assertEqual(moved["description"], "With the project owner")
		# Deleted, as in the desk.
		gone = self._set(destroy=[vid])
		self.assertEqual((gone["destroyed"], gone["notDestroyed"]), ([vid], {}))
		self.assertFalse(any(e["id"] == vid for e in self._window(march)))

	def test_an_occurrence_is_still_reached_after_the_server_renumbers_it(self):
		"""The mail server gives an occurrence a new id of its own as soon as it gets an override (an edit, an answer): a
		change or a deletion made from an older read still reaches it, by its series and its start."""
		from suite.calendar import jmap_events
		from suite.calendar.local import instance_id

		self._as(PERSON)
		series = {
			"@type": "Event",
			"calendarIds": {self._calendar(): True},
			"title": "Workshop (renumbered)",
			"start": "2030-06-03T09:00:00",
			"duration": "PT1H",
			"timeZone": "Europe/Zurich",
			"recurrenceRule": {"@type": "RecurrenceRule", "frequency": "weekly", "count": 3},
		}
		made = self._set(create={"s": series})
		self.assertEqual(made["notCreated"], {})
		base, uid = calendars._raw(made["created"]["s"]["id"], "V"), made["created"]["s"]["uid"]
		june = {"after": "2030-06-01T00:00:00Z", "before": "2030-07-01T00:00:00Z"}

		def ours():
			return sorted((e for e in self._window(june) if e.get("uid") == uid), key=lambda e: e["utcStart"])

		_, second, third = ours()
		# The server renumbers the second and the third occurrence: their former ids name nothing any more.
		renumbered = {
			instance_id(base, second["recurrenceId"]): "renumbered-2",
			instance_id(base, third["recurrenceId"]): "renumbered-3",
		}
		former = {new: old for old, new in renumbered.items()}
		real_query, real_get = jmap_events.query_events, jmap_events.get_events

		def query(client, **arguments):
			answer = real_query(client, **arguments)
			return {**answer, "ids": [renumbered.get(i, i) for i in answer.get("ids") or []]}

		def get(client, ids=None):
			asked = [former.get(i, i) for i in ids or [] if i not in renumbered]
			events = real_get(client, asked)
			return [{**e, "id": renumbered.get(e["id"], e["id"])} for e in events]

		with patch.object(jmap_events, "query_events", query), patch.object(jmap_events, "get_events", get):
			changed = self._set(update={third["id"]: {"title": "Workshop (renumbered, room B)"}})
			self.assertEqual(changed["notUpdated"], {})
			gone = self._set(destroy=[second["id"]])
			self.assertEqual(gone["notDestroyed"], {})
			alone = self._calls(
				("CalendarEvent/get", {"accountId": jmap.account_id(BOX), "ids": [third["id"]]})
			)
			self.assertEqual([e["title"] for e in alone[0][1]["list"]], ["Workshop (renumbered, room B)"])
			self.assertEqual(
				[e["utcStart"] for e in ours()],
				["2030-06-03T07:00:00Z", "2030-06-17T07:00:00Z"],
				"the second is gone, the third changed, each by its series and its start",
			)

	def test_an_occurrence_keeps_its_series_where_the_server_names_it_only_when_asked(self):
		"""The mail server (Stalwart) gives an occurrence's series (`baseEventId`) only when it is asked for by name: the
		facade asks, and an occurrence is still named by its series and its start, says its series, and is reached by it."""
		from suite.calendar import jmap_events
		from suite.calendar.local import instance_id

		self._as(PERSON)
		series = {
			"@type": "Event",
			"calendarIds": {self._calendar(): True},
			"title": "Workshop (series)",
			"start": "2030-09-02T09:00:00",
			"duration": "PT1H",
			"timeZone": "Europe/Zurich",
			"recurrenceRule": {"@type": "RecurrenceRule", "frequency": "weekly", "count": 3},
		}
		made = self._set(create={"s": series})
		self.assertEqual(made["notCreated"], {})
		vid, uid = made["created"]["s"]["id"], made["created"]["s"]["uid"]
		september = {"after": "2030-09-01T00:00:00Z", "before": "2030-10-01T00:00:00Z"}
		real_get = jmap_events.get_events

		def get(client, ids=None):
			# As the server's get that names no property: no baseEventId.
			return [{k: v for k, v in e.items() if k != "baseEventId"} for e in real_get(client, ids)]

		def ours():
			return sorted(
				(e for e in self._window(september) if e.get("uid") == uid), key=lambda e: e["utcStart"]
			)

		with patch.object(jmap_events, "get_events", get):
			weekly = ours()
			self.assertEqual(len(weekly), 3)
			self.assertTrue(all(e["id"][:1] == "O" for e in weekly), [e["id"] for e in weekly])
			self.assertEqual({e.get("baseEventId") for e in weekly}, {vid}, "each says its series")
			changed = self._set(update={weekly[1]["id"]: {"title": "Workshop (room C)"}})
			self.assertEqual(changed["notUpdated"], {})
			self.assertEqual(
				[e["title"] for e in ours()], ["Workshop (series)", "Workshop (room C)", "Workshop (series)"]
			)
			# Asked for by the server's own id (an older read's), an occurrence says its series too.
			own = calendars._event_id(instance_id(calendars._raw(vid, "V"), weekly[2]["recurrenceId"]))
			got = self._calls(("CalendarEvent/get", {"accountId": jmap.account_id(BOX), "ids": [own]}))
			self.assertEqual([e.get("baseEventId") for e in got[0][1]["list"]], [vid])

	def test_one_occurrence_of_a_series_is_changed_or_deleted_alone(self):
		self._as(PERSON)
		series = {
			"@type": "Event",
			"calendarIds": {self._calendar(): True},
			"title": "Team meeting",
			"start": "2030-05-06T08:30:00",
			"duration": "PT1H",
			"timeZone": "Europe/Zurich",
			"recurrenceRule": {"@type": "RecurrenceRule", "frequency": "weekly", "count": 3},
		}
		self.assertEqual(self._set(create={"s": series})["notCreated"], {})
		may = {"after": "2030-05-01T00:00:00Z", "before": "2030-06-01T00:00:00Z"}

		def occurrences():
			return sorted(
				(e for e in self._window(may) if e.get("title", "").startswith("Team meeting")),
				key=lambda e: e["utcStart"],
			)

		weekly = occurrences()
		self.assertEqual(
			[e["utcStart"] for e in weekly],
			["2030-05-06T06:30:00Z", "2030-05-13T06:30:00Z", "2030-05-20T06:30:00Z"],
		)
		second, third = weekly[1]["id"], weekly[2]["id"]
		self.assertTrue(
			weekly[1].get("recurrenceId"), "an occurrence says which one it is (the desk's instance path)"
		)
		self.assertEqual(self._set(update={third: {"title": "Team meeting (room B)"}})["notUpdated"], {})
		self.assertEqual(self._set(destroy=[second])["notDestroyed"], {})
		after = occurrences()
		self.assertEqual([e["utcStart"] for e in after], ["2030-05-06T06:30:00Z", "2030-05-20T06:30:00Z"])
		self.assertEqual([e["title"] for e in after], ["Team meeting", "Team meeting (room B)"])

	def test_what_cannot_be_written_is_refused_and_says_why(self):
		self._as(PERSON)
		calendar = self._calendar()
		base = {"start": "2030-03-04T10:00:00", "duration": "PT1H", "title": "x"}
		refused = self._set(
			create={
				"elsewhere": {**base, "calendarIds": {"Cbm9uZQ": True}},
				"unknown": {**base, "calendarIds": {calendar: True}, "virtualLocations": {"v": {"uri": "x"}}},
				"shape": {**base, "calendarIds": {calendar: True}, "locations": ["Vevey"]},
			},
			update={"Vbm9uZQ": {"title": "y"}},
			destroy=["Vbm9uZQ"],
		)
		weekly = next(e for e in self._window(JANUARY) if e.get("uid") == "mc-cal-weekly")
		part = self._set(update={weekly["id"]: {"locations/l1/name": "Vevey"}})
		self.assertEqual(
			part["notUpdated"][weekly["id"]]["type"], "invalidProperties", "a whole property, no part"
		)
		self.assertIn("whole property", part["notUpdated"][weekly["id"]]["description"])
		self.assertEqual(
			{key: error["type"] for key, error in refused["notCreated"].items()},
			{"elsewhere": "invalidProperties", "unknown": "invalidProperties", "shape": "invalidProperties"},
		)
		self.assertEqual(refused["notUpdated"]["Vbm9uZQ"]["type"], "notFound")
		self.assertEqual(refused["notDestroyed"]["Vbm9uZQ"]["type"], "notFound")
		self.assertEqual(refused["created"], {})

	def test_a_calendar_the_person_may_only_read_is_not_written(self):
		"""The rights the Suite reads on each calendar (a mail server's shared calendar may be read-only) hold."""
		from suite.calendar import jmap_events

		self._as(PERSON)
		real = jmap_events.get_calendars

		def read_only(client, ids=None):
			return [{**c, "myRights": {"mayReadItems": True}} for c in real(client, ids)]

		weekly = next(e for e in self._window(JANUARY) if e.get("uid") == "mc-cal-weekly")
		calendar = self._calendar()
		with patch.object(jmap_events, "get_calendars", side_effect=read_only):
			aid = jmap.account_id(BOX)
			listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
			self.assertFalse(listed[0]["myRights"]["mayWriteOwn"])
			refused = self._set(
				create={
					"k": {
						"calendarIds": {calendar: True},
						"title": "x",
						"start": "2030-03-04T10:00:00",
						"duration": "PT1H",
					}
				},
				update={weekly["id"]: {"title": "y"}},
				destroy=[weekly["id"]],
			)
		self.assertEqual(refused["notCreated"]["k"]["type"], "forbidden")
		self.assertEqual(refused["notUpdated"][weekly["id"]]["type"], "forbidden")
		self.assertEqual(refused["notDestroyed"][weekly["id"]]["type"], "forbidden")
		self.assertIn("mc-cal-weekly", {e.get("uid") for e in self._window(JANUARY)}, "nothing deleted")

	def _make(self, **over):
		event = {
			"@type": "Event",
			"calendarIds": {self._calendar(): True},
			"title": "Review",
			"start": "2030-04-08T10:00:00",
			"duration": "PT1H",
			"timeZone": "Europe/Zurich",
			**over,
		}
		made = self._set(create={"k": event})
		self.assertEqual(made["notCreated"], {}, made)
		return made["created"]["k"]["id"]

	def _get(self, vid):
		aid = jmap.account_id(BOX)
		return self._calls(("CalendarEvent/get", {"accountId": aid, "ids": [vid]}))[0][1]["list"][0]

	def test_the_organizer_and_the_draft_state_are_the_events_own(self):
		"""The desk never changes who organizes an event, nor sends a draft by an edit: neither does NeoMail."""
		self._as(PERSON)
		vid = self._make()
		stored = self._get(vid)
		organizer = stored.get("organizerCalendarAddress")
		# Sent back as it was: accepted.
		same = self._set(update={vid: {"title": "Review (again)", "organizerCalendarAddress": organizer}})
		self.assertEqual(same["notUpdated"], {})
		# Another organizer, or none: refused, nothing changed.
		for other in ("mailto:boss@example.com", None):
			refused = self._set(update={vid: {"organizerCalendarAddress": other, "title": "x"}})
			self.assertEqual(refused["notUpdated"][vid]["type"], "forbidden", other)
		self.assertEqual(self._get(vid)["title"], "Review (again)")
		# A create names one of the person's own addresses, or none.
		elsewhere = self._set(
			create={
				"k": {
					"calendarIds": {self._calendar(): True},
					"title": "x",
					"start": "2030-04-09T10:00:00",
					"duration": "PT1H",
					"organizerCalendarAddress": "mailto:boss@example.com",
				}
			}
		)
		self.assertEqual(elsewhere["notCreated"]["k"]["type"], "forbidden")
		# A draft stays a draft, and is not sent by NeoMail.
		self.assertEqual(
			self._set(update={vid: {"isDraft": True}})["notUpdated"][vid]["type"], "invalidProperties"
		)

	def test_a_draft_made_in_the_desk_stays_a_draft(self):
		from suite.calendar.doctype.calendar_event.calendar_event import add_calendar_event

		self._as(PERSON)
		raw = add_calendar_event(
			account=self.account,
			calendar_ids=[calendars._raw(self._calendar(), "C")],
			draft=True,
			title="Draft",
			start="2030-04-10T09:00:00",
			duration="PT30M",
			time_zone="Europe/Zurich",
		)
		vid = calendars._event_id(raw)
		self.assertEqual(self._set(update={vid: {"title": "Draft (renamed)"}})["notUpdated"], {})
		after = self._get(vid)
		self.assertEqual((after["title"], bool(after.get("isDraft"))), ("Draft (renamed)", True))

	def _invitation(self, **over):
		"""The occurrences (one for a single event) of an event someone else organizes, in the person's calendar, the
		person invited (as the Suite files an invitation that arrives), with a second guest."""
		from suite.calendar.jmap_events import create_events
		from suite.mail.jmap import get_account_client

		uid = f"mc-invite-{frappe.generate_hash(length=10)}"
		guest = {"roles": {"attendee": True}, "participation_status": "needs-action", "expect_reply": True}
		create_events(
			get_account_client(self.account),
			self.account,
			[
				{
					"creation_id": "i",
					"uid": uid,
					"calendar_ids": [calendars._raw(self._calendar(), "C")],
					"organizer": "boss@example.com",
					"title": "Project review",
					"start": "2030-11-04T10:00:00",
					"duration": "PT1H",
					"time_zone": "Europe/Zurich",
					"participants": [
						{
							"uid": "boss",
							"email": "boss@example.com",
							"roles": {"owner": True, "attendee": True},
							"participation_status": "accepted",
						},
						{"uid": "me", "email": PERSON, **guest},
						{"uid": "ana", "email": "ana@example.com", **guest},
					],
					**over,
				}
			],
		)
		return sorted((e for e in self._window(NOVEMBER) if e.get("uid") == uid), key=lambda e: e["utcStart"])

	def _answered(self, event, who="me", status="accepted"):
		"""The participants of `event` as a client sends them back, `who` having answered `status`."""
		participants = json.loads(json.dumps(event["participants"]))
		participants[who]["participationStatus"] = status
		return participants

	def _sending_answers(self):
		"""The person's calendars as a mail server's: answers go out from them (`mayRSVP`), where the calendar the Suite
		keeps in the instance sends none."""
		from suite.calendar import jmap_events

		real = jmap_events.get_calendars

		def granted(client, ids=None):
			return [
				{**c, "myRights": {**(c.get("myRights") or {}), "mayRSVP": True}} for c in real(client, ids)
			]

		return patch.object(jmap_events, "get_calendars", side_effect=granted)

	def test_an_answer_to_someone_elses_invitation_reaches_its_organizer(self):
		"""Answered in NeoMail, the client asking for it to be sent: recorded on the person's copy and told to the
		organizer, by the desk's own answer (rsvp_calendar_event), where a change of the copy alone tells nobody."""
		from suite.calendar.doctype.calendar_event import invitations

		self._as(PERSON)
		(event,) = self._invitation()
		queued = []
		# The custom reply mail is queued (and not run): what it would be told is read from the queue.
		with (
			self._sending_answers(),
			patch.object(invitations, "custom_event_invites_enabled", return_value=True),
			patch.object(frappe, "enqueue", side_effect=lambda method, **kw: queued.append((method, kw))),
			patch.object(frappe, "sendmail", side_effect=AssertionError("a test sends no mail")),
		):
			answered = self._set(
				update={event["id"]: {"participants": self._answered(event)}}, sendSchedulingMessages=True
			)
		self.assertEqual((answered["updated"], answered["notUpdated"]), ({event["id"]: None}, {}))
		after = self._get(event["id"])["participants"]
		self.assertEqual(
			{who: p.get("participationStatus") for who, p in after.items()},
			{"boss": "accepted", "me": "accepted", "ana": "needs-action"},
		)
		told = [kw for method, kw in queued if method.endswith(".notify_organizer_of_reply")]
		self.assertEqual(len(told), 1, queued)
		self.assertEqual(
			(told[0]["event_id"], told[0]["responder_email"], told[0]["status"], told[0]["recurrence_id"]),
			(calendars._raw(event["id"], "V"), PERSON, "accepted", None),
		)

	def test_a_calendar_that_sends_no_answers_keeps_them_on_the_copy(self):
		"""A calendar the Suite keeps in the instance sends no mail (`mayRSVP` is off): an answer there is written on the
		copy, as before, and never handed to the desk's answer, whose reply mail could not go."""
		from suite.calendar import api as calendar_api
		from suite.calendar.doctype.calendar_event import calendar_event, invitations

		self._as(PERSON)
		(event,) = self._invitation()
		with (
			patch.object(calendar_api, "rsvp_calendar_event", side_effect=AssertionError("no answer sent")),
			patch.object(
				calendar_event, "update_calendar_event", wraps=calendar_event.update_calendar_event
			) as written,
			patch.object(invitations, "custom_event_invites_enabled", return_value=False),
			patch.object(frappe, "enqueue"),
		):
			answered = self._set(
				update={event["id"]: {"participants": self._answered(event, status="tentative")}},
				sendSchedulingMessages=True,
			)
		self.assertEqual(answered["notUpdated"], {})
		self.assertEqual(written.call_args.kwargs["send_scheduling_messages"], False)
		self.assertEqual(self._get(event["id"])["participants"]["me"]["participationStatus"], "tentative")

	def test_what_is_not_an_answer_is_written_as_before_and_tells_nobody(self):
		"""Not asked to be sent, something else changed with it, another guest's status, a status that answers
		nothing, two entries changed, a guest added, the person's name changed, or the organizer's own: written as
		before (update_calendar_event), the organizer not told; what looked like the person's answer is logged."""
		from suite.calendar import api as calendar_api
		from suite.calendar.doctype.calendar_event import calendar_event, invitations

		self._as(PERSON)
		(event,) = self._invitation()
		vid = event["id"]

		def current():
			return self._get(vid)

		def two(e):
			participants = self._answered(e)
			participants["ana"]["participationStatus"] = "declined"
			return {"participants": participants}

		def added(e):
			participants = self._answered(e, status="tentative")
			participants["zed"] = {
				"@type": "Participant",
				"calendarAddress": "mailto:zed@example.com",
				"roles": {"attendee": True},
				"participationStatus": "needs-action",
			}
			return {"participants": participants}

		def renamed(e):
			participants = self._answered(e)
			participants["me"]["name"] = "Someone else"
			return {"participants": participants}

		cases = [
			("not asked", lambda e: {"participants": self._answered(e, status="tentative")}, False),
			(
				"title too",
				lambda e: {"participants": self._answered(e, status="declined"), "title": "Review (again)"},
				True,
			),
			("another's", lambda e: {"participants": self._answered(e, who="ana")}, True),
			("no answer", lambda e: {"participants": self._answered(e, status="delegated")}, True),
			("two changed", two, True),
			("guest added", added, True),
			("name changed", renamed, True),
		]
		# The calendar kept in the instance sends no scheduling mail of its own; the custom invitations, which would, are
		# off, and nothing queued runs.
		with (
			self._sending_answers(),
			patch.object(
				calendar_api, "rsvp_calendar_event", side_effect=AssertionError("not an answer")
			) as answer,
			patch.object(
				calendar_event, "update_calendar_event", wraps=calendar_event.update_calendar_event
			) as written,
			patch.object(invitations, "custom_event_invites_enabled", return_value=False),
			patch.object(frappe, "enqueue"),
			patch.object(frappe, "sendmail", side_effect=AssertionError("a test sends no mail")),
			patch.object(frappe, "log_error") as logged,
		):
			for name, change, send in cases:
				done = self._set(update={vid: change(current())}, sendSchedulingMessages=send)
				self.assertEqual(done["notUpdated"], {}, name)
				self.assertEqual(written.call_args.kwargs["send_scheduling_messages"], False, name)
			# The organizer's own answer is an organizer's change: the guests are told by an update, as from the desk.
			with patch.object(calendars, "_organizes", return_value=True):
				done = self._set(
					update={vid: {"participants": self._answered(current(), who="boss", status="tentative")}},
					sendSchedulingMessages=True,
				)
			self.assertEqual(done["notUpdated"], {})
			self.assertEqual(written.call_args.kwargs["send_scheduling_messages"], True)
		self.assertEqual(answer.call_count, 0)
		self.assertEqual(
			[call.args[0] for call in logged.call_args_list],
			["NeoMail: an answer to an invitation was written on the copy alone"] * 4,
			"title too, two changed, guest added, name changed",
		)
		after = current()
		self.assertEqual(after["title"], "Review (again)")
		self.assertEqual(after["participants"]["me"]["name"], "Someone else")
		self.assertEqual(
			{who: p.get("participationStatus") for who, p in after["participants"].items()},
			{"boss": "tentative", "me": "accepted", "ana": "declined", "zed": "needs-action"},
		)

	def test_an_answer_sent_back_as_a_client_spells_it_is_still_one(self):
		"""What the Suite works out again when it writes a participant (where invitations go, its scheduling id, whether
		a reply is expected) may come back otherwise, an address's scheme in capitals, roles that are off said off: the
		person's answer is still theirs alone."""
		from suite.calendar import api as calendar_api

		self._as(PERSON)
		(event,) = self._invitation()
		echoed = self._answered(event)
		for entry in echoed.values():
			for derived in ("sendTo", "scheduleId", "expectReply"):
				entry.pop(derived, None)
			entry["roles"] = {**(entry.get("roles") or {}), "chair": False}
		echoed["me"]["calendarAddress"] = "MAILTO:" + PERSON.upper()
		with self._sending_answers(), patch.object(calendar_api, "rsvp_calendar_event") as answer:
			answered = self._set(update={event["id"]: {"participants": echoed}}, sendSchedulingMessages=True)
		self.assertEqual(answered["notUpdated"], {})
		answer.assert_called_once_with(self.account, calendars._raw(event["id"], "V"), "accepted")

	def test_invited_under_two_of_their_addresses_either_entry_answers(self):
		"""A client may move either of the person's entries (it cannot know which the server lists first): either is
		the answer, which record_rsvp records on the first and tells the organizer."""
		from suite.calendar import api as calendar_api
		from suite.calendar.doctype.calendar_event import invitations
		from suite.mail import jmap as suite_jmap

		self._as(PERSON)
		guest = {"roles": {"attendee": True}, "participation_status": "needs-action", "expect_reply": True}
		(event,) = self._invitation(
			participants=[
				{
					"uid": "boss",
					"email": "boss@example.com",
					"roles": {"owner": True},
					"participation_status": "accepted",
				},
				{"uid": "me", "email": PERSON, **guest},
				{"uid": "alias", "email": "alias.mailcraft@example.com", **guest},
			]
		)
		identities = [{"email": PERSON}, {"email": "alias.mailcraft@example.com"}]
		with (
			self._sending_answers(),
			patch.object(suite_jmap, "get_participant_identities", return_value=identities),
			patch.object(calendar_api, "rsvp_calendar_event") as answer,
			patch.object(invitations, "custom_event_invites_enabled", return_value=False),
			patch.object(frappe, "enqueue"),
			patch.object(frappe, "sendmail", side_effect=AssertionError("a test sends no mail")),
		):
			other = self._set(
				update={event["id"]: {"participants": self._answered(event, who="alias")}},
				sendSchedulingMessages=True,
			)
			self.assertEqual(other["notUpdated"], {})
			answer.assert_called_once_with(self.account, calendars._raw(event["id"], "V"), "accepted")
			# The entry the client moved says it too (record_rsvp, stood in for here, records the first).
			self.assertEqual(
				self._get(event["id"])["participants"]["alias"]["participationStatus"], "accepted"
			)
			first = self._set(
				update={
					event["id"]: {"participants": self._answered(self._get(event["id"]), status="declined")}
				},
				sendSchedulingMessages=True,
			)
		self.assertEqual(first["notUpdated"], {})
		self.assertEqual(answer.call_args.args, (self.account, calendars._raw(event["id"], "V"), "declined"))

	def test_the_organizers_own_status_moved_alone_tells_nobody(self):
		"""The person organizes the meeting (under an address the client took for a guest's) and only their own status
		moves: no change to tell the guests, and no answer sent to oneself."""
		from suite.calendar import api as calendar_api
		from suite.calendar.doctype.calendar_event import calendar_event, invitations
		from suite.mail import jmap as suite_jmap

		self._as(PERSON)
		(event,) = self._invitation()
		real_update = calendar_event.update_calendar_event
		with (
			self._sending_answers(),
			patch.object(calendars, "_organizes", return_value=True),
			patch.object(suite_jmap, "get_participant_identities", return_value=[{"email": PERSON}]),
			patch.object(
				calendar_api, "rsvp_calendar_event", side_effect=AssertionError("no answer to oneself")
			),
			patch.object(calendar_event, "update_calendar_event", wraps=real_update) as update,
			patch.object(invitations, "custom_event_invites_enabled", return_value=False),
			patch.object(frappe, "enqueue"),
			patch.object(frappe, "sendmail", side_effect=AssertionError("a test sends no mail")),
		):
			own = self._set(
				update={event["id"]: {"participants": self._answered(event, status="tentative")}},
				sendSchedulingMessages=True,
			)
			self.assertEqual(own["notUpdated"], {}, own)
			self.assertIs(update.call_args.kwargs["send_scheduling_messages"], False)
			# Anything else changed with it is the organizer's change, told to the guests.
			retitled = self._set(
				update={event["id"]: {"title": "Project review (room B)"}}, sendSchedulingMessages=True
			)
			self.assertEqual(retitled["notUpdated"], {}, retitled)
			self.assertIs(update.call_args.kwargs["send_scheduling_messages"], True)

	def test_one_occurrence_of_someone_elses_invitation_is_answered_with_its_series(self):
		"""As in the desk, which offers no answer to one occurrence of another's invitation (the mail server would give
		it to every occurrence, and the copy would lose its rule): refused, and said; nothing written."""
		from suite.calendar import api as calendar_api

		self._as(PERSON)
		weekly = self._invitation(
			recurrence_rule={"@type": "RecurrenceRule", "frequency": "weekly", "count": 3}
		)
		self.assertEqual(len(weekly), 3)
		second = weekly[1]
		self.assertEqual(second["id"][:1], "O", second["id"])
		with (
			self._sending_answers(),
			patch.object(calendar_api, "rsvp_calendar_event", side_effect=AssertionError("refused first")),
		):
			refused = self._set(
				update={second["id"]: {"participants": self._answered(second, status="declined")}},
				sendSchedulingMessages=True,
			)
		self.assertEqual(refused["notUpdated"][second["id"]]["type"], "forbidden")
		self.assertIn("answered as a whole", refused["notUpdated"][second["id"]]["description"])
		self.assertEqual(
			[e["participants"]["me"]["participationStatus"] for e in self._invitation_now(weekly)],
			["needs-action"] * 3,
		)

	def _invitation_now(self, occurrences):
		uid = occurrences[0]["uid"]
		return sorted((e for e in self._window(NOVEMBER) if e.get("uid") == uid), key=lambda e: e["utcStart"])

	def test_one_calendar_is_the_default_and_colours_are_rrggbb(self):
		"""The Suite and the mail server may flag several calendars, or none, and keep a colour as any client wrote it:
		one is said to be the default, the one an event made without a calendar goes to, and each colour is #rrggbb."""
		from suite.calendar import jmap_events
		from suite.calendar.doctype.calendar_event import calendar_event

		self._as(PERSON)
		read_only, writable = {"mayReadItems": True}, {"mayReadItems": True, "mayWriteAll": True}

		def kept(*calendars_kept):
			return lambda client, ids=None: [dict(c) for c in calendars_kept]

		flagged_read_only = {
			"id": "a",
			"name": "A",
			"isDefault": True,
			"myRights": read_only,
			"color": "blue",
		}
		plain = {"id": "b", "name": "B", "myRights": writable, "color": "#ABC"}
		flagged = {"id": "c", "name": "C", "isDefault": True, "myRights": writable, "color": "#11223344"}
		odd = {"id": "d", "name": "D", "myRights": writable, "color": "not a colour"}
		aid = jmap.account_id(BOX)
		for calendars_kept, default in (
			((flagged_read_only, plain, flagged, odd), "c"),
			((flagged_read_only, plain, odd), "b"),
			((flagged_read_only, {**flagged, "myRights": read_only}), "a"),
		):
			with patch.object(jmap_events, "get_calendars", side_effect=kept(*calendars_kept)):
				listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
			self.assertEqual(
				[c["id"] for c in listed if c["isDefault"]], [calendars._calendar_id(default)], default
			)
		with patch.object(
			jmap_events, "get_calendars", side_effect=kept(flagged_read_only, plain, flagged, odd)
		):
			listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
			self.assertEqual(
				{c["name"]: c["color"] for c in listed if not _read_only(c["id"])},
				{"A": "#0000ff", "B": "#aabbcc", "C": "#112233", "D": None},
			)
			with patch.object(calendar_event, "add_calendar_event", return_value="made") as add:
				self._set(create={"k": {"title": "x", "start": "2030-04-08T10:00:00", "duration": "PT1H"}})
		self.assertEqual(add.call_args.kwargs["calendar_ids"], ["c"], "where the default said it would go")
		# What Pillow reads but is no colour: a channel out of bounds, a transparent one.
		for odd_colour in (
			"rgb(300,0,0)",
			"rgb(200%,0%,0%)",
			"hsl(0, 500%, 50%)",
			"#00000000",
			"rgba(0,0,0,0)",
		):
			self.assertIsNone(calendars._color(odd_colour), odd_colour)
		self.assertEqual(calendars._color("#D68A59"), "#d68a59")

	def test_the_clients_uid_goes_to_a_suite_that_keeps_it(self):
		"""An older Suite makes its own uid and takes no `uid`: nothing is passed to it then."""

		def older(account, organizer=None, send_scheduling_messages=False):
			pass

		def newer(account, organizer=None, send_scheduling_messages=False, uid=None):
			pass

		self.assertEqual(
			(calendars._keeps_client_uid(older), calendars._keeps_client_uid(newer)), (False, True)
		)

	def test_an_online_meeting_is_the_events_own_meet_room(self):
		"""Asked for by its request in virtualLocations, the event gets a Meet room as the desk's switch makes it: its link
		in links, the room tied to the event, read back as a virtual location. Asked again, no second room; a place that
		is no room of this site is refused; named no more, its link goes and the room stays. Without Meet the request is
		refused, and an event refused after its room was made leaves no room."""
		from suite.calendar.doctype.calendar_event import calendar_event
		from suite.utils import rate_limiter

		if not frappe.db.exists("Role", "Suite User"):
			self.skipTest("Meet rooms are made by a Suite User")
		# Meet's limit on new rooms (ten an hour from one address) is the desk's, and would stop a test run again.
		real_limits = rate_limiter.get_rate_limits
		no_room_limit = patch.object(
			rate_limiter,
			"get_rate_limits",
			side_effect=lambda path: [] if path == "suite.meet.api.meeting.create" else real_limits(path),
		)
		no_room_limit.start()
		self.addCleanup(no_room_limit.stop)
		request = {"m": {"@type": "VirtualLocation", "uri": calendars.ONLINE_MEETING_REQUEST}}
		event = {
			"calendarIds": {},
			"title": "Design review",
			"start": "2030-05-06T10:00:00",
			"duration": "PT1H",
			"timeZone": "Europe/Zurich",
			"virtualLocations": request,
		}
		rooms_before = set(frappe.get_all("Meet Room", pluck="name"))
		frappe.get_doc("User", PERSON).add_roles("Suite User")
		vid = other_vid = None
		try:
			self._as(PERSON)
			event["calendarIds"] = {self._calendar(): True}
			with patch.object(calendars, "meet_usable", return_value=True):
				aid = jmap.account_id(BOX)
				session = json.loads(jmap.session(BOX).get_data())
				written = session["accounts"][aid]["accountCapabilities"][calendars.CALENDARS][
					"writableProperties"
				]
				self.assertIn("virtualLocations", written, "offered where Meet makes the room")
				made = self._set(create={"k": event})
				self.assertEqual(made["notCreated"], {}, made)
				vid = made["created"]["k"]["id"]
				places = list(made["created"]["k"]["virtualLocations"].values())
				self.assertEqual(len(places), 1, places)
				url = places[0]["uri"]
				self.assertIn("/meet/", url)
				self.assertTrue(places[0]["features"]["video"])
				room = url.rsplit("/", 1)[1]
				self.assertEqual(
					frappe.db.get_value("Meet Room", room, "calendar_event"),
					f"{self.account}|{calendars._raw(vid, 'V')}",
				)
				read = self._get(vid)
				self.assertEqual([link["href"] for link in read["links"].values()], [url])
				self.assertEqual([place["uri"] for place in read["virtualLocations"].values()], [url])
				# Asked again (a second device, a resend): the same room.
				again = self._set(update={vid: {"virtualLocations": request}})
				self.assertEqual(again["notUpdated"], {}, again)
				self.assertEqual(
					[p["uri"] for p in again["updated"][vid]["virtualLocations"].values()], [url]
				)
				self.assertEqual(set(frappe.get_all("Meet Room", pluck="name")) - rooms_before, {room})
				# Asked again with links read before the room was made: the room's link goes back, no second room.
				stale = self._set(update={vid: {"links": {}, "virtualLocations": request}})
				self.assertEqual(
					[p["uri"] for p in stale["updated"][vid]["virtualLocations"].values()], [url]
				)
				self.assertEqual([link["href"] for link in self._get(vid)["links"].values()], [url])
				self.assertEqual(set(frappe.get_all("Meet Room", pluck="name")) - rooms_before, {room})
				# A place that is no room of this site is refused.
				elsewhere = {"z": {"@type": "VirtualLocation", "uri": "https://video.example.org/room"}}
				odd = self._set(update={vid: {"virtualLocations": elsewhere}})
				self.assertEqual(odd["notUpdated"][vid]["type"], "invalidProperties", odd)
				# Named no more: the link goes, the room stays (with its recordings, its host's).
				dropped = self._set(update={vid: {"virtualLocations": {}}})
				self.assertEqual(
					(dropped["notUpdated"], dropped["updated"][vid]), ({}, {"virtualLocations": {}})
				)
				self.assertFalse(calendars._meet_links(self._get(vid).get("links")))
				self.assertTrue(frappe.db.exists("Meet Room", room))
				# Another service's address with /meet/ in it is no room: one is made, and dropping it keeps the other.
				elsewhere_link = {
					"f": {"@type": "Link", "href": "https://video.example.org/meet/abcd-efgh-ijkl"}
				}
				other = self._set(
					create={"k": {**event, "title": "x" * 200, "links": elsewhere_link, "uid": None}}
				)
				self.assertEqual(other["notCreated"], {}, other)
				other_vid = other["created"]["k"]["id"]
				places = [p["uri"] for p in other["created"]["k"]["virtualLocations"].values()]
				self.assertEqual(len(places), 1, places)
				self.assertNotEqual(places[0], elsewhere_link["f"]["href"])
				self.assertEqual(
					frappe.db.get_value("Meet Room", places[0].rsplit("/", 1)[1], "title"), "x" * 140
				)
				self._set(update={other_vid: {"virtualLocations": {}}})
				self.assertEqual(
					[link["href"] for link in self._get(other_vid)["links"].values()],
					[elsewhere_link["f"]["href"]],
				)
			# Without Meet: refused, nothing made.
			with patch.object(calendars, "meet_usable", return_value=False):
				refused = self._set(create={"k": event})
			self.assertEqual(refused["notCreated"]["k"]["type"], "forbidden", refused)
			self.assertEqual(
				refused["notCreated"]["k"]["properties"], ["virtualLocations"], "the room, not the event"
			)
			# The limit on new rooms is the room's refusal, said apart from the desk's own limits.
			from suite.meet.api import meeting as meet_meeting

			with (
				patch.object(calendars, "meet_usable", return_value=True),
				patch.object(
					meet_meeting, "create", side_effect=frappe.RateLimitExceededError("Too many rooms")
				),
			):
				limited = self._set(create={"k": event})
			self.assertEqual(
				(limited["notCreated"]["k"]["type"], limited["notCreated"]["k"]["properties"]),
				("rateLimit", ["virtualLocations"]),
				limited,
			)
			# Refused after its room was made: no room left.
			with (
				patch.object(calendars, "meet_usable", return_value=True),
				patch.object(calendar_event, "add_calendar_event", side_effect=ValueError("refused")),
			):
				failed = self._set(create={"k": event})
			self.assertEqual(failed["notCreated"]["k"]["type"], "invalidProperties", failed)
			self.assertEqual(
				set(frappe.get_all("Meet Room", pluck="name")) - rooms_before,
				{room, places[0].rsplit("/", 1)[1]},
			)
		finally:
			self._as(PERSON)
			for made_vid in (vid, other_vid):
				if made_vid:
					self._set(destroy=[made_vid])
			frappe.set_user("Administrator")
			frappe.get_doc("User", PERSON).remove_roles("Suite User")
			for name in set(frappe.get_all("Meet Room", pluck="name")) - rooms_before:
				frappe.delete_doc("Meet Room", name, ignore_permissions=True, force=True)

	def test_the_persons_addresses_in_events_are_their_participant_identities(self):
		"""A client learns every address the person takes part in events under, an alias included, as the desk reads
		them (ParticipantIdentity/get)."""
		from suite.mail import jmap as suite_jmap

		self._as(PERSON)
		aid = jmap.account_id(BOX)
		identities = [
			{"id": "1", "_name": "Person", "email": PERSON, "default": 1},
			{"id": "2", "_name": "Person (alias)", "email": "alias.mailcraft@example.com", "default": 0},
		]
		with patch.object(suite_jmap, "get_participant_identities", return_value=identities):
			every = self._calls(("ParticipantIdentity/get", {"accountId": aid, "ids": None}))[0]
			some = self._calls(("ParticipantIdentity/get", {"accountId": aid, "ids": ["2", "9"]}))[0]
		self.assertEqual(every[0], "ParticipantIdentity/get", every)
		self.assertEqual(
			[(i["calendarAddress"], i["isDefault"]) for i in every[1]["list"]],
			[(f"mailto:{PERSON}", True), ("mailto:alias.mailcraft@example.com", False)],
		)
		self.assertEqual(([i["id"] for i in some[1]["list"]], some[1]["notFound"]), (["2"], ["9"]))

	def test_a_series_master_is_read_by_its_v_id(self):
		"""A client reads a series itself by its V id, for its rule, its own changes of single occurrences and its
		first start."""
		self._as(PERSON)
		vid = self._make(
			title="Committee", recurrenceRule={"@type": "RecurrenceRule", "frequency": "weekly", "count": 3}
		)
		april = {"after": "2030-04-01T00:00:00Z", "before": "2030-05-01T00:00:00Z"}
		weekly = sorted(
			(e for e in self._window(april) if e.get("title") == "Committee"), key=lambda e: e["utcStart"]
		)
		self.assertEqual(len(weekly), 3)
		self.assertEqual(
			self._set(update={weekly[1]["id"]: {"title": "Committee (room B)"}})["notUpdated"], {}
		)
		master = self._get(vid)
		self.assertEqual(master["id"], vid)
		self.assertEqual(
			(master["recurrenceRule"]["frequency"], master["start"]), ("weekly", "2030-04-08T10:00:00")
		)
		self.assertFalse(master.get("recurrenceId"))
		self.assertIn(weekly[1]["recurrenceId"], master.get("recurrenceOverrides") or {})

	def test_what_the_suite_does_not_keep_is_refused_not_dropped(self):
		self._as(PERSON)
		vid = self._make()
		for change in (
			{"recurrenceOverrides": {"2030-04-15T10:00:00": {"excluded": True}}},
			{"keywords": {"x": True}},
			{"color": "red"},
			{"excludedRecurrenceRules": []},
		):
			refused = self._set(update={vid: change})
			self.assertEqual(refused["notUpdated"][vid]["type"], "invalidProperties", change)
		occurrence = self._set(
			create={
				"k": {
					"calendarIds": {self._calendar(): True},
					"title": "x",
					"start": "2030-04-08T10:00:00",
					"duration": "PT1H",
					"recurrenceId": "2030-04-08T10:00:00",
				}
			}
		)
		self.assertEqual(occurrence["notCreated"]["k"]["type"], "invalidProperties")

	def test_an_occurrence_keeps_its_zone_and_its_calendar(self):
		self._as(PERSON)
		self._make(
			title="Workshop", recurrenceRule={"@type": "RecurrenceRule", "frequency": "weekly", "count": 2}
		)
		april = {"after": "2030-04-01T00:00:00Z", "before": "2030-05-01T00:00:00Z"}
		first = next(
			e
			for e in sorted(self._window(april), key=lambda e: e["utcStart"])
			if e.get("title") == "Workshop"
		)
		self.assertEqual(
			self._set(update={first["id"]: {"title": "Workshop (A)", "timeZone": "America/New_York"}})[
				"notUpdated"
			],
			{},
		)
		moved = next(e for e in self._window(april) if e.get("title") == "Workshop (A)")
		self.assertEqual(
			moved["utcStart"], first["utcStart"], "the zone of an occurrence is not changed alone"
		)

	def test_the_desks_limits_and_a_batch_too_big_are_said_as_rate_limits(self):
		from suite.calendar.doctype.calendar_event import calendar_event

		self._as(PERSON)
		event = {
			"calendarIds": {self._calendar(): True},
			"title": "x",
			"start": "2030-04-08T10:00:00",
			"duration": "PT1H",
		}
		with patch.object(
			calendar_event,
			"add_calendar_event",
			side_effect=frappe.RateLimitExceededError("Too many requests"),
		):
			limited = self._set(create={"k": event})
		self.assertEqual(limited["notCreated"]["k"]["type"], "rateLimit")
		self.assertNotIn("properties", limited["notCreated"]["k"], "the desk's limits name no property")
		many = self._set(create={f"k{n}": {"title": "x"} for n in range(calendars.MAX_EVENTS_PER_SET + 1)})
		kinds = sorted(error["type"] for error in many["notCreated"].values())
		self.assertEqual(kinds.count("rateLimit"), 1, "one past the limit waits")
		self.assertEqual(kinds.count("invalidProperties"), calendars.MAX_EVENTS_PER_SET)

	# The calendars the person only reads: the ERP's dates, and a colleague's calendar shared with them.

	def _erp_only(self):
		if not (self.todo and self.fair):
			self.skipTest("no provider of the ERP's dates here")

	def _desk_calendars(self, account):
		"""The calendars the desk's calendar page lists for the session's person, in their language."""
		from frappe.translate import get_user_lang
		from suite.calendar.api import get_calendars_with_shared

		previous = frappe.local.lang
		frappe.local.lang = get_user_lang(frappe.session.user)
		try:
			return get_calendars_with_shared(account, erp_dates=1)
		finally:
			frappe.local.lang = previous

	def _query(self, box=BOX, **arguments):
		answer = self._calls(("CalendarEvent/query", {"accountId": jmap.account_id(box), **arguments}))[0]
		self.assertEqual(answer[0], "CalendarEvent/query", answer)
		return answer[1]

	def test_the_erp_dates_are_listed_read_only_with_the_desks_names_and_colours(self):
		from suite.calendar.jmap_events import get_calendars
		from suite.mail.jmap import get_account_client

		self._erp_only()
		# The person reads French, which has the words of the sources; the request's language is the client's,
		# settled before its token named the person: English here.
		spoken = frappe.db.get_value("User", PERSON, "language")
		frappe.db.set_value("User", PERSON, "language", "fr")
		frappe.cache.hdel("lang", PERSON)
		self.addCleanup(frappe.cache.hdel, "lang", PERSON)
		self.addCleanup(frappe.db.set_value, "User", PERSON, "language", spoken)
		french = frappe._("To-dos and tasks", lang="fr")
		self.assertNotEqual(french, "To-dos and tasks", "a real translation")
		self._as(PERSON)
		desk = {row["id"]: row for row in self._desk_calendars(self.account) if row["id"].startswith("erp:")}
		frappe.local.lang = "en"
		listed = self._calls(("Calendar/get", {"accountId": jmap.account_id(BOX), "ids": None}))[0][1]["list"]
		self.assertEqual(frappe.local.lang, "en", "the request's language again, once answered")
		erp = {calendars._raw(c["id"], "C"): c for c in listed if _read_only(c["id"]) == "erp"}
		self.assertEqual(list(erp), list(desk), "the desk's, in its order")
		self.assertIn("erp:tasks", erp)
		for raw, calendar in erp.items():
			row = desk[raw]
			self.assertEqual(calendar["name"], row["_name"], raw)
			self.assertEqual(calendar["color"], calendars.ERP_COLORS[row["palette"]], raw)
			self.assertEqual(calendar["isVisible"], bool(row["visible"]), "switched on or off as in the desk")
			self.assertFalse(calendar["isDefault"], raw)
			self.assertTrue(calendar["myRights"]["mayReadItems"], raw)
			self.assertEqual(
				{right for right, on in calendar["myRights"].items() if on},
				{"mayReadItems", "mayReadFreeBusy"},
				"no right to write",
			)
		self.assertEqual(erp["erp:tasks"]["name"], french, "their language, not the request's")
		# What a Sales User may not open is not offered: the leaves, the employees, the holiday lists, the invoices.
		for source in ("leaves", "birthdays", "holidays", "invoices"):
			self.assertNotIn(f"erp:{source}", erp)
		# The person's own come first, as they were.
		own = [c for c in listed if not _read_only(c["id"])]
		self.assertEqual(listed[: len(own)], own)
		kept = get_calendars(get_account_client(self.account))
		self.assertEqual([c["id"] for c in own], [calendars._calendar_id(c["id"]) for c in kept])
		self.assertTrue(all(c["myRights"]["mayWriteOwn"] for c in own))
		self.assertEqual(sum(1 for c in listed if c["isDefault"]), 1)
		self.assertTrue(next(c for c in listed if c["isDefault"]) in own)

	def test_the_erp_dates_are_read_in_a_window_under_ids_of_their_own(self):
		self._erp_only()
		self._as(PERSON)
		events = self._window(FEBRUARY)
		todo = next(e for e in events if e.get("title") == TODO_TITLE)
		fair = next(e for e in events if e.get("title") == FAIR_TITLE)
		tasks, dated = calendars._calendar_id("erp:tasks"), calendars._calendar_id("erp:events")
		self.assertEqual(calendars._raw(todo["id"], "V"), f"erp:tasks:todo:{self.todo}")
		self.assertEqual(todo["calendarIds"], {tasks: True})
		self.assertEqual(
			(todo["start"], todo["duration"], todo["showWithoutTime"]), ("2030-02-11T00:00:00", "P1D", True)
		)
		self.assertNotIn("utcStart", todo, "a day keeps its day")
		self.assertTrue(todo["links"]["document"]["href"].endswith(f"/app/todo/{self.todo}"))
		self.assertEqual(fair["calendarIds"], {dated: True})
		self.assertEqual(
			(fair["utcStart"], fair["utcEnd"]),
			("2030-02-12T09:00:00Z", "2030-02-12T10:30:00Z"),
			"10:00 to 11:30 on the instance's clock, winter time",
		)
		self.assertEqual((fair["freeBusyStatus"], fair["status"]), ("free", "confirmed"))
		# The same ids at the next read, and outside the window, none.
		self.assertTrue({todo["id"], fair["id"]} <= {e["id"] for e in self._window(FEBRUARY)})
		self.assertNotIn(TODO_TITLE, {e.get("title") for e in self._window(JULY)})
		# By calendar: the ERP's tasks alone, or the person's own alone.
		tasks_only = self._query(filter={**FEBRUARY, "inCalendars": [tasks]}, expandRecurrences=True)["ids"]
		self.assertIn(todo["id"], tasks_only)
		self.assertNotIn(fair["id"], tasks_only)
		own_only = self._query(filter={**JANUARY, "inCalendars": [self._calendar()]}, expandRecurrences=True)
		self.assertTrue(own_only["ids"] and all(_read_only(i) is None for i in own_only["ids"]))
		# Asked for by id in a request of its own: read again, in the window the person queried.
		aid = jmap.account_id(BOX)
		got = self._calls(
			(
				"CalendarEvent/get",
				{"accountId": aid, "ids": [todo["id"], fair["id"]], "properties": ["title"]},
			)
		)[0][1]
		self.assertEqual(([e["title"] for e in got["list"]], got["notFound"]), ([TODO_TITLE, FAIR_TITLE], []))
		# Outside every window the person queried, and far from today: not looked for.
		frappe.cache().delete_value(calendars._windows_key())
		gone = self._calls(("CalendarEvent/get", {"accountId": aid, "ids": [todo["id"]]}))[0][1]
		self.assertEqual(gone["notFound"], [todo["id"]])

	def test_the_erp_dates_follow_the_persons_own_events_page_by_page(self):
		self._erp_only()
		self._as(PERSON)
		query = {
			"filter": {"after": "2030-01-01T00:00:00Z", "before": "2030-03-01T00:00:00Z"},
			"expandRecurrences": True,
		}
		whole = self._query(**query, calculateTotal=True)
		kinds = [_read_only(i) for i in whole["ids"]]
		own = kinds.count(None)
		self.assertGreaterEqual(own, 4, "three weekly occurrences and the day-long event")
		self.assertIn("erp", kinds)
		self.assertEqual(kinds[:own], [None] * own, "the person's own first, then the read-only ones")
		self.assertEqual(whole["total"], len(whole["ids"]))
		paged, position = [], 0
		while True:
			page = self._query(**query, position=position, limit=3)
			self.assertEqual(page["position"], position)
			paged += page["ids"]
			position += len(page["ids"])
			if len(page["ids"]) < 3:
				break
		self.assertEqual(paged, whole["ids"], "pages of three, across the two")
		self.assertEqual(self._query(**query, position=-1)["ids"], whole["ids"][-1:], "from the end")
		counted = self._query(**query, limit=0, calculateTotal=True)
		self.assertEqual((counted["ids"], counted["total"]), ([], whole["total"]))
		# A date renamed keeps its id, and the query's state says it changed.
		february = {"filter": FEBRUARY, "expandRecurrences": True}
		first = self._query(**february)
		frappe.db.set_value("ToDo", self.todo, "description", TODO_TITLE + " (sooner)")
		try:
			kept = self._query(**february)
			calendars._forget_read_only_events()
			renamed = self._query(**february)
		finally:
			frappe.db.set_value("ToDo", self.todo, "description", TODO_TITLE)
			calendars._forget_read_only_events()
		self.assertEqual(kept["queryState"], first["queryState"], "the window as it was read, a little while")
		self.assertEqual(renamed["ids"], first["ids"])
		self.assertNotEqual(renamed["queryState"], first["queryState"])
		self.assertEqual(self._query(**february)["queryState"], first["queryState"])

	def test_a_date_of_the_erp_is_never_written(self):
		from datetime import date

		self._erp_only()
		self._as(PERSON)
		events = self._window(FEBRUARY)
		todo = next(e for e in events if e.get("title") == TODO_TITLE)
		fair = next(e for e in events if e.get("title") == FAIR_TITLE)
		tasks = calendars._calendar_id("erp:tasks")
		base = {"title": "x", "start": "2030-02-14T10:00:00", "duration": "PT1H", "timeZone": "Europe/Zurich"}
		answer = self._set(
			create={
				"into": {**base, "calendarIds": {tasks: True}},
				"mine": {**base, "calendarIds": {self._calendar(): True}, "title": "Mine, beside the ERP's"},
			},
			update={todo["id"]: {"title": "Changed here"}},
			destroy=[todo["id"], fair["id"]],
		)
		refusal = calendars._read_only_refusal("erp")
		self.assertEqual(refusal["type"], "forbidden")
		self.assertTrue(refusal["description"])
		self.assertEqual(answer["notCreated"], {"into": refusal})
		self.assertEqual(answer["notUpdated"], {todo["id"]: refusal})
		self.assertEqual(answer["notDestroyed"], {todo["id"]: refusal, fair["id"]: refusal})
		self.assertEqual((answer["updated"], answer["destroyed"]), ({}, []))
		# Each object for itself: the person's own event is made, and is not moved there either.
		mine = answer["created"]["mine"]["id"]
		try:
			moved = self._set(update={mine: {"calendarIds": {tasks: True}}})
			self.assertEqual(moved["notUpdated"], {mine: refusal})
		finally:
			self.assertEqual(self._set(destroy=[mine])["destroyed"], [mine])
		self.assertEqual(
			frappe.db.get_value("ToDo", self.todo, ["description", "date", "status"]),
			(TODO_TITLE, date(2030, 2, 11), "Open"),
		)
		self.assertTrue(frappe.db.exists("Event", self.fair))

	def test_without_the_roles_none_of_the_erp_data_the_desk_would_not_show(self):
		from suite.calendar import sources

		self._erp_only()
		self._as(READER)
		listed = self._calls(("Calendar/get", {"accountId": jmap.account_id(READER_BOX), "ids": None}))[0][1][
			"list"
		]
		erp = [calendars._raw(c["id"], "C") for c in listed if _read_only(c["id"]) == "erp"]
		desk = [
			row["id"] for row in self._desk_calendars(self.reader_account) if row["id"].startswith("erp:")
		]
		self.assertEqual(erp, desk, "what the desk lists them")
		for source in (
			"quotations",
			"deliveries",
			"subscriptions",
			"invoices",
			"leaves",
			"birthdays",
			"holidays",
			"projects",
			"planning",
			"bookings",
		):
			self.assertNotIn(f"erp:{source}", erp, "nothing they may not open")
		self._as(PERSON)
		theirs = [e["id"] for e in self._window(FEBRUARY) if e.get("title") in (TODO_TITLE, FAIR_TITLE)]
		self.assertEqual(len(theirs), 2)
		self._as(READER)
		# Every date they may read asked for (whose: "all"): still none of the person's, nor by their ids.
		sources.set_calendar_scope(self.reader_account, "all")
		try:
			titles = {e.get("title") for e in self._window(FEBRUARY, box=READER_BOX)}
			self.assertFalse({TODO_TITLE, FAIR_TITLE} & titles, titles)
			got = self._calls(
				("CalendarEvent/get", {"accountId": jmap.account_id(READER_BOX), "ids": theirs})
			)
			self.assertEqual((got[0][1]["list"], sorted(got[0][1]["notFound"])), ([], sorted(theirs)))
		finally:
			sources.set_calendar_scope(self.reader_account, "mine")

	def test_a_website_user_gets_none_of_the_erp_data(self):
		"""NeoMail is the desk's: a Website User is refused before anything is read, and the Suite gives them no
		calendar account. Had they one of their own and were they let through, the Suite would still give them none
		of the ERP's dates: its own checks apply, as the facade asks it as them."""
		self._as(PORTAL)
		self.assertEqual(frappe.db.get_value("User", PORTAL, "user_type"), "Website User")
		aid = jmap.account_id(PORTAL_BOX)
		refused = self._request(("Calendar/get", {"accountId": aid, "ids": None}))
		self.assertEqual(refused.status_code, 403, "NeoMail is the desk's")
		self.assertIsNone(calendars._person_account())
		self._erp_only()
		with (
			patch.object(jmap, "_is_desk_user", return_value=True),
			patch.object(calendars, "_person_account", return_value=self.portal_account),
		):
			listed, query = self._calls(
				("Calendar/get", {"accountId": aid, "ids": None}),
				("CalendarEvent/query", {"accountId": aid, "filter": FEBRUARY, "calculateTotal": True}),
			)
		self.assertEqual(listed[0], "Calendar/get", listed)
		self.assertEqual([c["name"] for c in listed[1]["list"] if _read_only(c["id"])], [])
		self.assertEqual((query[1]["ids"], query[1]["total"]), ([], 0))
		self.assertEqual(calendars._read_only_calendars(self.portal_account), {})
		self.assertEqual(
			calendars._erp_read(
				self.portal_account,
				calendars._utc_date(FEBRUARY["after"], "after"),
				calendars._utc_date(FEBRUARY["before"], "before"),
			),
			[],
		)

	def test_a_calendar_shared_with_the_person_is_shown_read_only(self):
		"""A colleague's calendar the mail server lets the person read: listed and read as the desk does, written never.
		The colleague's account is a calendar kept in the instance here, its share faked: the Suite lists it among the
		calendars shared with the person, and opens it for them. Another calendar of that account is not shared, and
		nothing of it is read; a share of the free and busy time alone gives no events."""
		from suite.calendar import api as calendar_api
		from suite.calendar import jmap_events, local
		from suite.calendar.doctype.calendar.calendar import add_calendar
		from suite.calendar.jmap_events import create_events, get_calendars
		from suite.mail.jmap import get_account_client

		self._as(READER)
		colleague = get_account_client(self.reader_account)
		calendar = get_calendars(colleague)[0]
		hidden = str(add_calendar(self.reader_account, "Colleague's own"))
		uid, private_uid = (f"mc-cal-shared-{frappe.generate_hash(length=8)}" for _n in range(2))
		row = {"duration": "PT2H", "time_zone": "Europe/Zurich", "show_without_time": False}
		create_events(
			colleague,
			self.reader_account,
			[
				{
					**row,
					"creation_id": "s",
					"uid": uid,
					"calendar_ids": [calendar["id"]],
					"title": "Colleague's workshop",
					"start": "2030-02-13T14:00:00",
				},
				{
					**row,
					"creation_id": "p",
					"uid": private_uid,
					"calendar_ids": [hidden],
					"title": "Colleague's own meeting",
					"start": "2030-02-14T14:00:00",
				},
			],
		)
		private = next(e for e in self._window(FEBRUARY, box=READER_BOX) if e.get("uid") == private_uid)
		# How the person would name it, were its calendar shared with them.
		private_id = calendars._event_id(f"{self.reader_account}|{calendars._raw(private['id'], 'V')}")
		shared = f"{self.reader_account}|{calendar['id']}"
		real = local.get_local_client

		def opened(account, user=None, ignore_permissions=False):
			# The share: the mail server lets the person read the colleague's account.
			return real(
				account, user=user, ignore_permissions=ignore_permissions or account == self.reader_account
			)

		with (
			patch.object(calendar_api, "_shared_calendars", return_value=[shared]),
			patch.object(local, "get_local_client", side_effect=opened),
		):
			self._as(PERSON)
			aid = jmap.account_id(BOX)
			listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
			theirs = next(c for c in listed if c["id"] == calendars._calendar_id(shared))
			self.assertEqual(
				(theirs["name"], theirs["isVisible"], theirs["isDefault"]), (calendar["name"], True, False)
			)
			self.assertEqual(
				{right for right, on in theirs["myRights"].items() if on}, {"mayReadItems", "mayReadFreeBusy"}
			)
			workshop = next(e for e in self._window(FEBRUARY) if e.get("uid") == uid)
			self.assertEqual(workshop["calendarIds"], {theirs["id"]: True})
			self.assertEqual(_read_only(workshop["id"]), "shared")
			self.assertEqual(
				(workshop["utcStart"], workshop["utcEnd"]), ("2030-02-13T13:00:00Z", "2030-02-13T15:00:00Z")
			)
			got = self._calls(("CalendarEvent/get", {"accountId": aid, "ids": [workshop["id"]]}))[0][1]
			self.assertEqual(
				[e["title"] for e in got["list"]], ["Colleague's workshop"], "by id, from its account"
			)
			answer = self._set(
				create={
					"k": {
						"calendarIds": {theirs["id"]: True},
						"title": "x",
						"start": "2030-02-13T09:00:00",
						"duration": "PT1H",
					}
				},
				update={workshop["id"]: {"title": "Changed here"}},
				destroy=[workshop["id"]],
			)
			refusal = calendars._read_only_refusal("shared")
			# The calendar of that account that is not shared: nothing of it, even by id.
			self.assertNotIn(private_uid, {e.get("uid") for e in self._window(FEBRUARY)})
			hidden_got = self._calls(("CalendarEvent/get", {"accountId": aid, "ids": [private_id]}))[0][1]
			self.assertEqual((hidden_got["list"], hidden_got["notFound"]), ([], [private_id]))
			# Past the cap, the shared events keep their share beside the ERP's dates.
			with patch.object(calendars, "MAX_EVENTS", 2):
				capped = calendars._read_only_events(
					self.account,
					calendars._utc_date(FEBRUARY["after"], "after"),
					calendars._utc_date(FEBRUARY["before"], "before"),
				)
			self.assertIn(workshop["id"], [facade for facade, _event in capped])
			self.assertLessEqual(len(capped), 2)
			# Shared for the free and busy time alone: listed so, and none of its events.
			real_calendars = jmap_events.get_calendars

			def free_busy(client, ids=None):
				return [
					{**c, "myRights": {"mayReadFreeBusy": True}} if c.get("id") == calendar["id"] else c
					for c in real_calendars(client, ids)
				]

			with patch.object(jmap_events, "get_calendars", side_effect=free_busy):
				listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
				only_time = next(c for c in listed if c["id"] == theirs["id"])
				self.assertEqual(
					{right for right, on in only_time["myRights"].items() if on}, {"mayReadFreeBusy"}
				)
				self.assertNotIn(uid, {e.get("uid") for e in self._window(FEBRUARY)})
				none = self._calls(("CalendarEvent/get", {"accountId": aid, "ids": [workshop["id"]]}))[0][1]
				self.assertEqual(none["notFound"], [workshop["id"]])
		self.assertEqual(refusal["type"], "forbidden")
		self.assertEqual(
			(answer["notCreated"], answer["notUpdated"], answer["notDestroyed"]),
			({"k": refusal}, {workshop["id"]: refusal}, {workshop["id"]: refusal}),
		)
		# Without the share, nothing of it.
		listed = self._calls(("Calendar/get", {"accountId": jmap.account_id(BOX), "ids": None}))[0][1]["list"]
		self.assertNotIn(calendars._calendar_id(shared), {c["id"] for c in listed})
		self.assertNotIn(uid, {e.get("uid") for e in self._window(FEBRUARY)})
		gone = self._calls(
			("CalendarEvent/get", {"accountId": jmap.account_id(BOX), "ids": [workshop["id"]]})
		)
		self.assertEqual(gone[0][1]["notFound"], [workshop["id"]], "nor by id")
		self._as(READER)
		self.assertEqual(
			[e["title"] for e in self._window(FEBRUARY, box=READER_BOX) if e.get("uid") == uid],
			["Colleague's workshop"],
			"still the colleague's, unchanged",
		)

	def test_the_pages_of_a_window_read_the_erp_dates_once(self):
		"""NeoMail pages a window and asks its total, a request a page: the ERP's dates are read once for all of them,
		which then agree."""
		from suite.calendar import sources

		self._erp_only()
		self._as(PERSON)
		query = {"filter": FEBRUARY, "expandRecurrences": True}
		with patch.object(sources, "virtual_events", wraps=sources.virtual_events) as read:
			first = self._query(**query, position=0, limit=1, calculateTotal=True)
			reads = read.call_count
			pages = [first]
			while sum(len(page["ids"]) for page in pages) < first["total"]:
				pages.append(self._query(**query, position=sum(len(page["ids"]) for page in pages), limit=1))
			self.assertGreaterEqual(first["total"], 2, "the to-do and the Event")
			self.assertEqual(read.call_count, reads, "every page from what the first one read")
			whole = self._query(**query)["ids"]
		self.assertEqual([i for page in pages for i in page["ids"]], whole)

	def test_a_date_asked_for_by_id_is_looked_for_within_bounds(self):
		from suite.calendar import sources

		self._erp_only()
		self._as(PERSON)
		aid = jmap.account_id(BOX)
		events = self._window(FEBRUARY)
		todo = next(e for e in events if e.get("title") == TODO_TITLE)
		fair = next(e for e in events if e.get("title") == FAIR_TITLE)
		missing = calendars._event_id("erp:tasks:todo:no-such-todo")

		def get(*ids, calls=1):
			return self._calls(*[("CalendarEvent/get", {"accountId": aid, "ids": list(ids)})] * calls)

		with patch.object(sources, "virtual_events", wraps=sources.virtual_events) as read:
			# A source not offered to them (the holiday lists), or switched off (the deliveries): not looked for.
			unread = [
				calendars._event_id("erp:holidays:holiday:Somewhere:2030-02-01"),
				calendars._event_id("erp:deliveries:sales_order:SO-0001"),
			]
			self.assertEqual(sorted(get(*unread)[0][1]["notFound"]), sorted(unread))
			self.assertEqual(read.call_count, 0)
			# One that is on: each window read once in a request, however many of its calls ask.
			calendars._forget_read_only_events()
			self.assertEqual(get(missing)[0][1]["notFound"], [missing])
			once = read.call_count
			self.assertGreater(once, 0)
			calendars._forget_read_only_events()
			read.reset_mock()
			self.assertTrue(all(answer[1]["notFound"] == [missing] for answer in get(missing, calls=3)))
			self.assertEqual(read.call_count, once)
		# So many ids a call at most are looked for again.
		with patch.object(calendars, "MAX_LOOKUPS", 1):
			capped = get(todo["id"], fair["id"])[0][1]
		self.assertEqual(
			([e["id"] for e in capped["list"]], capped["notFound"]), ([todo["id"]], [fair["id"]])
		)
		# Today's window is not read again when one the person queried covers it.
		today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
		around = {
			"after": calendars._utc_text(today - timedelta(days=100)),
			"before": calendars._utc_text(today + timedelta(days=380)),
		}
		self._query(filter=around, expandRecurrences=True)
		with patch.object(calendars, "_erp_events", wraps=calendars._erp_events) as windows:
			get(missing)
		read_windows = [(call.args[1], call.args[2]) for call in windows.call_args_list]
		self.assertIn(
			(calendars._utc_date(around["after"], "a"), calendars._utc_date(around["before"], "b")),
			read_windows,
		)
		self.assertNotIn((today - calendars.TODAY_BEFORE, today + calendars.TODAY_AFTER), read_windows)

	def test_a_busy_source_is_read_in_halves_down_to_a_day(self):
		"""A source gives its oldest dates first, and the Suite keeps a page of them a read: a chunk where one gives a
		whole page is read again in halves for it, down to a day; a day that still fills a page is said, once."""
		from suite.calendar import sources

		if not _erp_dates_offered():
			self.skipTest("no ERP's dates here")
		self._as(PERSON)
		page = sources.MAX_PER_SOURCE

		def entry(source, key, day):
			return {
				"id": f"{source}:{key}",
				"calendars": [{"calendar_id": source}],
				"title": key,
				"start": f"{day}T00:00:00",
				"duration": "P1D",
				"show_without_time": 1,
			}

		def busy(account, from_date, to_date):
			first, last = (calendars._utc_date(moment, "x") for moment in (from_date, to_date))
			invoices, tasks = [], []
			day = first
			while day < last:
				text = day.strftime("%Y-%m-%d")
				invoices += [
					entry("erp:invoices", f"{text}:{n:03d}", text)
					for n in range(400 if text == "2030-02-20" else 15)
				]
				tasks.append(entry("erp:tasks", text, text))
				day += timedelta(days=1)
			return invoices[:page] + tasks[:page]

		after, before = (calendars._utc_date(FEBRUARY[key], key) for key in ("after", "before"))
		with (
			patch.object(sources, "virtual_events", side_effect=busy) as read,
			patch.object(frappe, "log_error") as logged,
		):
			dates = calendars._erp_read(self.account, after, before)
			again = calendars._erp_read(self.account, after, before)
		kinds = [next(iter(event["calendarIds"])) for _facade, event in dates]
		self.assertEqual(kinds.count("erp:invoices"), 27 * 15 + page, "every day, the full one cut at a page")
		self.assertEqual(kinds.count("erp:tasks"), 28)
		self.assertEqual(len(again), len(dates))
		self.assertLessEqual(read.call_count, 2 * calendars.ERP_SPLIT_READS)
		self.assertEqual(
			[call.args[0] for call in logged.call_args_list],
			["MailCraft calendars: dates of the ERP were cut"],
			"once",
		)

	def test_a_failure_of_the_read_only_calendars_leaves_the_persons_own(self):
		from suite.calendar import api as calendar_api

		self._as(PERSON)
		aid = jmap.account_id(BOX)
		with (
			patch.object(calendar_api, "get_calendars_with_shared", side_effect=RuntimeError("down")),
			patch.object(frappe, "log_error") as logged,
		):
			listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0]
			weekly = [e for e in self._window(JANUARY) if e.get("uid") == "mc-cal-weekly"]
			counted = self._query(filter=JANUARY, expandRecurrences=True, calculateTotal=True)
		self.assertEqual(listed[0], "Calendar/get", listed)
		self.assertTrue(listed[1]["list"])
		self.assertFalse([c for c in listed[1]["list"] if _read_only(c["id"])])
		self.assertEqual(len(weekly), 3, "the person's own events, as ever")
		self.assertEqual(counted["total"], len(counted["ids"]))
		self.assertEqual(
			[call.args[0] for call in logged.call_args_list],
			["MailCraft calendars: the read-only calendars could not be read"],
			"said once in a while",
		)

	def test_the_persons_own_calendars_alone_read_nothing_else(self):
		from suite.calendar import api as calendar_api

		self._as(PERSON)
		aid = jmap.account_id(BOX)
		own = self._calendar()
		with patch.object(
			calendar_api, "get_calendars_with_shared", wraps=calendar_api.get_calendars_with_shared
		) as listing:
			found = self._query(
				filter={**JANUARY, "inCalendars": [own]}, expandRecurrences=True, calculateTotal=True
			)
			listed = self._calls(("Calendar/get", {"accountId": aid, "ids": [own]}))[0][1]["list"]
			got = self._calls(("CalendarEvent/get", {"accountId": aid, "ids": found["ids"]}))[0][1]
		self.assertEqual([c["id"] for c in listed], [own])
		self.assertTrue(found["ids"] and len(got["list"]) == len(found["ids"]))
		self.assertEqual(listing.call_count, 0)

	def test_a_window_past_2100_is_empty_not_a_failure(self):
		self._as(PERSON)
		far = self._query(
			# Its last chunk of 90 days would reach past the year 9999.
			filter={"after": "9999-10-01T00:00:00Z", "before": "9999-12-31T00:00:00Z"},
			expandRecurrences=True,
			calculateTotal=True,
		)
		self.assertEqual((far["ids"], far["total"]), ([], 0))

	def test_a_short_page_of_the_persons_own_is_not_followed_by_the_others(self):
		"""A server that gives fewer of the person's events than asked, before the end it said: the page is theirs
		alone, the read-only ones come after the last of them."""
		from suite.calendar import jmap_events

		self._as(PERSON)
		real = jmap_events.query_events

		def short(client, **arguments):
			answer = real(client, **arguments)
			return {**answer, "ids": (answer.get("ids") or [])[:1]}

		window = {"after": "2030-01-01T00:00:00Z", "before": "2030-03-01T00:00:00Z"}
		with patch.object(jmap_events, "query_events", side_effect=short):
			page = self._query(filter=window, expandRecurrences=True, limit=10)
		self.assertEqual(len(page["ids"]), 1)
		self.assertIsNone(_read_only(page["ids"][0]))

	def test_a_documents_address_writes_its_name(self):
		event = calendars._erp_event(
			{
				"id": "erp:holidays:holiday:Public holidays 2030:2030-02-01",
				"calendars": [{"calendar_id": "erp:holidays"}],
				"start": "2030-02-01T00:00:00",
				"duration": "P1D",
				"show_without_time": 1,
				"route": "/app/holiday-list/Public holidays 2030",
			}
		)
		self.assertTrue(
			event["links"]["document"]["href"].endswith("/app/holiday-list/Public%20holidays%202030"),
			event["links"],
		)
		for elsewhere in ("https://example.org/app/x/y", "/login", "/app/holiday-list"):
			self.assertNotIn("links", calendars._erp_event({**event, "route": elsewhere}), elsewhere)

	def test_the_persons_language_is_left_as_it_was(self):
		from frappe.translate import get_user_lang

		self._as(PERSON)
		saved = frappe.local.lang
		del frappe.local.lang
		try:
			with calendars._persons_language():
				self.assertEqual(frappe.local.lang, get_user_lang(PERSON))
			self.assertFalse(hasattr(frappe.local, "lang"), "never set, left unset")
		finally:
			frappe.local.lang = saved
		frappe.local.lang = "xx"
		with calendars._persons_language():
			pass
		self.assertEqual(frappe.local.lang, "xx")
