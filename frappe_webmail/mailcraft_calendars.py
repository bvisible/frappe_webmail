# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
JMAP for Calendars (draft-ietf-jmap-calendars) in MailCraft's facade (mailcraft_jmap): the person's own calendars as the
Suite keeps them (on the mail server, or in the instance for a person without a mailbox), read-only, with the events of
a window, each occurrence of a repeating event apart and with its start and end in UTC (`utcStart`, `utcEnd`, worked out
here: MailCraft has no time-zone database). NeoMail's calendar is then Neoffice's (maintenance#1630, step 3 of NeoMail's
programme; study: vault note Neoffice-Apps/20).

Offered where the Suite is installed, in the same one mailbox of the person as the address book
(mailcraft_contacts.contacts_mailbox). The calendar account is the person's own, chosen here and never named by the
client (`suite.calendar.feed._account_of`: their mailbox's, else the one kept in the instance, never created here): an
administrator's client would otherwise reach anyone's. Left out for now: the calendars others share with the person, and
the ERP's dates (`erp:`), whose titles carry customers, amounts and leaves that MailCraft would keep on the computer.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe.utils import cint

from frappe_webmail import mailcraft_jmap as jmap

CALENDARS = "urn:ietf:params:jmap:calendars"
# MailCraft reads from 90 days back to a year and a day ahead (456 days, crates/jmap/src/calendars.rs): a window a little
# longer than that, and no more.
MAX_SPAN = timedelta(days=500)
MAX_EVENTS = 5000
_DURATION = re.compile(r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_READ_ONLY = {
	"mayReadFreeBusy": True,
	"mayReadItems": True,
	"mayWriteAll": False,
	"mayWriteOwn": False,
	"mayUpdatePrivate": False,
	"mayRSVP": False,
	"mayAdmin": False,
	"mayDelete": False,
}


def suite_installed():
	return "suite" in frappe.get_installed_apps()


def _person_account():
	"""The person's own calendar account in the Suite, or None (no mailbox and no calendar kept in the instance)."""
	from suite.calendar.feed import _account_of

	return _account_of(frappe.session.user)


def session_parts(account):
	"""What the session of `account` (a Webmail Account) adds when it offers the calendars: its capabilities, and its
	account's; nothing for the person's other mailboxes, nor without the Suite or a calendar."""
	from frappe_webmail.mailcraft_contacts import contacts_mailbox

	if not suite_installed() or account.name != contacts_mailbox() or not _person_account():
		return {}, {}
	return {CALENDARS: {}}, {
		CALENDARS: {
			"maxCalendarsPerEvent": None,
			"minDateTime": "1970-01-01T00:00:00Z",
			"maxDateTime": "2100-01-01T00:00:00Z",
			"maxExpandedQueryDuration": "P500D",
			"maxParticipantsPerEvent": None,
			"mayCreateCalendar": False,
		}
	}


def _calendar_account(args):
	"""The facade account a call names, when it is the one that offers the calendars, and the person's Suite account."""
	from frappe_webmail.mailcraft_contacts import contacts_mailbox

	account = jmap._account(args.get("accountId"))
	suite_account = _person_account() if suite_installed() and account.name == contacts_mailbox() else None
	if not suite_account:
		raise jmap.JmapError("accountNotSupportedByMethod", "This mailbox offers no calendar.")
	return jmap.account_id(account.name), suite_account


def _client(suite_account):
	from suite.mail.jmap import get_account_client

	return get_account_client(suite_account)


def _reading(read):
	"""A read of the Suite, with its refusals said as JMAP says them."""
	try:
		return read()
	except frappe.PermissionError as e:
		raise jmap.JmapError("forbidden", str(e)) from e
	except Exception as e:
		if type(e).__name__ == "MailServerUnavailableError":
			raise jmap.JmapError("serverUnavailable", "The calendar server is not answering.") from e
		raise


def _calendar_id(raw):
	return "C" + jmap._b64(str(raw))


def _event_id(raw):
	return "V" + jmap._b64(str(raw))


def _raw(jmap_id, prefix):
	return jmap._unb64(jmap_id[1:]) if isinstance(jmap_id, str) and jmap_id[:1] == prefix else None


def calendar_get(args):
	aid, suite_account = _calendar_account(args)
	ids = _string_ids(args)
	from suite.calendar.jmap_events import get_calendars

	listed = []
	for calendar in _reading(lambda: get_calendars(_client(suite_account))):
		cid = _calendar_id(calendar.get("id"))
		if ids is not None and cid not in ids:
			continue
		listed.append(
			{
				"id": cid,
				"name": calendar.get("name") or "",
				"description": calendar.get("description"),
				"color": calendar.get("color"),
				"sortOrder": cint(calendar.get("sortOrder")),
				"isSubscribed": True,
				"isVisible": calendar.get("isVisible", True) is not False,
				"isDefault": bool(calendar.get("isDefault")),
				"includeInAvailability": "none",
				"myRights": dict(_READ_ONLY),
			}
		)
	found = {c["id"] for c in listed}
	return {
		"accountId": aid,
		"state": "0",
		"list": listed,
		"notFound": [i for i in (ids or []) if i not in found],
	}


def _utc_date(value, name):
	"""A UTCDate argument (`2026-10-17T00:00:00Z`) as an aware datetime; refused otherwise."""
	try:
		parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
	except (TypeError, ValueError):
		raise jmap.JmapError("invalidArguments", name) from None
	if parsed.tzinfo is None:
		raise jmap.JmapError("invalidArguments", name)
	return parsed.astimezone(timezone.utc)


def event_query(args):
	"""The ids of the events of a window (`after`, `before`, both asked, 400 days at most), in the person's calendars
	or those named (`inCalendars`); each occurrence apart when `expandRecurrences` is asked."""
	aid, suite_account = _calendar_account(args)
	criteria = args.get("filter") or {}
	if not isinstance(criteria, dict) or set(criteria) - {"after", "before", "inCalendars"}:
		raise jmap.JmapError("unsupportedFilter", "Only after, before and inCalendars are supported.")
	if "after" not in criteria or "before" not in criteria:
		raise jmap.JmapError("unsupportedFilter", "A window (after and before) is required.")
	after, before = _utc_date(criteria["after"], "after"), _utc_date(criteria["before"], "before")
	if before <= after or before - after > MAX_SPAN:
		raise jmap.JmapError("unsupportedFilter", "The window must be of 500 days at most.")
	query = {"after": after.strftime("%Y-%m-%dT%H:%M:%SZ"), "before": before.strftime("%Y-%m-%dT%H:%M:%SZ")}
	position = jmap._whole_number(args.get("position"), "position", 0)
	limit = jmap._whole_number(args.get("limit"), "limit")
	if limit is not None and limit < 0:
		raise jmap.JmapError("invalidArguments", "limit")
	if args.get("anchor") is not None:
		raise jmap.JmapError("invalidArguments", "anchor")
	used = MAX_EVENTS if limit is None else min(limit, MAX_EVENTS)
	asked_total = bool(args.get("calculateTotal"))
	answer = {
		"accountId": aid,
		"queryState": "0",
		"canCalculateChanges": False,
		"position": position,
		"ids": [],
	}
	if limit is None or limit > MAX_EVENTS:
		answer["limit"] = used
	if criteria.get("inCalendars") is not None:
		named = criteria["inCalendars"]
		if not isinstance(named, list) or len(named) > jmap.MAX_OBJECTS:
			raise jmap.JmapError("invalidArguments", "inCalendars")
		raws = [r for r in (_raw(c, "C") for c in named) if r]
		if not raws:
			return {**answer, "position": 0, **({"total": 0} if asked_total else {})}
		query = {
			"operator": "AND",
			"conditions": [query, {"operator": "OR", "conditions": [{"inCalendar": r} for r in raws]}],
		}
	from suite.calendar.jmap_events import query_events

	def read(start, size):
		return _reading(
			lambda: query_events(
				_client(suite_account),
				filter=query,
				position=start,
				limit=size,
				time_zone=_person_zone().key,
				expand_recurrences=bool(args.get("expandRecurrences")),
			)
		)

	# The Suite reads from a position on, and returns nothing for a limit of 0: the total, when it is needed first (a
	# position from the end, RFC 8620 §5.5) or alone, comes from a read of one.
	total = None
	if position < 0 or (asked_total and not used):
		total = cint(read(0, 1).get("total"))
		position = max(0, total + position) if position < 0 else position
	found = read(position, used) if used else {"ids": [], "total": total}
	ids = [_event_id(i) for i in found.get("ids") or []]
	if total is None and found.get("total") is not None:
		total = cint(found["total"])
	answer.update(
		position=position, ids=ids, queryState=hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
	)
	if asked_total:
		answer["total"] = total if total is not None else position + len(ids)
	return answer


def event_get(args):
	"""The events asked for (never all of them), read as the Suite keeps them, with their ids and calendars renamed for
	the facade and their UTC start and end."""
	aid, suite_account = _calendar_account(args)
	ids = _string_ids(args)
	if ids is None:
		raise jmap.JmapError("requestTooLarge", "Ask for the events by id (CalendarEvent/query).")
	properties = args.get("properties")
	if properties is not None and (
		not isinstance(properties, list) or not all(isinstance(p, str) for p in properties)
	):
		raise jmap.JmapError("invalidArguments", "properties")
	raws = {r: i for i, r in ((i, _raw(i, "V")) for i in ids) if r}
	from suite.calendar.jmap_events import get_events

	events = _reading(lambda: get_events(_client(suite_account), list(raws))) if raws else []
	listed = []
	for event in events:
		if event.get("id") not in raws:
			continue
		listed.append(_facade_event(event, properties))
	found = {e["id"] for e in listed}
	return {"accountId": aid, "state": "0", "list": listed, "notFound": [i for i in ids if i not in found]}


def event_set(args):
	"""The calendars are read-only for now: every change is refused, said for each."""
	aid, _suite_account = _calendar_account(args)
	creates, updates, destroys = args.get("create") or {}, args.get("update") or {}, args.get("destroy") or []
	if not isinstance(creates, dict) or not isinstance(updates, dict) or not isinstance(destroys, list):
		raise jmap.JmapError("invalidArguments", "create, update, destroy")
	refused = {"type": "forbidden", "description": "The calendars are read-only."}
	return {
		"accountId": aid,
		"oldState": "0",
		"newState": "0",
		"notCreated": {k: refused for k in creates},
		"notUpdated": {k: refused for k in updates},
		"notDestroyed": {k: refused for k in destroys if isinstance(k, str)},
	}


def _string_ids(args):
	"""The ids a call names (null for all), those that are strings: another value is no id of ours, and could not be
	looked up (a JSON object is not hashable)."""
	ids = jmap._ids(args)
	return None if ids is None else [i for i in ids if isinstance(i, str)]


def _person_zone():
	"""Where a floating time is read: the person's time zone, else the instance's."""
	from frappe.utils import get_system_timezone

	for name in (frappe.db.get_value("User", frappe.session.user, "time_zone"), get_system_timezone(), "UTC"):
		try:
			return ZoneInfo(name)
		except (ZoneInfoNotFoundError, TypeError, ValueError):
			continue
	return ZoneInfo("UTC")


def _duration_parts(value):
	"""(nominal, exact) of an ISO 8601 duration: its weeks and days are the calendar's (P1D ends at the same time the next
	day, summer time or not), its hours, minutes and seconds the clock's (RFC 8984 §1.4.6)."""
	match = _DURATION.match(str(value or ""))
	if not match:
		return timedelta(0), timedelta(0)
	weeks, days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
	return timedelta(weeks=weeks, days=days), timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _utc_times(event):
	"""(utcStart, utcEnd) of an event with a time, from its local start, its zone (else the person's) and its length."""
	try:
		local = datetime.fromisoformat(str(event.get("start")))
	except (TypeError, ValueError):
		return None, None
	try:
		zone = ZoneInfo(event["timeZone"]) if event.get("timeZone") else _person_zone()
	except (ZoneInfoNotFoundError, ValueError):
		zone = _person_zone()
	start = local.replace(tzinfo=zone)
	nominal, exact = _duration_parts(event.get("duration"))
	# The days on the wall clock, then the hours as they pass: 01:00 + PT3H on the night summer time ends is 02:00 UTC.
	end = (local + nominal).replace(tzinfo=zone).astimezone(timezone.utc) + exact
	stamp = lambda moment: moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
	return stamp(start), stamp(end)


def _facade_event(event, properties=None):
	out = dict(event)
	out["id"] = _event_id(event.get("id"))
	out["calendarIds"] = {_calendar_id(k): True for k, on in (event.get("calendarIds") or {}).items() if on}
	if event.get("baseEventId"):
		out["baseEventId"] = _event_id(event["baseEventId"])
	if not event.get("showWithoutTime"):
		out["utcStart"], out["utcEnd"] = _utc_times(event)
	if properties is not None:
		keep = set(properties) | {"id", "@type"}
		out = {k: v for k, v in out.items() if k in keep}
	return out


def no_changes(args):
	"""The changes since a state are not kept: the client reads the window again (RFC 8620 §5.2)."""
	_calendar_account(args)
	raise jmap.JmapError("cannotCalculateChanges", "Read the calendars again.")


METHODS = {
	"Calendar/get": calendar_get,
	"Calendar/changes": no_changes,
	"CalendarEvent/query": event_query,
	"CalendarEvent/queryChanges": no_changes,
	"CalendarEvent/get": event_get,
	"CalendarEvent/changes": no_changes,
	"CalendarEvent/set": event_set,
}
