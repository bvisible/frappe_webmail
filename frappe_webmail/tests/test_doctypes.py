# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Tests for Webmail DocTypes

Tests for Webmail Account and Email Signature DocTypes.

Run with:
    bench --site [sitename] run-tests --app frappe_webmail --module frappe_webmail.tests.test_doctypes
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestWebmailAccount(FrappeTestCase):
	"""Tests for Webmail Account DocType"""

	@classmethod
	def setUpClass(cls):
		"""Set up test fixtures"""
		super().setUpClass()

		# Create test user
		cls.test_user = "webmail_doctype_test@example.com"
		if not frappe.db.exists("User", cls.test_user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.test_user,
					"first_name": "DocType",
					"last_name": "Tester",
					"send_welcome_email": 0,
					"user_type": "System User",
				}
			).insert(ignore_permissions=True)
			frappe.get_doc("User", cls.test_user).add_roles("System Manager")

		frappe.db.commit()

	def setUp(self):
		"""Set up before each test"""
		frappe.set_user(self.test_user)

	def tearDown(self):
		"""Clean up after each test"""
		frappe.set_user("Administrator")

	def test_create_account(self):
		"""Test creating a webmail account"""
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "create_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_port": 993,
				"imap_ssl": 1,
				"imap_password": "password123",
				"smtp_host": "smtp.test.local",
				"smtp_port": 587,
				"smtp_starttls": 1,
				"smtp_password": "password123",
			}
		)
		account.insert()

		self.assertEqual(account.email, "create_test@webmail.test")
		self.assertEqual(account.imap_port, 993)
		self.assertTrue(account.enabled)

		# Cleanup
		account.delete()

	def test_account_autoname(self):
		"""Test that account is named after email"""
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "autoname_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)
		account.insert()

		self.assertEqual(account.name, "autoname_test@webmail.test")

		# Cleanup
		account.delete()

	def test_account_requires_email(self):
		"""Test that email is required"""
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)

		with self.assertRaises(frappe.exceptions.MandatoryError):
			account.insert()

	def test_account_validates_email_format(self):
		"""Test that invalid email format is rejected"""
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "invalid-email-format",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)

		with self.assertRaises(frappe.exceptions.ValidationError):
			account.insert()

	def test_account_validates_ports(self):
		"""Test that invalid ports are rejected"""
		# Port too high
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "port_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_port": 99999,
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)

		with self.assertRaises(frappe.exceptions.ValidationError):
			account.insert()

	def test_account_default_user(self):
		"""Test that user defaults to current user"""
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "default_user@webmail.test",
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)
		account.insert()

		self.assertEqual(account.user, self.test_user)

		# Cleanup
		account.delete()

	def test_account_password_encrypted(self):
		"""Test that passwords are stored encrypted"""
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "password_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "secret_password",
				"smtp_host": "smtp.test.local",
				"smtp_password": "secret_password",
			}
		)
		account.insert()

		# Reload and check password can be retrieved
		account.reload()
		decrypted = account.get_password("imap_password")
		self.assertEqual(decrypted, "secret_password")

		# Raw value should be encrypted (not equal to plaintext)
		raw_value = frappe.db.get_value("Webmail Account", account.name, "imap_password", as_dict=False)
		self.assertNotEqual(raw_value, "secret_password")

		# Cleanup
		account.delete()

	def test_account_if_owner_permission(self):
		"""Test that users can only access their own accounts"""
		# Create account as test_user
		frappe.set_user(self.test_user)
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "owner_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)
		account.insert()

		# Create another user
		other_user = "other_doctype_test@example.com"
		if not frappe.db.exists("User", other_user):
			frappe.set_user("Administrator")
			frappe.get_doc(
				{
					"doctype": "User",
					"email": other_user,
					"first_name": "Other",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		# Try to access as other user (should fail)
		frappe.set_user(other_user)
		try:
			frappe.get_doc("Webmail Account", account.name)
			# If no error, check has_permission
			self.assertFalse(account.has_permission("read"))
		except frappe.exceptions.PermissionError:
			pass  # Expected

		# Cleanup
		frappe.set_user("Administrator")
		account.delete()

	def test_a_shared_mailbox_is_read_by_its_guests_and_changed_by_its_owner_alone(self):
		"""Its settings, secrets, owner and sharing are the owner's (maintenance#1654); what the webmail keeps for
		everyone still goes through its own methods."""
		from frappe_webmail.webmail_api import (
			add_trusted_source,
			disconnect_oauth,
			save_folder_mapping,
			save_ui_preferences,
		)

		guest, stranger = "shared_doctype_test@example.com", "stranger_doctype_test@example.com"
		for email in (guest, stranger):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": "Guest", "send_welcome_email": 0}
				).insert(ignore_permissions=True)
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "shared_doctype_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
				"enabled": 1,
			}
		)
		account.append("allowed_users", {"user": guest})
		account.insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "Webmail Account", account.name, force=True, ignore_permissions=True
		)
		self.addCleanup(frappe.set_user, "Administrator")

		frappe.set_user(guest)
		doc = frappe.get_doc("Webmail Account", account.name)
		self.assertTrue(doc.has_permission("read"))
		self.assertTrue(frappe.has_permission("Webmail Account", "read", doc=doc, user=guest))
		for ptype in ("write", "delete", "create", "share", "submit"):
			self.assertFalse(doc.has_permission(ptype), ptype)
			self.assertFalse(frappe.has_permission("Webmail Account", ptype, doc=doc, user=guest), ptype)
		doc.smtp_host = "smtp.elsewhere.test"
		self.assertRaises(frappe.PermissionError, doc.save)
		self.assertRaises(
			frappe.PermissionError, frappe.client.set_value, "Webmail Account", account.name, "user", guest
		)
		self.assertRaises(frappe.PermissionError, frappe.delete_doc, "Webmail Account", account.name)
		# The settings that hold for everyone are the owner's to change, through the webmail's methods too.
		self.assertRaises(frappe.PermissionError, disconnect_oauth, account.name)
		self.assertRaises(frappe.PermissionError, save_folder_mapping, account.name, sent_folder="Elsewhere")
		# A rename is refused even when the client asks Frappe to skip its checks; the request then undoes it.
		self._assert_not_renamed(doc, guest)
		# Nor can they make an account in someone else's name.
		someone_elses = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "made_for_another@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
			}
		)
		someone_elses.append("allowed_users", {"user": guest})
		self.assertRaises(frappe.PermissionError, someone_elses.insert)
		self.assertEqual(
			frappe.db.get_value("Webmail Account", account.name, ["smtp_host", "user"]),
			("smtp.test.local", self.test_user),
		)
		# The webmail of a guest keeps working: widths, folded folders and trusted senders are saved for them (their
		# commits held back, so that nothing of the test outlives it).
		with patch.object(frappe.db, "commit"):
			save_ui_preferences(account.name, sidebar_width=280)
			add_trusted_source(account.name, "news@example.com", "Sender")
		self.assertEqual(frappe.db.get_value("Webmail Account", account.name, "sidebar_width"), 280)
		trusted = frappe.get_all("Trusted Email Source", {"parent": account.name}, pluck="value")
		self.assertIn("news@example.com", trusted)

		# Someone it is not shared with does not even read it.
		frappe.set_user(stranger)
		self.assertFalse(frappe.has_permission("Webmail Account", "read", doc=account.name, user=stranger))

		frappe.set_user(self.test_user)
		owned = frappe.get_doc("Webmail Account", account.name)
		owned.sender_name = "Changed by its owner"
		owned.save()
		self.assertEqual(
			frappe.db.get_value("Webmail Account", account.name, "sender_name"), "Changed by its owner"
		)
		# Its owner does not hand it to someone else: an administrator does.
		owned.user = guest
		self.assertRaises(frappe.PermissionError, owned.save)
		self.assertEqual(frappe.db.get_value("Webmail Account", account.name, "user"), self.test_user)
		self._assert_not_renamed(frappe.get_doc("Webmail Account", account.name), self.test_user)

		# An administrator still can, both: rename it (when asked to force it) and give it to someone else.
		frappe.set_user("Administrator")
		frappe.db.savepoint("administrator")
		try:
			frappe.rename_doc(
				"Webmail Account", account.name, "renamed_doctype_test@webmail.test", force=True
			)
			self.assertTrue(frappe.db.exists("Webmail Account", "renamed_doctype_test@webmail.test"))
			given = frappe.get_doc("Webmail Account", "renamed_doctype_test@webmail.test")
			given.user = guest
			given.save()
			self.assertEqual(frappe.db.get_value("Webmail Account", given.name, "user"), guest)
		finally:
			frappe.db.rollback(save_point="administrator")
		self.assertTrue(frappe.db.exists("Webmail Account", account.name))

	def _assert_not_renamed(self, doc, user):
		"""`user` cannot rename the account, even with Frappe's own checks skipped, as a client may ask through the
		whitelisted `rename`. What the refused rename wrote is undone, as the refused request would undo it."""
		frappe.set_user(user)
		name = doc.name
		frappe.db.savepoint("before_rename")
		try:
			with self.assertRaises(frappe.PermissionError):
				doc.rename("renamed_doctype_test@webmail.test", validate_rename=False)
		finally:
			frappe.db.rollback(save_point="before_rename")
		self.assertTrue(frappe.db.exists("Webmail Account", name))
		self.assertFalse(frappe.db.exists("Webmail Account", "renamed_doctype_test@webmail.test"))


class TestEmailSignature(FrappeTestCase):
	"""Tests for Email Signature DocType"""

	@classmethod
	def setUpClass(cls):
		"""Set up test fixtures"""
		super().setUpClass()

		# Create test user
		cls.test_user = "signature_test@example.com"
		if not frappe.db.exists("User", cls.test_user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.test_user,
					"first_name": "Signature",
					"last_name": "Tester",
					"send_welcome_email": 0,
					"user_type": "System User",
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def setUp(self):
		"""Set up before each test"""
		frappe.set_user(self.test_user)

		# Clean up any existing signatures for test user
		frappe.db.delete("Email Signature", {"user": self.test_user})

	def tearDown(self):
		"""Clean up after each test"""
		frappe.set_user("Administrator")

	def test_create_signature(self):
		"""Test creating a signature"""
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Test Signature",
				"content": "<p>Best regards,<br>Test User</p>",
			}
		)
		sig.insert()

		self.assertEqual(sig.signature_name, "Test Signature")
		self.assertIn("Best regards", sig.content)

	def test_signature_autoname(self):
		"""Test signature naming format"""
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Professional",
				"content": "<p>Signature content</p>",
			}
		)
		sig.insert()

		self.assertEqual(sig.name, f"{self.test_user}-Professional")

	def test_first_signature_is_default(self):
		"""Test that first signature for user is set as default"""
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "First",
				"content": "<p>First signature</p>",
			}
		)
		sig.insert()

		self.assertTrue(sig.is_default)

	def test_only_one_default_signature(self):
		"""Test that only one signature can be default per user"""
		# Create first signature (should be default)
		sig1 = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Sig1",
				"content": "<p>Sig 1</p>",
			}
		)
		sig1.insert()
		self.assertTrue(sig1.is_default)

		# Create second signature and set as default
		sig2 = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Sig2",
				"content": "<p>Sig 2</p>",
				"is_default": 1,
			}
		)
		sig2.insert()

		# Reload sig1 - should no longer be default
		sig1.reload()
		self.assertFalse(sig1.is_default)
		self.assertTrue(sig2.is_default)

	def test_signature_requires_name(self):
		"""Test that signature_name is required"""
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"content": "<p>Content without name</p>",
			}
		)

		with self.assertRaises(frappe.exceptions.MandatoryError):
			sig.insert()

	def test_signature_requires_content(self):
		"""Test that content is required"""
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Empty Content",
			}
		)

		with self.assertRaises(frappe.exceptions.MandatoryError):
			sig.insert()

	def test_signature_default_user(self):
		"""Test that user defaults to current user"""
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"signature_name": "Auto User",
				"content": "<p>Content</p>",
			}
		)
		sig.insert()

		self.assertEqual(sig.user, self.test_user)

	def test_signature_if_owner_permission(self):
		"""Test that users can only access their own signatures"""
		# Create signature as test_user
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Private",
				"content": "<p>Private signature</p>",
			}
		)
		sig.insert()

		# Create another user
		other_user = "other_sig_test@example.com"
		if not frappe.db.exists("User", other_user):
			frappe.set_user("Administrator")
			frappe.get_doc(
				{
					"doctype": "User",
					"email": other_user,
					"first_name": "Other",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		# Try to access as other user
		frappe.set_user(other_user)
		try:
			doc = frappe.get_doc("Email Signature", sig.name)
			self.assertFalse(doc.has_permission("read"))
		except frappe.exceptions.PermissionError:
			pass  # Expected

		# Cleanup
		frappe.set_user("Administrator")


class TestDocTypeIntegration(FrappeTestCase):
	"""Integration tests for DocTypes working together"""

	@classmethod
	def setUpClass(cls):
		"""Set up test fixtures"""
		super().setUpClass()

		cls.test_user = "integration_test@example.com"
		if not frappe.db.exists("User", cls.test_user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.test_user,
					"first_name": "Integration",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def setUp(self):
		frappe.set_user(self.test_user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_account_with_default_signature(self):
		"""Test linking account to signature"""
		# Create signature
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "Account Sig",
				"content": "<p>Signature</p>",
			}
		)
		sig.insert()

		# Create account with signature
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "integration@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
				"default_signature": sig.name,
			}
		)
		account.insert()

		# Verify link
		self.assertEqual(account.default_signature, sig.name)

		# Cleanup
		account.delete()
		sig.delete()

	def test_delete_signature_updates_accounts(self):
		"""Test that deleting signature doesn't break accounts"""
		# Create signature
		sig = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": "To Delete",
				"content": "<p>Will be deleted</p>",
			}
		)
		sig.insert()

		# Create account with signature
		account = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": "delete_sig_test@webmail.test",
				"user": self.test_user,
				"imap_host": "imap.test.local",
				"imap_password": "test",
				"smtp_host": "smtp.test.local",
				"smtp_password": "test",
				"default_signature": sig.name,
			}
		)
		account.insert()

		# Delete signature
		sig.delete()

		# Account should still exist
		account.reload()
		self.assertTrue(frappe.db.exists("Webmail Account", account.name))

		# Cleanup
		account.delete()
