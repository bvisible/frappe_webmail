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

	def test_a_company_s_logo_goes_in_for_everybody(self):
		"""The company signature draws the company's logo for everybody (signatures.py): it leaves as a part whoever
		sends it, a private file of the company or a public one the setup wizard wrote with no File row."""
		import os

		written = f"data:image/png;base64,{base64.b64encode(PNG).decode()}"
		private = self._file()
		html = f'<img src="{private}">'
		self.assertEqual(files_inlined(html, logo=""), html, "not a logo: it stays")
		self.assertIn(written, files_inlined(html, logo=private))
		# A public file written straight into the site's files, with no File row
		name = f"inline-logo-{frappe.generate_hash(length=8)}.png"
		on_disk = frappe.get_site_path("public", "files", name)
		with open(on_disk, "wb") as handle:
			handle.write(PNG)
		self.addCleanup(os.remove, on_disk)
		address = f"/files/{name}"
		html = f'<img src="{address}">'
		self.assertEqual(files_inlined(html, logo=""), html, "not a logo: it stays")
		self.assertIn(written, files_inlined(html, logo=address))
		# Only the logo of the sender's own company counts, to the letter
		for other in (address[:-4] + ".PNG", private):
			html = f'<img src="{other}">'
			self.assertEqual(files_inlined(html, logo=address), html, other)

	def test_the_sender_s_logo_is_asked_for_once_a_message(self):
		with patch.object(inline_images, "sender_logo", return_value="") as asked:
			files_inlined('<p>Hello</p><img src="https://elsewhere.example/a.png">')
			self.assertEqual(asked.call_count, 0, "no file of the instance: not asked")
			files_inlined("".join(f'<img src="/files/inline-many-{n}.png">' for n in range(3)))
			self.assertEqual(asked.call_count, 1)
			files_inlined('<img src="/files/inline-many-0.png">', logo="")
			self.assertEqual(asked.call_count, 1, "given by the caller: not asked again")

	def test_the_sender_s_logo_is_their_company_s_for_the_desk_s_people_only(self):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("this site has no company")
		before = frappe.db.get_value("Company", company, "company_logo")
		self.addCleanup(
			frappe.db.set_value, "Company", company, "company_logo", before, update_modified=False
		)
		frappe.db.set_value(
			"Company", company, "company_logo", " /files/inline-logo-own.png ", update_modified=False
		)
		portal = "inline_portal@example.com"
		if not frappe.db.exists("User", portal):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": portal,
					"first_name": "Portal",
					"send_welcome_email": 0,
					"user_type": "Website User",
				}
			).insert(ignore_permissions=True)
		with patch("frappe_webmail.signatures.company_of_user", return_value=company):
			self.assertEqual(inline_images.sender_logo(), "/files/inline-logo-own.png")
			frappe.set_user(portal)
			self.assertEqual(
				inline_images.sender_logo(), "", "a portal account is told nothing of the company"
			)
			frappe.set_user(self.test_user)
		with patch("frappe_webmail.signatures.company_of_user", return_value=None):
			self.assertEqual(inline_images.sender_logo(), "", "no company: no logo")
		with patch("frappe_webmail.signatures.company_of_user", side_effect=RuntimeError("boom")):
			self.assertEqual(inline_images.sender_logo(), "", "never in the way of a message")

	def test_the_logo_leaves_at_the_width_its_template_draws_it(self):
		"""The desk's editor keeps a picture's address but not its size: the sender's company logo gets back its width."""
		logo = "/files/inline-logo-sized.png"
		with patch.object(inline_images, "_logo_width", return_value=150):
			self.assertEqual(
				inline_images.logo_sized(f'<p>Camille</p><img src="{logo}" alt="logo">', logo),
				f'<p>Camille</p><img width="150" src="{logo}" alt="logo">',
			)
			# A width it already says stays, and another picture is left as it was, beside the logo too
			for kept in (
				f'<img src="{logo}" width="80">',
				'<img src="/files/other.png">',
				"<p>No picture</p>",
			):
				self.assertEqual(inline_images.logo_sized(kept, logo), kept)
			self.assertEqual(
				inline_images.logo_sized(f'<img src="/files/other.png"><img src="{logo}">', logo),
				f'<img src="/files/other.png"><img width="150" src="{logo}">',
			)
			# The sender's own logo, when the caller doesn't give it
			with patch.object(inline_images, "sender_logo", return_value=logo):
				self.assertIn('width="150"', inline_images.logo_sized(f'<img src="{logo}">'))
		self.assertEqual(inline_images.logo_sized(f'<img src="{logo}">', ""), f'<img src="{logo}">')

	def test_a_file_is_only_the_one_of_its_very_address(self):
		"""The database compares addresses without case: a file named like another in other letters is not that one."""
		url = self._file(private=0)
		self.assertIn("data:image/png", files_inlined(f'<img src="{url}">'))
		other = url[:-4] + url[-4:].upper()
		self.assertEqual(files_inlined(f'<img src="{other}">'), f'<img src="{other}">')

	def test_a_public_file_is_read_from_the_public_files_only(self):
		for climbing in (
			"/files/../../site_config.json",
			"/files/%2e%2e/%2e%2e/site_config.json",
			"/files/../private/files/x.png",
			"/files/",
			"/files/inline-logo-gone.png",
			"/files/with-a-nul\x00.png",
		):
			self.assertIsNone(inline_images._public_file(climbing), climbing)
		# A file that can't be read never stops a message: it is as if it weren't there
		import os

		name = f"inline-logo-{frappe.generate_hash(length=8)}.png"
		on_disk = frappe.get_site_path("public", "files", name)
		with open(on_disk, "wb") as handle:
			handle.write(PNG)
		self.addCleanup(os.remove, on_disk)
		self.assertEqual(inline_images._public_file(f"/files/{name}"), PNG)
		with patch("builtins.open", side_effect=PermissionError("denied")):
			self.assertIsNone(inline_images._public_file(f"/files/{name}"))
		# A link in the public files to a file out of them is not read
		outside = frappe.get_site_path(f"inline-outside-{frappe.generate_hash(length=8)}.png")
		with open(outside, "wb") as handle:
			handle.write(PNG)
		self.addCleanup(os.remove, outside)
		link = frappe.get_site_path("public", "files", f"inline-link-{frappe.generate_hash(length=8)}.png")
		os.symlink(outside, link)
		self.addCleanup(os.remove, link)
		self.assertIsNone(inline_images._public_file("/files/" + os.path.basename(link)))
		# From the address a message gives, decoded, to the disk: a file out of the public files stays an address, even
		# taken for the logo
		climbing = "/files/%2e%2e/%2e%2e/" + os.path.basename(outside)
		decoded = inline_images._local_path(climbing)
		self.assertEqual(decoded, "/files/../../" + os.path.basename(outside))
		html = f'<img src="{climbing}">'
		self.assertEqual(files_inlined(html, logo=decoded), html)

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
