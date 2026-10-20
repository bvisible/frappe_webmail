# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The person's calendars as NeoMail's (mailcraft_calendars, JMAP for Calendars; maintenance#1630, step 3).

Read on the calendar the Suite keeps in the instance for a person without a mailbox server account (the clone's
mailboxes have no password, so their calendars cannot be reached): its events of a window, each occurrence apart, with
their start and end in UTC worked out from their zone, summer time included. Only the person's own calendar, chosen
by the facade. NeoMail does what the desk does (Jérémy, 17.10): events created, changed and deleted there, a series or
one of its occurrences, through the Suite's own calendar functions.

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
NOVEMBER = {"after": "2030-11-01T00:00:00Z", "before": "2030-12-01T00:00:00Z"}


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
		self.trial = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
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
		# A request as the facade reads it, with the headers the Suite's rate limit reads when an event is written.
		request = SimpleNamespace(
			get_data=lambda: body, headers={}, method="POST", path="/api/method/" + jmap.METHOD_PREFIX + "api"
		)
		with patch.object(frappe.local, "request", request, create=True):
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

	def test_invited_under_two_of_their_addresses_the_first_answers(self):
		"""record_rsvp answers for the first of the person's entries: a change of the other is not taken for an answer
		(it would land on the wrong entry), and is written as before."""
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
			self.assertEqual((other["notUpdated"], answer.call_count), ({}, 0))
			first = self._set(
				update={event["id"]: {"participants": self._answered(self._get(event["id"]))}},
				sendSchedulingMessages=True,
			)
		self.assertEqual(first["notUpdated"], {})
		answer.assert_called_once_with(self.account, calendars._raw(event["id"], "V"), "accepted")

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
				{c["name"]: c["color"] for c in listed},
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
		many = self._set(create={f"k{n}": {"title": "x"} for n in range(calendars.MAX_EVENTS_PER_SET + 1)})
		kinds = sorted(error["type"] for error in many["notCreated"].values())
		self.assertEqual(kinds.count("rateLimit"), 1, "one past the limit waits")
		self.assertEqual(kinds.count("invalidProperties"), calendars.MAX_EVENTS_PER_SET)
