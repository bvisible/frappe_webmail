# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
NeoMail's notes are Neoffice's (Jérémy, 20.10: notes are not to be kept in fifteen places): the person's Neoffice Notes
(neoffice_theme), those they own and those shared with them, as the desk's Notes page, the phone and Neodesk list them
(neoffice_theme.notes_api.list_my_notes), in MailCraft's facade (mailcraft_jmap). JMAP has no standard for notes: this
is a data type of our own in its shape, under NOTES, with Note/get, Note/query, Note/set and Note/changes (not kept).

A note is read as its title and its text (the words of its content, without markup). It is written as the desk's Notes
page writes it: a plain note's title and text replace them (notes_api.update_note, so its children are never touched),
it is pinned or archived (notes_api.set_note_pinned, set_note_archived), and deleted by its owner only, as the desk
deletes it (a copy in the Deleted Documents; its attachments' files go with it). Only what differs from the note is
written: a client may send back a whole note it read. A rich note (formatting, a checklist, attachments, drawings, a recording) is read here and its words changed
in the desk, where `webUrl` opens it: they would not survive a write of plain text. Offered in the mailbox that offers
the address book (mailcraft_contacts.contacts_mailbox), where neoffice_theme is installed.
"""

import contextlib
import hashlib
import html
import json
import re
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, strip_html

from frappe_webmail import mailcraft_jmap as jmap

NOTES = "https://neoffice.me/jmap/notes"
NOTE_DOCTYPE = "Neoffice Note"
MAX_NOTES = 5000
MAX_TITLE = 140  # the title is a Data field
MAX_TEXT = 100_000
UID_SECONDS = 7 * 24 * 3600  # how long a create is recognised by its note's uid (an answer lost on the way)
FIELDS = [
	"name",
	"title",
	"content",
	"category",
	"archived",
	"pinned",
	"owner",
	"creation",
	"modified",
	"audio_file",
]
PROPERTIES = {
	"id",
	"title",
	"text",
	"isRich",
	"isPinned",
	"isArchived",
	"category",
	"created",
	"updated",
	"isShared",
	"ownerName",
	"myRights",
	"webUrl",
}
WRITABLE = {"title", "text", "isPinned", "isArchived"}
# What a client may send back as it read it, and the server keeps for itself: left as it is ("updated" is read as the
# version the client changed, see _update).
IGNORED = PROPERTIES - WRITABLE | {"uid", "@type"}
# The children that make a note rich: what plain text cannot carry.
CHILDREN = ("Note Checklist Item", "Note Attachment", "Note Canvas")
# The markup a plain note's content may have: paragraphs and line breaks (the desk's editor wraps them in its own div).
_PLAIN_TAGS = {"p", "br", "div"}
_TAG = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")


def notes_installed():
	return "neoffice_theme" in frappe.get_installed_apps()


def session_parts(account):
	"""What the session of `account` (a Webmail Account) adds when it offers the notes: its capabilities, and its
	account's; nothing for the person's other mailboxes, nor without Neoffice's notes."""
	from frappe_webmail.mailcraft_contacts import contacts_mailbox

	if not notes_installed() or account.name != contacts_mailbox():
		return {}, {}
	return {NOTES: {}}, {
		NOTES: {
			"maxSizeTitle": MAX_TITLE,
			"maxSizeText": MAX_TEXT,
			"writableProperties": sorted(WRITABLE),
		}
	}


def _notes_account(args):
	"""The account a call names, when it is the one that offers the notes."""
	from frappe_webmail.mailcraft_contacts import contacts_mailbox

	account = jmap._account(args.get("accountId"))
	if not notes_installed() or account.name != contacts_mailbox():
		raise jmap.JmapError("accountNotSupportedByMethod", "This mailbox offers no notes.")
	return jmap.account_id(account.name)


def _shared_names():
	"""The notes shared with the person (the DocType reads only one's own: `if_owner`), read once per request."""
	request = getattr(frappe.local, "request", None)
	kept = getattr(request, "_mailcraft_note_shares", None)
	if kept is not None:
		return kept
	names = frappe.get_all(
		"DocShare", filters={"share_doctype": NOTE_DOCTYPE, "user": frappe.session.user}, pluck="share_name"
	)
	if request is not None:
		with contextlib.suppress(AttributeError, TypeError):
			request._mailcraft_note_shares = names
	return names


def _visible(fields, names=None, archived=None):
	"""The notes the person sees in the desk's Notes list (owned, then shared with them), among `names` when given, of
	one archive state when given: pinned first, then the latest changed first, then by name."""
	user = frappe.session.user
	filters = {} if archived is None else {"archived": cint(archived)}
	if names is not None:
		filters["name"] = ["in", list(names)]
	owned = frappe.get_all(
		NOTE_DOCTYPE, filters={**filters, "owner": user}, fields=fields, ignore_permissions=True
	)
	shared = _shared_names()
	if names is not None:
		wanted = set(names)
		shared = [name for name in shared if name in wanted]
	if shared:
		filters["name"] = ["in", shared]
		owned += frappe.get_all(NOTE_DOCTYPE, filters=filters, fields=fields, ignore_permissions=True)
	seen, rows = set(), []
	for row in owned:
		if row.name not in seen:
			seen.add(row.name)
			rows.append(row)
	rows.sort(key=lambda row: row.name)
	rows.sort(key=lambda row: str(row.modified), reverse=True)
	rows.sort(key=lambda row: -cint(row.pinned))
	return rows


def _state():
	"""The notes' state: it changes when a note the person sees is added, changed or removed, or a share of one with
	them is added, removed or changed."""
	rows = sorted((row.name, str(row.modified)) for row in _visible(["name", "modified"]))
	shares = sorted(
		(row.share_name, cint(row.write))
		for row in frappe.get_all(
			"DocShare",
			filters={"share_doctype": NOTE_DOCTYPE, "user": frappe.session.user},
			fields=["share_name", "write"],
		)
	)
	return hashlib.sha256(json.dumps([rows, shares]).encode()).hexdigest()[:16]


_BLOCK_END = r"<\s*/\s*(?:p|div|li|h[1-6])\s*>"
# An empty paragraph, as content_of and the desk's editor write an empty line.
_EMPTY_LINE = re.compile(r"(?i)<\s*p\b[^>]*>\s*<\s*br\s*/?\s*>\s*<\s*/\s*p\s*>")
# A wrapper closed right after a paragraph (the editor's <div class="ql-editor">, a list) ends no line of its own.
_WRAPPERS_AFTER = re.compile(r"(?i)(" + _BLOCK_END + r")(?:\s*<\s*/\s*(?:div|ul|ol)\s*>)+")
# Layout whitespace between a paragraph and the next tag is no text.
_LAYOUT = re.compile(r"(?i)(" + _BLOCK_END + r")\s+(?=<)")
_LINE_END = "\x00"


def plain_text(content):
	"""The words of a note's content, read back exactly as content_of wrote them: a line per paragraph (or div, list
	item, heading), an empty paragraph an empty line, a line break within one a new line; the markup gone, the entities
	read, the editor's non-breaking spaces (&nbsp;) plain spaces. Nothing else is trimmed or merged: a client compares
	what it wrote with what it reads back, and a space at the end of a line or a run of empty lines is the person's."""
	text = _EMPTY_LINE.sub("<p></p>", content or "")
	text = _LAYOUT.sub(r"\1", _WRAPPERS_AFTER.sub(r"\1", text))
	text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
	text = re.sub("(?i)" + _BLOCK_END, _LINE_END, text.replace(_LINE_END, ""))
	text = html.unescape(re.sub(r"(?i)&nbsp;|&#160;|&#x0*a0;", " ", strip_html(text)))
	lines = text.split(_LINE_END)
	if len(lines) > 1 and not lines[-1]:
		lines.pop()
	return "\n".join(lines)


def content_of(text):
	"""A note's content for plain text, as the desk's editor writes it: a paragraph per line, an empty line kept."""
	lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
	return "".join(f"<p>{html.escape(line) or '<br>'}</p>" for line in lines) if text else ""


def _rich_markup(content):
	"""Whether a note's content has more than paragraphs and line breaks (formatting, lists, pictures, links)."""
	for closing, tag, rest in _TAG.findall(content or ""):
		tag = tag.lower()
		if tag not in _PLAIN_TAGS:
			return True
		if (
			tag == "div"
			and not closing
			and rest.strip()
			and not re.fullmatch(r'\s*class="ql-editor[^"]*"\s*', rest)
		):
			return True
		if tag == "p" and not closing and rest.strip():
			return True
	return False


def _children_of(names):
	"""The notes among `names` that have children (a checklist item, an attachment, a drawing)."""
	if not names:
		return set()
	having = set()
	for child in CHILDREN:
		having.update(
			frappe.get_all(
				child,
				filters={"parent": ["in", list(names)], "parenttype": NOTE_DOCTYPE},
				pluck="parent",
				distinct=True,
			)
		)
	return having


def _writable_by_share(names):
	"""The notes among `names` shared with the person for writing."""
	if not names:
		return set()
	return set(
		frappe.get_all(
			"DocShare",
			filters={
				"share_doctype": NOTE_DOCTYPE,
				"share_name": ["in", list(names)],
				"user": frappe.session.user,
				"write": 1,
			},
			pluck="share_name",
		)
	)


def _owner_names(owners):
	return {owner: frappe.db.get_value("User", owner, "full_name") or owner for owner in set(owners) if owner}


def _notes(rows, wanted=None):
	"""The notes (as this facade writes them) of `rows`."""
	names = [row.name for row in rows]
	with_children = _children_of(names)
	shared_writable = _writable_by_share(names)
	owner_names = _owner_names(row.owner for row in rows)
	user = frappe.session.user
	out = []
	for row in rows:
		own = row.owner == user
		rich = row.name in with_children or bool(row.audio_file) or _rich_markup(row.content)
		writes = own or row.name in shared_writable
		note = {
			"id": row.name,
			"title": row.title or "",
			"text": plain_text(row.content),
			"isRich": rich,
			"isPinned": bool(cint(row.pinned)),
			"isArchived": bool(cint(row.archived)),
			"category": row.category or None,
			"created": jmap.utc_of(row.creation),
			"updated": jmap.utc_of(row.modified, precise=True),
			"isShared": not own,
			"ownerName": owner_names.get(row.owner, row.owner),
			"myRights": {"mayWrite": writes, "mayWriteText": writes and not rich, "mayDelete": own},
			"webUrl": frappe.utils.get_url("/app/notes?note=" + quote(row.name, safe="")),
		}
		if wanted is not None:
			note = {key: value for key, value in note.items() if key in wanted}
		out.append(note)
	return out


def note_query(args):
	"""The ids of the notes the person sees, as the desk's list orders them (pinned, then the latest changed). The one
	filter is `isArchived` (the desk's two lists); a window of them as RFC 8620 §5.5 says: `position` from the start, or
	from the end when negative; `limit` at most MAX_NOTES, said back when the server set it; `total` when asked."""
	aid = _notes_account(args)
	position = jmap._whole_number(args.get("position"), "position", 0)
	limit = jmap._whole_number(args.get("limit"), "limit")
	if limit is not None and limit < 0:
		raise jmap.JmapError("invalidArguments", "limit")
	if args.get("anchor") is not None:
		raise jmap.JmapError("invalidArguments", "anchor")
	criteria = args.get("filter")
	if criteria is not None and (not isinstance(criteria, dict) or set(criteria) - {"isArchived"}):
		raise jmap.JmapError("unsupportedFilter", "Only isArchived is supported.")
	if args.get("sort") not in (None, []):
		raise jmap.JmapError("unsupportedSort", "The notes come as the desk's list has them.")
	archived = (criteria or {}).get("isArchived")
	ids = [row.name for row in _visible(["name", "modified", "pinned"], archived=archived)]
	total = len(ids)
	if position < 0:
		position = max(0, total + position)
	used = MAX_NOTES if limit is None else min(limit, MAX_NOTES)
	answer = {
		"accountId": aid,
		"queryState": _state(),
		"canCalculateChanges": False,
		"position": position,
		"ids": ids[position : position + used],
	}
	if args.get("calculateTotal"):
		answer["total"] = total
	if limit is None or limit > MAX_NOTES:
		answer["limit"] = used
	return answer


def note_get(args):
	"""The notes asked for that the person sees; the others are not found."""
	aid = _notes_account(args)
	ids = jmap._ids(args)
	if ids is None:
		every = note_query({"accountId": args.get("accountId"), "limit": jmap.MAX_OBJECTS + 1})["ids"]
		if len(every) > jmap.MAX_OBJECTS:
			raise jmap.JmapError("requestTooLarge", "Ask for the notes by id (Note/query).")
		ids = every
	ids = [i for i in ids if isinstance(i, str)]
	properties = args.get("properties")
	if properties is not None and (
		not isinstance(properties, list) or not all(isinstance(p, str) for p in properties)
	):
		raise jmap.JmapError("invalidArguments", "properties")
	rows = _visible(FIELDS, names=ids) if ids else []
	order = {name: n for n, name in enumerate(ids)}
	rows.sort(key=lambda row: order[row.name])
	wanted = set(properties) & PROPERTIES | {"id"} if properties is not None else None
	found = {row.name for row in rows}
	return {
		"accountId": aid,
		"state": _state(),
		"list": _notes(rows, wanted),
		"notFound": [i for i in ids if i not in found],
	}


def note_set(args):
	"""Notes created, changed and deleted as the desk's Notes page does it (see the module's text). Each refusal is said
	for its note, and what a refused note had begun to write is undone (a savepoint per note)."""
	aid = _notes_account(args)
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
	for key, note in creates.items():
		outcome = _one_note(lambda note=note: _create(note))
		if isinstance(outcome, str):
			# Everything the server set of it: its title from its first line, its rights, its address in the desk…
			made = _notes(_visible(FIELDS, names=[outcome]))
			created[key] = made[0] if made else {"id": outcome}
		else:
			not_created[key] = outcome
	for name, patch in updates.items():
		outcome = _one_note(lambda name=name, patch=patch: _update(name, patch))
		if isinstance(outcome, dict):
			not_updated[name] = outcome
		else:
			changed = _notes(
				_visible(FIELDS, names=[name]), {"updated", "title", "text", "isRich", "myRights"}
			)
			updated[name] = changed[0] if changed else None
	destroyed, not_destroyed = [], {}
	for name in destroys:
		if not isinstance(name, str):
			continue
		outcome = _one_note(lambda name=name: _destroy(name))
		if isinstance(outcome, dict):
			not_destroyed[name] = outcome
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


SAVEPOINT = "mailcraft_note"


class _Stale(Exception):
	"""A change made from a version of the note older than the one it now has."""


def _one_note(write):
	"""Runs the write of one note: its answer, or its SetError (a dict) after undoing what it had begun."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		return write() or True
	except Exception as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		return _refusal(e)


def _refusal(error):
	"""A JMAP SetError for what stopped a note."""
	if isinstance(error, _Stale):
		return {"type": "stateMismatch", "description": _("The note was changed elsewhere: read it again.")}
	if isinstance(error, frappe.PermissionError):
		return {
			"type": "forbidden",
			"description": strip_html(str(error)).strip()[:200] or _("Not permitted"),
		}
	if isinstance(error, frappe.DoesNotExistError):
		return {"type": "notFound"}
	if isinstance(error, frappe.ValidationError | ValueError | TypeError):
		return {"type": "invalidProperties", "description": strip_html(str(error)).strip()[:200]}
	frappe.log_error("MailCraft notes: a note could not be written", frappe.get_traceback())
	return {"type": "serverFail"}


def _fields(note):
	"""What a note (or a patch of whole properties) gives, for the properties it names: its title, its text, whether it
	is pinned or archived."""
	if not isinstance(note, dict) or set(note) - WRITABLE - IGNORED:
		raise ValueError("Only title, text, isPinned and isArchived can be written.")
	out = {}
	if "title" in note:
		title = str(note["title"] or "").strip()
		if len(title) > MAX_TITLE or "\n" in title:
			raise ValueError(f"A title is one line of {MAX_TITLE} characters at most.")
		out["title"] = title
	if "text" in note:
		text = str(note["text"] or "")
		if len(text) > MAX_TEXT:
			raise ValueError(f"A note holds {MAX_TEXT} characters at most.")
		out["text"] = text
	for given, field in (("isPinned", "pinned"), ("isArchived", "archived")):
		if given in note:
			if not isinstance(note[given], bool):
				raise ValueError(f"{given} is true or false.")
			out[field] = int(note[given])
	return out


def _uid_key(uid):
	return f"mailcraft_note_uid:{frappe.session.user}:" + hashlib.sha256(uid.encode()).hexdigest()


def _made_before(uid):
	"""The note a create with this uid made, when it is still that one: the person's, created when it was."""
	kept = frappe.cache().get_value(_uid_key(uid)) if uid else None
	if not isinstance(kept, dict) or not isinstance(kept.get("name"), str):
		return None
	row = frappe.db.get_value(NOTE_DOCTYPE, kept["name"], ["owner", "creation"], as_dict=True)
	if not row or row.owner != frappe.session.user or str(row.creation) != kept.get("creation"):
		return None
	return kept["name"]


def _create(note):
	"""A new note, as the desk's Notes page makes one (a draft, in the person's language: nothing is sent to the
	assistant). Without a title, its first line is the title."""
	frappe.has_permission(NOTE_DOCTYPE, "create", throw=True)
	fields = _fields(note)
	uid = str(note.get("uid") or "")[:255] if isinstance(note.get("uid"), str) else ""
	made = _made_before(uid)
	if made:
		return made
	text = fields.get("text", "")
	title = fields.get("title") or next((line.strip() for line in text.split("\n") if line.strip()), "")
	language = (frappe.local.lang or "fr")[:2]
	doc = frappe.get_doc(
		{
			"doctype": NOTE_DOCTYPE,
			"title": title[:MAX_TITLE],
			"content": content_of(text),
			"status": "Draft",
			"language": language if language in ("fr", "en", "de", "it", "es") else "fr",
			"pinned": fields.get("pinned", 0),
			"archived": fields.get("archived", 0),
		}
	)
	name = doc.insert().name
	if uid:
		frappe.cache().set_value(
			_uid_key(uid), {"name": name, "creation": str(doc.creation)}, expires_in_sec=UID_SECONDS
		)
	return name


def _seen(name):
	"""The note, when the person sees it (owned or shared with them); one they do not see is not there."""
	if not isinstance(name, str) or not _visible(["name"], names=[name]):
		raise frappe.DoesNotExistError
	return frappe.db.get_value(NOTE_DOCTYPE, name, FIELDS, as_dict=True)


def _update(name, patch):
	"""A note changed by the desk's own functions (notes_api): the owner or a colleague it is shared with for writing.
	A patch that gives the `updated` the client read is refused when the note has changed since (the phone, the desk,
	the assistant): the client reads it again rather than write over it."""
	from neoffice_theme import notes_api

	row = _seen(name)
	if isinstance(patch, dict) and any("/" in key for key in patch):
		raise ValueError("A whole property replaces it: no patch of a part.")
	fields = _fields(patch)
	read = patch.get("updated") if isinstance(patch, dict) else None
	if read is not None:
		said = jmap.moment_of(read)
		if said is None:
			raise ValueError("updated is a date.")
		if said != jmap.moment_of(jmap.utc_of(row.modified, precise=True)):
			raise _Stale
	# Only what differs is written: a whole note sent back changes nothing it does not change.
	title = fields["title"] if "title" in fields and fields["title"] != (row.title or "") else None
	text = fields["text"] if "text" in fields and fields["text"] != plain_text(row.content) else None
	if text is not None and _notes([row])[0]["isRich"]:
		raise frappe.PermissionError(_("This note is changed in Neoffice's Notes: open it there."))
	if title is not None or text is not None:
		# A title alone leaves a rich note's content and children as they are.
		notes_api.update_note(name, title=title, content=content_of(text) if text is not None else None)
	if "pinned" in fields and fields["pinned"] != cint(row.pinned):
		notes_api.set_note_pinned(name, fields["pinned"])
	if "archived" in fields and fields["archived"] != cint(row.archived):
		notes_api.set_note_archived(name, fields["archived"])


def _destroy(name):
	"""Deletes a note as the desk does, its owner only (a System Manager a note is shared with for reading is no owner,
	whatever the DocType lets them), a copy kept in the Deleted Documents."""
	row = _seen(name)
	if row.owner != frappe.session.user:
		raise frappe.PermissionError(_("Only its owner deletes a note."))
	frappe.delete_doc(NOTE_DOCTYPE, name)


def no_changes(args):
	"""The changes since a state are not kept: the client reads the notes again (RFC 8620 §5.2)."""
	_notes_account(args)
	raise jmap.JmapError("cannotCalculateChanges", "Read the notes again.")


METHODS = {
	"Note/get": note_get,
	"Note/query": note_query,
	"Note/queryChanges": no_changes,
	"Note/changes": no_changes,
	"Note/set": note_set,
}
