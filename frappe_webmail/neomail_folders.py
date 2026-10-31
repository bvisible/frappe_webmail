# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What is done to a folder of NeoMail's: on the right-click of the desk's menu (29.10), and from NeoMail itself (31.10).

The desk's page (page/neomail, public/js/neomail_host.js `folderActions`) asks `act`, which does it on the mailbox's IMAP
server with the webmail's own functions; NeoMail shows it when it reads the folders again (the page has it do so at
once). NeoMail itself (its folder pane and its Folder tab, in the desk and in Neodesk) makes, renames, moves and deletes
folders with JMAP's `Mailbox/set` (`mailbox_set`, a method of the facade, mailcraft_jmap), under the same rules.

The mailbox is named as NeoMail's state names it, by its address, and the folder by NeoMail's id of it (the facade's
`mailbox_id`). A mailbox of the person's own only: one shared with them is set up by its owner. A special folder (the
Inbox, Sent, Drafts, Trash, Junk and Archive, as the facade gives NeoMail their roles) keeps its name and its place, and
only Trash and Junk are emptied.
"""

import frappe
from frappe import _

from frappe_webmail import webmail_api as webmail
from frappe_webmail.mailcraft_jmap import (
	MAX_OBJECTS,
	JmapError,
	_account_of,
	_folder_of,
	account_id,
	mailbox_id,
)

ACTIONS = ("create", "rename", "delete", "empty", "read")
# The roles of the folders that are emptied, for good (the webmail's names of them)
EMPTIED = ("trash", "spam")
# The longest name a folder is given here
MAX_NAME = 200
# What a Mailbox/set changes of a folder: its name and its parent; what it lets be (answered, not applied)
CHANGED = ("name", "parentId")
LET_BE = ("isSubscribed", "sortOrder")


@frappe.whitelist(methods=["POST"])
def act(account, mailbox, action, name=None):
	"""Do `action` to the folder `mailbox` (NeoMail's id of it) of the person's mailbox `account` (its address):
	`create` a folder `name` in it, `rename` it `name` in its place, `delete` it, `empty` it, mark all of it `read`.
	Returns NeoMail's id of the folder made or renamed, else of the folder acted on."""
	from frappe_webmail.www.neomail import desk_people_only

	desk_people_only()
	if action not in ACTIONS:
		frappe.throw(_("Unknown folder action."))
	own = _own(account)
	folder = _folder_of(mailbox)
	listed = webmail.get_folders(own.name)
	if not folder or folder not in {f["name"] for f in listed}:
		frappe.throw(_("That mailbox has no such folder."))
	roles = _roles(own, listed)
	delimiter = next((f.get("delimiter") for f in listed if f["name"] == folder), None) or "/"
	if action in ("create", "rename"):
		name = (name or "").strip()
		if not name or len(name) > MAX_NAME or delimiter in name:
			frappe.throw(_("Give the folder a name, without « {0} ».").format(delimiter))
	if action in ("rename", "delete") and folder in roles:
		frappe.throw(_("A special folder keeps its name and its place."))
	if action == "create":
		made = webmail.create_folder(own.name, name, parent_folder=folder)
		return {"mailbox": mailbox_id(made["folder"])}
	if action == "rename":
		parent, sep, _leaf = folder.rpartition(delimiter)
		renamed = f"{parent}{sep}{name}"
		webmail.rename_folder(own.name, folder, renamed)
		return {"mailbox": mailbox_id(renamed)}
	if action == "delete":
		webmail.delete_folder(own.name, folder)
	elif action == "empty":
		if roles.get(folder) not in EMPTIED:
			frappe.throw(_("Only Trash and Junk Email are emptied."))
		with webmail.imap_session(own) as client:
			client.select_folder(folder)
			uids = client.search(["ALL"])
			if uids:
				client.add_flags(uids, [b"\\Deleted"])
				client.expunge()
	else:
		webmail.mark_folder_read(own.name, folder)
	return {"mailbox": mailbox}


def _own(address):
	"""The person's own Webmail Account of `address`: one shared with them is set up by its owner."""
	address = (address or "").strip().lower()
	for row in webmail.get_accounts() or []:
		if (row.get("email") or "").strip().lower() != address:
			continue
		if row.get("is_shared"):
			frappe.throw(_("A mailbox shared with you is set up by its owner."), frappe.PermissionError)
		return webmail.get_account(row["name"])
	frappe.throw(_("That mailbox isn't one of yours."), frappe.PermissionError)


def _roles(account, listed):
	"""{folder: role} of the mailbox's special folders, as the facade gives NeoMail their roles (mailbox_get): the
	account's own folder settings, else what the server marks, the Inbox at least."""
	found = webmail.special_folders((f.get("flags") or (), f.get("delimiter"), f["name"]) for f in listed)
	effective = webmail.effective_folders(webmail.configured_folders(account), found)
	return {folder: role for role, folder in effective.items() if folder}


# ---------------------------------------------------------------------------------------------------------------
# Mailbox/set
# ---------------------------------------------------------------------------------------------------------------


class _Refused(Exception):
	"""What one object of a Mailbox/set comes to when it isn't done: a SetError (RFC 8620 §5.3)."""

	def __init__(self, type_, description):
		super().__init__(description)
		self.answer = {"type": type_, "description": description}


def mailbox_set(args):
	"""Mailbox/set (RFC 8621 §2.5): NeoMail makes, renames, moves and deletes the folders of the person's own mailbox on
	its IMAP server, under `act`'s rules (a mailbox shared with them is set up by its owner, a special folder keeps its
	name and its place, a name holds no separator). The creations first, then the updates, then the destructions (RFC
	8620 §5.3); a folder made by the same call is named in a `parentId` by `#` and its creation id.

	A mailbox id names the folder's place (`mailbox_id` of its path): a folder renamed or moved has another id, which
	`updated` names (`{old: {"id": new}}`, as Email/set names a moved email's), and so have the folders in it. A folder is
	destroyed with the folders in it and their mail (as NeoMail asks, `onDestroyRemoveEmails`), where a JMAP server would
	refuse it (`mailboxHasChild`): NeoMail deletes a folder as Outlook does, the folders in it along."""
	address = _account_of(args.get("accountId"))
	if not address:
		raise JmapError("accountNotFound", str(args.get("accountId"))[:200])
	try:
		own = _own(address)
	except frappe.PermissionError as e:
		raise JmapError("forbidden", str(e)) from None
	create, update, destroy = args.get("create") or {}, args.get("update") or {}, args.get("destroy") or []
	if not isinstance(create, dict) or not isinstance(update, dict) or not isinstance(destroy, list):
		raise JmapError("invalidArguments", "create and update are objects, destroy is a list")
	if len(create) + len(update) + len(destroy) > MAX_OBJECTS:
		raise JmapError("requestTooLarge", "maxObjectsInSet")
	listed = webmail.get_folders(own.name)
	roles = _roles(own, listed)
	delimiter = next((f.get("delimiter") for f in listed if f.get("delimiter")), None) or "/"
	names = {f["name"] for f in listed}
	out = {
		"accountId": account_id(own.name),
		"oldState": "0",
		"newState": "0",
		"created": {},
		"notCreated": {},
		"updated": {},
		"notUpdated": {},
		"destroyed": [],
		"notDestroyed": {},
	}
	# The folders this call made, by their creation ids
	made = {}
	with webmail.imap_session(own) as client:
		for cid, mailbox in create.items():
			try:
				made[cid] = _create(client, mailbox, names, made, delimiter)
				out["created"][cid] = {"id": mailbox_id(made[cid])}
			except _Refused as e:
				out["notCreated"][cid] = e.answer
		for mid, patch in update.items():
			try:
				now = _update(client, mid, patch, names, made, roles, delimiter)
				out["updated"][mid] = None if now == _folder_of(mid) else {"id": mailbox_id(now)}
			except _Refused as e:
				out["notUpdated"][mid] = e.answer
		for mid in dict.fromkeys(i for i in destroy if isinstance(i, str)):
			try:
				_destroy(client, mid, names, roles, delimiter, bool(args.get("onDestroyRemoveEmails")))
				out["destroyed"].append(mid)
			except _Refused as e:
				out["notDestroyed"][mid] = e.answer
	return out


def _name(value, delimiter):
	"""A folder's name as given, trimmed; refused when there is none, it is too long, or it holds the separator."""
	name = value.strip() if isinstance(value, str) else ""
	if not name or len(name) > MAX_NAME or delimiter in name:
		raise _Refused("invalidProperties", f"A folder needs a name, without « {delimiter} ».")
	return name


def _parent(value, names, made):
	"""The path of the folder a `parentId` names ("" for the top), a folder made by this call by its creation id."""
	if value is None:
		return ""
	if isinstance(value, str) and value.startswith("#") and value[1:] in made:
		return made[value[1:]]
	folder = _folder_of(value)
	if folder not in names:
		raise _Refused("invalidProperties", "There is no such parent folder.")
	return folder


def _imap(action, *args):
	"""An IMAP command on a folder; the server's refusal (NO, BAD) is the object's, a lost connection the call's."""
	import imaplib

	try:
		return action(*args)
	except imaplib.IMAP4.abort:
		raise
	except imaplib.IMAP4.error as e:
		raise _Refused("forbidden", str(e)[:200]) from None


def _create(client, mailbox, names, made, delimiter):
	if not isinstance(mailbox, dict) or set(mailbox) - set(CHANGED) - set(LET_BE):
		raise _Refused("invalidProperties", "A folder is made with a name and a parent.")
	name = _name(mailbox.get("name"), delimiter)
	parent = _parent(mailbox.get("parentId"), names, made)
	path = f"{parent}{delimiter}{name}" if parent else name
	if path in names:
		raise _Refused("invalidProperties", "A folder of that name is there already.")
	_imap(client.create_folder, path)
	try:
		client.subscribe_folder(path)
	except Exception:
		# (A server that keeps no subscriptions lists the folder all the same)
		pass
	names.add(path)
	return path


def _update(client, mid, patch, names, made, roles, delimiter):
	"""Rename or move the folder `mid` as `patch` says; returns its path now."""
	folder = _folder_of(mid)
	if folder not in names:
		raise _Refused("notFound", "There is no such folder.")
	if not isinstance(patch, dict) or set(patch) - set(CHANGED) - set(LET_BE):
		raise _Refused("invalidProperties", "A folder's name and parent are changed, nothing else.")
	if not set(patch) & set(CHANGED):
		return folder
	if folder in roles:
		raise _Refused("forbidden", "A special folder keeps its name and its place.")
	parent, _sep, leaf = folder.rpartition(delimiter)
	leaf = _name(patch["name"], delimiter) if "name" in patch else leaf
	parent = _parent(patch["parentId"], names, made) if "parentId" in patch else parent
	if parent == folder or parent.startswith(folder + delimiter):
		raise _Refused("invalidProperties", "A folder can't go inside itself.")
	now = f"{parent}{delimiter}{leaf}" if parent else leaf
	if now == folder:
		return folder
	if now in names:
		raise _Refused("invalidProperties", "A folder of that name is there already.")
	_imap(client.rename_folder, folder, now)
	# The folders in it went with it (IMAP RENAME, RFC 3501 §6.3.5)
	moved = {n for n in names if n == folder or n.startswith(folder + delimiter)}
	names.difference_update(moved)
	names.update(now + n[len(folder) :] for n in moved)
	return now


def _destroy(client, mid, names, roles, delimiter, with_mail):
	folder = _folder_of(mid)
	if folder not in names:
		raise _Refused("notFound", "There is no such folder.")
	if folder in roles:
		raise _Refused("forbidden", "A special folder keeps its name and its place.")
	inside = sorted((n for n in names if n.startswith(folder + delimiter)), key=len, reverse=True)
	if not with_mail:
		for n in [*inside, folder]:
			try:
				count = client.folder_status(n, ["MESSAGES"]).get(b"MESSAGES")
			except Exception:
				count = 0
			if count:
				raise _Refused("mailboxHasEmail", "The folder holds mail.")
	# The folders in it first, the deepest first: IMAP deletes one folder at a time
	for n in [*inside, folder]:
		_imap(client.delete_folder, n)
		try:
			client.unsubscribe_folder(n)
		except Exception:
			pass
		names.discard(n)


METHODS = {"Mailbox/set": mailbox_set}
