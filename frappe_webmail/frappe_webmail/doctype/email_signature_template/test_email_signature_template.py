# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Email Signature Template: what a manager may save. How a template is written and which one applies are tested in
frappe_webmail/tests/test_signatures.py.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.frappe_webmail.doctype.email_signature_template.test_email_signature_template
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from frappe_webmail import signatures

PREFIX = "zz-signature-test"
# Roles that ordinary people, portal users or visitors hold: never one that reads or writes the templates
BROAD_ROLES = {"All", "Guest", "Desk User", "Website User", "Employee", "Employee Self Service"}
# The test runner makes test records for every DocType a template links to: a site without ERPNext (the CI's) has neither
# of these, and the tests that need them skip there.
test_ignore = ["Company", "Department"]


class TestEmailSignatureTemplate(FrappeTestCase):
	def make(self, **values):
		"""A template as a manager's form would send it, not yet saved."""
		return frappe.get_doc(
			{
				"doctype": "Email Signature Template",
				"template_name": f"{PREFIX}-{frappe.generate_hash(length=8)}",
				"applies_to": "Everyone",
				"layout": "Text only",
			}
			| values
		)

	def saved(self, **values):
		doc = self.make(**values).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "Email Signature Template", doc.name, force=True, ignore_permissions=True
		)
		return doc

	def test_a_new_template_has_the_defaults_of_the_form(self):
		doc = self.saved()
		self.assertEqual(doc.enabled, 1)
		self.assertEqual((doc.font, doc.font_size, doc.logo_width), ("Arial", 13, 120))
		self.assertEqual(doc.accent_color, signatures.DEFAULT_ACCENT)
		self.assertEqual(doc.allow_personal, 0, "people do not keep their own signature unless it is said")
		self.assertEqual(
			{name: doc.get(name) for name in signatures.SWITCHES},
			signatures.SWITCHES,
			"what the form shows is what the renderer takes when nothing is said",
		)

	def test_the_choices_of_the_form_are_the_ones_the_renderer_knows(self):
		meta = frappe.get_meta("Email Signature Template")
		self.assertEqual(meta.get_field("layout").options.split("\n"), list(signatures.LAYOUTS))
		self.assertEqual(meta.get_field("font").options.split("\n"), list(signatures.FONTS))
		self.assertEqual(
			frappe.get_meta("Email Signature Social Link").get_field("network").options.split("\n"),
			list(signatures.NETWORKS),
		)
		self.assertEqual(set(meta.get_field("applies_to").options.split("\n")), set(signatures.RANK))
		self.assertEqual(meta.get_field("social_links").options, "Email Signature Social Link")
		self.assertEqual(meta.get_field("company").options, "Company")
		self.assertEqual(meta.get_field("department").options, "Department")
		self.assertEqual(meta.get_field("preview_user").options, "User")
		self.assertFalse(meta.get_field("preview_user").reqd)
		self.assertEqual(meta.get_field("accent_color").fieldtype, "Color")
		self.assertEqual(meta.get_field("disclaimer").fieldtype, "Small Text")
		self.assertEqual(meta.get_field("preview_html").fieldtype, "HTML")

	def test_the_accent_colour_is_written_rrggbb(self):
		self.assertEqual(self.saved(accent_color="#AA3300").accent_color, "#aa3300", "kept in lower case")
		self.assertEqual(
			self.saved(accent_color="").accent_color, signatures.DEFAULT_ACCENT, "none: the default"
		)
		for bad in ("red", "#fff", "#12345g", "#1234567", "aa3300", "#aa3300;position:fixed", "rgb(1,2,3)"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				self.make(accent_color=bad).insert(ignore_permissions=True)

	def test_the_sizes_are_kept_between_their_bounds(self):
		for field, low, high in (("font_size", 11, 16), ("logo_width", 60, 240)):
			self.assertEqual(self.saved(**{field: low}).get(field), low)
			self.assertEqual(self.saved(**{field: high}).get(field), high)
			for out in (low - 1, high + 1, -5):
				with self.assertRaises(frappe.ValidationError, msg=f"{field}: {out}"):
					self.make(**{field: out}).insert(ignore_permissions=True)
		self.assertEqual(self.saved(font_size=0, logo_width=0).font_size, 13, "left empty: the default")

	def test_a_template_for_a_company_or_a_department_names_it(self):
		company = frappe.db.get_value("Company", {}, "name")
		department = frappe.db.get_value("Department", {"is_group": 0}, "name")
		if not (company and department):
			self.skipTest("this site has no company or department")
		# Said empty: a Link called company that is left out takes the site's default company
		with self.assertRaises(frappe.ValidationError):
			self.make(applies_to="Company", company="").insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.make(applies_to="Department", department="").insert(ignore_permissions=True)
		# It names only what it applies to
		by_company = self.saved(applies_to="Company", company=company, department=department)
		self.assertEqual((by_company.company, by_company.department), (company, None))
		by_department = self.saved(applies_to="Department", company=company, department=department)
		self.assertEqual((by_department.company, by_department.department), (None, department))
		everyone = self.saved(applies_to="Everyone", company=company, department=department)
		self.assertEqual((everyone.company, everyone.department), (None, None))

	def test_a_name_is_taken_once(self):
		first = self.saved()
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make(template_name=first.template_name).insert(ignore_permissions=True)

	def test_a_social_link_is_an_https_address_of_a_known_network(self):
		doc = self.saved(
			social_links=[
				{"network": "LinkedIn", "url": " https://www.linkedin.com/company/example "},
				{"network": "YouTube", "url": "https://youtube.example.com/example"},
			]
		)
		self.assertEqual(
			[(row.network, row.url) for row in doc.social_links],
			[
				("LinkedIn", "https://www.linkedin.com/company/example"),
				("YouTube", "https://youtube.example.com/example"),
			],
		)
		for bad in (
			"http://www.linkedin.com/company/example",
			"javascript:alert(1)",
			"//www.linkedin.com/company/example",
			"www.linkedin.com/company/example",
			"https://",
			'https://example.com/"x',
		):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				self.make(social_links=[{"network": "LinkedIn", "url": bad}]).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.make(social_links=[{"network": "Myspace", "url": "https://myspace.example.com"}]).insert(
				ignore_permissions=True
			)

	def test_a_call_to_action_is_a_label_with_an_https_address(self):
		doc = self.saved(cta_label=" Book a call ", cta_url="https://example.com/book")
		self.assertEqual((doc.cta_label, doc.cta_url), ("Book a call", "https://example.com/book"))
		self.assertEqual(self.saved().cta_url, None, "optional")
		for values in (
			{"cta_label": "Book a call"},
			{"cta_url": "https://example.com/book"},
			{"cta_label": "Book a call", "cta_url": "http://example.com/book"},
			{"cta_label": "Book a call", "cta_url": "javascript:alert(1)"},
		):
			with self.assertRaises(frappe.ValidationError, msg=str(values)):
				self.make(**values).insert(ignore_permissions=True)

	def test_the_free_text_is_shown_as_it_was_written(self):
		"""Frappe's filter against markup encodes what looks like it in a saved field (kept on these fields: the desk's
		lists and reports may draw them); the signature reads it back as written, and encodes it once when it draws it."""
		meta = frappe.get_meta("Email Signature Template")
		for field in ("disclaimer", "cta_label"):
			self.assertFalse(meta.get_field(field).ignore_xss_filter, field)
		disclaimer = "Reply to <legal@example.com> & partners: <b>never</b> by e-mail."
		doc = self.saved(
			show_disclaimer=1,
			disclaimer=disclaimer,
			cta_label="Pay <now> & save",
			cta_url="https://example.com/pay",
		)
		stored = frappe.db.get_value(doc.doctype, doc.name, ["disclaimer", "cta_label"], as_dict=True)
		self.assertNotIn("<legal", stored.disclaimer, "the filter encoded what it does not keep")
		self.assertNotIn("<now>", stored.cta_label)
		nobody = frappe._dict(
			name="", job_title="", department="", phone="", mobile="", email="", company_name=""
		)
		result = signatures.render_person(frappe.get_doc("Email Signature Template", doc.name), nobody)
		html = result["html"]
		self.assertIn("Reply to &lt;legal@example.com&gt; &amp; partners: &lt;b&gt;never&lt;/b&gt;", html)
		self.assertIn("Pay &lt;now&gt; &amp; save", html)
		for twice in ("&amp;lt;", "&amp;gt;", "&amp;amp;"):
			self.assertNotIn(twice, html, "encoded once")
		self.assertIn(disclaimer, result["text"])
		self.assertIn("Pay <now> & save: https://example.com/pay", result["text"])

	def test_whom_the_preview_was_written_for_is_not_kept(self):
		"""Kept, it would link the template to that person, who could then not be deleted."""
		doc = self.saved(preview_user="Administrator")
		self.assertIsNone(doc.preview_user)
		self.assertIsNone(frappe.db.get_value(doc.doctype, doc.name, "preview_user"))

	def test_an_address_may_be_as_long_as_its_field(self):
		meta = frappe.get_meta("Email Signature Template")
		child = frappe.get_meta("Email Signature Social Link")
		for field in (meta.get_field("cta_url"), child.get_field("url")):
			self.assertEqual(cint(field.length), signatures.MAX_URL, field.fieldname)
		long = "https://example.com/" + "a" * (signatures.MAX_URL - 20)
		self.assertEqual(len(long), signatures.MAX_URL)
		doc = self.saved(cta_label="Go", cta_url=long, social_links=[{"network": "LinkedIn", "url": long}])
		self.assertEqual((doc.cta_url, doc.social_links[0].url), (long, long))
		with self.assertRaises(frappe.ValidationError):
			self.make(cta_label="Go", cta_url=long + "a").insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.make(social_links=[{"network": "LinkedIn", "url": long + "a"}]).insert(
				ignore_permissions=True
			)

	def test_only_the_system_manager_may_write_it(self):
		meta = frappe.get_meta("Email Signature Template")
		roles = {row.role for row in meta.permissions}
		self.assertIn("System Manager", roles)
		# An instance may let its own administrators' role read every DocType (one such is named Admin); never a role
		# that ordinary people, portal users or visitors hold.
		self.assertFalse(roles & BROAD_ROLES, roles)
		self.assertEqual(roles - {"System Manager", "Admin"}, set(), roles)
		# Writing it is the System Manager's alone.
		rights = {row.role: (row.create, row.write, row.delete) for row in meta.permissions}
		self.assertEqual(rights.get("System Manager"), (1, 1, 1))
		self.assertEqual({role for role, given in rights.items() if any(given)}, {"System Manager"}, rights)
