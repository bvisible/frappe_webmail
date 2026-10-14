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

from frappe.tests.utils import FrappeTestCase

from frappe_webmail.inline_images import to_parts
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
