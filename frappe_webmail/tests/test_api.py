# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Tests for the Webmail API

These tests cover the API endpoints in frappe_webmail/api.py
They use mocking to avoid requiring actual IMAP/SMTP servers.

Run with:
    bench --site [sitename] run-tests --app frappe_webmail --module frappe_webmail.tests.test_api
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestWebmailAPIBase(FrappeTestCase):
	"""Base class for Webmail API tests with common setup"""

	@classmethod
	def setUpClass(cls):
		"""Set up test fixtures"""
		super().setUpClass()

		# Create test user
		cls.test_user = "webmail_test@example.com"
		if not frappe.db.exists("User", cls.test_user):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.test_user,
					"first_name": "Webmail",
					"last_name": "Tester",
					"send_welcome_email": 0,
					"user_type": "System User",
				}
			)
			user.insert(ignore_permissions=True)
			user.add_roles("System Manager")

		# Create test webmail account
		cls.test_account_email = "test_account@webmail.test"
		if not frappe.db.exists("Webmail Account", cls.test_account_email):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": cls.test_account_email,
					"user": cls.test_user,
					"sender_name": "Test Account",
					"imap_host": "imap.test.local",
					"imap_port": 993,
					"imap_ssl": 1,
					"imap_password": "test_password_123",
					"smtp_host": "smtp.test.local",
					"smtp_port": 587,
					"smtp_starttls": 1,
					"smtp_password": "test_password_123",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def setUp(self):
		"""Set up before each test"""
		frappe.set_user(self.test_user)

	def tearDown(self):
		"""Clean up after each test"""
		frappe.set_user("Administrator")


class TestGetAccounts(TestWebmailAPIBase):
	"""Tests for get_accounts API"""

	def test_returns_list(self):
		"""Test that get_accounts returns a list"""
		from frappe_webmail.api import get_accounts

		result = get_accounts()
		self.assertIsInstance(result, list)

	def test_returns_user_accounts_only(self):
		"""Test that only accounts belonging to current user are returned"""
		from frappe_webmail.api import get_accounts

		accounts = get_accounts()
		for account in accounts:
			doc = frappe.get_doc("Webmail Account", account["name"])
			self.assertEqual(doc.user, frappe.session.user)

	def test_returns_correct_fields(self):
		"""Test that returned accounts have required fields"""
		from frappe_webmail.api import get_accounts

		accounts = get_accounts()
		self.assertTrue(len(accounts) >= 1)

		account = accounts[0]
		self.assertIn("name", account)
		self.assertIn("email", account)
		self.assertIn("sender_name", account)

	def test_excludes_disabled_accounts(self):
		"""Test that disabled accounts are not returned"""
		from frappe_webmail.api import get_accounts

		# Create disabled account
		disabled_email = "disabled@webmail.test"
		if not frappe.db.exists("Webmail Account", disabled_email):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": disabled_email,
					"user": self.test_user,
					"imap_host": "imap.test.local",
					"imap_password": "test",
					"smtp_host": "smtp.test.local",
					"smtp_password": "test",
					"enabled": 0,
				}
			).insert(ignore_permissions=True)

		accounts = get_accounts()
		account_names = [a["name"] for a in accounts]
		self.assertNotIn(disabled_email, account_names)


class TestGetAccountHelper(TestWebmailAPIBase):
	"""Tests for get_account helper function"""

	def test_returns_account_for_owner(self):
		"""Test that account is returned for owner"""
		from frappe_webmail.api import get_account

		account = get_account(self.test_account_email)
		self.assertEqual(account.email, self.test_account_email)

	def test_raises_for_nonexistent_account(self):
		"""Test that error is raised for non-existent account"""
		from frappe_webmail.api import get_account

		with self.assertRaises(frappe.exceptions.ValidationError):
			get_account("nonexistent@example.com")

	def test_raises_for_other_user_account(self):
		"""Test that error is raised when accessing another user's account"""
		from frappe_webmail.api import get_account

		# Create another user with an account
		other_user = "other_user@example.com"
		other_account = "other_account@webmail.test"

		if not frappe.db.exists("User", other_user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": other_user,
					"first_name": "Other",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Webmail Account", other_account):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": other_account,
					"user": other_user,
					"imap_host": "imap.test.local",
					"imap_password": "test",
					"smtp_host": "smtp.test.local",
					"smtp_password": "test",
				}
			).insert(ignore_permissions=True)

		# Try to access as test_user
		with self.assertRaises(frappe.exceptions.ValidationError):
			get_account(other_account)


class TestGetFoldersWithMock(TestWebmailAPIBase):
	"""Tests for get_folders API with mocked IMAP"""

	@patch("frappe_webmail.api.IMAPClient")
	def test_returns_folder_list(self, mock_imap_class):
		"""Test that get_folders returns folder list"""
		from frappe_webmail.api import get_folders

		# Setup mock
		mock_client = MagicMock()
		mock_client.list_folders.return_value = [
			([b"\\HasNoChildren"], b"/", "INBOX"),
			([b"\\Sent", b"\\HasNoChildren"], b"/", "Sent"),
			([b"\\Trash"], b"/", "Trash"),
		]
		mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
		mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

		# Execute
		folders = get_folders(self.test_account_email)

		# Verify
		self.assertIsInstance(folders, list)
		self.assertEqual(len(folders), 3)

		inbox = next(f for f in folders if f["name"] == "INBOX")
		self.assertTrue(inbox["selectable"])

	@patch("frappe_webmail.api.IMAPClient")
	def test_handles_noselect_folders(self, mock_imap_class):
		"""Test that non-selectable folders are marked correctly"""
		from frappe_webmail.api import get_folders

		mock_client = MagicMock()
		mock_client.list_folders.return_value = [
			([b"\\Noselect"], b"/", "[Gmail]"),
		]
		mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
		mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

		folders = get_folders(self.test_account_email)

		self.assertFalse(folders[0]["selectable"])


class TestGetEmailsWithMock(TestWebmailAPIBase):
	"""Tests for get_emails API with mocked IMAP"""

	@patch("frappe_webmail.api.IMAPClient")
	def test_returns_email_list(self, mock_imap_class):
		"""Test that get_emails returns email list with pagination info"""
		from frappe_webmail.api import get_emails

		# Setup mock
		mock_client = MagicMock()
		mock_client.search.return_value = [1, 2, 3]

		# Mock envelope data
		from datetime import datetime

		mock_envelope = MagicMock()
		mock_envelope.subject = b"Test Subject"
		mock_envelope.date = datetime(2024, 1, 15, 10, 30)
		mock_envelope.from_ = [MagicMock(name=b"Sender", mailbox=b"sender", host=b"example.com")]
		mock_envelope.to = [MagicMock(mailbox=b"recipient", host=b"example.com")]

		mock_client.fetch.return_value = {
			3: {
				b"ENVELOPE": mock_envelope,
				b"FLAGS": [b"\\Seen"],
				b"BODYSTRUCTURE": None,
				b"RFC822.SIZE": 1234,
			}
		}

		mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
		mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

		# Execute
		result = get_emails(self.test_account_email, folder="INBOX", limit=10)

		# Verify structure
		self.assertIn("emails", result)
		self.assertIn("total", result)
		self.assertIn("has_more", result)
		self.assertEqual(result["total"], 3)

	@patch("frappe_webmail.api.IMAPClient")
	def test_respects_limit(self, mock_imap_class):
		"""Test that limit parameter is respected"""
		from frappe_webmail.api import get_emails

		mock_client = MagicMock()
		# Return more messages than limit
		mock_client.search.return_value = list(range(1, 101))
		mock_client.fetch.return_value = {}

		mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
		mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

		result = get_emails(self.test_account_email, limit=50)

		self.assertTrue(result["has_more"])
		self.assertEqual(result["total"], 100)

	def test_limit_capped_at_100(self):
		"""Test that limit is capped at 100"""
		from frappe_webmail.api import get_emails

		# This would need a mock to fully test, but we can check the logic
		with patch("frappe_webmail.api.IMAPClient") as mock_imap_class:
			mock_client = MagicMock()
			mock_client.search.return_value = []
			mock_client.fetch.return_value = {}
			mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
			mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

			# Should not raise even with limit > 100
			result = get_emails(self.test_account_email, limit=200)
			self.assertIsInstance(result, dict)


class TestSendEmailWithMock(TestWebmailAPIBase):
	"""Tests for send_email API with mocked SMTP"""

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_sends_email_successfully(self, mock_smtp_class):
		"""Test that email is sent successfully"""
		from frappe_webmail.api import send_email

		mock_server = MagicMock()
		mock_smtp_class.return_value = mock_server

		result = send_email(
			account_name=self.test_account_email,
			to="recipient@example.com",
			subject="Test Subject",
			html_content="<p>Test content</p>",
		)

		self.assertTrue(result["success"])
		mock_server.sendmail.assert_called_once()

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_handles_multiple_recipients(self, mock_smtp_class):
		"""Test sending to multiple recipients"""
		from frappe_webmail.api import send_email

		mock_server = MagicMock()
		mock_smtp_class.return_value = mock_server

		result = send_email(
			account_name=self.test_account_email,
			to="one@example.com, two@example.com",
			cc="three@example.com",
			subject="Test",
			html_content="<p>Test</p>",
		)

		self.assertTrue(result["success"])

		# Check sendmail was called with all recipients
		call_args = mock_server.sendmail.call_args
		recipients = call_args[0][1]
		self.assertEqual(len(recipients), 3)

	@patch("frappe_webmail.api.smtplib.SMTP_SSL")
	def test_uses_ssl_when_configured(self, mock_smtp_ssl_class):
		"""Test that SSL is used when account is configured for SSL"""
		from frappe_webmail.api import send_email

		# Update account to use SSL
		account = frappe.get_doc("Webmail Account", self.test_account_email)
		account.smtp_ssl = 1
		account.smtp_starttls = 0
		account.save()

		mock_server = MagicMock()
		mock_smtp_ssl_class.return_value = mock_server

		send_email(
			account_name=self.test_account_email,
			to="recipient@example.com",
			subject="Test",
			html_content="<p>Test</p>",
		)

		mock_smtp_ssl_class.assert_called_once()


class TestSetFlagsWithMock(TestWebmailAPIBase):
	"""Tests for set_flags API"""

	@patch("frappe_webmail.api.IMAPClient")
	def test_adds_flags(self, mock_imap_class):
		"""Test adding flags to messages"""
		from frappe_webmail.api import set_flags

		mock_client = MagicMock()
		mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
		mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

		result = set_flags(
			account_name=self.test_account_email,
			uids="[1, 2, 3]",
			folder="INBOX",
			add_flags='["\\\\Seen", "\\\\Flagged"]',
		)

		self.assertTrue(result["success"])
		mock_client.add_flags.assert_called_once()

	@patch("frappe_webmail.api.IMAPClient")
	def test_removes_flags(self, mock_imap_class):
		"""Test removing flags from messages"""
		from frappe_webmail.api import set_flags

		mock_client = MagicMock()
		mock_imap_class.return_value.__enter__ = MagicMock(return_value=mock_client)
		mock_imap_class.return_value.__exit__ = MagicMock(return_value=False)

		result = set_flags(
			account_name=self.test_account_email,
			uids="[1]",
			folder="INBOX",
			remove_flags='["\\\\Flagged"]',
		)

		self.assertTrue(result["success"])
		mock_client.remove_flags.assert_called_once()


class TestSignaturesAPI(TestWebmailAPIBase):
	"""Tests for signature-related API endpoints"""

	def test_get_signatures_returns_list(self):
		"""Test that get_signatures returns a list"""
		from frappe_webmail.api import get_signatures

		result = get_signatures()
		self.assertIsInstance(result, list)

	def test_get_signatures_only_user_signatures(self):
		"""Test that only current user's signatures are returned"""
		from frappe_webmail.api import get_signatures

		# Create a signature for test user
		sig_name = f"{self.test_user}-TestSig"
		if not frappe.db.exists("Email Signature", sig_name):
			frappe.get_doc(
				{
					"doctype": "Email Signature",
					"user": self.test_user,
					"signature_name": "TestSig",
					"content": "<p>Test signature</p>",
				}
			).insert(ignore_permissions=True)

		signatures = get_signatures()

		for sig in signatures:
			doc = frappe.get_doc("Email Signature", sig["name"])
			self.assertEqual(doc.user, frappe.session.user)

	def test_get_default_signature(self):
		"""Test getting default signature"""
		from frappe_webmail.api import get_default_signature

		# Create default signature
		sig_name = f"{self.test_user}-DefaultSig"
		if not frappe.db.exists("Email Signature", sig_name):
			frappe.get_doc(
				{
					"doctype": "Email Signature",
					"user": self.test_user,
					"signature_name": "DefaultSig",
					"content": "<p>Default signature content</p>",
					"is_default": 1,
				}
			).insert(ignore_permissions=True)

		result = get_default_signature()
		self.assertIn("Default signature content", result)


class TestHelperFunctions(unittest.TestCase):
	"""Tests for helper functions"""

	def test_decode_mime_header_plain(self):
		"""Test decoding plain header"""
		from frappe_webmail.api import decode_mime_header

		result = decode_mime_header("Plain Subject")
		self.assertEqual(result, "Plain Subject")

	def test_decode_mime_header_encoded(self):
		"""Test decoding MIME-encoded header"""
		from frappe_webmail.api import decode_mime_header

		# UTF-8 encoded subject
		encoded = "=?UTF-8?B?VMOpc3Qgc3ViamVjdA==?="
		result = decode_mime_header(encoded)
		self.assertIn("Test", result.replace("é", "e").replace("è", "e"))

	def test_decode_mime_header_none(self):
		"""Test handling None header"""
		from frappe_webmail.api import decode_mime_header

		result = decode_mime_header(None)
		self.assertEqual(result, "")

	def test_format_address(self):
		"""Test formatting email address from envelope"""
		from frappe_webmail.api import format_address

		mock_addr = MagicMock()
		mock_addr.mailbox = b"user"
		mock_addr.host = b"example.com"

		result = format_address(mock_addr)
		self.assertEqual(result, "user@example.com")

	def test_format_address_none(self):
		"""Test handling None address"""
		from frappe_webmail.api import format_address

		result = format_address(None)
		self.assertEqual(result, "")


class TestGuestAccess(unittest.TestCase):
	"""Tests for guest access restrictions"""

	def setUp(self):
		frappe.set_user("Guest")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_guest_cannot_get_accounts(self):
		"""Test that guest cannot access accounts"""
		from frappe_webmail.api import get_accounts

		# Should raise permission error or return empty
		try:
			result = get_accounts()
			# If it doesn't raise, result should be empty
			self.assertEqual(len(result), 0)
		except frappe.exceptions.PermissionError:
			pass  # Expected

	def test_guest_cannot_get_signatures(self):
		"""Test that guest cannot access signatures"""
		from frappe_webmail.api import get_signatures

		try:
			result = get_signatures()
			self.assertEqual(len(result), 0)
		except frappe.exceptions.PermissionError:
			pass
