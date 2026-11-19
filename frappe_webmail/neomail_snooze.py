# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""« Plus tard » for NeoMail (snooze): a person puts a message away until a chosen time; it leaves the folder it was in,
and comes back to it at that time, unread, even with every NeoMail window closed.

Where it waits. In a real folder of the mailbox on its IMAP server, named by this server (SNOOZED, in the language of
the mailbox's owner: « Plus tard »), so that the message is out of the Inbox in every other client too, and anyone who
opens that folder elsewhere sees normal mail in it. The folder is found again by its name (any of FOLDER_NAMES, or the
owner's word for it) at the top of the mailbox, and made, and subscribed to, the first time something is put away.

What is kept. One `NeoMail Snooze` record per message put away: whose (the person who did it), which mailbox, the
message's Message-ID and where it is (folder, UID, UIDVALIDITY), the folder it came from, when it comes back (UTC), and
its state: Waiting, Returned, CalledOff (the person moved or deleted it meanwhile, or called it off) or Failed (the mail
server would not take it back, MAX_TRIES times; the message stays in the folder, where the person sees it, and putting it
away again makes the same record wait again). One waiting record per person, mailbox, message and folder it came from
(`active_key`, unique): two tabs that put the same message away make one; two copies of one message in two folders (a
message to oneself, in Sent and in the Inbox) make two.

How it is reached. JMAP methods of our own under their own capability (SNOOZE), on the pattern of mailcraft_settings:
`NeomailSnooze/get` (the caller's own records of the mailbox, the waiting and the failed, and where the folder is) and
`NeomailSnooze/set` (create: put a message away; update: another time, or `state: "returned"` to bring it back now;
destroy: call it off, the message staying where it is). Only ever the caller's own records: a mailbox they may open (the
webmail's rule, `get_account`), and in it what they put away. A create never leaves a message away without its record:
the folder is made if need be, the record written, then the message moved; a move the server refused takes the record
back, and one whose outcome can't be told (the connection lost on the way) keeps it (the job finds the message by its
Message-ID, or calls the record off when it is not in the folder).

How it comes back. `tick`, every minute (hooks.py, `scheduler_events`): one indexed read when nothing is due; else one
job per mailbox (deduplicated), run as the mailbox's owner, that finds each message again (by its UID while that holds,
by its Message-ID once the server numbered it anew, in the mailbox's Snoozed folder of now when the one it was put in
was renamed), clears `\\Seen`, and moves it back with the webmail's own move (`_move_messages`): to the folder it came
from, or the Inbox when that one is gone. A move a server without MOVE left half done (copied, not yet taken out) is
finished, never copied again. A mailbox's moves, the job's and the person's (put away, another time, bring back now, call
off), take one lock: a message comes back once. A message no longer in the folder is not looked for again (CalledOff); a
mail server that fails, or refuses the folder for now, is tried again later (RETRY_AFTER), MAX_TRIES times, then the
record is Failed and the Error Log says so, once an hour for a mailbox.
"""

import contextlib
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import frappe
from frappe import _

from frappe_webmail import webmail_api as webmail
from frappe_webmail.mailcraft_jmap import (
	MAX_OBJECTS,
	JmapError,
	_account,
	_message_ids,
	_message_of,
	_select,
	email_id,
	log_quietly,
	mailbox_id,
	moment_of,
)

SNOOZE = "https://neoffice.me/jmap/neomail-snooze"
DOCTYPE = "NeoMail Snooze"
WAITING, RETURNED, CALLED_OFF, FAILED = "Waiting", "Returned", "CalledOff", "Failed"
# The states as JMAP says them
CODES = {WAITING: "waiting", RETURNED: "returned", CALLED_OFF: "calledOff", FAILED: "failed"}
# The source text of the folder's name: translated in the owner's language when the folder is made (« Plus tard »)
SNOOZED = "Snoozed"
# The names a folder made here, by a NeoMail of another language or by MailCraft, has: found again by any of them
FOLDER_NAMES = ("Plus tard", "Snoozed", "Später", "Più tardi", "Más tarde")
# The furthest a return may lie ahead, as NeoMail takes it (mailcraft_model::MAX_SNOOZE_AHEAD): five years
MAX_AHEAD = timedelta(days=5 * 366)
MAX_TRIES = 3
# How long after a failed try the next one is made, by the number of tries so far
RETRY_AFTER = {1: timedelta(minutes=10), 2: timedelta(hours=1)}
# The Error Log says a mailbox's Failed records once in this long
FAILED_QUIET_S = 3600
# What one minute's look takes on: mailboxes enqueued, and messages one job brings back (the rest at the next minute)
MAX_ACCOUNTS = 500
MAX_ROWS = 100
# The lock of a mailbox's moves: held this long at most, and waited for this long by the person's call
LOCK_SECONDS = 300
LOCK_WAIT = 20
# What one call may spend before it refuses the rest (a web worker is stopped at two minutes), and what one job may spend
# before it leaves the rest to the next minute (its queue's limit is five)
CALL_BUDGET_S = 60
JOB_BUDGET_S = 150
FOLDER_CACHE_S = 3600
MAX_MESSAGE_ID = 998
JOB = "frappe_webmail.neomail_snooze.return_due"


class _Busy(Exception):
	"""Another call or job holds the mailbox's lock."""


class _TryAgain(Exception):
	"""The mail server would not open the folder just now (it is there): a try that failed, not a message gone."""


class _Refused(Exception):
	"""What one object of a NeomailSnooze/set comes to when it isn't done: a SetError (RFC 8620 §5.3)."""

	def __init__(self, type_, description=""):
		super().__init__(description)
		self.answer = {"type": type_, "description": description}


def ready():
	"""Whether the records' table is there: not on a site whose `bench migrate` is still to run after this change, which
	then neither offers nor takes « Plus tard »."""
	return frappe.db.table_exists(DOCTYPE)


def session_parts(account):
	"""What every mailbox's session adds where the records are kept: the capability, and what it takes."""
	if not ready():
		return {}, {}
	return {SNOOZE: {}}, {SNOOZE: {"maxAheadDays": MAX_AHEAD.days, "maxTries": MAX_TRIES}}


# ---------------------------------------------------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------------------------------------------------


def _now():
	"""Now, in UTC (a function of its own: the tests set the clock)."""
	return datetime.now(timezone.utc)


def _naive(moment):
	"""An aware moment as the records keep it: naive, in UTC."""
	return moment.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _utc_text(value):
	"""A moment kept naive in UTC as JMAP writes it; None for none."""
	if not value:
		return None
	moment = frappe.utils.get_datetime(value)
	return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _until(value):
	"""When a message comes back, as a person asks it (a JMAP UTCDate): refused when it is not a time, or not in the
	future; brought back to MAX_AHEAD from now when it lies further."""
	moment = moment_of(value)
	if moment is None:
		raise _Refused("invalidProperties", _("The time to bring the message back is not a time."))
	now = _now()
	if moment <= now:
		raise _Refused("invalidProperties", _("Choose a time in the future."))
	return _naive(min(moment, now + MAX_AHEAD))


# ---------------------------------------------------------------------------------------------------------------
# The folder
# ---------------------------------------------------------------------------------------------------------------


def _owner_language(account):
	return (
		frappe.db.get_value("User", account.user, "language")
		or frappe.db.get_single_value("System Settings", "language")
		or "en"
	)


def _folder_key(account):
	return f"neomail_snooze_folder:{account.name}"


def _text(value):
	return value.decode() if isinstance(value, bytes) else str(value or "")


def _prefix(client):
	"""The personal namespace's prefix (RFC 2342: `INBOX.` on a server whose folders all lie under the Inbox), or ""."""
	try:
		namespace = client.namespace()
		personal = getattr(namespace, "personal", None) or (namespace[0] if namespace else None) or ()
		return _text(personal[0][0]) if personal else ""
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		return ""


def _snoozed_folder(client, account, make=False):
	"""The path of the mailbox's Snoozed folder: a folder of one of its names (the owner's word for it first) at the top of
	the mailbox's own folders (under the namespace's prefix, where the server has one), or None; made and subscribed to
	when there is none and `make` says so."""
	own_word = _(SNOOZED, lang=_owner_language(account))
	wanted = [own_word.lower(), *(name.lower() for name in FOLDER_NAMES)]
	prefix = _prefix(client)
	top = {}
	for flags, delimiter, name in client.list_folders():
		delimiter, name = _text(delimiter), _text(name)
		if b"\\Noselect" in (flags or ()) or not name.startswith(prefix):
			continue
		leaf = name[len(prefix) :]
		if not leaf or (delimiter and delimiter in leaf):
			continue
		top.setdefault(leaf.lower(), name)
	cached = (frappe.cache().get_value(_folder_key(account)) or {}).get("path")
	if cached and cached[len(prefix) :].lower() in top and top[cached[len(prefix) :].lower()] == cached:
		return cached
	found = next((top[name] for name in wanted if name in top), None)
	if found is None and make:
		found = prefix + own_word
		client.create_folder(found)
		with contextlib.suppress(Exception):
			# Other clients list the folders subscribed to: the folder is hidden from nothing.
			client.subscribe_folder(found)
	frappe.cache().set_value(_folder_key(account), {"path": found}, expires_in_sec=FOLDER_CACHE_S)
	return found


def _known_folder(account):
	"""The Snoozed folder as last found, an hour at most (no IMAP), or found now; None when the mailbox has none or
	can't be read."""
	cached = frappe.cache().get_value(_folder_key(account))
	if isinstance(cached, dict):
		return cached.get("path")
	try:
		with webmail.imap_session(account) as client:
			return _snoozed_folder(client, account)
	except Exception as e:
		if not isinstance(e, webmail.WebmailConnectionError | webmail.WebmailAuthenticationError):
			log_quietly("NeoMail: the Snoozed folder could not be looked for", e)
		return None


# ---------------------------------------------------------------------------------------------------------------
# Finding a message
# ---------------------------------------------------------------------------------------------------------------


def _key(user, account_name, message_id, from_folder):
	return hashlib.sha256(f"{user}\n{account_name}\n{message_id}\n{from_folder}".encode()).hexdigest()


def _clean_id(value):
	"""A Message-ID as the records keep it and the mail server is searched for: without its angle brackets (a text field
	would keep them escaped), lower case; None for what can't be one (a blank, a quote, a bracket, a line break, what is
	not ASCII)."""
	if isinstance(value, bytes):
		try:
			value = value.decode("ascii")
		except UnicodeDecodeError:
			return None
	text = str(value or "").strip().lower()
	text = text[1:-1].strip() if text.startswith("<") and text.endswith(">") else text
	if not text or len(text) > MAX_MESSAGE_ID or not text.isascii() or any(c in text for c in '<>\r\n\t"\\ '):
		return None
	return text


def _uidnext(client, folder):
	try:
		return int((client.folder_status(folder, [b"UIDNEXT"]) or {}).get(b"UIDNEXT") or 0)
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		return 0


def _ids(client, messages):
	"""The Message-ID of each of these messages of the selected folder, by UID, as the records keep it (text)."""
	return {uid: _clean_id(mid) for uid, mid in _message_ids(client, messages).items()}


def _by_message_id(client, message_id):
	"""The UIDs of the selected folder whose Message-ID is exactly `message_id`."""
	found = client.search(["HEADER", "Message-ID", message_id])
	if not found:
		return []
	return sorted(uid for uid, mid in _ids(client, list(found)).items() if mid == message_id)


def _landed(client, folder, before, message_id):
	"""(UIDVALIDITY, UID) of a message just moved into `folder`: the one arrival since UIDNEXT was `before` with its
	Message-ID, else the one message of the folder with it; UID None when it can't be told."""
	validity = _select(client, folder)
	if not validity:
		return 0, None
	if before:
		arrived = [
			uid for uid, mid in _ids(client, f"{before}:*").items() if uid >= before and mid == message_id
		]
		if len(arrived) == 1:
			return validity, arrived[0]
	same = _by_message_id(client, message_id)
	return validity, (same[0] if len(same) == 1 else None)


def _folders(client):
	"""The selectable folders of the mailbox, by path."""
	return {
		_text(name) for flags, _delimiter, name in client.list_folders() if b"\\Noselect" not in (flags or ())
	}


def _open(client, folder):
	"""Select `folder` (read-write): its UIDVALIDITY; None when the folder is not there; _TryAgain when it is there and the
	server would not open it just now (a temporary NO)."""
	try:
		answer = client.select_folder(folder) or {}
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		if folder in _folders(client):
			raise _TryAgain(str(e)[:200]) from e
		return None
	return int(answer.get(b"UIDVALIDITY") or 0) or None


def _find(client, account, row):
	"""(folder, UIDVALIDITY, UID) of the message of a record now, its folder left selected (read-write): its UID while the
	folder's UIDVALIDITY and its Message-ID say it is still that message, else the message of that Message-ID (a server
	that numbered the folder anew); in the mailbox's Snoozed folder of now when the one it was put in is gone (renamed).
	UID None when the message is in neither; _TryAgain when the server would not open the folder just now."""
	validity = _open(client, row.folder)
	if validity:
		if row.uid and int(row.uidvalidity or 0) == validity:
			if _ids(client, [int(row.uid)]).get(int(row.uid)) == row.message_id:
				return row.folder, validity, int(row.uid)
		same = _by_message_id(client, row.message_id)
		return row.folder, validity, (same[-1] if same else None)
	now = _snoozed_folder(client, account)
	if now and now != row.folder:
		validity = _open(client, now)
		if validity:
			same = _by_message_id(client, row.message_id)
			if same:
				return now, validity, same[-1]
	return row.folder, 0, None


# ---------------------------------------------------------------------------------------------------------------
# The lock of a mailbox's moves
# ---------------------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def _locked(account_name, wait=LOCK_WAIT):
	"""The lock of a mailbox's moves, across the instance's workers; _Busy when another holds it past `wait`. It yields
	`guard`, called before each move of a job: the lock is still this job's, for LOCK_SECONDS more, or _Busy."""
	cache = frappe.cache()
	lock = cache.lock(
		cache.make_key("neomail_snooze_lock:" + account_name), timeout=LOCK_SECONDS, blocking_timeout=wait
	)
	if not lock.acquire(blocking=wait > 0):
		raise _Busy

	def guard():
		try:
			lock.reacquire()
		except Exception as e:
			raise _Busy from e

	try:
		yield guard
	finally:
		# Past LOCK_SECONDS the lock went by itself: nothing to give back.
		with contextlib.suppress(Exception):
			lock.release()


# ---------------------------------------------------------------------------------------------------------------
# NeomailSnooze/get
# ---------------------------------------------------------------------------------------------------------------

FIELDS = [
	"name",
	"message_id",
	"folder",
	"uid",
	"uidvalidity",
	"from_folder",
	"until_utc",
	"state",
	"returned_at",
	"tries",
	"last_error",
	"modified",
]


def _rows(user, account_name, names=None):
	filters = {"user": user, "account": account_name}
	if names is None:
		filters["state"] = ("in", (WAITING, FAILED))
	else:
		filters["name"] = ("in", names or [""])
	return frappe.get_all(
		DOCTYPE, filters=filters, fields=FIELDS, order_by="until_utc asc", limit=MAX_OBJECTS
	)


def _error_text(kind):
	"""What the person reads of why a message did not come back."""
	return {
		"sign-in": _("The mail server refused the mailbox's password."),
		"connection": _("The mail server could not be reached."),
		"mailbox": _("The mailbox is disabled or no longer yours to open."),
	}.get(kind or "", _("The mail server would not move it back."))


def _object(row):
	out = {
		"id": row.name,
		"emailId": email_id(row.folder, row.uidvalidity, row.uid) if row.uid and row.uidvalidity else None,
		"messageId": row.message_id,
		"mailboxId": mailbox_id(row.folder) if row.folder else None,
		"fromMailboxId": mailbox_id(row.from_folder) if row.from_folder else None,
		"until": _utc_text(row.until_utc),
		"state": CODES.get(row.state, "waiting"),
		"returnedAt": _utc_text(row.returned_at),
		"tries": int(row.tries or 0),
	}
	if row.state == FAILED:
		out["error"] = _error_text(row.last_error)
	return out


def _state(rows):
	text = json.dumps(
		[[r.name, r.state, str(r.until_utc), r.uid, str(r.modified)] for r in rows], default=str
	)
	return hashlib.sha256(text.encode()).hexdigest()[:16]


def snooze_get(args):
	account = _account(args.get("accountId"))
	if not ready():
		raise JmapError("unknownMethod", "NeomailSnooze/get")
	ids = args.get("ids")
	if ids is not None and (
		not isinstance(ids, list)
		or len(ids) > MAX_OBJECTS
		or not all(isinstance(i, str) and len(i) <= 140 for i in ids)
	):
		raise JmapError("invalidArguments", "ids")
	user = frappe.session.user
	rows = _rows(user, account.name, ids)
	found = {r.name for r in rows}
	folder = _known_folder(account)
	return {
		"accountId": args.get("accountId"),
		"state": _state(_rows(user, account.name)),
		"list": [_object(r) for r in rows],
		"notFound": [i for i in (ids or []) if i not in found],
		# Where the Snoozed folder is (none until something was first put away): NeoMail names it « Plus tard ».
		"mailboxId": mailbox_id(folder) if folder else None,
	}


# ---------------------------------------------------------------------------------------------------------------
# NeomailSnooze/set
# ---------------------------------------------------------------------------------------------------------------


def snooze_set(args):
	account = _account(args.get("accountId"))
	if not ready():
		raise JmapError("unknownMethod", "NeomailSnooze/set")
	create, update, destroy = args.get("create") or {}, args.get("update") or {}, args.get("destroy") or []
	if not isinstance(create, dict) or not isinstance(update, dict) or not isinstance(destroy, list):
		raise JmapError("invalidArguments", "create and update are objects, destroy is a list")
	if len(create) + len(update) + len(destroy) > MAX_OBJECTS:
		raise JmapError("requestTooLarge", str(MAX_OBJECTS))
	user = frappe.session.user
	before = _state(_rows(user, account.name))
	created, not_created, updated, not_updated, destroyed, not_destroyed = {}, {}, {}, {}, [], {}
	deadline = time.monotonic() + CALL_BUDGET_S

	def guarded(run):
		# Past the call's budget the rest is refused as « not now »: NeoMail asks again.
		if time.monotonic() > deadline:
			raise _Refused("serverUnavailable", _("The mailbox is busy: try again in a moment."))
		return _guarded(account, run)

	for cid, spec in create.items():
		spec = spec if isinstance(spec, dict) else {}
		try:
			created[str(cid)[:100]] = guarded(lambda spec=spec: _create(account, user, spec))
		except _Refused as e:
			not_created[str(cid)[:100]] = e.answer
	for name, patch in update.items():
		try:
			patch = patch if isinstance(patch, dict) else None
			updated[str(name)[:140]] = guarded(
				lambda name=name, patch=patch: _update(account, user, str(name), patch)
			)
		except _Refused as e:
			not_updated[str(name)[:140]] = e.answer
	for name in destroy:
		try:
			guarded(lambda name=name: _call_off(user, account, str(name)))
			destroyed.append(str(name))
		except _Refused as e:
			not_destroyed[str(name)[:140]] = e.answer
	return {
		"accountId": args.get("accountId"),
		"oldState": before,
		"newState": _state(_rows(user, account.name)),
		"created": created or None,
		"notCreated": not_created or None,
		"updated": updated or None,
		"notUpdated": not_updated or None,
		"destroyed": destroyed or None,
		"notDestroyed": not_destroyed or None,
	}


def _imap_refusal(e):
	"""The SetError of a mail server that failed: nothing done and to be asked again, or done perhaps."""
	if isinstance(e, webmail.WebmailConnectionLost):
		return _Refused("serverFail", str(e)[:300])
	if isinstance(e, webmail.WebmailConnectionError | webmail.WebmailAuthenticationError):
		return _Refused("serverUnavailable", str(e)[:300])
	if isinstance(e, _TryAgain) or webmail._imap_is_connection_error(e):
		return _Refused("serverUnavailable", _("The mail server could not be reached."))
	return None


def _guarded(account, run):
	"""Run one object of a NeomailSnooze/set under the mailbox's lock: its SetError when it is not done (the lock held by
	another, the mail server failing, anything unforeseen: logged)."""
	try:
		with _locked(account.name):
			return run()
	except _Busy:
		raise _Refused("serverUnavailable", _("The mailbox is busy: try again in a moment.")) from None
	except _Refused:
		raise
	except Exception as e:
		frappe.db.rollback()
		refusal = _imap_refusal(e)
		if refusal:
			raise refusal from None
		frappe.log_error("NeoMail: a snoozed message could not be changed", frappe.get_traceback())
		raise _Refused("serverFail", _("The mail server could not answer.")) from None


def _answer_of(name):
	return _object(frappe.db.get_value(DOCTYPE, name, FIELDS, as_dict=True))


def _commit():
	frappe.db.commit()  # nosemgrep: a record goes with the move it is about, whatever comes after


def _wait_again(name, until, user, account_name):
	"""A record waits (again) until `until`, its tries forgotten: another time asked, or one that failed put away anew.
	When another record of the same message and folder waits already, that one takes the time and this one is over.
	Answers the record that waits."""
	row = frappe.db.get_value(DOCTYPE, name, ["message_id", "from_folder"], as_dict=True)
	key = _key(user, account_name, row.message_id, row.from_folder)
	holder = frappe.db.get_value(DOCTYPE, {"active_key": key, "name": ("!=", name)}, "name")
	if holder:
		frappe.db.set_value(DOCTYPE, name, {"state": CALLED_OFF, "active_key": None})
		name = holder
	frappe.db.set_value(
		DOCTYPE,
		name,
		{
			"state": WAITING,
			"until_utc": until,
			"tries": 0,
			"next_try": None,
			"last_error": None,
			"active_key": key,
		},
	)
	_commit()
	return name


def _waiting_by_key(user, account_name, message_id, from_folder):
	return frappe.db.get_value(
		DOCTYPE, {"active_key": _key(user, account_name, message_id, from_folder)}, "name"
	)


def _waiting_for(user, account_name, message_id, place=None):
	"""The person's records of this message that wait or failed (whatever folder it came from): the one of that very place
	(folder, UIDVALIDITY, UID) first, then the waiting before the failed, the latest first."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={
			"user": user,
			"account": account_name,
			"message_id": message_id,
			"state": ("in", (WAITING, FAILED)),
		},
		fields=["name", "folder", "uidvalidity", "uid", "state", "modified"],
		order_by="modified desc",
	)
	exact = [r for r in rows if place and (r.folder, int(r.uidvalidity or 0), int(r.uid or 0)) == place]
	rest = sorted((r for r in rows if r not in exact), key=lambda r: r.state != WAITING)
	return [r.name for r in exact + rest]


def _create(account, user, spec):
	"""Put the message `emailId` away until `until` (the lock is held): the Snoozed folder made if need be, the record
	written, then the message moved. A message that waits already (put away from another tab, or again from the folder)
	gets the new time, and no second record; one whose return failed waits again in the same record."""
	from frappe_webmail import mailcraft_changes

	until = _until(spec.get("until"))
	place = _message_of(spec.get("emailId"))
	if not place or str(spec.get("emailId") or "")[:1] != "E":
		raise _Refused("invalidProperties", "emailId")
	asked_id = _clean_id(spec.get("messageId")) if spec.get("messageId") else None
	folder, validity, uid = place
	with webmail.imap_session(account) as client:
		present = _select(client, folder) == validity and bool(client.search(["UID", str(uid)]))
		if not present:
			# Not there (any more): put away meanwhile by another tab from this folder, whose record answers, or gone.
			existing = asked_id and _waiting_by_key(user, account.name, asked_id, folder)
			if existing:
				return _answer_of(_wait_again(existing, until, user, account.name))
			raise _Refused("notFound", _("This message is no longer in its folder."))
		message_id = _ids(client, [uid]).get(uid)
		if not message_id:
			raise _Refused(
				"invalidProperties",
				_("This message has no Message-ID: it could not be found again once put away."),
			)
		snoozed = _snoozed_folder(client, account, make=True)
		if folder == snoozed:
			# Again from the folder: its record waits again (the latest, when there were several), or a message moved
			# there by hand waits now, and comes back to the Inbox.
			kept = _waiting_for(user, account.name, message_id, (folder, validity, uid))
			if kept:
				return _answer_of(_wait_again(kept[0], until, user, account.name))
			return _answer_of(_record(account, user, message_id, snoozed, validity, uid, "INBOX", until))
		# Records of this message that wait for a copy no longer in the folder (the person took it out by hand, here or
		# elsewhere): over, or the job would find this copy by its Message-ID and bring it back at their time.
		for other in _waiting_for(user, account.name, message_id):
			row = frappe.db.get_value(DOCTYPE, other, FIELDS, as_dict=True)
			if _find(client, account, row)[2] is None:
				frappe.db.set_value(DOCTYPE, other, {"state": CALLED_OFF, "active_key": None})
			elif _key(user, account.name, message_id, row.from_folder) == _key(
				user, account.name, message_id, folder
			):
				raise _Refused("invalidProperties", _("A copy of this message is put away already."))
		before = _uidnext(client, snoozed)
		name = _record(account, user, message_id, snoozed, 0, 0, folder, until)
		try:
			_open(client, folder)
			webmail._move_messages(client, [uid], snoozed)
		except Exception as e:
			_settle_failed_move(client, name, (folder, uid), (snoozed, before), message_id, e)
			raise
		new_validity, new_uid = 0, None
		try:
			new_validity, new_uid = _landed(client, snoozed, before, message_id)
		except Exception as e:
			log_quietly("NeoMail: where a message put away went could not be read", e)
		frappe.db.set_value(DOCTYPE, name, {"uid": int(new_uid or 0), "uidvalidity": int(new_validity or 0)})
		_commit()
	answer = _answer_of(name)
	mailcraft_changes.logged(
		account,
		created=[answer["emailId"]] if answer.get("emailId") else [],
		destroyed=[email_id(folder, validity, uid)],
	)
	return answer


def _settle_failed_move(client, name, source, target, message_id, error):
	"""After a move that raised. The connection lost on the way: nobody can tell, the record stays (the job finds the
	message by its Message-ID, or calls the record off when it is not in the folder). Else, where the message is now: still
	where it was and not copied (the server refused it), the record goes; copied but the original not taken out (a server
	without MOVE), the copy is taken back out of the Snoozed folder and the record goes; gone from where it was, it waits,
	and the record stays."""
	if isinstance(error, webmail.WebmailConnectionError) or webmail._imap_is_connection_error(error):
		return
	(folder, uid), (snoozed, before) = source, target
	try:
		still = _select(client, folder) is not None and bool(
			client.search(["UID", str(uid), "NOT", "DELETED"])
		)
		if not still:
			return
		if _select(client, snoozed) and before:
			copies = [
				u for u, mid in _ids(client, f"{before}:*").items() if u >= before and mid == message_id
			]
			if copies:
				client.select_folder(snoozed)
				webmail._remove_from_folder(client, copies)
	except Exception as e:
		log_quietly("NeoMail: a message put away could not be looked for after its move failed", e)
		return
	frappe.db.delete(DOCTYPE, {"name": name})
	_commit()


def _record(account, user, message_id, folder, validity, uid, from_folder, until):
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"user": user,
			"account": account.name,
			"message_id": message_id,
			"folder": folder,
			"uid": int(uid or 0),
			"uidvalidity": int(validity or 0),
			"from_folder": from_folder,
			"until_utc": until,
			"state": WAITING,
			"tries": 0,
			"active_key": _key(user, account.name, message_id, from_folder),
		}
	)
	doc.insert(ignore_permissions=True)
	_commit()
	return doc.name


def _mine(user, account_name, name):
	row = frappe.db.get_value(
		DOCTYPE,
		{"name": name, "user": user, "account": account_name},
		[*FIELDS, "user", "account"],
		as_dict=True,
	)
	if not row:
		raise _Refused("notFound")
	return row


def _update(account, user, name, patch):
	"""Another time for a waiting message (`until`), or bring it back now (`state: "returned"`); the lock is held."""
	if patch is None or not patch or set(patch) - {"until", "state"}:
		raise _Refused("invalidPatch")
	row = _mine(user, account.name, name)
	if "until" in patch:
		until = _until(patch["until"])
		if row.state != WAITING:
			raise _Refused("invalidProperties", _("This message is no longer put away."))
		name = _wait_again(name, until, user, account.name)
	if "state" in patch:
		if patch["state"] != CODES[RETURNED]:
			raise _Refused("invalidProperties", "state")
		return _bring_back_now(account, name)
	return None


def _bring_back_now(account, name):
	"""The person brings it back before its time: as the job would, under the same lock, so that it comes back once."""
	# Read again under the lock: the job may have brought it back meanwhile.
	row = frappe.db.get_value(DOCTYPE, name, [*FIELDS, "account"], as_dict=True)
	if row.state == RETURNED:
		return {"state": CODES[RETURNED]}
	if row.state == CALLED_OFF:
		raise _Refused("notFound", _("This message is no longer put away."))
	back = _bring_back(account, row)
	if back["state"] == CODES[CALLED_OFF]:
		raise _Refused("notFound", _("This message is no longer in its folder."))
	return back


def _call_off(user, account, name):
	"""It waits no longer: the message stays where it is (the lock is held)."""
	row = _mine(user, account.name, name)
	if row.state in (WAITING, FAILED):
		frappe.db.set_value(DOCTYPE, name, {"state": CALLED_OFF, "active_key": None})
		_commit()


# ---------------------------------------------------------------------------------------------------------------
# Coming back
# ---------------------------------------------------------------------------------------------------------------


def _bring_back(account, row):
	"""Bring the message of a record back (the lock is held): found again, made unread, moved to the folder it came from
	(the Inbox when that one is gone). CalledOff when it is no longer there. Answers its state, and where it is now
	(`mailboxId`, and `emailId` when it can be told). Raises what the mail server raised; the record is then as it was."""
	from frappe_webmail import mailcraft_changes

	with webmail.imap_session(account) as client:
		folder, old_validity, uid = _find(client, account, row)
		if uid is None:
			# Moved or deleted by the person meanwhile: nothing comes back, and nothing is looked for again.
			_set(row.name, state=CALLED_OFF, active_key=None)
			return {"state": CODES[CALLED_OFF]}
		folders = _folders(client)
		target = row.from_folder if row.from_folder in folders and row.from_folder != folder else "INBOX"
		flags = (client.fetch([uid], ["FLAGS"]).get(uid) or {}).get(b"FLAGS") or ()
		deleted = b"\\Deleted" in flags
		# A try before this one may have copied it already (a server without MOVE: marked deleted here, or the connection
		# lost after the copy): when the folder it goes to has it, only taking it out of here is left to do.
		there = (
			(deleted or int(row.tries or 0) > 0)
			and _open(client, target)
			and _by_message_id(client, row.message_id)
		)
		half_done = bool(there)
		if deleted and not half_done:
			# Deleted by the person in another client, not yet erased: it does not come back.
			_set(row.name, state=CALLED_OFF, active_key=None)
			return {"state": CODES[CALLED_OFF]}
		before = _uidnext(client, target)
		client.select_folder(folder)
		if half_done:
			# A server without MOVE copied it the last time, and failed to take it out: only that is left to do.
			webmail._remove_from_folder(client, [uid])
		else:
			client.remove_flags([uid], [b"\\Seen"])
			webmail._move_messages(client, [uid], target)
		# The message is back: what follows only tells its new id, and never makes the return a failure.
		validity, new_uid = 0, None
		try:
			validity, new_uid = _landed(client, target, 0 if half_done else before, row.message_id)
		except Exception as e:
			log_quietly("NeoMail: where a snoozed message came back to could not be read", e)
	_set(row.name, state=RETURNED, active_key=None, returned_at=_naive(_now()), last_error=None)
	new_id = email_id(target, validity, new_uid) if validity and new_uid else None
	mailcraft_changes.logged(
		account, created=[new_id] if new_id else [], destroyed=[email_id(folder, old_validity, uid)]
	)
	return {"state": CODES[RETURNED], "emailId": new_id, "mailboxId": mailbox_id(target)}


def _set(name, **values):
	frappe.db.set_value(DOCTYPE, name, values, update_modified=True)
	_commit()


def tick():
	"""Every minute: what is due, by mailbox, each to one job (one at a time per mailbox). One indexed read when nothing
	is due."""
	if not ready():
		return
	now = _naive(_now())
	due = frappe.db.sql(
		f"""select account from `tab{DOCTYPE}`
		where state=%s and until_utc<=%s and (next_try is null or next_try<=%s)
		group by account limit %s""",
		(WAITING, now, now, MAX_ACCOUNTS),
	)
	for (name,) in due:
		frappe.enqueue(
			JOB, queue="short", job_id=f"neomail_snooze_return:{name}", deduplicate=True, account=name
		)


def return_due(account):
	"""A mailbox's messages that are due come back, as the mailbox's owner (the job's)."""
	if not ready():
		return
	owner = frappe.db.get_value("Webmail Account", account, "user")
	if not owner:
		# The mailbox is gone: nothing can come back from it, and nothing is tried again.
		frappe.db.set_value(
			DOCTYPE, {"account": account, "state": WAITING}, {"state": CALLED_OFF, "active_key": None}
		)
		_commit()
		return
	try:
		with _locked(account, wait=0) as guard:
			rows = _due(account)
			if not rows:
				return
			frappe.set_user(owner)
			try:
				mailbox = webmail.get_account(account)
			except Exception as e:
				for row in rows:
					_failed_try(account, row, e)
				return
			started = time.monotonic()
			for row in rows:
				if time.monotonic() - started > JOB_BUDGET_S:
					# The next minute's job takes the rest.
					return
				guard()
				# Read again: the person may have brought it back, called it off or given it another time since.
				now = _naive(_now())
				state, until = frappe.db.get_value(DOCTYPE, row.name, ["state", "until_utc"]) or (None, None)
				if state != WAITING or not until or frappe.utils.get_datetime(until) > now:
					continue
				try:
					_bring_back(mailbox, row)
				except Exception as e:
					_failed_try(account, row, e)
	except _Busy:
		# The person acts on the mailbox just now, or another job runs: the next minute takes the rest.
		return


def _due(account):
	now = _naive(_now())
	return frappe.get_all(
		DOCTYPE,
		filters={"account": account, "state": WAITING, "until_utc": ("<=", now)},
		or_filters=[["next_try", "is", "not set"], ["next_try", "<=", now]],
		fields=[*FIELDS, "account"],
		order_by="until_utc asc",
		limit=MAX_ROWS,
	)


def _kind(e):
	if isinstance(e, webmail.WebmailAuthenticationError):
		return "sign-in"
	if isinstance(e, webmail.WebmailConnectionError) or webmail._imap_is_connection_error(e):
		return "connection"
	if isinstance(e, frappe.ValidationError):
		return "mailbox"
	return "server"


def _failed_try(account, row, e):
	"""One more try that failed: the next later on (RETRY_AFTER), or, after MAX_TRIES, the record is Failed (the message
	stays in the folder, where the person sees it) and the Error Log says so, once an hour for a mailbox."""
	tries = int(row.tries or 0) + 1
	kind = _kind(e)
	if tries < MAX_TRIES:
		later = _naive(_now() + RETRY_AFTER.get(tries, RETRY_AFTER[max(RETRY_AFTER)]))
		_set(row.name, tries=tries, last_error=kind, next_try=later)
		return
	_set(row.name, tries=tries, state=FAILED, active_key=None, last_error=kind, next_try=None)
	quiet = f"neomail_snooze_failed:{account}"
	if not frappe.cache().get_value(quiet):
		frappe.cache().set_value(quiet, 1, expires_in_sec=FAILED_QUIET_S)
		frappe.log_error(
			"NeoMail: a snoozed message could not come back",
			f"{account}: record {row.name}, {tries} tries, last: {kind} ({type(e).__name__})",
		)


METHODS = {
	"NeomailSnooze/get": snooze_get,
	"NeomailSnooze/set": snooze_set,
}


def on_user_trash(doc, method=None):
	"""A person deleted: what they put away in a mailbox of somebody else's goes on, the owner's from now on (it comes
	back all the same, and the owner sees it); the rest goes with them."""
	if not ready():
		return
	for name, account in frappe.get_all(
		DOCTYPE,
		filters={"user": doc.name, "state": ("in", (WAITING, FAILED))},
		fields=["name", "account"],
		as_list=True,
	):
		owner = frappe.db.get_value("Webmail Account", account, "user")
		if owner and owner != doc.name:
			row = frappe.db.get_value(DOCTYPE, name, ["message_id", "from_folder", "state"], as_dict=True)
			active = _key(owner, account, row.message_id, row.from_folder) if row.state == WAITING else None
			if active and frappe.db.exists(DOCTYPE, {"active_key": active}):
				active = None
			frappe.db.set_value(DOCTYPE, name, {"user": owner, "active_key": active})
	frappe.db.delete(DOCTYPE, {"user": doc.name})


def on_account_trash(doc, method=None):
	"""A mailbox deleted takes the records of its messages with it."""
	if ready():
		frappe.db.delete(DOCTYPE, {"account": doc.name})


def on_account_rename(doc, method=None, old=None, new=None, merge=False):
	"""A mailbox renamed keeps its records (they name it by its name), and the keys of those that wait."""
	if not (ready() and old and new and old != new):
		return
	for row in frappe.get_all(
		DOCTYPE, filters={"account": old}, fields=["name", "user", "message_id", "from_folder", "state"]
	):
		key = _key(row.user, new, row.message_id, row.from_folder) if row.state == WAITING else None
		frappe.db.set_value(DOCTYPE, row.name, {"account": new, "active_key": key})
