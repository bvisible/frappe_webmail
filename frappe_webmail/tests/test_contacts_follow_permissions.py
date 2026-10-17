# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The webmail's contact methods answer with the person's own rights (maintenance#1541).

`search_contacts` and `get_recent_contacts` read every contact (names and addresses) for anyone signed in, a portal
client included, and `create_contact_from_email` inserted with ignore_permissions; an address already known came back
with the name of its contact. They now read through frappe.get_list (rights and user permissions applied), create with
the right to create contacts, and name an existing contact only to someone who may read it. Sites differ in who may
create a contact (the standard rights let every user create their own; the hub's lets the desk's roles only), so the
refusal is checked with that right taken away, and the rest with users whose rights hold everywhere. A contact is
found by any of the rows that carry its address, and a record one may not read (a contact to link, a document to print)
is answered as one that is not there; the file picker and the print formats are the desk's.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_contacts_follow_permissions
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api as webmail

ADDRESSES = (
	"webmail-perm-alpha@example.com",
	"webmail-perm-beta@example.com",
	"webmail-perm-new@example.com",
)
PORTAL = "webmail-perm-portal@example.com"
DESK = "webmail-perm-desk@example.com"  # Sales User: reads and creates contacts
READER = (
	"webmail-perm-reader@example.com"  # Sales User, its contacts restricted to Alpha by a User Permission
)


def _user(email, roles=()):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	for role in roles:
		user.append("roles", {"role": role})
	if not roles:
		user.user_type = "Website User"
	user.insert(ignore_permissions=True)


def _forget(email):
	"""Removes the contacts of a test address (create_contact_from_email commits what it creates)."""
	for name in frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent"):
		frappe.delete_doc("Contact", name, ignore_permissions=True, force=True)


def _contact(first_name, email):
	existing = frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
	if existing:
		return existing
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first_name,
			"last_name": "Webmailperm",
			"email_ids": [{"email_id": email, "is_primary": 1}],
		}
	)
	return contact.insert(ignore_permissions=True).name


class TestContactsFollowPermissions(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.alpha = _contact("Alpha", "webmail-perm-alpha@example.com")
		cls.beta = _contact("Beta", "webmail-perm-beta@example.com")
		_user(PORTAL)
		_user(DESK, ["Sales User"])
		_user(READER, ["Sales User"])
		if not frappe.db.exists("User Permission", {"user": READER, "allow": "Contact"}):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": READER,
					"allow": "Contact",
					"for_value": cls.alpha,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in ADDRESSES:
			_forget(email)
		for name in frappe.get_all("User Permission", filters={"user": READER}, pluck="name"):
			frappe.delete_doc("User Permission", name, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: what the tests committed through create_contact_from_email goes too
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _names(self, found):
		return {contact["name"] for contact in found}

	def test_a_portal_client_finds_no_contact_it_may_not_read(self):
		frappe.set_user(PORTAL)
		self.assertFalse(
			self._names(webmail.search_contacts("webmail-perm")) & {self.alpha, self.beta}, "by address"
		)
		self.assertFalse(
			self._names(webmail.search_contacts("Webmailperm")) & {self.alpha, self.beta}, "by name"
		)
		self.assertFalse(self._names(webmail.get_recent_contacts(50)) & {self.alpha, self.beta})

	def test_the_desk_keeps_its_suggestions_by_name_and_by_address(self):
		frappe.set_user(DESK)
		self.assertEqual(self._names(webmail.search_contacts("webmail-perm-alpha")), {self.alpha})
		self.assertEqual(self._names(webmail.search_contacts("Webmailperm")), {self.alpha, self.beta})
		found = next(c for c in webmail.search_contacts("webmail-perm-beta") if c["name"] == self.beta)
		self.assertEqual(
			(found["email"], found["emails"]),
			("webmail-perm-beta@example.com", ["webmail-perm-beta@example.com"]),
		)
		self.assertTrue({self.alpha, self.beta} <= self._names(webmail.get_recent_contacts(50)))

	def test_a_reader_finds_only_what_its_user_permissions_allow(self):
		frappe.set_user(READER)
		self.assertEqual(self._names(webmail.search_contacts("webmail-perm")), {self.alpha})
		self.assertEqual(self._names(webmail.search_contacts("Webmailperm")), {self.alpha})
		recent = self._names(webmail.get_recent_contacts(50))
		self.assertIn(self.alpha, recent)
		self.assertNotIn(self.beta, recent)

	def test_a_known_address_is_known_only_to_whoever_may_read_its_contact(self):
		"""A contact one may not read is as if it did not exist: « already there » would say which addresses the
		company keeps. The reader restricted to Alpha may not create a contact either, so Beta's address is refused."""
		frappe.set_user(READER)
		self.assertEqual(
			webmail.create_contact_from_email("webmail-perm-alpha@example.com")["contact"], self.alpha
		)
		with self.assertRaises(frappe.PermissionError):
			webmail.create_contact_from_email("webmail-perm-beta@example.com")
		self.assertEqual(
			frappe.get_all(
				"Contact Email", filters={"email_id": "webmail-perm-beta@example.com"}, pluck="parent"
			),
			[self.beta],
			"no second Beta",
		)
		frappe.set_user(DESK)
		skipped = webmail.bulk_create_contacts(
			frappe.as_json(
				[{"email": "webmail-perm-beta@example.com"}, {"email": "webmail-perm-alpha@example.com"}]
			)
		)["skipped"]
		self.assertEqual([s["contact"] for s in skipped], [self.beta, self.alpha])

	def test_the_webmail_is_the_desks(self):
		"""A portal client adds no contact and picks no document through the webmail, whatever the site's rights (the
		standard ones let anyone create a contact of their own)."""
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			webmail.create_contact_from_email("webmail-perm-new@example.com")
		with self.assertRaises(frappe.PermissionError):
			webmail.bulk_create_contacts(frappe.as_json([{"email": "webmail-perm-new@example.com"}]))
		with self.assertRaises(frappe.PermissionError):
			webmail.get_recent_documents("Contact")

	def test_recent_documents_are_those_the_person_may_read(self):
		frappe.set_user(READER)
		recent = {d["value"] for d in webmail.get_recent_documents("Contact", 20)}
		self.assertIn(self.alpha, recent)
		self.assertNotIn(self.beta, recent, "outside the reader's user permissions")

	def test_creating_takes_the_right_to_create_contacts(self):
		email = "webmail-perm-new@example.com"
		_forget(email)
		real = frappe.has_permission

		def no_create(doctype=None, ptype="read", *args, **kwargs):
			if doctype == "Contact" and ptype == "create":
				if kwargs.get("throw"):
					raise frappe.PermissionError
				return False
			return real(doctype, ptype, *args, **kwargs)

		frappe.set_user(PORTAL)
		with patch.object(webmail.frappe, "has_permission", side_effect=no_create):
			for address in (email, "webmail-perm-alpha@example.com"):
				# Not even whether an address is known: that comes after the right to create.
				with self.assertRaises(frappe.PermissionError, msg=address):
					webmail.create_contact_from_email(address, "New Person")
				with self.assertRaises(frappe.PermissionError, msg=address):
					webmail.bulk_create_contacts(frappe.as_json([{"email": address}]))
		self.assertFalse(frappe.db.exists("Contact Email", {"email_id": email}), "nothing was created")

		# A reader whose contacts a User Permission restricts may not create one, as in the desk.
		frappe.set_user(READER)
		with self.assertRaises(frappe.PermissionError):
			webmail.create_contact_from_email(email, "New Person")
		self.assertFalse(frappe.db.exists("Contact Email", {"email_id": email}))

		frappe.set_user(DESK)
		created = webmail.create_contact_from_email(email, "New Person")
		self.assertTrue(created["success"])
		self.assertEqual(frappe.db.get_value("Contact", created["contact"], "owner"), DESK)

	def test_a_contact_is_found_among_all_that_have_the_address(self):
		"""Two contacts share Alpha's address: the reader restricted to Alpha gets Alpha whichever row comes first (the
		first row alone said None when it was the other's), and a portal client gets nothing."""
		frappe.set_user("Administrator")
		gamma = (
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Gamma",
					"last_name": "Webmailperm",
					"email_ids": [{"email_id": "webmail-perm-alpha@example.com", "is_primary": 1}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.addCleanup(frappe.delete_doc, "Contact", gamma, ignore_permissions=True, force=True)
		frappe.set_user(READER)
		self.assertEqual(webmail.get_contact_by_email("webmail-perm-alpha@example.com")["name"], self.alpha)
		self.assertIsNone(
			webmail.get_contact_by_email("webmail-perm-beta@example.com"), "outside its permissions"
		)
		frappe.set_user(DESK)
		self.assertIn(
			webmail.get_contact_by_email("webmail-perm-alpha@example.com")["name"], {self.alpha, gamma}
		)
		frappe.set_user(PORTAL)
		self.assertIsNone(webmail.get_contact_by_email("webmail-perm-alpha@example.com"))

	def test_a_record_one_may_not_read_is_answered_as_absent(self):
		"""Linking a contact and printing a document say « not found » alike for a record that is not there and one that
		is not the person's to read: the refusal used to tell which records exist."""
		frappe.set_user(READER)
		for contact in (self.beta, "webmail-perm-nobody"):
			with self.assertRaises(frappe.DoesNotExistError, msg=contact):
				webmail.link_contact_to_document(contact, "Contact", self.alpha)
			with self.assertRaises(frappe.DoesNotExistError, msg=contact):
				webmail.generate_document_pdf("Contact", contact)
		# A row of a child table is no record to link, though it exists (Alpha's own address row).
		row = frappe.db.get_value("Contact Email", {"parent": self.alpha}, "name")
		for doctype, name in (("Contact", self.beta), ("Not A DocType", "x"), ("Contact Email", row)):
			with self.assertRaises(frappe.DoesNotExistError, msg=doctype):
				webmail.link_contact_to_document(self.alpha, doctype, name)
		self.assertEqual(
			frappe.db.get_value("Dynamic Link", {"parent": self.alpha, "link_name": self.beta}),
			None,
			"nothing linked",
		)

	def test_the_file_picker_and_the_print_formats_are_the_desks(self):
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			webmail.get_file_manager_files()
		with self.assertRaises(frappe.PermissionError):
			webmail.get_print_formats("Contact")
		frappe.set_user(DESK)
		listed = webmail.get_file_manager_files(page_length=5)
		self.assertLessEqual(len(listed["files"]), 5)
		self.assertGreaterEqual(listed["total"], len(listed["files"]))
		self.assertEqual(webmail.get_print_formats("Contact")[0]["name"], "Standard")
		self.assertEqual(webmail.get_print_formats("Error Log"), [], "a DocType the person may not read")

	def test_a_private_file_one_may_not_read_is_answered_as_absent(self):
		frappe.set_user("Administrator")
		private = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "webmail-perm-private.txt",
				"content": b"private",
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "File", private.name, ignore_permissions=True, force=True)
		frappe.set_user(READER)
		for url in (private.file_url, "/private/files/webmail-perm-nobody.txt"):
			with self.assertRaises(frappe.DoesNotExistError, msg=url):
				webmail.get_file_content(url)
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			webmail.get_file_content(private.file_url)
		frappe.set_user("Administrator")
		self.assertEqual(webmail.get_file_content(private.file_url)["size"], len(b"private"))
