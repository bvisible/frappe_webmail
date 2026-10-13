# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What a person can do with an e-mail attachment, for every screen that shows the mail.

The desk's webmail (Vue, /app/webmail) and Neodesk (the app's shared code) are two screens on one base, the server:
every action on an attachment is written and tested once, here. `get_attachment_actions` describes them (key, label,
icon, kind) so that both screens draw the same menu with the same words, and a new action of a kind they already
play needs no screen code:

- "client": the screen does it itself (preview, save as, forward);
- "now": one call, then a toast (create a scanned document);
- "pick_folder": the screen asks for a Drive folder first (`get_drive_folders`), then calls;
- "pick_document": the screen asks for a Neoffice document first (`get_attachable_doctypes`, then the webmail's
  `search_documents` / `get_recent_documents`), then calls.

The attachment is always read again from the IMAP server, on the server (`webmail_api.read_attachment`): its bytes
never travel through the browser, reading it never marks the message as read, and `get_account` checks the person's
right to the mailbox on every call.
"""

import frappe
from frappe import _

from frappe_webmail.webmail_api import (
	_imap_is_connection_error,
	get_account,
	imap_session,
	read_attachment,
	to_bool,
)

# What a browser may show inline from a stranger's e-mail. Anything else (HTML, SVG, XML…) would run on the
# instance's own origin, with the person's session: it is only ever downloaded, as bytes.
INLINE_SAFE = frozenset(
	("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain")
)


@frappe.whitelist()
def download_attachment(account_name, folder, uid, attachment_id, inline=0):
	"""The attachment itself, streamed (not base64 in JSON): what a preview shows and what « Save as… » saves."""
	account = get_account(account_name)
	filename, content_type, payload = read_attachment(account, folder, uid, attachment_id)

	show = to_bool(inline) and content_type in INLINE_SAFE
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "inline" if show else "attachment"
	frappe.local.response.content_type = content_type if show else "application/octet-stream"
	# frappe.utils.response.as_raw decodes the name with "unicode-escape", which turns « Relevé.pdf » into « RelevÃ©.pdf »:
	# escaping it first gives the decode back the real name, which werkzeug then encodes properly (RFC 6266).
	frappe.local.response.filename = filename.encode("unicode-escape").decode("ascii")
	frappe.local.response.filecontent = payload


@frappe.whitelist()
def get_folder_counts(account_name, folders=None):
	"""Unread and total messages of each folder (IMAP STATUS), for the folder lists of both screens.

	`folders`: a JSON list to count only those (the ones a sidebar shows). A folder the server refuses to count is left
	out; a broken connection is raised, so that the pool drops it.
	"""
	account = get_account(account_name)
	wanted = set(frappe.parse_json(folders)) if folders else None

	counts = {}
	with imap_session(account) as client:
		for flags, _delimiter, name in client.list_folders():
			if b"\\Noselect" in flags or (wanted is not None and name not in wanted):
				continue
			try:
				status = client.folder_status(name, [b"MESSAGES", b"UNSEEN"])
			except Exception as exc:
				if _imap_is_connection_error(exc):
					raise
				continue
			counts[name] = {
				"unseen": int(status.get(b"UNSEEN", 0)),
				"messages": int(status.get(b"MESSAGES", 0)),
			}
	return counts


# Where an attachment is usually filed. Only those the person may write appear (get_attachable_doctypes).
ATTACHABLE_DOCTYPES = (
	"Purchase Invoice",
	"Purchase Order",
	"Supplier Quotation",
	"Supplier",
	"Sales Invoice",
	"Sales Order",
	"Quotation",
	"Customer",
	"Project",
	"Task",
	"Issue",
	"Lead",
	"Opportunity",
	"Employee",
)


@frappe.whitelist()
def get_attachable_doctypes():
	"""The kinds of documents an attachment can be joined to, among those the person may write."""
	return [
		{"doctype": doctype, "label": _(doctype)}
		for doctype in ATTACHABLE_DOCTYPES
		if frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, "write")
	]


@frappe.whitelist()
def attach_to_document(account_name, folder, uid, attachment_id, doctype, docname):
	"""Join the attachment to a Neoffice document, as a private file in its attachments.

	The same right as the desk's « Attach » on that document: writing it.
	"""
	account = get_account(account_name)
	if not frappe.db.exists(doctype, docname):
		frappe.throw(_("{0} {1} not found").format(_(doctype), docname), frappe.DoesNotExistError)
	if not frappe.has_permission(doctype, "write", doc=docname):
		frappe.throw(
			_("You are not allowed to attach a file to {0} {1}").format(_(doctype), docname),
			frappe.PermissionError,
		)

	filename, _content_type, payload = read_attachment(account, folder, uid, attachment_id)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"attached_to_doctype": doctype,
			"attached_to_name": docname,
			"is_private": 1,
			"content": payload,
		}
	).insert()
	return {
		"file": file.name,
		"file_name": file.file_name,
		"doctype": doctype,
		"docname": docname,
		"url": frappe.utils.get_url_to_form(doctype, docname),
	}
