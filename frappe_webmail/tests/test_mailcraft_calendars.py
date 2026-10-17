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
		listed = self._calls(("Calendar/get", {"accountId": aid, "ids": None}))[0][1]["list"]
		self.assertTrue(listed and all(c["id"].startswith("C") for c in listed))
		self.assertTrue(listed[0]["myRights"]["mayWriteOwn"], "the person's own calendar, as in the desk")

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
			"title": "Visite de chantier",
			"start": "2030-03-04T10:00:00",
			"duration": "PT2H",
			"timeZone": "Europe/Zurich",
			"showWithoutTime": False,
			"description": "Avec le maître d'ouvrage",
			"locations": {"l1": {"@type": "Location", "name": "Rue du Lac 12, Vevey"}},
		}
		made = self._set(create={"k": event})
		self.assertEqual(made["notCreated"], {})
		vid = made["created"]["k"]["id"]
		march = {"after": "2030-03-01T00:00:00Z", "before": "2030-04-01T00:00:00Z"}
		found = next(e for e in self._window(march) if e["id"] == vid)
		self.assertEqual(
			(found["title"], found["utcStart"], found["utcEnd"]),
			("Visite de chantier", "2030-03-04T09:00:00Z", "2030-03-04T11:00:00Z"),
		)
		self.assertEqual([place["name"] for place in found["locations"].values()], ["Rue du Lac 12, Vevey"])
		# Sent again (its answer lost on the way): the same event, not a second one.
		again = self._set(create={"k2": event})
		self.assertEqual(again["created"]["k2"]["id"], vid)
		self.assertEqual(sum(1 for e in self._window(march) if e.get("title") == "Visite de chantier"), 1)
		# Changed: the properties named replace the stored ones, the others stay.
		changed = self._set(
			update={vid: {"title": "Visite de chantier (déplacée)", "start": "2030-03-05T14:00:00"}}
		)
		self.assertEqual((changed["updated"], changed["notUpdated"]), ({vid: None}, {}))
		moved = next(e for e in self._window(march) if e["id"] == vid)
		self.assertEqual(
			(moved["title"], moved["utcStart"], moved["duration"]),
			("Visite de chantier (déplacée)", "2030-03-05T13:00:00Z", "PT2H"),
		)
		self.assertEqual(moved["description"], "Avec le maître d'ouvrage")
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
			"title": "Atelier (renuméroté)",
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
			changed = self._set(update={third["id"]: {"title": "Atelier (renuméroté, salle B)"}})
			self.assertEqual(changed["notUpdated"], {})
			gone = self._set(destroy=[second["id"]])
			self.assertEqual(gone["notDestroyed"], {})
			alone = self._calls(
				("CalendarEvent/get", {"accountId": jmap.account_id(BOX), "ids": [third["id"]]})
			)
			self.assertEqual([e["title"] for e in alone[0][1]["list"]], ["Atelier (renuméroté, salle B)"])
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
			"title": "Atelier (série)",
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
			changed = self._set(update={weekly[1]["id"]: {"title": "Atelier (salle C)"}})
			self.assertEqual(changed["notUpdated"], {})
			self.assertEqual(
				[e["title"] for e in ours()], ["Atelier (série)", "Atelier (salle C)", "Atelier (série)"]
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
			"title": "Réunion d'équipe",
			"start": "2030-05-06T08:30:00",
			"duration": "PT1H",
			"timeZone": "Europe/Zurich",
			"recurrenceRule": {"@type": "RecurrenceRule", "frequency": "weekly", "count": 3},
		}
		self.assertEqual(self._set(create={"s": series})["notCreated"], {})
		may = {"after": "2030-05-01T00:00:00Z", "before": "2030-06-01T00:00:00Z"}

		def occurrences():
			return sorted(
				(e for e in self._window(may) if e.get("title", "").startswith("Réunion d'équipe")),
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
		self.assertEqual(self._set(update={third: {"title": "Réunion d'équipe (salle B)"}})["notUpdated"], {})
		self.assertEqual(self._set(destroy=[second])["notDestroyed"], {})
		after = occurrences()
		self.assertEqual([e["utcStart"] for e in after], ["2030-05-06T06:30:00Z", "2030-05-20T06:30:00Z"])
		self.assertEqual([e["title"] for e in after], ["Réunion d'équipe", "Réunion d'équipe (salle B)"])

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
			"title": "Revue",
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
		same = self._set(update={vid: {"title": "Revue (bis)", "organizerCalendarAddress": organizer}})
		self.assertEqual(same["notUpdated"], {})
		# Another organizer, or none: refused, nothing changed.
		for other in ("mailto:boss@example.com", None):
			refused = self._set(update={vid: {"organizerCalendarAddress": other, "title": "x"}})
			self.assertEqual(refused["notUpdated"][vid]["type"], "forbidden", other)
		self.assertEqual(self._get(vid)["title"], "Revue (bis)")
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
			title="Brouillon",
			start="2030-04-10T09:00:00",
			duration="PT30M",
			time_zone="Europe/Zurich",
		)
		vid = calendars._event_id(raw)
		self.assertEqual(self._set(update={vid: {"title": "Brouillon (renommé)"}})["notUpdated"], {})
		after = self._get(vid)
		self.assertEqual((after["title"], bool(after.get("isDraft"))), ("Brouillon (renommé)", True))

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
			title="Atelier", recurrenceRule={"@type": "RecurrenceRule", "frequency": "weekly", "count": 2}
		)
		april = {"after": "2030-04-01T00:00:00Z", "before": "2030-05-01T00:00:00Z"}
		first = next(
			e for e in sorted(self._window(april), key=lambda e: e["utcStart"]) if e.get("title") == "Atelier"
		)
		self.assertEqual(
			self._set(update={first["id"]: {"title": "Atelier (A)", "timeZone": "America/New_York"}})[
				"notUpdated"
			],
			{},
		)
		moved = next(e for e in self._window(april) if e.get("title") == "Atelier (A)")
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
