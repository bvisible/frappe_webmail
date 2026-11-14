# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
What changed in a mailbox since a state NeoMail holds (RFC 8620 §5.2, §5.6; RFC 8621 §2.2, §4.3, §4.5): real states for
the facade's mail and folders (mailcraft_jmap), so that NeoMail, reopened on the copy it kept in the browser, asks what
changed and no more. Until then every state was "0", and NeoMail read the window of every folder again at each run.

**The journal**, one per mailbox (Webmail Account), kept in the cache for JOURNAL_SECONDS after its last use (lost with
it: a state of before is then answered `cannotCalculateChanges`, and NeoMail reads its windows again, as it used to):
- each folder as the last *sweep* saw it (`_views_key`): its UIDVALIDITY, UIDNEXT, number of messages and unseen ones, its
  HIGHESTMODSEQ where the server has CONDSTORE (RFC 7162), and the UIDs it shows (those not marked \\Deleted); without
  CONDSTORE, the flags of each of them, digested (the folder's fingerprint), and when they were read;
- the entries (`_log_key`): for each sweep or change that found something, its number and, by folder, the UIDs of the
  messages created, updated and destroyed, or a break (the folder's UIDVALIDITY changed: its UIDs now name other
  messages), the oldest ones let go past MAX_ENTRIES or MAX_LOG_CHARS (`floor`: a state older than that is not answered);
- the head (`_head_key`): the journal's epoch (drawn when it starts, or starts again), its last number, and for each folder
  the number of the last entry that put a message into it or took one out of it (`touched`: the state of its query).

A state is "<epoch>-<number>", a folder's queryState "<epoch>-<touched>": the same as long as nothing changed.

**A sweep** compares the server with the folders as last seen, under a lock of the mailbox, and logs what differs under
the next number (nothing, and the state stays, when nothing does). A folder whose STATUS says nothing moved (the same
UIDVALIDITY, UIDNEXT and number of messages, and the same HIGHESTMODSEQ) is not opened. With CONDSTORE, one that moved is
read for the messages changed since its HIGHESTMODSEQ (FETCH CHANGEDSINCE), and for its UIDs (UID SEARCH ALL) when its
count says some went. Without, the flags of all its messages are read again as soon as its STATUS moved (a new message,
one gone, one read or unread), and at most every FLAGS_RECHECK seconds otherwise: a flag set from another client, the
one change STATUS doesn't show, shows that much later. Email/changes sweeps every folder, Email/query and
Email/queryChanges their own; the first call that needs a state starts the journal with a sweep of every folder that
logs nothing.

**Why nothing is lost.** A state handed out is never newer than what goes with it: Email/get answers the head as it
stands, read before the messages are (what it reads is the server after it), and a change the journal hasn't seen yet is
logged by a later sweep, under a number above every state handed out before. NeoMail may hear of a change twice, never
miss one. Email/set and Email/import log what they did themselves (the ids they changed, under the next number: their
`newState`, `oldState` being the head just before) and never sweep after, which would log another's change in the same
breath as theirs, which NeoMail, taking the new state, would never read.

**Folders**: Mailbox/get of all of them keeps a journal of their own, per person (the rights differ from one to another):
Mailbox/changes says which were made, changed or let go, and `updatedProperties` when only their counts moved.

No push (eventSourceUrl): a stream held open would hold one of the instance's few web workers for as long as NeoMail
stays open; NeoMail asks Email/changes at each run instead.
"""

import contextlib
import json
import secrets
import time
import zlib

import frappe

from frappe_webmail import webmail_api as webmail
from frappe_webmail.mailcraft_jmap import (
	JmapError,
	_account,
	_arrival_order,
	_message_of,
	_select,
	_whole_number,
	account_id,
	email_id,
	log_quietly,
	query_shape,
)

JOURNAL_SECONDS = 30 * 24 * 3600
# The entries kept, and the length of what they name at most (packed UIDs): past either, the oldest go (`floor`).
MAX_ENTRIES = 1000
MAX_LOG_CHARS = 200_000
# The folders' journal of one person keeps fewer: a folder changes far less often than its mail.
MAX_BOX_ENTRIES = 300
# The most ids one Email/changes or Email/queryChanges answers, whatever its maxChanges: more, and NeoMail is told to
# read again (cannotCalculateChanges), which costs less than thousands of ids to fetch one by one.
MAX_CHANGES = 5000
# Without CONDSTORE, how long a folder whose STATUS didn't move is taken for unchanged before its flags are read again.
FLAGS_RECHECK = 120
# The lock of a mailbox's journal: how long it holds at most (a sweep of a large mailbox), how long a call waits for it.
LOCK_SECONDS = 300
LOCK_WAIT = 20
# The state of a mailbox whose journal can't be read or written: no change is ever calculated from it.
UNKNOWN = "-"
# What a Mailbox/changes reports in `updatedProperties` when only the counts of the folders moved.
COUNTS = ["totalEmails", "unreadEmails", "totalThreads", "unreadThreads"]


class _Busy(Exception):
	"""Another request holds the journal's lock for longer than a call waits."""


# ---------------------------------------------------------------------------------------------------------------
# Kept in the cache
# ---------------------------------------------------------------------------------------------------------------


def _head_key(name):
	return f"mailcraft_jmap_changes:{name}"


def _log_key(name):
	return f"mailcraft_jmap_changes_log:{name}"


def _views_key(name):
	return f"mailcraft_jmap_changes_folders:{name}"


def _boxes_key(name, user):
	return f"mailcraft_jmap_changes_boxes:{name}:{user}"


def _read(key):
	"""A value as Redis holds it now: `expires=True` keeps it out of the request's memory (frappe.local.cache), which would
	serve a value another worker has replaced since."""
	return frappe.cache().get_value(key, expires=True)


def _write(key, value):
	frappe.cache().set_value(key, value, expires_in_sec=JOURNAL_SECONDS)


def _all_views(name):
	"""Every folder's view, read from Redis (hgetall keeps nothing in the request's memory)."""
	return {
		(field.decode() if isinstance(field, bytes) else field): view
		for field, view in (frappe.cache().hgetall(_views_key(name)) or {}).items()
	}


def _one_view(name, folder):
	"""One folder's view, read from Redis: what hget kept in the request's memory is dropped first."""
	cache = frappe.cache()
	with contextlib.suppress(Exception):
		frappe.local.cache.pop(cache.make_key(_views_key(name)), None)
	return cache.hget(_views_key(name), folder)


def _keep_alive(name):
	"""The journal's entries and views live as long as its head: their expiry starts again with it."""
	cache = frappe.cache()
	for key in (_log_key(name), _views_key(name)):
		with contextlib.suppress(Exception):
			cache.expire(cache.make_key(key), JOURNAL_SECONDS)


@contextlib.contextmanager
def _locked(key):
	"""The lock of a journal, across the instance's workers; _Busy when another holds it past LOCK_WAIT."""
	cache = frappe.cache()
	lock = cache.lock(
		cache.make_key("mailcraft_jmap_changes_lock:" + key), timeout=LOCK_SECONDS, blocking_timeout=LOCK_WAIT
	)
	if not lock.acquire(blocking=True):
		raise _Busy
	try:
		yield
	finally:
		# Past LOCK_SECONDS the lock went by itself: nothing to give back.
		with contextlib.suppress(Exception):
			lock.release()


def _state(head, number=None):
	return f"{head['epoch']}-{head['number'] if number is None else number}"


def _parse(state):
	"""(epoch, number) of a state handed out here, (None, None) for anything else."""
	if not isinstance(state, str) or len(state) > 64:
		return None, None
	epoch, _sep, number = state.rpartition("-")
	if not epoch or not number.isdecimal() or len(number) > 15:
		return None, None
	return epoch, int(number)


def _usable(head, log):
	return (
		isinstance(head, dict)
		and isinstance(log, dict)
		and bool(head.get("epoch"))
		and head.get("epoch") == log.get("epoch")
		and log.get("floor", 0) <= head.get("number", -1)
	)


def pack(uids):
	"""UIDs as IMAP writes a set, sorted ("3,5:7"): what the journal keeps of a folder."""
	parts, start, last = [], None, None
	for uid in sorted(set(uids)):
		if start is not None and uid == last + 1:
			last = uid
			continue
		if start is not None:
			parts.append(f"{start}:{last}" if last > start else str(start))
		start = last = uid
	if start is not None:
		parts.append(f"{start}:{last}" if last > start else str(start))
	return ",".join(parts)


def unpack(text):
	"""The UIDs of a set packed by `pack`, one by one, in order."""
	for part in (text or "").split(","):
		if not part:
			continue
		low, _sep, high = part.partition(":")
		yield from range(int(low), int(high or low) + 1)


def _digest(flags):
	"""A message's flags as one number: the fingerprint of a folder without CONDSTORE. \\Recent is no flag of the message's
	(another session takes it)."""
	kept = sorted(
		{(f if isinstance(f, bytes) else str(f).encode()).lower() for f in flags or ()} - {b"\\recent"}
	)
	return zlib.crc32(b" ".join(kept))


def _deleted(got):
	return any(
		(f if isinstance(f, bytes) else str(f).encode()).lower() == b"\\deleted"
		for f in got.get(b"FLAGS") or ()
	)


# ---------------------------------------------------------------------------------------------------------------
# A sweep
# ---------------------------------------------------------------------------------------------------------------


def _has_condstore(client):
	try:
		capabilities = {c.upper() for c in client.capabilities() or ()}
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		return False
	return b"CONDSTORE" in capabilities or b"QRESYNC" in capabilities


def _listed(client):
	"""The folders that hold messages, as the server lists them."""
	names = []
	for flags, _delimiter, name in client.list_folders():
		marks = {(f if isinstance(f, bytes) else str(f).encode()).lower() for f in flags or ()}
		if b"\\noselect" in marks or b"\\nonexistent" in marks:
			continue
		names.append(name.decode() if isinstance(name, bytes) else name)
	return names


def _status(client, folder, condstore):
	"""What STATUS says of a folder (UIDVALIDITY `v`, UIDNEXT `n`, messages `c`, unseen `s`, HIGHESTMODSEQ `m`, None where
	the folder has none); None for a folder it can't be asked of."""
	items = [b"MESSAGES", b"UIDNEXT", b"UIDVALIDITY", b"UNSEEN"] + ([b"HIGHESTMODSEQ"] if condstore else [])
	try:
		got = client.folder_status(folder, items) or {}
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		return None
	return {
		"v": int(got.get(b"UIDVALIDITY") or 0),
		"n": int(got.get(b"UIDNEXT") or 0),
		"c": int(got.get(b"MESSAGES") or 0),
		"s": int(got.get(b"UNSEEN") or 0),
		"m": int(got.get(b"HIGHESTMODSEQ") or 0) or None,
	}


def _look(client, folder, old, status, now):
	"""What became of `folder` since the journal's view of it (`old`; None for one it doesn't know): (its view now, the
	change), the change None when nothing did, or {"x": True} when its UIDVALIDITY changed."""
	if old and (old["v"], old["n"], old["c"]) == (status["v"], status["n"], status["c"]):
		if status["m"] and status["m"] == old.get("m"):
			return old, None
		recent = now - old.get("at", 0) < FLAGS_RECHECK
		if not status["m"] and "f" in old and old.get("s") == status["s"] and recent:
			return old, None
	validity = _select(client, folder)
	if not validity:
		return old, None
	status = {**status, "v": validity}
	broken = bool(old) and old["v"] != validity
	base = None if broken else old
	if status["m"] and base and base.get("m"):
		# CONDSTORE: the messages changed since the view's HIGHESTMODSEQ, and the UIDs gone when the count says so.
		shown = set(unpack(base["u"]))
		changed = (
			client.fetch("1:*", ["FLAGS"], modifiers=[f"CHANGEDSINCE {base['m']}"]) if status["c"] else {}
		)
		arrived = sum(1 for uid in changed if uid >= base["n"])
		destroyed = set()
		if base["c"] + arrived != status["c"]:
			destroyed = shown - set(client.search(["ALL"])) if status["c"] else set(shown)
		created, updated = set(), set()
		for uid, got in changed.items():
			if _deleted(got):
				if uid in shown:
					destroyed.add(uid)
			elif uid in shown:
				updated.add(uid)
			else:
				created.add(uid)
		updated -= destroyed
		view = {**status, "u": pack((shown - destroyed) | created)}
	elif status["m"] and not base:
		# CONDSTORE, a folder seen for the first time: its UIDs are all it takes.
		created = set(client.search(["NOT", "DELETED"])) if status["c"] else set()
		updated, destroyed = set(), set()
		view = {**status, "u": pack(created)}
	else:
		# Without CONDSTORE (or when it came or went): the flags of every message, compared one by one.
		fetched = client.fetch("1:*", ["FLAGS"]) if status["c"] else {}
		digests = {uid: _digest(got.get(b"FLAGS")) for uid, got in fetched.items() if not _deleted(got)}
		if not base:
			created, updated, destroyed = set(digests), set(), set()
		elif "f" in base:
			before = base["f"]
			created, destroyed = set(digests) - set(before), set(before) - set(digests)
			updated = {uid for uid, digest in digests.items() if uid in before and before[uid] != digest}
		else:
			shown = set(unpack(base["u"]))
			created, destroyed, updated = set(digests) - shown, shown - set(digests), set(digests) & shown
		view = {**status, "u": pack(digests)}
		if not status["m"]:
			view.update(f=digests, at=now)
	if broken:
		return view, {"f": folder, "v": validity, "x": True}
	if not (created or updated or destroyed):
		return view, None
	return view, {
		"f": folder,
		"v": validity,
		"c": pack(created),
		"u": pack(updated),
		"d": pack(destroyed),
	}


def _start(name, client):
	"""A new journal: every folder as the server shows it now, under a new epoch, nothing logged. The head after."""
	condstore, now = _has_condstore(client), time.time()
	views = {}
	for folder in _listed(client):
		status = _status(client, folder, condstore)
		if status is None:
			continue
		view, _change = _look(client, folder, None, status, now)
		if view:
			views[folder] = view
	epoch = secrets.token_hex(4)
	head = {"epoch": epoch, "number": 0, "touched": dict.fromkeys(views, 0)}
	cache = frappe.cache()
	_write(_log_key(name), {"epoch": epoch, "floor": 0, "entries": []})
	cache.delete_value(_views_key(name))
	for folder, view in views.items():
		cache.hset(_views_key(name), folder, view)
	_keep_alive(name)
	# The head last: a journal is usable only once all of it is there (_usable).
	_write(_head_key(name), head)
	return head


def _append(name, head, log, changes):
	"""Log `changes` under the next number; the head after. The entries first and the head after them: a reader never
	sees a number whose entry isn't there yet."""
	number = head["number"] + 1
	size = sum(len(c.get(k) or "") for c in changes for k in ("c", "u", "d")) + 40 * len(changes)
	entries = [*log["entries"], {"n": number, "changes": changes, "size": size}]
	floor = log.get("floor", 0)
	while len(entries) > MAX_ENTRIES or (
		len(entries) > 1 and sum(e.get("size", 0) for e in entries) > MAX_LOG_CHARS
	):
		floor = entries.pop(0)["n"]
	# Only a folder the journal knows (it has its view): one it doesn't is new to the next sweep, which logs its messages.
	touched = dict(head.get("touched") or {})
	for change in changes:
		if change["f"] in touched and (change.get("x") or change.get("c") or change.get("d")):
			touched[change["f"]] = number
	_write(_log_key(name), {"epoch": head["epoch"], "floor": floor, "entries": entries})
	head = {**head, "number": number, "touched": touched}
	_write(_head_key(name), head)
	return head


def _commit(name, head, log, changes, views, gone):
	"""Log what a sweep found, then keep the folders' views (in that order: a view kept before its change is logged would
	lose the change, should the rest fail). The head after."""
	touched = dict(head.get("touched") or {})
	for folder in views:
		touched.setdefault(folder, head["number"])
	head = {**head, "touched": touched}
	if changes:
		head = _append(name, head, log, changes)
	# A folder let go is known no more (after _append, which marks it touched by its messages' going).
	head = {**head, "touched": {f: n for f, n in head["touched"].items() if f not in gone}}
	_write(_head_key(name), head)
	cache = frappe.cache()
	for folder, view in views.items():
		cache.hset(_views_key(name), folder, view)
	for folder in gone:
		cache.hdel(_views_key(name), folder)
	_keep_alive(name)
	return head


def _sweep(account, client, only=None):
	"""Compare the server's folders (all, or the one `only` names) with the journal and log what differs; start the
	journal when it is missing or broken. The head after, or as it stands when another request holds the lock (what it
	sweeps is logged all the same), None when there is none."""
	name = account.name
	try:
		with _locked(name):
			head, log = _read(_head_key(name)), _read(_log_key(name))
			if not _usable(head, log):
				return _start(name, client)
			known = head.get("touched") or {}
			condstore, now = _has_condstore(client), time.time()
			if only is None:
				views = _all_views(name)
				if any(folder not in views for folder in known):
					# A view the cache let go: what changed in that folder can't be told any more.
					return _start(name, client)
				listed = _listed(client)
			else:
				old = _one_view(name, only)
				if old is None and only in known:
					return _start(name, client)
				views, listed = ({only: old} if old else {}), [only]
			changes, kept = [], {}
			for folder in listed:
				status = _status(client, folder, condstore)
				if status is None:
					continue
				old = views.get(folder)
				view, change = _look(client, folder, old, status, now)
				if view is not None and view is not old:
					kept[folder] = view
				if change:
					changes.append(change)
			gone = []
			if only is None:
				for folder in set(views) - set(listed):
					gone.append(folder)
					if views[folder].get("u"):
						changes.append({"f": folder, "v": views[folder]["v"], "d": views[folder]["u"]})
			return _commit(name, head, log, changes, kept, gone)
	except _Busy:
		head, log = _read(_head_key(name)), _read(_log_key(name))
		return head if _usable(head, log) else None


def _shielded(what, run, fallback):
	"""Run a part of the journal; a failure of its own (not the mail server's) is logged and answered by `fallback`,
	never by the call that needed a state: reading mail doesn't depend on it."""
	try:
		return run()
	except (webmail.WebmailConnectionError, webmail.WebmailAuthenticationError):
		raise
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		log_quietly(f"MailCraft JMAP: {what}", e)
		return fallback


# ---------------------------------------------------------------------------------------------------------------
# The states the facade's calls answer
# ---------------------------------------------------------------------------------------------------------------


def email_state(account):
	"""The Email state of a mailbox as it stands, for Email/get, read before the messages are; the journal is started
	(a sweep of every folder, once) when there is none."""

	def run():
		head = _read(_head_key(account.name))
		if isinstance(head, dict) and head.get("epoch"):
			return _state(head)
		with webmail.imap_session(account) as client:
			head = _sweep(account, client)
		return _state(head) if head else UNKNOWN

	return _shielded("the state of a mailbox could not be read", run, UNKNOWN)


def query_state(account, client, folder):
	"""The queryState of a folder's Email/query, after a sweep of that folder (in the query's own IMAP session): the same
	until a message comes into it or leaves it."""

	def run():
		head = _sweep(account, client, only=folder)
		if not head:
			return UNKNOWN
		return f"{head['epoch']}-{(head.get('touched') or {}).get(folder, head['number'])}"

	return _shielded("the state of a folder could not be read", run, UNKNOWN)


def logged(account, created=(), updated=(), destroyed=()):
	"""What a call changed itself (Email/set, Email/import), logged under the next number: (oldState, newState) of its
	answer, `oldState` being the head just before. Nothing changed: the state as it stands, twice. When the journal is
	missing or busy, the state as it stands: the next sweep logs these changes (NeoMail may read them once more)."""

	def run():
		by_folder = {}
		for kind, ids in (("c", created), ("u", updated), ("d", destroyed)):
			for jid in ids or ():
				place = _message_of(jid)
				if place:
					folder, validity, uid = place
					by_folder.setdefault((folder, validity), {"c": [], "u": [], "d": []})[kind].append(uid)
		name = account.name
		try:
			with _locked(name):
				head, log = _read(_head_key(name)), _read(_log_key(name))
				if not _usable(head, log):
					return UNKNOWN, UNKNOWN
				before = _state(head)
				if not by_folder:
					return before, before
				changes = [
					{"f": folder, "v": validity, **{kind: pack(uids) for kind, uids in kinds.items()}}
					for (folder, validity), kinds in by_folder.items()
				]
				return before, _state(_append(name, head, log, changes))
		except _Busy:
			head = _read(_head_key(name))
			now = _state(head) if isinstance(head, dict) and head.get("epoch") else UNKNOWN
			return now, now

	return _shielded("a change could not be logged", run, (UNKNOWN, UNKNOWN))


# ---------------------------------------------------------------------------------------------------------------
# Email/changes, Email/queryChanges
# ---------------------------------------------------------------------------------------------------------------


class _Merged:
	"""What became of each id over entries since the old state: created (not there before, there now), updated (there
	before and now), destroyed (there before, not now), or nothing to say (made and let go since). `count` is how many
	ids an answer would hold."""

	def __init__(self):
		self.ids, self.count = {}, 0

	def note(self, jid, kind):
		before = self.ids.get(jid)
		after = (before[0] if before else kind != "c", kind != "d")
		self.ids[jid] = after
		self.count += any(after) - (any(before) if before else 0)
		return jid, before

	def undo(self, marks):
		for jid, before in reversed(marks):
			self.count += (any(before) if before else 0) - any(self.ids[jid])
			if before is None:
				del self.ids[jid]
			else:
				self.ids[jid] = before

	def lists(self):
		out = {"created": [], "updated": [], "destroyed": []}
		for jid, (was, now) in self.ids.items():
			if now:
				out["updated" if was else "created"].append(jid)
			elif was:
				out["destroyed"].append(jid)
		return out


def _cannot(why):
	return JmapError("cannotCalculateChanges", why)


def _since(args, key):
	since = args.get(key)
	if not isinstance(since, str):
		raise JmapError("invalidArguments", key)
	return since


def _max_changes(args):
	"""A /changes call's maxChanges (RFC 8620 §5.2: a positive number when given), never past MAX_CHANGES."""
	given = _whole_number(args.get("maxChanges"), "maxChanges")
	if given is not None and given < 1:
		raise JmapError("invalidArguments", "maxChanges")
	return min(given or MAX_CHANGES, MAX_CHANGES)


def _page(entries, merged, ids_of, limit, since):
	"""Take entries in order while the answer holds `limit` ids at most: (the number of the last one taken, whether some
	were left). A first entry alone over the limit can't be answered in parts."""
	taken = since
	for entry in entries:
		marks = []
		for jid, kind in ids_of(entry):
			marks.append(merged.note(jid, kind))
			if merged.count > limit:
				merged.undo(marks)
				if taken == since:
					raise _cannot("Too many changes: read the mailbox again.")
				return taken, True
		taken = entry["n"]
	return taken, False


def _email_ids(entry):
	for change in entry["changes"]:
		if change.get("x"):
			raise _cannot("A folder was made again: read the mailbox again.")
		for kind in ("c", "u", "d"):
			for uid in unpack(change.get(kind)):
				yield email_id(change["f"], change["v"], uid), kind


def email_changes(args):
	"""Email/changes (RFC 8620 §5.2): the emails created, updated and destroyed since `sinceState`, after a sweep of every
	folder. `cannotCalculateChanges` for a state of another epoch, older than the journal keeps, or across a folder made
	again: NeoMail then reads its windows again."""
	account = _account(args.get("accountId"))
	since = _since(args, "sinceState")
	limit = _max_changes(args)
	epoch, number = _parse(since)
	with webmail.imap_session(account) as client:
		head = _sweep(account, client)
	log = _read(_log_key(account.name))
	if not _usable(head, log) or epoch != head["epoch"]:
		raise _cannot("This state is not known here: read the mailbox again.")
	if number is None or number > head["number"] or number < log.get("floor", 0):
		raise _cannot("This state is too old: read the mailbox again.")
	entries = [e for e in log["entries"] if number < e["n"] <= head["number"]]
	merged = _Merged()
	taken, more = _page(entries, merged, _email_ids, limit, number)
	return {
		"accountId": account_id(account.name),
		"oldState": since,
		"newState": _state(head, taken if more else head["number"]),
		"hasMoreChanges": more,
		**merged.lists(),
	}


def email_query_changes(args):
	"""Email/queryChanges (RFC 8620 §5.6) of a folder's query: the emails that left it (`removed`) and those that came
	(`added`, each with its index in the whole list now, and in `removed` as well, so that one listed already is never
	listed twice). `upToId` is not used: the whole list is read. Within `maxChanges`, else tooManyChanges."""
	account = _account(args.get("accountId"))
	folder, ascending = query_shape(args)
	since = _since(args, "sinceQueryState")
	given = _whole_number(args.get("maxChanges"), "maxChanges")
	if given is not None and given < 1:
		raise JmapError("invalidArguments", "maxChanges")
	epoch, number = _parse(since)
	with webmail.imap_session(account) as client:
		head = _sweep(account, client, only=folder)
		validity = _select(client, folder)
		uids = _arrival_order(client) if validity else []
	log = _read(_log_key(account.name))
	touched = (head or {}).get("touched", {}).get(folder)
	if not _usable(head, log) or epoch != head["epoch"] or touched is None:
		raise _cannot("This state is not known here: run the query again.")
	if number is None or number > touched:
		raise _cannot("This state is not known here: run the query again.")
	removed, added = [], []
	if number < touched:
		if number < log.get("floor", 0):
			raise _cannot("This state is too old: run the query again.")
		came, went = {}, set()
		for entry in log["entries"]:
			if not number < entry["n"] <= head["number"]:
				continue
			for change in entry["changes"]:
				if change["f"] != folder:
					continue
				if change.get("x"):
					raise _cannot("The folder was made again: run the query again.")
				for kind in ("c", "d"):
					for uid in unpack(change.get(kind)):
						jid = email_id(folder, change["v"], uid)
						went.add(jid)
						if kind == "c" and change["v"] == validity:
							came[jid] = uid
						elif kind == "d":
							came.pop(jid, None)
		if not ascending:
			uids = list(reversed(uids))
		index = {uid: i for i, uid in enumerate(uids)}
		removed = sorted(went)
		added = sorted(
			({"id": jid, "index": index[uid]} for jid, uid in came.items() if uid in index),
			key=lambda a: a["index"],
		)
		if len(removed) + len(added) > MAX_CHANGES:
			raise _cannot("Too many changes: run the query again.")
		if given is not None and len(removed) + len(added) > given:
			raise JmapError("tooManyChanges", str(given))
	out = {
		"accountId": account_id(account.name),
		"oldQueryState": since,
		"newQueryState": f"{head['epoch']}-{touched}",
		"removed": removed,
		"added": added,
	}
	if args.get("calculateTotal"):
		out["total"] = len(uids)
	return out


# ---------------------------------------------------------------------------------------------------------------
# Mailbox/get's state, Mailbox/changes, Mailbox/set's states
# ---------------------------------------------------------------------------------------------------------------


def _props(entry):
	"""A folder's properties but its counts, as one number."""
	kept = {k: v for k, v in entry.items() if k not in COUNTS}
	return zlib.crc32(json.dumps(kept, sort_keys=True, default=str).encode())


def _boxes_usable(kept):
	return isinstance(kept, dict) and bool(kept.get("epoch")) and isinstance(kept.get("log"), list)


def mailbox_state(account, listed=None):
	"""The Mailbox state of the person's view of a mailbox. `listed`, the whole list Mailbox/get just read: compared with
	the last one and logged (a folder made, changed or let go), the state after; None: the state as it stands (a Mailbox/get
	of a few, read before them)."""
	key = _boxes_key(account.name, frappe.session.user)

	def run():
		if listed is None:
			kept = _read(key)
			return _state(kept) if _boxes_usable(kept) else UNKNOWN
		view = {e["id"]: (_props(e), e.get("totalEmails"), e.get("unreadEmails")) for e in listed}
		try:
			with _locked(key):
				kept = _read(key)
				if not _boxes_usable(kept):
					kept = {"epoch": secrets.token_hex(4), "number": 0, "floor": 0, "view": view, "log": []}
				else:
					old = kept.get("view") or {}
					created = [m for m in view if m not in old]
					destroyed = [m for m in old if m not in view]
					updated = [m for m in view if m in old and view[m] != old[m]]
					if created or updated or destroyed:
						props = any(view[m][0] != old[m][0] for m in updated)
						kept = _boxes_append(kept, created, updated, destroyed, props)
					kept["view"] = view
				_write(key, kept)
				return _state(kept)
		except _Busy:
			kept = _read(key)
			return _state(kept) if _boxes_usable(kept) else UNKNOWN

	return _shielded("the state of the folders could not be read", run, UNKNOWN)


def _boxes_append(kept, created, updated, destroyed, props):
	number = kept["number"] + 1
	log = [*kept["log"], {"n": number, "c": created, "u": updated, "d": destroyed, "p": props}]
	floor = kept.get("floor", 0)
	while len(log) > MAX_BOX_ENTRIES:
		floor = log.pop(0)["n"]
	return {**kept, "number": number, "floor": floor, "log": log}


def boxes_logged(account, created=(), updated=(), destroyed=()):
	"""What Mailbox/set changed itself, logged under the next number: (oldState, newState). The folders' view is left as
	it was: the next Mailbox/get logs these changes again (NeoMail may read them once more), and the folders moved with a
	renamed one there for the first time."""
	key = _boxes_key(account.name, frappe.session.user)

	def run():
		try:
			with _locked(key):
				kept = _read(key)
				if not _boxes_usable(kept):
					return UNKNOWN, UNKNOWN
				before = _state(kept)
				if not (created or updated or destroyed):
					return before, before
				kept = _boxes_append(kept, list(created), list(updated), list(destroyed), True)
				_write(key, kept)
				return before, _state(kept)
		except _Busy:
			kept = _read(key)
			now = _state(kept) if _boxes_usable(kept) else UNKNOWN
			return now, now

	return _shielded("a change of the folders could not be logged", run, (UNKNOWN, UNKNOWN))


def _box_ids(entry):
	for kind in ("c", "u", "d"):
		for mid in entry.get(kind) or ():
			yield mid, kind


def mailbox_changes(args):
	"""Mailbox/changes (RFC 8621 §2.2): the folders made, changed and let go since `sinceState`, after reading them all
	(as Mailbox/get does); `updatedProperties` names the counts when nothing else of them changed."""
	from frappe_webmail.mailcraft_jmap import mailbox_entries

	account = _account(args.get("accountId"))
	since = _since(args, "sinceState")
	limit = _max_changes(args)
	epoch, number = _parse(since)
	mailbox_state(account, mailbox_entries(account, None))
	kept = _read(_boxes_key(account.name, frappe.session.user))
	if not _boxes_usable(kept) or epoch != kept["epoch"]:
		raise _cannot("This state is not known here: read the folders again.")
	if number is None or number > kept["number"] or number < kept.get("floor", 0):
		raise _cannot("This state is too old: read the folders again.")
	entries = [e for e in kept["log"] if e["n"] > number]
	merged = _Merged()
	taken, more = _page(entries, merged, _box_ids, limit, number)
	lists = merged.lists()
	only_counts = not any(e.get("p") for e in entries if e["n"] <= taken)
	return {
		"accountId": account_id(account.name),
		"oldState": since,
		"newState": _state(kept, taken if more else kept["number"]),
		"hasMoreChanges": more,
		**lists,
		"updatedProperties": COUNTS if lists["updated"] and only_counts else None,
	}


METHODS = {
	"Email/changes": email_changes,
	"Email/queryChanges": email_query_changes,
	"Mailbox/changes": mailbox_changes,
}
