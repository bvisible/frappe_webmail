# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The Neoffice documents a message can carry as a PDF: listed by kind, those of the people written to first, and the
PDF named after its document, printed in the language asked for (« Joindre un document Neoffice », 14.10.2026).

Run on a copy of a real site (its invoices, its contacts):
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_documents
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail.documents import KINDS, list_attachable_documents, parties_of
from frappe_webmail.webmail_api import generate_document_pdf

PREFIX = "zz-webmail-docs"


def an_invoice(oldest=False):
	"""A Sales Invoice of the site, not cancelled, with its customer (None on a site without one). The oldest one when
	asked: newer invoices of other customers then exist, so that coming first proves the ordering."""
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": ["<", 2], "customer": ["is", "set"]},
		fields=["name", "customer"],
		order_by="posting_date asc" if oldest else "posting_date desc",
		limit=1,
	)
	return rows[0] if rows else None


class TestAttachableDocuments(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.contacts = []

	def tearDown(self):
		for name in self.contacts:
			frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def a_contact_of(self, customer):
		"""A contact of `customer` with an address of its own, deleted after the test."""
		email = f"{PREFIX}-{frappe.generate_hash(length=8)}@example.com"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": PREFIX,
				"email_ids": [{"email_id": email, "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert(ignore_permissions=True)
		self.contacts.append(contact.name)
		return email

	def test_a_kind_lists_its_doctypes_with_party_amount_and_date_newest_first(self):
		rows = list_attachable_documents(kind="invoice", limit=8)
		if not rows:
			self.skipTest("no invoice on this site")
		self.assertTrue({r["doctype"] for r in rows} <= set(KINDS["invoice"]))
		for row in rows:
			self.assertEqual(
				set(row),
				{"doctype", "kind", "label", "name", "party", "amount", "currency", "date", "linked"},
			)
			self.assertEqual(row["kind"], "invoice")
		dates = [r["date"] or "" for r in rows if not r["linked"]]
		self.assertEqual(dates, sorted(dates, reverse=True))

	def test_the_documents_of_the_people_written_to_come_first(self):
		invoice = an_invoice(oldest=True)
		if not invoice:
			self.skipTest("no invoice with a customer on this site")
		email = self.a_contact_of(invoice.customer)
		self.assertIn(("Customer", invoice.customer), parties_of([email.upper()]))
		rows = list_attachable_documents(kind="invoice", emails=frappe.as_json([email]), limit=10)
		self.assertTrue(rows[0]["linked"])
		linked = [r for r in rows if r["linked"]]
		self.assertTrue(all(r["doctype"] == "Sales Invoice" for r in linked))
		self.assertIn(invoice.name, [r["name"] for r in linked])
		# Once linked, never listed again among the others
		self.assertEqual(len({r["name"] for r in rows}), len(rows))

	def test_words_find_a_document_by_its_name(self):
		invoice = an_invoice()
		if not invoice:
			self.skipTest("no invoice on this site")
		rows = list_attachable_documents(search=invoice.name, kind="invoice")
		self.assertIn(invoice.name, [r["name"] for r in rows])

	def test_no_kind_means_every_kind_and_cancelled_documents_never_show(self):
		rows = list_attachable_documents(limit=50)
		self.assertTrue({r["kind"] for r in rows} <= set(KINDS))
		for row in rows:
			self.assertLess(frappe.db.get_value(row["doctype"], row["name"], "docstatus"), 2)


class TestWhoMaySeeThem(FrappeTestCase):
	"""A person without access to a doctype gets none of its documents, and cannot print one (a portal user, say)."""

	def setUp(self):
		self.email = f"{PREFIX}-{frappe.generate_hash(length=8)}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": self.email, "first_name": PREFIX, "user_type": "Website User"}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("User", self.email, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_a_user_without_access_gets_no_document_and_no_pdf(self):
		invoice = an_invoice()
		frappe.set_user(self.email)
		self.assertEqual(list_attachable_documents(limit=50), [])
		if invoice:
			with self.assertRaises(frappe.ValidationError):
				generate_document_pdf("Sales Invoice", invoice.name)


class TestDocumentPdf(FrappeTestCase):
	def test_the_pdf_is_named_after_its_document_and_printed_in_the_language_asked(self):
		invoice = an_invoice()
		if not invoice:
			self.skipTest("no invoice on this site")
		seen = {}

		def fake_print(*args, **kwargs):
			seen["lang"] = frappe.local.lang
			return "<p>facture</p>"

		with (
			patch("frappe.get_print", side_effect=fake_print),
			patch("frappe.utils.pdf.get_pdf", return_value=b"%PDF-1.4 test"),
		):
			pdf = generate_document_pdf("Sales Invoice", invoice.name, language="de")
		self.assertEqual(seen["lang"], "de")
		self.assertEqual(pdf["filename"], f"{invoice.name}.pdf".replace("/", "-"))
		self.assertEqual((pdf["doctype"], pdf["docname"]), ("Sales Invoice", invoice.name))
