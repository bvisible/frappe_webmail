# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What a person can do with an e-mail attachment (frappe_webmail.attachments), and the one rule that finds it.

The list of a message's attachments, their download and every action on one find them with `mime_parts`: an
attachment the list shows can always be read and acted on. The IMAP server is mocked; the message is a real MIME
message with the awkward cases (an accented RFC 2231 name, an image named without a disposition, an inline image with
a Content-ID, an attached e-mail).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_attachments
"""

import email
from contextlib import contextmanager
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from pypdf import PdfWriter

from frappe_webmail.mime_parts import iter_attachments
from frappe_webmail.tests.test_api import TestWebmailAPIBase


def blank_pdf():
	"""A real PDF: frappe reads every PDF it stores (pdf_contains_js), and refuses bytes that only look like one."""
	writer = PdfWriter()
	writer.add_blank_page(width=200, height=200)
	buffer = BytesIO()
	writer.write(buffer)
	return buffer.getvalue()


PDF = blank_pdf()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
UID = 42


def mail_with_attachments():
	msg = MIMEMultipart("mixed")
	msg["Subject"] = "Invoice 2026-118"
	msg["From"] = "supplier@example.com"
	msg["To"] = "test_account@webmail.test"

	body = MIMEMultipart("alternative")
	body.attach(MIMEText("Please find our invoice attached.", "plain"))
	body.attach(MIMEText("<p>Please find our invoice attached.</p>", "html"))
	msg.attach(body)

	pdf = MIMEApplication(PDF, _subtype="pdf")
	pdf.add_header("Content-Disposition", "attachment", filename=("utf-8", "", "Relevé 2026-118.pdf"))
	msg.attach(pdf)

	# A file name and no disposition: still an attachment
	plan = MIMEImage(PNG, _subtype="png")
	plan.set_param("name", "plan.png")
	msg.attach(plan)

	# An inline image with a Content-ID and a name: an attachment whose id is its Content-ID
	logo = MIMEImage(PNG, _subtype="png")
	logo.add_header("Content-ID", "<logo@example.com>")
	logo.add_header("Content-Disposition", "inline", filename="logo.png")
	msg.attach(logo)

	inner = MIMEText("The forwarded message.", "plain")
	inner["Subject"] = "Forwarded"
	forwarded = MIMEMessage(inner)
	forwarded.add_header("Content-Disposition", "attachment")
	msg.attach(forwarded)
	return msg.as_bytes()


RAW = mail_with_attachments()


def imap_client(raw=RAW):
	"""A mocked IMAP connection serving `raw` as message UID."""
	client = MagicMock()
	envelope = SimpleNamespace(
		subject=b"Invoice 2026-118",
		date=datetime(2026, 10, 13, 10, 42),
		from_=[SimpleNamespace(name=b"Supplier", mailbox=b"supplier", host=b"example.com")],
		to=[SimpleNamespace(name=None, mailbox=b"test_account", host=b"webmail.test")],
		cc=None,
		reply_to=None,
	)
	client.fetch.side_effect = lambda uids, items: {
		UID: {b"BODY[]": raw, b"RFC822": raw, b"ENVELOPE": envelope, b"FLAGS": (b"\\Seen",)}
	}
	return client


@contextmanager
def mocked_imap(client):
	with patch("frappe_webmail.webmail_api.IMAPClient") as imap_class:
		imap_class.return_value.__enter__ = MagicMock(return_value=client)
		imap_class.return_value.__exit__ = MagicMock(return_value=False)
		yield client


class TestTheOneRule(TestWebmailAPIBase):
	"""The list, the download and the actions see the same attachments, with the same ids."""

	def test_the_rule_on_a_real_message(self):
		found = [
			(a.id, a.rank, a.part.get_content_type()) for a in iter_attachments(email.message_from_bytes(RAW))
		]
		self.assertEqual(
			found,
			[
				("0", 0, "application/pdf"),
				("1", 1, "image/png"),
				("logo@example.com", 2, "image/png"),
				("3", 3, "message/rfc822"),
			],
		)

	def test_every_attachment_listed_can_be_downloaded(self):
		from frappe_webmail.api import get_attachment, get_email_content

		with mocked_imap(imap_client()):
			listed = get_email_content(self.test_account_email, UID, folder="INBOX", mark_read=False)[
				"attachments"
			]
			self.assertEqual(
				[(a["id"], a["filename"]) for a in listed],
				[
					("0", "Relevé 2026-118.pdf"),
					("1", "plan.png"),
					("logo@example.com", "logo.png"),
					("3", "attachment_3.eml"),
				],
			)
			for item in listed:
				got = get_attachment(self.test_account_email, UID, "INBOX", item["id"])
				self.assertEqual(got["filename"], item["filename"])
				self.assertEqual(got["size"], item["size"])
				self.assertGreater(got["size"], 0)

	def test_reading_an_attachment_never_marks_the_message_read(self):
		from frappe_webmail.api import get_attachment

		with mocked_imap(imap_client()) as client:
			get_attachment(self.test_account_email, UID, "INBOX", "0")
		client.select_folder.assert_called_with("INBOX", readonly=True)
		self.assertEqual(client.fetch.call_args.args[1], ["BODY.PEEK[]"])
		client.add_flags.assert_not_called()

	def test_an_attached_email_is_saved_as_an_eml_file(self):
		from frappe_webmail.webmail_api import read_attachment

		account = frappe.get_doc("Webmail Account", self.test_account_email)
		with mocked_imap(imap_client()):
			name, content_type, payload = read_attachment(account, "INBOX", UID, "3")
		self.assertEqual((name, content_type), ("attachment_3.eml", "message/rfc822"))
		self.assertIn(b"Subject: Forwarded", payload)
		self.assertIn(b"The forwarded message.", payload)

	def test_an_unknown_attachment_is_refused(self):
		from frappe_webmail.api import get_attachment

		with mocked_imap(imap_client()), self.assertRaises(frappe.ValidationError):
			get_attachment(self.test_account_email, UID, "INBOX", "9")


class TestDownload(TestWebmailAPIBase):
	"""The preview and « Save as… »: the bytes streamed, and never a stranger's HTML shown on the instance."""

	def download(self, attachment_id, inline):
		from frappe_webmail.attachments import download_attachment

		frappe.local.response = frappe._dict()
		with mocked_imap(imap_client()):
			download_attachment(self.test_account_email, "INBOX", UID, attachment_id, inline=inline)
		return frappe.local.response

	def test_a_pdf_previews_inline(self):
		response = self.download("0", inline=1)
		self.assertEqual(response.type, "download")
		self.assertEqual(response.display_content_as, "inline")
		self.assertEqual(response.content_type, "application/pdf")
		self.assertEqual(response.filecontent, PDF)
		# as_raw decodes the name with "unicode-escape": what it gets back must be the real name
		self.assertEqual(response.filename.encode("utf-8").decode("unicode-escape"), "Relevé 2026-118.pdf")

	def test_html_is_never_shown_inline(self):
		raw = MIMEMultipart("mixed")
		raw.attach(MIMEText("See the page.", "plain"))
		page = MIMEText("<script>alert(document.cookie)</script>", "html")
		page.add_header("Content-Disposition", "attachment", filename="page.html")
		raw.attach(page)
		from frappe_webmail.attachments import download_attachment

		frappe.local.response = frappe._dict()
		with mocked_imap(imap_client(raw.as_bytes())):
			download_attachment(self.test_account_email, "INBOX", UID, "0", inline=1)
		self.assertEqual(frappe.local.response.display_content_as, "attachment")
		self.assertEqual(frappe.local.response.content_type, "application/octet-stream")

	def test_someone_without_the_mailbox_cannot_download(self):
		from frappe_webmail.attachments import download_attachment

		frappe.set_user("Guest")
		with mocked_imap(imap_client()), self.assertRaises(frappe.ValidationError):
			download_attachment(self.test_account_email, "INBOX", UID, "0")


class TestFolderCounts(TestWebmailAPIBase):
	def test_unread_and_total_per_folder(self):
		from frappe_webmail.attachments import get_folder_counts

		client = imap_client()
		client.list_folders.return_value = [
			((b"\\HasNoChildren",), b"/", "INBOX"),
			((b"\\Noselect",), b"/", "[Gmail]"),
			((b"\\HasNoChildren",), b"/", "Fournisseurs"),
			((b"\\HasNoChildren",), b"/", "Refused"),
		]

		def status(name, items):
			if name == "Refused":
				raise Exception("STATUS failed: mailbox does not exist")
			return {
				"INBOX": {b"MESSAGES": 40, b"UNSEEN": 12},
				"Fournisseurs": {b"MESSAGES": 7, b"UNSEEN": 0},
			}[name]

		client.folder_status.side_effect = status
		with mocked_imap(client):
			counts = get_folder_counts(self.test_account_email)
		self.assertEqual(
			counts,
			{"INBOX": {"unseen": 12, "messages": 40}, "Fournisseurs": {"unseen": 0, "messages": 7}},
		)

		with mocked_imap(client):
			only = get_folder_counts(self.test_account_email, folders='["Fournisseurs"]')
		self.assertEqual(list(only), ["Fournisseurs"])


class TestAttachToDocument(TestWebmailAPIBase):
	"""Join an attachment to a Neoffice document: the right to write it, a private file in its attachments."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.todo = frappe.get_doc({"doctype": "ToDo", "description": "Webmail attach test"}).insert()
		frappe.set_user(self.test_user)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"File", {"attached_to_doctype": "ToDo", "attached_to_name": self.todo.name}, pluck="name"
		):
			frappe.delete_doc("File", name, force=True)
		frappe.delete_doc("ToDo", self.todo.name, force=True)
		super().tearDown()

	def test_the_attachment_becomes_a_private_file_of_the_document(self):
		from frappe_webmail.attachments import attach_to_document

		with mocked_imap(imap_client()):
			result = attach_to_document(self.test_account_email, "INBOX", UID, "0", "ToDo", self.todo.name)
		file = frappe.get_doc("File", result["file"])
		self.assertEqual((file.attached_to_doctype, file.attached_to_name), ("ToDo", self.todo.name))
		self.assertTrue(file.is_private)
		self.assertEqual(file.file_name, "Relevé 2026-118.pdf")
		self.assertEqual(file.get_content(), PDF)

	def test_a_document_the_person_cannot_write_is_refused(self):
		from frappe_webmail.attachments import attach_to_document

		with (
			mocked_imap(imap_client()),
			patch("frappe_webmail.attachments.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			attach_to_document(self.test_account_email, "INBOX", UID, "0", "ToDo", self.todo.name)
		self.assertFalse(frappe.db.exists("File", {"attached_to_name": self.todo.name}))
