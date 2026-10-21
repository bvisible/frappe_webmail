# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""NeoMail's actions on an attachment (neomail_attachments.py): which part of the message NeoMail names (never by its
rank alone), in whose mailbox, how large, under which name, and where it goes. The mail server, the Drive and the
scanned documents are stood in for: nothing reaches a mailbox, a folder or the OCR, and the tests run on a bench
without the Drive (the app's CI).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_neomail_attachments
"""

import email
import re
from contextlib import contextmanager
from email import policy
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import neomail_attachments as files
from frappe_webmail.attachments import LAST_DRIVE_FOLDER
from frappe_webmail.tests.test_api import TestWebmailAPIBase

PDF = b"%PDF-1.4\n% a made-up invoice\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
# The plan's picture is not the logo's: they would otherwise be alike but for their names
PLAN = PNG + b"plan"
UID = 42
VALIDITY = 7
OTHER_MAILBOX = "webmail_attachments_other@webmail.test"
PORTAL = "webmail_attachments_portal@example.com"
# What NeoMail says of the invoice of `mail(invoice(), …)`: after the picture of the text, its second attachment.
INVOICE = {"index": 1, "name": "Relevé 2026-118.pdf", "size": len(PDF), "mime": "application/pdf"}
# What the page checks before it opens a file of the Drive (neomail_host.js, driveFileUrl).
DRIVE_FILE = re.compile(r"^/drive/[fd]/[A-Za-z0-9_-]+$")


def _named(part, name):
	"""`part` as an attachment named `name`, the name written as RFC 2231 has it (any character, accents included)."""
	part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", name))
	return part


def mail(*attached, inline_logo=True, forwarded=True):
	"""A message as a server holds it: its text in two renderings, a picture of the text (a Content-ID), the parts
	`attached` and an attached e-mail without a name."""
	msg = MIMEMultipart("mixed")
	msg["Subject"] = "Facture 2026-118"
	msg["From"] = "Grace Hopper <grace@example.org>"
	msg["To"] = "test_account@webmail.test"
	related = MIMEMultipart("related")
	body = MIMEMultipart("alternative")
	body.attach(MIMEText("Voici la facture.", "plain"))
	body.attach(MIMEText('<p>Voici la facture.</p><img src="cid:logo@example.org">', "html"))
	related.attach(body)
	if inline_logo:
		logo = MIMEImage(PNG, _subtype="png")
		logo.add_header("Content-ID", "<logo@example.org>")
		logo.add_header("Content-Disposition", "inline")
		related.attach(logo)
	msg.attach(related)
	for part in attached:
		msg.attach(part)
	if forwarded:
		inner = MIMEText("Le message transféré.", "plain")
		inner["Subject"] = "Transféré"
		msg.attach(MIMEMessage(inner))
	return msg.as_bytes()


def invoice(name="Relevé 2026-118.pdf", data=PDF):
	return _named(MIMEApplication(data, _subtype="pdf"), name)


def plan():
	"""A picture with a name and no disposition: an attachment all the same."""
	part = MIMEImage(PLAN, _subtype="png")
	part.set_param("name", "plan.png")
	return part


def wanted(name="", size=None, mime="", cid="", index=None, count=None):
	return files.Wanted(index, name, size, mime, files._cid(cid), count)


def parsed(raw):
	"""The message as `read` parses it."""
	return email.message_from_bytes(raw, policy=policy.default)


def found(raw, **hint):
	return files.find(parsed(raw), wanted(**hint))


def carried(subject):
	"""An e-mail as another one carries it attached: its own bytes, CRLF and all."""
	return (
		f"From: Grace Hopper <grace@example.org>\r\nSubject: {subject}\r\nMessage-ID: <{subject}@example.org>\r\n"
		"X-Long: one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen\r\n"
		f"\r\nThe text of {subject}.\r\n"
	).encode()


def raw_mail(*parts):
	"""A message written by hand, `parts` (headers and body, as bytes) after its text: what a library would not write."""
	out = b"From: z@example.org\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
	out += b"--XX\r\nContent-Type: text/plain\r\n\r\nHello\r\n"
	for part in parts:
		out += b"--XX\r\n" + part + b"\r\n"
	return out + b"--XX--\r\n"


def attached_mail(subject, name=b""):
	header = b"Content-Type: message/rfc822\r\nContent-Disposition: attachment" + name + b"\r\n\r\n"
	return header + carried(subject)


EMAIL_ID = jmap.email_id("INBOX", VALIDITY, UID)


def server(raw, validity=VALIDITY, size=None, sized=True):
	"""A mocked IMAP connection that holds `raw` as message UID in a folder of UIDVALIDITY `validity`, and says its
	size is `size` (its length unless said; nothing at all without `sized`)."""
	client = MagicMock()
	client.select_folder.return_value = {b"UIDVALIDITY": validity}

	def fetch(uids, items):
		if "RFC822.SIZE" in items:
			return {UID: {b"RFC822.SIZE": len(raw) if size is None else size} if sized else {}}
		return {UID: {b"BODY[]": raw}}

	client.fetch.side_effect = fetch
	return client


@contextmanager
def mocked_imap(client):
	with patch("frappe_webmail.webmail_api.IMAPClient") as imap_class:
		imap_class.return_value.__enter__ = MagicMock(return_value=client)
		imap_class.return_value.__exit__ = MagicMock(return_value=False)
		yield imap_class


def fetched(client):
	"""What was asked of the server, call by call."""
	return [call.args[1] for call in client.fetch.call_args_list]


class TestWhichAttachment(TestWebmailAPIBase):
	"""The part NeoMail names is found by what identifies it, never by its rank alone."""

	def test_the_parts_are_counted_as_neomail_counts_them(self):
		raw = mail(invoice(), plan())
		listed = [(c.rank, c.name, c.mime, c.cid) for c in files.candidates(parsed(raw))]
		# The picture of the text and the attached e-mail are NeoMail's attachments too; the text never is
		self.assertEqual(
			listed,
			[
				(0, None, "image/png", "logo@example.org"),
				(1, "Relevé 2026-118.pdf", "application/pdf", ""),
				(2, "plan.png", "image/png", ""),
				(3, None, "message/rfc822", ""),
			],
		)

	def test_the_content_id_finds_a_picture_whatever_else_is_said(self):
		part = found(
			mail(invoice()), name="other.png", size=1, mime="image/gif", cid="<logo@example.org>", index=9
		)
		self.assertEqual(part.cid, "logo@example.org")

	def test_the_name_size_and_type_find_it_whatever_rank_neomail_gives(self):
		raw = mail(invoice(), plan())
		part = found(raw, name="Relevé 2026-118.pdf", size=len(PDF), mime="application/pdf", index=3)
		self.assertEqual(part.rank, 1)
		# A name NeoMail reads otherwise (a decomposed accent, another case) is the same name
		part = found(raw, name="RELEVE\u0301 2026-118.PDF", size=len(PDF), mime="application/pdf", index=0)
		self.assertEqual(part.rank, 1)
		# A name read quite otherwise: its size and its type
		part = found(raw, name="Relev? 2026-118.pdf", size=len(PDF), mime="application/pdf", index=0)
		self.assertEqual(part.rank, 1)

	def test_an_attached_email_without_a_name_is_found_by_its_type(self):
		# NeoMail calls it message.eml; a size read otherwise still finds it, by its type
		part = found(mail(invoice()), name="message.eml", size=99_999, mime="message/rfc822", index=2)
		self.assertEqual(part.mime, "message/rfc822")
		# Saved under a name of its type
		self.assertEqual(files._file_name(part.name or files._unnamed(part)), "attachment.eml")

	def test_files_alike_are_told_apart_by_the_rank_and_refused_when_it_does_not(self):
		raw = mail(invoice("scan.pdf"), invoice("scan.pdf"), inline_logo=False, forwarded=False)
		alike = {"name": "scan.pdf", "size": len(PDF), "mime": "application/pdf", "count": 2}
		self.assertEqual(found(raw, index=1, **alike).rank, 1)
		self.assertEqual(found(raw, index=0, **alike).rank, 0)
		for hint in (
			{**alike, "index": 5},
			{**alike, "index": None},
			# NeoMail sees one less (removed on this computer): its rank is not the server's
			{**alike, "index": 0, "count": 1},
			# A NeoMail that says nothing of how many it sees
			{**alike, "index": 0, "count": None},
		):
			with self.assertRaisesRegex(frappe.ValidationError, "look alike", msg=hint):
				found(raw, **hint)

	def test_two_attached_emails_without_names_are_told_apart_by_their_own_bytes(self):
		# Before them, a part Python reads as a type of its own (a comment in its type), which NeoMail reads as text,
		# and a digest whose part declares no type: neither is an attachment for NeoMail, and the ranks agree
		digest = (
			b"Content-Type: multipart/digest; boundary=YY\r\n\r\n--YY\r\n\r\n"
			+ carried("Digest")
			+ b"\r\n--YY--"
		)
		raw = raw_mail(
			b"Content-Type: text/plain (list footer)\r\n\r\n-- the list's footer",
			digest,
			attached_mail("First"),
			attached_mail("Second"),
		)
		parts = files.candidates(parsed(raw))
		self.assertEqual(
			[(c.rank, c.mime, c.name) for c in parts],
			[(0, "message/rfc822", None), (1, "message/rfc822", None)],
		)
		# Each carried as the message carries it, byte for byte: its size is NeoMail's
		self.assertEqual([c.size for c in parts], [len(carried("First")), len(carried("Second"))])
		for index, subject in ((0, "First"), (1, "Second")):
			hint = {
				"name": "message.eml",
				"size": len(carried(subject)),
				"mime": "message/rfc822",
				"count": 2,
			}
			# Whatever rank NeoMail gives, and however many it counts
			for told in ({"index": index}, {"index": 1 - index}, {"index": index, "count": 3}):
				part = found(raw, **{**hint, **told})
				self.assertEqual(part.part.get_payload()[0]["Subject"], subject, told)
		# The same e-mail attached twice: only the rank tells them apart, and only when the counts agree
		twice = raw_mail(attached_mail("Same"), attached_mail("Same"))
		hint = {"name": "message.eml", "size": len(carried("Same")), "mime": "message/rfc822"}
		self.assertEqual(found(twice, index=1, count=2, **hint).rank, 1)
		with self.assertRaisesRegex(frappe.ValidationError, "look alike"):
			found(twice, index=1, count=1, **hint)

	def test_an_attached_email_is_written_back_as_it_was_carried(self):
		from frappe_webmail.webmail_api import attachment_bytes

		# CRLF line ends and its headers as they were folded (a long one included)
		raw = raw_mail(attached_mail("Kept"))
		for message in (email.message_from_bytes(raw), parsed(raw)):
			part = message.get_payload()[1]
			self.assertEqual(attachment_bytes(part), carried("Kept"))

	def test_every_attached_message_is_written_back_never_left_empty(self):
		from frappe_webmail.webmail_api import attachment_bytes

		report = (
			b"Reporting-MTA: dns; mx.example.org\r\n\r\n"
			b"Final-Recipient: rfc822; ada@example.org\r\nAction: failed\r\nStatus: 5.1.1\r\n"
		)
		receipt = b"Final-Recipient: rfc822; ada@example.org\r\nDisposition: manual-action/MDN-sent-manually; displayed\r\n"
		kinds = (
			(b"message/global", carried("Global"), True),
			(b"message/delivery-status", report, True),
			# A receipt is one block of fields, which Python writes back with the blank line that ends it
			(b"message/disposition-notification", receipt, False),
		)
		raw = raw_mail(*(b"Content-Type: " + kind + b"\r\n\r\n" + body for kind, body, _same in kinds))
		parts = parsed(raw).get_payload()[1:]
		for part, (kind, body, same) in zip(parts, kinds, strict=True):
			written = attachment_bytes(part)
			self.assertTrue(written, kind)
			if same:
				self.assertEqual(written, body, kind)
			else:
				self.assertEqual(written, body + b"\r\n", kind)
		# Named after what they are when the message names nothing
		names = [files._unnamed(c) for c in files.candidates(parsed(raw))]
		self.assertEqual(names, ["attachment.eml", "attachment.txt", "attachment.txt"])

	def test_no_empty_file_is_saved_where_neomail_sees_one(self):
		raw = mail(invoice())
		with (
			patch("frappe_webmail.webmail_api.attachment_bytes", return_value=b""),
			mocked_imap(server(raw)),
			self.assertRaisesRegex(frappe.ValidationError, "cannot be read from its message"),
		):
			files.read(self.test_account_email, EMAIL_ID, INVOICE)

	def test_a_name_is_read_as_the_message_wrote_it(self):
		pdf = b"Content-Type: application/pdf\r\n"
		written = (
			# UTF-8 as it is, RFC 2231, RFC 2047 in quotes (common, against the RFC), RFC 2047 in the type's name
			pdf + b'Content-Disposition: attachment; filename="Relev\xc3\xa9 \xc3\xa9t\xc3\xa9.pdf"',
			pdf + b"Content-Disposition: attachment; filename*=utf-8''Relev%C3%A9%20%C3%A9t%C3%A9.pdf",
			pdf + b'Content-Disposition: attachment; filename="=?utf-8?q?Relev=C3=A9_=C3=A9t=C3=A9.pdf?="',
			b'Content-Type: application/pdf; name="=?iso-8859-1?q?Relev=E9_=E9t=E9.pdf?="',
			# Against the rules, read as NeoMail reads them: unquoted with a space, an encoded word unquoted
			pdf + b"Content-Disposition: attachment; filename=Relev\xc3\xa9 \xc3\xa9t\xc3\xa9.pdf",
			pdf + b"Content-Disposition: attachment; filename==?UTF-8?B?UmVsZXbDqSDDqXTDqS5wZGY=?=",
		)
		raw = raw_mail(*(headers + b"\r\n\r\n%PDF" for headers in written))
		self.assertEqual([c.name for c in files.candidates(parsed(raw))], ["Relevé été.pdf"] * 6)
		with mocked_imap(server(raw)):
			name, _mime, _data = files.read(
				self.test_account_email, EMAIL_ID, {"index": 0, "name": "Relevé été.pdf", "count": 6}
			)
		self.assertEqual(name, "Relevé été.pdf")

	def test_a_name_against_the_rules_keeps_its_extension(self):
		scan = raw_mail(
			b"Content-Type: application/pdf\r\nContent-Disposition: attachment; filename=Scan 01.pdf\r\n\r\n%PDF"
		)
		self.assertEqual([c.name for c in files.candidates(parsed(scan))], ["Scan 01.pdf"])
		# And opens in its editor: its extension is there
		self.assertEqual(files.editor(files._name_of(parsed(scan).get_payload()[1])), ("pdf", "NeoPDF"))
		word = raw_mail(
			b"Content-Type: application/pdf\r\nContent-Disposition: attachment; filename==?UTF-8?B?w6l0w6kucGRm?=\r\n\r\n%PDF"
		)
		self.assertEqual([c.name for c in files.candidates(parsed(word))], ["été.pdf"])

	def test_an_attachment_that_is_not_in_the_message_is_refused(self):
		raw = mail(invoice())
		for hint in (
			{"name": "contrat.docx", "size": 12, "mime": "application/vnd.ms-word", "index": 1},
			{"index": 1},
			{"cid": "nobody@example.org", "index": 0},
		):
			with self.assertRaisesRegex(frappe.ValidationError, "cannot be found", msg=hint):
				found(raw, **hint)

	def test_a_description_is_taken_only_for_what_it_is(self):
		self.assertEqual(
			files._wanted(
				'{"index": 2, "name": "a.pdf", "size": 10, "mime": "Application/PDF", "cid": " <x@y> "}'
			),
			files.Wanted(2, "a.pdf", 10, "application/pdf", "x@y"),
		)
		self.assertEqual(files._wanted({"name": "a.pdf", "count": 3}).count, 3)
		self.assertIsNone(files._wanted({"name": "a.pdf", "count": "3"}).count)
		self.assertEqual(
			files._wanted({"index": True, "name": 5, "size": -1, "mime": None, "cid": ["x"]}),
			files.Wanted(None, "", None, "", ""),
		)
		self.assertEqual(len(files._wanted({"name": "a" * 5000}).name), files.MAX_HINT)
		for wrong in ("not json", '["a"]', None, 7):
			self.assertRaises(frappe.ValidationError, files._wanted, wrong)


class TestReadingIt(TestWebmailAPIBase):
	"""Whose mailbox, how large, which message: all said before the mail is read."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Webmail Account", OTHER_MAILBOX):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": OTHER_MAILBOX,
					"user": "Administrator",
					"sender_name": "Someone else",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def test_the_attachment_is_read_from_its_message_on_the_server_without_marking_it_read(self):
		raw = mail(invoice(), plan())
		client = server(raw)
		with mocked_imap(client):
			name, mime, data = files.read(
				self.test_account_email,
				EMAIL_ID,
				{"index": 1, "name": "Relevé 2026-118.pdf", "size": len(PDF), "mime": "application/pdf"},
			)
		self.assertEqual((name, mime, data), ("Relevé 2026-118.pdf", "application/pdf", PDF))
		# Its size first, then the message, never anything that marks it read
		self.assertEqual(fetched(client), [["RFC822.SIZE"], ["BODY.PEEK[]"]])
		for call in client.select_folder.call_args_list:
			self.assertTrue(call.kwargs.get("readonly"))

	def test_another_s_mailbox_is_refused_before_any_mail_is_read(self):
		client = server(mail(invoice()))
		with mocked_imap(client) as imap_class:
			for account in (OTHER_MAILBOX, "webmail_attachments_nobody@webmail.test"):
				with self.assertRaisesRegex(frappe.ValidationError, "Account not found", msg=account):
					files.read(account, EMAIL_ID, {"index": 0, "name": "Relevé 2026-118.pdf"})
		imap_class.assert_not_called()
		client.fetch.assert_not_called()

	def test_a_message_over_the_cap_is_refused_before_it_is_read(self):
		client = server(mail(invoice()), size=files.MAX_SOURCE + 1)
		with mocked_imap(client), self.assertRaisesRegex(frappe.ValidationError, "larger than 30 MB"):
			files.read(self.test_account_email, EMAIL_ID, {"index": 1, "name": "Relevé 2026-118.pdf"})
		self.assertEqual(fetched(client), [["RFC822.SIZE"]], "the message itself was never asked for")

	def test_a_mailbox_shared_with_the_person_is_read_as_their_own(self):
		shared = "webmail_attachments_shared@webmail.test"
		if not frappe.db.exists("Webmail Account", shared):
			account = frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": shared,
					"user": "Administrator",
					"sender_name": "The office",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			)
			account.append("allowed_users", {"user": self.test_user})
			account.insert(ignore_permissions=True)
		with mocked_imap(server(mail(invoice()))):
			name, _mime, data = files.read(shared, EMAIL_ID, INVOICE)
		self.assertEqual((name, data), ("Relevé 2026-118.pdf", PDF))

	def test_a_size_the_server_does_not_say_or_says_wrong_is_refused(self):
		# No size: the message is gone, and nothing more is asked
		client = server(mail(invoice()), sized=False)
		with mocked_imap(client), self.assertRaisesRegex(frappe.ValidationError, "no longer in its folder"):
			files.read(self.test_account_email, EMAIL_ID, INVOICE)
		self.assertEqual(fetched(client), [["RFC822.SIZE"]])
		# A server that says less than it gives: what it gave is measured too
		raw = mail(invoice())
		with (
			patch.object(files, "MAX_SOURCE", len(raw) - 1),
			mocked_imap(server(raw, size=10)),
			self.assertRaisesRegex(frappe.ValidationError, "larger than"),
		):
			files.read(self.test_account_email, EMAIL_ID, INVOICE)

	def test_a_message_moved_or_gone_and_an_id_that_is_none_are_refused(self):
		hint = {"index": 1, "name": "Relevé 2026-118.pdf"}
		# Its folder was made again: the UID could name another message
		client = server(mail(invoice()), validity=VALIDITY + 1)
		with mocked_imap(client), self.assertRaisesRegex(frappe.ValidationError, "no longer in its folder"):
			files.read(self.test_account_email, EMAIL_ID, hint)
		client.fetch.assert_not_called()
		# Not a message's id: refused before the server is asked anything
		with mocked_imap(server(mail(invoice()))) as imap_class:
			for wrong in ("M7", "B7V42ZSU5CT1g", "../../etc", "", None):
				self.assertRaises(frappe.ValidationError, files.read, self.test_account_email, wrong, hint)
		imap_class.assert_not_called()

	def test_a_hostile_name_keeps_nothing_a_path_or_a_control_character_could_slip_in(self):
		hostile = (
			("Facture\u202egpj.exe", "Facturegpj.exe"),
			("../../etc/passwd.pdf", "passwd.pdf"),
			("a\x07b\r\nc.pdf", "abc.pdf"),
			('C:\\temp\\fac<t>ure".pdf', "facture.pdf"),
		)
		raw = mail(*(invoice(name, data=PDF + str(n).encode()) for n, (name, _clean) in enumerate(hostile)))
		for n, (name, clean) in enumerate(hostile):
			with mocked_imap(server(raw)):
				got, _mime, _data = files.read(
					self.test_account_email,
					EMAIL_ID,
					{"index": n + 1, "name": name, "size": len(PDF) + 1, "mime": "application/pdf"},
				)
			self.assertEqual(got, clean, repr(name))
			self.assertFalse(any(not ch.isprintable() for ch in got), repr(got))


class TestWhereItGoes(TestWebmailAPIBase):
	"""The Drive, the scanned documents, an editor: by the old webmail's doors, with their refusals first."""

	@contextmanager
	def drive(self, editors=("pdf",)):
		"""The Drive stood in for: a folder the person may fill, and what is put in it."""
		put = []

		def deposit(payload, name, folder):
			put.append((payload, name, folder))
			return SimpleNamespace(name="a1B2c3_d4-e5", file_name=name)

		with (
			patch.object(files, "_gate"),
			patch("frappe_webmail.drive.available", return_value=True),
			patch(
				"frappe_webmail.drive.folder_entry",
				side_effect=lambda f: {"name": f, "path": "My Drive / Invoices"} if f == "folder-1" else None,
			),
			patch("frappe_webmail.drive.deposit", side_effect=deposit),
			patch.object(files, "installed_editors", return_value=set(editors)),
		):
			yield put

	def test_the_drive_gets_the_file_and_the_page_its_address(self):
		with self.drive() as put, mocked_imap(server(mail(invoice()))):
			answer = files.save_to_drive(
				account=self.test_account_email, email=EMAIL_ID, attachment=INVOICE, drive_folder="folder-1"
			)
		self.assertEqual(put, [(PDF, "Relevé 2026-118.pdf", "folder-1")])
		self.assertRegex(answer["url"], DRIVE_FILE)
		self.assertRegex(answer["folder_url"], DRIVE_FILE)
		self.assertEqual(answer["file_name"], "Relevé 2026-118.pdf")
		self.assertIn("My Drive / Invoices", answer["message"])
		self.assertEqual(
			frappe.defaults.get_user_default(LAST_DRIVE_FOLDER), "folder-1", "proposed first next time"
		)

	def test_a_drive_file_is_a_name_never_an_object(self):
		from frappe_webmail import drive

		with (
			patch.object(drive, "available", return_value=True),
			patch.object(frappe.db, "get_value") as looked,
		):
			for name in ({"name": ["like", "%"]}, ["x"], 7, None, "", "x" * 500):
				with self.assertRaises(frappe.DoesNotExistError, msg=repr(name)):
					drive.read(name)
		looked.assert_not_called()

	def test_a_name_and_its_number_stay_within_the_drive_s_length(self):
		from frappe_webmail import drive

		taken = {"a" * 136 + ".pdf"}

		def free(name):
			stem, ext = name.rsplit(".", 1)
			return name if name not in taken else f"{stem} (1).{ext}"

		self.assertEqual(drive.bounded_free("short.pdf", free), "short.pdf")
		chosen = drive.bounded_free("a" * 136 + ".pdf", free)
		self.assertLessEqual(len(chosen), drive.MAX_NAME)
		self.assertTrue(chosen.endswith(".pdf"))
		self.assertNotIn(chosen, taken)
		# A folder that numbers every name it is asked: the stem is cut before the number
		numbered = drive.bounded_free("b" * 136 + ".pdf", lambda name: name[:-4] + " (1).pdf")
		self.assertEqual(len(numbered), drive.MAX_NAME)
		self.assertTrue(numbered.endswith("b (1).pdf"))

	def test_an_older_suite_names_deposits_as_before_and_says_so_once(self):
		from frappe_webmail import drive

		def hold(folder, commit=False):
			return None

		def free(name, folder, locking=True):
			return name

		self.assertEqual(
			drive._name_lock(SimpleNamespace(hold_folder_names=hold, free_file_name=free)), (hold, free)
		)
		with patch.object(drive, "_UNLOCKED_SAID", False), patch.object(frappe, "log_error") as logged:
			self.assertIsNone(drive._name_lock(SimpleNamespace(hold_folder_names=hold)))
			self.assertIsNone(drive._name_lock(SimpleNamespace()))
		logged.assert_called_once()
		# The title first, then what it means
		self.assertEqual(logged.call_args.args[0], "Webmail: Drive deposits named without the folder's lock")
		self.assertIn("hold_folder_names", logged.call_args.args[1])

	def test_a_folder_is_a_name_never_an_object(self):
		from frappe_webmail import drive

		client = server(mail(invoice()))
		with self.drive() as put, mocked_imap(client):
			for folder in ({"name": ["like", "%"]}, ["folder-1"], 7, None, "folder-1" + "x" * 500):
				with self.assertRaises(frappe.PermissionError, msg=repr(folder)):
					files.save_to_drive(self.test_account_email, EMAIL_ID, INVOICE, folder)
		client.fetch.assert_not_called()
		self.assertEqual(put, [])
		# The Drive's door takes no object either: it would be the filters of its query
		for folder in ({"name": ["like", "%"]}, ["x"], None, ""):
			self.assertIsNone(drive._folder_row(folder))

	def test_a_folder_the_person_may_not_fill_is_refused_before_the_mail_is_read(self):
		client = server(mail(invoice()))
		with self.drive() as put, mocked_imap(client), self.assertRaises(frappe.PermissionError):
			files.save_to_drive(
				account=self.test_account_email, email=EMAIL_ID, attachment=INVOICE, drive_folder="folder-2"
			)
		client.fetch.assert_not_called()
		self.assertEqual(put, [])

	def test_an_editor_opens_only_its_own_type_and_only_where_it_is_installed(self):
		raw = mail(invoice(), plan())
		picture = {"index": 2, "name": "plan.png", "size": len(PLAN), "mime": "image/png"}
		client = server(raw)
		with self.drive() as put, mocked_imap(client):
			with self.assertRaisesRegex(frappe.ValidationError, r"\.docx, \.xlsx, \.pptx or \.pdf"):
				files.save_to_drive(self.test_account_email, EMAIL_ID, picture, "folder-1", edit=1)
			client.fetch.assert_not_called()
			answer = files.save_to_drive(self.test_account_email, EMAIL_ID, INVOICE, "folder-1", edit=1)
			self.assertRegex(answer["url"], DRIVE_FILE)
		with self.drive(editors=("docx",)) as put, mocked_imap(server(raw)):
			with self.assertRaisesRegex(frappe.ValidationError, "NeoPDF is not installed"):
				files.save_to_drive(self.test_account_email, EMAIL_ID, INVOICE, "folder-1", edit=1)
		self.assertEqual(put, [])
		# A NeoMail that calls a picture a PDF: the name the message gives decides
		lying = {**picture, "name": "plan.pdf"}
		with self.drive() as put, mocked_imap(server(raw)):
			with self.assertRaisesRegex(frappe.ValidationError, r"\.docx, \.xlsx, \.pptx or \.pdf"):
				files.save_to_drive(self.test_account_email, EMAIL_ID, lying, "folder-1", edit=1)
		self.assertEqual(put, [])

	def test_the_scanned_documents_take_a_pdf_or_a_picture_by_their_own_door(self):
		made = []

		def create(payload, name, document_type="Invoice"):
			made.append((payload, name, document_type))
			return {"name": "SCAN-0001", "duplicate": len(made) > 1, "url": "/app/document-scan/SCAN-0001"}

		hostile = invoice("..\\..\\Facture\u202efdp.pdf")
		raw = mail(hostile, plan())
		hint = {
			"index": 1,
			"name": "..\\..\\Facture\u202efdp.pdf",
			"size": len(PDF),
			"mime": "application/pdf",
		}
		with (
			patch.object(files, "_gate"),
			patch("frappe_webmail.scans.can_create", return_value=True),
			patch("frappe_webmail.scans.create", side_effect=create),
		):
			with mocked_imap(server(raw)):
				first = files.to_scans(self.test_account_email, EMAIL_ID, hint)
				again = files.to_scans(self.test_account_email, EMAIL_ID, hint)
			client = server(raw)
			with mocked_imap(client), self.assertRaisesRegex(frappe.ValidationError, "PDF or a picture"):
				files.to_scans(self.test_account_email, EMAIL_ID, {"index": 3, "name": "message.eml"})
			client.fetch.assert_not_called()
		# The name cleaned for the scanned documents too
		self.assertEqual(made[0], (PDF, "Facturefdp.pdf", "Invoice"))
		self.assertFalse(first["duplicate"])
		self.assertTrue(again["duplicate"])
		self.assertIn("about a minute", first["message"])

	def test_someone_who_may_not_create_a_scan_is_refused_before_the_mail_is_read(self):
		client = server(mail(invoice()))
		with (
			patch.object(files, "_gate"),
			patch("frappe_webmail.scans.can_create", return_value=False),
			mocked_imap(client),
			self.assertRaises(frappe.PermissionError),
		):
			files.to_scans(self.test_account_email, EMAIL_ID, INVOICE)
		client.fetch.assert_not_called()


class TestWhoAndWhat(TestWebmailAPIBase):
	"""What NeoMail is offered, and who may ask."""

	def test_what_is_offered_is_the_old_webmail_s_menu_and_the_drive_s_editors(self):
		def menu(*keys):
			return patch(
				"frappe_webmail.attachments.get_attachment_actions", return_value=[{"key": k} for k in keys]
			)

		with menu("preview", "download", "save_to_drive", "document_scan", "forward"):
			with patch.object(files, "installed_editors", return_value={"docx"}):
				self.assertEqual(files.offered(), ["drive", "scan", "edit"])
			with patch.object(files, "installed_editors", return_value=set()):
				self.assertEqual(files.offered(), ["drive", "scan"])
		with menu("preview", "document_scan"), patch.object(files, "installed_editors", return_value={"pdf"}):
			self.assertEqual(files.offered(), ["scan"], "no editor without the Drive")
		with menu("preview", "download"):
			self.assertEqual(files.offered(), [])

	def test_types_follow_neomail_s_rule(self):
		self.assertTrue(files.scannable("Facture.PDF", "application/octet-stream"))
		self.assertTrue(files.scannable("photo.heic", ""))
		self.assertTrue(files.scannable("scan", "image/jpeg"))
		self.assertFalse(files.scannable("plan.svg", "image/svg+xml"))
		self.assertFalse(files.scannable("virus.exe", "application/pdf"), "the name's extension decides")
		self.assertEqual(files.editor("Budget 2026.XLSX"), ("xlsx", "NeoGrille"))
		self.assertEqual(files.editor("deck.pptx"), ("pptx", "NeoPrés"))
		self.assertEqual(files.editor("a.docx"), ("docx", "NeoDoc"))
		self.assertEqual(files.editor("a.pdf"), ("pdf", "NeoPDF"))
		self.assertIsNone(files.editor("a.doc"))
		self.assertIsNone(files.editor("pdf"))

	def test_the_page_s_calls_only_for_the_desk_s_people_by_post(self):
		if not frappe.db.exists("User", PORTAL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": PORTAL,
					"first_name": "Portal",
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		with (
			patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk", return_value=True),
			patch("frappe_webmail.mailcraft_jmap.page_request_only"),
			patch("frappe_webmail.mailcraft_jmap.csrf_token_required"),
		):
			for user in (PORTAL, "Guest"):
				frappe.set_user(user)
				for call in (files.save_to_drive, files.to_scans):
					with self.assertRaises(frappe.PermissionError, msg=(user, call.__name__)):
						call(
							account=self.test_account_email,
							email=EMAIL_ID,
							attachment={"index": 0, "name": "a.pdf"},
						)
		frappe.set_user("Administrator")
		# A request with a token rather than the desk's cookie (a facade token, Neodesk's OAuth token) is refused
		with (
			patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk", return_value=True),
			patch.object(frappe, "get_request_header", side_effect=lambda name, *a: "Bearer x"),
			self.assertRaises(frappe.PermissionError),
		):
			files.save_to_drive(
				account=self.test_account_email, email=EMAIL_ID, attachment={"index": 0, "name": "a.pdf"}
			)
		# Where the page is not offered, the calls are a page that does not exist
		with patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk", return_value=False):
			self.assertRaises(frappe.PageDoesNotExistError, files.to_scans)
		from frappe_webmail.attachments import create_drive_folder

		for call in (files.save_to_drive, files.to_scans, create_drive_folder):
			self.assertIn(call, frappe.whitelisted)
			self.assertNotIn(call, frappe.guest_methods)
			self.assertEqual(list(frappe.allowed_http_methods_for_whitelisted_func[call]), ["POST"])

	def test_the_session_s_csrf_token_is_asked_for(self):
		sent = {}
		attachment = {"index": 0, "name": "a.pdf"}
		with (
			patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk", return_value=True),
			patch("frappe.get_request_header", side_effect=lambda key, default=None: sent.get(key, default)),
			patch("frappe_webmail.drive.available", return_value=False),
		):
			for token in (None, "not-the-session-s"):
				if token:
					sent["X-Frappe-CSRF-Token"] = token
				for call in (files.save_to_drive, files.to_scans):
					with self.assertRaises(frappe.CSRFTokenError, msg=(token, call.__name__)):
						call(account=self.test_account_email, email=EMAIL_ID, attachment=attachment)
			# The session's own: past the gate, to the Drive's own refusal
			sent["X-Frappe-CSRF-Token"] = frappe.sessions.get_csrf_token()
			with self.assertRaisesRegex(frappe.ValidationError, "Drive is not installed"):
				files.save_to_drive(account=self.test_account_email, email=EMAIL_ID, attachment=attachment)

	def test_calls_are_counted_for_each_person(self):
		def probe():
			return "ok"

		probe.__name__ = "probe_" + frappe.generate_hash(length=10)
		limited = files.per_person(probe)
		with patch.object(frappe.local, "request", SimpleNamespace(), create=True):
			for _call in range(files.CALLS_A_MINUTE):
				self.assertEqual(limited(), "ok")
			with self.assertRaises(frappe.RateLimitExceededError):
				limited()
			# Someone else has a count of their own
			frappe.set_user("Administrator")
			self.assertEqual(limited(), "ok")
		# Outside a request (a script, a test) nothing is counted
		frappe.set_user(self.test_user)
		self.assertEqual(limited(), "ok")

	def test_a_count_always_ends_with_its_minute(self):
		def probe():
			return "ok"

		probe.__name__ = "probe_" + frappe.generate_hash(length=10)
		limited = files.per_person(probe)
		key = files._count_key(probe.__name__)
		with patch.object(frappe.local, "request", SimpleNamespace(), create=True):
			limited()
			self.assertTrue(0 < frappe.cache.ttl(key) <= 60, "the first call gives the count its minute")
			# A count left without one (as a reading then a write could leave it) gets it back at the next call
			frappe.cache.set(key, 5)
			self.assertEqual(frappe.cache.ttl(key), -1)
			limited()
			self.assertTrue(0 < frappe.cache.ttl(key) <= 60)
			self.assertEqual(int(frappe.cache.get(key)), 6)
		frappe.cache.delete(key)
