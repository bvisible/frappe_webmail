# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What the desk's menu does to a folder of NeoMail's, on its right-click (29.10).

NeoMail makes, renames and deletes no folder of a JMAP mailbox yet (its engine refuses: « A JMAP account's folders are
its server's », and the facade's Mailbox/set refuses too), and the webmail that did it now leads to NeoMail: the desk's
people had nowhere left to make a folder. The desk's page (page/neomail, public/js/neomail_host.js `folderActions`)
asks this, which does it on the mailbox's IMAP server with the webmail's own functions; NeoMail shows it when it reads
the folders again (the page has it do so at once).

The mailbox is named as NeoMail's state names it, by its address, and the folder by NeoMail's id of it (the facade's
`mailbox_id`). A mailbox of the person's own only: one shared with them is set up by its owner. A special folder (the
Inbox, Sent, Drafts, Trash, Junk and Archive, as the facade gives NeoMail their roles) keeps its name and its place, and
only Trash and Junk are emptied.
"""

import frappe
from frappe import _

from frappe_webmail import webmail_api as webmail
from frappe_webmail.mailcraft_jmap import _folder_of, mailbox_id

ACTIONS = ("create", "rename", "delete", "empty", "read")
# The roles of the folders that are emptied, for good (the webmail's names of them)
EMPTIED = ("trash", "spam")
# The longest name a folder is given here
MAX_NAME = 200


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
