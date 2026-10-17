# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""An image written in the text of a message leaves as a part of it, named by the Content-ID its `<img>` points to
(« cid: »), in a message sent and in a draft; before, the cleaning dropped the `data:` image and the recipient saw none.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_inline_images
"""

import base64
import email
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

import frappe_webmail.inline_images as inline_images
from frappe_webmail.inline_images import files_inlined, to_parts
from frappe_webmail.mime_parts import is_attachment
from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import imap_client, mocked_imap
from frappe_webmail.tests.test_forward import files_of
from frappe_webmail.tests.test_replies import drafts_client

# A one-pixel PNG
PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
TEXT = (
	f'<p>La niche :</p><p><img src="data:image/png;base64,{base64.b64encode(PNG).decode()}" alt="niche"></p>'
)


def images_of(message):
	"""The image parts of a message and the Content-IDs its HTML points to."""
	html = (
		next(p for p in message.walk() if p.get_content_type() == "text/html")
		.get_payload(decode=True)
		.decode()
	)
	images = [p for p in message.walk() if p.get_content_maintype() == "image"]
	return html, images


class TestImagesAsParts(FrappeTestCase):
	def test_a_data_image_becomes_a_part_the_html_points_to(self):
		html, parts = to_parts(TEXT, "example.com")
		self.assertEqual(len(parts), 1)
		cid = parts[0]["Content-ID"].strip("<>")
		self.assertIn(f'src="cid:{cid}"', html)
		self.assertNotIn("data:", html)
		self.assertEqual(parts[0].get_payload(decode=True), PNG)
		self.assertEqual(parts[0].get_content_type(), "image/png")
		# Inline and nameless: read back, it is shown in the text, not listed as an attachment
		self.assertFalse(is_attachment(parts[0]))

	def test_a_text_without_image_or_with_broken_bytes_is_left_as_it_was(self):
		self.assertEqual(to_parts("<p>Bonjour</p>", "example.com"), ("<p>Bonjour</p>", []))
		broken = '<img src="data:image/png;base64,@@not-base64@@">'
		self.assertEqual(to_parts(broken, "example.com"), (broken, []))


class TestImagesLeaveWithTheMessage(TestWebmailAPIBase):
	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_a_message_sent_carries_its_image_in_its_text(self, smtp_class):
		from frappe_webmail.api import send_email

		server = MagicMock()
		smtp_class.return_value = server
		# The copy kept in « Envoyés » goes through the mailbox: a mocked one
		with mocked_imap(imap_client()):
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="La niche",
				html_content=TEXT,
			)
		sent = email.message_from_string(server.sendmail.call_args.args[2])
		html, images = images_of(sent)
		self.assertEqual(len(images), 1)
		# The cleaning kept the part's address, and the part sits beside the text (multipart/related)
		self.assertIn(f'cid:{images[0]["Content-ID"].strip("<>")}', html)
		self.assertIn("multipart/related", [p.get_content_type() for p in sent.walk()])
		self.assertEqual(files_of(server), [])

	def test_a_draft_keeps_its_image_as_a_part(self):
		from frappe_webmail.api import save_draft_imap

		with mocked_imap(drafts_client()) as client:
			save_draft_imap(
				self.test_account_email, to="marc@example.com", subject="La niche", html_content=TEXT
			)
		saved = email.message_from_bytes(client.append.call_args.args[1])
		html, images = images_of(saved)
		self.assertEqual(len(images), 1)
		self.assertIn(f'cid:{images[0]["Content-ID"].strip("<>")}', html)
		self.assertFalse(is_attachment(images[0]))


class TestTheInstancePicturesGoAsParts(TestWebmailAPIBase):
	"""A signature's logo, which Frappe keeps as a private file of that signature, leaves as a part of the message sent
	(maintenance#1650): sent as an address, it reached the recipient as a private address of another site."""

	def _signature(self, content=PNG):
		"""A signature of the person with a pasted logo, and the address Frappe stored the logo at."""
		signature = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": self.test_user,
				"signature_name": f"inline-1650-{frappe.generate_hash(length=8)}",
				"content": f'<p>Camille</p><p><img src="data:image/png;base64,{base64.b64encode(content).decode()}"></p>',
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "Email Signature", signature.name, force=True, ignore_permissions=True
		)
		urls = frappe.get_all(
			"File",
			{"attached_to_doctype": "Email Signature", "attached_to_name": signature.name},
			pluck="file_url",
		)
		self.assertEqual(len(urls), 1, "Frappe keeps the pasted logo as a file of the signature")
		self.assertIn(urls[0], signature.content)
		return signature, urls[0]

	def _file(self, extension="png", content=PNG, private=1, as_user=None):
		"""A file of `as_user` (the person by default), attached to nothing, removed after the test."""
		frappe.set_user(as_user or self.test_user)
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"inline-1650-{frappe.generate_hash(length=8)}.{extension}",
				"content": content,
				"is_private": private,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.test_user)
		self.addCleanup(frappe.delete_doc, "File", file.name, force=True, ignore_permissions=True)
		return file.file_url

	def test_the_signature_s_logo_and_a_public_picture_are_written_in(self):
		_, logo = self._signature()
		written = f"data:image/png;base64,{base64.b64encode(PNG).decode()}"
		self.assertIn(
			f'src="{written}"', files_inlined(f'<p>Camille</p><p><img src="{logo}" alt="logo"></p>')
		)
		absolute = files_inlined(f"<img src='{frappe.utils.get_url()}{logo}'>")
		self.assertIn(f"src='{written}'", absolute, "this site's own address, its quote kept")
		self.assertIn(written, files_inlined(f'<img src="{self._file(private=0)}">'), "a public picture")
		self.assertIn(
			written, files_inlined(f'<img src="{logo}?fid=0123456789">'), "as Frappe serves it, with ?fid"
		)

	def test_what_must_not_go_or_a_client_would_not_show_stays(self):
		addresses = (
			# A private file the person may read but that is not their signature's: an address a quoted message names
			self._file(),
			self._file(as_user="Administrator"),
			self._file(extension="txt", content=b"Not a picture"),
			self._file(extension="svg", content=b"<svg xmlns='http://www.w3.org/2000/svg'/>", private=0),
			"https://elsewhere.example/files/logo.png",
			"/private/files/inline-1650-gone.png",
			"http://[x/a.png",
			"/app/file",
		)
		for address in addresses:
			html = f'<img src="{address}">'
			self.assertEqual(files_inlined(html), html, address)
		with patch.object(inline_images, "MAX_FILE_IMAGE", len(PNG) - 1):
			heavy = f'<img src="{self._signature()[1]}">'
			self.assertEqual(files_inlined(heavy), heavy, "too big: the address stays")

	def test_a_colleague_s_signature_logo_stays_an_address(self):
		"""Frappe stores one logo pasted by several people once: the person's own row decides, not the colleague's."""
		colleague = "inline_1650_colleague@example.com"
		if not frappe.db.exists("User", colleague):
			frappe.get_doc(
				{"doctype": "User", "email": colleague, "first_name": "Colleague", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		other = PNG + b"colleague"  # bytes of their own, so that the file is theirs alone
		signature = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": colleague,
				"signature_name": f"inline-1650-{frappe.generate_hash(length=8)}",
				"content": f'<p><img src="data:image/png;base64,{base64.b64encode(other).decode()}"></p>',
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "Email Signature", signature.name, force=True, ignore_permissions=True
		)
		logo = frappe.get_all(
			"File",
			{"attached_to_doctype": "Email Signature", "attached_to_name": signature.name},
			pluck="file_url",
		)[0]
		html = f'<img src="{logo}">'
		self.assertEqual(files_inlined(html), html)
		# The same logo pasted in the person's own signature too: one address, their row lets it go.
		_, own = self._signature(content=other)
		self.assertEqual(own, logo, "Frappe shares the address of identical bytes")
		self.assertIn("data:image/png", files_inlined(html))

	def test_a_colleague_looking_at_the_logo_s_file_is_refused_not_crashed(self):
		_, logo = self._signature()
		name = frappe.db.get_value("File", {"file_url": logo})
		frappe.set_user("Administrator")
		other = "inline_1650_colleague@example.com"
		if not frappe.db.exists("User", other):
			frappe.get_doc(
				{"doctype": "User", "email": other, "first_name": "Colleague", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		self.assertFalse(frappe.has_permission("File", "read", doc=name, user=other))

	@patch("frappe_webmail.webmail_api.create_communication_link", return_value={"created": True})
	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_the_message_sent_carries_the_logo_and_the_timeline_keeps_its_address(self, smtp_class, timeline):
		from frappe_webmail.api import send_email

		_, logo = self._signature()
		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()):
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Devis",
				html_content=f'<p>Bonjour</p><p>--</p><p>Camille</p><p><img src="{logo}"></p>',
				reference_doctype="ToDo",
				reference_name="inline-1650",
			)
		sent = email.message_from_string(server.sendmail.call_args.args[2])
		html, images = images_of(sent)
		self.assertEqual([part.get_payload(decode=True) for part in images], [PNG])
		self.assertIn(f'cid:{images[0]["Content-ID"].strip("<>")}', html)
		self.assertNotIn("/private/files/", html)
		self.assertIn(logo, timeline.call_args.kwargs["html_content"], "the desk shows the address")

	def test_a_draft_keeps_the_logo_s_address(self):
		"""The webmail's editor shows the address, and drops a `data:` image: a draft taken back keeps its logo."""
		from frappe_webmail.api import save_draft_imap

		_, logo = self._signature()
		with mocked_imap(drafts_client()) as client:
			save_draft_imap(
				self.test_account_email,
				to="marc@example.com",
				subject="Devis",
				html_content=f'<img src="{logo}">',
			)
		saved = email.message_from_bytes(client.append.call_args.args[1])
		html, images = images_of(saved)
		self.assertEqual(images, [])
		self.assertIn(logo, html)
