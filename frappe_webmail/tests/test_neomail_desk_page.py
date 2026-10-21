# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The desk's page /app/neomail (page/neomail): off unless the site's configuration says `neomail_in_desk`, and only
where /neomail can be opened; its handover is /neomail's, for the desk's people only, and the two pages give the build
the same functions (public/js/neomail_host.js).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_neomail_desk_page
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail.frappe_webmail.page.neomail import neomail as desk
from frappe_webmail.www import neomail

PORTAL = "webmail_neomail_desk_portal@example.com"
STAFF = "webmail_neomail_desk_staff@example.com"
NOBOX = "webmail_neomail_desk_nobox@example.com"
MAILBOX = "webmail_neomail_desk_box@webmail.test"
HANDOVER = "/api/method/frappe_webmail.frappe_webmail.page.neomail.neomail.hand_over"
SHARED_SCRIPT = ("frappe_webmail", "public", "js", "neomail_host.js")
# What the shared script defines, found in each page that includes it
DEFINED = "window.neomailHost = (function () {"


def _make_user(email, desk_user):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	if desk_user:
		# A desk role makes the account a System User.
		user.append("roles", {"role": "Blogger"})
	else:
		user.user_type = "Website User"
	user.insert(ignore_permissions=True)


def _page_folder():
	return frappe.get_app_path("frappe_webmail", "frappe_webmail", "page", "neomail")


class TestNeoMailDeskPage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_make_user(PORTAL, desk_user=False)
		_make_user(STAFF, desk_user=True)
		_make_user(NOBOX, desk_user=True)
		if not frappe.db.exists("Webmail Account", MAILBOX):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": MAILBOX,
					"user": STAFF,
					"sender_name": "Desk Box",
					"auth_type": "Password",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		# The page's row as a migrate makes it from its file, on a site not migrated since the page came (rolled back
		# with the class's other records).
		if not frappe.db.exists("Page", desk.PAGE):
			from frappe.modules.import_file import import_file_by_path

			import_file_by_path(os.path.join(_page_folder(), "neomail.json"), force=True)

	def setUp(self):
		# NeoMail on, its build installed, the page offered, and the page's own request: the session's CSRF token in
		# its header and no Authorization (a test changes what `self.sent` names).
		self.sent = {}
		for started in (
			patch.dict(frappe.local.conf, {"neomail_disabled": 0, desk.FLAG: 1}),
			patch.object(neomail, "build_installed", return_value=True),
			patch("frappe.get_request_header", side_effect=self._header),
		):
			started.start()
			self.addCleanup(started.stop)

	def _header(self, key, default=None):
		if key in self.sent:
			return self.sent[key]
		if key == "X-Frappe-CSRF-Token":
			return frappe.sessions.get_csrf_token()
		return default

	def tearDown(self):
		frappe.set_user("Administrator")

	def _www_context(self, **form):
		context = frappe._dict()
		with patch.object(frappe.local, "form_dict", frappe._dict(form)):
			neomail.get_context(context)
		return context

	# Where the page is offered ------------------------------------------------------------------------------------

	def test_the_page_is_off_unless_the_site_says_so(self):
		frappe.set_user(STAFF)
		with patch.dict(frappe.local.conf):
			frappe.local.conf.pop(desk.FLAG, None)
			self.assertFalse(desk.in_desk(), "off by default")
			with self.assertRaises(frappe.PageDoesNotExistError):
				desk.hand_over()
		with patch.dict(frappe.local.conf, {desk.FLAG: 0}), self.assertRaises(frappe.PageDoesNotExistError):
			desk.hand_over()
		self.assertTrue(desk.in_desk())
		with patch.dict(frappe.local.conf, {"neomail_disabled": 1}):
			self.assertFalse(desk.in_desk(), "NeoMail switched off")
		with patch.object(neomail, "build_installed", return_value=False):
			self.assertFalse(desk.in_desk(), "no build to frame")
			with self.assertRaises(frappe.PageDoesNotExistError):
				desk.hand_over()

	def test_the_desk_lists_the_page_only_where_it_is_offered(self):
		def boot():
			return frappe._dict(page_info={desk.PAGE: {"title": "NeoMail"}, "webmail": {"title": "Webmail"}})

		listed = boot()
		desk.extend_bootinfo(listed)
		self.assertIn(desk.PAGE, listed.page_info)
		with patch.dict(frappe.local.conf, {desk.FLAG: 0}):
			hidden = boot()
			desk.extend_bootinfo(hidden)
			# A boot without pages (a visitor's) is left as it is
			desk.extend_bootinfo(frappe._dict())
		self.assertNotIn(desk.PAGE, hidden.page_info)
		self.assertIn("webmail", hidden.page_info)

	def test_the_flag_is_named_in_the_hooks(self):
		self.assertIn(
			"frappe_webmail.frappe_webmail.page.neomail.neomail.extend_bootinfo",
			frappe.get_hooks("extend_bootinfo", app_name="frappe_webmail"),
		)
		self.assertEqual(desk.FLAG, "neomail_in_desk")

	# Who reaches it -----------------------------------------------------------------------------------------------

	def test_a_desk_person_gets_their_mailboxes_as_neomail_hands_them(self):
		frappe.set_user(STAFF)
		given = desk.hand_over()
		context = self._www_context()
		self.assertFalse(given["no_mailbox"])
		self.assertEqual(given["build_url"], context.build_url, "the build /neomail frames")
		www = json.loads(context.host_json)
		self.assertEqual(set(given["host"]), {*www, "chrome"}, "the fields /neomail hands over, and one more")
		self.assertEqual(given["host"]["chrome"], "menu", "the desk's menu draws NeoMail's navigation")
		self.assertNotIn("chrome", www, "/neomail has no menu: NeoMail keeps its own navigation there")
		self.assertEqual(given["host"]["product"], "NeoMail")
		self.assertEqual(given["host"]["signatures"], frappe.utils.get_url("/app/webmail?signatures=1"))
		self.assertEqual(given["host"]["language"], www["language"])
		box = next(a for a in given["host"]["accounts"] if a["email"] == MAILBOX)
		self.assertEqual(box["name"], "Desk Box")
		self.assertEqual(box["scheme"], "bearer")
		self.assertTrue(
			box["session"].endswith("mailcraft_jmap.session?account=" + MAILBOX.replace("@", "%40"))
		)
		# Each answer gives its own tokens; everything else is the same as /neomail's
		self.assertEqual(
			[{k: v for k, v in a.items() if k != "secret"} for a in given["host"]["accounts"]],
			[{k: v for k, v in a.items() if k != "secret"} for a in www["accounts"]],
		)
		kept = frappe.cache().get_value(jmap._token_key(box["secret"]))
		self.assertEqual(kept.get("user"), STAFF)
		self.assertNotIn("oauth", kept, "bound to the desk session that asked, as /neomail's tokens are")
		self.assertIn("sid", kept)

	def test_a_portal_account_and_a_visitor_are_refused(self):
		for user in (PORTAL, "Guest"):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError, msg=user):
				desk.hand_over()
		self.assertIn(desk.hand_over, frappe.whitelisted)
		self.assertNotIn(desk.hand_over, frappe.guest_methods)
		self.assertEqual(list(frappe.allowed_http_methods_for_whitelisted_func[desk.hand_over]), ["POST"])

	def test_a_request_with_any_authorization_gets_nothing(self):
		"""Its tokens are bound to the desk session: a request signed in otherwise (a bearer token, an API key, a
		password) is not the page's. Neodesk, which signs in with its OAuth token, asks mailcraft_jmap.hand_over."""
		frappe.set_user(STAFF)
		for authorization in ("Bearer something", "token api-key:api-secret", "Basic dXNlcjpwYXNz"):
			self.sent = {"Authorization": authorization}
			with self.assertRaises(frappe.PermissionError, msg=authorization):
				desk.hand_over()

	def test_the_session_s_csrf_token_is_required(self):
		"""Whatever the site's CSRF settings: this fork's own check refuses nothing unless the site sets
		`neoffice_csrf_enforce` (maintenance#310). A refusal is Frappe's CSRFTokenError, which the page reads as a
		session to sign in again."""
		frappe.set_user(STAFF)
		for sent, why in ((None, "no token"), ("", "an empty one"), ("not-the-session-s", "another one")):
			self.sent = {"X-Frappe-CSRF-Token": sent}
			with self.assertRaises(frappe.CSRFTokenError, msg=why):
				desk.hand_over()
		with patch.dict(frappe.local.conf, {"ignore_csrf": 1, "neoffice_csrf_enforce": 0}):
			self.sent = {"X-Frappe-CSRF-Token": None}
			with self.assertRaises(frappe.CSRFTokenError, msg="whatever the site's settings"):
				desk.hand_over()
		self.sent = {}
		self.assertFalse(desk.hand_over()["no_mailbox"], "the session's own token: answered")

	def test_the_page_is_for_the_desk_s_people(self):
		from frappe.desk.desk_page import get

		with open(os.path.join(_page_folder(), "neomail.json")) as handle:
			row = json.load(handle)
		self.assertEqual((row["name"], row["module"], row["standard"]), ("neomail", "Frappe Webmail", "Yes"))
		self.assertEqual([r["role"] for r in row["roles"]], ["Desk User"])
		frappe.set_user(STAFF)
		self.assertIn(
			DEFINED, get(desk.PAGE)["script"], "the shared functions, served in place of their line"
		)
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			get(desk.PAGE)

	def test_the_sample_and_the_trial_build_are_asked_as_on_neomail(self):
		frappe.set_user(NOBOX)
		self.assertTrue(desk.hand_over()["no_mailbox"], "no mailbox: the page says so, and frames nothing")
		with patch.object(
			neomail,
			"build_installed",
			side_effect=lambda folder="mailcraft": True,
		):
			given = desk.hand_over(sample="1", build="ucs")
			context = self._www_context(sample="", build="ucs")
		self.assertFalse(given["no_mailbox"])
		self.assertEqual(given["host"]["accounts"], [])
		self.assertTrue(given["build_url"].startswith(neomail.TRIAL_BUILD + "?sample"), given["build_url"])
		self.assertEqual(given["build_url"], context.build_url)
		self.assertTrue(
			desk.hand_over(sample="0", build="../mailcraft")["build_url"].startswith(neomail.BUILD)
		)

	# What it holds --------------------------------------------------------------------------------------------------

	def test_no_cache_keeps_the_handover(self):
		for path in (HANDOVER, HANDOVER.replace("/api/method/", "/api/v2/method/")):
			response = SimpleNamespace(headers={})
			jmap.no_store(response=response, request=SimpleNamespace(path=path))
			self.assertEqual(response.headers["Cache-Control"], "no-store", path)
		# The former way of calling a method: its name in the form's `cmd`, whatever the address
		response = SimpleNamespace(headers={})
		with patch.object(frappe.local, "form_dict", frappe._dict(cmd=HANDOVER.rsplit("/", 1)[1])):
			jmap.no_store(response=response, request=SimpleNamespace(path="/"))
		self.assertEqual(response.headers.get("Cache-Control"), "no-store")

	def test_both_pages_give_the_build_the_same_functions(self):
		"""/neomail and the desk's page include one script where they are rendered: Jinja's include for the first,
		Frappe's render_include for the second, which leaves the include's line as a comment before the file."""
		with open(frappe.get_app_path(*SHARED_SCRIPT)) as handle:
			shared = handle.read()
		for delimiter in ("{{", "{%", "{#"):
			self.assertNotIn(delimiter, shared, "the script is included by Jinja")
		self.assertTrue(shared.startswith("//"), "its first line ends the desk script's include comment")
		frappe.set_user(STAFF)
		context = self._www_context()
		html = frappe.render_template("frappe_webmail/www/neomail.html", context)
		self.assertIn(DEFINED, html)
		self.assertIn("window.neomailHost.install(window, " + context.host_json, html)
		from frappe.model.utils import render_include

		with open(os.path.join(_page_folder(), "neomail.js")) as handle:
			script = render_include(handle.read())
		self.assertIn("// " + shared.split("\n", 1)[0], script)
		self.assertIn(DEFINED, script)
		self.assertNotIn("{% include", script)
