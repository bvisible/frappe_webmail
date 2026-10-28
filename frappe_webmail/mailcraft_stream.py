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
"""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, wait

import frappe

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import stream

STREAM = "https://neoffice.me/jmap/neomail-stream"
MAX_IDS = 200  # a window of the list (the client asks for 200 emails at once)
BUDGET_S = 4.0  # what the model has, for one ask
WORKERS = 4
CACHE_S = 30 * 24 * 3600  # settled by the headers or the model: a message does not change
DEFAULT_CACHE_S = 3600  # settled by nothing: another look later, the model may have been away
SOURCES = ("headers", "model", "default")


def enabled():
	"""Whether this site offers the tabs: `nora_decide_mail` = on in its site configuration."""
	return str(frappe.conf.get("nora_decide_mail") or "").strip().lower() == "on"


def session_parts(account):
	"""What every mailbox's session adds: the capability, where the site offers it."""
	if not enabled():
		return {}, {}
	return {STREAM: {}}, {STREAM: {"maxIds": MAX_IDS}}


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
			results[uid] = {"stream": first["stream"], "source": "headers"}
		else:
			unsettled.append(uid)
	if not unsettled:
		return results, []
	if ask is None:
		for uid in unsettled:
			results[uid] = {"stream": "person", "source": "default"}
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
			results[uid] = {"stream": decided["stream"], "source": decided["source"]}
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
	for folder, wanted in folders.items():
		by_validity = {}
		for jid, validity, uid in wanted:
			hit = cache.get_value(_key(account.name, folder, validity, uid))
			if hit:
				listed.append({"id": jid, **hit})
			else:
				by_validity.setdefault(validity, []).append((jid, uid))
		for validity, misses in by_validity.items():
			uids = [uid for _jid, uid in misses]
			messages, gone = _read(account, folder, validity, uids)
			if gone:
				not_found += [jid for jid, _uid in misses]
				continue
			_count("asked", len(messages))
			results, waiting = classify(
				messages, lambda wanted_uids: _previews(account, folder, validity, wanted_uids), ask, deadline
			)
			for jid, uid in misses:
				if uid in results:
					entry = results[uid]
					cache.set_value(
						_key(account.name, folder, validity, uid),
						entry,
						expires_in_sec=CACHE_S if entry["source"] != "default" else DEFAULT_CACHE_S,
					)
					listed.append({"id": jid, **entry})
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


def _finish_later(account_name, folder, validity, uids):
	"""The answers the model did not give in time, finished by a background job that puts them in the cache."""
	digest = hashlib.sha256(
		f"{account_name}\x00{folder}\x00{validity}\x00{sorted(uids)}".encode()
	).hexdigest()[:24]
	try:
		frappe.enqueue(
			"frappe_webmail.mailcraft_stream.finish",
			queue="short",
			timeout=120,
			job_id=f"neomail_stream:{digest}",
			deduplicate=True,
			account_name=account_name,
			folder=folder,
			validity=validity,
			uids=list(uids),
		)
	except Exception:
		frappe.log_error("NeoMail stream: the job could not be queued", frappe.get_traceback())


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


METHODS = {"NeomailStream/get": stream_get}
