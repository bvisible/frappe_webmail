# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The Neoffice documents a message can carry as a PDF (an invoice, a quotation, an order, a delivery note).

Both screens of the mail offer them in « Joindre un document Neoffice »: by kind, the documents of the people the
message is written to first (found through their contacts), then the most recent, each with its party, amount and
date; only what the person may read. The PDF itself is generate_document_pdf (webmail_api).
"""

import json

import frappe
from frappe import _

# What the picker calls a kind, and the doctypes behind it
KINDS = {
	"invoice": ("Sales Invoice", "Purchase Invoice"),
	"quotation": ("Quotation", "Supplier Quotation"),
	"order": ("Sales Order", "Purchase Order"),
	"delivery": ("Delivery Note",),
}

# Each doctype's party, the party's name and the document's date
_FIELDS = {
	"Sales Invoice": ("Customer", "customer", "customer_name", "posting_date"),
	"Purchase Invoice": ("Supplier", "supplier", "supplier_name", "posting_date"),
	"Quotation": ("Customer", "party_name", "customer_name", "transaction_date"),
	"Supplier Quotation": ("Supplier", "supplier", "supplier_name", "transaction_date"),
	"Sales Order": ("Customer", "customer", "customer_name", "transaction_date"),
	"Purchase Order": ("Supplier", "supplier", "supplier_name", "transaction_date"),
	"Delivery Note": ("Customer", "customer", "customer_name", "posting_date"),
}

MAX_ROWS = 50


def _addresses(emails) -> list[str]:
	"""The addresses written to, from a JSON list or a comma-separated text, in lower case."""
	if not emails:
		return []
	if isinstance(emails, str):
		text = emails.strip()
		emails = json.loads(text) if text.startswith("[") else text.split(",")
	return sorted({str(e).strip().lower() for e in emails if str(e).strip()})


def parties_of(emails) -> set[tuple[str, str]]:
	"""The customers and suppliers behind these addresses: through their contacts, or their own address."""
	addresses = _addresses(emails)
	if not addresses:
		return set()
	found: set[tuple[str, str]] = set()
	contacts = frappe.get_all("Contact Email", filters={"email_id": ["in", addresses]}, pluck="parent")
	if contacts:
		for link in frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Contact",
				"parent": ["in", list(set(contacts))],
				"link_doctype": ["in", ["Customer", "Supplier"]],
			},
			fields=["link_doctype", "link_name"],
		):
			found.add((link.link_doctype, link.link_name))
	for doctype in ("Customer", "Supplier"):
		if frappe.get_meta(doctype).has_field("email_id"):
			for name in frappe.get_all(doctype, filters={"email_id": ["in", addresses]}, pluck="name"):
				found.add((doctype, name))
	return found


def _row(doctype: str, kind: str, doc, linked: bool) -> dict:
	_party_doctype, party_field, name_field, date_field = _FIELDS[doctype]
	when = doc.get(date_field)
	return {
		"doctype": doctype,
		"kind": kind,
		"label": _(doctype),
		"name": doc.name,
		"party": doc.get(name_field) or doc.get(party_field) or "",
		"amount": doc.get("grand_total"),
		"currency": doc.get("currency"),
		"date": when.isoformat() if hasattr(when, "isoformat") else (str(when) if when else None),
		"linked": linked,
	}


@frappe.whitelist()
def list_attachable_documents(search=None, kind=None, emails=None, limit=20):
	"""The documents a message can carry, newest first, those of the people written to (`emails`) before the others.

	`kind`: invoice, quotation, order or delivery (every kind when absent); `search`: words of the document's name, its
	party or its title. Cancelled documents are left out; a doctype the person may not read is skipped.
	"""
	kinds = [kind] if kind in KINDS else list(KINDS)
	limit = max(1, min(int(limit or 20), MAX_ROWS))
	words = (search or "").strip()
	parties = parties_of(emails)

	linked_rows: list[dict] = []
	other_rows: list[dict] = []
	for each in kinds:
		for doctype in KINDS[each]:
			if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
				continue
			party_doctype, party_field, name_field, date_field = _FIELDS[doctype]
			meta = frappe.get_meta(doctype)
			fields = ["name", party_field, name_field, "grand_total", "currency", date_field, "modified"]
			fields = [f for f in fields if f in ("name", "modified") or meta.has_field(f)]
			or_filters = None
			if words:
				like = f"%{words}%"
				or_filters = [[doctype, "name", "like", like], [doctype, name_field, "like", like]]
				if meta.has_field("title"):
					or_filters.append([doctype, "title", "like", like])

			def fetch(extra, doctype=doctype, fields=fields, or_filters=or_filters, date_field=date_field):
				return frappe.get_list(
					doctype,
					filters={"docstatus": ["<", 2], **extra},
					or_filters=or_filters,
					fields=fields,
					order_by=f"{date_field} desc, modified desc",
					limit_page_length=limit,
				)

			theirs = [name for (dt, name) in parties if dt == party_doctype]
			seen: set[str] = set()
			if theirs:
				for doc in fetch({party_field: ["in", theirs]}):
					seen.add(doc.name)
					linked_rows.append(_row(doctype, each, doc, True))
			for doc in fetch({}):
				if doc.name not in seen:
					other_rows.append(_row(doctype, each, doc, False))

	def newest(rows):
		return sorted(rows, key=lambda r: r["date"] or "", reverse=True)

	return (newest(linked_rows) + newest(other_rows))[:limit]
