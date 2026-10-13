# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Three methods that answered anyone signed in (#1531): a folder's subfolders listed for any folder id, a contact
relinked with ignore_permissions, an e-mail written into any document's timeline.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_access
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

OUTSIDER = "webmail_outsider@example.com"


class TestAccess(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", OUTSIDER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": OUTSIDER,
					"first_name": "Outsider",
					"send_welcome_email": 0,
					"user_type": "Website User",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_folder_one_may_not_read_is_not_listed(self):
		from frappe_webmail.webmail_api import get_file_manager_files

		with (
			patch("frappe_webmail.webmail_api.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			get_file_manager_files(folder="Users")

	def test_a_contact_is_relinked_only_by_who_may_write_it(self):
		from frappe_webmail.webmail_api import link_contact_to_document

		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Webmail access test"}).insert()
		todo = frappe.get_doc({"doctype": "ToDo", "description": "Webmail access test"}).insert()
		try:
			frappe.set_user(OUTSIDER)
			with self.assertRaises(frappe.PermissionError):
				link_contact_to_document(contact.name, "ToDo", todo.name)
			frappe.set_user("Administrator")
			self.assertEqual(frappe.get_doc("Contact", contact.name).links, [])
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("Contact", contact.name, force=True)
			frappe.delete_doc("ToDo", todo.name, force=True)

	def test_the_timeline_link_is_not_an_open_door(self):
		from frappe_webmail.webmail_api import create_communication_link

		self.assertNotIn(create_communication_link, frappe.whitelisted)
		todo = frappe.get_doc({"doctype": "ToDo", "description": "Webmail access test"}).insert()
		try:
			frappe.set_user(OUTSIDER)
			result = create_communication_link(
				"someone@example.com", "x@example.com", "S", "<p>B</p>", "ToDo", todo.name
			)
			self.assertFalse(result["created"])
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("ToDo", todo.name, force=True)
