# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Email Signature Preference: a person's choices are theirs (and a System Manager's) to read and change, the desk's
people only, and the copy of their photo is the server's to write. What the choices change in a signature is tested in
frappe_webmail/tests/test_signatures.py.

Run with:
    bench --site prodclone.local run-tests --module frappe_webmail.frappe_webmail.doctype.email_signature_preference.test_email_signature_preference
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import signature_photos
from frappe_webmail.signatures import PREFERENCE
from frappe_webmail.tests.test_signatures import make_user, picture_file

PERSON = "signatures_pref_person@example.com"
OTHER = "signatures_pref_other@example.com"
THIRD = "signatures_pref_third@example.com"
PORTAL = "signatures_pref_portal@example.com"
# The people of these tests are made by them: the runner's own test users are not needed
test_ignore = ["User"]


class TestEmailSignaturePreference(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email, last in ((PERSON, "Person"), (OTHER, "Other"), (THIRD, "Third")):
			make_user(email, "Preftest", last)
		make_user(PORTAL, "Preftest", "Portal", desk=False)

	def setUp(self):
		for user in (PERSON, OTHER, THIRD, PORTAL):
			if frappe.db.exists(PREFERENCE, {"user": user}):
				frappe.delete_doc(PREFERENCE, frappe.db.get_value(PREFERENCE, {"user": user}), force=True)
		later = patch.object(signature_photos, "refresh_later")
		later.start()
		self.addCleanup(later.stop)
		self.addCleanup(frappe.set_user, "Administrator")

	def own(self, user=PERSON, **values):
		"""The person's record, made by them with their own rights, removed after the test."""
		frappe.set_user(user)
		doc = frappe.get_doc({"doctype": PREFERENCE, **values}).insert()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.delete_doc, PREFERENCE, doc.name, force=True, ignore_permissions=True)
		return doc

	def test_a_person_makes_reads_and_changes_their_own_record(self):
		doc = self.own()
		self.assertEqual(
			(doc.name, doc.user), (PERSON, PERSON), "made for whoever makes it, named after them"
		)
		frappe.set_user(PERSON)
		self.assertTrue(frappe.has_permission(PREFERENCE, "read", doc=PERSON))
		frappe.client.set_value(PREFERENCE, PERSON, "hide_mobile", 1)
		self.assertEqual(frappe.db.get_value(PREFERENCE, PERSON, "hide_mobile"), 1)
		self.assertEqual(frappe.get_list(PREFERENCE, pluck="name"), [PERSON])

	def test_nobody_else_reads_or_changes_a_person_s_record(self):
		self.own()
		self.own(user=OTHER)
		frappe.set_user(OTHER)
		for ptype in ("read", "write", "delete"):
			self.assertFalse(frappe.has_permission(PREFERENCE, ptype, doc=PERSON), ptype)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get(PREFERENCE, PERSON)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.set_value(PREFERENCE, PERSON, "photo_allowed", 1)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(PREFERENCE, PERSON).delete()
		self.assertEqual(frappe.get_list(PREFERENCE, pluck="name"), [OTHER], "the lists show their own only")
		self.assertEqual(frappe.db.get_value(PREFERENCE, PERSON, "photo_allowed"), 0)
		# Nor makes one for someone else
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": PREFERENCE, "user": THIRD, "photo_allowed": 1}).insert()
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists(PREFERENCE, {"user": THIRD}))

	def test_a_system_manager_reads_and_changes_everyone_s(self):
		self.own()
		self.own(user=OTHER)
		frappe.set_user("Administrator")
		self.assertTrue({PERSON, OTHER} <= set(frappe.get_list(PREFERENCE, pluck="name")))
		frappe.client.set_value(PREFERENCE, PERSON, "hide_mobile", 1)
		self.assertEqual(frappe.db.get_value(PREFERENCE, PERSON, "hide_mobile"), 1)

	def test_a_portal_account_has_no_choices(self):
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": PREFERENCE, "photo_allowed": 1}).insert()
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": PREFERENCE, "user": PORTAL}).insert()
		self.assertFalse(frappe.db.exists(PREFERENCE, {"user": PORTAL}))

	def test_the_copy_of_the_photo_is_written_by_the_server_alone(self):
		"""A message carries the file the copy names: whatever a save says of it, it stays the server's."""
		secret = "/private/files/zz-pref-test-someone-else.png"
		frappe.set_user(PERSON)
		doc = frappe.get_doc({"doctype": PREFERENCE, "photo": secret, "photo_source": "x"}).insert()
		self.addCleanup(frappe.delete_doc, PREFERENCE, doc.name, force=True, ignore_permissions=True)
		self.assertEqual(frappe.db.get_value(PREFERENCE, PERSON, ["photo", "photo_source"]), (None, None))
		doc.photo = secret
		doc.save()
		try:
			frappe.client.set_value(PREFERENCE, PERSON, {"photo": secret, "photo_source": "y"})
		except frappe.ValidationError:
			# Refused outright is as good: what matters is what is stored
			pass
		self.assertEqual(frappe.db.get_value(PREFERENCE, PERSON, ["photo", "photo_source"]), (None, None))

	def test_the_copy_of_the_photo_is_the_person_s_and_unreadable_by_a_colleague(self):
		"""Whoever made it: the person, or a manager ticking the box for them (a worker started by a manager's preview
		makes it as that manager too). Where the Drive decides who reads a file (suite), its owner reads it."""
		frappe.db.set_value(
			"User", PERSON, "user_image", picture_file(self, width=64, height=80, colour=(3, 4, 5))
		)
		self.addCleanup(frappe.db.set_value, "User", PERSON, "user_image", None)
		for made_by in (PERSON, "Administrator"):
			if made_by == PERSON:
				self.own(photo_allowed=1)
			else:
				frappe.delete_doc(PREFERENCE, PERSON, force=True, ignore_permissions=True)
				frappe.get_doc({"doctype": PREFERENCE, "user": PERSON, "photo_allowed": 1}).insert(
					ignore_permissions=True
				)
			copy = frappe.db.get_value(
				"File",
				{"attached_to_doctype": PREFERENCE, "attached_to_name": PERSON},
				["name", "is_private", "owner"],
				as_dict=True,
			)
			self.assertTrue(copy and copy.is_private, made_by)
			self.assertEqual(copy.owner, PERSON, made_by)
			self.assertTrue(frappe.has_permission("File", "read", doc=copy.name, user=PERSON), made_by)
			for colleague in (OTHER, PORTAL):
				self.assertFalse(
					frappe.has_permission("File", "read", doc=copy.name, user=colleague), (made_by, colleague)
				)
				# What serves a private file asks the same (frappe.utils.response.download_private_file)
				frappe.set_user(colleague)
				with self.assertRaises(frappe.PermissionError, msg=str((made_by, colleague))):
					frappe.get_doc("File", copy.name).check_permission("read")
				frappe.set_user("Administrator")

	def test_a_person_deleted_takes_their_choices_and_their_photo_along(self):
		gone = "signatures_pref_gone@example.com"
		make_user(gone, "Preftest", "Gone")
		self.addCleanup(
			lambda: frappe.db.exists("User", gone) and frappe.delete_doc("User", gone, force=True)
		)
		frappe.db.set_value(
			"User", gone, "user_image", picture_file(self, width=66, height=80, colour=(6, 7, 8))
		)
		frappe.get_doc({"doctype": PREFERENCE, "user": gone, "photo_allowed": 1}).insert(
			ignore_permissions=True
		)
		copy = frappe.db.get_value("File", {"attached_to_doctype": PREFERENCE, "attached_to_name": gone})
		self.assertTrue(copy)
		frappe.delete_doc("User", gone)
		self.assertFalse(frappe.db.exists("User", gone))
		self.assertFalse(frappe.db.exists(PREFERENCE, gone))
		self.assertFalse(frappe.db.exists("File", copy))

	def test_the_rights_of_the_doctype(self):
		meta = frappe.get_meta(PREFERENCE)
		rights = {row.role: (row.read, row.write, row.create, row.delete) for row in meta.permissions}
		self.assertEqual(rights.get("System Manager"), (1, 1, 1, 1))
		self.assertEqual(rights.get("Desk User"), (1, 1, 1, 0), "the desk's people, on their own record")
		# An instance may let its own administrators' role read every DocType (one such is named Admin); never a role
		# that portal users or visitors hold.
		self.assertEqual(set(rights) - {"System Manager", "Desk User", "Admin"}, set(), rights)
		self.assertTrue(meta.track_changes, "who changed a choice, and when")
		self.assertEqual(meta.get_field("photo").read_only, 1)
		self.assertEqual(meta.get_field("photo_source").read_only, 1)
