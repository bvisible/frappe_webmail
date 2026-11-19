# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The stream of the messages of a mailbox, for NeoMail's tabs: Principal, Notifications, Newsletters (28.10.2026).

JMAP has no standard for it: a method of our own, `NeomailStream/get`, under the capability STREAM, on the pattern of
`mailcraft_settings` (NeomailSettings). NeoMail's hosting page asks, for the messages its list shows, which kind of sender wrote
each; this answers `{id, stream, source}` for each, where `stream` is `person`, `notification` or `newsletter` and `source` says how
it was settled (`headers`, `model`, `default`).

The work is stream.py's: the headers first, the box's small model for what they do not settle, a person for what nothing settles.
This module is the part that reads the mailbox and keeps the answer:

- **Nothing is written to the mailbox.** The messages are read (envelope, a few header fields, the first words of the body of the
  ones the headers do not settle), never changed; the answer is recomputed or read from the cache.
- **The cache holds the kind and how it was settled, never a word of a message**, under a hash of the mailbox, the folder, its
  UIDVALIDITY and the uid: a message does not change, and a folder that was recreated has another validity.
- **A reply is never kept waiting.** The model has FOUR SECONDS for a window of messages; what it has not answered by then comes back
  in `pending`, and is finished by a background job, so that the next ask (a few seconds later) finds it in the cache.
- **Only where the site asks for it**: `nora_decide_mail` = `on` (the box's decisions, nora.api.decide). Elsewhere the capability is
  not offered, and the method answers `unknownMethod`.

A person may correct a tab (19.11.2026, neoffice-maintenance#3142): `NeomailStream/set {accountId, corrections: [{id, stream,
sender?}]}`, offered where the site also says `nora_decide_mail_feedback` = 1 (the capability then says `correct: true`). The
message moves at once (`source: person`), for this person and this mailbox; with `sender: true` (the person said yes to « the
next ones from this sender too », as Gmail asks), so do this sender's other messages and the next ones. Both are kept in their
NeoMail Setting of the mailbox (`sender_streams`: a hash of the sender's address, or `m:` and a hash of the message's place, and
the tab; never an address), the message's own choice before the sender's, and win over the headers and the model, on this window
and on the phone's Mail tab. Then, in a background job, the sender, the subject and the first words (what the model reads) go to
the box as a person's correction (nora.api.decide.feedback): one vote in its memory of senders, and what vega's Learner learns
from; a message already put under that tab is not told again.
"""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, wait

import frappe
from frappe import _
from frappe.utils import cint

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import stream

STREAM = "https://neoffice.me/jmap/neomail-stream"
MAX_IDS = 200  # a window of the list (the client asks for 200 emails at once)
BUDGET_S = 4.0  # what the model has, for one ask
WORKERS = 4
CACHE_S = 30 * 24 * 3600  # settled by the headers or the model: a message does not change
DEFAULT_CACHE_S = 3600  # settled by nothing: another look later, the model may have been away
SOURCES = ("headers", "model", "default", "person")
STREAMS = ("person", "notification", "newsletter")
# A person's corrections: the site's key, the record field, how many choices (messages and senders) a mailbox keeps (the newest)
CORRECT_KEY = "nora_decide_mail_feedback"
PREFS_DOCTYPE = "NeoMail Setting"
PREFS_FIELD = "sender_streams"
MAX_PREFS = 1_000
# Background jobs one person may have queued or running at once for one mailbox (_finish_later). Each different set of
# messages left pending made a job of its own, so that one person asking with other sets kept the short queue busy for
# everyone; past these, what is pending waits for the next ask, which tries again (it is asked within seconds).
JOBS_PER_MAILBOX = 2


def enabled():
	"""Whether this site offers the tabs: `nora_decide_mail` = on in its site configuration."""
	return str(frappe.conf.get("nora_decide_mail") or "").strip().lower() == "on"


def corrections_enabled():
	"""Whether a person may correct a tab here: the tabs, and `nora_decide_mail_feedback` = 1, and the record field migrated."""
	return (
		enabled()
		and cint(frappe.conf.get(CORRECT_KEY))
		and frappe.db.table_exists(PREFS_DOCTYPE)
		and frappe.db.has_column(PREFS_DOCTYPE, PREFS_FIELD)
	)


def session_parts(account):
	"""What every mailbox's session adds: the capability, where the site offers it."""
	if not enabled():
		return {}, {}
	takes = {"maxIds": MAX_IDS}
	if corrections_enabled():
		takes["correct"] = True
	return {STREAM: {}}, {STREAM: takes}


def sender_hash(address):
	"""What stands for a sender in the cache and in a person's choices: a hash of the address, never the address."""
	return hashlib.sha256(str(address or "").strip().lower().encode()).hexdigest()[:20]


def message_key(folder, validity, uid):
	"""What stands for a message in a person's choices (beside the senders' hashes): its place in the mailbox, hashed."""
	text = f"{folder}\x00{int(validity)}\x00{int(uid)}"
	return "m:" + hashlib.sha256(text.encode()).hexdigest()[:20]


def _prefs(user, account_name):
	"""{sender hash or message key: stream} of this person in this mailbox, {} without any or where the key is off."""
	if not corrections_enabled():
		return {}
	value = frappe.db.get_value(PREFS_DOCTYPE, {"user": user, "account": account_name}, PREFS_FIELD)
	try:
		prefs = json.loads(value) if isinstance(value, str) and value else (value or {})
	except ValueError:
		return {}
	return (
		{k: v for k, v in prefs.items() if isinstance(k, str) and v in STREAMS}
		if isinstance(prefs, dict)
		else {}
	)


def _chosen(prefs, message, sender):
	"""The person's choice for this message, else for its sender, else none."""
	return prefs.get(message) or prefs.get(sender or "")


def _apply(entry, prefs, message=""):
	"""The entry as the person sees it: their choice for this message, else for this sender, wins."""
	chosen = _chosen(prefs, message, entry.get("from"))
	return {**entry, "stream": chosen, "source": "person"} if chosen else entry


# ---------------------------------------------------------------------------------------------------------------
# The seams: what reads the mailbox, the cache, the model (replaced in the tests)
# ---------------------------------------------------------------------------------------------------------------


def _cache():
	return frappe.cache()


def _key(account_name, folder, validity, uid):
	text = f"{account_name}\x00{folder}\x00{int(validity)}\x00{int(uid)}"
	return "neomail_stream:" + hashlib.sha256(text.encode()).hexdigest()[:40]


def _model():
	"""`ask(text)` of the box's decisions, or None where nora is not installed or has no way to reach the box. Called in the
	request's own thread (it reads the site's configuration); the function it gives is pure and runs in worker threads."""
	try:
		from nora.api import decide
	except Exception:
		return None
	url, key = decide._endpoint()
	if not url:
		return None

	def ask(text):
		answer = decide._post(url, key, "mail_stream", text, BUDGET_S)
		return None if answer.get("_error") else answer

	return ask


def _count(outcome, amount=1):
	"""The numbers of the try-out page (nora.api.decide.counters), where nora is there."""
	try:
		from nora.api import decide

		decide.count("mail", outcome, amount)
	except Exception:
		pass


def _read(account, folder, validity, uids):
	"""({uid: {name, address, subject, headers}}, gone) of the messages of `folder`: the envelope and the header fields the
	headers stage reads, nothing marked read. `gone` says the folder is not the one the ids name any more (recreated, or
	deleted): its ids are not found."""
	webmail = jmap.webmail
	messages = {}
	with webmail.imap_session(account) as client:
		if jmap._select(client, folder) != validity:
			return {}, True
		data = client.fetch(list(uids), ["ENVELOPE"])
		headers = stream.fetch_headers(client, uids)
		for uid in uids:
			envelope = (data.get(uid) or {}).get(b"ENVELOPE")
			if envelope is None:
				continue
			sender = envelope.from_[0] if envelope.from_ else None
			messages[uid] = {
				"name": webmail.decode_mime_header(sender.name) if sender and sender.name else "",
				"address": webmail.format_address(sender) if sender else "",
				"subject": webmail.decode_mime_header(envelope.subject),
				"headers": headers.get(uid, {}),
			}
	return messages, False


def _previews(account, folder, validity, uids):
	"""{uid: the first words of the body} for these messages: asked only for the ones the headers do not settle."""
	webmail = jmap.webmail
	with webmail.imap_session(account) as client:
		if jmap._select(client, folder) != validity:
			return {}
		data = client.fetch(list(uids), ["BODYSTRUCTURE"])
		return webmail._list_previews(client, data)


# ---------------------------------------------------------------------------------------------------------------
# The two stages over a window of messages
# ---------------------------------------------------------------------------------------------------------------


def classify(messages, previews_of, ask, deadline):
	"""({uid: {stream, source}}, [uid pending]): the headers' answer for every message that has one, then the model's for the
	rest within `deadline` (time.monotonic()). `previews_of(uids)` gives the first words of the ones that need the model;
	`ask(text)` is the box's answer or None (no model: those messages are a person's by default, never pending)."""
	results, unsettled = {}, []
	for uid, message in messages.items():
		first = stream.of_headers(message.get("headers") or {}, message.get("address", ""))
		if first["stream"]:
			results[uid] = {
				"stream": first["stream"],
				"source": "headers",
				"from": sender_hash(message.get("address")),
			}
		else:
			unsettled.append(uid)
	if not unsettled:
		return results, []
	if ask is None:
		for uid in unsettled:
			results[uid] = {
				"stream": "person",
				"source": "default",
				"from": sender_hash(messages[uid].get("address")),
			}
		_count("unavailable", len(unsettled))
		return results, []
	previews = previews_of(unsettled)
	pool = ThreadPoolExecutor(max_workers=WORKERS)
	futures = {
		pool.submit(stream.decide, {**messages[uid], "preview": previews.get(uid, "")}, ask): uid
		for uid in unsettled
	}
	finished, _waiting = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
	pool.shutdown(
		wait=False, cancel_futures=True
	)  # what has not started never will; what runs ends by itself
	pending = []
	for future, uid in futures.items():
		if future in finished and not future.exception():
			decided = future.result()
			results[uid] = {
				"stream": decided["stream"],
				"source": decided["source"],
				"from": sender_hash(messages[uid].get("address")),
			}
		else:
			pending.append(uid)
	return results, pending


# ---------------------------------------------------------------------------------------------------------------
# The method
# ---------------------------------------------------------------------------------------------------------------


def stream_get(args):
	"""`NeomailStream/get {accountId, ids}` → `{list: [{id, stream, source}], notFound, pending}`; `pending` are the ids the model
	has not answered within the budget: ask them again in a few seconds."""
	if not enabled():
		raise jmap.JmapError("unknownMethod", "NeomailStream/get")
	account = jmap._account(args.get("accountId"))
	ids = args.get("ids")
	if (
		not isinstance(ids, list)
		or not ids
		or len(ids) > MAX_IDS
		or not all(isinstance(i, str) and len(i) <= 255 for i in ids)
	):
		raise jmap.JmapError("invalidArguments", "ids")
	folders, not_found = jmap._by_folder(ids)
	cache, listed, pending = _cache(), [], []
	deadline = time.monotonic() + BUDGET_S
	ask = _model()
	prefs = _prefs(_who(), account.name)
	for folder, wanted in folders.items():
		by_validity = {}
		for jid, validity, uid in wanted:
			hit = cache.get_value(_key(account.name, folder, validity, uid))
			# A person's choice is never the mailbox's (#3151): an entry of that source, written before, is read again.
			if hit and hit.get("source") != "person":
				listed.append({"id": jid, **_said(_apply(hit, prefs, message_key(folder, validity, uid)))})
			else:
				by_validity.setdefault(validity, []).append((jid, uid))
		for validity, misses in by_validity.items():
			uids = [uid for _jid, uid in misses]
			messages, gone = _read(account, folder, validity, uids)
			if gone:
				not_found += [jid for jid, _uid in misses]
				continue
			# A message or a sender this person chose a tab for is answered by their choice, without the model: nothing is
			# cached of it, since the cache is the mailbox's and the choice is theirs alone (#3151).
			chosen = {}
			for _jid, uid in misses:
				message = messages.get(uid)
				sender = sender_hash(message.get("address")) if message is not None else ""
				tab = (
					_chosen(prefs, message_key(folder, validity, uid), sender)
					if message is not None
					else None
				)
				if tab:
					chosen[uid] = {"stream": tab, "source": "person", "from": sender}
			messages = {uid: m for uid, m in messages.items() if uid not in chosen}
			_count("asked", len(messages))
			results, waiting = classify(
				messages, lambda wanted_uids: _previews(account, folder, validity, wanted_uids), ask, deadline
			)
			for jid, uid in misses:
				if uid in chosen:
					listed.append({"id": jid, **_said(chosen[uid])})
				elif uid in results:
					entry = results[uid]
					cache.set_value(
						_key(account.name, folder, validity, uid),
						entry,
						expires_in_sec=CACHE_S if entry["source"] != "default" else DEFAULT_CACHE_S,
					)
					listed.append(
						{"id": jid, **_said(_apply(entry, prefs, message_key(folder, validity, uid)))}
					)
				elif uid in waiting:
					pending.append(jid)
				else:
					not_found.append(jid)  # the message is gone from the folder
			if waiting:
				_finish_later(account.name, folder, validity, waiting)
	return {
		"accountId": args.get("accountId"),
		"state": "0",
		"list": listed,
		"notFound": not_found,
		"pending": pending,
	}


def _said(entry):
	"""What NeoMail is told of an entry: the stream and how it was settled, not the sender's hash."""
	return {"stream": entry["stream"], "source": entry["source"]}


def _finish_later(account_name, folder, validity, uids):
	"""The answers the model did not give in time, finished by a background job that puts them in the cache: in one of
	the person's JOBS_PER_MAILBOX places for this mailbox, the first one free; none when all are taken (the ids stay
	pending, and the next ask tries again)."""
	try:
		place = hashlib.sha256(f"{_who()}\x00{account_name}".encode()).hexdigest()[:24]
		for slot in range(JOBS_PER_MAILBOX):
			job_id = f"neomail_stream:{place}:{slot}"
			if _job_busy(job_id):
				continue
			frappe.enqueue(
				"frappe_webmail.mailcraft_stream.finish",
				queue="short",
				timeout=120,
				job_id=job_id,
				deduplicate=True,
				account_name=account_name,
				folder=folder,
				validity=validity,
				uids=list(uids),
			)
			return
	except Exception:
		frappe.log_error("NeoMail stream: the job could not be queued", frappe.get_traceback())


def _who():
	"""The person asking (replaced in the tests)."""
	return frappe.session.user


def _job_busy(job_id):
	"""Whether a job of this id is queued or running (replaced in the tests)."""
	from frappe.utils.background_jobs import is_job_enqueued

	return is_job_enqueued(job_id)


def finish(account_name, folder, validity, uids):
	"""The background job: the same two stages with a longer budget, the answers put in the cache."""
	account = jmap.webmail.get_account(account_name)
	messages, gone = _read(account, folder, validity, uids)
	if gone:
		return
	results, _waiting = classify(
		messages, lambda wanted: _previews(account, folder, validity, wanted), _model(), time.monotonic() + 60
	)
	cache = _cache()
	for uid, entry in results.items():
		cache.set_value(
			_key(account.name, folder, validity, uid),
			entry,
			expires_in_sec=CACHE_S if entry["source"] != "default" else DEFAULT_CACHE_S,
		)


# ---------------------------------------------------------------------------------------------------------------
# The phone's Mail tab: the same answer, named by the folder and the UIDs its list holds
# ---------------------------------------------------------------------------------------------------------------


def _validity(account, folder):
	"""The UIDVALIDITY of `folder`, or None when it cannot be opened (replaced in the tests)."""
	with jmap.webmail.imap_session(account) as client:
		return jmap._select(client, folder)


def _uids_of(uids):
	"""The UIDs a call names: a JSON list, or numbers separated by commas; at most MAX_IDS."""
	if isinstance(uids, str):
		text = uids.strip()
		uids = frappe.parse_json(text) if text.startswith("[") else [u for u in text.split(",") if u.strip()]
	try:
		wanted = [int(u) for u in uids or []]
	except (TypeError, ValueError):
		frappe.throw(_("The messages asked for are not valid."), frappe.ValidationError)
	if len(wanted) > MAX_IDS or any(u <= 0 for u in wanted):
		frappe.throw(
			_("At most {0} messages can be asked for at once.").format(MAX_IDS), frappe.ValidationError
		)
	return list(dict.fromkeys(wanted))


@frappe.whitelist()
def get_streams(account_name, folder="INBOX", uids=None):  # permission-check: ok jmap.webmail.get_account refuses a portal account and a mailbox that is not the caller's
	"""The kind of sender of these messages of a folder, for the groups of the phone's Mail tab (Notifications and
	Newsletters at the foot of each day, as NeoMail has them): `{enabled, streams: {uid: stream}, pending: [uid]}`.

	The same work as NeomailStream/get (the cache, the headers, the model, the job that finishes what is pending), named by
	the folder and the UIDs the phone's list holds instead of NeoMail's ids: the phone does not know the UIDVALIDITY of each
	mailbox of « Toutes les boîtes ». `pending` are the messages the model has not answered yet: ask them again in a few
	seconds. Where the site does not offer the tabs, `enabled` is false and nothing is read."""
	if not enabled():
		return {"enabled": False, "streams": {}, "pending": []}
	wanted = _uids_of(uids)
	account = jmap.webmail.get_account(account_name)
	validity = _validity(account, folder) if wanted else None
	if not validity:
		return {"enabled": True, "streams": {}, "pending": []}
	ids = {jmap.email_id(folder, validity, uid): uid for uid in wanted}
	answer = stream_get({"accountId": "A" + jmap._b64(account.name), "ids": list(ids)})
	return {
		"enabled": True,
		"streams": {str(ids[e["id"]]): e["stream"] for e in answer["list"] if e["id"] in ids},
		"pending": [ids[jid] for jid in answer["pending"] if jid in ids],
	}


# ---------------------------------------------------------------------------------------------------------------
# A person's corrections
# ---------------------------------------------------------------------------------------------------------------


def stream_set(args):
	"""`NeomailStream/set {accountId, corrections: [{id, stream, sender?}]}` → `{accountId, updated, notUpdated}`: the person
	put these messages under these tabs, for them and this mailbox; with `sender: true`, their senders' others and next ones too.
	The box is told of each message the first time it is put under a tab."""
	if not corrections_enabled():
		raise jmap.JmapError("unknownMethod", "NeomailStream/set")
	account = jmap._account(args.get("accountId"))
	corrections = args.get("corrections")
	if (
		not isinstance(corrections, list)
		or not corrections
		or len(corrections) > MAX_IDS
		or not all(
			isinstance(c, dict)
			and isinstance(c.get("id"), str)
			and len(c["id"]) <= 255
			and c.get("stream") in STREAMS
			and isinstance(c.get("sender", False), bool)
			for c in corrections
		)
	):
		raise jmap.JmapError("invalidArguments", "corrections")
	wanted = {c["id"]: (c["stream"], c.get("sender", False)) for c in corrections}
	folders, not_found = jmap._by_folder(list(wanted))
	before = _prefs(_who(), account.name)
	updated, chosen = [], {}
	for folder, ids in folders.items():
		by_validity = {}
		for jid, validity, uid in ids:
			by_validity.setdefault(validity, []).append((jid, uid))
		for validity, items in by_validity.items():
			messages, gone = _read(account, folder, validity, [uid for _jid, uid in items])
			taught = []
			for jid, uid in items:
				message = messages.get(uid)
				if gone or message is None:
					not_found.append(jid)
					continue
				# The choice is kept for this person alone (`_keep_choices`), and `stream_get` applies it: never in the cache,
				# which is the mailbox's and is read by everyone the mailbox is shared with (#3151).
				(tab, whole_sender), key = wanted[jid], message_key(folder, validity, uid)
				if before.get(key) != tab:
					taught.append(
						(uid, tab)
					)  # not twice for the same message under the same tab (the « yes » after it)
				chosen[key] = tab
				if whole_sender:
					chosen[sender_hash(message.get("address"))] = tab
				updated.append(jid)
			if taught:
				_teach_later(account.name, folder, validity, taught)
	if chosen:
		_keep_choices(_who(), account.name, chosen)
	_count("corrected", len(updated))
	return {
		"accountId": args.get("accountId"),
		"updated": updated,
		"notUpdated": {jid: {"type": "notFound", "description": "no such message"} for jid in not_found},
	}


def _keep_choices(user, account_name, chosen):
	"""The person's choice for these messages and senders in this mailbox: the newest win, MAX_PREFS kept."""
	from frappe_webmail import mailcraft_settings

	prefs = _prefs(user, account_name)
	for sender, tab in chosen.items():
		prefs.pop(sender, None)
		prefs[sender] = tab
	prefs = dict(list(prefs.items())[-MAX_PREFS:])
	mailcraft_settings._write(user, account_name, {PREFS_FIELD: prefs})


def _teach_later(account_name, folder, validity, taught):
	"""The box hears of the corrections in a background job: reading the messages again takes the mail server's time."""
	try:
		frappe.enqueue(
			"frappe_webmail.mailcraft_stream.teach",
			queue="short",
			timeout=120,
			account_name=account_name,
			folder=folder,
			validity=validity,
			taught=[[int(uid), tab] for uid, tab in taught],
		)
	except Exception:
		frappe.log_error("NeoMail stream: a correction could not be queued", frappe.get_traceback())


def teach(account_name, folder, validity, taught):
	"""The background job: what the model reads of each corrected message, to the box with the person's tab."""
	try:
		from nora.api import decide
	except Exception:
		return
	account = jmap.webmail.get_account(account_name)
	uids = [uid for uid, _tab in taught]
	messages, gone = _read(account, folder, validity, uids)
	if gone:
		return
	previews = _previews(account, folder, validity, uids)
	for uid, tab in taught:
		message = messages.get(uid)
		if not message:
			continue
		text = stream.model_text(
			message.get("name"), message.get("address"), message.get("subject"), previews.get(uid, "")
		)
		decide.feedback("mail_stream", text, tab)


METHODS = {"NeomailStream/get": stream_get, "NeomailStream/set": stream_set}
