# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The card under a message's sender (get_sender_card) and the contact it is read from (get_contact_by_email): the
supplier or the customer a sender is, its invoices of the year, and nothing for whom may not read them.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_sender_card
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api
from frappe_webmail.webmail_api import get_contact_by_email, get_sender_card

SENDER = "test-sender-card@supplier.example.com"
LONER = "test-sender-card-alone@example.com"
PORTAL = "test-sender-card-portal@example.com"
SUPPLIER_NAME = "_Test Sender Card Supplier"


def _contact(email, links=()):
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": email.split("@")[0],
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"links": [{"link_doctype": doctype, "link_name": name} for doctype, name in links],
		}
	)
	contact.insert(ignore_permissions=True)
	return contact.name


class TestSenderCard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": SUPPLIER_NAME,
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			}
		)
		supplier.insert(ignore_permissions=True)
		cls.supplier = supplier.name
		cls.contacts = [_contact(SENDER, [("Supplier", cls.supplier)]), _contact(LONER)]
		if not frappe.db.exists("User", PORTAL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": PORTAL,
					"first_name": "Portal",
					"send_welcome_email": 0,
					"user_type": "Website User",
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in cls.contacts:
			frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
		frappe.delete_doc("Supplier", cls.supplier, force=True, ignore_permissions=True)
		frappe.delete_doc("User", PORTAL, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_supplier_s_contact_shows_the_supplier_and_its_invoices_of_the_year(self):
		card = get_sender_card(SENDER)
		self.assertEqual(card["doctype"], "Supplier")
		self.assertEqual(card["name"], self.supplier)
		self.assertEqual(card["title"], SUPPLIER_NAME)
		self.assertEqual(card["kind"], frappe._("Supplier"))
		self.assertIn("/app/supplier/", card["url"])
		self.assertEqual(card["invoices"], 0)

	def test_the_invoices_counted_are_the_supplier_s_submitted_ones_since_new_year(self):
		with patch.object(webmail_api.frappe, "get_list", return_value=["PINV-1", "PINV-2"]) as get_list:
			card = get_sender_card(SENDER)
		self.assertEqual(card["invoices"], 2)
		doctype = get_list.call_args.args[0]
		filters = get_list.call_args.kwargs["filters"]
		self.assertEqual(doctype, "Purchase Invoice")
		self.assertEqual(filters["supplier"], self.supplier)
		self.assertEqual(filters["docstatus"], 1)
		self.assertEqual(filters["posting_date"][0], ">=")
		self.assertEqual((filters["posting_date"][1].month, filters["posting_date"][1].day), (1, 1))

	def test_no_count_for_whom_may_not_read_invoices(self):
		real = frappe.has_permission

		def no_invoices(doctype, *args, **kwargs):
			return False if doctype == "Purchase Invoice" else real(doctype, *args, **kwargs)

		with patch.object(webmail_api.frappe, "has_permission", side_effect=no_invoices):
			card = get_sender_card(SENDER)
		self.assertEqual(card["doctype"], "Supplier")
		self.assertIsNone(card["invoices"])

	def test_a_sender_with_no_record_or_no_contact_has_no_card(self):
		self.assertIsNone(get_sender_card(LONER))
		self.assertIsNone(get_sender_card("nobody-sender-card@example.com"))
		self.assertIsNone(get_sender_card(""))

	def test_a_portal_client_reads_no_contact_and_no_card(self):
		frappe.set_user(PORTAL)
		self.assertIsNone(get_contact_by_email(SENDER))
		self.assertIsNone(get_sender_card(SENDER))

	def test_the_contact_is_still_given_to_whom_may_read_it(self):
		contact = get_contact_by_email(SENDER)
		self.assertEqual(contact["primary_email"], SENDER)
		self.assertEqual(contact["links"][0]["link_name"], self.supplier)
