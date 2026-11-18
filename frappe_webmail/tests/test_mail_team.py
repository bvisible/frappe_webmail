# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The team's mail (mail_team.py, 18.11.2026): who sees the team's mailboxes and adds one, what « Add a mailbox » finds
from a domain, what « My mail » shows each person, the user menu's entry, and the builder's « signature of each »
(signature_builder.each).

Administrator only sets the scene (the accounts, the mailboxes); every act is played by a real role: the company's
administrator (client_admin), a desk person (sales_user), a portal account and a visitor. The DNS is never asked: the
MX records are given (mx_hosts patched). Everything made is named with PREFIX or DOMAIN and removed; nothing is sent.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mail_team
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mail_team, signature_builder
from frappe_webmail.frappe_webmail.page.neomail.neomail import _my_mail_in_the_user_menu

PREFIX = "mlt-test"
DOMAIN = "mlt-test.example"
OWNER = f"{PREFIX}-owner@yopmail.com"
READER = f"{PREFIX}-reader@yopmail.com"
MANAGER = f"{PREFIX}-manager@yopmail.com"
PORTAL = f"{PREFIX}-portal@yopmail.com"
SECRET = "mlt-Secret-42!"
EMAILARRAY = ["mx.emailarray.com", "mx2.emailarray.com"]
INFOMANIAK = ["mta-gw.infomaniak.ch"]


def _drop_boxes():
	for name in frappe.get_all("Webmail Account", filters={"email": ["like", f"%@{DOMAIN}"]}, pluck="name"):
		frappe.delete_doc("Webmail Account", name, force=True, ignore_permissions=True)


def _box(email, owner, readers=(), oauth=None):
	doc = frappe.new_doc("Webmail Account")
	doc.update({"email": email, "user": owner, "enabled": 1})
	if oauth:
		doc.update({"auth_type": "OAuth2", "oauth_provider": oauth})
	else:
		doc.update(
			{
				"auth_type": "Password",
				"imap_password": SECRET,
				"imap_host": "imap.mlt-test.example",
				"imap_port": 993,
				"imap_ssl": 1,
				"smtp_host": "smtp.mlt-test.example",
				"smtp_port": 465,
				"smtp_ssl": 1,
			}
		)
	for reader in readers:
		doc.append("allowed_users", {"user": reader})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


class TestMailTeam(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# A site without Neoffice's theme has no « Admin » role: the company's administrator's, made for the scene, with
		# its right on the templates; what the scene adds is taken away after (test_signatures counts who holds it)
		template = signature_builder.TEMPLATE
		cls.made_role = not frappe.db.exists("Role", "Admin")
		cls.custom_rules = frappe.db.count("Custom DocPerm", {"parent": template})
		cls.admin_rule = frappe.db.exists("Custom DocPerm", {"parent": template, "role": "Admin"})
		if cls.made_role:
			frappe.get_doc({"doctype": "Role", "role_name": "Admin", "desk_access": 1}).insert(
				ignore_permissions=True
			)
		signature_builder.let_the_company_admin_write()
		for email in (OWNER, READER):
			with as_role("sales_user", email=email):
				pass
		with as_role("client_admin", email=MANAGER):
			pass
		if not frappe.db.exists("User", PORTAL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": PORTAL,
					"first_name": "Mlt Portal",
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		_drop_boxes()
		self.addCleanup(_drop_boxes)
		self.addCleanup(frappe.set_user, "Administrator")
		# The site signs in at Google and Microsoft (webmail_oauth_* of site_config), unless a test says otherwise
		oauth = patch.object(mail_team, "_oauth_configured", return_value=True)
		oauth.start()
		self.addCleanup(oauth.stop)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_drop_boxes()
		for email in (OWNER, READER, MANAGER, PORTAL):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		template = signature_builder.TEMPLATE
		if not cls.custom_rules:
			# Frappe copied the standard rules to add the scene's: the template goes back to them alone
			frappe.db.delete("Custom DocPerm", {"parent": template})
		elif not cls.admin_rule:
			frappe.db.delete("Custom DocPerm", {"parent": template, "role": "Admin"})
		if cls.made_role:
			frappe.delete_doc("Role", "Admin", force=True, ignore_permissions=True)
		frappe.clear_cache(doctype=template)
		frappe.db.commit()
		super().tearDownClass()

	# ---- who reaches it -----------------------------------------------------------------------------------------------

	def test_a_visitor_and_a_portal_account_reach_none_of_it(self):
		calls = (
			("team", lambda: mail_team.team()),
			("detect", lambda: mail_team.detect(f"x@{DOMAIN}")),
			("add", lambda: mail_team.add(OWNER, f"x@{DOMAIN}", "google")),
			(
				"try_connection",
				lambda: mail_team.try_connection(f"x@{DOMAIN}", "other", "pw", "imap.x", 993, "smtp.x", 465),
			),
			("mine", lambda: mail_team.mine()),
		)
		for who in ("Guest", PORTAL):
			for name, call in calls:
				with self.subTest(who=who, call=name):
					with as_role(who):
						self.assertRaises(frappe.PermissionError, call)
		self.assertFalse(frappe.db.exists("Webmail Account", f"x@{DOMAIN}"))

	def test_a_desk_person_who_manages_nothing_sees_only_their_own(self):
		_box(f"own@{DOMAIN}", OWNER)
		_box(f"other@{DOMAIN}", READER)
		with as_role("sales_user", email=OWNER):
			self.assertRaises(frappe.PermissionError, mail_team.team)
			self.assertRaises(frappe.PermissionError, mail_team.detect, f"x@{DOMAIN}")
			self.assertRaises(frappe.PermissionError, mail_team.add, OWNER, f"x@{DOMAIN}", "google")
			mine = mail_team.mine()
		self.assertEqual([box["email"] for box in mine["boxes"]], [f"own@{DOMAIN}"])
		self.assertFalse(mine["may_manage"])

	# ---- the team's list ---------------------------------------------------------------------------------------------

	def test_the_administrator_sees_every_mailbox_by_person_and_no_secret(self):
		_box(f"lea@{DOMAIN}", OWNER)
		_box(f"info@{DOMAIN}", OWNER, readers=[READER])
		_box(f"google@{DOMAIN}", READER, oauth="Gmail")
		with as_role("client_admin", email=MANAGER):
			team = mail_team.team()
		people = {person["user"]: person for person in team["people"]}
		self.assertEqual([box["email"] for box in people[OWNER]["boxes"]], [f"lea@{DOMAIN}"])
		self.assertEqual(people[OWNER]["reads"], [f"info@{DOMAIN}"])
		self.assertEqual(people[READER]["reads"], [f"info@{DOMAIN}"])
		shared = [box for box in team["shared"] if box["email"].endswith(DOMAIN)]
		self.assertEqual(len(shared), 1)
		self.assertEqual(shared[0]["owner"], OWNER)
		self.assertEqual([r["user"] for r in shared[0]["readers"]], [READER])
		states = {box["email"]: box["state"]["code"] for person in team["people"] for box in person["boxes"]}
		self.assertEqual(states[f"lea@{DOMAIN}"], "ready")
		self.assertEqual(states[f"google@{DOMAIN}"], "connect")
		self.assertNotIn(SECRET, json.dumps(team, default=str))
		self.assertNotIn("imap_host", json.dumps(team, default=str))

	def test_a_mailbox_without_its_password_says_so(self):
		name = _box(f"lea@{DOMAIN}", OWNER)
		frappe.db.delete("__Auth", {"doctype": "Webmail Account", "name": name, "fieldname": "imap_password"})
		with as_role("client_admin", email=MANAGER):
			team = mail_team.team()
		box = next(b for p in team["people"] for b in p["boxes"] if b["name"] == name)
		self.assertEqual(box["state"]["code"], "password")

	# ---- where a domain receives its mail ---------------------------------------------------------------------------

	def test_the_domain_says_where_its_mail_is(self):
		cases = (
			(EMAILARRAY, "neoservice", "EmailArray"),
			(INFOMANIAK, "neoservice", "Infomaniak"),
			(["aspmx.l.google.com", "alt1.aspmx.l.google.com"], "google", ""),
			(["mlt-test-example.mail.protection.outlook.com"], "microsoft", ""),
			(["mx.elsewhere.example"], "", ""),
			([], "", ""),
		)
		for hosts, provider, preset in cases:
			with self.subTest(hosts=hosts), patch.object(mail_team, "mx_hosts", return_value=hosts):
				with as_role("client_admin", email=MANAGER):
					found = mail_team.detect(f"lea@{DOMAIN}")
				self.assertEqual((found["provider"], found["preset"]), (provider, preset))
				self.assertEqual(found["domain"], DOMAIN)

	def test_a_host_that_only_ends_like_ours_is_not_ours(self):
		with patch.object(mail_team, "mx_hosts", return_value=["mx.notemailarray.com"]):
			self.assertEqual(mail_team.provider_of_domain(DOMAIN)["provider"], "")

	# ---- adding one --------------------------------------------------------------------------------------------------

	def test_neoservices_mailbox_takes_its_servers_from_the_domain(self):
		for hosts, preset, imap in (
			(EMAILARRAY, "EmailArray", "imap.emailarray.com"),
			(INFOMANIAK, "Infomaniak", "mail.infomaniak.com"),
		):
			with self.subTest(preset=preset), patch.object(mail_team, "mx_hosts", return_value=hosts):
				_drop_boxes()
				with as_role("client_admin", email=MANAGER):
					made = mail_team.add(OWNER, f"lea@{DOMAIN}", "neoservice", password=SECRET)
				doc = frappe.get_doc("Webmail Account", made["name"])
				self.assertEqual(
					(doc.provider_preset, doc.imap_host, doc.auth_type), (preset, imap, "Password")
				)
				self.assertEqual(doc.user, OWNER)
				self.assertEqual(doc.get_password("imap_password"), SECRET)
				self.assertFalse(made["waits_to_connect"])

	def test_neoservices_mailbox_is_refused_where_the_domain_is_elsewhere(self):
		with patch.object(mail_team, "mx_hosts", return_value=["aspmx.l.google.com"]):
			with as_role("client_admin", email=MANAGER):
				self.assertRaises(
					frappe.ValidationError, mail_team.add, OWNER, f"lea@{DOMAIN}", "neoservice", SECRET
				)
		self.assertFalse(frappe.db.exists("Webmail Account", f"lea@{DOMAIN}"))

	def test_a_mailbox_is_its_owners_and_its_readers_see_it(self):
		with as_role("client_admin", email=MANAGER):
			made = mail_team.add(OWNER, f"info@{DOMAIN}", "google", readers=json.dumps([READER, OWNER]))
		doc = frappe.get_doc("Webmail Account", made["name"])
		self.assertEqual(doc.user, OWNER)
		self.assertEqual([row.user for row in doc.allowed_users], [READER])
		self.assertEqual((doc.auth_type, doc.oauth_provider), ("OAuth2", "Gmail"))
		self.assertTrue(made["waits_to_connect"])
		with as_role("sales_user", email=OWNER):
			theirs = mail_team.mine()
		box = theirs["boxes"][0]
		self.assertTrue(box["mine"] and box["may_connect"])
		self.assertEqual([r["user"] for r in box["readers"]], [READER])
		self.assertEqual(theirs["waiting"], 1)
		with as_role("sales_user", email=READER):
			read = mail_team.mine()
		self.assertEqual(
			[(b["email"], b["mine"], b["may_connect"]) for b in read["boxes"]],
			[(f"info@{DOMAIN}", False, False)],
		)
		self.assertEqual(read["waiting"], 0)

	def test_the_administrator_never_names_themselves_a_reader_of_someone_elses_mailbox(self):
		with as_role("client_admin", email=MANAGER):
			self.assertRaises(
				frappe.PermissionError, mail_team.add, OWNER, f"lea@{DOMAIN}", "google", readers=[MANAGER]
			)
			# Their own mailbox, others may read
			made = mail_team.add(MANAGER, f"admin@{DOMAIN}", "google", readers=[OWNER])
		self.assertFalse(frappe.db.exists("Webmail Account", f"lea@{DOMAIN}"))
		self.assertEqual(
			[row.user for row in frappe.get_doc("Webmail Account", made["name"]).allowed_users], [OWNER]
		)

	def test_adding_refuses_a_portal_account_as_owner_or_reader_and_a_second_box(self):
		with as_role("client_admin", email=MANAGER):
			self.assertRaises(frappe.ValidationError, mail_team.add, PORTAL, f"p@{DOMAIN}", "google")
			self.assertRaises(
				frappe.ValidationError, mail_team.add, OWNER, f"p@{DOMAIN}", "google", readers=[PORTAL]
			)
			mail_team.add(OWNER, f"p@{DOMAIN}", "google")
			self.assertRaises(frappe.ValidationError, mail_team.add, READER, f"p@{DOMAIN}", "google")
			self.assertRaises(
				frappe.ValidationError, mail_team.add, MANAGER, f"q@{DOMAIN}", "other", password=SECRET
			)
		self.assertEqual(frappe.db.get_value("Webmail Account", f"p@{DOMAIN}", "user"), OWNER)

	def test_another_providers_servers_are_tried_before_anything_is_made(self):
		with patch(
			"frappe_webmail.webmail_api.test_connection_live", return_value={"success": True}
		) as tried:
			with as_role("client_admin", email=MANAGER):
				answer = mail_team.try_connection(
					f"lea@{DOMAIN}", "other", SECRET, "imap.x.example", 993, "smtp.x.example", 587
				)
		self.assertTrue(answer["success"])
		kwargs = tried.call_args.kwargs
		self.assertEqual((kwargs["smtp_port"], kwargs["smtp_ssl"], kwargs["smtp_starttls"]), (587, 0, 1))
		self.assertFalse(frappe.db.exists("Webmail Account", f"lea@{DOMAIN}"))

	def test_another_providers_servers_are_never_set_for_someone_else(self):
		with as_role("client_admin", email=MANAGER):
			self.assertRaises(
				frappe.PermissionError,
				mail_team.add,
				OWNER,
				f"lea@{DOMAIN}",
				"other",
				password=SECRET,
				imap_host="imap.attacker.example",
				smtp_host="smtp.attacker.example",
			)
			# Their own, they may
			made = mail_team.add(
				MANAGER,
				f"admin@{DOMAIN}",
				"other",
				password=SECRET,
				imap_host="imap.own.example",
				smtp_host="smtp.own.example",
			)
		self.assertFalse(frappe.db.exists("Webmail Account", f"lea@{DOMAIN}"))
		self.assertEqual(
			frappe.db.get_value("Webmail Account", made["name"], "imap_host"), "imap.own.example"
		)

	def test_a_provider_the_site_cannot_sign_in_at_is_refused(self):
		with patch.object(mail_team, "_oauth_configured", return_value=False):
			with as_role("client_admin", email=MANAGER):
				self.assertRaises(frappe.ValidationError, mail_team.add, OWNER, f"lea@{DOMAIN}", "microsoft")
		self.assertFalse(frappe.db.exists("Webmail Account", f"lea@{DOMAIN}"))

	def test_an_address_is_one_plain_address(self):
		with as_role("client_admin", email=MANAGER):
			for email in (f"lea@{DOMAIN},other@{DOMAIN}", f"Lea <lea@{DOMAIN}>", f"lea @{DOMAIN}", "lea"):
				with self.subTest(email=email):
					self.assertRaises(frappe.ValidationError, mail_team.add, OWNER, email, "google")
			made = mail_team.add(OWNER, f"  LEA@{DOMAIN.upper()} ", "google")
		self.assertEqual(made["email"], f"lea@{DOMAIN}")

	def test_a_lookup_that_fails_is_said_as_such(self):
		with patch.object(mail_team, "mx_hosts", return_value=None):
			with as_role("client_admin", email=MANAGER):
				found = mail_team.detect(f"lea@{DOMAIN}")
				self.assertTrue(found["failed"])
				with self.assertRaises(frappe.ValidationError) as caught:
					mail_team.add(OWNER, f"lea@{DOMAIN}", "neoservice", password=SECRET)
		self.assertIn(DOMAIN, str(caught.exception))
		self.assertFalse(frappe.db.exists("Webmail Account", f"lea@{DOMAIN}"))

	def test_unreadable_readers_are_said_not_raised_with_the_password(self):
		with patch.object(mail_team, "mx_hosts", return_value=INFOMANIAK):
			with as_role("client_admin", email=MANAGER):
				self.assertRaises(
					frappe.ValidationError,
					mail_team.add,
					OWNER,
					f"lea@{DOMAIN}",
					"neoservice",
					password=SECRET,
					readers="[not json",
				)

	def test_the_owner_sees_who_added_their_mailbox(self):
		with as_role("client_admin", email=MANAGER):
			mail_team.add(OWNER, f"lea@{DOMAIN}", "google")
		with as_role("sales_user", email=OWNER):
			box = mail_team.mine()["boxes"][0]
		self.assertTrue(box["added_by"])
		self.assertNotEqual(box["added_by"], "")

	def test_administrators_own_mailboxes_are_not_the_teams(self):
		_box(f"neoservice@{DOMAIN}", "Administrator")
		with as_role("client_admin", email=MANAGER):
			team = mail_team.team()
		emails = [b["email"] for p in team["people"] for b in p["boxes"]] + [
			b["email"] for b in team["shared"]
		]
		self.assertNotIn(f"neoservice@{DOMAIN}", emails)

	def test_a_consent_comes_back_to_the_owners_own_session_only(self):
		from frappe_webmail import webmail_api

		name = _box(f"google@{DOMAIN}", OWNER, oauth="Gmail")
		frappe.cache().set_value(
			"webmail_oauth_state_mlt-test-state", {"account": name, "user": OWNER}, expires_in_sec=60
		)
		with as_role("sales_user", email=READER):
			self.assertRaises(
				frappe.PermissionError, webmail_api.oauth_callback, code="x", state="mlt-test-state"
			)
		self.assertFalse(frappe.db.get_value("Webmail Account", name, "oauth_status") == "Connected")

	# ---- the user menu -----------------------------------------------------------------------------------------------

	def test_the_user_menu_carries_my_mail_with_what_waits(self):
		_box(f"google@{DOMAIN}", OWNER, oauth="Gmail")
		_box(f"lea@{DOMAIN}", OWNER)
		with as_role("sales_user", email=OWNER):
			boot = frappe._dict()
			_my_mail_in_the_user_menu(boot)
		entry = next(item for item in boot.neo_user_menu if item["key"] == "my_mail")
		self.assertEqual(entry["badge"], 1)
		self.assertEqual(entry["call"], "frappe_webmail.mail_team.open_mine")
		with as_role(PORTAL):
			boot = frappe._dict()
			_my_mail_in_the_user_menu(boot)
		self.assertNotIn("neo_user_menu", boot)

	def test_mon_espace_says_when_ones_own_mailbox_waits_and_nothing_of_others(self):
		with as_role("sales_user", email=OWNER):
			self.assertEqual(mail_team.day_summary("all"), [])
		_box(f"google@{DOMAIN}", OWNER, oauth="Gmail")
		_box(f"lea@{DOMAIN}", OWNER)
		_box(f"other@{DOMAIN}", READER, oauth="Gmail")
		with as_role("sales_user", email=OWNER):
			rows = mail_team.day_summary("all")
		self.assertEqual(len(rows), 1)
		self.assertIn(f"google@{DOMAIN}", rows[0]["title"])
		self.assertNotIn(f"other@{DOMAIN}", json.dumps(rows))
		self.assertEqual(rows[0]["route"], "/app/neomail?my_mail=1")
		self.assertTrue(rows[0]["phrase"])
		with as_role(PORTAL):
			self.assertEqual(mail_team.day_summary("all"), [])

	# ---- the signature of each ---------------------------------------------------------------------------------------

	def test_the_signature_of_each_is_for_those_who_make_the_signatures(self):
		with as_role("sales_user", email=OWNER):
			self.assertRaises(frappe.PermissionError, signature_builder.each)
		with as_role("client_admin", email=MANAGER):
			people = {p["user"]: p for p in signature_builder.each()["people"]}
		self.assertIn(OWNER, people)
		self.assertIn(frappe._("job title"), people[OWNER]["missing"])
