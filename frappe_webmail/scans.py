# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The webmail's door into the scanned documents (neoffice_theme's Document Scan, read by OCR).

The attachment becomes a private File the person owns (under /private/files, which the OCR reads from disk: a Drive
blob on S3 it could not), then a Document Scan through neoffice_theme's own `create_document_scan_from_json`, which
checks the right to create one and to read the file, sets the company and queues the reading. Like the scanners'
intake (nora, scanner_ingest), the same bytes are never scanned twice (their SHA-256, `content_hash`) and the File is
attached to the scan, whose rights it then follows.

Its intake channel is « Upload »: « Email » and « Scanner » notify every desk user, by push, when the reading ends
(neoffice_theme scan_notifications) — that is for a scanner's mailbox, not for one person filing one invoice.

Every import from neoffice_theme is made in this module: a change on its side breaks here, under its tests.
"""

import hashlib
import uuid
from datetime import datetime

import frappe
from frappe import _

CREATE_SCAN = (
	"neoffice_theme.neoffice_theme.doctype.document_scan.document_scan.create_document_scan_from_json"
)
TYPES = (
	"Invoice",
	"Receipt",
	"Expense Claim",
	"Delivery Note",
	"Order Confirmation",
	"Bank Statement",
	"Other",
)


def available() -> bool:
	return "neoffice_theme" in frappe.get_installed_apps() and bool(
		frappe.db.exists("DocType", "Document Scan")
	)


def can_create() -> bool:
	return available() and bool(frappe.has_permission("Document Scan", "create"))


def scan_url(name) -> str:
	return f"/app/document-scan/{name}"


def create(payload: bytes, file_name: str, document_type: str = "Invoice") -> dict:
	"""A Document Scan of `payload`, or the one these bytes already have. Returns {name, duplicate, url}."""
	if not available():
		frappe.throw(_("Scanned documents are not available on this instance"))
	if not frappe.has_permission("Document Scan", "create"):
		frappe.throw(_("You are not allowed to create a scanned document"), frappe.PermissionError)
	if document_type not in TYPES:
		document_type = "Other"

	content_hash = hashlib.sha256(payload).hexdigest()
	existing = frappe.db.get_value("Document Scan", {"content_hash": content_hash}, "name")
	if existing:
		if frappe.has_permission("Document Scan", "read", doc=existing):
			return {"name": existing, "duplicate": True, "url": scan_url(existing)}
		frappe.throw(_("This document is already among the scanned documents"))

	source = frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "is_private": 1, "content": payload}
	).insert()
	result = frappe.get_attr(CREATE_SCAN)(
		{
			"generated_document_name": f"SCAN-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6].upper()}",
			"source_file": source.file_url,
			"file_name": file_name,
			"document_type": document_type,
		}
	)
	if not result or not result.get("success"):
		# It answers a failure instead of raising: the File would stay behind, owned by nobody's scan
		frappe.delete_doc("File", source.name, force=True, ignore_permissions=True)
		frappe.log_error("Webmail: a scanned document could not be created", frappe.as_json(result))
		frappe.throw(_("The scanned document could not be created"))

	name = result["name"]
	frappe.db.set_value(
		"Document Scan",
		name,
		{"content_hash": content_hash, "intake_channel": "Upload"},
		update_modified=False,
	)
	frappe.db.set_value(
		"File",
		source.name,
		{"attached_to_doctype": "Document Scan", "attached_to_name": name},
		update_modified=False,
	)
	return {"name": name, "duplicate": False, "url": scan_url(name)}
