# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The new senders of a mailbox, for the phone's Mail tab (« Nouveaux expéditeurs », 16.11.2026): NeoMail's rule, which
NeoMail reckons in the window it has loaded, reckoned here on the server, where the phone can ask for it.

A new sender wrote to the mailbox's inbox in the last DAYS days and is none of these: in the person's Safe Senders or
Blocked Senders of the mailbox (an address, or a domain), a contact of the instance, someone the mailbox ever wrote to (its
Sent folder), someone who wrote before those days, someone one of whose mail was answered. « Accepter » puts the address
in the Safe Senders; « Bloquer » puts it in the Blocked Senders and moves its mail of the inbox to the Junk folder, as
NeoMail's `junk.blockSender` does. The two lists are the ones NeoMail keeps (mailcraft_settings, `NeoMail Setting`): what
is accepted or blocked on the phone is so in NeoMail, and the other way round.

Nothing is changed in a mailbox but by « Bloquer ». The answer is kept a few minutes per person and mailbox, and dropped
when they accept or block someone.
"""

import datetime

import frappe
from frappe import _
from frappe.utils import cint, getdate

from frappe_webmail import mailcraft_settings as settings
from frappe_webmail import webmail_api as webmail

DAYS = 14
MAX_DAYS = 60
LOOKED = 500  # the newest mail of the inbox looked at
SHOWN = 50  # new senders answered at most
CANDIDATES = 100  # senders checked against the Sent folder and the older mail at most
CACHE_S = 300
VERDICTS = ("accept", "block")


# ---------------------------------------------------------------------------------------------------------------
# The rule (pure)
# ---------------------------------------------------------------------------------------------------------------


def listed(address, entries):
	"""Whether `address` is in a Safe or Blocked list: the address itself, or its domain (« exemple.ch », « @exemple.ch »)."""
	address = (address or "").strip().lower()
	domain = address.rpartition("@")[2]
	for entry in entries or ():
		entry = (entry or "").strip().lower()
		if entry and (entry == address or entry.lstrip("@") == domain):
			return True
	return False


def newcomers(messages, lists, known):
	"""The new senders among `messages` (the inbox's, newest first: {address, name, subject, date, answered}): grouped by
	address in the order of their newest mail, each with how many and its newest subject and date; a sender in the lists,
	in `known` (contacts, written to, older mail) or with an answered mail is not new."""
	safe, blocked = lists
	order, by_address, answered = [], {}, set()
	for message in messages:
		address = (message.get("address") or "").strip().lower()
		if not address or "@" not in address:
			continue
		if message.get("answered"):
			answered.add(address)
		sender = by_address.get(address)
		if sender is None:
			sender = by_address[address] = {
				"address": address,
				"name": message.get("name") or "",
				"count": 0,
				"subject": message.get("subject") or "",
				"date": message.get("date"),
			}
			order.append(address)
		sender["count"] += 1
	return [
		by_address[a]
		for a in order
		if a not in answered and a not in known and not listed(a, safe) and not listed(a, blocked)
	]


def candidates(messages, lists):
	"""The addresses worth checking against the mailbox and the contacts: the inbox's senders not already ruled out by the
	lists or an answered mail, newest first, at most CANDIDATES."""
	return [s["address"] for s in newcomers(messages, lists, set())][:CANDIDATES]


# ---------------------------------------------------------------------------------------------------------------
# The seams: the mailbox, the contacts, the lists, the cache (replaced in the tests)
# ---------------------------------------------------------------------------------------------------------------


def _roles(client, account):
	return webmail.effective_folders(
		webmail.configured_folders(account), webmail.special_folders(client.list_folders())
	)


def _envelopes(client, uids):
	"""{uid: (address, name, subject, date, answered)} of these messages, nothing marked read."""
	out = {}
	if not uids:
		return out
	for uid, data in client.fetch(list(uids), ["ENVELOPE", "FLAGS"]).items():
		envelope = data.get(b"ENVELOPE")
		if envelope is None:
			continue
		sender = envelope.from_[0] if envelope.from_ else None
		address = ""
		if sender is not None and sender.mailbox and sender.host:
			address = (
				f"{sender.mailbox.decode(errors='replace')}@{sender.host.decode(errors='replace')}".lower()
			)
		flags = {f.decode() if isinstance(f, bytes) else str(f) for f in data.get(b"FLAGS") or ()}
		out[uid] = {
			"address": address,
			"name": webmail.decode_mime_header(sender.name) if sender is not None and sender.name else "",
			"subject": webmail.decode_mime_header(envelope.subject),
			"date": str(envelope.date) if envelope.date else None,
			"answered": "\\Answered" in flags,
		}
	return out


def _exactly(client, uids, address):
	"""Whether one of these messages is from or to `address` exactly (an IMAP search matches a part of an address)."""
	for _uid, data in client.fetch(list(uids)[:20], ["ENVELOPE"]).items():
		envelope = data.get(b"ENVELOPE")
		people = list((envelope.from_ or ()) + (envelope.to or ()) + (envelope.cc or ())) if envelope else []
		for person in people:
			if person.mailbox and person.host:
				if (
					f"{person.mailbox.decode(errors='replace')}@{person.host.decode(errors='replace')}".lower()
					== address
				):
					return True
	return False


def _scan(account, since, lists):
	"""(the inbox's messages since `since`, newest first; the addresses the mailbox already knows: written to, or that
	wrote before)."""
	with webmail.imap_session(account) as client:
		roles = _roles(client, account)
		client.select_folder(roles["inbox"], readonly=True)
		uids = sorted(client.search(["SINCE", since]), reverse=True)[:LOOKED]
		found = _envelopes(client, uids)
		messages = [found[u] for u in uids if u in found]
		known = set()
		looked = candidates(messages, lists)
		for address in looked:
			older = client.search(["BEFORE", since, "FROM", address])
			if older and _exactly(client, older, address):
				known.add(address)
		sent = roles.get("sent")
		if sent and looked:
			client.select_folder(sent, readonly=True)
			for address in looked:
				if address in known:
					continue
				written = client.search(["TO", address])
				if written and _exactly(client, written, address):
					known.add(address)
	return messages, known


def _contacts(addresses):
	"""The addresses that are a contact of the instance (read to leave them out, never shown)."""
	if not addresses:
		return set()
	rows = frappe.get_all("Contact Email", filters={"email_id": ["in", list(addresses)]}, pluck="email_id")
	return {(r or "").strip().lower() for r in rows}


def _lists(user, account_name):
	kept = settings._read(user, account_name)
	return list(kept.get("safe_senders") or []), list(kept.get("blocked_senders") or [])


def _keep_lists(user, account_name, safe, blocked):
	settings._write(user, account_name, {"safe_senders": safe, "blocked_senders": blocked})


def _block_move(account, address):
	"""The inbox's mail from `address` moved to the Junk folder: how many (none without a Junk folder)."""
	with webmail.imap_session(account) as client:
		roles = _roles(client, account)
		junk = roles.get("spam")
		if not junk:
			return 0
		client.select_folder(roles["inbox"])
		found = client.search(["FROM", address])
		mine = [uid for uid, e in _envelopes(client, found).items() if e["address"] == address]
		if mine:
			client.move(mine, junk)
		return len(mine)


def _cache():
	return frappe.cache()


def _cache_key(user, account_name):
	return f"neomail_new_senders:{user}:{account_name}"


# ---------------------------------------------------------------------------------------------------------------
# The methods
# ---------------------------------------------------------------------------------------------------------------


@frappe.whitelist()
def get_new_senders(
	account_name, days=DAYS
):  # permission-check: ok webmail.get_account refuses a portal account and a mailbox that is not the caller's
	"""The new senders of a mailbox: `{senders: [{address, name, count, subject, date}], count}`, newest first."""
	account = webmail.get_account(account_name)
	days = min(max(cint(days) or DAYS, 1), MAX_DAYS)
	user = frappe.session.user
	# Kept a few minutes for the window the phone asks for (DAYS); another window is reckoned each time
	key = _cache_key(user, account.name) if days == DAYS else None
	kept = _cache().get_value(key) if key else None
	if kept is not None:
		return kept
	lists = _lists(user, account.name)
	since = getdate() - datetime.timedelta(days=days)
	messages, known = _scan(account, since, lists)
	known |= _contacts(candidates(messages, lists))
	senders = newcomers(messages, lists, known)[:SHOWN]
	answer = {"senders": senders, "count": len(senders)}
	if key:
		_cache().set_value(key, answer, expires_in_sec=CACHE_S)
	return answer


@frappe.whitelist(methods=["POST"])
def set_new_sender(
	account_name, address, verdict
):  # permission-check: ok webmail.get_account refuses a portal account and a mailbox that is not the caller's
	"""« Accepter » (`accept`): the address joins the Safe Senders. « Bloquer » (`block`): it joins the Blocked Senders and
	its mail of the inbox goes to the Junk folder. `{verdict, moved}`."""
	if verdict not in VERDICTS:
		frappe.throw(_("Choose to accept or to block the sender."), frappe.ValidationError)
	address = (address or "").strip().lower()
	try:
		settings._senders([address], "sender")
	except ValueError:
		frappe.throw(_("This is not an email address."), frappe.ValidationError)
	if "@" not in address:
		frappe.throw(_("This is not an email address."), frappe.ValidationError)
	account = webmail.get_account(account_name)
	user = frappe.session.user
	safe, blocked = _lists(user, account.name)
	safe = [s for s in safe if s.strip().lower() != address]
	blocked = [s for s in blocked if s.strip().lower() != address]
	(safe if verdict == "accept" else blocked).append(address)
	if len(safe) > settings.MAX_SENDERS or len(blocked) > settings.MAX_SENDERS:
		frappe.throw(_("The list of senders is full."), frappe.ValidationError)
	_keep_lists(user, account.name, safe, blocked)
	moved = _block_move(account, address) if verdict == "block" else 0
	_cache().delete_value(_cache_key(user, account.name))
	return {"verdict": verdict, "moved": moved}
