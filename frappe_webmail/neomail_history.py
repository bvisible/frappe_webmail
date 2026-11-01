# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What was said with someone, for NeoMail's « Échanges » pane (1.11.2026; Obsidian note 52 of Neoffice-Apps).

NeoMail keeps in memory the newest messages of each folder (500 at most), so it can list by itself the exchanges that are
in them; this is the rest, asked of the Neoffice server, in the web page and in Neodesk alike (both read the mailbox's JMAP
session): three methods of our own under a capability of their own, on the pattern of `mailcraft_stream`.

- `NeomailContact/get {accountId, address}`: who the address is in Neoffice (the contact the person may read, the customer
  or supplier it is linked to with the invoices of the year, a lead), and **all the addresses of that someone** (the
  contact's own, and those of the other contacts of the same customer or supplier), so that the pane lists the exchanges
  with the whole company and not with one address;
- `NeomailHistory/get {accountId, addresses, limit, before, direction, text, includeCc, domains, mailboxIds}`: the
  messages sent to or by those addresses, **in every folder but Trash, Junk and Drafts** (or the folders named), the newest
  first, a page at a time (`next` is the date to ask `before`), each with the attachments' names;
- `NeomailLinked/get {accountId, address}`: what Neoffice links that someone's customer, supplier or lead to (quotes,
  orders, invoices, tickets, tasks…), the few that wait on someone first: the rows of « Tout voir » (neoffice_theme
  `bar.everything`), read with the reader's rights, and the way to its page.

Nothing is written, nothing is marked read (BODY.PEEK only). The mailboxes are the person's own, and those shared with them
(`mailcraft_jmap._account`); the contacts, the customers and their documents are read with the person's rights, so a person
who may not read a customer gets the messages and no card. Nothing in a message is read but its envelope and its structure:
the subjects and the names are a stranger's words, shown as text.
"""

import hashlib
import re
import time
from datetime import timedelta

import frappe

from frappe_webmail import webmail_api as webmail
from frappe_webmail.mailcraft_jmap import (
	JmapError,
	_account,
	_select,
	email_id,
	mailbox_id,
	moment_of,
	utc_date,
)

HISTORY = "https://neoffice.me/jmap/neomail-history"
# What one ask holds: the addresses of someone, the rows of a page, the folders looked through, the time it may take.
MAX_ADDRESSES = 8
MAX_LIMIT = 50
DEFAULT_LIMIT = 20
MAX_FOLDERS = 40
BUDGET_S = 20.0
MAX_TEXT = 100
MAX_ATTACHMENTS = 6
LINKED_ROWS = 6
CACHE_S = 60
# The folders that are not someone's exchanges: what was thrown away, what is junk, what is not sent yet.
SKIPPED_ROLES = ("trash", "spam", "drafts")
# A domain that stands for a whole company only when it is the company's: these are everybody's mailboxes, never searched
# as « the whole domain ».
PUBLIC_DOMAINS = frozenset(
	"""gmail.com googlemail.com outlook.com hotmail.com hotmail.fr hotmail.ch live.com live.fr msn.com yahoo.com yahoo.fr
	icloud.com me.com mac.com aol.com gmx.ch gmx.net gmx.com gmx.de bluewin.ch sunrise.ch hispeed.ch swissonline.ch
	proton.me protonmail.com pm.me tutanota.com infomaniak.ch bluemail.ch ik.me yopmail.com web.de t-online.de orange.fr
	free.fr wanadoo.fr laposte.net""".split()
)
_ADDRESS = re.compile(r"^[^\s@<>\"',;]+@[^\s@<>\"',;]+\.[^\s@<>\"',;]+$")
_DOMAIN = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")
# The parts of a message that are bodies and containers, never an attachment (mime_parts.NOT_ATTACHMENTS).
_NOT_ATTACHMENTS = frozenset(("text/plain", "text/html", "multipart/alternative", "multipart/mixed"))


def session_parts(account):
	"""What every mailbox's session adds: the capability. Offered to the desk's people only (a portal account has no
	mailbox here, but no Contact to read either)."""
	return {HISTORY: {}}, {HISTORY: {"maxAddresses": MAX_ADDRESSES, "maxLimit": MAX_LIMIT}}


# ---------------------------------------------------------------------------------------------------------------
# The arguments
# ---------------------------------------------------------------------------------------------------------------


def _address(value):
	"""The address a text is, lower case; None for what is none."""
	text = str(value or "").strip().lower()
	found = re.search(r"<([^<>]+)>", text)
	text = (found.group(1) if found else text).strip()
	return text if len(text) <= 254 and _ADDRESS.match(text) else None


def _addresses(value):
	if not isinstance(value, list) or not value or len(value) > MAX_ADDRESSES:
		raise JmapError("invalidArguments", "addresses")
	found = [_address(each) for each in value]
	if not all(found):
		raise JmapError("invalidArguments", "addresses")
	return list(dict.fromkeys(found))


def _domains(addresses):
	"""The company domains of these addresses: not a public provider's."""
	domains = {a.rpartition("@")[2] for a in addresses}
	return sorted(d for d in domains if _DOMAIN.match(d) and d not in PUBLIC_DOMAINS)


def _number(value, name, default, low, high):
	if value is None:
		return default
	if isinstance(value, bool) or not isinstance(value, int):
		raise JmapError("invalidArguments", name)
	return max(low, min(value, high))


def _flag(value, name):
	if value is None:
		return False
	if not isinstance(value, bool):
		raise JmapError("invalidArguments", name)
	return value


# ---------------------------------------------------------------------------------------------------------------
# Who someone is
# ---------------------------------------------------------------------------------------------------------------


def _party_of(address):
	"""({contact, card}, the lead or None): the contact the person may read with this address, the customer or supplier it
	is linked to (webmail.get_sender_card), and a lead with it, as the person's rights allow."""
	contact = webmail.get_contact_by_email(address)
	card = webmail.get_sender_card(address) if contact else None
	lead = None
	if frappe.db.exists("DocType", "Lead") and frappe.has_permission("Lead", "read"):
		found = frappe.get_list(
			"Lead",
			filters={"email_id": address},
			fields=["name", "lead_name", "company_name", "status"],
			limit_page_length=1,
		)
		lead = found[0] if found else None
	return {"contact": contact, "card": card}, lead


def party_addresses(doctype, name):
	"""The addresses of the contacts linked to a customer or a supplier the person may read (the lead's own too)."""
	rows = frappe.get_list(
		"Contact",
		filters=[["Dynamic Link", "link_doctype", "=", doctype], ["Dynamic Link", "link_name", "=", name]],
		fields=["name"],
		limit_page_length=20,
	)
	found = []
	for row in rows:
		for each in frappe.get_all(
			"Contact Email", filters={"parent": row["name"], "parenttype": "Contact"}, pluck="email_id"
		):
			found.append(_address(each))
	if doctype == "Lead":
		found.append(_address(frappe.db.get_value("Lead", name, "email_id")))
	return [a for a in dict.fromkeys(found) if a]


def contact_get(args):
	"""`NeomailContact/get {accountId, address}` → who the address is, and every address of that someone (the first is the
	one asked)."""
	_account(args.get("accountId"))
	address = _address(args.get("address"))
	if not address:
		raise JmapError("invalidArguments", "address")
	found, lead = _party_of(address)
	contact, card = found["contact"], found["card"]
	addresses = [address]
	if contact:
		addresses += [_address(each) for each in contact.get("emails") or []]
	if card:
		addresses += party_addresses(card["doctype"], card["name"])
	elif lead:
		addresses += party_addresses("Lead", lead["name"])
	answer = {
		"accountId": args.get("accountId"),
		"state": "0",
		"address": address,
		"known": bool(contact or lead),
		"addresses": [a for a in dict.fromkeys(addresses) if a][:MAX_ADDRESSES],
		"domains": _domains([address]),
		"contact": None,
		"party": None,
		"lead": None,
	}
	if contact:
		answer["contact"] = {
			"name": contact.get("name"),
			"fullName": contact.get("full_name"),
			"company": contact.get("company_name"),
			"phone": contact.get("phone") or contact.get("mobile_no"),
		}
	if card:
		answer["party"] = {
			"doctype": card["doctype"],
			"name": card["name"],
			"title": card["title"],
			"kind": card["kind"],
			"url": card["url"],
			"invoices": card["invoices"],
			"everything": _everything_url(card["doctype"], card["name"]),
		}
	if lead:
		answer["lead"] = {
			"name": lead["name"],
			"title": lead.get("lead_name") or lead["name"],
			"company": lead.get("company_name"),
			"status": lead.get("status"),
			"everything": _everything_url("Lead", lead["name"]),
		}
	return answer


def _everything_url(doctype, name):
	"""The desk's page « Tout voir » of a thing."""
	from urllib.parse import quote

	return frappe.utils.get_url(f"/app/history/{quote(doctype, safe='')}/{quote(name, safe='')}")


# ---------------------------------------------------------------------------------------------------------------
# What Neoffice links someone to
# ---------------------------------------------------------------------------------------------------------------


def _everything():
	"""neoffice_theme's `bar.everything` (« Tout voir »), or None on a site without it."""
	try:
		return frappe.get_attr("neoffice_theme.bar.everything.gathered")
	except Exception:
		return None


def linked_get(args):
	"""`NeomailLinked/get {accountId, address}` → `{thing, total, rows}`: the customer, the supplier or the lead of that address
	and the few documents linked to it that wait on someone, then the newest (the mails are not here: they are the pane's
	first tab). Read with the person's rights, as « Tout voir » does."""
	_account(args.get("accountId"))
	address = _address(args.get("address"))
	if not address:
		raise JmapError("invalidArguments", "address")
	answer = {
		"accountId": args.get("accountId"),
		"state": "0",
		"address": address,
		"thing": None,
		"total": 0,
		"rows": [],
	}
	gathered = _everything()
	if gathered is None:
		return answer
	found, lead = _party_of(address)
	card = found["card"]
	thing = (card["doctype"], card["name"]) if card else (("Lead", lead["name"]) if lead else None)
	if not thing:
		return answer
	try:
		items = gathered(*thing)["items"]
	except Exception:
		frappe.log_error("NeoMail: what Neoffice links someone to could not be read", frappe.get_traceback())
		return answer
	kept = [each for each in items if each.get("cat") != "mail" and each.get("docstatus") != 2]
	waiting = {"danger": 0, "warn": 1}
	kept.sort(key=lambda each: waiting.get(each.get("tone"), 2))
	answer["thing"] = {"doctype": thing[0], "name": thing[1], "everything": _everything_url(*thing)}
	answer["total"] = len(kept)
	answer["rows"] = [
		{
			"kind": each.get("kind"),
			"doctype": each["doctype"],
			"name": each["name"],
			"number": each.get("number") or "",
			"title": each.get("title") or "",
			"ref": each.get("ref") or "",
			"date": each.get("date"),
			"amount": each.get("amount"),
			"currency": each.get("currency"),
			"status": each.get("status") or "",
			"tone": each.get("tone"),
			"url": each.get("url") or frappe.utils.get_url_to_form(each["doctype"], each["name"]),
		}
		for each in kept[:LINKED_ROWS]
	]
	return answer


# ---------------------------------------------------------------------------------------------------------------
# The messages
# ---------------------------------------------------------------------------------------------------------------


def _criteria(addresses, direction, include_cc, domains, text, before):
	"""IMAP SEARCH criteria, flat on purpose (webmail._search_charset): one of the addresses (or domains) in the From, and/or
	the To (and the Cc); then the words; then the day before which. Messages deleted but not yet expunged are left out."""
	atoms = []
	for who in [*addresses, *("@" + d for d in domains)]:
		if direction in ("all", "in"):
			atoms.append(["FROM", who])
		if direction in ("all", "out"):
			atoms.append(["TO", who])
			if include_cc:
				atoms.append(["CC", who])
	criteria = ["OR"] * (len(atoms) - 1)
	for atom in atoms:
		criteria += atom
	criteria += ["NOT", "DELETED"]
	if text:
		criteria += webmail._text_criteria(text)
	if before is not None:
		# BEFORE reads a day, not a moment: the day after the cursor, so that the day's earlier messages are in; the moment is
		# compared once the dates are read.
		criteria += ["BEFORE", (before + timedelta(days=1)).strftime("%d-%b-%Y")]
	return criteria


def _ordered(client, criteria):
	"""The matching UIDs, the newest received first: by the server's SORT where it has one, else by reading their dates."""
	try:
		if b"SORT" in (client.capabilities() or ()):
			return list(client.sort(["REVERSE", "ARRIVAL"], criteria))
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
	uids = client.search(criteria, charset=webmail._search_charset(criteria))
	dates = client.fetch(uids, ["INTERNALDATE"]) if uids else {}
	return sorted(
		uids, key=lambda uid: (utc_date((dates.get(uid) or {}).get(b"INTERNALDATE")) or "", uid), reverse=True
	)


def _person(address):
	if not address:
		return {"name": "", "email": ""}
	name = webmail.decode_mime_header(address.name) if address.name else ""
	return {"name": name, "email": webmail.format_address(address).lower()}


def _text(value):
	if isinstance(value, bytes):
		return value.decode("utf-8", "replace")
	return str(value or "")


def _params(value):
	"""{name: value} of a BODYSTRUCTURE parameter list (a flat tuple of names and values), names in lower case."""
	if not isinstance(value, tuple | list):
		return {}
	items = list(value)
	return {_text(items[i]).lower(): _text(items[i + 1]) for i in range(0, len(items) - 1, 2)}


def attachments_of(structure):
	"""[{id, name, type, size}] of a message's attachments, by its BODYSTRUCTURE, by the one rule mime_parts has (an explicit
	attachment, or a part with a file name that is not a body), with its ids: the part's Content-ID, else its rank."""
	found = []

	def walk(part):
		if not isinstance(part, tuple | list) or not part:
			return
		if isinstance(part[0], tuple | list):
			for each in part:
				if isinstance(each, tuple | list):
					walk(each)
			return
		if len(part) < 7:
			return
		kind = f"{_text(part[0]).lower()}/{_text(part[1]).lower()}"
		params = _params(part[2])
		disposition, filename = "", ""
		for each in part[7:]:
			if (
				isinstance(each, tuple | list)
				and each
				and isinstance(each[0], bytes | str)
				and len(each) >= 2
			):
				label = _text(each[0]).lower()
				if label in ("attachment", "inline"):
					disposition = label
					filename = _params(each[1]).get("filename", "")
		filename = filename or params.get("name", "")
		if disposition == "attachment" or (filename and kind not in _NOT_ATTACHMENTS):
			content_id = _text(part[3]).strip("<>") if len(part) > 3 and part[3] else ""
			size = part[6] if isinstance(part[6], int) else 0
			found.append(
				{
					"id": content_id or str(len(found)),
					"name": webmail.decode_mime_header(filename) if filename else "",
					"type": kind,
					"size": size,
				}
			)

	walk(structure)
	return found[:MAX_ATTACHMENTS]


def _folders(client, account, wanted):
	"""[(folder, role)] to look through: the folders named (those that exist), else all that can be selected but Trash, Junk
	and Drafts; the Inbox and Sent first. `role` is the webmail's name of a special folder, or None."""
	listing = client.list_folders()
	roles = webmail.effective_folders(webmail.configured_folders(account), webmail.special_folders(listing))
	role_of = {folder: role for role, folder in roles.items() if folder}
	selectable = [name for flags, _delimiter, name in listing if b"\\Noselect" not in flags]
	if wanted is not None:
		chosen = [name for name in selectable if mailbox_id(name) in wanted]
	else:
		chosen = [name for name in selectable if role_of.get(name) not in SKIPPED_ROLES]
	first = [name for name in chosen if role_of.get(name) in ("inbox", "sent")]
	chosen = first + [name for name in chosen if name not in first]
	return [(name, role_of.get(name)) for name in chosen[:MAX_FOLDERS]]


def _direction(sender, role, own, mine):
	"""`out` for what the person sent: it is in Sent, or comes from their own address (and not from the someone asked
	about); the rest came in."""
	if sender in own:
		return "in"
	return "out" if role == "sent" or sender == mine else "in"


def _wanted_folders(args):
	value = args.get("mailboxIds")
	if value is None:
		return None
	if not isinstance(value, list) or len(value) > MAX_FOLDERS or not all(isinstance(i, str) for i in value):
		raise JmapError("invalidArguments", "mailboxIds")
	return set(value)


def _key(account, args_digest):
	return f"neomail_history:{frappe.session.user}:{account.name}:{args_digest}"


def history_get(args):
	"""`NeomailHistory/get` → `{list, total, next, scanned, partial}`: the messages with these addresses, the newest first.
	`next` is the moment to ask `before` for the next page (None at the end); `total` is how many there are, on the first page
	only; `scanned` is `{folders, of}`, and `partial` says the time ran out before every folder was looked through."""
	account = _account(args.get("accountId"))
	addresses = _addresses(args.get("addresses"))
	limit = _number(args.get("limit"), "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
	direction = args.get("direction") or "all"
	if direction not in ("all", "in", "out"):
		raise JmapError("invalidArguments", "direction")
	include_cc = _flag(args.get("includeCc"), "includeCc")
	use_domains = _flag(args.get("domains"), "domains")
	text = str(args.get("text") or "").strip()[:MAX_TEXT]
	before = args.get("before")
	moment = moment_of(before) if before is not None else None
	if before is not None and moment is None:
		raise JmapError("invalidArguments", "before")
	wanted = _wanted_folders(args)
	domains = _domains(addresses) if use_domains else []
	digest = hashlib.sha256(
		repr((addresses, limit, direction, include_cc, domains, text, before, sorted(wanted or []))).encode()
	).hexdigest()[:32]
	cache = frappe.cache()
	hit = cache.get_value(_key(account, digest))
	if hit is not None:
		return {"accountId": args.get("accountId"), "state": "0", **hit}

	criteria = _criteria(addresses, direction, include_cc, domains, text, moment)
	deadline = time.monotonic() + BUDGET_S
	rows, total, more, looked, partial = [], 0, False, 0, False
	own, mine = set(addresses), (account.email or "").strip().lower()
	with webmail.imap_session(account) as client:
		folders = _folders(client, account, wanted)
		for folder, role in folders:
			if time.monotonic() > deadline:
				partial = True
				break
			try:
				validity = _select(client, folder)
				if not validity:
					continue
				uids = _ordered(client, criteria)
				looked += 1
				total += len(uids)
				if len(uids) > limit:
					more = True
				page = uids[: limit + 1]
				data = (
					client.fetch(page, ["ENVELOPE", "FLAGS", "BODYSTRUCTURE", "INTERNALDATE"]) if page else {}
				)
			except Exception as e:
				if webmail._imap_is_connection_error(e):
					raise
				frappe.log_error("NeoMail history: a folder could not be searched", frappe.get_traceback())
				continue
			for uid in page:
				entry = data.get(uid)
				envelope = (entry or {}).get(b"ENVELOPE")
				if envelope is None:
					continue
				received = utc_date(entry.get(b"INTERNALDATE"))
				if moment is not None and received and received >= moment.strftime("%Y-%m-%dT%H:%M:%SZ"):
					continue
				sender = _person(envelope.from_[0] if envelope.from_ else None)
				flags = entry.get(b"FLAGS") or ()
				structure = entry.get(b"BODYSTRUCTURE")
				files = attachments_of(structure)
				rows.append(
					{
						"id": email_id(folder, validity, uid),
						"mailboxId": mailbox_id(folder),
						"folder": folder.rpartition("/")[2] or folder,
						"role": role,
						"subject": webmail.decode_mime_header(envelope.subject),
						"from": sender,
						"to": [_person(a) for a in (envelope.to or [])[:3]],
						"receivedAt": received,
						"unread": b"\\Seen" not in flags,
						"hasAttachment": bool(files),
						"attachments": files,
						"direction": _direction(sender["email"], role, own, mine),
					}
				)
	rows.sort(key=lambda row: (row["receivedAt"] or "", row["id"]), reverse=True)
	rest = rows[limit:]
	rows = rows[:limit]
	answer = {
		"list": rows,
		"total": total if moment is None else None,
		"next": rows[-1]["receivedAt"] if rows and (rest or more) else None,
		"scanned": {"folders": looked, "of": len(folders)},
		"partial": partial,
	}
	if not partial:
		cache.set_value(_key(account, digest), answer, expires_in_sec=CACHE_S)
	return {"accountId": args.get("accountId"), "state": "0", **answer}


METHODS = {
	"NeomailContact/get": contact_get,
	"NeomailHistory/get": history_get,
	"NeomailLinked/get": linked_get,
}
