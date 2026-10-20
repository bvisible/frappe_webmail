# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The company's signature (signatures.py, Email Signature Template): how a template is written for a person, which
template applies to whom, and what the composers are given.

The rendering tests need no site data: a person and a template are built in the test. The others create their own
records, all named with PREFIX, and remove them; nothing is sent.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_signatures
"""

import email
import io
import json
import os
from unittest.mock import MagicMock, patch

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import signature_photos, signatures
from frappe_webmail.signatures import (
	LAYOUTS,
	PREFERENCE,
	card_of,
	own_signature,
	render_person,
	signature_for,
	template_for,
)
from frappe_webmail.tests.test_api import TestWebmailAPIBase
from frappe_webmail.tests.test_attachments import imap_client, mocked_imap

PREFIX = "zz-signature-test"
# The address of a logo that no file of the site answers to
MISSING_LOGO = f"/files/{PREFIX}-no-such-logo.png"
USER = "signatures_test_person@example.com"
OTHER = "signatures_test_other@example.com"
# A portal account (a Website User): no company signature is ever written for it
PORTAL = "signatures_test_portal@example.com"
# A role that opens the desk and gives no right: a template applies to the desk's people only, and the people of these
# tests may read or write nothing of the templates
DESK_ROLE = f"{PREFIX}-desk"
# The address of a person's photo and of a banner that no file of the site answers to (drawing needs no file)
PHOTO = f"/private/files/{PREFIX}-photo.jpg"
BANNER = f"/files/{PREFIX}-no-such-banner.png"
# The worker's call itself, which the tests that give people photos replace (PhotoTestCase)
REFRESH_LATER = signature_photos.refresh_later

# The tags and attributes that the cleaning of a message sent keeps (webmail_api.send_email), as that function writes
# them. The layouts keep to them, so that what the form shows is what leaves: a layout that needs another is a change
# to both.
KEPT_TAGS = {"a", "b", "br", "div", "img", "span", "strong", "table", "tbody", "td", "th", "thead", "tr"}
KEPT_ATTRIBUTES = {
	"*": {"class", "style"},
	"a": {"href", "title", "target", "rel"},
	"img": {"src", "alt", "width", "height"},
	"table": {"border", "cellpadding", "cellspacing", "width"},
	"td": {"colspan", "rowspan", "width", "valign", "align"},
	"th": {"colspan", "rowspan", "width", "valign", "align"},
}


def person(**values):
	"""A person as person_of gives them, with every item filled unless the test empties or changes it."""
	return frappe._dict(
		{
			"user": "alex@example.com",
			"name": "Alex Example",
			"job_title": "Head of Sales",
			"department": "Sales",
			"phone": "+41 00 000 00 00",
			"mobile": "+41 00 000 00 01",
			"email": "alex@example.com",
			"company_name": "Example Ltd",
			"website": "www.example.com/shop",
			"address": "Main Street 1, 1000 Town",
			"logo": MISSING_LOGO,
		}
		| values
	)


def template(layout="Text only", **values):
	"""A template as the form gives it, unsaved (rendering only reads it)."""
	return frappe._dict({"layout": layout, **values})


def link(network, url):
	return frappe._dict(network=network, url=url)


def soup(html):
	return BeautifulSoup(html, "html.parser")


def make_user(email, first_name, last_name, desk=True):
	"""A person of the desk with no role that gives a right, or a portal account (`desk=False`), for the test class (the
	class's changes are rolled back when it is done). Frappe makes a user with no role that opens the desk a portal
	account, whatever its type is said to be."""
	if desk and not frappe.db.exists("Role", DESK_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": DESK_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"last_name": last_name,
				"send_welcome_email": 0,
				"user_type": "System User" if desk else "Website User",
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	if desk and DESK_ROLE not in {row.role for row in user.roles}:
		user.add_roles(DESK_ROLE)
	if user.user_type != ("System User" if desk else "Website User"):
		raise AssertionError(f"{email} is a {user.user_type}")


def picture_file(
	test, width=40, height=30, colour=(31, 58, 95), kind="PNG", content=None, extension=None, **values
):
	"""A file of the instance, a picture of that size and colour (or those bytes), removed after the test: its address.
	`values` are the File's own (is_private, attached_to_doctype, attached_to_name). Bytes alike are one file to Frappe:
	a test that needs two files draws two pictures."""
	from PIL import Image

	if content is None:
		buffer = io.BytesIO()
		Image.new("RGB", (width, height), colour).save(buffer, kind)
		content = buffer.getvalue()
	extension = extension or {"JPEG": "jpg", "GIF": "gif"}.get(kind, "png")
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{PREFIX}-{frappe.generate_hash(length=8)}.{extension}",
			"content": content,
			"is_private": 0,
		}
		| values
	).insert(ignore_permissions=True)
	test.addCleanup(frappe.delete_doc, "File", file.name, force=True, ignore_permissions=True)
	return file.file_url


def banner(**values):
	"""A template's banner, a picture with its link and its words, unless the test changes them."""
	return {
		"banner_image": BANNER,
		"banner_url": "https://example.com/fair",
		"banner_description": "Meet us at the fair",
	} | values


class SignatureTestCase(FrappeTestCase):
	def make_template(self, label="everyone", **values):
		"""An enabled template for everyone, drawn text only, removed after the test; others say what they apply to."""
		doc = frappe.get_doc(
			{
				"doctype": "Email Signature Template",
				"template_name": f"{PREFIX}-{label}-{frappe.generate_hash(length=6)}",
				"enabled": 1,
				"applies_to": "Everyone",
				"layout": "Text only",
			}
			| values
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "Email Signature Template", doc.name, force=True, ignore_permissions=True
		)
		return doc

	def quiet_the_site(self):
		"""The templates already on the site would answer in place of the ones a test makes: they are all turned off,
		before the test makes its own (the class's changes are rolled back when it is done)."""
		frappe.db.sql("update `tabEmail Signature Template` set enabled = 0 where enabled = 1")


class TestRendering(FrappeTestCase):
	"""A template written for a person: the HTML a mail client shows, and its text."""

	def test_every_value_is_escaped(self):
		hostile = person(
			name="Alex <script>alert(1)</script> & Co",
			job_title='<img src=x onerror="alert(2)">',
			company_name="Example & Sons <b>Ltd</b>",
			address="Main Street 1 <i>bis</i>, 1000 Town",
			phone="<u>+41</u> 00",
			logo="/files/a.png",
		)
		look = template(
			show_company_address=1,
			show_disclaimer=1,
			disclaimer="<script>alert(3)</script> & more",
			cta_label="<b>Book</b>",
			cta_url="https://example.com/?a=1&b=2",
		)
		for layout in LAYOUTS:
			look["layout"] = layout
			result = render_person(look, hostile)
			html = result["html"]
			self.assertNotIn("<script", html.lower(), layout)
			self.assertNotIn("<img src=x", html.lower(), layout)
			for tag in ("<b>", "<u>", "<i>"):
				self.assertNotIn(tag, html, layout)
			self.assertIn("Alex &lt;script&gt;alert(1)&lt;/script&gt; &amp; Co", html, layout)
			self.assertIn("Example &amp; Sons &lt;b&gt;Ltd&lt;/b&gt;", html, layout)
			self.assertIn('href="https://example.com/?a=1&amp;b=2"', html, layout)
			# The text is text: it says what the person is called, and is never read as markup
			self.assertIn("Alex <script>alert(1)</script> & Co", result["text"], layout)
			# Read as a browser reads it, the name is words and not a script
			tree = soup(html)
			self.assertIsNone(tree.find("script"), layout)
			self.assertIsNone(tree.find("b"), layout)
			self.assertIn("Alex <script>alert(1)</script> & Co", tree.get_text(), layout)

	def test_an_address_cannot_leave_its_attribute(self):
		"""A quote or an angle bracket in an address would end the href: such an address is not a link at all."""
		attempts = (
			'https://example.com/"onmouseover="alert(1)',
			"https://example.com/<script>",
			"https://example.com/ a",
			"https://example.com/\nb",
			"https://",
			"https://[bad",
		)
		for attempt in attempts:
			result = render_person(
				template(social_links=[link("LinkedIn", attempt)], cta_label="Go", cta_url=attempt), person()
			)
			self.assertNotIn("onmouseover", result["html"], attempt)
			self.assertNotIn("<script", result["html"], attempt)
			self.assertNotIn("LinkedIn", result["html"], attempt)
			self.assertNotIn(">Go<", result["html"], attempt)

	def test_an_empty_value_removes_its_whole_line(self):
		"""A label never stands alone: with nothing to put after it, the line is not there."""
		labels = {"phone": _("Phone"), "mobile": _("Mobile"), "email": _("Email"), "website": _("Website")}
		values = {
			"phone": "+41 00 000 00 00",
			"mobile": "+41 00 000 00 01",
			"email": "alex@example.com",
			"website": "www.example.com/shop",
		}
		for layout in LAYOUTS:
			full = render_person(template(layout, show_mobile=1), person())
			for item, value in values.items():
				self.assertIn(value, full["html"], f"{layout}: {item}")
				self.assertIn(f"{labels[item]}: {value}", full["text"], f"{layout}: {item}")
				if layout != "Compact" or item in ("phone", "mobile"):
					self.assertIn(f"{labels[item]}:", full["html"], f"{layout}: {item}")
			for item, value in values.items():
				empty = render_person(template(layout, show_mobile=1), person(**{item: ""}))
				self.assertNotIn(value, empty["html"], f"{layout}: {item}")
				self.assertNotIn(value, empty["text"], f"{layout}: {item}")
				self.assertNotIn(f"{labels[item]}: ", empty["text"], f"{layout}: {item}")
				# The compact layout names its numbers and lets the address and the website say what they are
				if layout != "Compact" or item in ("phone", "mobile"):
					self.assertNotIn(labels[item], empty["html"], f"{layout}: {item}")
				for other in set(values) - {item}:
					self.assertIn(values[other], empty["html"], f"{layout}: {item} empty, {other}")
		# Nor a title, a department or a company name alone, and no empty block in their place
		bare = render_person(
			template(show_department=1), person(job_title="", department="", company_name="")
		)
		self.assertNotIn("Head of Sales", bare["html"])
		for block in soup(bare["html"]).find_all("div"):
			self.assertTrue(block.get_text(strip=True), "no empty line")
		# Nor the whole signature when there is nothing to say
		nothing = person(
			name="", job_title="", company_name="", phone="", mobile="", email="", website="", logo=""
		)
		self.assertEqual(render_person(template(), nothing), {"html": "", "text": ""})

	def test_a_value_that_is_only_spaces_is_empty_and_a_line_break_is_a_space(self):
		result = render_person(template(show_mobile=1), person(mobile="   \n\t", job_title=" "))
		self.assertNotIn(_("Mobile"), result["html"])
		self.assertNotIn("Head of Sales", result["html"])
		result = render_person(template(), person(name="  Alex \n Example  "))
		self.assertIn(">Alex Example</div>", result["html"])
		self.assertEqual(result["text"].splitlines()[0], "Alex Example")

	def test_the_checks_say_what_is_shown(self):
		# What is off by default: the department, the mobile number (often a private one), the company address, the
		# disclaimer
		default = render_person(template(disclaimer="Small print"), person())
		self.assertNotIn("Main Street", default["html"])
		self.assertNotIn("Small print", default["html"])
		self.assertNotIn("+41 00 000 00 01", default["html"])
		self.assertNotIn("+41 00 000 00 01", default["text"])
		self.assertIn(">Head of Sales</div>", default["html"], "the title alone, without the department")
		on = render_person(
			template(
				show_department=1,
				show_mobile=1,
				show_company_address=1,
				show_disclaimer=1,
				disclaimer="Small print",
			),
			person(),
		)
		self.assertIn("Head of Sales, Sales", on["html"])
		self.assertIn("+41 00 000 00 01", on["html"])
		self.assertIn(f"{_('Mobile')}: +41 00 000 00 01", on["text"])
		self.assertIn("Main Street 1, 1000 Town", on["html"])
		self.assertIn("Small print", on["html"])
		self.assertIn("Small print", on["text"])
		# Each of the others can be turned off
		for switch, expected in (
			("show_full_name", "Alex Example"),
			("show_job_title", "Head of Sales"),
			("show_phone", "+41 00 000 00 00"),
			("show_email", "alex@example.com"),
			("show_website", "www.example.com/shop"),
			("show_company_name", "Example Ltd"),
		):
			self.assertIn(expected, render_person(template(), person())["html"], switch)
			off = render_person(template(**{switch: 0}), person())
			self.assertNotIn(expected, off["html"], switch)
			self.assertNotIn(expected, off["text"], switch)
		# The defaults are the ones the form has
		self.assertEqual(
			{name: value for name, value in signatures.SWITCHES.items() if not value},
			{"show_department": 0, "show_mobile": 0, "show_company_address": 0, "show_disclaimer": 0},
		)

	def test_each_layout_is_a_table_of_inline_styles_and_has_its_text(self):
		for name in LAYOUTS:
			result = render_person(
				template(
					name,
					show_department=1,
					show_mobile=1,
					show_company_address=1,
					show_disclaimer=1,
					disclaimer="First line\nSecond line",
					social_links=[link("LinkedIn", "https://www.linkedin.com/company/example")],
					cta_label="Book a call",
					cta_url="https://example.com/book",
				),
				person(),
			)
			html, text = result["html"], result["text"]
			tree = soup(html)
			# Tables to place things, in one piece, with nothing a mail client drops or reads wrongly
			roots = [child for child in tree.contents if getattr(child, "name", None)]
			self.assertEqual([root.name for root in roots], ["table"], name)
			self.assertNotIn("<style", html.lower(), name)
			self.assertNotIn("<script", html.lower(), name)
			self.assertNotIn("class=", html, name)
			self.assertNotIn("data:", html, name)
			self.assertNotIn("\n", html, name)
			for element in tree.find_all(["table", "td", "div", "span", "a", "img"]):
				self.assertTrue(element.get("style"), f"{name}: a style on every {element.name}")
				self.assertNotRegex(
					element["style"],
					r"flex|grid|margin|float|position|var\(|calc\(",
					f"{name}: {element.name}",
				)
			for table in tree.find_all("table"):
				self.assertEqual(
					(table["cellpadding"], table["cellspacing"], table["border"]), ("0", "0", "0")
				)
			for image in tree.find_all("img"):
				self.assertTrue(image.get("width") and image.get("alt"), name)
			# Only what the cleaning of a message sent keeps
			for element in tree.find_all(True):
				self.assertIn(element.name, KEPT_TAGS, name)
				kept = KEPT_ATTRIBUTES["*"] | KEPT_ATTRIBUTES.get(element.name, set())
				self.assertLessEqual(set(element.attrs), kept, f"{name}: {element.name}")
			# What is said is in the HTML and in the text, whichever the layout
			for words in (
				"Alex Example",
				"Head of Sales, Sales",
				"Example Ltd",
				"+41 00 000 00 00",
				"+41 00 000 00 01",
				"alex@example.com",
				"www.example.com/shop",
				"Main Street 1, 1000 Town",
				"LinkedIn",
				"Book a call",
				"First line",
				"Second line",
			):
				self.assertIn(words, tree.get_text(), f"{name}: {words}")
				self.assertIn(words, text, f"{name}: {words}")
			self.assertEqual(text.splitlines()[0], "Alex Example", name)
			self.assertIn("LinkedIn: https://www.linkedin.com/company/example", text, name)
			self.assertIn("Book a call: https://example.com/book", text, name)
			self.assertTrue(text.endswith("\n\nFirst line\nSecond line"), name)

	def test_the_layouts_differ_where_they_should(self):
		def drawn(name):
			return soup(render_person(template(name, show_mobile=1), person())["html"])

		self.assertIsNone(drawn("Text only").find("img"), "no picture in the text-only layout")

		left = drawn("Logo left")
		cells = left.find("tr").find_all("td", recursive=False)
		self.assertEqual(len(cells), 2, "the logo in a column, the details in another")
		self.assertIsNotNone(cells[0].find("img"))
		self.assertIsNone(cells[1].find("img"))
		self.assertIn("border-left:1px solid", cells[1]["style"], "a thin vertical rule between the two")
		self.assertNotIn("border-left", cells[0]["style"])
		self.assertEqual(
			cells[0]["width"], "120", "the logo's column is as wide as the logo: the rest is the details'"
		)

		above = drawn("Logo above")
		rows = above.find("table").find_all("tr", recursive=False)
		self.assertIsNotNone(rows[0].find("img"), "the logo on a row of its own")
		self.assertIsNone(rows[1].find("img"))
		self.assertEqual(len(rows[0].find_all("td", recursive=False)), 1)

		compact = drawn("Compact")
		self.assertIsNone(compact.find("img"), "no logo in two lines")
		lines = compact.find("td").find_all("div", recursive=False)
		self.assertEqual(len(lines), 2, "two lines")
		self.assertIn("Alex Example", lines[0].get_text())
		self.assertIn("Example Ltd", lines[0].get_text())
		self.assertIn("alex@example.com", lines[1].get_text())
		self.assertIn("+41 00 000 00 01", lines[1].get_text())

	def test_a_layout_with_no_logo_to_show_leaves_no_empty_column(self):
		for name in ("Logo left", "Logo above"):
			for result in (
				render_person(template(name), person(logo="")),
				render_person(template(name, show_logo=0), person()),
			):
				tree = soup(result["html"])
				self.assertIsNone(tree.find("img"), name)
				self.assertNotIn("border-left", result["html"], f"{name}: no rule on its own")
				self.assertEqual(len(tree.find("tr").find_all("td", recursive=False)), 1, name)
				self.assertIn("Alex Example", result["text"])

	def test_a_layout_draws_no_column_nor_rule_for_nothing(self):
		off = {switch: 0 for switch in signatures.SWITCHES}
		# A logo and nothing beside it: the logo alone, without the rule of an empty column
		for name in ("Logo left", "Logo above"):
			html = render_person(template(name, **off | {"show_logo": 1}), person())["html"]
			tree = soup(html)
			self.assertIsNotNone(tree.find("img"), name)
			self.assertNotIn("border-left", html, name)
			self.assertEqual(len(tree.find_all("td")), 1, f"{name}: the logo's cell alone")
		# The small print alone: its row, and no empty table in front of it
		only = off | {"show_disclaimer": 1, "disclaimer": "Small print"}
		for name in LAYOUTS:
			tree = soup(render_person(template(name, **only), person())["html"])
			self.assertEqual(len(tree.find_all("table")), 1, name)
			self.assertEqual(tree.get_text(), "Small print", name)

	def test_an_unknown_layout_is_drawn_as_the_default_one(self):
		self.assertEqual(
			render_person(template("Round photo"), person()),
			render_person(template(signatures.DEFAULT_LAYOUT), person()),
		)

	def test_the_look_is_written_on_the_elements(self):
		html = render_person(
			template(
				"Logo left",
				font="Verdana",
				accent_color="#AA3300",
				font_size=14,
				show_disclaimer=1,
				disclaimer="Small print",
			),
			person(),
		)["html"]
		self.assertIn("font-family:Verdana,Geneva,sans-serif;", html)
		self.assertIn("font-size:14px;", html)
		self.assertIn("font-size:16px;", html, "the name, two pixels over the base size")
		self.assertIn("font-size:12px;", html, "the small print, two under")
		self.assertIn("color:#aa3300;", html)
		self.assertIn("border-left:1px solid #aa3300;", html)
		self.assertNotIn(signatures.DEFAULT_ACCENT, html)
		self.assertNotIn("Arial", html)
		# Every element that carries text has the face on it: a client does not hand it down from a table
		for element in soup(html).find_all(["td", "div"]):
			self.assertIn("font-family:Verdana,Geneva,sans-serif", element["style"], element.name)
		# The fonts of the Select, each with fonts to fall back on
		for font, stack in signatures.FONTS.items():
			self.assertIn(f"font-family:{stack};", render_person(template(font=font), person())["html"], font)
			self.assertIn(",", stack)

	def test_the_look_has_defaults_and_limits(self):
		default = render_person(template(), person())["html"]
		self.assertIn("font-family:Arial,Helvetica,sans-serif;", default)
		self.assertIn(f"color:{signatures.DEFAULT_ACCENT};", default)
		self.assertIn("font-size:13px;", default)
		# Anything that is not #rrggbb is not a colour, and is not written
		for bad in (
			"red",
			"#fff",
			"#12345",
			"#1234567",
			"#gggggg",
			"url(x)",
			"#aa3300;position:fixed",
			"",
			None,
		):
			html = render_person(template(accent_color=bad), person())["html"]
			self.assertIn(f"color:{signatures.DEFAULT_ACCENT};", html, repr(bad))
			self.assertNotIn("position", html, repr(bad))
		self.assertIn("font-family:Arial,", render_person(template(font="Comic Sans; x"), person())["html"])
		# Sizes are brought back between their bounds: 11 to 16 for the text (the name is two over, the small print
		# two under with ten as its least), 60 to 240 for the logo
		small = render_person(template(font_size=3), person())["html"]
		self.assertIn("font-size:11px;", small)
		self.assertIn("font-size:13px;", small, "the name")
		large = render_person(template(font_size=99), person())["html"]
		self.assertIn("font-size:16px;", large)
		self.assertIn("font-size:18px;", large, "the name")
		for width, expected in ((10, 60), (999, 240), (0, 120), (None, 120), ("90", 90)):
			image = soup(render_person(template("Logo left", logo_width=width), person())["html"]).find("img")
			self.assertEqual(image["width"], str(expected), width)

	def test_only_https_links_are_kept(self):
		links = [
			link("LinkedIn", "https://www.linkedin.com/company/example"),
			link("X", "http://x-network.example.com/example"),
			link("Facebook", "javascript:alert(1)"),
			link("Instagram", "//instagram-network.example.com/example"),
			link("YouTube", "ftp://youtube-network.example.com/example"),
			link("Website", "https://example.com"),
			link("Myspace", "https://myspace-network.example.com"),
			link("LinkedIn", ""),
			link("Facebook", "https://facebook-network.example.com/ page"),
		]
		for layout in LAYOUTS:
			result = render_person(template(layout, social_links=links), person())
			tree = soup(result["html"])
			hrefs = {a["href"] for a in tree.find_all("a") if a.get_text() in ("LinkedIn", _("Website"))}
			self.assertIn("https://www.linkedin.com/company/example", hrefs, layout)
			self.assertIn("https://example.com", hrefs, layout)
			for refused in (
				"x-network",
				"alert(1)",
				"instagram-network",
				"youtube-network",
				"myspace",
				"facebook-network",
			):
				self.assertNotIn(refused, result["html"], f"{layout}: {refused}")
				self.assertNotIn(refused, result["text"], f"{layout}: {refused}")
			for anchor in tree.find_all("a"):
				self.assertRegex(anchor["href"], r"^(https://|mailto:)", layout)
		off = render_person(template(social_links=links, show_social_links=0), person())
		self.assertNotIn("LinkedIn", off["html"])
		self.assertNotIn("LinkedIn", off["text"])

	def test_the_call_to_action_is_a_label_with_an_https_address(self):
		def anchors(**values):
			return soup(render_person(template(**values), person())["html"]).find_all(
				"a", string="Book a call"
			)

		found = anchors(cta_label="Book a call", cta_url="https://example.com/book")
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0]["href"], "https://example.com/book")
		self.assertIn("text-decoration:underline", found[0]["style"], "a small coloured link")
		for values in (
			{"cta_label": "Book a call", "cta_url": "http://example.com/book"},
			{"cta_label": "Book a call", "cta_url": "javascript:alert(1)"},
			{"cta_label": "Book a call", "cta_url": ""},
			{"cta_label": "", "cta_url": "https://example.com/book"},
		):
			result = render_person(template(**values), person())
			self.assertNotIn("Book a call", result["html"], values)
			self.assertNotIn("example.com/book", result["html"], values)
			self.assertNotIn("example.com/book", result["text"], values)

	def test_the_website_is_a_link_only_when_it_is_a_web_address(self):
		for stored, words, href in (
			("www.example.com", "www.example.com", "https://www.example.com"),
			("example.com/shop/", "example.com/shop", "https://example.com/shop/"),
			("https://example.com", "example.com", "https://example.com"),
			("http://example.com/a?b=1", "example.com/a?b=1", "http://example.com/a?b=1"),
			# A '://' further in is part of the address, not its scheme
			(
				"shop.example.com/?from=https://example.org",
				"shop.example.com/?from=https://example.org",
				"https://shop.example.com/?from=https://example.org",
			),
		):
			self.assertEqual(signatures.web_address(stored), (words, href), stored)
			self.assertIn(f'href="{href}"', render_person(template(), person(website=stored))["html"], stored)
		for stored in (
			"javascript:alert(1)",
			"mailto:someone@example.com",
			"data:text/html,x",
			"ftp://example.com",
			"not a website",
			"localhost",
			"user@example.com",
			'example.com"onclick="x',
			"",
			None,
		):
			self.assertIsNone(signatures.web_address(stored), stored)
			self.assertNotIn(_("Website"), render_person(template(), person(website=stored))["html"], stored)

	def test_the_email_is_a_link_when_it_is_an_address(self):
		html = render_person(template(), person())["html"]
		self.assertEqual(soup(html).find("a", string="alex@example.com")["href"], "mailto:alex@example.com")
		# Something that is not an address is shown as words, never as a link
		html = render_person(template(), person(email="alex at example"))["html"]
		self.assertIn("alex at example", html)
		self.assertNotIn("mailto:", html)

	def test_the_logo_is_the_company_file_as_stored(self):
		for stored in (
			MISSING_LOGO,
			"/private/files/example logo.png",
			"https://cdn.example.com/logo.png",
		):
			html = render_person(template("Logo left"), person(logo=stored))["html"]
			image = soup(html).find("img")
			self.assertEqual(image["src"], stored)
			self.assertEqual(image["alt"], "Example Ltd")
			self.assertEqual(image["width"], "120")
			self.assertIn("width:120px;", image["style"])
			self.assertIn("display:block", image["style"])
			self.assertNotIn("data:", html)
		# No embedded picture, no other scheme, no way out of the files
		for stored in (
			"data:image/png;base64,iVBORw0KGgo=",
			"javascript:alert(1)",
			"http://insecure.example.com/logo.png",
			"/files/../private/secret.png",
			"/app/file/secret",
			'/files/a.png" onerror="x',
			"files/logo.png",
			"",
			None,
		):
			html = render_person(template("Logo left"), person(logo=stored))["html"]
			self.assertIsNone(soup(html).find("img"), repr(stored))

	def test_the_logo_height_is_the_files_own_proportion_when_it_can_be_read(self):
		# A file that is not there: the width alone decides, the height follows it
		image = soup(render_person(template("Logo left", logo_width=100), person())["html"]).find("img")
		self.assertNotIn("height", image.attrs)
		self.assertIn("height:auto;", image["style"])
		# A file of the instance: its proportions, whatever the width asked
		logo = self.logo_file(width=400, height=100)
		for width, height in ((100, 25), (240, 60), (60, 15)):
			html = render_person(template("Logo left", logo_width=width), person(logo=logo))["html"]
			image = soup(html).find("img")
			self.assertEqual((image["width"], image["height"]), (str(width), str(height)))
			self.assertIn(f"width:{width}px;height:{height}px;", image["style"])
		# A file that is no picture, or an address that is not a file here: no height, and no error
		for stored in (
			self.logo_file(content=b"not a picture", extension="txt"),
			"https://cdn.example.com/logo.png",
			"/files/zz-signature-test-a%00b.png",
			"/files/zz-signature-test-%2e%2e/%2e%2e/site_config.json",
		):
			image = soup(render_person(template("Logo left"), person(logo=stored))["html"]).find("img")
			self.assertNotIn("height", image.attrs, stored)

	def test_neomail_is_handed_the_logo_by_its_bytes_and_where_it_goes(self):
		"""MailCraft drops the pictures of a signature's HTML (its `signature.set`): the page hands it the template's logo
		itself, read from the instance's files, and the place the layout gives it (www/neomail.py)."""
		import base64

		from frappe_webmail.www.neomail import MAX_PICTURE_BYTES, handed_picture

		logo = self.logo_file(width=40, height=10)
		for layout, place in (("Logo left", "pictureLeft"), ("Logo above", "pictureAbove")):
			handed = handed_picture(render_person(template(layout, logo_width=80), person(logo=logo)), {})
			self.assertEqual(handed["layout"], place)
			self.assertEqual((handed["logo"]["width"], handed["logo"]["alt"]), (80, "Example Ltd"))
			self.assertEqual(handed["logo"]["name"], logo.rsplit("/", 1)[1])
			self.assertTrue(base64.b64decode(handed["logo"]["data"]).startswith(b"\x89PNG\r\n\x1a\n"))
		# A layout that draws no logo, and a person's own signature, hand none
		for layout in ("Text only", "Compact"):
			self.assertIsNone(handed_picture(render_person(template(layout), person(logo=logo)), {}), layout)
		self.assertIsNone(handed_picture({"html": "<p>Me</p>", "text": "Me"}, {}))
		# Nor does a logo elsewhere (MailCraft fetches nothing for a signature), one no longer there, or a file it would not
		# keep: no PNG, JPEG or GIF by its own bytes, or heavier than it takes
		for stored in (
			"https://cdn.example.com/logo.png",
			MISSING_LOGO,
			self.logo_file(content=b"<svg xmlns='http://www.w3.org/2000/svg'/>", extension="svg"),
			self.logo_file(content=b"\x89PNG\r\n\x1a\n" + b"\0" * MAX_PICTURE_BYTES),
		):
			self.assertIsNone(
				handed_picture(render_person(template("Logo left"), person(logo=stored)), {}), stored
			)
		# The file is read once a page, whatever the number of mailboxes that carry it
		memo = {}
		chosen = render_person(template("Logo left"), person(logo=logo))
		handed_picture(chosen, memo)
		with patch("frappe_webmail.www.neomail._picture_of", side_effect=AssertionError("read again")):
			self.assertIsNotNone(handed_picture(chosen, memo))

	def logo_file(self, width=1, height=1, content=None, extension="png"):
		"""A public file of the instance, a picture of that size or those bytes, removed after the test: its address."""
		from PIL import Image

		if content is None:
			buffer = io.BytesIO()
			Image.new("RGB", (width, height), (31, 58, 95)).save(buffer, "PNG")
			content = buffer.getvalue()
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{PREFIX}-{frappe.generate_hash(length=8)}.{extension}",
				"content": content,
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "File", file.name, force=True, ignore_permissions=True)
		return file.file_url

	def test_the_text_is_one_line_per_item(self):
		result = render_person(
			template(
				"Logo left",
				show_department=1,
				show_mobile=1,
				show_company_address=1,
				show_disclaimer=1,
				disclaimer="\n First line \n\nSecond line\n\n",
				social_links=[
					link("LinkedIn", "https://www.linkedin.com/in/alex"),
					link("YouTube", "https://youtube.example.com/a"),
				],
				cta_label="Book a call",
				cta_url="https://example.com/book",
			),
			person(),
		)
		self.assertEqual(
			result["text"],
			"\n".join(
				[
					"Alex Example",
					"Head of Sales, Sales",
					"Example Ltd",
					f"{_('Phone')}: +41 00 000 00 00",
					f"{_('Mobile')}: +41 00 000 00 01",
					f"{_('Email')}: alex@example.com",
					f"{_('Website')}: www.example.com/shop",
					"Main Street 1, 1000 Town",
					"LinkedIn: https://www.linkedin.com/in/alex",
					"YouTube: https://youtube.example.com/a",
					"Book a call: https://example.com/book",
					"",
					"First line",
					"",
					"Second line",
				]
			),
		)

	def test_a_line_of_the_disclaimer_is_a_line_of_the_html_too(self):
		html = render_person(template(show_disclaimer=1, disclaimer="One\n\nTwo & three"), person())["html"]
		self.assertIn("One<br><br>Two &amp; three</td>", html)

	def test_card_of_gives_what_the_layouts_draw(self):
		card = card_of(template(), person(mobile=""))
		self.assertEqual([part["kind"] for part in card["identity"]], ["name", "role", "company"])
		self.assertEqual(
			[contact["text"] for contact in card["contacts"]],
			["+41 00 000 00 00", "alex@example.com", "www.example.com/shop"],
		)
		self.assertIsNone(card["action"])
		self.assertEqual((card["social"], card["disclaimer"], card["address"]), ([], [], ""))

	def test_a_layout_is_a_file_of_templates_signatures(self):
		folder = os.path.join(os.path.dirname(signatures.__file__), "templates", "signatures")
		for name, file in LAYOUTS.items():
			self.assertTrue(os.path.isfile(os.path.join(folder, file)), f"{name}: {file}")


class TestFromTheSite(FrappeTestCase):
	"""What a signature says about a person comes from their records."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")

	def test_the_name_comes_from_the_user_and_an_empty_number_is_left_out(self):
		frappe.db.set_value("User", USER, {"mobile_no": None, "phone": None})
		known = signatures.person_of(USER)
		self.assertEqual(known.name, "Sigtest Person")
		self.assertEqual(known.email, USER)
		self.assertEqual(known.mobile, "")
		with patch.object(signatures, "_company_of", return_value=frappe._dict()):
			html = render_person(template(show_mobile=1), signatures.person_of(USER))["html"]
		self.assertIn("Sigtest Person", html)
		self.assertNotIn(_("Mobile"), html)
		frappe.db.set_value("User", USER, "mobile_no", "+41 00 000 00 02")
		self.assertEqual(signatures.person_of(USER).mobile, "+41 00 000 00 02")

	def test_the_employee_s_values_win_over_the_user_s(self):
		employee = frappe._dict(
			employee_name="Sigtest Employee",
			designation="Chief Tester",
			department="Quality - TST",
			cell_number="+41 00 000 00 99",
			company_email="sigtest.employee@example.com",
			company="Test Company",
		)
		company = frappe._dict(
			company_name="Test Company",
			company_logo="/files/test-company.png",
			phone_no="+41 00 000 00 10",
			email="info@example.com",
			website="www.example.com",
			address="Main Street 1, 1000 Town",
		)
		frappe.db.set_value("User", USER, {"mobile_no": "+41 00 000 00 02", "phone": None})
		with (
			patch.object(signatures, "_employee_of", return_value=employee),
			patch.object(signatures, "_company_of", return_value=company),
			patch.object(signatures, "_department_name", return_value="Quality"),
		):
			known = signatures.person_of(USER)
		self.assertEqual(known.name, "Sigtest Employee")
		self.assertEqual(known.job_title, "Chief Tester")
		self.assertEqual(known.department, "Quality")
		self.assertEqual(known.mobile, "+41 00 000 00 99", "the employee's before the user's")
		self.assertEqual(known.email, "sigtest.employee@example.com")
		self.assertEqual(known.phone, "+41 00 000 00 10", "the company's number, the user having none")
		self.assertEqual(
			(known.company_name, known.website, known.logo, known.address),
			("Test Company", "www.example.com", "/files/test-company.png", "Main Street 1, 1000 Town"),
		)

	def test_the_user_s_own_number_comes_before_the_company_s(self):
		frappe.db.set_value("User", USER, {"phone": "+41 00 000 00 03"})
		company = frappe._dict(company_name="Test Company", phone_no="+41 00 000 00 10")
		with patch.object(signatures, "_company_of", return_value=company):
			self.assertEqual(signatures.person_of(USER).phone, "+41 00 000 00 03")

	def test_the_company_s_address_is_read_from_its_own_address(self):
		"""The one query of the module that reads ERPNext's tables: an Address linked to the company and marked as its own."""
		company = frappe.db.get_value("Company", {}, "name")
		country = frappe.db.get_value("Country", {}, "name")
		if not (company and country and frappe.db.exists("Address Template", {"is_default": 1})):
			self.skipTest("this site has no company, country or default address template")
		if not frappe.get_meta("Address").has_field("is_your_company_address"):
			self.skipTest("Address has no is_your_company_address field (ERPNext adds it)")
		# The company's other addresses would be read first: they are set aside for the test
		frappe.db.sql(
			"""update `tabAddress` set disabled = 1 where name in (
				select parent from `tabDynamic Link`
				where parenttype = 'Address' and link_doctype = 'Company' and link_name = %s)""",
			(company,),
		)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"{PREFIX}-{frappe.generate_hash(length=6)}",
				"address_type": "Office",
				"address_line1": "Test Street 1",
				"address_line2": "Block B",
				"pincode": "1234",
				"city": "Testville",
				"country": country,
				"links": [{"link_doctype": "Company", "link_name": company}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Address", address.name, force=True, ignore_permissions=True)
		self.assertEqual(signatures._company_address(company), "Test Street 1, Block B, 1234 Testville")
		self.assertEqual(signatures._company_of(company).address, "Test Street 1, Block B, 1234 Testville")
		# A disabled one is not read, and a company with none has no address
		frappe.db.set_value("Address", address.name, "disabled", 1)
		self.assertEqual(signatures._company_address(company), "")

	def test_the_house_number_is_put_back_after_the_street(self):
		"""Where Address keeps the number in a field of its own, address_line1 is the street alone: a line read as it is
		would give the street without its number."""
		street = frappe._dict(
			address_line1="Test Street",
			address_line2="Block B",
			pincode="1234",
			city="Testville",
			custom_house_number="12",
		)
		meta = MagicMock()
		meta.has_field.return_value = True
		with (
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe, "get_all", return_value=[street]) as get_all,
		):
			self.assertEqual(
				signatures._company_address("Test Company"), "Test Street 12, Block B, 1234 Testville"
			)
		self.assertIn("custom_house_number", get_all.call_args.kwargs["fields"])
		# Where it has none, the number is in the line, which is read as it is and asked for no such field
		meta.has_field.side_effect = lambda field: field != "custom_house_number"
		combined = frappe._dict(
			address_line1="Test Street 12", address_line2="", pincode="", city="Testville"
		)
		with (
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe, "get_all", return_value=[combined]) as get_all,
		):
			self.assertEqual(signatures._company_address("Test Company"), "Test Street 12, Testville")
		self.assertNotIn("custom_house_number", get_all.call_args.kwargs["fields"])
		# Without the field that marks a company's own address (no ERPNext): no query, no address
		meta.has_field.side_effect = lambda field: False
		with patch.object(frappe, "get_meta", return_value=meta), patch.object(frappe, "get_all") as get_all:
			self.assertEqual(signatures._company_address("Test Company"), "")
		get_all.assert_not_called()

	def test_a_site_without_erpnext_still_has_people(self):
		missing = ("Employee", "Company")
		with patch.object(
			frappe.db, "table_exists", side_effect=lambda doctype, *a, **k: doctype not in missing
		):
			known = signatures.person_of(USER)
		self.assertEqual((known.name, known.email), ("Sigtest Person", USER))
		self.assertEqual(
			(known.job_title, known.department, known.company_name, known.logo, known.address), ("",) * 5
		)


class TestTheTemplateThatApplies(SignatureTestCase):
	"""template_for: the most specific enabled template, then the most recently modified."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")
		make_user(PORTAL, "Sigtest", "Portal", desk=False)
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.department = frappe.db.get_value(
			"Department", {"is_group": 0, "parent_department": ["is", "set"]}, "name"
		) or frappe.db.get_value("Department", {"is_group": 0}, "name")

	def setUp(self):
		if not (self.company and self.department):
			self.skipTest("this site has no company or department")
		self.quiet_the_site()
		self.everyone = self.make_template("everyone")
		self.company_wide = self.make_template("company", applies_to="Company", company=self.company)
		self.in_department = self.make_template(
			"department", applies_to="Department", department=self.department
		)

	def disable(self, doc):
		frappe.db.set_value("Email Signature Template", doc.name, "enabled", 0)

	def asked(self, department=None, company=None):
		"""The name of template_for(USER) for a person of that department and company, as an Employee would say."""
		employee = frappe._dict(department=department, company=company)
		with (
			patch.object(signatures, "_employee_of", return_value=employee),
			patch.object(signatures, "_default_company", return_value=None),
		):
			found = template_for(USER)
		return found.name if found else None

	def test_the_department_beats_the_company_which_beats_everyone(self):
		self.assertEqual(self.asked(self.department, self.company), self.in_department.name)
		self.disable(self.in_department)
		self.assertEqual(self.asked(self.department, self.company), self.company_wide.name)
		self.disable(self.company_wide)
		self.assertEqual(self.asked(self.department, self.company), self.everyone.name)
		self.disable(self.everyone)
		self.assertIsNone(self.asked(self.department, self.company), "no template: none")

	def test_a_template_for_another_department_or_company_does_not_apply(self):
		self.assertEqual(self.asked("Elsewhere - XX", self.company), self.company_wide.name)
		self.assertEqual(self.asked("Elsewhere - XX", "Other Company"), self.everyone.name)
		self.assertEqual(self.asked(None, None), self.everyone.name, "a person with no employee: everyone's")
		self.disable(self.everyone)
		self.assertIsNone(self.asked(None, "Other Company"))
		self.assertIsNone(self.asked(None, None))
		self.assertEqual(self.asked(None, self.company), self.company_wide.name)

	def test_a_disabled_template_is_ignored(self):
		for doc in (self.in_department, self.company_wide, self.everyone):
			self.disable(doc)
		self.assertIsNone(self.asked(self.department, self.company))
		frappe.db.set_value("Email Signature Template", self.company_wide.name, "enabled", 1)
		self.assertEqual(self.asked(self.department, self.company), self.company_wide.name)

	def test_between_equals_the_most_recently_modified_wins(self):
		newer = self.make_template("everyone-newer")
		for doc, when in ((self.everyone, "2026-01-01 10:00:00"), (newer, "2026-02-01 10:00:00")):
			frappe.db.set_value("Email Signature Template", doc.name, "modified", when, update_modified=False)
		self.disable(self.in_department)
		self.disable(self.company_wide)
		self.assertEqual(self.asked(), newer.name)
		frappe.db.set_value(
			"Email Signature Template",
			self.everyone.name,
			"modified",
			"2026-03-01 10:00:00",
			update_modified=False,
		)
		self.assertEqual(self.asked(), self.everyone.name)

	def test_a_department_s_template_applies_under_it_and_the_nearest_wins(self):
		"""Department is a tree: a template for a department is for the departments under it too, and the one of the
		person's own department comes before the one of a department above it."""
		above = frappe.db.get_value("Department", self.department, "parent_department")
		if not above:
			self.skipTest("this site's department has no department above it")
		self.disable(self.in_department)
		upper = self.make_template("above", applies_to="Department", department=above)
		self.assertEqual(self.asked(self.department, self.company), upper.name, "the one above, under it")
		frappe.db.set_value("Email Signature Template", self.in_department.name, "enabled", 1)
		# Made before the one above, it still wins: it is nearer
		self.assertEqual(self.asked(self.department, self.company), self.in_department.name)
		# A department's template is not for the department above it
		self.assertEqual(self.asked(above, self.company), upper.name)
		self.disable(upper)
		self.assertEqual(self.asked(above, self.company), self.company_wide.name)

	def test_a_portal_account_has_no_template(self):
		"""A portal account writes no mail from the instance, and is told nothing of the company."""
		self.assertIsNotNone(template_for(USER))
		self.assertIsNone(template_for(PORTAL))
		self.assertIsNone(template_for("Guest"))
		self.assertIsNone(template_for("nobody_at_all@example.com"))

	def test_the_person_s_default_company_stands_in_for_an_employee_s(self):
		with (
			patch.object(signatures, "_employee_of", return_value=frappe._dict()),
			patch.object(signatures, "_default_company", return_value=self.company),
		):
			self.assertEqual(template_for(USER).name, self.company_wide.name)

	def test_a_site_that_has_not_the_doctype_yet_has_no_template(self):
		with patch.object(
			frappe.db,
			"table_exists",
			side_effect=lambda doctype, *a, **k: doctype != "Email Signature Template",
		):
			self.assertIsNone(template_for(USER))


class TestWhatTheComposersAreGiven(SignatureTestCase):
	"""signature_for, and the methods that hand it over."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")
		make_user(OTHER, "Sigtest", "Other")
		make_user(PORTAL, "Sigtest", "Portal", desk=False)

	def setUp(self):
		self.quiet_the_site()
		frappe.db.delete("Email Signature", {"user": ["in", (USER, OTHER, PORTAL)]})
		frappe.set_user(USER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def personal(self, user=USER, content="<p>My own signature</p>", default=True):
		"""An Email Signature of the user, removed after the test."""
		doc = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": user,
				"signature_name": f"{PREFIX}-{frappe.generate_hash(length=6)}",
				"is_default": int(default),
				"content": content,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Email Signature", doc.name, force=True, ignore_permissions=True)
		return doc

	def company_signature(self):
		"""An enabled template for everyone: the name and the e-mail address, text only."""
		return self.make_template(
			"company", show_job_title=0, show_phone=0, show_mobile=0, show_website=0, show_company_name=0
		)

	def test_no_template_keeps_what_the_webmail_has_always_given(self):
		from frappe_webmail.api import get_default_signature

		self.assertIsNone(signature_for(USER))
		self.assertEqual(get_default_signature(), "")
		mine = self.personal(content='<div class="ql-editor read-mode"><p>Sigtest</p><p><br></p></div>')
		given = signature_for(USER)
		self.assertEqual(given["html"], mine.content, "as stored")
		self.assertEqual(given["text"], "Sigtest")
		self.assertEqual(get_default_signature(), mine.content)
		# Someone else's is theirs
		frappe.set_user(OTHER)
		self.assertEqual(get_default_signature(), "")

	def test_the_default_signature_is_for_those_who_are_signed_in(self):
		from frappe_webmail.api import get_default_signature

		frappe.is_whitelisted(get_default_signature)
		self.assertNotIn(get_default_signature, frappe.guest_methods)

	def test_an_emptied_signature_of_their_own_does_not_win_over_the_template(self):
		"""Word and Outlook leave an emptied signature as a paragraph of a non-breaking space: it shows nothing, so the
		person has none. Without a template it is still given as stored, as the webmail has always given it."""
		mine = self.personal(content="<p>&nbsp;</p>")
		rule = self.company_signature()
		frappe.db.set_value("Email Signature Template", rule.name, "allow_personal", 1)
		self.assertTrue(signature_for(USER)["html"].startswith("<table"))
		frappe.db.set_value("Email Signature Template", rule.name, "enabled", 0)
		self.assertEqual(signature_for(USER)["html"], mine.content)

	def test_a_template_gives_the_company_signature_to_a_person_with_none_of_their_own(self):
		from frappe_webmail.api import get_default_signature

		self.company_signature()
		html = get_default_signature()
		self.assertTrue(html.startswith("<table"), html[:80])
		self.assertIn("Sigtest Person", html)
		self.assertIn(USER, html)
		given = signature_for(USER)
		self.assertEqual(given["html"], html)
		self.assertTrue(given["text"].startswith("Sigtest Person\n"), given["text"])
		self.assertIn(f"{_('Email')}: {USER}", given["text"])
		# Everyone gets theirs, written with their own name
		frappe.set_user(OTHER)
		self.assertIn("Sigtest Other", get_default_signature())
		self.assertNotIn("Sigtest Person", get_default_signature())

	def test_the_template_replaces_the_person_s_own_unless_it_lets_them_keep_it(self):
		from frappe_webmail.api import get_default_signature

		mine = self.personal()
		rule = self.company_signature()
		self.assertIn("Sigtest Person", get_default_signature())
		self.assertNotIn("My own signature", get_default_signature())
		frappe.db.set_value("Email Signature Template", rule.name, "allow_personal", 1)
		self.assertEqual(get_default_signature(), mine.content, "theirs wins")
		self.assertEqual(signature_for(USER)["html"], mine.content)
		# A person who has none gets the template all the same
		frappe.db.delete("Email Signature", {"user": USER})
		self.assertIn("Sigtest Person", get_default_signature())
		self.assertTrue(signature_for(USER)["html"].startswith("<table"))

	def test_a_disabled_template_leaves_the_person_their_own(self):
		from frappe_webmail.api import get_default_signature

		mine = self.personal()
		rule = self.company_signature()
		frappe.db.set_value("Email Signature Template", rule.name, "enabled", 0)
		self.assertEqual(get_default_signature(), mine.content)

	def test_a_template_that_says_nothing_leaves_the_person_their_own(self):
		from frappe_webmail.api import get_default_signature

		mine = self.personal()
		self.make_template("empty", **{switch: 0 for switch in signatures.SWITCHES})
		self.assertEqual(signature_for(USER)["html"], mine.content)
		self.assertEqual(get_default_signature(), mine.content)
		# With none of their own, they get none
		frappe.db.delete("Email Signature", {"user": USER})
		self.assertIsNone(signature_for(USER))
		self.assertEqual(get_default_signature(), "")

	def test_a_mailbox_names_its_own_signature_when_it_is_its_owner_s(self):
		theirs = self.personal(user=OTHER, content="<p>The team</p>", default=False)
		mine = self.personal(content="<p>Me</p>")
		# A mailbox of USER whose Link names a signature of OTHER: it is not used (Frappe checks only that it exists)
		borrowed = {"default_signature": theirs.name, "user": USER}
		self.assertEqual(own_signature(USER, borrowed)["text"], "Me")
		# A mailbox of OTHER that names theirs
		self.assertEqual(
			own_signature(OTHER, {"default_signature": theirs.name, "user": OTHER})["text"], "The team"
		)
		self.assertEqual(own_signature(USER, None)["html"], mine.content)
		self.assertEqual(own_signature(USER, {"default_signature": None, "user": USER})["html"], mine.content)
		emptied = self.personal(user=OTHER, content="<p>&nbsp;</p>", default=False)
		self.assertEqual(
			own_signature(USER, {"default_signature": emptied.name, "user": OTHER})["html"],
			mine.content,
			"a mailbox signature with nothing to show falls back on the person's",
		)

	def test_a_template_gives_every_mailbox_its_signature_too(self):
		self.company_signature()
		mailbox = self.personal(content="<p>Mailbox</p>", default=False)
		for box in (
			{"default_signature": None, "user": USER},
			{"default_signature": mailbox.name, "user": USER},
		):
			html = signature_for(USER, box)["html"]
			self.assertIn("Sigtest Person", html)
			self.assertNotIn("Mailbox", html)

	def test_a_failure_is_logged_and_the_person_keeps_their_own(self):
		from frappe_webmail.api import get_default_signature

		mine = self.personal()
		with (
			patch.object(signatures, "template_for", side_effect=RuntimeError("boom")),
			patch.object(frappe, "log_error") as log,
		):
			self.assertEqual(signature_for(USER)["html"], mine.content)
			self.assertEqual(get_default_signature(), mine.content)
		title, message = log.call_args.args[:2]
		self.assertLessEqual(len(title), 140)
		self.assertIn("boom", message)
		self.assertNotIn("boom", title)
		# When even theirs cannot be read: none, and the composer carries on
		with (
			patch.object(signatures, "template_for", side_effect=RuntimeError("boom")),
			patch.object(signatures, "own_signature", side_effect=RuntimeError("again")),
			patch.object(frappe, "log_error"),
		):
			self.assertIsNone(signature_for(USER))
			self.assertEqual(get_default_signature(), "")

	def test_a_shared_mailbox_signs_as_the_mailbox_and_never_as_the_writer(self):
		"""Written from a mailbox someone else owns (info@, shared with the person), a message carries the signature the
		mailbox names as its own, else the company's written for the mailbox: its name and address, the company's number,
		nothing of the person writing (their job, their numbers)."""
		self.make_template("team", show_mobile=1)
		shared = {
			"email": "team@webmail.test",
			"sender_name": "The Team",
			"default_signature": None,
			"user": OTHER,
		}
		writer = person(user=USER, name="Sigtest Person", email=USER)
		with (
			patch.object(signatures, "person_of", return_value=writer),
			patch.object(signatures, "_company_phone", return_value="+41 00 000 00 10"),
		):
			given = signature_for(USER, shared)
			theirs = signature_for(USER, {**shared, "user": USER})
		for words in ("The Team", "team@webmail.test", "+41 00 000 00 10", "Example Ltd"):
			self.assertIn(words, given["html"], words)
			self.assertIn(words, given["text"], words)
		for words in ("Sigtest Person", "Head of Sales", "+41 00 000 00 00", "+41 00 000 00 01", USER):
			self.assertNotIn(words, given["html"], words)
			self.assertNotIn(words, given["text"], words)
		# The writer's own mailbox carries their own card
		for words in ("Sigtest Person", "Head of Sales", "+41 00 000 00 01"):
			self.assertIn(words, theirs["html"], words)
		# A shared mailbox that names a signature of its owner carries that one, whoever writes
		team = self.personal(user=OTHER, content="<p>The team card</p>", default=False)
		named = signature_for(USER, {**shared, "default_signature": team.name})
		self.assertEqual(named, {"html": team.content, "text": "The team card"})

	def shared_box(self):
		"""A mailbox of OTHER's that USER writes from, with no signature of its own."""
		return {
			"email": "team@webmail.test",
			"sender_name": "The Team",
			"default_signature": None,
			"user": OTHER,
		}

	def test_under_a_template_a_shared_mailbox_never_carries_the_writer_s_own_signature(self):
		"""The writer's own signature is theirs to keep under their own mailboxes when the template allows it, never under
		a mailbox they share; a template with nothing to show, or one that can't be read, leaves a shared mailbox its own
		signature or none."""
		self.personal(content="<p>Mine</p>")
		rule = self.make_template("team")
		frappe.db.set_value("Email Signature Template", rule.name, "allow_personal", 1)
		given = signature_for(USER, self.shared_box())
		self.assertIn("The Team", given["html"])
		self.assertNotIn("Mine", given["html"])
		self.assertIn("Mine", signature_for(USER)["html"], "under their own mailbox they keep it")
		# A template with nothing to show
		frappe.db.set_value("Email Signature Template", rule.name, "enabled", 0)
		self.make_template("empty", **{switch: 0 for switch in signatures.SWITCHES})
		self.assertIsNone(signature_for(USER, self.shared_box()))
		self.assertIn("Mine", signature_for(USER)["html"])
		# A failure: the mailbox's own, else none
		team = self.personal(user=OTHER, content="<p>The team card</p>", default=False)
		with (
			patch.object(signatures, "template_for", side_effect=RuntimeError("boom")),
			patch.object(frappe, "log_error"),
		):
			self.assertIsNone(signature_for(USER, self.shared_box()))
			named = signature_for(USER, {**self.shared_box(), "default_signature": team.name})
			self.assertEqual(named["text"], "The team card")
			self.assertIn("Mine", signature_for(USER)["html"], "under their own mailbox: theirs")

	def test_a_failure_is_logged_once_for_all_the_mailboxes_of_a_page(self):
		mine = self.personal(content="<p>Mine</p>")
		memo = {}
		with (
			patch.object(signatures, "template_for", side_effect=RuntimeError("boom")),
			patch.object(frappe, "log_error") as log,
		):
			for n in range(3):
				box = {"email": f"box{n}@webmail.test", "default_signature": None, "user": USER}
				self.assertEqual(signature_for(USER, box, memo)["html"], mine.content)
		self.assertEqual(log.call_count, 1)

	def mailbox(self, email, owner, shared_with=(), sender_name=None):
		"""A Webmail Account of `owner`, shared with `shared_with`, removed after the test."""
		doc = frappe.get_doc(
			{
				"doctype": "Webmail Account",
				"email": email,
				"user": owner,
				"sender_name": sender_name or email,
				"imap_host": "imap.test.local",
				"imap_port": 993,
				"imap_ssl": 1,
				"imap_password": "test_password_123",
				"smtp_host": "smtp.test.local",
				"smtp_port": 587,
				"smtp_starttls": 1,
				"smtp_password": "test_password_123",
				"enabled": 1,
				"allowed_users": [{"user": user} for user in shared_with],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Webmail Account", doc.name, force=True, ignore_permissions=True)
		return doc

	def test_the_desk_s_composer_signs_each_mailbox_as_neomail_does(self):
		"""The desk asks for the signature of the mailbox a message leaves from: a shared one signs as the mailbox, never
		with the writer's card; one the person may not write from is refused."""
		from frappe_webmail.api import get_default_signature

		self.make_template("team", show_job_title=0, show_phone=0, show_website=0, show_company_name=0)
		frappe.set_user("Administrator")
		own = self.mailbox("signatures_own@webmail.test", USER)
		team = self.mailbox(
			"signatures_team@webmail.test", OTHER, shared_with=[USER], sender_name="The Signatures Team"
		)
		closed = self.mailbox("signatures_closed@webmail.test", OTHER)
		frappe.set_user(USER)
		self.assertIn("Sigtest Person", get_default_signature(own.name))
		under_team = get_default_signature(team.name)
		self.assertIn("The Signatures Team", under_team)
		self.assertIn("signatures_team@webmail.test", under_team)
		self.assertNotIn("Sigtest Person", under_team)
		self.assertNotIn(USER, under_team)
		self.assertEqual(
			get_default_signature(), get_default_signature(own.name), "no mailbox: the person's own"
		)
		with self.assertRaises(frappe.ValidationError):
			get_default_signature(closed.name)
		with self.assertRaises(frappe.ValidationError):
			get_default_signature("nobody_at_all@webmail.test")

	def test_the_template_and_the_person_are_worked_out_once_for_all_the_mailboxes(self):
		self.company_signature()
		memo = {}
		with (
			patch.object(signatures, "template_for", wraps=signatures.template_for) as found,
			patch.object(signatures, "person_of", wraps=signatures.person_of) as known,
		):
			given = [
				signature_for(
					USER, {"email": f"box{n}@webmail.test", "default_signature": None, "user": USER}, memo
				)
				for n in range(3)
			]
		self.assertEqual((found.call_count, known.call_count), (1, 1))
		self.assertEqual(given[0], given[2])
		self.assertIn("Sigtest Person", given[0]["html"])

	def test_a_portal_account_keeps_what_it_had(self):
		"""No template applies to a portal account: it is given its own signature, as before, and nothing of the
		company."""
		from frappe_webmail.api import get_default_signature

		self.company_signature()
		self.assertIsNone(signature_for(PORTAL))
		mine = self.personal(user=PORTAL, content="<p>Portal own</p>")
		self.assertEqual(signature_for(PORTAL), {"html": mine.content, "text": "Portal own"})
		frappe.set_user(PORTAL)
		self.assertEqual(get_default_signature(), mine.content)

	def test_the_desks_composer_and_neomail_are_given_the_same_signature(self):
		from frappe_webmail.api import get_default_signature
		from frappe_webmail.www import neomail

		self.company_signature()
		account = {
			"name": "signatures_box@webmail.test",
			"email": "signatures_box@webmail.test",
			"sender_name": "Sigtest",
			"default_signature": None,
			"user": USER,
		}
		with (
			patch("frappe_webmail.webmail_api.get_accounts", return_value=[account]),
			patch("frappe_webmail.mailcraft_jmap.give_token", return_value="token"),
		):
			boxes = neomail.host_mailboxes()
		self.assertEqual(len(boxes), 1)
		handed = boxes[0]["signature"]
		self.assertEqual(handed["html"], get_default_signature(), "the same HTML")
		self.assertIn("Sigtest Person", handed["text"])
		self.assertIn(USER, handed["text"])
		self.assertEqual(
			handed["text"], signature_for(USER)["text"], "the text written with it, line for line"
		)

	def test_neomail_keeps_its_signatures_when_no_template_applies(self):
		from frappe_webmail.www import neomail

		mine = self.personal(content="<p>Me</p>")
		team = self.personal(content="<p>The team</p>", default=False)
		accounts = [
			{"name": "a@webmail.test", "email": "a@webmail.test", "default_signature": None, "user": USER},
			{
				"name": "b@webmail.test",
				"email": "b@webmail.test",
				"default_signature": team.name,
				"user": USER,
			},
		]
		with (
			patch("frappe_webmail.webmail_api.get_accounts", return_value=accounts),
			patch("frappe_webmail.mailcraft_jmap.give_token", return_value="token"),
		):
			boxes = neomail.host_mailboxes()
		self.assertEqual(boxes[0]["signature"], {"html": mine.content, "text": "Me"})
		self.assertEqual(boxes[1]["signature"], {"html": team.content, "text": "The team"})
		frappe.db.delete("Email Signature", {"user": USER})
		with (
			patch("frappe_webmail.webmail_api.get_accounts", return_value=accounts[:1]),
			patch("frappe_webmail.mailcraft_jmap.give_token", return_value="token"),
		):
			self.assertNotIn("signature", neomail.host_mailboxes()[0])


class TestThePreview(SignatureTestCase):
	"""The form's preview: a template as it stands, written for a person, for those who may write it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")
		make_user(OTHER, "Sigtest", "Other")

	def tearDown(self):
		frappe.set_user("Administrator")

	def doc(self):
		return {
			"doctype": "Email Signature Template",
			"layout": "Compact",
			"show_phone": 0,
			"show_mobile": 0,
			"show_website": 0,
			"social_links": [
				{
					"doctype": "Email Signature Social Link",
					"network": "LinkedIn",
					"url": "https://www.linkedin.com/in/a",
				},
				{
					"doctype": "Email Signature Social Link",
					"network": "X",
					"url": "http://insecure.example.com",
				},
			],
		}

	def test_it_writes_a_template_that_is_not_saved(self):
		count = frappe.db.count("Email Signature Template")
		for given in (self.doc(), json.dumps(self.doc())):
			shown = signatures.preview(given, USER)
			self.assertEqual(set(shown), {"html", "text"})
			lines = soup(shown["html"]).find("td").find_all("div", recursive=False)
			self.assertEqual(len(lines), 3, "the compact layout: two lines, and the links")
			self.assertIn("Sigtest Person", shown["text"])
			self.assertIn("LinkedIn: https://www.linkedin.com/in/a", shown["text"])
			self.assertNotIn("insecure", shown["html"])
			self.assertNotIn(_("Phone"), shown["html"])
		self.assertEqual(frappe.db.count("Email Signature Template"), count)

	def test_it_is_written_for_the_person_who_asks_by_default(self):
		self.assertIn(signatures.person_of("Administrator").name, signatures.preview(self.doc())["text"])

	def test_whatever_the_form_says_it_is_it_is_read_as_a_template(self):
		shown = signatures.preview({**self.doc(), "doctype": "User"}, USER)
		self.assertIn("Sigtest Person", shown["text"])

	def test_it_refuses_what_is_not_a_template_or_a_person(self):
		with self.assertRaises(frappe.DoesNotExistError):
			signatures.preview(self.doc(), "nobody_at_all@example.com")
		with self.assertRaises(frappe.ValidationError):
			signatures.preview("[1, 2]")

	def test_it_is_for_those_who_may_write_the_template(self):
		frappe.is_whitelisted(signatures.preview)
		self.assertNotIn(signatures.preview, frappe.guest_methods)
		for refused in (USER, OTHER, "Guest"):
			frappe.set_user(refused)
			with self.assertRaises(frappe.PermissionError):
				signatures.preview(self.doc(), USER)

	def test_only_the_system_manager_reads_the_templates(self):
		rows = frappe.get_meta("Email Signature Template").permissions
		roles = {row.role for row in rows}
		self.assertIn("System Manager", roles)
		# An instance may let its own administrators' role read every DocType (one such is named Admin); nobody else.
		self.assertEqual(roles - {"System Manager", "Admin"}, set(), roles)
		rights = {row.role: (row.create, row.write, row.delete, row.read) for row in rows}
		self.assertEqual(rights.get("System Manager"), (1, 1, 1, 1))
		self.assertEqual(
			{role for role, given in rights.items() if any(given[:3])}, {"System Manager"}, rights
		)
		for user in (USER, OTHER):
			for ptype in ("read", "write", "create", "delete"):
				self.assertFalse(
					frappe.has_permission("Email Signature Template", ptype, user=user), (user, ptype)
				)


def shape(tree):
	"""A tag and what is under it, as the cleaning of a message sent may rewrite it, compared by what it says: the tags
	(a table body the cleaner adds is not one), their attributes, the declarations of their styles whichever their
	order, and the words."""
	rows = []
	for element in [tree, *tree.find_all(True)]:
		if element.name == "tbody":
			continue
		attributes = dict(element.attrs)
		if "style" in attributes:
			attributes["style"] = sorted(
				declaration.replace(" ", "")
				for declaration in attributes["style"].split(";")
				if declaration.strip()
			)
		rows.append((element.name, sorted((name, str(value)) for name, value in attributes.items())))
	return rows, tree.get_text()


class TestTheSignatureLeavesWithTheMessage(TestWebmailAPIBase):
	"""What the form shows is what leaves: the cleaning of a message sent keeps the layouts, their styles included."""

	def drawn(self, name):
		"""A layout with everything it can show, drawn for a person."""
		return render_person(
			template(
				name,
				font="Verdana",
				accent_color="#AA3300",
				show_department=1,
				show_mobile=1,
				show_company_address=1,
				show_disclaimer=1,
				disclaimer="Small print\nSecond line",
				social_links=[link("LinkedIn", "https://www.linkedin.com/in/a")],
				cta_label="Book a call",
				cta_url="https://example.com/book?a=1&b=2",
			),
			person(),
		)["html"]

	def test_the_styles_the_layouts_write_are_the_ones_the_cleaning_keeps(self):
		from frappe_webmail.webmail_api import EMAIL_CSS_PROPERTIES

		for name in LAYOUTS:
			for element in soup(self.drawn(name)).find_all(True):
				for declaration in filter(None, element.get("style", "").split(";")):
					self.assertIn(
						declaration.split(":")[0].strip(), EMAIL_CSS_PROPERTIES, f"{name}: {declaration}"
					)

	def sent_html(self, smtp_class, html_content):
		"""The HTML of the message that send_email hands to the (mocked) SMTP server for that text."""
		from frappe_webmail.api import send_email

		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()):
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Signature",
				html_content=html_content,
			)
		sent = email.message_from_string(server.sendmail.call_args.args[2])
		return (
			next(part for part in sent.walk() if part.get_content_type() == "text/html")
			.get_payload(decode=True)
			.decode()
		)

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_the_text_of_a_message_sent_says_where_its_links_and_its_banner_lead(self, smtp_class):
		"""Beside the HTML, the text a reader of the text alone gets: a link's address after its words, a banner's
		description and where it leads (email_html.plain_text); before, the tags went and so did every address."""
		server = MagicMock()
		smtp_class.return_value = server
		with mocked_imap(imap_client()):
			from frappe_webmail.api import send_email

			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Banner",
				html_content=(
					'<p>See <a href="https://example.com/offer">the offer</a></p><p>--</p>'
					'<a href="https://example.com/spring"><img src="https://example.com/banner.png" alt="Spring offer"></a>'
				),
			)
		sent = email.message_from_string(server.sendmail.call_args.args[2])
		text = next(part for part in sent.walk() if part.get_content_type() == "text/plain").get_payload(
			decode=True
		)
		self.assertEqual(
			text.decode(),
			"See the offer (https://example.com/offer)\n\n--\n\nSpring offer (https://example.com/spring)",
		)

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_a_message_sent_carries_the_signature_as_it_was_drawn(self, smtp_class):
		for name in LAYOUTS:
			drawn = self.drawn(name)
			html = self.sent_html(smtp_class, f"<p>Hello</p><p>--</p>{drawn}")
			self.assertEqual(shape(soup(html).find("table")), shape(soup(drawn).find("table")), name)
			self.assertIn("font-family:Verdana,Geneva,sans-serif", html, name)
			self.assertIn("#aa3300", html, name)

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_a_style_that_places_or_fetches_does_not_leave(self, smtp_class):
		"""The cleaning keeps the properties that style text and boxes and drops the others, values and all."""
		html = self.sent_html(
			smtp_class,
			'<p style="color:#aa3300;position:fixed;top:0;float:left;'
			'background-image:url(https://tracker.example.com/pixel.png)">Hello</p>',
		)
		self.assertIn("color:#aa3300", html)
		for dropped in ("position", "float", "top:", "background-image", "tracker.example.com"):
			self.assertNotIn(dropped, html)


class TestThePhotoAndTheBannerAreDrawn(FrappeTestCase):
	"""The Photo left layout and the banner, as a mail client is given them: a person and a template built in the test."""

	def test_photo_left_draws_the_photo_round_at_the_left_and_the_logo_under_the_details(self):
		tree = soup(render_person(template("Photo left"), person(photo=PHOTO))["html"])
		cells = tree.find("tr").find_all("td", recursive=False)
		self.assertEqual(len(cells), 2, "the photo in a column, the details in another")
		photo = cells[0].find("img")
		self.assertEqual(photo["src"], PHOTO)
		self.assertEqual((photo["width"], photo["height"]), ("96", "96"), "drawn at a fixed size")
		self.assertIn("width:96px;height:96px;", photo["style"])
		self.assertIn(
			"border-radius:48px;", photo["style"], "round where a mail client keeps rounded corners"
		)
		self.assertEqual(photo["alt"], "Alex Example")
		self.assertEqual(cells[0]["width"], "96", "the photo's column is as wide as the photo")
		self.assertEqual(len(cells[0].find_all("img")), 1)
		# At its right the details, and the company's logo under them
		self.assertEqual([image["src"] for image in cells[1].find_all("img")], [MISSING_LOGO])
		rows = cells[1].find("table").find_all("tr", recursive=False)
		self.assertIn("Alex Example", rows[0].get_text())
		self.assertIsNone(rows[0].find("img"))
		self.assertIsNotNone(rows[-1].find("img"), "the logo on the last row, under the details")
		self.assertNotIn("border-left", str(tree), "no rule between the photo and the details")
		# Without the logo: the photo and the details
		bare = soup(render_person(template("Photo left", show_logo=0), person(photo=PHOTO))["html"])
		self.assertEqual([image["src"] for image in bare.find_all("img")], [PHOTO])

	def test_photo_left_without_a_photo_leaves_no_empty_column(self):
		for case, (values, who) in {
			"the person shows none": ({}, person()),
			"the company shows none": ({"show_photo": 0}, person(photo=PHOTO)),
		}.items():
			result = render_person(template("Photo left", **values), who)
			tree = soup(result["html"])
			self.assertNotIn(PHOTO, result["html"], case)
			self.assertIsNone(result["photo"], case)
			for row in tree.find("table").find_all("tr", recursive=False):
				self.assertEqual(len(row.find_all("td", recursive=False)), 1, case)
			self.assertEqual([image["src"] for image in tree.find_all("img")], [MISSING_LOGO], case)
			self.assertIn("Alex Example", result["text"], case)
		# The photo alone, when nothing else is shown
		off = {switch: 0 for switch in signatures.SWITCHES}
		tree = soup(
			render_person(template("Photo left", **off | {"show_photo": 1}), person(photo=PHOTO))["html"]
		)
		self.assertEqual(len(tree.find_all("td")), 1)
		self.assertEqual(tree.find("img")["src"], PHOTO)

	def test_the_photo_is_drawn_in_the_photo_layout_only(self):
		for layout in LAYOUTS:
			result = render_person(template(layout), person(photo=PHOTO))
			self.assertEqual(PHOTO in result["html"], layout in signatures.WITH_PHOTO, layout)
			self.assertNotIn(PHOTO, result["text"], layout)

	def test_a_photo_is_a_file_of_the_instance(self):
		for stored in (
			"https://cdn.example.com/me.jpg",
			"data:image/jpeg;base64,/9j/4AAQ",
			"javascript:alert(1)",
			"/private/files/../site_config.json",
			"/private/files/%2e%2e/%2e%2e/site_config.json",
			'/private/files/a.jpg" onerror="x',
			"private/files/a.jpg",
			"",
			None,
		):
			html = render_person(template("Photo left"), person(photo=stored))["html"]
			self.assertEqual(
				[image["src"] for image in soup(html).find_all("img")], [MISSING_LOGO], repr(stored)
			)

	def test_a_banner_goes_under_the_signature_and_above_its_small_print_whatever_the_layout(self):
		small = {"show_disclaimer": 1, "disclaimer": "Small print"}
		for layout in LAYOUTS:
			plain = render_person(template(layout), person(photo=PHOTO))["html"]
			result = render_person(template(layout, **small, **banner()), person(photo=PHOTO))
			tree = soup(result["html"])
			roots = [child for child in tree.contents if getattr(child, "name", None)]
			self.assertEqual([root.name for root in roots], ["table"], f"{layout}: in one piece")
			rows = roots[0].find_all("tr", recursive=False)
			self.assertEqual(len(rows), 3, f"{layout}: the signature, the banner, the small print")
			# The signature as its layout draws it, untouched, then the banner, then the small print
			self.assertIn(plain, result["html"], layout)
			anchor = rows[1].find("a")
			self.assertEqual(anchor["href"], "https://example.com/fair", layout)
			self.assertTrue(anchor.get("style"), layout)
			image = anchor.find("img")
			self.assertEqual(
				(image["src"], image["width"], image["alt"]), (BANNER, "400", "Meet us at the fair"), layout
			)
			self.assertIn("width:400px;", image["style"], layout)
			self.assertEqual(rows[2].get_text(), "Small print", layout)
			# In the text: its words and its link, the small print still last
			self.assertTrue(
				result["text"].endswith("Meet us at the fair: https://example.com/fair\n\nSmall print"),
				layout,
			)

	def test_a_banner_link_is_an_https_address_and_its_width_is_bounded(self):
		for bad in (
			"http://example.com/fair",
			"javascript:alert(1)",
			"//example.com/fair",
			"https://example.com/ x",
			"",
		):
			result = render_person(template(**banner(banner_url=bad)), person())
			image = soup(result["html"]).find("img", src=BANNER)
			self.assertIsNotNone(image, repr(bad))
			self.assertIsNone(image.find_parent("a"), f"{bad!r}: a picture, not a link")
			self.assertNotIn("Meet us at the fair:", result["text"], repr(bad))
			self.assertNotIn("alert", result["html"], repr(bad))
		for width, expected in ((10, 200), (999, 600), (0, 400), (None, 400), ("300", 300)):
			drawn = render_person(template(**banner(banner_width=width)), person())["html"]
			self.assertEqual(soup(drawn).find("img", src=BANNER)["width"], str(expected), width)

	def test_a_banner_is_a_public_picture_of_the_instance(self):
		"""Public: every person who writes with the signature shows it, and a template's private file is the System
		Manager's to read."""
		for stored in (
			f"/private/files/{PREFIX}-banner.png",
			"https://cdn.example.com/banner.png",
			"data:image/png;base64,iVBORw0KGgo=",
			"javascript:alert(1)",
			"/files/../private/files/x.png",
			"/files/%2e%2e/private/files/x.png",
			"files/banner.png",
			"",
			None,
		):
			result = render_person(template(**banner(banner_image=stored)), person())
			self.assertIsNone(soup(result["html"]).find("a", href="https://example.com/fair"), repr(stored))
			self.assertNotIn("Meet us at the fair", result["text"], repr(stored))

	def test_the_banner_height_is_its_file_s_own_proportion(self):
		src = picture_file(self, width=600, height=150)
		for width, height in ((400, 100), (200, 50), (600, 150)):
			drawn = render_person(template(**banner(banner_image=src, banner_width=width)), person())["html"]
			image = soup(drawn).find("img", src=src)
			self.assertEqual((image["width"], image["height"]), (str(width), str(height)))
			self.assertIn(f"width:{width}px;height:{height}px;", image["style"])
		# A file that is not there: its width alone, the height following it
		image = soup(render_person(template(**banner()), person())["html"]).find("img", src=BANNER)
		self.assertNotIn("height", image.attrs)
		self.assertIn("height:auto;", image["style"])

	def test_a_banner_alone_is_a_signature_and_its_words_have_a_fallback(self):
		off = {switch: 0 for switch in signatures.SWITCHES}
		result = render_person(template(**off, **banner()), person(photo=PHOTO))
		tree = soup(result["html"])
		self.assertEqual(len(tree.find_all("img")), 1)
		self.assertEqual(len(tree.find_all("td")), 1, "the banner alone")
		self.assertEqual(result["text"], "Meet us at the fair: https://example.com/fair")
		# Words of its own, else the company's name (the form asks for its words before it saves a banner)
		for description, company, expected in (("", "Example Ltd", "Example Ltd"), (" ", "", _("Banner"))):
			drawn = render_person(
				template(**banner(banner_description=description)), person(company_name=company)
			)
			self.assertEqual(soup(drawn["html"]).find("img", src=BANNER)["alt"], expected)

	def test_the_photo_and_the_banner_are_escaped_like_every_value(self):
		hostile = person(name='Alex "><script>alert(1)</script>', photo=PHOTO)
		words = 'Fair "><img src=x onerror=alert(2)> & more'
		html = render_person(template("Photo left", **banner(banner_description=words)), hostile)["html"]
		self.assertNotIn("<script", html.lower())
		self.assertNotIn("<img src=x", html.lower())
		tree = soup(html)
		self.assertIsNone(tree.find("script"))
		self.assertEqual(tree.find("img", src=PHOTO)["alt"], 'Alex "><script>alert(1)</script>')
		self.assertEqual(tree.find("img", src=BANNER)["alt"], words)
		self.assertEqual(len(tree.find_all("img")), 3, "the photo, the logo, the banner: nothing more")

	def test_the_photo_and_the_banner_keep_to_what_a_message_sent_keeps(self):
		from frappe_webmail.webmail_api import EMAIL_CSS_PROPERTIES

		for layout in LAYOUTS:
			drawn = render_person(
				template(layout, show_disclaimer=1, disclaimer="Small print", **banner()), person(photo=PHOTO)
			)["html"]
			self.assertNotIn("\n", drawn, layout)
			self.assertNotIn("data:", drawn, layout)
			tree = soup(drawn)
			for element in tree.find_all(True):
				self.assertIn(element.name, KEPT_TAGS, layout)
				kept = KEPT_ATTRIBUTES["*"] | KEPT_ATTRIBUTES.get(element.name, set())
				self.assertLessEqual(set(element.attrs), kept, f"{layout}: {element.name}")
				if element.name in ("table", "td", "div", "span", "a", "img"):
					self.assertTrue(element.get("style"), f"{layout}: a style on every {element.name}")
					self.assertNotRegex(
						element["style"], r"flex|grid|margin|float|position|var\(|calc\(|url\(", layout
					)
				for declaration in filter(None, element.get("style", "").split(";")):
					self.assertIn(
						declaration.split(":")[0].strip(), EMAIL_CSS_PROPERTIES, f"{layout}: {declaration}"
					)
			for image in tree.find_all("img"):
				self.assertTrue(image.get("width") and image.get("alt"), layout)
			for anchor in tree.find_all("a"):
				self.assertRegex(anchor["href"], r"^(https://|mailto:)", layout)


class PhotoTestCase(SignatureTestCase):
	"""Tests that give people a picture and choices: the worker that makes a copy again is not asked (its job is called
	by the tests that need it), and what a test gives a person is taken back."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")
		make_user(OTHER, "Sigtest", "Other")
		make_user(PORTAL, "Sigtest", "Portal", desk=False)

	def setUp(self):
		self.quiet_the_site()
		later = patch.object(signature_photos, "refresh_later")
		self.later = later.start()
		self.addCleanup(later.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		for user in (USER, OTHER, PORTAL):
			self.forget(user)

	def forget(self, user):
		"""The person without choices, picture or copy; USER with a mobile number (a number is one person's: unique)."""
		name = frappe.db.get_value(PREFERENCE, {"user": user}, "name")
		if name:
			frappe.delete_doc(PREFERENCE, name, force=True, ignore_permissions=True)
		mobile = "+41 00 000 00 02" if user == USER else None
		frappe.db.set_value("User", user, {"user_image": None, "mobile_no": mobile})

	def face(self, user=USER, **picture):
		"""A picture of the person, as their User's (a public file of the instance): its address."""
		url = picture_file(self, **picture)
		frappe.db.set_value("User", user, "user_image", url)
		return url

	def choose(self, user=USER, **values):
		"""The person's choices saved in their record, made the first time and removed after the test."""
		name = frappe.db.get_value(PREFERENCE, {"user": user}, "name")
		doc = (
			frappe.get_doc(PREFERENCE, name)
			if name
			else frappe.get_doc({"doctype": PREFERENCE, "user": user})
		)
		doc.update(values)
		doc.save(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, PREFERENCE, doc.name, force=True, ignore_permissions=True)
		return doc

	def copies(self, user=USER):
		"""The copies of the person's photo: the File records attached to their preference."""
		name = frappe.db.get_value(PREFERENCE, {"user": user}, "name")
		if not name:
			return []
		return frappe.get_all(
			"File",
			filters={"attached_to_doctype": PREFERENCE, "attached_to_name": name},
			fields=["name", "file_url", "is_private"],
		)


class TestThePersonsChoices(PhotoTestCase):
	"""Each person's choices of the company signature: their photo only if they say yes, and gone when they say no; their
	mobile hidden if they wish; the copy of their photo made once, and again only when its source changes."""

	def test_a_person_who_made_no_choice_shows_no_photo_and_keeps_their_mobile(self):
		self.face()
		known = signatures.person_of(USER)
		self.assertEqual((known.photo, known.mobile), ("", "+41 00 000 00 02"))
		self.assertIsNone(frappe.db.get_value(PREFERENCE, {"user": USER}))
		self.assertIsNone(render_person(template("Photo left", show_mobile=1), known)["photo"])
		self.assertIn("+41 00 000 00 02", render_person(template(show_mobile=1), known)["html"])

	def test_the_mobile_a_person_hides_is_left_out(self):
		self.choose(hide_mobile=1)
		known = signatures.person_of(USER)
		self.assertEqual(known.mobile, "")
		result = render_person(template(show_mobile=1), known)
		self.assertNotIn("+41 00 000 00 02", result["html"])
		self.assertNotIn(f"{_('Mobile')}:", result["text"])
		self.choose(hide_mobile=0)
		self.assertEqual(signatures.person_of(USER).mobile, "+41 00 000 00 02")

	def test_the_photo_is_there_only_with_the_person_s_consent_and_goes_with_it(self):
		from PIL import Image

		self.face(width=300, height=400, colour=(200, 40, 40))
		self.assertEqual(signatures.person_of(USER).photo, "", "no choice made: no photo")
		self.choose(hide_mobile=1)
		self.assertEqual(signatures.person_of(USER).photo, "", "another choice: still no photo")
		self.assertEqual(self.copies(), [])
		doc = self.choose(photo_allowed=1)
		copies = self.copies()
		self.assertEqual(len(copies), 1, "one copy, made when they agree")
		copy = copies[0]
		self.assertTrue(copy.is_private, "a private file of the instance")
		self.assertTrue(copy.file_url.startswith("/private/files/"))
		self.assertEqual(frappe.db.get_value(PREFERENCE, doc.name, "photo"), copy.file_url)
		content = frappe.get_doc("File", copy.name).get_content()
		picture = Image.open(io.BytesIO(content))
		self.assertEqual(
			(picture.format, picture.size),
			("JPEG", (signatures.PHOTO_SIZE, signatures.PHOTO_SIZE)),
			"a square of 96 pixels",
		)
		self.assertFalse(dict(picture.getexif()), "nothing of the source's metadata")
		self.assertLess(len(content), 20_000, "a few kilobytes in each message")
		known = signatures.person_of(USER)
		self.assertEqual(known.photo, copy.file_url)
		drawn = render_person(template("Photo left"), known)
		self.assertEqual(drawn["photo"]["src"], copy.file_url)
		self.assertIn(f'src="{copy.file_url}"', drawn["html"])
		# Taken back: gone from the signature, and the copy from the instance
		on_disk = signatures._file_on_disk(copy.file_url)
		self.choose(photo_allowed=0)
		self.assertEqual(signatures.person_of(USER).photo, "")
		self.assertIsNone(render_person(template("Photo left"), signatures.person_of(USER))["photo"])
		self.assertEqual(self.copies(), [])
		self.assertFalse(frappe.db.exists("File", copy.name))
		self.assertFalse(os.path.exists(on_disk), "the copy's file is deleted too")
		self.assertEqual(frappe.db.get_value(PREFERENCE, doc.name, ["photo", "photo_source"]), (None, None))

	def test_the_copy_is_made_once_and_again_only_when_its_source_changes(self):
		self.face(width=200, height=200, colour=(10, 120, 10))
		self.choose(photo_allowed=1)
		first = self.copies()
		self.assertEqual(len(first), 1)
		with patch.object(signature_photos, "reduced", wraps=signature_photos.reduced) as made:
			self.choose(hide_mobile=1)
			for _n in range(3):
				self.assertEqual(signatures.person_of(USER).photo, first[0].file_url)
			self.assertEqual(made.call_count, 0, "nothing changed: not made again")
		self.assertEqual(self.copies(), first)
		self.later.assert_not_called()
		# A new picture: the copy is out of date, left out, and a worker is asked to make it again
		self.face(width=220, height=200, colour=(10, 10, 120))
		self.assertEqual(signature_photos.photo_state(USER, signatures.preference_of(USER)), ("", "pending"))
		self.assertEqual(signatures.person_of(USER).photo, "")
		self.later.assert_called_with(USER)
		# The worker's job: a new copy, the old one deleted
		made = signature_photos.refresh(USER)
		self.assertTrue(made)
		self.assertNotEqual(made, first[0].file_url)
		self.assertEqual([copy.file_url for copy in self.copies()], [made])
		self.assertFalse(frappe.db.exists("File", first[0].name))
		self.assertEqual(signatures.person_of(USER).photo, made)
		# No picture any more: no photo, and its copy goes
		frappe.db.set_value("User", USER, "user_image", None)
		self.assertEqual(signature_photos.photo_state(USER, signatures.preference_of(USER)), ("", "missing"))
		signature_photos.refresh(USER)
		self.assertEqual(self.copies(), [])
		self.assertEqual(signature_photos.photo_state(USER, signatures.preference_of(USER)), ("", "missing"))

	def test_a_worker_is_asked_once_for_a_person(self):
		"""refresh_later itself: one job waiting at a time for each person, on the short queue."""
		with patch.object(frappe, "enqueue") as enqueue:
			REFRESH_LATER(USER)
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(enqueue.call_args.args[0], "frappe_webmail.signature_photos.refresh")
		self.assertEqual((kwargs["user"], kwargs["deduplicate"]), (USER, True))
		self.assertIn(USER, kwargs["job_id"])
		with (
			patch.object(frappe, "enqueue", side_effect=RuntimeError("no queue")),
			patch.object(frappe, "log_error") as log,
		):
			REFRESH_LATER(USER)
		self.assertLessEqual(len(log.call_args.args[0]), 140)
		self.assertIn("no queue", log.call_args.args[1])

	def test_the_employee_s_picture_comes_before_the_user_s(self):
		account = frappe._dict(user_image="/files/user.png")
		self.assertEqual(
			signature_photos.source_of(
				USER, frappe._dict(name="HR-EMP-0001", image="/files/employee.png"), account
			),
			("/files/employee.png", "Employee", "HR-EMP-0001"),
		)
		self.assertEqual(
			signature_photos.source_of(USER, frappe._dict(name="HR-EMP-0001", image=" "), account),
			("/files/user.png", "User", USER),
			"an Employee without a picture: the User's",
		)
		self.assertEqual(signature_photos.source_of(USER, frappe._dict(), frappe._dict()), ("", None, None))
		url = self.face()
		with patch.object(signatures, "_employee_of", return_value=frappe._dict()):
			self.assertEqual(signature_photos.source_of(USER), (url, "User", USER), "read from the records")

	def test_a_photo_that_cannot_be_read_is_left_out_and_logged_once(self):
		broken = picture_file(
			self,
			content=b"not a picture at all",
			extension="png",
			is_private=1,
			attached_to_doctype="User",
			attached_to_name=USER,
		)
		frappe.db.set_value("User", USER, "user_image", broken)
		with patch.object(frappe, "log_error") as log:
			self.choose(photo_allowed=1)
			self.assertEqual(self.copies(), [])
			self.assertEqual(log.call_count, 1)
			title, message = log.call_args.args[:2]
			self.assertEqual(title, "Email signature photo could not be read")
			self.assertLessEqual(len(title), 140)
			self.assertIn(USER, message)
			# Known as unreadable: left out without a word, and not tried again until the picture changes
			self.assertEqual(
				signature_photos.photo_state(USER, signatures.preference_of(USER)), ("", "unreadable")
			)
			self.choose(hide_mobile=1)
			self.assertEqual(signatures.person_of(USER).photo, "")
			self.assertEqual(log.call_count, 1)
		self.later.assert_not_called()

	def test_a_private_picture_is_copied_only_from_the_employee_record(self):
		"""Anyone may point their own User's picture at any address, and Frappe lets anyone make a File record of any
		address: from the User record, a public picture only. A private one is taken from the Employee record (HR's
		choice), as a File attached to that very record."""
		theirs = picture_file(self, width=50, height=50, colour=(1, 2, 3), is_private=1)
		frappe.db.set_value("User", USER, "user_image", theirs)
		self.assertFalse(
			frappe.has_permission(
				"File", "read", doc=frappe.db.get_value("File", {"file_url": theirs}), user=USER
			)
		)
		with patch.object(frappe, "log_error") as log:
			self.choose(photo_allowed=1)
		self.assertEqual(self.copies(), [])
		self.assertEqual(log.call_count, 1)
		self.assertIsNone(signature_photos.usable_path(theirs, "User", USER))
		# Not even a private picture attached to their own User record, nor one they put in Neoffice themselves
		own = picture_file(
			self,
			width=50,
			height=52,
			colour=(1, 2, 3),
			is_private=1,
			attached_to_doctype="User",
			attached_to_name=USER,
		)
		frappe.set_user(USER)
		mine = picture_file(self, width=52, height=50, colour=(1, 2, 3), is_private=1)
		frappe.set_user("Administrator")
		for private in (own, mine):
			self.assertIsNone(signature_photos.usable_path(private, "User", USER), private)
		# A public picture of their User record is taken
		public = self.face(width=53, height=50, colour=(1, 2, 3))
		self.assertTrue(signature_photos.usable_path(public, "User", USER))
		self.assertTrue(signature_photos.refresh(USER))
		self.assertEqual(len(self.copies()), 1)
		# A private picture of their Employee record, attached to that record, and to no other
		employee = f"{PREFIX}-employee"
		hr = picture_file(
			self,
			width=54,
			height=50,
			colour=(1, 2, 3),
			is_private=1,
			attached_to_doctype="Employee",
			attached_to_name=employee,
		)
		self.assertTrue(signature_photos.usable_path(hr, "Employee", employee))
		self.assertIsNone(signature_photos.usable_path(hr, "Employee", f"{employee}-other"))
		self.assertIsNone(signature_photos.usable_path(hr, "User", USER))
		self.assertIsNone(signature_photos.usable_path(theirs, "Employee", employee))
		# Nothing is fetched from the web, and nothing out of the files, written as is or encoded
		for elsewhere in (
			"https://cdn.example.com/me.jpg",
			"/private/files/../../site_config.json",
			"/files/%2e%2e/%2e%2e/site_config.json",
			"",
		):
			self.assertIsNone(signature_photos.usable_path(elsewhere, "Employee", employee), elsewhere)

	def test_a_shared_mailbox_never_carries_the_writer_s_photo(self):
		self.face(width=60, height=60, colour=(5, 5, 5))
		self.choose(photo_allowed=1)
		self.make_template("team", layout="Photo left")
		photo = signatures.person_of(USER).photo
		self.assertTrue(photo)
		shared = {
			"email": "team@webmail.test",
			"sender_name": "The Team",
			"default_signature": None,
			"user": OTHER,
		}
		frappe.set_user(USER)
		self.assertNotIn(photo, signature_for(USER, shared)["html"])
		self.assertIn(photo, signature_for(USER)["html"], "under their own mailbox: their photo")

	def test_my_choices_say_what_the_template_lets_the_person_choose(self):
		frappe.set_user(USER)
		self.assertEqual(
			signatures.my_choices(),
			{
				"template": False,
				"photo": False,
				"mobile": False,
				"photo_allowed": 0,
				"hide_mobile": 0,
				"photo_url": "",
				"photo_state": "off",
			},
		)
		frappe.set_user("Administrator")
		rule = self.make_template("photos", layout="Photo left")

		def offered():
			frappe.set_user(USER)
			found = signatures.my_choices()
			frappe.set_user("Administrator")
			return {item: found[item] for item in ("template", "photo", "mobile")}

		self.assertEqual(offered(), {"template": True, "photo": True, "mobile": False})
		frappe.db.set_value("Email Signature Template", rule.name, {"show_mobile": 1, "show_photo": 0})
		self.assertEqual(offered(), {"template": True, "photo": False, "mobile": True})
		frappe.db.set_value("Email Signature Template", rule.name, {"show_photo": 1, "layout": "Logo left"})
		self.assertEqual(offered()["photo"], False, "a layout with no place for a photo")

	def test_a_person_who_said_yes_can_always_take_it_back(self):
		"""Without a template that shows photos any more (it was changed, or removed), a person who said yes still sees the
		switch, to take their photo back; and the same for a mobile they hide."""
		self.face(width=75, height=75, colour=(40, 90, 40))
		self.choose(photo_allowed=1, hide_mobile=1)
		frappe.set_user(USER)
		found = signatures.my_choices()
		self.assertEqual((found["template"], found["photo"], found["mobile"]), (False, True, True))
		self.assertEqual(
			signatures.save_my_choices(photo_allowed=0)["photo"], False, "taken back: nothing left to show"
		)
		self.assertEqual(self.copies(), [])

	def test_the_template_s_preview_shows_a_photo_only_for_a_person_who_said_yes(self):
		doc = {"doctype": "Email Signature Template", "layout": "Photo left"}
		self.face(width=77, height=77, colour=(90, 40, 90))
		self.assertNotIn("border-radius", signatures.preview(doc, USER)["html"])
		self.choose(photo_allowed=1)
		photo = frappe.db.get_value(PREFERENCE, {"user": USER}, "photo")
		self.assertIn(f'src="{photo}"', signatures.preview(doc, USER)["html"])
		self.assertNotIn(photo, signatures.preview({**doc, "show_photo": 0}, USER)["html"])

	def test_a_person_saves_their_own_choices_and_no_one_else_s(self):
		self.face(width=70, height=70, colour=(9, 9, 9))
		frappe.set_user(USER)
		given = signatures.save_my_choices(photo_allowed=1)
		self.assertEqual(
			(given["photo_allowed"], given["hide_mobile"], given["photo_state"]), (1, 0, "ready")
		)
		self.assertEqual(given["photo_url"], frappe.db.get_value(PREFERENCE, {"user": USER}, "photo"))
		self.assertTrue(given["photo_url"].startswith("/private/files/"))
		self.assertEqual(signatures.save_my_choices(hide_mobile="true")["hide_mobile"], 1)
		after = signatures.save_my_choices(photo_allowed="0")
		self.assertEqual((after["photo_allowed"], after["hide_mobile"]), (0, 1), "what is not said stays")
		self.assertEqual(self.copies(), [], "taken back: the copy is gone")
		# Another person changes their own, whatever they send: there is no way to name someone else
		frappe.set_user(OTHER)
		frappe.call(signatures.save_my_choices, user=USER, photo_allowed=1, hide_mobile=0)
		frappe.set_user("Administrator")
		self.addCleanup(frappe.delete_doc, PREFERENCE, OTHER, force=True, ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, PREFERENCE, USER, force=True, ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value(PREFERENCE, {"user": USER}, ["photo_allowed", "hide_mobile"]), (0, 1)
		)
		self.assertEqual(
			frappe.db.get_value(PREFERENCE, {"user": OTHER}, ["photo_allowed", "hide_mobile"]), (1, 0)
		)

	def test_the_choices_are_for_the_desk_s_people_only(self):
		for method in (signatures.my_choices, signatures.save_my_choices):
			frappe.is_whitelisted(method)
			self.assertNotIn(method, frappe.guest_methods)
		self.assertEqual(
			list(frappe.allowed_http_methods_for_whitelisted_func[signatures.save_my_choices]), ["POST"]
		)
		for refused in (PORTAL, "Guest"):
			frappe.set_user(refused)
			with self.assertRaises(frappe.PermissionError, msg=refused):
				signatures.my_choices()
			with self.assertRaises(frappe.PermissionError, msg=refused):
				signatures.save_my_choices(photo_allowed=1)
		frappe.set_user("Administrator")
		self.assertIsNone(frappe.db.get_value(PREFERENCE, {"user": PORTAL}))


class TestNeoMailIsHandedThePhoto(PhotoTestCase):
	"""In "Photo left", the page hands MailCraft the person's photo by its bytes, as it hands the logo of the other
	layouts, and keeps out of the HTML the pictures MailCraft has no place for (www/neomail.py)."""

	def test_the_photo_goes_by_its_bytes_in_the_logo_s_place(self):
		import base64

		from frappe_webmail.www.neomail import handed_picture, pictures_left_out

		photo = picture_file(self, width=96, height=96, colour=(40, 40, 40), kind="JPEG", is_private=1)
		logo = picture_file(self, width=40, height=10)
		chosen = render_person(template("Photo left", **banner()), person(photo=photo, logo=logo))
		handed = handed_picture(chosen, {})
		self.assertEqual(handed["layout"], "pictureLeft")
		self.assertEqual((handed["logo"]["width"], handed["logo"]["alt"]), (96, "Alex Example"))
		self.assertEqual(handed["logo"]["name"], photo.rsplit("/", 1)[1])
		data = base64.b64decode(handed["logo"]["data"])
		self.assertTrue(data.startswith(b"\xff\xd8\xff"), "the photo's own bytes, a JPEG")
		# Out of the HTML: the photo (handed) and the logo (MailCraft has no place under the words); the banner stays,
		# its words a link to where it leads
		self.assertEqual(set(pictures_left_out(chosen, handed)), {photo, logo})
		# Without a photo: nothing handed, the logo still out
		bare = render_person(template("Photo left"), person(logo=logo))
		self.assertIsNone(handed_picture(bare, {}))
		self.assertEqual(pictures_left_out(bare, None), [logo])
		# The other layouts as before: the logo, handed and out of the HTML
		left = render_person(template("Logo left"), person(photo=photo, logo=logo))
		self.assertEqual(base64.b64decode(handed_picture(left, {})["logo"]["data"])[:4], b"\x89PNG")
		self.assertEqual(pictures_left_out(left, handed_picture(left, {})), [logo])
		self.assertEqual(pictures_left_out(left, None), [], "a logo not handed stays")

	def test_the_page_hands_neomail_the_photo_and_keeps_the_banner(self):
		from frappe_webmail.www import neomail

		self.face(width=80, height=90, colour=(70, 20, 70))
		self.choose(photo_allowed=1)
		photo = frappe.db.get_value(PREFERENCE, {"user": USER}, "photo")
		self.assertTrue(photo)
		self.make_template(
			"photo",
			layout="Photo left",
			**banner(banner_image=picture_file(self, width=400, height=80, colour=(200, 120, 60))),
		)
		account = {
			"name": "signatures_box@webmail.test",
			"email": "signatures_box@webmail.test",
			"sender_name": "Sigtest",
			"default_signature": None,
			"user": USER,
		}
		frappe.set_user(USER)
		with (
			patch("frappe_webmail.webmail_api.get_accounts", return_value=[account]),
			patch("frappe_webmail.mailcraft_jmap.give_token", return_value="token"),
		):
			box = neomail.host_mailboxes()[0]
		signature = box["signature"]
		self.assertEqual(signature["layout"], "pictureLeft")
		self.assertEqual(signature["logo"]["alt"], "Sigtest Person")
		self.assertTrue(signature["logo"]["data"])
		self.assertNotIn(photo, signature["html"], "the photo goes by its bytes, not in the HTML")
		self.assertIn('href="https://example.com/fair"', signature["html"], "the banner stays, as a link")
		self.assertIn("Sigtest Person", signature["text"])
		self.assertIn("Meet us at the fair: https://example.com/fair", signature["text"])


class TestThePhotoAndTheBannerLeaveWithTheMessage(TestWebmailAPIBase):
	"""The photo and the banner are files of the instance: the message sent carries them as its own parts, as it carries
	the logo (inline_images.files_inlined). The photo is a private file: the sender's own goes, never a colleague's. The
	banner is a public one."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.sql("update `tabEmail Signature Template` set enabled = 0 where enabled = 1")
		later = patch.object(signature_photos, "refresh_later")
		later.start()
		self.addCleanup(later.stop)
		for user in (self.test_user, OTHER):
			name = frappe.db.get_value(PREFERENCE, {"user": user}, "name")
			if name:
				frappe.delete_doc(PREFERENCE, name, force=True, ignore_permissions=True)
		make_user(OTHER, "Sigtest", "Other")

	def photo_of(self, user, **picture):
		"""The person's picture, their consent, and the copy made of it: its address."""
		frappe.db.set_value("User", user, "user_image", picture_file(self, **picture))
		self.addCleanup(frappe.db.set_value, "User", user, "user_image", None)
		doc = frappe.get_doc({"doctype": PREFERENCE, "user": user, "photo_allowed": 1}).insert(
			ignore_permissions=True
		)
		self.addCleanup(frappe.delete_doc, PREFERENCE, doc.name, force=True, ignore_permissions=True)
		return frappe.db.get_value(PREFERENCE, doc.name, "photo")

	def company_template(self, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Email Signature Template",
				"template_name": f"{PREFIX}-sent-{frappe.generate_hash(length=6)}",
				"enabled": 1,
				"applies_to": "Everyone",
				"layout": "Photo left",
			}
			| values
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "Email Signature Template", doc.name, force=True, ignore_permissions=True
		)
		return doc

	@patch("frappe_webmail.api.smtplib.SMTP")
	def test_the_photo_and_the_banner_leave_as_parts_of_the_message(self, smtp_class):
		from frappe_webmail.api import send_email

		photo = self.photo_of(self.test_user, width=90, height=120, colour=(120, 60, 30))
		banner_url = picture_file(self, width=600, height=100, colour=(0, 90, 160))
		rule = self.company_template(**banner(banner_image=banner_url))
		drawn = render_person(rule, person(photo=photo))["html"]
		self.assertIn(photo, drawn)
		self.assertIn(banner_url, drawn)
		server = MagicMock()
		smtp_class.return_value = server
		frappe.set_user(self.test_user)
		with mocked_imap(imap_client()):
			send_email(
				account_name=self.test_account_email,
				to="marc@example.com",
				subject="Signature",
				html_content=f"<p>Hello</p><p>--</p>{drawn}",
			)
		sent = email.message_from_string(server.sendmail.call_args.args[2])
		html = (
			next(p for p in sent.walk() if p.get_content_type() == "text/html")
			.get_payload(decode=True)
			.decode()
		)
		parts = {
			part["Content-ID"].strip("<>"): part.get_payload(decode=True)
			for part in sent.walk()
			if part.get_content_maintype() == "image"
		}
		frappe.set_user("Administrator")
		photo_bytes = frappe.get_doc("File", {"file_url": photo}).get_content()
		banner_bytes = frappe.get_doc("File", {"file_url": banner_url}).get_content()
		self.assertIn(photo_bytes, parts.values(), "the photo's copy, as a part")
		self.assertIn(banner_bytes, parts.values(), "the banner, as a part")
		self.assertNotIn("/private/files/", html, "no private address of the instance leaves")
		for cid in parts:
			self.assertIn(f"cid:{cid}", html)
		tree = soup(html)
		# The sizes and the link as drawn
		drawn_photo = tree.find("img", alt="Alex Example")
		self.assertEqual((drawn_photo["width"], drawn_photo["height"]), ("96", "96"))
		self.assertEqual(tree.find("a", href="https://example.com/fair").find("img")["width"], "400")

	def test_only_the_sender_s_own_photo_goes_in(self):
		from frappe_webmail import inline_images

		# Pictures far apart: two copies of the same bytes are one file to Frappe, at one address
		mine = self.photo_of(self.test_user, width=91, height=120, colour=(121, 60, 30))
		theirs = self.photo_of(OTHER, width=92, height=120, colour=(20, 160, 200))
		self.assertNotEqual(mine, theirs)
		frappe.set_user(self.test_user)
		self.assertEqual(inline_images.sender_photo(), mine)
		written = inline_images.files_inlined(f'<img src="{mine}"><img src="{theirs}">')
		self.assertNotIn(mine, written)
		self.assertIn(f'src="{theirs}"', written, "a colleague's photo stays an address")
		# Their consent taken back: their photo no longer goes either (and its copy is gone)
		frappe.set_user("Administrator")
		doc = frappe.get_doc(PREFERENCE, {"user": self.test_user})
		doc.photo_allowed = 0
		doc.save(ignore_permissions=True)
		frappe.set_user(self.test_user)
		self.assertEqual(inline_images.sender_photo(), "")
		self.assertEqual(inline_images.files_inlined(f'<img src="{mine}">'), f'<img src="{mine}">')

	def test_a_portal_account_sends_no_photo_and_a_failure_none(self):
		from frappe_webmail import inline_images

		make_user(PORTAL, "Sigtest", "Portal", desk=False)
		frappe.set_user(PORTAL)
		self.assertEqual(inline_images.sender_photo(), "")
		with patch.object(signature_photos, "sent_photo", side_effect=RuntimeError("boom")):
			frappe.set_user(self.test_user)
			self.assertEqual(inline_images.sender_photo(), "", "never in the way of a message")
