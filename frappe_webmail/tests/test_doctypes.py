# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Tests for Webmail DocTypes

Tests for Webmail Account and Email Signature DocTypes.

Run with:
    bench --site [sitename] run-tests --app frappe_webmail --module frappe_webmail.tests.test_doctypes
"""

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
		raw_value = frappe.db.get_value(
			"Webmail Account", account.name, "imap_password", as_dict=False
		)
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
