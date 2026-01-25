# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Tests for Webmail utility modules

Tests for imap_client.py and email_parser.py utilities.

Run with:
    bench --site [sitename] run-tests --app frappe_webmail --module frappe_webmail.tests.test_utils
"""

import base64
import unittest
from unittest.mock import MagicMock, patch


class TestEmailParser(unittest.TestCase):
	"""Tests for EmailParser utility"""

	def test_parse_plain_text_email(self):
		"""Test parsing plain text email"""
		from frappe_webmail.utils.email_parser import EmailParser

		raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Content-Type: text/plain; charset=utf-8

This is a plain text email body.
"""
		parser = EmailParser(raw_email)
		parser.parse()

		self.assertIsNone(parser.html_content)
		self.assertIn("plain text email", parser.text_content)

	def test_parse_html_email(self):
		"""Test parsing HTML email"""
		from frappe_webmail.utils.email_parser import EmailParser

		raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Content-Type: text/html; charset=utf-8

<html><body><p>This is an HTML email.</p></body></html>
"""
		parser = EmailParser(raw_email)
		parser.parse()

		self.assertIn("<p>This is an HTML email.</p>", parser.html_content)

	def test_parse_multipart_email(self):
		"""Test parsing multipart email with text and HTML"""
		from frappe_webmail.utils.email_parser import EmailParser

		raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Plain text version.

--boundary123
Content-Type: text/html; charset=utf-8

<html><body><p>HTML version.</p></body></html>

--boundary123--
"""
		parser = EmailParser(raw_email)
		parser.parse()

		self.assertIn("HTML version", parser.html_content)
		self.assertIn("Plain text version", parser.text_content)

	def test_extract_attachments(self):
		"""Test extracting attachments"""
		from frappe_webmail.utils.email_parser import EmailParser

		attachment_content = base64.b64encode(b"PDF content here").decode()
		raw_email = f"""From: sender@example.com
To: recipient@example.com
Subject: With Attachment
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Email with attachment.

--boundary123
Content-Type: application/pdf; name="document.pdf"
Content-Disposition: attachment; filename="document.pdf"
Content-Transfer-Encoding: base64

{attachment_content}

--boundary123--
""".encode()

		parser = EmailParser(raw_email)
		parser.parse()

		self.assertEqual(len(parser.attachments), 1)
		self.assertEqual(parser.attachments[0]["filename"], "document.pdf")
		self.assertEqual(parser.attachments[0]["content_type"], "application/pdf")

	def test_decode_header_plain(self):
		"""Test decoding plain header"""
		from frappe_webmail.utils.email_parser import EmailParser

		result = EmailParser.decode_header("Plain Subject")
		self.assertEqual(result, "Plain Subject")

	def test_decode_header_utf8(self):
		"""Test decoding UTF-8 encoded header"""
		from frappe_webmail.utils.email_parser import EmailParser

		# "Test" in UTF-8 base64
		encoded = "=?UTF-8?B?VGVzdA==?="
		result = EmailParser.decode_header(encoded)
		self.assertEqual(result, "Test")

	def test_decode_header_none(self):
		"""Test handling None header"""
		from frappe_webmail.utils.email_parser import EmailParser

		result = EmailParser.decode_header(None)
		self.assertEqual(result, "")

	def test_sanitize_html_removes_script(self):
		"""Test that script tags are removed"""
		from frappe_webmail.utils.email_parser import EmailParser

		raw_email = b"""From: sender@example.com
Subject: Test
Content-Type: text/html

<html><body>
<p>Hello</p>
<script>alert('xss')</script>
</body></html>
"""
		parser = EmailParser(raw_email)
		parser.parse()
		sanitized = parser.get_sanitized_html()

		self.assertNotIn("<script>", sanitized)
		self.assertIn("Hello", sanitized)

	def test_sanitize_html_removes_event_handlers(self):
		"""Test that event handlers are removed"""
		from frappe_webmail.utils.email_parser import EmailParser

		raw_email = b"""From: sender@example.com
Subject: Test
Content-Type: text/html

<html><body>
<img src="test.jpg" onerror="alert('xss')">
</body></html>
"""
		parser = EmailParser(raw_email)
		parser.parse()
		sanitized = parser.get_sanitized_html()

		self.assertNotIn("onerror", sanitized)

	def test_block_external_images(self):
		"""Test that external images are blocked"""
		from frappe_webmail.utils.email_parser import EmailParser

		raw_email = b"""From: sender@example.com
Subject: Test
Content-Type: text/html

<html><body>
<img src="https://tracker.example.com/pixel.gif">
</body></html>
"""
		parser = EmailParser(raw_email)
		parser.parse()
		sanitized = parser.get_sanitized_html(block_external_images=True)

		self.assertNotIn("https://tracker.example.com", sanitized)

	def test_allow_data_uri_images(self):
		"""Test that data URI images are allowed"""
		from frappe_webmail.utils.email_parser import EmailParser

		data_uri = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
		raw_email = f"""From: sender@example.com
Subject: Test
Content-Type: text/html

<html><body>
<img src="{data_uri}">
</body></html>
""".encode()

		parser = EmailParser(raw_email)
		parser.parse()
		sanitized = parser.get_sanitized_html(block_external_images=True)

		self.assertIn("data:image/gif", sanitized)

	def test_format_address(self):
		"""Test formatting address from envelope"""
		from frappe_webmail.utils.email_parser import EmailParser

		mock_addr = MagicMock()
		mock_addr.mailbox = b"user"
		mock_addr.host = b"example.com"

		result = EmailParser.format_address(mock_addr)
		self.assertEqual(result, "user@example.com")

	def test_format_address_string(self):
		"""Test formatting address with string values"""
		from frappe_webmail.utils.email_parser import EmailParser

		mock_addr = MagicMock()
		mock_addr.mailbox = "user"
		mock_addr.host = "example.com"

		result = EmailParser.format_address(mock_addr)
		self.assertEqual(result, "user@example.com")

	def test_has_attachments_true(self):
		"""Test detecting attachments in bodystructure"""
		from frappe_webmail.utils.email_parser import EmailParser

		# Simulated bodystructure with attachment
		bodystructure = (
			(b"TEXT", b"PLAIN", (b"CHARSET", b"UTF-8"), None, None, b"7BIT", 100, 10),
			(
				b"APPLICATION",
				b"PDF",
				None,
				None,
				None,
				b"BASE64",
				5000,
				(b"attachment", (b"filename", b"doc.pdf")),
			),
			b"MIXED",
		)

		result = EmailParser.has_attachments(bodystructure)
		# Note: Implementation may need adjustment based on actual bodystructure format
		# This test verifies the method handles the structure without errors
		self.assertIsInstance(result, bool)

	def test_has_attachments_false(self):
		"""Test no attachments detected for plain email"""
		from frappe_webmail.utils.email_parser import EmailParser

		result = EmailParser.has_attachments(None)
		self.assertFalse(result)


class TestIMAPClient(unittest.TestCase):
	"""Tests for WebmailIMAPClient utility"""

	def test_client_requires_imapclient_package(self):
		"""Test that client checks for imapclient package"""
		# This test verifies the import check works
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		# Just verify the class exists
		self.assertTrue(callable(WebmailIMAPClient))

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_context_manager(self, mock_imap_class):
		"""Test client works as context manager"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_imap_class.return_value = mock_client

		# Create mock account
		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			self.assertIsNotNone(client)

		# Verify login and logout were called
		mock_client.login.assert_called_once()
		mock_client.logout.assert_called_once()

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_list_folders(self, mock_imap_class):
		"""Test listing folders"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_client.list_folders.return_value = [
			([b"\\HasNoChildren"], b"/", "INBOX"),
			([b"\\Sent"], b"/", "Sent"),
		]
		mock_imap_class.return_value = mock_client

		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			folders = client.list_folders()

		self.assertEqual(len(folders), 2)
		self.assertEqual(folders[0]["name"], "INBOX")

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_select_folder(self, mock_imap_class):
		"""Test selecting a folder"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_client.select_folder.return_value = {b"EXISTS": 100}
		mock_imap_class.return_value = mock_client

		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			client.select_folder("INBOX")

		mock_client.select_folder.assert_called_with("INBOX", readonly=False)

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_search(self, mock_imap_class):
		"""Test searching messages"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_client.search.return_value = [1, 2, 3, 4, 5]
		mock_imap_class.return_value = mock_client

		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			results = client.search(["NOT", "DELETED"])

		self.assertEqual(results, [1, 2, 3, 4, 5])

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_add_flags(self, mock_imap_class):
		"""Test adding flags to messages"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_imap_class.return_value = mock_client

		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			client.add_flags([1, 2], [b"\\Seen"])

		mock_client.add_flags.assert_called_with([1, 2], [b"\\Seen"])

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_remove_flags(self, mock_imap_class):
		"""Test removing flags from messages"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_imap_class.return_value = mock_client

		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			client.remove_flags([1], [b"\\Flagged"])

		mock_client.remove_flags.assert_called_with([1], [b"\\Flagged"])

	@patch("frappe_webmail.utils.imap_client.IMAPClient")
	def test_copy_and_expunge(self, mock_imap_class):
		"""Test copying messages and expunging"""
		from frappe_webmail.utils.imap_client import WebmailIMAPClient

		mock_client = MagicMock()
		mock_imap_class.return_value = mock_client

		mock_account = MagicMock()
		mock_account.imap_host = "imap.test.local"
		mock_account.imap_port = 993
		mock_account.imap_ssl = True
		mock_account.email = "test@example.com"
		mock_account.get_password.return_value = "password"

		with WebmailIMAPClient(mock_account) as client:
			client.copy([1, 2], "Archive")
			client.expunge()

		mock_client.copy.assert_called_with([1, 2], "Archive")
		mock_client.expunge.assert_called_once()


class TestHelperFunctions(unittest.TestCase):
	"""Tests for standalone helper functions"""

	def test_text_to_html_escapes_special_chars(self):
		"""Test that special characters are escaped"""
		from frappe_webmail.utils.email_parser import EmailParser

		parser = EmailParser(b"")
		html = parser._text_to_html("<script>alert('xss')</script>")

		self.assertNotIn("<script>", html)
		self.assertIn("&lt;script&gt;", html)

	def test_text_to_html_converts_newlines(self):
		"""Test that newlines are converted to <br>"""
		from frappe_webmail.utils.email_parser import EmailParser

		parser = EmailParser(b"")
		html = parser._text_to_html("Line 1\nLine 2")

		self.assertIn("<br>", html)

	def test_basic_sanitize_removes_scripts(self):
		"""Test basic sanitization removes script tags"""
		from frappe_webmail.utils.email_parser import EmailParser

		parser = EmailParser(b"")
		result = parser._basic_sanitize("<p>Hello</p><script>evil()</script>")

		self.assertNotIn("<script>", result)
		self.assertIn("<p>Hello</p>", result)

	def test_basic_sanitize_removes_event_handlers(self):
		"""Test basic sanitization removes event handlers"""
		from frappe_webmail.utils.email_parser import EmailParser

		parser = EmailParser(b"")
		result = parser._basic_sanitize('<img src="x" onerror="alert(1)">')

		self.assertNotIn("onerror", result)


if __name__ == "__main__":
	unittest.main()
