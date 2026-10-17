# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
JMAP for Calendars (draft-ietf-jmap-calendars) in MailCraft's facade (mailcraft_jmap): the person's own calendars as the
Suite keeps them (on the mail server, or in the instance for a person without a mailbox), with the events of a window,
each occurrence of a repeating event apart and with its start and end in UTC (`utcStart`, `utcEnd`, worked out here:
MailCraft has no time-zone database). NeoMail's calendar is then Neoffice's (maintenance#1630, step 3 of NeoMail's
programme; study: vault note Neoffice-Apps/20).

NeoMail does with them what the desk does (Jérémy, 17.10: « elle doit pouvoir tout faire, comme dans le desk »): it
creates, changes and deletes events, a whole series or one of its occurrences, through the Suite's own calendar functions
(suite.calendar.doctype.calendar_event: add_calendar_event, update_calendar_event, delete_calendar_events and their
occurrence variants), so with their rules, their rights and their invitations, and in the calendars the person may
write (their rights on each, as the Suite reads them).

Offered where the Suite is installed, in the same one mailbox of the person as the address book
(mailcraft_contacts.contacts_mailbox). The calendar account is the person's own, chosen here and never named by the
client (`suite.calendar.feed._account_of`: their mailbox's, else the one kept in the instance, never created here): an
administrator's client would otherwise reach anyone's. Left out for now: the calendars others share with the person, and
the ERP's dates (`erp:`), whose titles carry customers, amounts and leaves that MailCraft would keep on the computer.
"""

import hashlib
import json
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


def _occurrence_id(series, recurrence_id):
	"""The facade id of an occurrence of a series: its series and its start, both kept by the mail server, where the
	occurrence's own id is renumbered the moment it gets an override of its own (an edit, an answer: an id that stops
	resolving, as the Suite's calendar API says). "O" and the two, JSON, base64url."""
	return "O" + jmap._b64(json.dumps([str(series), str(recurrence_id)]))


def _occurrence_of(jmap_id):
	"""(series, start) an occurrence's facade id names; None for another id."""
	if not (isinstance(jmap_id, str) and jmap_id[:1] == "O"):
		return None
	try:
		series, start = json.loads(jmap._unb64(jmap_id[1:]))
	except (ValueError, TypeError):
		return None
	return (series, start) if isinstance(series, str) and isinstance(start, str) else None


def _facade_id(event):
	"""The facade id of an event the Suite read: an occurrence's by its series and its start, another's by its own. Not an
	occurrence of a series without a uid (the mail server accepts one): it is found again by its uid (`_occurrences_now`),
	so it keeps its own id."""
	if event.get("recurrenceId") and event.get("baseEventId") and event.get("uid"):
		return _occurrence_id(event["baseEventId"], event["recurrenceId"])
	return _event_id(event.get("id"))


def _with_series(client, events):
	"""`events` as the Suite read them, each occurrence (`recurrenceId`) with the series it belongs to (`baseEventId`):
	the mail server gives it only when it is asked for by name (Stalwart's `CalendarEvent/get`), which the Suite's get
	doesn't do; its `get_base_event_ids` does. Without it, an occurrence would be named by its own id, which the server
	renumbers."""
	from suite.calendar.jmap_events import get_base_event_ids

	needing = [e["id"] for e in events if e.get("recurrenceId") and not e.get("baseEventId") and e.get("id")]
	if needing:
		bases = _reading(lambda: get_base_event_ids(client, needing))
		for event in events:
			base = bases.get(event.get("id"))
			if base and base != event.get("id") and not event.get("baseEventId"):
				event["baseEventId"] = base
	return events


def _request_events():
	"""The events this JMAP request read (`CalendarEvent/query` with its occurrences), by facade id: its
	`CalendarEvent/get` most often follows in the same request, and reads nothing again. Tied to the request, never
	longer: a write empties it."""
	request = getattr(frappe.local, "request", None)
	kept = getattr(frappe.local, "mailcraft_calendar_events", None)
	if not kept or kept[0] is not request:
		kept = (request, {})
		frappe.local.mailcraft_calendar_events = kept
	return kept[1]


def _occurrences_now(suite_account, wanted):
	"""{(series, start): event} for the occurrences named, as the mail server holds them now, whatever their own ids
	became: one query per series, around each start (where an override moved it, around its new start)."""
	from suite.calendar.jmap_events import get_events, query_events

	client = _reading(lambda: _client(suite_account))
	starts: dict[str, set[str]] = {}
	for series, start in wanted:
		starts.setdefault(series, set()).add(start)
	found = {}
	for series, asked in starts.items():
		master = _stored(client, series)
		if not master or not master.get("uid"):
			continue
		try:
			zone = ZoneInfo(master["timeZone"]) if master.get("timeZone") else _person_zone()
		except (ZoneInfoNotFoundError, ValueError):
			zone = _person_zone()
		overrides = master.get("recurrenceOverrides") or {}
		moments = []
		for start in asked:
			moved = (
				(overrides.get(start) or {}).get("start") if isinstance(overrides.get(start), dict) else None
			)
			for local in filter(None, (start, moved)):
				try:
					moments.append(
						datetime.fromisoformat(str(local)).replace(tzinfo=zone).astimezone(timezone.utc)
					)
				except (TypeError, ValueError):
					continue
		if not moments:
			continue
		window = {
			"operator": "AND",
			"conditions": [
				{"uid": master["uid"]},
				{"after": (min(moments) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")},
				{"before": (max(moments) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")},
			],
		}
		ids = _reading(
			lambda window=window: query_events(
				client, filter=window, limit=MAX_EVENTS, time_zone=_person_zone().key, expand_recurrences=True
			)
		).get("ids")
		read = [
			e
			for e in _reading(lambda ids=ids: get_events(client, list(ids or [])))
			if e.get("recurrenceId") in asked
		]
		for event in _with_series(client, read):
			key = (event.get("baseEventId"), event.get("recurrenceId"))
			if key[0] == series and key[1] in asked:
				found[key] = event
	return found


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
				"myRights": _rights(calendar.get("myRights")),
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
	raws = found.get("ids") or []
	if args.get("expandRecurrences") and raws:
		ids = _named_by_series(suite_account, raws)
	else:
		ids = [_event_id(i) for i in raws]
	if total is None and found.get("total") is not None:
		total = cint(found["total"])
	answer.update(
		position=position, ids=ids, queryState=hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
	)
	if asked_total:
		answer["total"] = total if total is not None else position + len(ids)
	return answer


def _named_by_series(suite_account, raws):
	"""The facade ids of the events a query found, each occurrence by its series and its start; what was read for it is
	kept for the request's `CalendarEvent/get`."""
	from suite.calendar.jmap_events import get_events

	client = _reading(lambda: _client(suite_account))
	read = {e.get("id"): e for e in _with_series(client, _reading(lambda: get_events(client, list(raws))))}
	kept = _request_events()
	kept.clear()
	ids = []
	for raw in raws:
		event = read.get(raw)
		facade = _facade_id(event) if event else _event_id(raw)
		if event:
			kept[facade] = event
		ids.append(facade)
	return ids


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

	found = {}
	client = _reading(lambda: _client(suite_account)) if raws else None
	for event in _with_series(client, _reading(lambda: get_events(client, list(raws)))) if raws else []:
		if event.get("id") in raws:
			found[raws[event["id"]]] = event
	# An occurrence by its series and its start: from what this request's query read, else as the server holds it now.
	kept = _request_events()
	occurrences = {i: o for i, o in ((i, _occurrence_of(i)) for i in ids) if o}
	missing = {o: i for i, o in occurrences.items() if i not in kept}
	now = _occurrences_now(suite_account, list(missing)) if missing else {}
	for i, o in occurrences.items():
		event = kept.get(i) or now.get(o)
		if event:
			found[i] = event
	listed = [_facade_event(found[i], properties, as_id=i) for i in ids if i in found]
	return {"accountId": aid, "state": "0", "list": listed, "notFound": [i for i in ids if i not in found]}


def _rights(given):
	"""A calendar's rights as JMAP names them, from the Suite's (the mail server's for its calendars, all of them for a
	calendar kept in the instance); read-only when it says none."""
	if not isinstance(given, dict):
		return dict(_READ_ONLY)
	return {key: bool(given.get(key, False)) for key in _READ_ONLY}


def _writable(rights):
	"""Whether events may be written there, as the desk reads it (`mayWriteAll`)."""
	return bool(rights.get("mayWriteAll"))


# A batch's events are written one by one through the desk's rate-limited functions, whose limits the whole office
# shares: at most this many in one call, the others answered « rateLimit » (tried again later by the client).
MAX_EVENTS_PER_SET = 50


def event_set(args):
	"""Events created, changed and deleted in the person's own calendars, as the desk does it (see the module's text).
	A whole property replaces it; an occurrence of a series is changed or deleted alone. Invitations go out when the
	client asks (`sendSchedulingMessages`) and the person organizes the event, never for a draft, as in the desk. Each
	refusal is said for its event; what a refused one had begun to write in the instance is undone (a savepoint per
	event: the instance's own records, not what a mail server already did)."""
	aid, suite_account = _calendar_account(args)
	creates, updates, destroys = args.get("create") or {}, args.get("update") or {}, args.get("destroy") or []
	if not isinstance(creates, dict) or not isinstance(updates, dict) or not isinstance(destroys, list):
		raise jmap.JmapError("invalidArguments", "create, update, destroy")
	if len(creates) + len(updates) + len(destroys) > jmap.MAX_OBJECTS:
		raise jmap.JmapError("requestTooLarge", "maxObjectsInSet")
	if args.get("ifInState") is not None:
		raise jmap.JmapError("invalidArguments", "ifInState")
	notify = args.get("sendSchedulingMessages") is True
	from suite.calendar.jmap_events import get_calendars

	client = _client(suite_account)
	calendars = {c.get("id"): c for c in _reading(lambda: get_calendars(client))}
	# What this request read is no longer what the server holds once it writes.
	_request_events().clear()
	created, updated, destroyed = {}, {}, []
	not_created, not_updated, not_destroyed = {}, {}, {}
	budget = [MAX_EVENTS_PER_SET]

	def written(write):
		if budget[0] <= 0:
			return {"type": "rateLimit", "description": "Too many events at once: try again in a minute."}
		budget[0] -= 1
		return _one_event(write)

	for key, event in creates.items():
		outcome = written(lambda event=event: _create_event(suite_account, client, calendars, event, notify))
		if isinstance(outcome, tuple):
			created[key] = {"id": _event_id(outcome[0]), "uid": outcome[1]}
		else:
			not_created[key] = outcome
	for vid, patch in updates.items():
		outcome = written(
			lambda vid=vid, patch=patch: _update_event(suite_account, client, calendars, vid, patch, notify)
		)
		if isinstance(outcome, dict):
			not_updated[vid] = outcome
		else:
			updated[vid] = None
	for vid in destroys:
		if not isinstance(vid, str):
			continue
		outcome = written(lambda vid=vid: _destroy_event(suite_account, client, calendars, vid, notify))
		if isinstance(outcome, dict):
			not_destroyed[vid] = outcome
		else:
			destroyed.append(vid)
	return {
		"accountId": aid,
		"oldState": "0",
		"newState": "0",
		"created": created,
		"updated": updated,
		"destroyed": destroyed,
		"notCreated": not_created,
		"notUpdated": not_updated,
		"notDestroyed": not_destroyed,
	}


EVENT_SAVEPOINT = "mailcraft_event"
# What a client may write of an event (JSCalendar, RFC 8984), as the desk's form does.
WRITABLE_EVENT = {
	"calendarIds",
	"title",
	"description",
	"start",
	"duration",
	"timeZone",
	"showWithoutTime",
	"status",
	"privacy",
	"freeBusyStatus",
	"recurrenceRule",
	"locations",
	"links",
	"alerts",
	"useDefaultAlerts",
	"participants",
}
# What a client may send back as it read it, and the server sets or keeps for itself: left as it is. The organizer
# and the draft state are the event's own (checked below: a client never changes them here, as in the desk).
SERVER_SET = {
	"@type",
	"id",
	"uid",
	"created",
	"updated",
	"sequence",
	"prodId",
	"method",
	"utcStart",
	"utcEnd",
	"baseEventId",
	"recurrenceIdTimeZone",
	"isOrigin",
	"mayInviteSelf",
	"mayInviteOthers",
	"hideAttendees",
	"organizerCalendarAddress",
	"isDraft",
}
# Fields an occurrence of a series never takes, as the desk keeps them off its patches: a zone there would move the
# exception away from its occurrence, and an occurrence does not change calendar alone.
NOT_FOR_AN_OCCURRENCE = ("time_zone", "calendar_ids")


def _one_event(write):
	"""Runs the write of one event: its answer, or its SetError (a dict) after undoing what it had begun."""
	frappe.db.savepoint(EVENT_SAVEPOINT)
	try:
		return write() or True
	except Exception as e:
		frappe.db.rollback(save_point=EVENT_SAVEPOINT)
		return _event_refusal(e)


def _event_refusal(error):
	"""A JMAP SetError for what stopped an event (the Suite's own messages, without their markup)."""
	from frappe.utils import strip_html

	described = strip_html(str(error)).strip()[:200]
	if isinstance(error, jmap.JmapError):
		# A read of the Suite on the way (_reading): refused, or the server not answering.
		return {
			"type": "forbidden" if error.type == "forbidden" else "serverFail",
			"description": error.description,
		}
	if isinstance(error, frappe.PermissionError):
		return {"type": "forbidden", "description": described or "Your rights do not allow it."}
	if isinstance(error, frappe.DoesNotExistError):
		return {"type": "notFound"}
	if isinstance(error, frappe.RateLimitExceededError):
		# The desk's limits (shared with the office): not the event's fault, tried again later.
		return {"type": "rateLimit", "description": described}
	if (
		isinstance(error, frappe.ValidationError | ValueError | TypeError)
		or type(error).__name__ == "ValidationError"
	):
		return {"type": "invalidProperties", "description": described}
	frappe.log_error("MailCraft calendars: an event could not be written", frappe.get_traceback())
	return {"type": "serverFail"}


def _map(event, key):
	"""A JSCalendar map property (`locations`, `alerts`…): its entries that are objects; null is none."""
	value = event.get(key)
	if value is None:
		return {}
	if not isinstance(value, dict):
		raise ValueError(f"{key} must be an object.")
	return {uid: entry for uid, entry in value.items() if isinstance(entry, dict)}


def _address(value):
	return str(value or "").strip().removeprefix("mailto:").removeprefix("MAILTO:")


def _participant_address(entry):
	"""A participant's address: its calendar address, else where invitations go to it (a room known by its sendTo)."""
	send_to = entry.get("sendTo") if isinstance(entry.get("sendTo"), dict) else {}
	return _address(
		entry.get("calendarAddress") or entry.get("email") or send_to.get("imip") or entry.get("scheduleId")
	)


def _event_fields(event, calendars):
	"""The fields the Suite's calendar functions take (snake_case, as the desk's form sends them) of a JSCalendar event
	or a patch of whole properties, for the properties it names only."""
	if not isinstance(event, dict):
		raise ValueError("An event must be an object.")
	if any("/" in key for key in event):
		raise ValueError("A whole property replaces it: no patch of a part.")
	unknown = set(event) - WRITABLE_EVENT - SERVER_SET
	if unknown:
		raise ValueError("Not written here: " + ", ".join(sorted(unknown)))
	out = {}
	if "calendarIds" in event:
		named = event["calendarIds"]
		if not isinstance(named, dict) or not any(named.values()):
			raise ValueError("An event goes in one of your calendars.")
		raws = [_raw(cid, "C") for cid, on in named.items() if on]
		if any(raw not in calendars for raw in raws):
			raise ValueError("An event goes in one of your calendars.")
		if not all(_writable(_rights(calendars[raw].get("myRights"))) for raw in raws):
			raise frappe.PermissionError
		out["calendar_ids"] = raws
	for given, field in (
		("title", "title"),
		("description", "description"),
		("start", "start"),
		("duration", "duration"),
		("timeZone", "time_zone"),
	):
		if given in event:
			out[field] = None if event[given] is None else str(event[given])
	if "showWithoutTime" in event:
		out["show_without_time"] = bool(event["showWithoutTime"])
	if "useDefaultAlerts" in event:
		out["use_default_alerts"] = bool(event["useDefaultAlerts"])
	if "status" in event:
		out["status"] = str(event["status"] or "confirmed")
	if "privacy" in event:
		out["privacy"] = event["privacy"]
	if "freeBusyStatus" in event:
		out["free_busy_status"] = event["freeBusyStatus"]
	if "recurrenceRule" in event:
		rule = event["recurrenceRule"]
		if rule is not None and not isinstance(rule, dict):
			raise ValueError("recurrenceRule must be an object.")
		out["recurrence_rule"] = rule
	if "locations" in event:
		out["locations"] = [
			{"uid": uid, "name": entry.get("name")} for uid, entry in _map(event, "locations").items()
		]
	if "links" in event:
		out["links"] = [
			{"uid": uid, "href": entry.get("href"), "content_type": entry.get("contentType")}
			for uid, entry in _map(event, "links").items()
		]
	if "alerts" in event:
		alerts = []
		for uid, entry in _map(event, "alerts").items():
			trigger = entry.get("trigger") if isinstance(entry.get("trigger"), dict) else {}
			action = entry.get("action") or "display"
			if trigger.get("@type") == "AbsoluteTrigger":
				alerts.append(
					{"type": "AbsoluteTrigger", "uid": uid, "action": action, "when": trigger.get("when")}
				)
			elif trigger.get("@type", "OffsetTrigger") == "OffsetTrigger":
				alerts.append(
					{
						"type": "OffsetTrigger",
						"uid": uid,
						"action": action,
						"offset": trigger.get("offset") or "-PT15M",
						"relative_to": trigger.get("relativeTo") or "start",
					}
				)
		out["alerts"] = alerts
	if "participants" in event:
		out["participants"] = [
			{
				"uid": uid,
				"name": entry.get("name"),
				"email": _participant_address(entry),
				"kind": entry.get("kind"),
				"roles": entry.get("roles"),
				"participation_status": entry.get("participationStatus"),
				# Someone added is asked for an answer, as the desk asks every participant it adds (JSCalendar's
				# default is « no reply expected »); the organizer is not.
				"expect_reply": bool(
					entry["expectReply"]
					if "expectReply" in entry
					else not (isinstance(entry.get("roles"), dict) and entry["roles"].get("owner"))
				),
				"description": entry.get("description"),
				"comment": entry.get("comment"),
				"schedule_agent": entry.get("scheduleAgent"),
				"schedule_id": entry.get("scheduleId"),
				"send_to": entry.get("sendTo"),
				"member_of": entry.get("memberOf"),
			}
			for uid, entry in _map(event, "participants").items()
			if _participant_address(entry)
		]
	return out


def _keep_own(event, stored=None):
	"""The organizer and the draft state stay the event's: a client sends them back as they are, or not at all."""
	if "organizerCalendarAddress" in event:
		given = _address(event["organizerCalendarAddress"]).lower()
		kept = _address((stored or {}).get("organizerCalendarAddress")).lower()
		if stored is not None and given != kept:
			raise frappe.PermissionError("The organizer of an event is not changed here.")
	if "isDraft" in event and bool(event["isDraft"]) != bool((stored or {}).get("isDraft")):
		raise ValueError("A draft is sent from the desk.")


def _event_uid_key(uid):
	return f"mailcraft_event_uid:{frappe.session.user}:" + hashlib.sha256(uid.encode()).hexdigest()


def _stored(client, raw):
	from suite.calendar.jmap_events import get_events

	found = _reading(lambda: get_events(client, [raw])) if raw else []
	return found[0] if found else None


def _organizes(suite_account, stored):
	"""Whether the person organizes the event (one of their own identities), as the desk's invitations check it."""
	from suite.calendar.doctype.calendar_event.invitations import acting_as_organizer

	return acting_as_organizer(suite_account, _address(stored.get("organizerCalendarAddress")) or None)


def _create_event(suite_account, client, calendars, event, notify):
	"""A new event, by the desk's add_calendar_event: (its id, its uid). The organizer is the person's own identity
	(the account's, or one of theirs the client names). One sent again (its answer lost on the way) comes back to the
	event it made, by the client's uid. An occurrence's own object (`recurrenceId`) is not made here: it is a change of
	its series."""
	from suite.calendar.doctype.calendar_event.calendar_event import add_calendar_event
	from suite.calendar.doctype.calendar_event.invitations import acting_as_organizer

	if isinstance(event, dict) and event.get("recurrenceId") is not None:
		raise ValueError("An occurrence is changed through its series, not created.")
	_keep_own(event)
	organizer = _address(event.get("organizerCalendarAddress")) if isinstance(event, dict) else ""
	if organizer and not acting_as_organizer(suite_account, organizer):
		raise frappe.PermissionError("An event is organized by one of your own addresses.")
	fields = _event_fields(event, calendars)
	if not fields.get("start") or not fields.get("duration"):
		raise ValueError("An event needs its start and its duration.")
	uid = str(event.get("uid") or "")[:255]
	if uid:
		kept = frappe.cache().get_value(_event_uid_key(uid))
		if isinstance(kept, dict) and kept.get("account") == suite_account:
			again = _stored(client, kept.get("id"))
			if again:
				return again["id"], again.get("uid")
	if "calendar_ids" not in fields:
		writable = [
			raw for raw, calendar in calendars.items() if _writable(_rights(calendar.get("myRights")))
		]
		default = next(
			(raw for raw in writable if calendars[raw].get("isDefault")), writable[0] if writable else None
		)
		if not default:
			raise frappe.PermissionError
		fields["calendar_ids"] = [default]
	raw = add_calendar_event(
		account=suite_account, organizer=organizer or None, send_scheduling_messages=notify, **fields
	)
	# Kept before anything else can fail: the event is made (on the mail server too), and a resend must find it.
	if uid:
		frappe.cache().set_value(
			_event_uid_key(uid), {"account": suite_account, "id": raw}, expires_in_sec=7 * 24 * 3600
		)
	try:
		made = _stored(client, raw) or {}
	except Exception:
		made = {}
	return raw, made.get("uid")


def _update_event(suite_account, client, calendars, vid, patch, notify):
	"""An event changed, by the desk's update_calendar_event: the properties the patch names replace the stored ones,
	the others stay, its organizer and draft state among them. An occurrence of a series is changed alone
	(update_calendar_event_instance). Invitations go out only from the organizer, never for a draft."""
	from suite.calendar.doctype.calendar_event.calendar_event import (
		update_calendar_event,
		update_calendar_event_instance,
	)
	from suite.calendar.doctype.calendar_event.fields import EventFields

	raw, stored, series, recurrence_id = _addressed(suite_account, client, vid)
	_check_writable(stored, calendars)
	_keep_own(patch if isinstance(patch, dict) else {}, stored)
	fields = _event_fields(patch, calendars)
	draft = bool(stored.get("isDraft"))
	notify = notify and not draft and _organizes(suite_account, stored)
	if recurrence_id:
		for key in NOT_FOR_AN_OCCURRENCE:
			fields.pop(key, None)
		# Checked and written as the desk's form gives them (lower-case enumerations), the fields named only.
		service = EventFields.model_validate(fields).for_service()
		update_calendar_event_instance(
			account=suite_account,
			master_id=series,
			recurrence_id=recurrence_id,
			patch={key: service[key] for key in fields if key in service},
			send_scheduling_messages=notify,
		)
		return True
	whole = {key: value for key, value in stored.items() if key in WRITABLE_EVENT}
	whole["calendarIds"] = {
		_calendar_id(k): True for k, on in (stored.get("calendarIds") or {}).items() if on
	}
	merged = _event_fields(whole, calendars) | fields
	update_calendar_event(
		account=suite_account,
		id=raw,
		uid=stored.get("uid"),
		organizer=_address(stored.get("organizerCalendarAddress")) or None,
		draft=draft,
		send_scheduling_messages=notify,
		**merged,
	)
	return True


def _destroy_event(suite_account, client, calendars, vid, notify):
	"""An event deleted, by the desk's delete_calendar_events; an occurrence of a series alone
	(delete_calendar_event_instance). Cancellations go out only from the organizer, never for a draft (nobody was
	invited); an attendee's copy deleted tells nobody, as in the desk."""
	from suite.calendar.doctype.calendar_event.calendar_event import (
		delete_calendar_event_instance,
		delete_calendar_events,
	)

	raw, stored, series, recurrence_id = _addressed(suite_account, client, vid)
	_check_writable(stored, calendars)
	notify = notify and not stored.get("isDraft") and _organizes(suite_account, stored)
	if recurrence_id:
		delete_calendar_event_instance(
			account=suite_account,
			master_id=series,
			recurrence_id=recurrence_id,
			send_scheduling_messages=notify,
		)
	else:
		delete_calendar_events(account=suite_account, ids=[raw], send_scheduling_messages=notify)
	return True


def _addressed(suite_account, client, vid):
	"""(raw id, the event as stored, its series, its start) of the event a facade id names; series and start are None
	for an event that is not an occurrence. An occurrence named by its series and start is checked against its series
	(its calendar, its organizer, its draft state are the series'), after making sure it is still one of it."""
	occurrence = _occurrence_of(vid)
	if occurrence:
		series, recurrence_id = occurrence
		stored = _stored(client, series)
		if not stored or not _occurrences_now(suite_account, [occurrence]):
			raise frappe.DoesNotExistError
		return series, stored, series, recurrence_id
	raw = _raw(vid, "V")
	stored = _stored(client, raw)
	if not stored:
		raise frappe.DoesNotExistError
	if stored.get("recurrenceId"):
		return raw, stored, _master_of(client, raw), stored["recurrenceId"]
	return raw, stored, None, None


def _check_writable(stored, calendars):
	"""An event of a calendar the person may not write is not theirs to change (one of another account is not there)."""
	held = [k for k, on in (stored.get("calendarIds") or {}).items() if on]
	if not held or any(k not in calendars for k in held):
		raise frappe.DoesNotExistError
	if not all(_writable(_rights(calendars[k].get("myRights"))) for k in held):
		raise frappe.PermissionError


def _master_of(client, raw):
	"""The series an occurrence belongs to (its own id when the server knows no other)."""
	from suite.calendar.jmap_events import get_base_event_ids

	return _reading(lambda: get_base_event_ids(client, [raw])).get(raw, raw)


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


def _facade_event(event, properties=None, as_id=None):
	out = dict(event)
	out["id"] = as_id or _facade_id(event)
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
