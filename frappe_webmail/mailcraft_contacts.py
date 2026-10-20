# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
JMAP for Contacts (RFC 9610) in MailCraft's facade (mailcraft_jmap): the instance's contacts (Contact, with their
addresses and phone numbers) as one address book, with the rights of the person the token is for. NeoMail's address
book, its completion of recipients and its person card are then Neoffice's (maintenance#1630, step 2 of NeoMail's
programme). NeoMail does what the desk does (Jérémy, 17.10: "she must be able to do everything, as in the desk"): it
creates, changes and deletes contacts with the person's own rights, and by the desk's rules (Frappe's link check and
the apps' own hooks on a deletion; a deleted one can be restored from the Deleted Documents).

The contacts are the instance's, not a mailbox's, and MailCraft keeps an address book per account: one mailbox of the
person offers them, their own first (by name), else the first shared with them, so that they are not listed twice.
"""

import hashlib
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, strip_html

from frappe_webmail import mailcraft_jmap as jmap

CONTACTS = "urn:ietf:params:jmap:contacts"
BOOK = "neoffice"
MAX_CARDS = 5000
UID_SECONDS = 7 * 24 * 3600  # how long a create is recognised by its card's uid (an answer lost on the way)
FIELDS = [
	"name",
	"first_name",
	"last_name",
	"full_name",
	"company_name",
	"designation",
	"creation",
	"modified",
]
PROPERTIES = {
	"id",
	"uid",
	"addressBookIds",
	"name",
	"emails",
	"phones",
	"organizations",
	"titles",
	"created",
	"updated",
}
# The longest text a contact keeps in a field (Data fields): a longer one is refused, never cut.
MAX_TEXT = 140


def contacts_mailbox():
	"""The one mailbox of the person whose session offers the address book: their own first, by name, else the first
	shared with them; None without any."""
	from frappe_webmail.webmail_api import get_accounts

	accounts = get_accounts()
	user = frappe.session.user
	own = sorted(a["name"] for a in accounts if a.get("user") == user)
	shared = sorted(a["name"] for a in accounts if a.get("user") != user)
	return (own or shared or [None])[0]


def session_parts(account):
	"""What the session of `account` (a Webmail Account) adds when it offers the address book: its capabilities, and its
	account's; nothing for the person's other mailboxes."""
	if account.name != contacts_mailbox():
		return {}, {}
	return {CONTACTS: {}}, {
		CONTACTS: {
			"maxAddressBooksPerCard": 1,
			"mayCreateAddressBook": False,
			# Not in the RFC: what a card keeps when it is written here, so that a client offers nothing else (addresses,
			# notes, birthdays…) rather than learn it from a refusal.
			"writableProperties": sorted(WRITABLE),
		}
	}


def _book_account(args):
	"""The account a call names, when it is the one that offers the address book."""
	account = jmap._account(args.get("accountId"))
	if account.name != contacts_mailbox():
		raise jmap.JmapError("accountNotSupportedByMethod", "This mailbox offers no address book.")
	return jmap.account_id(account.name)


def _readable():
	"""Whether the person may read contacts at all: frappe.get_list refuses outright someone who may not."""
	return bool(frappe.has_permission("Contact", "read"))


def _may_write():
	"""Whether the person may create and change contacts: their rights, and no User Permission that keeps them to some
	contacts (a new one is never among those: Frappe refuses to create it, and the book would refuse every card)."""
	if not (frappe.has_permission("Contact", "create") and frappe.has_permission("Contact", "write")):
		return False
	from frappe.core.doctype.user_permission.user_permission import get_user_permissions

	return not get_user_permissions(frappe.session.user).get("Contact")


def address_book_get(args):
	aid = _book_account(args)
	ids = jmap._ids(args)
	writes = _may_write()
	# RFC 9610: `mayDelete` is the book itself (never, here), and destroying cards falls under `mayWrite`. Someone who
	# may write contacts but not delete them (a Sales User) is said by `mayRemoveItems`, as JMAP's mailboxes say it.
	removes = bool(writes and frappe.has_permission("Contact", "delete"))
	book = {
		"id": BOOK,
		"name": "Neoffice",
		"description": None,
		"sortOrder": 0,
		"isDefault": True,
		"isSubscribed": True,
		"shareWith": None,
		"myRights": {
			"mayRead": True,
			"mayWrite": writes,
			"mayShare": False,
			"mayDelete": False,
			"mayRemoveItems": removes,
		},
	}
	return {
		"accountId": aid,
		"state": "0",
		"list": [book] if ids is None or BOOK in ids else [],
		"notFound": [i for i in (ids or []) if i != BOOK],
	}


def _aggregate(expression):
	"""One aggregate of the contacts the person may read (frappe.get_list's rights): `count(name)`, `max(modified)`. A
	column named with its table inside the function (`max(`tabContact`.modified)`) is read by get_list as a DocType."""
	if not _readable():
		return None
	rows = frappe.get_list("Contact", fields=[f"{expression} as aggregate"])
	return rows[0].get("aggregate") if rows else None


def _state():
	"""The cards' state: it changes when a contact the person may read is added, changed or removed."""
	count, newest = _aggregate("count(name)"), _aggregate("max(modified)")
	return hashlib.sha256(f"{count}|{newest}".encode()).hexdigest()[:16]


def card_query(args):
	"""The ids of the contacts the person may read, by name; the filters are the one address book, and `uid`: the contact
	a create with that uid made here (a client that sends a create again finds it, and writes it only what changed). A
	window of them (RFC 8620 §5.5): `position` from the start, or from the end when negative; `limit` at most MAX_CARDS,
	said back when the server set it; `total` when asked (`calculateTotal`)."""
	aid = _book_account(args)
	position = jmap._whole_number(args.get("position"), "position", 0)
	limit = jmap._whole_number(args.get("limit"), "limit")
	if limit is not None and limit < 0:
		raise jmap.JmapError("invalidArguments", "limit")
	if args.get("anchor") is not None:
		raise jmap.JmapError("invalidArguments", "anchor")
	criteria = args.get("filter")
	if criteria is not None and (
		not isinstance(criteria, dict)
		or set(criteria) - {"inAddressBook", "uid"}
		or criteria.get("inAddressBook", BOOK) != BOOK
		or ("uid" in criteria and not isinstance(criteria["uid"], str))
	):
		raise jmap.JmapError("unsupportedFilter", "Only inAddressBook and uid are supported.")
	if args.get("sort") not in (None, []):
		raise jmap.JmapError("unsupportedSort", "The cards come by name.")
	if criteria and "uid" in criteria:
		made = _made_before(_text(criteria["uid"], 255)) if _readable() else None
		found = [made] if made else []
		answer = {
			"accountId": aid,
			"queryState": _state(),
			"canCalculateChanges": False,
			"position": 0,
			"ids": found[position:] if limit is None else found[position : position + limit],
		}
		if args.get("calculateTotal"):
			answer["total"] = len(found)
		return answer
	total = cint(_aggregate("count(name)")) if args.get("calculateTotal") or position < 0 else None
	if position < 0:
		position = max(0, total + position)
	used = MAX_CARDS if limit is None else min(limit, MAX_CARDS)
	ids = (
		frappe.get_list(
			"Contact", pluck="name", order_by="name asc", limit_start=position, limit_page_length=used
		)
		if used and _readable()  # a page length of 0 would be no limit at all
		else []
	)
	answer = {
		"accountId": aid,
		"queryState": _state(),
		"canCalculateChanges": False,
		"position": position,
		"ids": ids,
	}
	if args.get("calculateTotal"):
		answer["total"] = total
	if limit is None or limit > MAX_CARDS:
		answer["limit"] = used
	return answer


def card_get(args):
	"""The cards (JSContact, RFC 9553) of the contacts asked for that the person may read; the others are not found."""
	aid = _book_account(args)
	ids = jmap._ids(args)
	if ids is None:
		every = card_query({"accountId": args.get("accountId"), "limit": jmap.MAX_OBJECTS + 1})["ids"]
		if len(every) > jmap.MAX_OBJECTS:
			raise jmap.JmapError("requestTooLarge", "Ask for the cards by id (ContactCard/query).")
		ids = every
	ids = [i for i in ids if isinstance(i, str)]
	properties = args.get("properties")
	if properties is not None and (
		not isinstance(properties, list) or not all(isinstance(p, str) for p in properties)
	):
		raise jmap.JmapError("invalidArguments", "properties")
	rows = (
		frappe.get_list("Contact", filters={"name": ["in", ids]}, fields=FIELDS, limit_page_length=len(ids))
		if ids and _readable()
		else []
	)
	names = [row.name for row in rows]
	emails, phones = defaultdict(list), defaultdict(list)
	if names:
		# The rows of contacts the person may read (the list above); a child table has no rights of its own.
		for email in frappe.get_all(
			"Contact Email",
			filters={"parent": ["in", names], "parenttype": "Contact"},
			fields=["parent", "email_id", "is_primary"],
			order_by="is_primary desc, idx asc",
		):
			emails[email.parent].append(email)
		for phone in frappe.get_all(
			"Contact Phone",
			filters={"parent": ["in", names], "parenttype": "Contact"},
			fields=["parent", "phone", "is_primary_mobile_no"],
			order_by="idx asc",
		):
			phones[phone.parent].append(phone)
	wanted = set(properties) & PROPERTIES | {"id"} if properties is not None else None
	cards = [_card(row, emails[row.name], phones[row.name], wanted) for row in rows]
	return {
		"accountId": aid,
		"state": _state(),
		"list": cards,
		"notFound": [i for i in ids if i not in set(names)],
	}


def card_set(args):
	"""Contacts created, changed and deleted with the person's rights (a full property replaces it: `name`, `emails`,
	`phones`, `organizations`, `titles`), as the desk does. Each refusal is said for its card, and what a refused card
	had begun to write is undone (a savepoint per card), so the others still go through."""
	aid = _book_account(args)
	creates, updates = args.get("create") or {}, args.get("update") or {}
	destroys = args.get("destroy") or []
	if not isinstance(creates, dict) or not isinstance(updates, dict) or not isinstance(destroys, list):
		raise jmap.JmapError("invalidArguments", "create, update, destroy")
	if len(creates) + len(updates) + len(destroys) > jmap.MAX_OBJECTS:
		raise jmap.JmapError("requestTooLarge", "maxObjectsInSet")
	if args.get("ifInState") is not None:
		raise jmap.JmapError("invalidArguments", "ifInState")
	old_state = _state()
	created, updated, not_created, not_updated = {}, {}, {}, {}
	for key, card in creates.items():
		refusal = _one_card(lambda card=card: _create(card))
		if isinstance(refusal, str):
			created[key] = {"id": refusal, "uid": refusal}
		else:
			not_created[key] = refusal
	for name, patch in updates.items():
		refusal = _one_card(lambda name=name, patch=patch: _update(name, patch))
		if isinstance(refusal, dict):
			not_updated[name] = refusal
		else:
			updated[name] = None
	destroyed, not_destroyed = [], {}
	for name in destroys:
		if not isinstance(name, str):
			continue
		refusal = _one_card(lambda name=name: _destroy(name))
		if isinstance(refusal, dict):
			not_destroyed[name] = refusal
		else:
			destroyed.append(name)
	return {
		"accountId": aid,
		"oldState": old_state,
		"newState": _state(),
		"created": created,
		"updated": updated,
		"destroyed": destroyed,
		"notCreated": not_created,
		"notUpdated": not_updated,
		"notDestroyed": not_destroyed,
	}


SAVEPOINT = "mailcraft_card"


def _one_card(write):
	"""Runs the write of one card: its answer, or its SetError (a dict) after undoing what it had begun."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		return write() or True
	except Exception as e:
		# Undone, or the whole call fails (the client keeps the cards and sends them again: a create comes back to the
		# same contact by its uid).
		frappe.db.rollback(save_point=SAVEPOINT)
		return _refusal(e)


WRITABLE = {"name", "emails", "phones", "organizations", "titles"}
IGNORED = {"@type", "version", "addressBookIds", "uid", "kind", "created", "updated"}


def _refusal(error):
	"""A JMAP SetError for what stopped a card."""
	if isinstance(error, frappe.PermissionError):
		return {"type": "forbidden", "description": _("Your rights do not allow it.")}
	if isinstance(error, frappe.DoesNotExistError):
		return {"type": "notFound"}
	if isinstance(error, frappe.LinkExistsError):
		# The desk's rule: a contact that documents name is not deleted (Frappe says which).
		return {"type": "forbidden", "description": strip_html(str(error)).strip()[:200]}
	if isinstance(error, frappe.ValidationError | ValueError | TypeError):
		# NeoMail shows it as it is: Frappe's messages carry markup ("Only one <strong>Email ID</strong>…").
		return {"type": "invalidProperties", "description": strip_html(str(error)).strip()[:200]}
	frappe.log_error("MailCraft contacts: a card could not be written", frappe.get_traceback())
	return {"type": "serverFail"}


def _entries(card, key):
	"""The entries of a JSContact map property (`emails`, `phones`…): its values that are objects; null is none."""
	value = card.get(key)
	if value is None:
		return []
	if not isinstance(value, dict):
		raise ValueError(f"{key} must be an object.")
	return [entry for entry in value.values() if isinstance(entry, dict)]


def _text(value, size=MAX_TEXT, what=None):
	"""A text of a card, trimmed: one longer than the contact keeps is refused (named `what`), or cut when `what` is
	not given (what the contact itself derives)."""
	text = str(value if value is not None else "").strip()
	if what and len(text) > size:
		raise ValueError(_("{0} is longer than {1} characters.").format(what, size))
	return text[:size]


def _fields(card):
	"""What a JSContact card (or a patch of whole properties) gives, only for the properties it names: the Contact's
	plain fields, its addresses (`emails`, in order, each once) and its phone numbers (`phones`: number, mobile)."""
	if not isinstance(card, dict) or set(card) - WRITABLE - IGNORED:
		raise ValueError("Only name, emails, phones, organizations and titles can be written.")
	if "addressBookIds" in card and card["addressBookIds"] != {BOOK: True}:
		raise ValueError("A card goes in the Neoffice address book.")
	out = {}
	if "name" in card:
		name = card["name"] or {}
		if not isinstance(name, dict):
			raise ValueError("name must be an object.")
		components = name.get("components") or []
		if not isinstance(components, list):
			raise ValueError("name.components must be a list.")
		parts = {
			p.get("kind"): _text(p.get("value"), what=_("A name")) for p in components if isinstance(p, dict)
		}
		first, last = parts.get("given", ""), parts.get("surname", "")
		if not first and not last:
			# Only the full name (a client that keeps no parts of it): read as the contact's own when it is unchanged.
			out["full_name"] = _text(name.get("full"), 281, _("A name"))
			first, _sep, last = out["full_name"].partition(" ")
		out["first_name"], out["last_name"] = first[:140], last.strip()[:140]
	if "emails" in card:
		seen, addresses, preferred = set(), [], []
		for entry in _entries(card, "emails"):
			address = _text(entry.get("address"), what=_("An address"))
			if "@" in address and address.lower() not in seen:
				seen.add(address.lower())
				addresses.append(address)
				# RFC 9553: the lowest `pref` is the most preferred, and is the contact's primary address.
				if isinstance(entry.get("pref"), int) and not isinstance(entry.get("pref"), bool):
					preferred.append((entry["pref"], len(addresses), address))
		out["emails"] = addresses
		if preferred:
			out["primary_email"] = min(preferred)[2]
	if "phones" in card:
		out["phones"] = [
			(
				_text(entry.get("number"), what=_("A number")),
				bool((entry.get("features") or {}).get("mobile")),
			)
			for entry in _entries(card, "phones")
			if _text(entry.get("number"), what=_("A number"))
		]
	if "organizations" in card:
		names = [_text(o.get("name"), what=_("A company")) for o in _entries(card, "organizations")]
		out["company_name"] = next((n for n in names if n), "")
	if "titles" in card:
		names = [_text(t.get("name"), what=_("A job title")) for t in _entries(card, "titles")]
		out["designation"] = next((n for n in names if n), "")
	return out


def _email_rows(addresses, primary=None):
	"""Contact Email rows: the primary address stays the one it was while it is there, else the first."""
	if primary not in addresses:
		primary = addresses[0] if addresses else None
	return [{"email_id": a, "is_primary": int(a == primary)} for a in addresses]


def _phone_rows(phones, old=()):
	"""Contact Phone rows. A number the contact had keeps what it was (whether it is a mobile is not read back: only the
	primary mobile number says so, the others read as numbers); the primary of a kind that went goes to the first new
	number of that kind; on a new contact, the first number of each kind is its primary. One of each at most: the
	Contact refuses two."""
	before = {row["phone"]: row for row in old}
	rows = [
		{
			"phone": number,
			"is_primary_phone": cint(before.get(number, {}).get("is_primary_phone")),
			"is_primary_mobile_no": cint(before.get(number, {}).get("is_primary_mobile_no")),
		}
		for number, _mobile in phones
	]
	for flag, of_kind in (("is_primary_phone", False), ("is_primary_mobile_no", True)):
		flagged = [row for row in rows if row[flag]]
		for extra in flagged[1:]:
			extra[flag] = 0
		if not flagged:
			first_new = next(
				(
					row
					for row, (number, mobile) in zip(rows, phones, strict=True)
					if mobile == of_kind and number not in before
				),
				None,
			)
			if first_new:
				first_new[flag] = 1
	return rows


def _uid_key(uid):
	return f"mailcraft_card_uid:{frappe.session.user}:" + hashlib.sha256(uid.encode()).hexdigest()


def _made_before(uid):
	"""The contact a create with this uid made, when it is still that one: the person's, created when it was (a create
	whose transaction was lost leaves its name free, and another contact may take it)."""
	kept = frappe.cache().get_value(_uid_key(uid)) if uid else None
	if not isinstance(kept, dict) or not isinstance(kept.get("name"), str):
		return None
	row = frappe.db.get_value("Contact", kept["name"], ["owner", "creation"], as_dict=True)
	if not row or row.owner != frappe.session.user or str(row.creation) != kept.get("creation"):
		return None
	return kept["name"] if frappe.has_permission("Contact", "read", doc=kept["name"]) else None


def _create(card):
	frappe.has_permission("Contact", "create", throw=True)
	fields = _fields(card)
	# A card sent again after its answer was lost: the contact made the first time, not a second one.
	uid = _text(card.get("uid"), 255) if isinstance(card.get("uid"), str) else ""
	made = _made_before(uid)
	if made:
		# Sent again after its answer was lost, maybe changed in between: the contact made the first time gets what the
		# client sends now, so that the server holds what the client believes it does.
		_update(made, {key: value for key, value in card.items() if key in WRITABLE})
		return made
	fields.pop("full_name", None)
	addresses, phones = fields.pop("emails", []), fields.pop("phones", [])
	primary = fields.pop("primary_email", None)
	if not (fields.get("first_name") or fields.get("last_name")) and not fields.get("company_name"):
		# A contact is named: by its company, as the desk names one (Contact.autoname), else from its address
		# ("jeanne.muster@…" → Jeanne Muster).
		if not addresses:
			raise ValueError(_("A contact needs a name, a company or an address."))
		words = addresses[0].split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").split()
		fields["first_name"] = " ".join(word.capitalize() for word in words)[:140] or addresses[0][:140]
	doc = frappe.get_doc(
		{
			"doctype": "Contact",
			**fields,
			"email_ids": _email_rows(addresses, primary),
			"phone_nos": _phone_rows(phones),
		}
	)
	name = doc.insert().name
	if uid:
		frappe.cache().set_value(
			_uid_key(uid), {"name": name, "creation": str(doc.creation)}, expires_in_sec=UID_SECONDS
		)
	return name


def _update(name, patch):
	# A contact the person may not read is one that is not there: "forbidden" would say it exists.
	if not isinstance(name, str) or not frappe.db.exists("Contact", name):
		raise frappe.DoesNotExistError
	if not frappe.has_permission("Contact", "read", doc=name):
		raise frappe.DoesNotExistError
	if isinstance(patch, dict) and any("/" in key for key in patch):
		raise ValueError("A whole property replaces it: no patch of a part.")
	fields = _fields(patch)
	doc = frappe.get_doc("Contact", name)
	doc.check_permission("write")
	if "first_name" in fields and not (fields["first_name"] or fields["last_name"]):
		# A name emptied is not written: a contact keeps one.
		del fields["first_name"], fields["last_name"]
	full = fields.pop("full_name", None)
	if full is not None and full == (doc.full_name or "").strip() and "first_name" in fields:
		# The full name as the contact has it (a company's contact reads as its company): nothing of it changed.
		del fields["first_name"], fields["last_name"]
	for key in ("first_name", "last_name", "company_name", "designation"):
		if key in fields:
			doc.set(key, fields[key])
	if "emails" in fields:
		primary = fields.get("primary_email") or next(
			(row.email_id for row in doc.email_ids if row.is_primary), None
		)
		doc.set("email_ids", _email_rows(fields["emails"], primary))
	if "phones" in fields:
		old = [
			{
				"phone": row.phone,
				"is_primary_phone": row.is_primary_phone,
				"is_primary_mobile_no": row.is_primary_mobile_no,
			}
			for row in doc.phone_nos
		]
		doc.set("phone_nos", _phone_rows(fields["phones"], old))
	doc.save()


def _destroy(name):
	"""Deletes a contact as the desk does: the person's right to delete it, the documents linked to it (Frappe refuses
	to delete one that documents name), and a copy kept in the Deleted Documents, from where it can be restored. One the
	person may not read is not there."""
	if not isinstance(name, str) or not frappe.db.exists("Contact", name):
		raise frappe.DoesNotExistError
	if not frappe.has_permission("Contact", "read", doc=name):
		raise frappe.DoesNotExistError
	frappe.delete_doc("Contact", name)


def _card(row, emails, phones, wanted=None):
	full = (row.full_name or " ".join(p for p in (row.first_name, row.last_name) if p)).strip()
	components = [
		{"@type": "NameComponent", "kind": kind, "value": value}
		for kind, value in (("given", row.first_name), ("surname", row.last_name))
		if value
	]
	card = {
		"@type": "Card",
		"version": "1.0",
		"id": row.name,
		"uid": row.name,
		"addressBookIds": {BOOK: True},
		"name": {"@type": "Name", "full": full, "components": components},
		"emails": {
			f"e{n}": {"@type": "EmailAddress", "address": e.email_id, **({"pref": 1} if e.is_primary else {})}
			for n, e in enumerate((e for e in emails if e.email_id), 1)
		},
		"phones": {
			f"p{n}": {
				"@type": "Phone",
				"number": p.phone,
				"features": {"mobile": True} if p.is_primary_mobile_no else {"voice": True},
			}
			for n, p in enumerate((p for p in phones if p.phone), 1)
		},
	}
	if row.creation:
		card["created"] = jmap.utc_of(row.creation)
	if row.modified:
		card["updated"] = jmap.utc_of(row.modified)
	if row.company_name:
		card["organizations"] = {"o1": {"@type": "Organization", "name": row.company_name}}
	if row.designation:
		card["titles"] = {"t1": {"@type": "Title", "name": row.designation, "kind": "title"}}
	if wanted is not None:
		card = {k: v for k, v in card.items() if k in wanted or k in ("@type", "version")}
	return card


def no_changes(args):
	"""The changes since a state are not kept: the client reads the address book again (RFC 8620 §5.2)."""
	_book_account(args)
	raise jmap.JmapError("cannotCalculateChanges", "Read the address book again.")


METHODS = {
	"AddressBook/get": address_book_get,
	"AddressBook/changes": no_changes,
	"ContactCard/query": card_query,
	"ContactCard/queryChanges": no_changes,
	"ContactCard/get": card_get,
	"ContactCard/changes": no_changes,
	"ContactCard/set": card_set,
}
