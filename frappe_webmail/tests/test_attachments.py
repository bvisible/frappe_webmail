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
import unittest
from contextlib import contextmanager
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

import frappe
from pypdf import PdfWriter

from frappe_webmail.attachments import LAST_DRIVE_FOLDER
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


def _remove_from_drive(name):
	"""A Drive entry, the deepest first: a folder goes once it is empty."""
	for child in frappe.get_all("File", {"folder": name}, pluck="name"):
		_remove_from_drive(child)
	if frappe.db.exists("File", name):
		frappe.delete_doc("File", name, force=True, ignore_permissions=True)


class DriveCase(TestWebmailAPIBase):
	"""A folder of the test user's own Drive, removed afterwards, with everything put in it.

	A deposit commits once it holds the folder's names (drive.deposit, suite's hold_folder_names): what the tests made
	is no longer taken back by the class's rollback. Every folder made is kept in the class's list and removed for good
	at its end, with a commit."""

	# Every folder a test of the class made
	made: ClassVar[list] = []

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if "suite" not in frappe.get_installed_apps():
			raise unittest.SkipTest("the Drive (suite) is not installed on this site")
		cls.made = []

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in reversed(cls.made):
			_remove_from_drive(name)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		from suite.drive.api.files import create_folder

		self.created = []
		self.folder = create_folder(f"Webmail test {frappe.generate_hash(length=6)}").name
		self.created.append(self.folder)
		type(self).made.append(self.folder)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in reversed(self.created):
			_remove_from_drive(name)
		frappe.defaults.clear_user_default(LAST_DRIVE_FOLDER, self.test_user)
		super().tearDown()

	def save(self, attachment_id="0", folder=None):
		from frappe_webmail.attachments import save_attachment_to_drive

		with mocked_imap(imap_client()):
			return save_attachment_to_drive(
				self.test_account_email, "INBOX", UID, attachment_id, folder or self.folder
			)


class TestSaveToDrive(DriveCase):
	"""« Save to the Drive… »: the folder the person chose, the Drive's rules, the bytes where the Drive keeps them."""

	def test_the_attachment_lands_in_the_chosen_folder(self):
		from suite.drive.utils.files import FileManager, storage_key

		size_before = frappe.db.get_value("File", self.folder, "file_size") or 0
		result = self.save()
		saved = frappe.get_doc("File", result["name"])
		self.assertEqual(
			(saved.folder, saved.owner, saved.file_name), (self.folder, self.test_user, "Relevé 2026-118.pdf")
		)
		self.assertEqual(saved.mime_type, "application/pdf")
		self.assertEqual(Path(FileManager().site_folder / storage_key(saved.file_url)).read_bytes(), PDF)
		self.assertEqual(frappe.db.get_value("File", self.folder, "file_size"), size_before + len(PDF))
		self.assertEqual(result["url"], f"/drive/f/{saved.name}")
		# The next time, the picker proposes this folder first
		from frappe_webmail.attachments import get_drive_folders

		self.assertEqual(get_drive_folders()["last"]["name"], self.folder)

	def test_a_second_copy_gets_a_free_name(self):
		self.save()
		second = frappe.get_doc("File", self.save()["name"])
		self.assertEqual(second.file_name, "Relevé 2026-118 (1).pdf")

	def test_an_older_suite_names_deposits_as_before(self):
		from frappe_webmail import drive

		# A suite without hold_folder_names: the names as before, the deposit made all the same
		with patch.object(drive, "_name_lock", return_value=None):
			self.save()
			second = frappe.get_doc("File", self.save()["name"])
		self.assertEqual(second.file_name, "Relevé 2026-118 (1).pdf")

	def test_a_folder_the_person_may_not_fill_is_refused_before_reading_the_mail(self):
		from suite.drive.utils import get_user_folder

		from frappe_webmail.attachments import save_attachment_to_drive

		frappe.set_user("Administrator")
		private = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"Private {frappe.generate_hash(length=6)}",
				"is_folder": 1,
				"folder": get_user_folder("Administrator").name,
			}
		).insert(ignore_permissions=True)
		self.created.append(private.name)
		type(self).made.append(private.name)
		frappe.set_user(self.test_user)

		client = imap_client()
		with mocked_imap(client), self.assertRaises(frappe.PermissionError):
			save_attachment_to_drive(self.test_account_email, "INBOX", UID, "0", private.name)
		client.fetch.assert_not_called()

	def test_a_new_folder_is_made_by_the_drive_s_rules_and_can_be_filled(self):
		from frappe_webmail.attachments import create_drive_folder

		made = create_drive_folder(self.folder, "Factures / 2026")
		row = frappe.db.get_value("File", made["name"], ["is_folder", "folder", "file_name"], as_dict=True)
		self.assertEqual((row.is_folder, row.folder), (1, self.folder))
		# What would cut a path is left out of the name
		self.assertEqual(row.file_name, "Factures - 2026")
		self.assertTrue(made["can_write"])
		self.assertEqual(frappe.get_doc("File", self.save(folder=made["name"])["name"]).folder, made["name"])
		with self.assertRaises(frappe.ValidationError):
			create_drive_folder(self.folder, "Factures / 2026")

	def test_the_picker_starts_at_my_drive_and_finds_a_folder_by_name(self):
		from suite.drive.utils import get_user_folder

		from frappe_webmail.attachments import get_drive_folders

		home = get_user_folder().name
		roots = get_drive_folders()["folders"]
		self.assertEqual((roots[0]["name"], roots[0]["kind"], roots[0]["title"]), (home, "home", "My Drive"))
		inside = get_drive_folders(parent=home)["folders"]
		mine = next(f for f in inside if f["name"] == self.folder)
		self.assertTrue(mine["can_write"])
		title = frappe.db.get_value("File", self.folder, "file_name")
		found = get_drive_folders(search=title)["folders"]
		self.assertEqual([(f["name"], f["path"]) for f in found], [(self.folder, f"My Drive / {title}")])


class TestDocumentScan(TestWebmailAPIBase):
	"""« Create a scanned document »: once per file, a private source the scan owns, never the notifying channels."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("DocType", "Document Scan"):
			raise unittest.SkipTest("scanned documents (neoffice_theme) are not installed on this site")

	def setUp(self):
		super().setUp()
		self.enqueue = patch("frappe.enqueue")
		self.queued = self.enqueue.start()

	def tearDown(self):
		self.enqueue.stop()
		frappe.set_user("Administrator")
		import hashlib

		for name in frappe.get_all(
			"Document Scan", {"content_hash": hashlib.sha256(PDF).hexdigest()}, pluck="name"
		):
			for file in frappe.get_all(
				"File", {"attached_to_doctype": "Document Scan", "attached_to_name": name}, pluck="name"
			):
				frappe.delete_doc("File", file, force=True, ignore_permissions=True)
			frappe.delete_doc("Document Scan", name, force=True, ignore_permissions=True)
		super().tearDown()

	def scan(self):
		from frappe_webmail.attachments import create_document_scan_from_attachment

		with mocked_imap(imap_client()):
			return create_document_scan_from_attachment(self.test_account_email, "INBOX", UID, "0")

	def test_the_attachment_becomes_a_scan_read_by_the_ocr(self):
		result = self.scan()
		scan = frappe.get_doc("Document Scan", result["name"])
		self.assertFalse(result["duplicate"])
		self.assertEqual(scan.document_type, "Invoice")
		self.assertEqual(scan.intake_channel, "Upload")
		source = frappe.get_doc("File", {"file_url": scan.source_file})
		self.assertTrue(source.is_private)
		self.assertEqual((source.attached_to_doctype, source.attached_to_name), ("Document Scan", scan.name))
		self.assertEqual(source.get_content(), PDF)
		self.assertTrue(
			any("process_ocr" in str(call.args[0]) for call in self.queued.call_args_list),
			"the OCR is queued",
		)

	def test_the_same_file_is_never_scanned_twice(self):
		first = self.scan()
		again = self.scan()
		self.assertEqual((again["name"], again["duplicate"]), (first["name"], True))
		self.assertEqual(frappe.db.count("Document Scan", {"name": first["name"]}), 1)

	def test_someone_who_may_not_create_a_scan_is_refused(self):
		from frappe_webmail.attachments import create_document_scan_from_attachment

		with (
			mocked_imap(imap_client()),
			patch("frappe_webmail.scans.can_create", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			create_document_scan_from_attachment(self.test_account_email, "INBOX", UID, "0")


class TestTheMenu(TestWebmailAPIBase):
	"""Both screens draw the menu the server describes: the same entries, the same words, only what can run."""

	def test_the_menu_lists_what_this_site_can_do(self):
		from frappe_webmail.attachments import get_attachment_actions

		keys = [a["key"] for a in get_attachment_actions()]
		self.assertEqual(keys[:2], ["preview", "download"])
		self.assertEqual(keys[-1], "forward")
		self.assertEqual("save_to_drive" in keys, "suite" in frappe.get_installed_apps())
		self.assertEqual("document_scan" in keys, bool(frappe.db.exists("DocType", "Document Scan")))
		for action in get_attachment_actions():
			self.assertIn(action["kind"], ("client", "now", "pick_folder", "pick_document"))
			if action["kind"] != "client":
				self.assertTrue(frappe.get_attr(action["method"]))

	def test_without_the_drive_the_menu_has_no_drive(self):
		from frappe_webmail.attachments import get_attachment_actions

		with patch("frappe_webmail.drive.available", return_value=False):
			self.assertNotIn("save_to_drive", [a["key"] for a in get_attachment_actions()])


class TestComposerDrive(DriveCase):
	"""The composer's « From the Drive » tab reads the Drive of suite (it read the old app's Drive Entity, gone)."""

	def test_the_tab_lists_and_attaches_a_drive_file(self):
		from frappe_webmail.webmail_api import get_drive_file_content, get_drive_files

		saved = self.save()["name"]
		listed = get_drive_files(folder=self.folder)
		self.assertTrue(listed["installed"])
		self.assertEqual([f["name"] for f in listed["files"]], [saved])
		self.assertEqual(listed["files"][0]["title"], "Relevé 2026-118.pdf")
		content = get_drive_file_content(saved)
		self.assertEqual((content["filename"], content["size"]), ("Relevé 2026-118.pdf", len(PDF)))

	def test_a_file_the_person_may_not_read_is_refused(self):
		from frappe_webmail.webmail_api import get_drive_file_content

		saved = self.save()["name"]
		with (
			patch("frappe_webmail.drive.can_read", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			get_drive_file_content(saved)
