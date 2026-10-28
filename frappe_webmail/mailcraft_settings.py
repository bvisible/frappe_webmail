# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
What NeoMail keeps of a person's window between two visits (maintenance#1956): their rules, their categories, and the
Safe Senders and Blocked Senders of each of their mailboxes. NeoMail's tab in the desk and Neodesk's window keep nothing
of their own (the browser build's `keeps_local`): without this, all of it was gone at the next visit.

Where it is kept. The mailboxes are the person's own at their provider (IMAP, read through the webmail): no standard place
there takes MailCraft's rules or lists (no JMAP for Sieve, RFC 9661, over IMAP; ManageSieve is not offered by every
provider). So the instance keeps them, in `NeoMail Setting`: one record of the person (`account` empty) for the rules and
the categories, which are their whole window's (`account` PERSON), and one record per mailbox for its two lists, the person's own even in a
mailbox shared with them. What they hold is MailCraft's own shape (a rule's conditions and actions, a category's name and
colour), checked for its shape and its size only; a rule that files into a folder names it by its mailbox and the
folder's id on the server, never by an id of this visit.

JMAP has no standard for these: a data type of our own in its shape, under SETTINGS, with NeomailSettings/get and
NeomailSettings/set (one object, `singleton`, in each mailbox). Offered in every mailbox of the facade (mailcraft_jmap):
the person reads and writes their own, and in a mailbox they may open (the webmail's rule, `get_account`); nobody reads or
writes another person's.
"""

import hashlib
import json

import frappe

from frappe_webmail import mailcraft_jmap as jmap

SETTINGS = "https://neoffice.me/jmap/neomail-settings"
DOCTYPE = "NeoMail Setting"
SINGLETON = "singleton"
MAX_RULES = 500  # as MailCraft keeps (mailcraft_model::MAX_RULES)
MAX_CATEGORIES = 1_000  # as MailCraft keeps (mailcraft_model::MAX_CATEGORIES)
MAX_SENDERS = 1_000  # each list (mailcraft_model::MAX_JUNK_ENTRIES)
MAX_SENDER = 320  # an address, or a domain
MAX_NAME = 255
MAX_RULES_BYTES = 512 * 1024
MAX_CATEGORIES_BYTES = 256 * 1024
# The record of the person's rules and categories, which are their whole window's (no Webmail Account is named so).
PERSON = "*"
PERSON_FIELDS = {"rules": "rules", "categories": "categories"}
MAILBOX_FIELDS = {"safeSenders": "safe_senders", "blockedSenders": "blocked_senders"}


def session_parts(account):
	"""What every mailbox's session adds: the capability, and what its account takes."""
	return {SETTINGS: {}}, {
		SETTINGS: {
			"maxRules": MAX_RULES,
			"maxCategories": MAX_CATEGORIES,
			"maxSenders": MAX_SENDERS,
		}
	}


def _record(user, account):
	"""The name of the person's record for `account` (PERSON for their own), or None when there is none yet."""
	return frappe.db.get_value(DOCTYPE, {"user": user, "account": account}, "name")


def _read(user, account):
	name = _record(user, account)
	if not name:
		return {}
	row = frappe.db.get_value(
		DOCTYPE, name, ["rules", "categories", "safe_senders", "blocked_senders"], as_dict=True
	)
	return {key: _loaded(row.get(key)) for key in ("rules", "categories", "safe_senders", "blocked_senders")}


def _loaded(value):
	if value is None or value == "":
		return None
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			return None
	return value


def _state(person, mailbox):
	"""A state for what the two records hold: it changes when they do."""
	text = json.dumps([person, mailbox], sort_keys=True, default=str)
	return hashlib.sha256(text.encode()).hexdigest()[:16]


def _object(person, mailbox):
	return {
		"id": SINGLETON,
		# None: never kept; MailCraft keeps what it has
		"rules": person.get("rules"),
		"categories": person.get("categories"),
		"safeSenders": mailbox.get("safe_senders") or [],
		"blockedSenders": mailbox.get("blocked_senders") or [],
	}


def settings_get(args):
	account = jmap._account(args.get("accountId"))
	user = frappe.session.user
	ids = args.get("ids")
	if ids is not None and (
		not isinstance(ids, list)
		or len(ids) > 50
		or not all(isinstance(i, str) and len(i) <= 255 for i in ids)
	):
		raise jmap.JmapError("invalidArguments", "ids")
	person, mailbox = _read(user, PERSON), _read(user, account.name)
	wanted = ids is None or SINGLETON in ids
	return {
		"accountId": args.get("accountId"),
		"state": _state(person, mailbox),
		"list": [_object(person, mailbox)] if wanted else [],
		"notFound": [i for i in (ids or []) if i != SINGLETON],
	}


def settings_set(args):
	account = jmap._account(args.get("accountId"))
	user = frappe.session.user
	before = _state(_read(user, PERSON), _read(user, account.name))
	if args.get("ifInState") and args["ifInState"] != before:
		raise jmap.JmapError("stateMismatch")
	update = args.get("update") or {}
	if not isinstance(update, dict):
		raise jmap.JmapError("invalidArguments", "update")
	updated, not_updated = {}, {}
	for key, patch in update.items():
		if key != SINGLETON:
			not_updated[str(key)[:50]] = {"type": "notFound"}
			continue
		try:
			person, mailbox = _checked(patch)
		except ValueError as e:
			not_updated[SINGLETON] = {"type": "invalidProperties", "description": str(e)}
			continue
		if person:
			_write(user, PERSON, person)
		if mailbox:
			_write(user, account.name, mailbox)
		updated[SINGLETON] = None
	answer = {
		"accountId": args.get("accountId"),
		"oldState": before,
		"newState": _state(_read(user, PERSON), _read(user, account.name)),
		"created": None,
		"updated": updated or None,
		"destroyed": None,
		"notCreated": None,
		"notUpdated": not_updated or None,
		"notDestroyed": None,
	}
	# The one object is always there: nothing is made, nothing is destroyed
	for asked, said in (("create", "notCreated"), ("destroy", "notDestroyed")):
		given = args.get(asked)
		if given:
			keys = list(given)[:50] if isinstance(given, dict | list) else []
			answer[said] = {str(k)[:50]: {"type": "forbidden"} for k in keys}
	return answer


def _checked(patch):
	"""The person's fields and the mailbox's fields of a patch, checked: ValueError says what is wrong."""
	if not isinstance(patch, dict):
		raise ValueError("the object is not a JSON object")
	unknown = set(patch) - set(PERSON_FIELDS) - set(MAILBOX_FIELDS)
	if unknown:
		raise ValueError("unknown properties: " + ", ".join(sorted(str(u)[:40] for u in unknown)[:10]))
	person, mailbox = {}, {}
	if "rules" in patch:
		person["rules"] = _rules(patch["rules"])
	if "categories" in patch:
		person["categories"] = _categories(patch["categories"])
	for key, field in MAILBOX_FIELDS.items():
		if key in patch:
			mailbox[field] = _senders(patch[key], key)
	return person, mailbox


def _size(value):
	return len(json.dumps(value, separators=(",", ":")).encode())


def _rules(rules):
	if not isinstance(rules, list) or len(rules) > MAX_RULES:
		raise ValueError(f"rules: a list of {MAX_RULES} rules at most")
	for rule in rules:
		if (
			not isinstance(rule, dict)
			or not isinstance(rule.get("name", ""), str)
			or len(rule.get("name", "")) > MAX_NAME
		):
			raise ValueError("rules: each rule is an object with a name")
		if not isinstance(rule.get("conditions", []), list) or not isinstance(rule.get("actions", []), list):
			raise ValueError("rules: conditions and actions are lists")
	if _size(rules) > MAX_RULES_BYTES:
		raise ValueError("rules: too large")
	return rules


def _categories(categories):
	if not isinstance(categories, list) or len(categories) > MAX_CATEGORIES:
		raise ValueError(f"categories: a list of {MAX_CATEGORIES} categories at most")
	for category in categories:
		if not isinstance(category, dict):
			raise ValueError("categories: each category is an object")
		name, color = category.get("name"), category.get("color")
		if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
			raise ValueError("categories: each category has a name")
		if not (
			isinstance(color, list)
			and len(color) == 3
			and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)
		):
			raise ValueError("categories: a colour is three numbers from 0 to 255")
	if _size(categories) > MAX_CATEGORIES_BYTES:
		raise ValueError("categories: too large")
	return categories


def _senders(senders, key):
	if not isinstance(senders, list) or len(senders) > MAX_SENDERS:
		raise ValueError(f"{key}: a list of {MAX_SENDERS} entries at most")
	kept = []
	for sender in senders:
		if (
			not isinstance(sender, str)
			or not sender.strip()
			or len(sender) > MAX_SENDER
			or any(c.isspace() or ord(c) < 32 for c in sender)
		):
			raise ValueError(f"{key}: each entry is an address or a domain")
		kept.append(sender)
	return kept


def _write(user, account, fields):
	name = _record(user, account)
	values = {field: json.dumps(value) for field, value in fields.items()}
	if not name:
		try:
			frappe.get_doc({"doctype": DOCTYPE, "user": user, "account": account, **values}).insert(
				ignore_permissions=True
			)
		except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
			# Two first writes at once (two windows): the other one made the record, this one changes it
			frappe.db.rollback()
			name = _record(user, account)
	if name:
		frappe.db.set_value(DOCTYPE, name, values)
	frappe.db.commit()  # nosemgrep: the answer says it is kept


METHODS = {
	"NeomailSettings/get": settings_get,
	"NeomailSettings/set": settings_set,
}


def on_user_trash(doc, method=None):
	"""A person deleted takes what NeoMail kept of their window with them."""
	if frappe.db.table_exists(DOCTYPE):
		frappe.db.delete(DOCTYPE, {"user": doc.name})


def on_account_trash(doc, method=None):
	"""A mailbox deleted takes everybody's lists of it with it."""
	if frappe.db.table_exists(DOCTYPE):
		frappe.db.delete(DOCTYPE, {"account": doc.name})
