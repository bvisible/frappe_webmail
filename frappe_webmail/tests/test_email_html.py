# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What the HTML of a message sent and of a signature pasted as HTML may carry (email_html.py): a signature from a
generator keeps its table, its colours, its logo and its links; what a mail client never shows or runs goes whole.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_email_html
"""

import base64

import frappe
from bs4 import BeautifulSoup
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api
from frappe_webmail.email_html import (
	MAX_SIGNATURE_SOURCE,
	clean_sent_html,
	clean_signature_html,
	plain_text,
)

USER = "email_html_signature@example.com"
PORTAL = "email_html_portal@example.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + b"\0" * 32
DATA_PNG = "data:image/png;base64," + base64.b64encode(PNG).decode()

# What a signature generator gives, more or less: a whole page, a style sheet, Outlook's comments, a table of cells
# with inline styles, a logo on the web and one written in, links to a site, an address and a phone number.
GENERATED = f"""<html><head><title>Signature</title><meta charset="utf-8">
<style>@font-face {{ font-family: Brand; }} .sig {{ color: red; }}</style>
<script>alert("from the generator")</script></head>
<body><!--[if mso]><table><tr><td>Outlook only</td></tr></table><![endif]-->
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-family:Arial,sans-serif" onclick="steal()">
<tr><td style="padding:0 12px 0 0;vertical-align:top" width="90">
<img src="https://cdn.example.org/logo.png" width="80" height="80" alt="Logo" onerror="steal()">
<img src="{DATA_PNG}" width="16" height="16" alt="Icon">
<img src="http://insecure.example.org/tracker.png" width="1" height="1">
<img src="javascript:steal()" alt="x">
</td><td style="color:#1f272e;font-size:13px;line-height:18px">
<strong style="color:#0b6e4f">Ann Example</strong><br>Project lead<br>
<a href="https://www.example.org" style="color:#0b6e4f">www.example.org</a> ·
<a href="mailto:ann@example.org">ann@example.org</a> ·
<a href="tel:+41210000000">+41 21 000 00 00</a> ·
<a href="javascript:steal()">click</a>
<form action="https://evil.example"><input name="password"><button>Go</button></form>
<iframe src="https://evil.example/frame"></iframe>
</td></tr></table></body></html>"""


def kept(html):
	return BeautifulSoup(clean_signature_html(html), "html.parser")


class TestEmailHtml(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The field as this version declares it: a site not migrated yet keeps Frappe's own cleaning on it.
		frappe.reload_doc("frappe_webmail", "doctype", "email_signature")
		if not frappe.db.exists("User", USER):
			user = frappe.get_doc(
				{"doctype": "User", "email": USER, "first_name": "Signature", "send_welcome_email": 0}
			)
			user.append("roles", {"role": "Blogger"})
			user.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Email Signature", {"user": USER})

	def test_a_generated_signature_keeps_its_layout_its_pictures_and_its_links(self):
		tree = kept(GENERATED)
		table = tree.find("table")
		self.assertIsNotNone(table)
		self.assertIn("border-collapse", table.get("style", ""))
		self.assertEqual(table.get("cellpadding"), "0")
		cells = tree.find_all("td")
		self.assertEqual(len(cells), 2)
		self.assertIn("vertical-align", cells[0].get("style", ""))
		self.assertEqual(cells[0].get("width"), "90")
		sources = [img.get("src") for img in tree.find_all("img")]
		self.assertEqual(sources, ["https://cdn.example.org/logo.png", DATA_PNG])
		links = [a.get("href") for a in tree.find_all("a")]
		self.assertEqual(
			links, ["https://www.example.org", "mailto:ann@example.org", "tel:+41210000000", None]
		)
		self.assertIn("Ann Example", tree.get_text())
		self.assertIn("color", tree.find("strong").get("style", ""))

	def test_what_a_mail_client_never_shows_or_runs_goes_whole(self):
		html = clean_signature_html(GENERATED)
		tree = BeautifulSoup(html, "html.parser")
		text = tree.get_text()
		# Neither the elements nor their words: a style sheet or a script never turns up as text.
		for words in ('alert("from the generator")', "@font-face", "Outlook only", "Signature"):
			self.assertNotIn(words, text, words)
		for tag in ("script", "style", "head", "title", "form", "input", "button", "iframe", "meta"):
			self.assertIsNone(tree.find(tag), tag)
		# Nor what runs, or leads where no recipient should go.
		for gone in ("onclick", "onerror", "steal", "javascript:", "evil.example"):
			self.assertNotIn(gone, html, gone)
		self.assertNotIn(
			"insecure.example.org", html, "a picture over plain http is not shown to every recipient"
		)
		self.assertEqual(clean_signature_html("<style>p { color: red }</style><script>x()</script>"), "")
		self.assertEqual(clean_signature_html(None), "")

	def test_cleaned_twice_a_signature_is_the_same(self):
		once = clean_signature_html(GENERATED)
		self.assertEqual(clean_signature_html(once), once)
		# What Word and Outlook leave of an emptied signature stays as it was written (Frappe would take a bare
		# non-breaking space for no content), and a picture's address comes first.
		self.assertEqual(clean_signature_html("<p>&nbsp;</p>"), "<p>&nbsp;</p>")
		self.assertTrue(
			clean_signature_html('<img alt="A" height="8" src="https://cdn.example.org/a.png">').startswith(
				'<img src="https://cdn.example.org/a.png"'
			)
		)

	def test_a_signature_is_saved_as_it_will_be_sent(self):
		frappe.set_user(USER)
		signature = frappe.get_doc(
			{"doctype": "Email Signature", "signature_name": "Generated", "content": GENERATED}
		).insert()
		self.assertEqual(signature.user, USER)
		tree = BeautifulSoup(signature.content, "html.parser")
		self.assertIsNotNone(tree.find("table"), "the table is kept, not rebuilt from paragraphs")
		self.assertIsNone(tree.find("script"))
		self.assertIn("tel:+41210000000", signature.content, "Frappe's own cleaning would have taken it")
		# The picture written in is kept as a file of the signature (Frappe), which the sending writes in again.
		sources = [img.get("src") for img in tree.find_all("img")]
		self.assertEqual(sources[0], "https://cdn.example.org/logo.png")
		self.assertFalse(sources[1].startswith("data:"), sources[1])
		self.assertTrue(sources[1].startswith(("/files/", "/private/files/")), sources[1])
		# Frappe rewrites the tag up to the address when it keeps the picture as a file: the address comes first, and
		# what the picture says of itself stays.
		icon = tree.find_all("img")[1]
		self.assertEqual((icon.get("alt"), icon.get("width"), icon.get("height")), ("Icon", "16", "16"))
		# Saved again, it stays as it is.
		before = signature.content
		signature.save()
		self.assertEqual(signature.content, before)

	def test_a_signature_with_nothing_left_or_too_large_is_refused(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Email Signature",
					"signature_name": "Nothing",
					"content": "<style>p{}</style><script>x()</script>",
				}
			).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Email Signature",
					"signature_name": "Too large",
					"content": "<p>" + "a" * MAX_SIGNATURE_SOURCE + "</p>",
				}
			).insert()

	def test_the_preview_is_the_cleaning_the_saving_does(self):
		frappe.set_user(USER)
		preview = webmail_api.clean_signature(GENERATED)["html"]
		self.assertEqual(preview, clean_signature_html(GENERATED))
		with self.assertRaises(frappe.ValidationError):
			webmail_api.clean_signature("x" * (MAX_SIGNATURE_SOURCE + 1))

	def test_the_preview_is_for_the_desk_s_people(self):
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
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			webmail_api.clean_signature("<p>Hello</p>")

	def test_nothing_slips_through_an_attribute_a_style_or_a_kind_of_picture(self):
		html = clean_signature_html(
			'<a href="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;">site</a>'
			'<img src="https://cdn.example.org/a.png" srcset="https://evil.example/b.png 2x">'
			'<img src="data:image/svg+xml;base64,PHN2Zy8+">'
			'<p style="position:fixed;top:0;background:url(https://evil.example/t.png);color:#123456">text</p>'
			'<img src="/files/logo.png" width="10"><img src="/private/files/logo.png">'
		)
		tree = BeautifulSoup(html, "html.parser")
		self.assertIsNone(tree.find("a").get("href"), "a link that is a page written in")
		sources = [img.get("src") for img in tree.find_all("img")]
		self.assertEqual(
			sources,
			["https://cdn.example.org/a.png", "/files/logo.png", "/private/files/logo.png"],
			"an SVG written in is refused; the instance's files are kept",
		)
		self.assertIn("color", tree.find("p").get("style", ""))
		for gone in ("srcset", "position", "url(", "evil.example"):
			self.assertNotIn(gone, html, gone)

	def test_a_message_sent_keeps_what_it_kept_and_its_phone_links(self):
		written = (
			'<p>Hello <strong>Ann</strong>, <a href="https://www.example.org" target="_blank">see</a></p>'
			'<div data-webmail-signature=""><table style="border-collapse:collapse"><tr>'
			'<td width="90" valign="top"><img src="https://cdn.example.org/logo.png" width="80"></td>'
			'<td><a href="tel:+41210000000">+41 21 000 00 00</a></td></tr></table></div>'
			"<script>alert(1)</script>"
		)
		sent = clean_sent_html(written)
		tree = BeautifulSoup(sent, "html.parser")
		self.assertEqual(tree.find("a").get("href"), "https://www.example.org")
		self.assertEqual(tree.find_all("a")[1].get("href"), "tel:+41210000000")
		self.assertIsNotNone(tree.find("table"))
		self.assertEqual(tree.find("td").get("width"), "90")
		self.assertIsNone(tree.find("script"))
		# The composer's mark of its signature block is its own: it doesn't leave.
		self.assertNotIn("data-webmail-signature", sent)

	def test_the_text_version_says_where_links_and_a_banner_lead(self):
		"""What a reader of the text alone gets: a link's address after its words (not when its words say it already), a
		banner's description and where it leads, a picture alone left out, entities read, what is never shown gone."""
		written = (
			'<p>Hello <strong>Ann</strong>,&nbsp;see <a href="https://www.example.org/offer">the offer</a>.</p><p></p>'
			'<p>Write to <a href="mailto:ann@example.org">ann@example.org</a> or <a href="tel:+41210000000">call us</a>.</p>'
			'<p><a href="https://www.example.org/">www.example.org</a> &amp; more</p><p>--</p>'
			'<table><tr><td><img src="cid:photo" alt="Ann"></td><td>Ann Example<br>Example SA</td></tr></table>'
			'<a href="https://www.example.org/spring"><img src="cid:banner" alt="Spring offer"></a>'
			"<script>alert(1)</script><style>p { color: red; }</style>"
		)
		self.assertEqual(
			plain_text(written),
			"Hello Ann, see the offer (https://www.example.org/offer).\n\n"
			"Write to ann@example.org or call us (+41210000000).\n\n"
			"www.example.org & more\n\n"
			"--\n\n"
			"Ann Example\nExample SA\n\n"
			"Spring offer (https://www.example.org/spring)",
		)
		self.assertEqual(plain_text(""), "")
		self.assertEqual(plain_text("Just words &lt;not a tag&gt;"), "Just words <not a tag>")

	def test_the_text_version_keeps_the_lines_lists_and_quotes(self):
		"""A line of a composer that writes one block a line (Gmail's divs) ends once, with no empty line between lines;
		an item starts with a dash or its number; a quote's lines start with "> ", a quote in a quote with "> > "."""
		self.assertEqual(
			plain_text("<div>Line 1</div>\n<div>Line 2</div>\n<div><br></div>\n<div>Line 4</div>"),
			"Line 1\nLine 2\n\nLine 4",
		)
		self.assertEqual(
			plain_text(
				"<p>Points:</p><ul><li>one</li><li>two <b>bold</b></li></ul><ol><li>first</li><li>second</li></ol><p>End</p>"
			),
			"Points:\n\n- one\n- two bold\n\n1. first\n2. second\n\nEnd",
		)
		self.assertEqual(
			plain_text(
				"<p>Thanks</p><blockquote><p>Original line</p><p>Second</p><blockquote><p>Older</p></blockquote></blockquote>"
			),
			"Thanks\n\n> Original line\n>\n> Second\n>\n> > Older",
		)
