# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
JMAP for Calendars (draft-ietf-jmap-calendars) in MailCraft's facade (mailcraft_jmap): the person's own calendars as the
Suite keeps them (on the mail server, or in the instance for a person without a mailbox), with the events of a window,
each occurrence of a repeating event apart and with its start and end in UTC (`utcStart`, `utcEnd`, worked out here:
MailCraft has no time-zone database). NeoMail's calendar is then Neoffice's (maintenance#1630, step 3 of NeoMail's
programme; study: vault note Neoffice-Apps/20).

NeoMail does with them what the desk does (Jérémy, 17.10: "she must be able to do everything, as in the desk"): it
creates, changes and deletes events, a whole series or one of its occurrences, through the Suite's own calendar functions
(suite.calendar.doctype.calendar_event: add_calendar_event, update_calendar_event, delete_calendar_events and their
occurrence variants), so with their rules, their rights and their invitations, and in the calendars the person may
write (their rights on each, as the Suite reads them).

Offered where the Suite is installed, in the same one mailbox of the person as the address book
(mailcraft_contacts.contacts_mailbox). The calendar account is the person's own, chosen here and never named by the
client (`suite.calendar.feed._account_of`: their mailbox's, else the one kept in the instance, never created here): an
administrator's client would otherwise reach anyone's.

Beside the person's own calendars, the ones the desk's calendar shows them too, read-only (`_read_only_calendars`):
- the dates of the ERP (tasks, reminders, interventions, leaves, bookings, invoices…), the Suite's calendars `erp:<source>`
  (suite.calendar.sources, maintenance#1428), each with the desk's name in the person's language, the colour of its
  palette, and switched on or off as the person switched it in the desk (a source that is off sends no events);
- the calendars colleagues share with the person read-only, kept in their owner's account on the mail server (named
  `<account>|<id>`, as the Suite names them).
They are listed by the desk's own call (suite.calendar.api.get_calendars_with_shared, with the ERP's dates), and their
events read as the desk reads them, as the person and with their rights: the ERP's dates by the Suite's batch for a
window (sources.virtual_events, a chunk of 90 days at a time, as the Suite's own feed reads them), a shared calendar's
events from its account. Nothing is written there: a create, a change or a deletion is refused, each with its reason.
Their titles carry customers, amounts and leaves, which MailCraft keeps on the computer as it keeps the person's mail.

No change is recorded, for any calendar: `/changes` answers `cannotCalculateChanges` and the client reads its window
again (RFC 8620 §5.2), as MailCraft does at each synchronisation; the read-only events are read where they live at each
query, and a query's `queryState` changes when one of them changes, its title or its time as much as its id.
"""

import hashlib
import inspect
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe import _
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
# The ids of the ERP's calendars and of their dates begin so (suite.calendar.sources.PREFIX, not imported: this module
# is read where the Suite may not be installed); a calendar or an event shared from another account is named
# `<account>|<id>`, as the Suite names it. The person's own ids have neither.
ERP_PREFIX = "erp:"
# The colours the desk draws a source of the ERP's dates in, by the name of its palette: the hexes of its calendar
# palette (frontend/src/apps/calendar/utils/calendars.ts, CALENDAR_COLORS), which frappe-ui reads back as its own.
ERP_COLORS = {
	"green": "#30a66d",
	"blue": "#0289f7",
	"violet": "#6846e3",
	"amber": "#db7706",
	"pink": "#e34aa6",
	"cyan": "#3bbde5",
	"orange": "#e86c13",
}
# The ERP's dates are read a chunk at a time, as the Suite's feed reads them (suite.calendar.feed.CHUNK_DAYS): a source
# gives at most 300 entries a read (sources.MAX_PER_SOURCE), which a whole window of MailCraft's could pass.
ERP_CHUNK = timedelta(days=90)
# A CalendarEvent/get of a date of the ERP that no query of the same request read: read again in the windows the person
# queried last (kept an hour), then in MailCraft's own window around today (90 days back, a year and a day ahead).
WINDOWS_KEPT = 4
WINDOWS_SECONDS = 3600
TODAY_BEFORE, TODAY_AFTER = timedelta(days=90), timedelta(days=366)
# The longest id RFC 8620 allows (§1.2).
MAX_ID = 255


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
			# Not in the draft: what an event keeps when it is written here, so that a client offers nothing else
			# (categories, importance, online meetings…) rather than learn it from a refusal.
			"writableProperties": sorted(WRITABLE_EVENT | ({ONLINE_PROPERTY} if meet_usable() else set())),
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
	every = _reading(lambda: get_calendars(_client(suite_account)))
	default = _default_calendar({calendar.get("id"): calendar for calendar in every})
	for calendar in every:
		cid = _calendar_id(calendar.get("id"))
		if ids is not None and cid not in ids:
			continue
		listed.append(
			{
				"id": cid,
				"name": calendar.get("name") or "",
				"description": calendar.get("description"),
				"color": _color(calendar.get("color")),
				"sortOrder": cint(calendar.get("sortOrder")),
				"isSubscribed": True,
				"isVisible": calendar.get("isVisible", True) is not False,
				# One, and the one an event made without naming its calendar goes to (_create_event).
				"isDefault": calendar.get("id") == default,
				"includeInAvailability": "none",
				"myRights": _rights(calendar.get("myRights")),
			}
		)
	# Then those the desk shows besides, read-only, in the desk's order: after the person's own.
	after = 1 + max((cint(calendar.get("sortOrder")) for calendar in every), default=0)
	for index, (raw, (kind, row)) in enumerate(_read_only_calendars(suite_account).items()):
		cid = _calendar_id(raw)
		if ids is None or cid in ids:
			listed.append(_read_only_calendar(cid, kind, row, after + index))
	found = {c["id"] for c in listed}
	return {
		"accountId": aid,
		"state": "0",
		"list": listed,
		"notFound": [i for i in (ids or []) if i not in found],
	}


@contextmanager
def _persons_language():
	"""The person's language for what the Suite writes in words (the names of the ERP's calendars, their dates'
	details, its refusals), as the desk speaks to them: the request's own was settled before its token named the
	person (frappe.auth.HTTPRequest.set_lang, then the auth hooks), from the client's headers or the instance's."""
	from frappe.translate import get_user_lang

	previous = getattr(frappe.local, "lang", None)
	frappe.local.lang = get_user_lang(frappe.session.user) or previous
	try:
		yield
	finally:
		frappe.local.lang = previous


def _read_only_kind(raw):
	"""The kind of a calendar or an event the person only reads, by its raw id: `erp` (a date of the ERP) or `shared`
	(from another account); None for one of their own."""
	if not isinstance(raw, str):
		return None
	if raw.startswith(ERP_PREFIX):
		return "erp"
	return "shared" if "|" in raw else None


def _shared_parts(raw):
	"""(its account, its id there) of a calendar's or an event's raw id shared from another account; None otherwise."""
	account, sep, rest = str(raw or "").partition("|")
	return (account, rest) if sep and account and rest else None


def _read_only_calendars(suite_account):
	"""{raw id: (kind, the desk's row)} of the calendars the desk shows the person beside their own, in its order:
	those shared with them read-only from other accounts, then the ERP's dates. Read by the desk's own call, as the
	person, once a request."""
	request = getattr(frappe.local, "request", None)
	kept = getattr(frappe.local, "mailcraft_read_only_calendars", None)
	if request is not None and kept and kept[0] is request and kept[1] == suite_account:
		return kept[2]
	from suite.calendar import api

	listing = getattr(api, "get_calendars_with_shared", None)
	if listing is None:
		return {}
	try:
		with_erp = "erp_dates" in inspect.signature(listing).parameters
	except (TypeError, ValueError):
		with_erp = False
	with _persons_language():
		rows = _reading(lambda: listing(suite_account, erp_dates=1) if with_erp else listing(suite_account))
	found = {}
	for row in rows or []:
		raw = str(row.get("id") or "") if isinstance(row, dict) else ""
		if raw.startswith(ERP_PREFIX):
			found[raw] = ("erp", row)
		elif raw and "|" not in raw and row.get("account") and row["account"] != suite_account:
			found[f"{row['account']}|{raw}"] = ("shared", row)
	if request is not None:
		frappe.local.mailcraft_read_only_calendars = (request, suite_account, found)
	return found


def _read_only_calendar(cid, kind, row, sort_order):
	"""A calendar the person only reads, as JMAP lists it: the desk's name and description, its colour (a source of the
	ERP's in the colour of its palette), shown or hidden as the desk shows it, and every right but reading off."""
	if kind == "erp":
		color = _color(row.get("color")) or ERP_COLORS.get(str(row.get("palette") or ""))
		# The switch the person keeps in the desk: a source that is off sends no events.
		visible = bool(cint(row.get("visible")))
	else:
		color = _color(row.get("color"))
		# The desk shows a calendar shared read-only unless the person hid it in their browser.
		visible = True
	return {
		"id": cid,
		"name": str(row.get("_name") or row.get("id") or ""),
		"description": row.get("description") or None,
		"color": color,
		"sortOrder": sort_order,
		"isSubscribed": True,
		"isVisible": visible,
		"isDefault": False,
		"includeInAvailability": "none",
		"myRights": dict(_READ_ONLY),
	}


def _default_calendar(calendars):
	"""The calendar (raw id) an event goes to when the client names none, which is also the one said to be the default:
	the first the Suite flags among those the person may write, else the first they may write. When they may write none,
	the first flagged, else the first, so that one is still the default (an event made there is refused). The Suite and
	the mail server may flag several, or none."""
	writable = [raw for raw, calendar in calendars.items() if _writable(_rights(calendar.get("myRights")))]
	pool = writable or list(calendars)
	return next((raw for raw in pool if calendars[raw].get("isDefault")), pool[0] if pool else None)


def _color(value):
	"""A calendar's colour as `#rrggbb`, whatever the Suite or another client of the mail server wrote (a CSS name,
	`#rgb`, `#rrggbbaa`, `rgb()`); None for none, for one that reads as no colour, and for a transparent one. Pillow
	does not bound what it reads (`rgb(300,0,0)`): a channel outside 0 to 255 is no colour either."""
	if not isinstance(value, str) or not value.strip() or len(value) > 64:
		return None
	from PIL import ImageColor

	try:
		channels = ImageColor.getrgb(value.strip())
	except ValueError:
		return None
	if not all(0 <= channel <= 255 for channel in channels) or (len(channels) == 4 and channels[3] == 0):
		return None
	red, green, blue = channels[:3]
	return f"#{red:02x}{green:02x}{blue:02x}"


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
	"""The ids of the events of a window (`after`, `before`, both asked, 500 days at most), in the person's calendars
	or those named (`inCalendars`); each occurrence apart when `expandRecurrences` is asked. The person's own events
	come first, as the server pages them; then those of the calendars they only read (_read_only_events), read when a
	page reaches them or a total is asked: positions and the total count both."""
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
	expand = bool(args.get("expandRecurrences"))
	# Which of the calendars the person only reads are asked for: all of them, or those named.
	read_only_named = None
	own_asked = True
	if criteria.get("inCalendars") is not None:
		named = criteria["inCalendars"]
		if not isinstance(named, list) or len(named) > jmap.MAX_OBJECTS:
			raise jmap.JmapError("invalidArguments", "inCalendars")
		raws = [r for r in (_raw(c, "C") for c in named) if r]
		if not raws:
			return {**answer, "position": 0, **({"total": 0} if asked_total else {})}
		own_raws = [r for r in raws if not _read_only_kind(r)]
		read_only_named = {r for r in raws if _read_only_kind(r)}
		own_asked = bool(own_raws)
		if own_raws:
			query = {
				"operator": "AND",
				"conditions": [
					query,
					{"operator": "OR", "conditions": [{"inCalendar": r} for r in own_raws]},
				],
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
				expand_recurrences=expand,
			)
		)

	read_only = []

	def others():
		"""The read-only events of the window, read once, when first needed."""
		if not read_only:
			read_only.append(_read_only_events(suite_account, after, before, read_only_named, expand))
		return read_only[0]

	# The Suite reads from a position on, and returns nothing for a limit of 0: the total of the person's own events,
	# when it is needed first (a position from the end, RFC 8620 §5.5) or alone, comes from a read of one.
	own_total = None if own_asked else 0
	if own_asked and (position < 0 or not used):
		own_total = cint(read(0, 1).get("total"))
	total = None
	if position < 0:
		total = own_total + len(others())
		position = max(0, total + position)
	ids = []
	_request_events().clear()
	if used and own_asked and (own_total is None or position < own_total):
		found = read(position, used)
		raws = found.get("ids") or []
		ids = _named_by_series(suite_account, raws) if expand and raws else [_event_id(i) for i in raws]
		if found.get("total") is not None:
			own_total = cint(found["total"])
		elif own_total is None:
			own_total = position + len(raws)
	own_total = own_total or 0
	page = []
	if used and len(ids) < used:
		# The person's own events are over: the read-only ones follow, from where this page is past them.
		start = max(0, position + len(ids) - own_total)
		page = others()[start : start + used - len(ids)]
		kept = _request_events()
		for facade, event in page:
			kept[facade] = event
			ids.append(facade)
	state = "|".join(ids)
	if page:
		# A date of the ERP renamed or moved keeps its id: what it says is in the state too.
		state += "#" + json.dumps([event for _facade, event in page], sort_keys=True, default=str)
	answer.update(position=position, ids=ids, queryState=hashlib.sha256(state.encode()).hexdigest()[:16])
	if asked_total:
		answer["total"] = total if total is not None else own_total + len(others())
	return answer


def _read_only_events(suite_account, after, before, named=None, expand=False):
	"""[(facade id, event)] of the window in the calendars the person only reads (all of them, or those `named` by
	their raw ids), as the desk reads them: the ERP's dates, then the events of each calendar shared with them."""
	calendars = _read_only_calendars(suite_account)
	chosen = {raw: kind for raw, (kind, _row) in calendars.items() if named is None or raw in named}
	events = []
	if any(kind == "erp" for kind in chosen.values()):
		_remember_window(after, before)
		events += [
			(facade, event)
			for facade, event in _erp_events(suite_account, after, before)
			if any(raw in chosen for raw in event["calendarIds"])
		]
	shared = {}
	for raw, kind in chosen.items():
		if kind == "shared":
			account, calendar = _shared_parts(raw)
			shared.setdefault(account, []).append(calendar)
	if shared:
		events += _shared_events(shared, after, before, expand)
	return events[:MAX_EVENTS]


def _utc_text(moment):
	return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _erp_events(suite_account, after, before):
	"""[(facade id, event)] of the ERP's dates between two moments (aware datetimes), as JSCalendar events, in the
	order of their start: the Suite's batch (sources.virtual_events, the sources the person switched on, read as them)
	a chunk at a time, each date once."""
	try:
		from suite.calendar import sources
	except ImportError:
		return []
	rows = {}
	start = after
	with _persons_language():
		while start < before:
			end = min(start + ERP_CHUNK, before)
			chunk = _reading(
				lambda start=start, end=end: sources.virtual_events(
					suite_account, _utc_text(start), _utc_text(end)
				)
			)
			for row in chunk or []:
				if isinstance(row, dict) and row.get("id"):
					rows.setdefault(str(row["id"]), row)
			start = end
		events = [_erp_event(row) for row in rows.values()]
	events.sort(key=lambda event: (event["start"], event["id"]))
	return [(_erp_event_id(event), event) for event in events[:MAX_EVENTS]]


def _erp_event(row):
	"""A date of the ERP (the Suite's row, as its calendar page reads it) as a JSCalendar event, ids still raw: a day
	or a time on the instance's wall clock; free time, as the Suite's feed publishes it (a date blocks nobody); its
	details and whether it is late in its description, as the feed writes them; the document it comes from as a link."""
	all_day = bool(cint(row.get("show_without_time")))
	lines = [str(row.get(key) or "") for key in ("description", "meta")]
	if cint(row.get("late")):
		lines.append(_("Late"))
	event = {
		"@type": "Event",
		"id": str(row["id"]),
		"uid": str(row.get("uid") or row["id"]),
		"calendarIds": {
			str(calendar["calendar_id"]): True
			for calendar in row.get("calendars") or []
			if isinstance(calendar, dict) and calendar.get("calendar_id")
		},
		"title": str(row.get("title") or ""),
		"description": "\n".join(dict.fromkeys(line for line in lines if line)),
		"start": str(row.get("start") or ""),
		"duration": str(row.get("duration") or ("P1D" if all_day else "PT0S")),
		"timeZone": None if all_day else (row.get("time_zone") or None),
		"showWithoutTime": all_day,
		"status": str(row.get("status") or "confirmed").lower(),
		"freeBusyStatus": "free",
		"sequence": 0,
	}
	# Only a page of the desk, as the desk's own card follows it (erpEventRoute): never another site.
	route = str(row.get("route") or "")
	if re.fullmatch(r"/app/\S*", route):
		event["links"] = {
			"document": {"@type": "Link", "href": frappe.utils.get_url(route), "contentType": "text/html"}
		}
	return event


def _erp_event_id(event):
	"""The facade id of a date of the ERP: its own (the Suite's, stable while its document is there), or, past the
	length of an id, its calendar's and a digest of it."""
	facade = _event_id(event["id"])
	if len(facade) <= MAX_ID:
		return facade
	calendar = next(iter(event["calendarIds"]), ERP_PREFIX)
	return _event_id(f"{calendar}:#{hashlib.sha256(event['id'].encode()).hexdigest()[:32]}")


def _windows_key():
	return f"mailcraft_calendar_windows:{frappe.session.user}"


def _remember_window(after, before):
	"""The windows the person queried last, for a CalendarEvent/get of the ERP's dates outside its query's request."""
	window = [_utc_text(after), _utc_text(before)]
	kept = frappe.cache().get_value(_windows_key())
	kept = [w for w in kept if w != window] if isinstance(kept, list) else []
	frappe.cache().set_value(_windows_key(), [window, *kept][:WINDOWS_KEPT], expires_in_sec=WINDOWS_SECONDS)


def _shared_events(shared, after, before, expand):
	"""[(facade id, event)] of the window in calendars shared with the person, {account: [calendar ids there]}: read
	from each account as the person (its mail server's rights), named under it."""
	from suite.calendar.jmap_events import get_events, query_events

	found = []
	for account, calendar_ids in shared.items():
		client = _reading(lambda account=account: _client(account))
		window = {
			"operator": "AND",
			"conditions": [
				{"after": _utc_text(after), "before": _utc_text(before)},
				{"operator": "OR", "conditions": [{"inCalendar": c} for c in calendar_ids]},
			],
		}
		raws = (
			_reading(
				lambda client=client, window=window: query_events(
					client,
					filter=window,
					limit=MAX_EVENTS,
					time_zone=_person_zone().key,
					expand_recurrences=expand,
				)
			).get("ids")
			or []
		)
		read = (
			{
				e.get("id"): e
				for e in _with_series(
					client, _reading(lambda client=client, raws=raws: get_events(client, raws))
				)
			}
			if raws
			else {}
		)
		for raw in raws:
			event = read.get(raw)
			if event and _in_calendars(event, calendar_ids):
				named = _namespaced(event, account)
				found.append((_facade_id(named), named))
	return found


def _in_calendars(event, calendar_ids):
	return any(on and k in calendar_ids for k, on in (event.get("calendarIds") or {}).items())


def _namespaced(event, account):
	"""An event of another account with its ids named under it (`<account>|<id>`), as the Suite names them: its facade
	ids then never meet the person's own."""
	out = dict(event)
	out["id"] = f"{account}|{event.get('id')}"
	if event.get("baseEventId"):
		out["baseEventId"] = f"{account}|{event['baseEventId']}"
	out["calendarIds"] = {f"{account}|{k}": on for k, on in (event.get("calendarIds") or {}).items()}
	return out


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
	# The events of the calendars the person only reads apart (_read_only_again): the rest is their own.
	read_only = [i for i in ids if _read_only_kind(_event_raw(i))]
	own = [i for i in ids if i not in set(read_only)]
	raws = {r: i for i, r in ((i, _raw(i, "V")) for i in own) if r}
	from suite.calendar.jmap_events import get_events

	found = {}
	client = _reading(lambda: _client(suite_account)) if raws else None
	for event in _with_series(client, _reading(lambda: get_events(client, list(raws)))) if raws else []:
		if event.get("id") in raws:
			found[raws[event["id"]]] = event
	# An occurrence by its series and its start: from what this request's query read, else as the server holds it now.
	kept = _request_events()
	occurrences = {i: o for i, o in ((i, _occurrence_of(i)) for i in own) if o}
	missing = {o: i for i, o in occurrences.items() if i not in kept}
	now = _occurrences_now(suite_account, list(missing)) if missing else {}
	for i, o in occurrences.items():
		event = kept.get(i) or now.get(o)
		if event:
			found[i] = event
	# A read-only one from what this request's query read, else read again.
	found.update({i: kept[i] for i in read_only if i in kept})
	again = [i for i in dict.fromkeys(read_only) if i not in kept]
	if again:
		found.update(_read_only_again(suite_account, again))
	listed = [_facade_event(found[i], properties, as_id=i) for i in ids if i in found]
	return {"accountId": aid, "state": "0", "list": listed, "notFound": [i for i in ids if i not in found]}


def _event_raw(jmap_id):
	"""The raw id an event's facade id names (an occurrence's series), or None."""
	occurrence = _occurrence_of(jmap_id)
	return occurrence[0] if occurrence else _raw(jmap_id, "V")


def _read_only_again(suite_account, ids):
	"""{facade id: event} of the read-only events asked for by id that no query of this request read: the ERP's dates
	in the windows the person queried last, then around today; a shared calendar's from its account, by id."""
	found = {}
	erp = {i for i in ids if _read_only_kind(_event_raw(i)) == "erp"}
	if erp:
		kept = frappe.cache().get_value(_windows_key())
		windows = [w for w in kept if isinstance(w, list) and len(w) == 2] if isinstance(kept, list) else []
		today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
		windows.append([_utc_text(today - TODAY_BEFORE), _utc_text(today + TODAY_AFTER)])
		for after, before in windows:
			try:
				after, before = _utc_date(after, "after"), _utc_date(before, "before")
			except jmap.JmapError:
				continue
			found.update(
				(facade, event)
				for facade, event in _erp_events(suite_account, after, min(before, after + MAX_SPAN))
				if facade in erp
			)
			if erp <= set(found):
				break
	shared = [i for i in ids if _read_only_kind(_event_raw(i)) == "shared"]
	if shared:
		found.update(_shared_again(suite_account, shared))
	return found


def _shared_again(suite_account, ids):
	"""{facade id: event} of events of calendars shared with the person, asked for by id: read from their account as
	the person, and only those of a calendar the desk shows them (one of an account they write to is no shared one)."""
	from suite.calendar.jmap_events import get_events

	shown = {}
	for raw, (kind, _row) in _read_only_calendars(suite_account).items():
		if kind == "shared":
			account, calendar = _shared_parts(raw)
			shown.setdefault(account, set()).add(calendar)
	asked = {}
	for i in ids:
		occurrence = _occurrence_of(i)
		parts = _shared_parts(occurrence[0] if occurrence else _raw(i, "V"))
		if parts and parts[0] in shown:
			named = asked.setdefault(parts[0], ({}, {}))
			if occurrence:
				named[1][(parts[1], occurrence[1])] = i
			else:
				named[0][parts[1]] = i
	found = {}
	for account, (by_id, by_start) in asked.items():
		client = _reading(lambda account=account: _client(account))
		read = (
			_with_series(client, _reading(lambda client=client, by_id=by_id: get_events(client, list(by_id))))
			if by_id
			else []
		)
		now = _occurrences_now(account, list(by_start)) if by_start else {}
		pairs = [(by_id.get(e.get("id")), e) for e in read] + [
			(i, now.get(key)) for key, i in by_start.items()
		]
		for i, event in pairs:
			if i and event and _in_calendars(event, shown[account]):
				found[i] = _namespaced(event, account)
	return found


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
# shares: at most this many in one call, the others answered "rateLimit" (tried again later by the client).
MAX_EVENTS_PER_SET = 50


def event_set(args):
	"""Events created, changed and deleted in the person's own calendars, as the desk does it (see the module's text);
	never in those they only read (the ERP's dates, a calendar shared with them), each refused with its reason before
	anything is written. A whole property replaces it; an occurrence of a series is changed or deleted alone.
	Invitations go out when the client asks (`sendSchedulingMessages`) and the person organizes the event, never for a
	draft, as in the desk; the person's answer to someone else's invitation, when the client asks for it to be sent,
	reaches its organizer as the desk's answer does (`_answer_of`). Each refusal is said for its event; what a refused
	one had begun to write in the instance is undone (a savepoint per event: the instance's own records, not what a mail
	server already did)."""
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
		refused = _read_only_refusal(_named_read_only(event))
		if refused:
			not_created[key] = refused
			continue
		outcome = written(lambda event=event: _create_event(suite_account, client, calendars, event, notify))
		if isinstance(outcome, tuple):
			created[key] = {"id": _event_id(outcome[0]), "uid": outcome[1], **outcome[2]}
		else:
			not_created[key] = outcome
	for vid, patch in updates.items():
		refused = _read_only_refusal(_read_only_kind(_event_raw(vid)) or _named_read_only(patch))
		if refused:
			not_updated[vid] = refused
			continue
		outcome = written(
			lambda vid=vid, patch=patch: _update_event(suite_account, client, calendars, vid, patch, notify)
		)
		if isinstance(outcome, dict):
			not_updated[vid] = outcome
		else:
			# What the server set of the event besides the patch (its online meeting), or nothing.
			updated[vid] = (outcome[1] or None) if isinstance(outcome, tuple) else None
	for vid in destroys:
		if not isinstance(vid, str):
			continue
		refused = _read_only_refusal(_read_only_kind(_event_raw(vid)))
		if refused:
			not_destroyed[vid] = refused
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


def _named_read_only(event):
	"""The kind ("erp", "shared") of a calendar the person only reads that an event or a patch puts it in, or None."""
	named = event.get("calendarIds") if isinstance(event, dict) else None
	if not isinstance(named, dict):
		return None
	kinds = [_read_only_kind(_raw(cid, "C")) for cid, on in named.items() if on and isinstance(cid, str)]
	return next((kind for kind in kinds if kind), None)


def _read_only_refusal(kind):
	"""The SetError of a write into a calendar the person only reads, said in their language; None for their own."""
	if not kind:
		return None
	with _persons_language():
		if kind == "erp":
			text = _("The dates of the ERP are read-only here: change them in the document they come from.")
		else:
			text = _("This calendar is shared with you to read only: its events are changed by its owner.")
	return {"type": "forbidden", "description": text}


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
# An online meeting (RFC 8984 `virtualLocations`): a client asks for one by this `uri`, and the event gets its own Meet
# room, made here as the desk's "Meet link" switch makes it (suite.meet.api.schedule), its link kept in `links`, where
# the desk, the invitation's Meet card and its .ics read it. A Meet link of an event reads back as a virtual location.
ONLINE_PROPERTY = "virtualLocations"
ONLINE_MEETING_REQUEST = "urn:x-online-meeting:new"
MEET_FEATURES = {"audio": True, "chat": True, "screen": True, "video": True}
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


class RoomRefused(Exception):
	"""What stopped the Meet room an event asked for, said apart from the event's own refusals: its SetError names the
	property (`virtualLocations`), so that a client tells "no room" from "the desk's limits, try again"."""

	def __init__(self, kind, description):
		super().__init__(description)
		self.kind = kind
		self.description = description


def _event_refusal(error):
	"""A JMAP SetError for what stopped an event (the Suite's own messages, without their markup)."""
	from frappe.utils import strip_html

	described = strip_html(str(error)).strip()[:200]
	if isinstance(error, RoomRefused):
		return {"type": error.kind, "properties": [ONLINE_PROPERTY], "description": error.description[:200]}
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
	unknown = set(event) - WRITABLE_EVENT - SERVER_SET - {ONLINE_PROPERTY}
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
				# default is "no reply expected"); the organizer is not.
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
	"""A new event, by the desk's add_calendar_event: (its id, its uid, what the answer says of its online meeting).
	The organizer is the person's own identity (the account's, or one of theirs the client names). One sent again (its
	answer lost on the way) comes back to the event it made, by the client's uid. An occurrence's own object
	(`recurrenceId`) is not made here: it is a change of its series. Asked for as an online meeting, it gets its own
	Meet room (_online_change)."""
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
				return again["id"], again.get("uid"), _online_answer(event, again)
	online, _ = _online_change(event)
	if "calendar_ids" not in fields:
		default = _default_calendar(calendars)
		if not default or not _writable(_rights(calendars[default].get("myRights"))):
			raise frappe.PermissionError
		fields["calendar_ids"] = [default]
	# The client's uid is the event's where the Suite keeps it (an older one makes its own): the client knows the event
	# it made in its next read, even when the answer to this call is lost on the way.
	if uid and _keeps_client_uid(add_calendar_event):
		fields["uid"] = uid
	room = None
	if online == "make":
		room, url = _make_room(suite_account, fields.get("title"))
		fields["links"] = [*(fields.get("links") or []), {"href": url, "content_type": "text/html"}]
	raw = add_calendar_event(
		account=suite_account, organizer=organizer or None, send_scheduling_messages=notify, **fields
	)
	# Kept before anything else can fail: the event is made (on the mail server too), and a resend must find it.
	if uid:
		frappe.cache().set_value(
			_event_uid_key(uid), {"account": suite_account, "id": raw}, expires_in_sec=7 * 24 * 3600
		)
	if room:
		_tie_room(room, suite_account, raw)
	try:
		made = _stored(client, raw) or {}
	except Exception:
		made = {}
	if room and not made:
		made = {"links": {"meet": {"href": url}}}
	return raw, made.get("uid"), _online_answer(event, made)


def _keeps_client_uid(add_calendar_event):
	"""Whether the Suite's add_calendar_event takes the client's uid (suite.calendar.doctype.calendar_event.client_uid)."""
	try:
		return "uid" in inspect.signature(add_calendar_event).parameters
	except (TypeError, ValueError):
		return False


def meet_usable():
	"""Whether the person's events get a Meet room here: the Suite's Meet is there and can be joined (the secret of its
	video server is set), and the person may make rooms, as the desk's switch needs. Read on every session: whatever goes
	wrong only says no."""
	try:
		from suite.meet.api import meeting
		from suite.meet.utils.sfu_config import get_sfu_config

		return (
			callable(getattr(meeting, "create", None))
			and bool(get_sfu_config().get("sfu_secret"))
			and bool(frappe.has_permission("Meet Room", "create"))
		)
	except Exception:
		return False


# A Meet room's address on this site, `/meet/<name>` (Meet names its rooms `xxxx-xxxx-xxxx`).
_ROOM_PATH = re.compile(r"^/meet/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")


def _room_of(href):
	"""The name of the Meet room of this site a link is, else None: the desk's Join reads it the same way, other
	services whose addresses happen to have `/meet/` are no room of it."""
	parts = urlsplit(str(href or ""))
	site = urlsplit(frappe.utils.get_url()).netloc.lower()
	if parts.scheme not in ("http", "https") or not site or parts.netloc.lower() != site:
		return None
	found = _ROOM_PATH.match(parts.path)
	return found.group(1) if found else None


def _meet_links(links, existing=False):
	"""The links among an event's `links` (a JSCalendar map) that are Meet rooms of this site, by their key; with
	`existing`, those whose room is still there (a room undone after its link reached the mail server is none)."""
	if not isinstance(links, dict):
		return {}
	out = {}
	for key, entry in links.items():
		room = _room_of(entry.get("href")) if isinstance(entry, dict) else None
		if room and (not existing or frappe.db.exists("Meet Room", room)):
			out[key] = entry
	return out


def _virtual_locations(event):
	"""The event's virtual locations: the mail server's own, and each Meet room of this site among its `links` as one,
	keyed as its link (the desk keeps a room there and writes no virtual location)."""
	value = event.get(ONLINE_PROPERTY)
	places = (
		{key: entry for key, entry in value.items() if isinstance(entry, dict)}
		if isinstance(value, dict)
		else {}
	)
	for key, link in _meet_links(event.get("links")).items():
		if any(place.get("uri") == link.get("href") for place in places.values()):
			continue
		places[key if key not in places else f"meet-{key}"] = {
			"@type": "VirtualLocation",
			"name": "Meet",
			"uri": link.get("href"),
			"features": dict(MEET_FEATURES),
		}
	return places


def _online_change(event, stored=None):
	"""What a client's `virtualLocations` asks of the event's Meet room, as (what, links):
	- ("make", []): it gives the request and the event has no room;
	- ("restore", links): it gives the request and names `links` without the room the event has (a resend, a copy read
	  before the room was made): the room's links, in the Suite's shape, go back with the others, and no room is made;
	- ("drop", hrefs): it names none of the event's rooms any more: their links go (the room stays);
	- (None, []): not named, or as it is.
	A place that is neither the request nor one the event has (or the client gives in its `links`) is refused: only a
	room made here is written."""
	if not isinstance(event, dict) or ONLINE_PROPERTY not in event:
		return None, []
	given = {entry.get("uri") for entry in _map(event, ONLINE_PROPERTY).values()}
	stored_rooms = _meet_links((stored or {}).get("links"), existing=True)
	named = _meet_links(event.get("links"), existing=True) if "links" in event else stored_rooms
	known = {place.get("uri") for place in _virtual_locations(stored or {}).values()} | {
		link.get("href") for link in _meet_links(event.get("links")).values()
	}
	if any(uri != ONLINE_MEETING_REQUEST and uri not in known for uri in given):
		raise ValueError("Only an online meeting made here is written: a Meet room of this site.")
	if ONLINE_MEETING_REQUEST in given:
		if named:
			return None, []
		if stored_rooms:
			return "restore", [
				{"uid": key, "href": link.get("href"), "content_type": link.get("contentType")}
				for key, link in stored_rooms.items()
			]
		return "make", []
	rooms = {link.get("href") for link in named.values()}
	return ("drop", sorted(rooms)) if rooms and not rooms & given else (None, [])


def _make_room(suite_account, title):
	"""(its name, its link): a Meet room for an event, as the desk's switch makes it (suite.meet.api.schedule): open,
	guests let in as the Meet settings say, the person its host, under the desk's limit on new rooms. Made in the
	event's savepoint, just before the event is written: an event the Suite then refuses leaves no room (the limit
	counts it, as in the desk)."""
	from frappe.utils import strip_html

	if not meet_usable():
		raise RoomRefused("forbidden", "No online meeting can be made here: Meet is not set up for you.")
	from suite.mail.doctype.user_account.user_account import is_jmap_account_belongs_to_user
	from suite.meet.api.meeting import create

	is_jmap_account_belongs_to_user(suite_account, raise_exception=True)
	try:
		# Meet keeps a title of 140 characters at most (a Data field).
		room = create(meeting_type="open", title=(title or "")[:140] or None)
	except frappe.RateLimitExceededError as e:
		raise RoomRefused(
			"rateLimit", strip_html(str(e)).strip() or "Too many meeting rooms were made from here just now."
		) from e
	except frappe.PermissionError as e:
		raise RoomRefused(
			"forbidden", strip_html(str(e)).strip() or "Your rights do not let you make meeting rooms."
		) from e
	return room, frappe.utils.get_url(f"/meet/{room}")


def _tie_room(room, suite_account, raw):
	"""The room knows its event, as the desk's create_scheduled_meeting records it (Meet's recording estimate reads it)."""
	frappe.db.set_value("Meet Room", room, "calendar_event", f"{suite_account}|{raw}")


def _online_answer(asked, made):
	"""What a set answers of an event's online meeting: its virtual locations as they now are, when the client named
	them; nothing otherwise."""
	if not isinstance(asked, dict) or ONLINE_PROPERTY not in asked:
		return {}
	return {ONLINE_PROPERTY: _virtual_locations(made or {})}


def _update_event(suite_account, client, calendars, vid, patch, notify):
	"""An event changed, by the desk's update_calendar_event: the properties the patch names replace the stored ones,
	the others stay, its organizer and draft state among them. An occurrence of a series is changed alone
	(update_calendar_event_instance). Invitations go out only from the organizer, never for a draft. The person's answer
	to someone else's invitation, the client asking for it to be sent from a calendar that sends answers, is the desk's
	answer (rsvp_calendar_event): recorded on their copy and told to the organizer, where a change of their copy would
	tell nobody; as in the desk, it is the whole invitation's, never one occurrence's. A patch that names the online
	meeting answers ("updated", its virtual locations as they now are); any other, True."""
	from suite.calendar.doctype.calendar_event.calendar_event import (
		update_calendar_event,
		update_calendar_event_instance,
	)
	from suite.calendar.doctype.calendar_event.fields import EventFields

	raw, stored, series, recurrence_id, now = _addressed(suite_account, client, vid)
	_check_writable(stored, calendars)
	_keep_own(patch if isinstance(patch, dict) else {}, stored)
	fields = _event_fields(patch, calendars)
	online, online_links = _online_change(patch, stored)
	if online and recurrence_id:
		raise ValueError("An online meeting is the whole series': change it on the series.")
	if online == "make" and _map(stored, "participants") and not _organizes(suite_account, stored):
		raise frappe.PermissionError("An online meeting is added by the meeting's organizer.")
	draft = bool(stored.get("isDraft"))
	asked = notify and not draft
	organizes = asked and _organizes(suite_account, stored)
	# The organizer's own status moved alone (a client that took one of their addresses for a guest's answers its
	# invitation): no change to tell the guests, and no answer to send to oneself.
	own_status_only = organizes and _answer_of(
		suite_account, stored, now, patch, fields, calendars, quiet=True
	)
	answer = (
		asked
		and not organizes
		and _may_answer(stored, calendars)
		and _answer_of(suite_account, stored, now, patch, fields, calendars)
	)
	if answer and recurrence_id:
		# The desk offers no answer to one occurrence of someone else's invitation: the mail server, finding no series on
		# the person's copy, gives the answer to every occurrence, and the copy loses its rule.
		raise frappe.PermissionError("An invitation is answered as a whole: answer its series.")
	if answer:
		from suite.calendar import jmap_events
		from suite.calendar.api import rsvp_calendar_event

		# The desk's own answer, with its rate limit (each answer is a mail): recorded on the person's first entry.
		rsvp_calendar_event(suite_account, raw, answer)
		# Invited under two of their addresses, the client moved another (it cannot know which the server lists first):
		# that one says the answer too, without a second mail, so that the copy reads as the client wrote it.
		first = next(iter(_own_entries(suite_account, stored)), None)
		for uid in _moved_own(suite_account, stored, now, fields, calendars):
			if uid != first:
				jmap_events.set_participation_status(client, raw, uid, answer, send_scheduling_messages=False)
		return True
	notify = organizes and not own_status_only
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
	room = None
	if online == "make":
		room, url = _make_room(suite_account, merged.get("title"))
		merged["links"] = [*(merged.get("links") or []), {"href": url, "content_type": "text/html"}]
	elif online == "restore":
		merged["links"] = [*(merged.get("links") or []), *online_links]
	elif online == "drop":
		# The links go, the room stays (with its recordings, which are its host's), as when the desk's switch is off.
		merged["links"] = [link for link in merged.get("links") or [] if link.get("href") not in online_links]
	update_calendar_event(
		account=suite_account,
		id=raw,
		uid=stored.get("uid"),
		organizer=_address(stored.get("organizerCalendarAddress")) or None,
		draft=draft,
		send_scheduling_messages=notify,
		**merged,
	)
	if room:
		_tie_room(room, suite_account, raw)
	if ONLINE_PROPERTY in patch:
		try:
			made = _stored(client, raw) or {}
		except Exception:
			made = {}
		if room and not made:
			made = {"links": {"meet": {"href": url}}}
		return "updated", _online_answer(patch, made)
	return True


def _destroy_event(suite_account, client, calendars, vid, notify):
	"""An event deleted, by the desk's delete_calendar_events; an occurrence of a series alone
	(delete_calendar_event_instance). Cancellations go out only from the organizer, never for a draft (nobody was
	invited); an attendee's copy deleted tells nobody, as in the desk."""
	from suite.calendar.doctype.calendar_event.calendar_event import (
		delete_calendar_event_instance,
		delete_calendar_events,
	)

	raw, stored, series, recurrence_id, _now = _addressed(suite_account, client, vid)
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
	"""(raw id, the event as stored, its series, its start, the event itself as the server holds it now) of the event a
	facade id names; series and start are None for an event that is not an occurrence. An occurrence named by its series
	and start is checked against its series (its calendar, its organizer, its draft state are the series'), after making
	sure it is still one of it; the last is then the occurrence, its own changes applied (its participants' answers)."""
	occurrence = _occurrence_of(vid)
	if occurrence:
		series, recurrence_id = occurrence
		stored = _stored(client, series)
		now = _occurrences_now(suite_account, [occurrence]).get(occurrence) if stored else None
		if not stored or not now:
			raise frappe.DoesNotExistError
		return series, stored, series, recurrence_id, now
	raw = _raw(vid, "V")
	stored = _stored(client, raw)
	if not stored:
		raise frappe.DoesNotExistError
	if stored.get("recurrenceId"):
		return raw, stored, _master_of(client, raw), stored["recurrenceId"], stored
	return raw, stored, None, None, stored


# What a person answers an invitation with: the Suite's PARTICIPATION_RESPONSES, which record_rsvp takes (not imported:
# this module is read where the Suite may not be installed).
ANSWERS = ("accepted", "tentative", "declined")


def _may_answer(stored, calendars):
	"""Whether the person's answers go to organizers from the event's calendars (`mayRSVP`): a mail server's calendars
	say so; a calendar the Suite keeps in the instance does not, as it sends no mail (an answer there stays on the copy,
	as before)."""
	held = [k for k, on in (stored.get("calendarIds") or {}).items() if on]
	return bool(held) and all(_rights(calendars[k].get("myRights")).get("mayRSVP") for k in held)


def _rsvp_address(entry):
	"""The address record_rsvp knows a participant by: its calendar address, else its email, in lower case, without
	`mailto:` (suite.calendar.api.rsvp)."""
	return str(entry.get("calendarAddress") or entry.get("email") or "").lower().replace("mailto:", "")


def _as_compared(row):
	"""A participant as _event_fields writes it, for telling whether two differ: without what the Suite works out again
	when it writes one (where invitations go, its scheduling id, whether a reply is expected), its address and its status
	in lower case whatever a client spelled, its roles those that are on."""
	roles = row.get("roles") if isinstance(row.get("roles"), dict) else {}
	return {
		**{key: value for key, value in row.items() if key not in ("send_to", "schedule_id", "expect_reply")},
		"email": re.sub(r"(?i)^mailto:", "", str(row.get("email") or "")).lower(),
		"roles": sorted(role for role, on in roles.items() if on),
		"participation_status": str(row.get("participation_status") or "").lower() or None,
	}


def _answer_of(suite_account, stored, now, patch, fields, calendars, quiet=False):
	"""The person's answer to an invitation that an update gives, or None for another change. An answer writes the
	participants alone, and changes the person's own entries of them, from the event as it is now (`now`, an occurrence's
	own), in their participationStatus alone, now accepted, tentative or declined. The person's entries are those whose
	address is one of theirs (_own_entries): invited under two, a client may move either, and record_rsvp answers for
	the first (the organizer is told the same). `fields` are the patch's, as _event_fields read them. The person's own
	status moved to an answer with something else changed beside it is written as before, and said in the error log
	(not with `quiet`): the organizer is not told."""
	if not isinstance(patch, dict):
		return None
	given = {row["uid"]: _as_compared(row) for row in fields.get("participants") or []}
	read = _event_fields({"participants": now.get("participants")}, calendars).get("participants") or []
	kept = {row["uid"]: _as_compared(row) for row in read}
	moved = _moved_own(suite_account, stored, now, fields, calendars)
	statuses = {given[uid]["participation_status"] for uid in moved}
	if not moved or len(statuses) != 1 or not statuses <= set(ANSWERS):
		return None
	if (
		set(patch) - SERVER_SET == {"participants"}
		and set(given) == set(kept)
		and all(row == kept[uid] for uid, row in given.items() if uid not in moved)
		and all(
			{**given[uid], "participation_status": None} == {**kept[uid], "participation_status": None}
			for uid in moved
		)
	):
		return statuses.pop()
	if not quiet:
		frappe.log_error(
			"NeoMail: an answer to an invitation was written on the copy alone",
			f"The update changed more than the person's answer (properties: {sorted(set(patch) - SERVER_SET)}): "
			"its organizer is not told.",
		)
	return None


def _moved_own(suite_account, stored, now, fields, calendars):
	"""The person's own entries (_own_entries) whose status the patch's participants (`fields`) move, from the event as
	it is now."""
	given = {row["uid"]: _as_compared(row) for row in fields.get("participants") or []}
	read = _event_fields({"participants": now.get("participants")}, calendars).get("participants") or []
	kept = {row["uid"]: _as_compared(row) for row in read}
	return [
		uid
		for uid in _own_entries(suite_account, stored)
		if uid in kept
		and uid in given
		and given[uid]["participation_status"] != kept[uid]["participation_status"]
	]


def _own_entries(suite_account, stored):
	"""The participants (their keys) of `stored` whose address is one of the person's, in the copy's order: the first
	is the one record_rsvp answers for."""
	from suite.mail.jmap import get_participant_identities

	own = {str(identity["email"]).lower() for identity in get_participant_identities(suite_account)}
	return [uid for uid, entry in _map(stored, "participants").items() if _rsvp_address(entry) in own]


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
	online = _virtual_locations(event)
	if online:
		out[ONLINE_PROPERTY] = online
	if properties is not None:
		keep = set(properties) | {"id", "@type"}
		out = {k: v for k, v in out.items() if k in keep}
	return out


def participant_identity_get(args):
	"""The addresses the person takes part in events under (JMAP for Calendars' ParticipantIdentity): the Suite's own
	list for their account, as the desk reads it to tell their entry of an event and whether they organize it. A client
	that knows them all tells its own meetings and answers from somebody else's, an alias included."""
	aid, suite_account = _calendar_account(args)
	ids = _string_ids(args)
	from suite.mail.jmap import get_participant_identities

	listed = [
		{
			"id": str(identity.get("id")),
			"name": identity.get("_name") or "",
			"calendarAddress": "mailto:" + str(identity.get("email") or ""),
			"isDefault": bool(cint(identity.get("default"))),
		}
		for identity in _reading(lambda: get_participant_identities(suite_account))
		if identity.get("email")
	]
	if ids is not None:
		listed = [identity for identity in listed if identity["id"] in ids]
	found = {identity["id"] for identity in listed}
	return {
		"accountId": aid,
		"state": "0",
		"list": listed,
		"notFound": [i for i in ids or [] if i not in found],
	}


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
	"ParticipantIdentity/get": participant_identity_get,
	"ParticipantIdentity/changes": no_changes,
}
