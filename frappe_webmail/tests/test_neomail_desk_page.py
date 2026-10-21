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
from urllib.parse import urlencode

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
MESSAGE_KEY = "frappe_webmail.frappe_webmail.page.neomail.neomail.message_key"
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
		with patch.dict(frappe.local.conf, {"neoffice_cockpit_disable": 1}):
			self.assertNotIn(
				"chrome", desk.hand_over()["host"], "a site without the desk's menu: NeoMail keeps its own"
			)
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

		for page in (
			_page_folder(),
			frappe.get_app_path("frappe_webmail", "frappe_webmail", "page", "webmail"),
		):
			name = os.path.basename(page) + ".js"
			with open(os.path.join(page, name)) as handle:
				script = render_include(handle.read())
			self.assertIn("// " + shared.split("\n", 1)[0], script, name)
			self.assertIn(DEFINED, script, name)
			self.assertNotIn("{% include", script, name)

	# The webmail gives way to NeoMail ----------------------------------------------------------------------------

	def _loaded(self, path, **args):
		"""lead_to_neomail for a load of `path` with that query: the address it leads to, or None."""
		request = SimpleNamespace(path=path, args=args)
		with patch.object(frappe.local, "request", request, create=True):
			try:
				desk.lead_to_neomail(frappe._dict())
			except frappe.Redirect as redirect:
				self.assertEqual(redirect.http_status_code, 302)
				return frappe.local.flags.redirect_location
		return None

	def test_the_webmail_leads_to_neomail_for_the_desk_s_people_where_the_site_says_so(self):
		frappe.set_user(STAFF)
		self.assertEqual(self._loaded("/app/webmail"), "/app/neomail")
		self.assertEqual(
			self._loaded("/app/webmail", account=MAILBOX, folder="Archive", uid="31"),
			"/app/neomail?" + urlencode({"account": MAILBOX, "folder": "Archive", "uid": "31"}),
		)
		self.assertEqual(self._loaded("/app/webmail/INBOX/", compose="1"), "/app/neomail?compose=1")
		# The webmail's signatures stay the webmail's; its mailboxes' settings and other pages are not its address
		for path, args in (
			("/app/webmail", {"signatures": "1"}),
			("/app/webmail-account/new", {}),
			("/app/neomail", {}),
			("/app/home", {}),
		):
			self.assertIsNone(self._loaded(path, **args), path)
		with patch.dict(frappe.local.conf, {desk.FLAG: 0}):
			self.assertIsNone(self._loaded("/app/webmail"), "the rest of the fleet: nothing changes")
		for user in (PORTAL, "Guest"):
			frappe.set_user(user)
			self.assertIsNone(self._loaded("/app/webmail"), user)
		self.assertIn(
			"frappe_webmail.frappe_webmail.page.neomail.neomail.lead_to_neomail",
			frappe.get_hooks("update_website_context", app_name="frappe_webmail"),
		)

	def test_the_webmail_s_addresses_and_neomail_s_say_the_same(self):
		address = desk.neomail_address
		self.assertEqual(address({}), "/app/neomail")
		self.assertEqual(address({"compose": "1", "uid": "4"}), "/app/neomail?compose=1")
		self.assertEqual(
			address({"account": "a@example.org", "uid": "9", "other": "x"}),
			"/app/neomail?account=a%40example.org&uid=9",
		)
		self.assertEqual(
			address({"account": "a@example.org", "email": "E7V9ZSU5CT1g"}),
			"/app/neomail?account=a%40example.org&email=E7V9ZSU5CT1g",
		)
		self.assertIsNone(address({"signatures": "1", "uid": "4"}))

	def test_the_website_s_webmail_address_leads_the_same_way(self):
		from frappe_webmail.www import webmail

		def loaded(**args):
			request = SimpleNamespace(path="/webmail", args=args, query_string=urlencode(args).encode())
			with (
				patch.object(frappe.local, "request", request, create=True),
				self.assertRaises(frappe.Redirect),
			):
				webmail.get_context(frappe._dict())
			return frappe.local.flags.redirect_location

		frappe.set_user(STAFF)
		self.assertEqual(
			loaded(uid="5", account=MAILBOX), "/app/neomail?" + urlencode({"account": MAILBOX, "uid": "5"})
		)
		self.assertEqual(loaded(signatures="1"), "/app/webmail?signatures=1")
		with patch.dict(frappe.local.conf, {desk.FLAG: 0}):
			self.assertEqual(loaded(uid="5"), "/app/webmail?uid=5")
		frappe.set_user(PORTAL)
		with (
			patch.object(
				frappe.local,
				"request",
				SimpleNamespace(path="/webmail", args={}, query_string=b""),
				create=True,
			),
			self.assertRaises(frappe.PermissionError),
		):
			webmail.get_context(frappe._dict())
		frappe.set_user("Guest")
		self.assertEqual(loaded(), "/login?redirect-to=/app/webmail")

	def test_the_desk_tells_the_webmail_s_page_whether_to_lead_to_neomail(self):
		frappe.set_user(STAFF)
		boot = frappe._dict(page_info={desk.PAGE: {}})
		desk.extend_bootinfo(boot)
		self.assertEqual(boot.neomail_in_desk, 1)
		with patch.dict(frappe.local.conf, {desk.FLAG: 0}):
			boot = frappe._dict(page_info={desk.PAGE: {}})
			desk.extend_bootinfo(boot)
		self.assertEqual(boot.neomail_in_desk, 0)

	# A message the webmail's links name, as NeoMail opens it -----------------------------------------------------

	def test_a_message_of_one_s_own_mailbox_is_named_as_the_facade_names_it(self):
		from frappe_webmail import mailcraft_jmap as jmap

		frappe.set_user(STAFF)
		with patch.object(jmap, "_validities", return_value={"Archive": 7}) as validities:
			first = desk.message_key(account=MAILBOX, folder="Archive", uid="31")
			again = desk.message_key(account=MAILBOX, folder="Archive", uid="31")
		self.assertEqual(
			first,
			{
				"account": MAILBOX,
				"mailbox": jmap.mailbox_id("Archive"),
				"email": jmap.email_id("Archive", 7, 31),
			},
		)
		self.assertEqual(again, first, "the same message, the same id")
		self.assertEqual(validities.call_args.args[1], ["Archive"])
		# Its folder alone, without a message; the inbox when the link names no folder
		self.assertEqual(
			desk.message_key(account=MAILBOX), {"account": MAILBOX, "mailbox": jmap.mailbox_id("INBOX")}
		)
		self.assertIn(
			"GET", list(frappe.allowed_http_methods_for_whitelisted_func[desk.message_key]), "a GET, as asked"
		)

	def test_a_message_of_another_s_mailbox_is_not_named(self):
		other = "webmail_neomail_desk_other@webmail.test"
		if not frappe.db.exists("Webmail Account", other):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": other,
					"user": "Administrator",
					"sender_name": "Other",
					"auth_type": "Password",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(STAFF)
		with self.assertRaises(frappe.ValidationError):
			desk.message_key(account=other, folder="INBOX", uid="1")
		with self.assertRaises(frappe.ValidationError, msg="a mailbox that is not there, answered the same"):
			desk.message_key(account="webmail_neomail_nobody@webmail.test", folder="INBOX", uid="1")
		self.sent = {"X-Frappe-CSRF-Token": None}
		with self.assertRaises(frappe.CSRFTokenError):
			desk.message_key(account=MAILBOX, folder="INBOX", uid="1")
		self.sent = {}
		with patch.dict(frappe.local.conf, {desk.FLAG: 0}), self.assertRaises(frappe.PageDoesNotExistError):
			desk.message_key(account=MAILBOX, folder="INBOX", uid="1")
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			desk.message_key(account=MAILBOX, folder="INBOX", uid="1")

	def test_a_load_of_the_webmail_is_answered_by_the_server_with_a_302_to_neomail(self):
		"""Through Frappe's own answer to an address (frappe.website.serve.get_response): the desk's address is a
		website page, and the redirect raised while it is rendered is the answer."""
		from frappe.website.serve import get_response
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		frappe.set_user(STAFF)
		query = urlencode({"account": MAILBOX, "folder": "INBOX", "uid": "31"})
		request = Request(EnvironBuilder(path="/app/webmail", query_string=query).get_environ())
		# www/app.py commits as it builds the desk's boot: not the test's records
		with patch.object(frappe.local, "request", request, create=True), patch.object(frappe.db, "commit"):
			response = get_response("app/webmail")
		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.headers["Location"], "/app/neomail?" + query)

	def test_what_only_the_webmail_has_stays_its_own(self):
		"""Its signatures, filters and automations: NeoMail has no equivalent of them yet."""
		for key in ("signatures", "filters", "automations"):
			self.assertIsNone(desk.neomail_address({key: "1", "uid": "4"}), key)
		frappe.set_user(STAFF)
		for key in ("filters", "automations"):
			self.assertIsNone(self._loaded("/app/webmail", **{key: "1"}), key)

	def test_a_message_of_a_mailbox_shared_with_the_person_is_named_too(self):
		from frappe_webmail import mailcraft_jmap as jmap

		shared = "webmail_neomail_desk_shared@webmail.test"
		if not frappe.db.exists("Webmail Account", shared):
			account = frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": shared,
					"user": "Administrator",
					"sender_name": "Shared",
					"auth_type": "Password",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			)
			account.append("allowed_users", {"user": STAFF})
			account.insert(ignore_permissions=True)
		frappe.set_user(STAFF)
		with patch.object(jmap, "_validities", return_value={"INBOX": 3}):
			self.assertEqual(
				desk.message_key(account=shared, folder="INBOX", uid="8")["email"],
				jmap.email_id("INBOX", 3, 8),
			)

	def test_another_s_mailbox_and_a_missing_one_are_answered_alike_and_no_authorization_gets_in(self):
		other = "webmail_neomail_desk_other@webmail.test"
		if not frappe.db.exists("Webmail Account", other):
			frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": other,
					"user": "Administrator",
					"sender_name": "Other",
					"auth_type": "Password",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(STAFF)
		said = []
		for account in (other, "webmail_neomail_nobody@webmail.test"):
			with self.assertRaises(frappe.ValidationError) as caught:
				desk.message_key(account=account, folder="INBOX", uid="1")
			said.append(str(caught.exception))
		self.assertEqual(said[0], said[1], "« not yours » would say which addresses have a mailbox here")
		for authorization in ("Bearer something", "token api-key:api-secret"):
			self.sent = {"Authorization": authorization}
			with self.assertRaises(frappe.PermissionError, msg=authorization):
				desk.message_key(account=MAILBOX, folder="INBOX", uid="1")

	def test_a_mailbox_may_be_named_by_its_address(self):
		"""Webmail.vue took the mailbox's name or its address: a mailbox whose name is not its address is found by the
		latter, then get_account says who may."""
		with (
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(frappe.db, "get_value", return_value="Desk Box (renamed)") as by_address,
		):
			self.assertEqual(desk._mailbox_name(" box@example.org "), "Desk Box (renamed)")
		self.assertEqual(by_address.call_args.args[1], {"email": "box@example.org"})
		with (
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(frappe.db, "get_value", return_value=None),
		):
			self.assertEqual(desk._mailbox_name("nobody@example.org"), "nobody@example.org")
		self.assertEqual(desk._mailbox_name(MAILBOX), MAILBOX)

	def test_the_message_key_is_asked_so_many_times_a_minute_at_most(self):
		"""One IMAP STATUS a call: a page that would ask in a loop is stopped (rate_limit, by the caller's address)."""
		import secrets

		from frappe_webmail import mailcraft_jmap as jmap

		frappe.set_user(STAFF)
		request = SimpleNamespace(method="GET", path="/api/method/" + MESSAGE_KEY)
		with (
			patch.object(frappe.local, "request", request, create=True),
			patch.object(
				frappe.local, "request_ip", "198.51.100." + str(secrets.randbelow(250) + 1), create=True
			),
			patch.object(frappe.local, "form_dict", frappe._dict(cmd=MESSAGE_KEY + secrets.token_hex(4))),
			patch.object(jmap, "_validities", return_value={"INBOX": 3}),
		):
			for _call in range(60):
				desk.message_key(account=MAILBOX, folder="INBOX", uid="1")
			with self.assertRaises(frappe.RateLimitExceededError):
				desk.message_key(account=MAILBOX, folder="INBOX", uid="1")
