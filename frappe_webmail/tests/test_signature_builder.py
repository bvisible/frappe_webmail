# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The team's card and the signature builder (17.11.2026): the « Logo centre » layout and the contacts' icons
(signatures.py, templates/signatures/logo_centre.html), templates given to a user group or to roles (template_for), the
signature NeoMail sends as written (www/neomail.py, written_html), and the builder's methods (signature_builder.py).

The rendering tests need no site data. The others create their own records, all named with PREFIX, and remove them;
nothing is sent.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_signature_builder
"""

from unittest.mock import patch

import frappe
from frappe import _
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import signature_builder, signatures
from frappe_webmail.signatures import ICONS, render_person, template_for
from frappe_webmail.tests.test_signatures import (
	KEPT_ATTRIBUTES,
	KEPT_TAGS,
	PREFIX,
	USER,
	SignatureTestCase,
	make_user,
	person,
	soup,
	template,
)
from frappe_webmail.www.neomail import written_html

ROLE = f"{PREFIX}-role"
OTHER_ROLE = f"{PREFIX}-other-role"
GROUP = f"{PREFIX}-group"


def centre(**values):
	return template(
		"Logo centre",
		**{
			"show_mobile": 1,
			"show_disclaimer": 1,
			"disclaimer": "Confidential\nVertraulich",
			"show_contact_icons": 1,
		}
		| values,
	)


class TestTheTeamsCard(FrappeTestCase):
	"""« Logo centre »: the name on the left, the logo between two rules, the contacts on the right."""

	def test_the_name_is_left_the_logo_in_the_middle_and_the_contacts_right(self):
		result = render_person(centre(), person())
		tree = soup(result["html"])
		row = tree.find("tr")
		cells = row.find_all("td", recursive=False)
		self.assertEqual(len(cells), 3)
		self.assertIn("Alex Example", cells[0].get_text())
		self.assertEqual(cells[0].get("align"), "right")
		self.assertIsNotNone(cells[1].find("img", alt="Example Ltd"), "the logo between")
		self.assertIn("border-left", cells[1]["style"])
		self.assertIn("border-right", cells[1]["style"])
		# Number first, address last: phone, mobile, website, e-mail
		texts = [div.get_text(strip=True) for div in cells[2].find_all("div")]
		self.assertEqual(
			texts[:4], ["+41 00 000 00 00", "+41 00 000 00 01", "www.example.com/shop", "alex@example.com"]
		)
		# The small print under the three, centred
		rows = tree.table.find_all("tr", recursive=False)
		self.assertEqual(len(rows), 2)
		small = rows[-1]
		self.assertEqual(small.td.get("colspan"), "3")
		# Given a width, the small print no longer widens the card to the whole message (the logo floated, in Gmail)
		self.assertEqual(small.td.get("width"), "480")
		self.assertEqual(cells[1].get("align"), "center")
		self.assertIn("text-align:center", small.div["style"])
		self.assertIn("Vertraulich", small.get_text())

	def test_a_column_with_nothing_to_show_is_left_out_with_its_rule(self):
		tree = soup(render_person(centre(show_logo=0), person())["html"])
		cells = tree.find("tr").find_all("td", recursive=False)
		self.assertEqual(len(cells), 2, "no logo: no middle column")
		self.assertIsNone(tree.find("img", alt="Example Ltd"))
		bare = person(phone="", mobile="", email="", website="", address="")
		tree = soup(render_person(centre(show_email=0, show_website=0), bare)["html"])
		cells = tree.find("tr").find_all("td", recursive=False)
		self.assertEqual(len(cells), 2, "nothing to reach: no right column")
		self.assertNotIn("border-right", cells[1]["style"], "and no rule beside nothing")

	def test_the_icons_stand_for_the_labels_and_are_web_addresses(self):
		with patch.object(frappe.utils, "get_url", side_effect=lambda path="": "https://example.org" + path):
			result = render_person(centre(), person())
		tree = soup(result["html"])
		icons = [img for img in tree.find_all("img") if img.get("width") == "14"]
		self.assertEqual(
			[img["src"] for img in icons],
			["https://example.org" + ICONS[kind] for kind in ("phone", "mobile", "website", "email")],
		)
		# The label is the picture's words (what a client shows when it blocks pictures), not a word before the value
		self.assertEqual([img["alt"] for img in icons], [_("Phone"), _("Mobile"), _("Website"), _("Email")])
		self.assertNotIn(_("Phone") + ":", tree.get_text())
		# The text keeps its labels: it has no picture
		self.assertIn(_("Phone") + ": +41 00 000 00 00", result["text"])
		self.assertIn(_("Email") + ": alex@example.com", result["text"])

	def test_without_icons_the_labels_stay_and_every_layout_may_take_icons(self):
		tree = soup(render_person(centre(show_contact_icons=0), person())["html"])
		self.assertIn(_("Phone") + ":", tree.get_text())
		self.assertFalse([img for img in tree.find_all("img") if img.get("width") == "14"])
		for layout in signatures.LAYOUTS:
			html = render_person(template(layout, show_contact_icons=1), person())["html"]
			self.assertIn(ICONS["phone"], html, layout)

	def test_it_keeps_to_what_a_message_sent_keeps(self):
		tree = soup(render_person(centre(), person())["html"])
		for element in tree.find_all(True):
			self.assertIn(element.name, KEPT_TAGS)
			kept = KEPT_ATTRIBUTES["*"] | KEPT_ATTRIBUTES.get(element.name, set())
			self.assertLessEqual(set(element.attrs), kept, element.name)
			if element.get("style"):
				self.assertNotRegex(element["style"], r"flex|grid|margin|float|position|var\(|calc\(")


class TestTheSignatureNeoMailSendsAsWritten(FrappeTestCase):
	"""written_html: the template's HTML with every picture a web address."""

	def test_public_files_become_web_addresses_and_https_ones_stay(self):
		html = '<table><tr><td><img src="/files/logo.png" alt="A"><img alt="B" src="https://cdn.example.org/b.png"><img src="/assets/frappe_webmail/images/signature/phone.png" alt="C"></td></tr></table>'
		with patch.object(frappe.utils, "get_url", side_effect=lambda path="": "https://example.org" + path):
			written = written_html(html)
		self.assertIn('src="https://example.org/files/logo.png"', written)
		self.assertIn('src="https://cdn.example.org/b.png"', written)
		self.assertIn('src="https://example.org/assets/frappe_webmail/images/signature/phone.png"', written)

	def test_a_private_picture_or_one_of_nowhere_refuses_it(self):
		self.assertIsNone(
			written_html('<img src="/private/files/photo.png" alt="P">'), "a photo shows to nobody"
		)
		self.assertIsNone(written_html('<img src="http://example.org/a.png" alt="P">'), "not https")
		self.assertIsNone(written_html('<img src="data:image/png;base64,AAAA" alt="P">'))
		self.assertIsNone(written_html(""))
		self.assertIsNone(written_html(None))

	def test_one_too_heavy_for_neomail_is_refused(self):
		self.assertIsNone(written_html("<div>" + "x" * (64 * 1024) + "</div>"))


class TestTemplatesGivenToGroupsAndRoles(SignatureTestCase):
	"""template_for with templates given to a user group or to roles: the department, then the group, then the roles, then
	the company, then everyone."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")
		for role in (ROLE, OTHER_ROLE):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
					ignore_permissions=True
				)
		frappe.get_doc("User", USER).add_roles(ROLE)
		if not frappe.db.exists("User Group", GROUP):
			frappe.get_doc(
				{"doctype": "User Group", "name": GROUP, "user_group_members": [{"user": USER}]}
			).insert(ignore_permissions=True)
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.department = frappe.db.get_value("Department", {"is_group": 0}, "name")

	def setUp(self):
		self.quiet_the_site()

	def asked(self, department=None, company=None):
		employee = frappe._dict(department=department, company=company)
		with (
			patch.object(signatures, "_employee_of", return_value=employee),
			patch.object(signatures, "_default_company", return_value=None),
		):
			found = template_for(USER)
		return found.name if found else None

	def roles_template(self, label, *roles):
		return self.make_template(label, applies_to="Role", roles=[{"role": role} for role in roles])

	def test_a_template_given_to_a_role_reaches_who_has_it_and_no_one_else(self):
		mine = self.roles_template("mine", OTHER_ROLE, ROLE)
		self.assertEqual(self.asked(), mine.name)
		frappe.db.set_value("Email Signature Template", mine.name, "enabled", 0)
		self.roles_template("theirs", OTHER_ROLE)
		self.assertIsNone(self.asked(), "a role the person has not")

	def test_a_template_given_to_a_user_group_reaches_its_members(self):
		group = self.make_template("group", applies_to="User Group", user_group=GROUP)
		self.assertEqual(self.asked(), group.name)
		frappe.db.set_value("Email Signature Template", group.name, "user_group", None)
		self.assertIsNone(self.asked(), "a template naming no group reaches nobody")

	def test_the_department_then_the_group_then_the_roles_then_the_company_then_everyone(self):
		if not (self.company and self.department):
			self.skipTest("this site has no company or department")
		everyone = self.make_template("everyone")
		company = self.make_template("company", applies_to="Company", company=self.company)
		roles = self.roles_template("roles", ROLE)
		group = self.make_template("group", applies_to="User Group", user_group=GROUP)
		department = self.make_template("department", applies_to="Department", department=self.department)
		order = [department, group, roles, company, everyone]
		for doc in order:
			self.assertEqual(self.asked(self.department, self.company), doc.name)
			frappe.db.set_value("Email Signature Template", doc.name, "enabled", 0)
		self.assertIsNone(self.asked(self.department, self.company))

	def test_a_template_for_roles_names_some_each_once_and_forgets_the_rest(self):
		with self.assertRaises(frappe.ValidationError):
			self.roles_template("none")
		doc = self.make_template(
			"twice",
			applies_to="Role",
			roles=[{"role": ROLE}, {"role": ROLE}, {"role": OTHER_ROLE}],
			company=self.company,
			user_group=GROUP,
		)
		self.assertEqual([row.role for row in doc.roles], [ROLE, OTHER_ROLE])
		self.assertFalse(doc.company or doc.user_group, "what another kind would name is cleared")
		doc.applies_to = "Everyone"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.roles, [], "given to everyone: no roles kept")
		with self.assertRaises(frappe.ValidationError):
			self.make_template("no-group", applies_to="User Group")


class TestTheBuilder(SignatureTestCase):
	"""signature_builder: who may make the company's signatures, whom a model reaches, and its saving."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(USER, "Sigtest", "Person")
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		frappe.get_doc("User", USER).add_roles(ROLE)

	def setUp(self):
		self.quiet_the_site()
		self.addCleanup(frappe.set_user, "Administrator")

	def model(self, **values):
		return {
			"template_name": f"{PREFIX}-built-{frappe.generate_hash(length=6)}",
			"enabled": 1,
			"applies_to": "Role",
			"roles": [ROLE],
			"layout": "Logo centre",
			"show_contact_icons": 1,
		} | values

	def test_a_person_without_the_right_sees_only_their_own(self):
		frappe.set_user(USER)
		state = signature_builder.state()
		self.assertFalse(state["can_edit"])
		self.assertNotIn("templates", state)
		self.assertNotIn("people", state)
		for call in (
			lambda: signature_builder.reach(self.model()),
			lambda: signature_builder.save(self.model()),
			lambda: signature_builder.preview(self.model(), user="Administrator"),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_whom_a_model_reaches_before_it_is_saved(self):
		answer = signature_builder.reach(self.model())
		mine = next(p for p in answer["people"] if p["user"] == USER)
		self.assertTrue(mine["applies"] and mine["sends"])
		self.assertIsNone(mine["today"], "no template is saved for them yet")
		self.assertGreaterEqual(answer["count"], 1)
		off = signature_builder.reach(self.model(enabled=0))
		mine = next(p for p in off["people"] if p["user"] == USER)
		self.assertTrue(mine["applies"])
		self.assertFalse(mine["sends"], "a model not in use is sent by nobody")

	def test_a_more_precise_model_takes_its_people(self):
		group = f"{PREFIX}-builder-group"
		if not frappe.db.exists("User Group", group):
			frappe.get_doc(
				{"doctype": "User Group", "name": group, "user_group_members": [{"user": USER}]}
			).insert(ignore_permissions=True)
		precise = self.make_template("precise", applies_to="User Group", user_group=group)
		mine = next(p for p in signature_builder.reach(self.model())["people"] if p["user"] == USER)
		self.assertTrue(mine["applies"])
		self.assertFalse(mine["sends"])
		self.assertEqual(mine["today"], precise.name)

	def test_saving_makes_the_model_and_then_changes_it(self):
		saved = signature_builder.save(self.model())
		self.addCleanup(
			frappe.delete_doc, "Email Signature Template", saved["name"], force=True, ignore_permissions=True
		)
		self.assertEqual(saved["roles"], [ROLE])
		self.assertEqual(template_for(USER).name, saved["name"])
		saved["layout"] = "Logo above"
		saved["roles"] = []
		with self.assertRaises(frappe.ValidationError):
			signature_builder.save(saved)
		saved["applies_to"] = "Everyone"
		again = signature_builder.save(saved)
		self.assertEqual((again["name"], again["layout"], again["roles"]), (saved["name"], "Logo above", []))

	def test_the_preview_is_written_for_the_person_asked(self):
		html = signature_builder.preview(self.model(), user=USER)["html"]
		self.assertIn("Sigtest Person", html)
		frappe.set_user(USER)
		self.assertIn(
			"Sigtest Person", signature_builder.preview(self.model())["html"], "one's own, without the right"
		)

	def test_the_company_admin_is_given_the_templates_once(self):
		if not frappe.db.exists("Role", signature_builder.COMPANY_ADMIN):
			self.skipTest("no Admin role on this site")
		signature_builder.let_the_company_admin_write()
		rule = {"parent": "Email Signature Template", "role": signature_builder.COMPANY_ADMIN, "permlevel": 0}
		rights = frappe.db.get_value(
			"Custom DocPerm", rule, list(signature_builder.ADMIN_RIGHTS), as_dict=True
		)
		self.assertTrue(all(rights.values()), rights)
		signature_builder.let_the_company_admin_write()
		self.assertEqual(frappe.db.count("Custom DocPerm", rule), 1, "idempotent")
		self.assertTrue(
			frappe.db.exists(
				"Custom DocPerm", {"parent": "Email Signature Template", "role": "System Manager", "write": 1}
			),
			"System Manager keeps its own",
		)


class TestWhereTheBuilderOpens(FrappeTestCase):
	"""The builder's address: NeoMail's File > Signatures leads to it, and the webmail's address leads to NeoMail's page
	with it where NeoMail is the desk's mail."""

	def test_neomail_s_signatures_lead_to_the_builder(self):
		from frappe_webmail.www import neomail

		self.assertEqual(neomail.signatures_url(), frappe.utils.get_url("/app/webmail?signature_builder=1"))

	def test_the_webmail_s_address_of_the_builder_leads_to_neomail_s_page(self):
		from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

		self.assertEqual(desk.neomail_address({"signature_builder": "1"}), "/app/neomail?signature_builder=1")
		self.assertEqual(
			desk.neomail_address({"signature_builder": "1", "compose": "1"}),
			"/app/neomail?signature_builder=1",
		)
		self.assertIsNone(
			desk.neomail_address({"signatures": "1", "signature_builder": "1"}), "one's own stay"
		)
