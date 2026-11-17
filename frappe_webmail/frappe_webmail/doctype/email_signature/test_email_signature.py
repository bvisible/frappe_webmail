# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from frappe_webmail.frappe_webmail.doctype.email_signature.email_signature import (
	get_permission_query_conditions,
)


class TestEmailSignature(FrappeTestCase):
	def test_the_list_shows_a_person_only_their_own_signatures(self):
		condition = get_permission_query_conditions("someone@example.com")
		self.assertIn("`tabEmail Signature`.`user`", condition)
		self.assertIn("someone@example.com", condition)

	def test_administrator_lists_every_signature(self):
		self.assertEqual(get_permission_query_conditions("Administrator"), "")
