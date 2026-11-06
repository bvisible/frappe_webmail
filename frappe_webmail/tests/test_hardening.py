# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What a mailbox's servers, a portal account, a colleague and another site's page could do with the webmail, and the
legitimate use next to each refusal (maintenance#2296).

- A mail server's words (its greeting, its answers) reach the desk as words, never as markup; a mailbox's settings too.
- What changes a mailbox answers POST only (another site's page makes a browser send a GET); what reads stays a GET.
- A draft and a filter are named by their name, never by a filter of the database.
- The connection tests are the desk's people's; a portal account keeps no mailbox.
- A signature, a signature preference and a draft are checked on whose they are as stored, not as the request says.
- The SMTP certificate is checked for a mailbox that says so (every new one), not for those made before.
- The pool of IMAP connections keeps so many at most, and none idle for longer than it would reuse it.
- A trusted domain is the one after the last @; a party is found through what the person may read; a NeoMail token is
  no longer good than its desk session.

Run with:
    bench --site prodclone.local run-tests --module frappe_webmail.tests.test_hardening
"""

import json
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import FrappeTypeError
from frappe.tests.roles import as_role, without_right
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import webmail_api
from frappe_webmail.webmail_api import WebmailConnectionError

OWNER = "webmail-hard-owner@yopmail.com"
COLLEAGUE = "webmail-hard-colleague@yopmail.com"
PORTAL = "webmail-hard-portal@yopmail.com"
BOX = "webmail-hard-box@hardening.test"
COLLEAGUE_BOX = "webmail-hard-colleague-box@hardening.test"
PORTAL_BOX = "webmail-hard-portal-box@hardening.test"
MARKUP = "b'* BYE <img src=x onerror=alert(document.domain)>'"

MUTATING = (
	"disconnect_oauth",
	"update_account_password",
	"test_connection",
	"test_connection_live",
	"create_folder",
	"mark_email_nora_seen",
	"send_email",
	"save_draft_imap",
	"set_flags",
	"move_emails",
	"copy_emails",
	"rename_folder",
	"mark_folder_read",
	"empty_folder",
	"delete_folder",
	"delete_emails",
	"save_draft",
	"delete_draft",
	"create_contact_from_email",
	"bulk_create_contacts",
	"link_contact_to_document",
	"create_filter",
	"update_filter",
	"delete_filter",
	"apply_filters_to_email",
	"apply_filters_to_folder",
	"add_trusted_source",
	"remove_trusted_source",
	"save_ui_preferences",
	"save_folder_mapping",
)
# Read by the mobile app with a GET (neoffice-mobile hooks/mail): they stay open to it
READ_BY_GET = (
	"get_accounts",
	"get_folders",
	"get_emails",
	"get_conversation",
	"get_email_content",
	"get_sender_card",
	"search_contacts",
	"search_documents",
	"get_recent_documents",
	"get_print_formats",
	"get_drive_files",
	"get_drive_file_content",
)


def _mailbox(email, user, shared_with=()):
	doc = frappe.get_doc(
		{
			"doctype": "Webmail Account",
			"email": email,
			"user": user,
			"sender_name": "Hardening",
			"auth_type": "Password",
			"imap_host": "imap.hardening.test",
			"imap_port": 993,
			"imap_ssl": 1,
			"imap_password": "x",
			"smtp_host": "smtp.hardening.test",
			"smtp_port": 587,
			"smtp_ssl": 0,
			"smtp_starttls": 1,
			"smtp_password": "x",
			"enabled": 1,
			"allowed_users": [{"user": u} for u in shared_with],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _imap_greeting(imap_class, error):
	"""The test's IMAPClient: a server that answers the sign-in with `error`."""
	client = MagicMock()
	client.login.side_effect = error
	imap_class.return_value.__enter__ = MagicMock(return_value=client)
	imap_class.return_value.__exit__ = MagicMock(return_value=False)
	return client


class TestMailboxHardening(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# The people of the test, with their real roles (frappe/tests/roles.py)
		with as_role("sales_user", email=OWNER):
			pass
		with as_role("warehouse", email=COLLEAGUE):
			pass
		with as_role("portal_customer", email=PORTAL):
			pass
		for name in (BOX, COLLEAGUE_BOX, PORTAL_BOX):
			if frappe.db.exists("Webmail Account", name):
				frappe.delete_doc("Webmail Account", name, force=True, ignore_permissions=True)
		_mailbox(BOX, OWNER, shared_with=[COLLEAGUE])
		_mailbox(COLLEAGUE_BOX, COLLEAGUE)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for doctype, filters in (
			("Email Draft", {"account": ["in", [BOX, COLLEAGUE_BOX]]}),
			("Email Filter", {"account": ["in", [BOX, COLLEAGUE_BOX]]}),
			("Email Signature", {"user": ["in", [OWNER, COLLEAGUE]]}),
			("Email Signature Preference", {"user": ["in", [OWNER, COLLEAGUE]]}),
		):
			for name in frappe.get_all(doctype, filters=filters, pluck="name"):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		for name in (BOX, COLLEAGUE_BOX, PORTAL_BOX):
			if frappe.db.exists("Webmail Account", name):
				frappe.delete_doc("Webmail Account", name, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.local.message_log = []

	def tearDown(self):
		frappe.set_user("Administrator")

	# -------------------------------------------------------------------- a server's words, as words

	def test_a_servers_greeting_reaches_whom_the_mailbox_is_shared_with_as_words(self):
		with patch("frappe_webmail.webmail_api.IMAPClient") as imap:
			_imap_greeting(imap, Exception(MARKUP))
			with as_role("warehouse", email=COLLEAGUE), self.assertRaises(WebmailConnectionError) as caught:
				webmail_api.get_folders(BOX)
		shown = str(caught.exception) + json.dumps(frappe.local.message_log, default=str)
		self.assertNotIn("<img", shown)
		self.assertIn("&lt;img src=x onerror=alert(document.domain)&gt;", str(caught.exception))

	def test_the_test_connection_dialog_is_handed_words_too(self):
		with (
			patch("frappe_webmail.webmail_api.IMAPClient") as imap,
			patch("frappe_webmail.webmail_api.smtplib.SMTP") as smtp,
		):
			_imap_greeting(imap, Exception(MARKUP))
			smtp.return_value.__enter__ = MagicMock(return_value=MagicMock())
			smtp.return_value.__exit__ = MagicMock(return_value=False)
			with as_role("sales_user", email=OWNER):
				result = webmail_api.test_connection(BOX)
		self.assertFalse(result["success"])
		self.assertTrue(result["smtp_success"])
		self.assertNotIn("<", "".join(result["errors"]))
		self.assertIn("&lt;img", result["errors"][0])

	def test_an_smtp_servers_answer_to_a_message_is_words(self):
		with patch("frappe_webmail.api.smtplib.SMTP") as smtp:
			smtp.return_value.sendmail.side_effect = smtplib.SMTPDataError(554, b"<script>alert(1)</script>")
			with as_role("sales_user", email=OWNER), self.assertRaises(frappe.ValidationError) as caught:
				webmail_api.send_email(BOX, "someone@example.com", "Hello", "<p>Hi</p>")
		self.assertNotIn("<script>", str(caught.exception))
		self.assertIn("&lt;script&gt;", str(caught.exception))

	def test_a_mailbox_server_address_is_words_and_a_plain_error_says_what_it_said(self):
		account = SimpleNamespace(
			imap_host="<b>imap</b>.hardening.test",
			imap_port=993,
			imap_ssl=1,
			smtp_host="x",
			smtp_port=1,
			smtp_ssl=0,
		)
		refused = webmail_api._format_connection_error(
			"IMAP", ConnectionRefusedError("Connection refused"), account
		)
		self.assertIn("&lt;b&gt;imap&lt;/b&gt;.hardening.test:993", refused)
		# What a legitimate mailbox is told is unchanged
		account.imap_host = "imap.hardening.test"
		self.assertEqual(
			webmail_api._format_connection_error(
				"IMAP", ConnectionRefusedError("Connection refused"), account
			),
			"IMAP: Connection refused to imap.hardening.test:993. Check that the server address and port are correct.",
		)
		self.assertEqual(
			webmail_api._format_connection_error("SMTP", OSError("No route to host"), account),
			"SMTP: No route to host",
		)

	# -------------------------------------------------------------------- what changes answers POST only

	def test_what_changes_a_mailbox_answers_post_only(self):
		from frappe.handler import is_valid_http_method

		for name in MUTATING:
			method = getattr(webmail_api, name)
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ("POST",), name)
		# Another site's page makes the browser send a GET: refused; the webmail's own frappe.call is a POST
		with patch.object(frappe.local, "request", SimpleNamespace(method="GET"), create=True):
			with self.assertRaises(frappe.PermissionError):
				is_valid_http_method(webmail_api.delete_emails)
		with patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True):
			is_valid_http_method(webmail_api.delete_emails)

	def test_what_the_mobile_app_reads_by_get_stays_open_to_it(self):
		for name in READ_BY_GET:
			self.assertIn(
				"GET", frappe.allowed_http_methods_for_whitelisted_func[getattr(webmail_api, name)], name
			)

	# -------------------------------------------------------------------- a draft and a filter, by their name

	def test_a_draft_is_named_by_its_name_never_by_a_filter(self):
		with as_role("sales_user", email=OWNER):
			draft = frappe.get_doc(
				{
					"doctype": "Email Draft",
					"account": BOX,
					"subject": "Hardening",
					"html_content": "hardening-secret",
				}
			).insert()
			self.assertEqual(webmail_api.get_draft(draft.name)["html_content"], "hardening-secret")
		search = {"user": ["!=", COLLEAGUE], "html_content": ["like", "hardening-s%"]}
		miss = {"user": ["!=", COLLEAGUE], "html_content": ["like", "hardening-x%"]}
		with as_role("warehouse", email=COLLEAGUE):
			for asked in (search, miss):
				with self.assertRaises(FrappeTypeError):
					webmail_api.get_draft(asked)
				with self.assertRaises(FrappeTypeError):
					webmail_api.delete_draft(asked)
			# Someone else's draft by its name: refused as before
			with self.assertRaisesRegex(frappe.ValidationError, "Access denied"):
				webmail_api.get_draft(draft.name)
		self.assertTrue(frappe.db.exists("Email Draft", draft.name))

	def test_a_filter_is_named_by_its_name_never_by_a_filter(self):
		with as_role("sales_user", email=OWNER):
			made = webmail_api.create_filter(
				BOX, "Hardening", from_contains="hardening-from", target_folder="X"
			)
			name = made["filter_name"]
			webmail_api.update_filter(name, enabled=0)
		self.assertEqual(frappe.db.get_value("Email Filter", name, "enabled"), 0)
		with as_role("warehouse", email=COLLEAGUE):
			for asked in ({"user": ["!=", COLLEAGUE], "from_contains": ["like", "hardening%"]},):
				with self.assertRaises(FrappeTypeError):
					webmail_api.update_filter(asked, enabled=1)
				with self.assertRaises(FrappeTypeError):
					webmail_api.delete_filter(asked)
		self.assertEqual(frappe.db.get_value("Email Filter", name, "enabled"), 0)
		with as_role("sales_user", email=OWNER):
			webmail_api.delete_filter(name)
		self.assertFalse(frappe.db.exists("Email Filter", name))

	def test_a_draft_cannot_be_taken_by_naming_oneself_its_person(self):
		with as_role("sales_user", email=OWNER):
			draft = frappe.get_doc(
				{"doctype": "Email Draft", "account": BOX, "subject": "Hardening", "html_content": "mine"}
			).insert()
		with as_role("warehouse", email=COLLEAGUE):
			# What /api/resource does: the document loaded, the request's fields put on it, saved
			taken = frappe.get_doc("Email Draft", draft.name)
			taken.update({"user": COLLEAGUE, "account": COLLEAGUE_BOX})
			with self.assertRaises(frappe.PermissionError):
				taken.save()
		self.assertEqual(frappe.db.get_value("Email Draft", draft.name, "user"), OWNER)
		# Its person still saves it
		with as_role("sales_user", email=OWNER):
			mine = frappe.get_doc("Email Draft", draft.name)
			mine.subject = "Hardening again"
			mine.save()

	# -------------------------------------------------------------------- the desk's people only

	def test_a_portal_account_makes_the_server_connect_nowhere(self):
		with (
			patch("frappe_webmail.webmail_api.IMAPClient") as imap,
			patch("frappe_webmail.webmail_api.smtplib"),
		):
			with as_role("portal_customer", email=PORTAL), self.assertRaises(frappe.PermissionError):
				webmail_api.test_connection_live(
					"x@hardening.test", "127.0.0.1", 3306, 0, "10.0.0.1", 22, 0, 0, "Password", "x", "x"
				)
			imap.assert_not_called()

	def test_the_desk_form_still_tests_a_mailbox_before_it_is_saved(self):
		with (
			patch("frappe_webmail.webmail_api.IMAPClient") as imap,
			patch("frappe_webmail.webmail_api.smtplib.SMTP") as smtp,
		):
			client = MagicMock()
			imap.return_value.__enter__ = MagicMock(return_value=client)
			imap.return_value.__exit__ = MagicMock(return_value=False)
			server = MagicMock()
			smtp.return_value.__enter__ = MagicMock(return_value=server)
			smtp.return_value.__exit__ = MagicMock(return_value=False)
			with as_role("sales_user", email=OWNER):
				result = webmail_api.test_connection_live(
					OWNER,
					"imap.hardening.test",
					993,
					1,
					"smtp.hardening.test",
					587,
					0,
					1,
					"Password",
					"a",
					"b",
					None,
					None,
					1,
				)
		self.assertTrue(result["success"])
		context = server.starttls.call_args.kwargs["context"]
		self.assertIsInstance(context, ssl.SSLContext)
		self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

	def test_a_portal_account_keeps_no_mailbox(self):
		with as_role("portal_customer", email=PORTAL):
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(
					{
						"doctype": "Webmail Account",
						"email": PORTAL_BOX,
						"user": PORTAL,
						"auth_type": "Password",
						"imap_host": "imap.hardening.test",
						"imap_password": "x",
						"smtp_host": "smtp.hardening.test",
						"smtp_password": "x",
					}
				).insert()
			answers = []
			for name in (BOX, "webmail-hard-nobody@hardening.test"):
				with self.assertRaises(frappe.ValidationError) as caught:
					webmail_api.get_account(name)
				answers.append(str(caught.exception))
			self.assertEqual(answers[0], answers[1])
		self.assertFalse(frappe.db.exists("Webmail Account", PORTAL_BOX))
		# A desk person makes their own, and whom it is shared with reads it
		with as_role("warehouse", email=COLLEAGUE):
			self.assertEqual(webmail_api.get_account(BOX).name, BOX)

	# -------------------------------------------------------------------- whose it is, as stored

	def test_a_signature_cannot_be_taken_by_naming_oneself_its_person(self):
		with as_role("sales_user", email=OWNER):
			signature = frappe.get_doc(
				{"doctype": "Email Signature", "signature_name": "Hardening", "content": "<p>Owner</p>"}
			).insert()
			# The signature editor's own path: frappe.client.set_value
			frappe.client.set_value("Email Signature", signature.name, {"content": "<p>Owner again</p>"})
		with as_role("warehouse", email=COLLEAGUE):
			taken = frappe.get_doc("Email Signature", signature.name)
			taken.update({"user": COLLEAGUE})
			with self.assertRaises(frappe.PermissionError):
				taken.save()
		self.assertEqual(frappe.db.get_value("Email Signature", signature.name, "user"), OWNER)
		self.assertIn("Owner again", frappe.db.get_value("Email Signature", signature.name, "content"))
		with as_role("sales_user", email=OWNER):
			given = frappe.get_doc("Email Signature", signature.name)
			given.user = COLLEAGUE
			with self.assertRaises(frappe.PermissionError):
				given.save()

	def test_someone_elses_signature_choices_are_not_changed_by_naming_oneself(self):
		from frappe_webmail.signatures import PREFERENCE, save_my_choices

		with as_role("sales_user", email=OWNER):
			save_my_choices(photo_allowed=0, hide_mobile=1)
		with as_role("warehouse", email=COLLEAGUE):
			theirs = frappe.get_doc(PREFERENCE, OWNER)
			theirs.update({"user": COLLEAGUE, "photo_allowed": 1, "hide_mobile": 0})
			with self.assertRaises(frappe.PermissionError):
				theirs.save()
		self.assertEqual(
			frappe.db.get_value(PREFERENCE, OWNER, ["photo_allowed", "hide_mobile"], as_dict=True),
			{"photo_allowed": 0, "hide_mobile": 1},
		)
		# The person changes their own
		with as_role("sales_user", email=OWNER):
			save_my_choices(hide_mobile=0)
		self.assertEqual(frappe.db.get_value(PREFERENCE, OWNER, "hide_mobile"), 0)

	# -------------------------------------------------------------------- the SMTP certificate

	def test_the_smtp_certificate_is_checked_for_a_mailbox_that_says_so(self):
		checked = webmail_api.smtp_tls_context(SimpleNamespace(smtp_verify_certificate=1))
		self.assertEqual((checked.verify_mode, checked.check_hostname), (ssl.CERT_REQUIRED, True))
		self.assertIsNone(webmail_api.smtp_tls_context(SimpleNamespace(smtp_verify_certificate=0)))
		self.assertIsNone(webmail_api.smtp_tls_context(SimpleNamespace()))
		self.assertEqual(frappe.new_doc("Webmail Account").smtp_verify_certificate, 1)
		for flag in (1, 0):
			frappe.db.set_value("Webmail Account", BOX, "smtp_verify_certificate", flag)
			with (
				patch("frappe_webmail.api.smtplib.SMTP") as smtp,
				patch.object(webmail_api, "_copy_to_sent_folder"),
				as_role("sales_user", email=OWNER),
			):
				webmail_api.send_email(BOX, "someone@example.com", "Hello", "<p>Hi</p>")
			context = smtp.return_value.starttls.call_args.kwargs["context"]
			if flag:
				self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
			else:
				# A mailbox made before the setting sends as it did (smtplib's own context)
				self.assertIsNone(context)

	def test_the_mailboxes_there_before_the_setting_keep_sending_as_they_did(self):
		from frappe_webmail.patches import (
			smtp_certificate_check_stays_off_for_existing_mailboxes as patch_module,
		)

		frappe.db.savepoint("wm_patch")
		try:
			frappe.db.set_value("Webmail Account", BOX, "smtp_verify_certificate", 1)
			patch_module.execute()
			self.assertEqual(frappe.db.get_value("Webmail Account", BOX, "smtp_verify_certificate"), 0)
		finally:
			frappe.db.rollback(save_point="wm_patch")

	# -------------------------------------------------------------------- the pool of IMAP connections

	def test_the_pool_keeps_so_many_connections_and_none_idle_too_long(self):
		made = []

		def connect(account):
			client = MagicMock(name=account.name)
			made.append(client)
			return client

		def box(n):
			return SimpleNamespace(name=f"pool-{n}@hardening.test")

		previous = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			with (
				patch.dict(webmail_api._IMAP_POOL, clear=True),
				patch.object(webmail_api, "_IMAP_POOL_MAX", 3),
				patch.object(webmail_api, "_imap_connect", side_effect=connect),
			):
				for n in range(5):
					with webmail_api.imap_session(box(n)):
						pass
				self.assertEqual(len(webmail_api._IMAP_POOL), 3)
				self.assertEqual([c.shutdown.call_count for c in made], [1, 1, 0, 0, 0])
				# The same mailbox again: its connection is used again, not a new one
				with webmail_api.imap_session(box(4)) as client:
					self.assertIs(client, made[4])
				# One idle past the time a connection is reused goes at the next lease
				webmail_api._IMAP_POOL["pool-2@hardening.test"].last_used -= webmail_api._IMAP_MAX_IDLE + 1
				with webmail_api.imap_session(box(4)):
					pass
				self.assertNotIn("pool-2@hardening.test", webmail_api._IMAP_POOL)
				self.assertEqual(made[2].shutdown.call_count, 1)
		finally:
			frappe.flags.in_test = previous

	# -------------------------------------------------------------------- a trusted domain

	def test_a_trusted_domain_is_the_one_after_the_last_at(self):
		account = frappe.get_doc("Webmail Account", BOX)
		account.set("trusted_sources", [{"source_type": "Domain", "value": "trusted.example"}])
		account.save(ignore_permissions=True)
		with as_role("sales_user", email=OWNER):
			# As the mail's From says it, and as the IMAP server's ENVELOPE gives it (without the quotes)
			self.assertFalse(webmail_api.is_sender_trusted(BOX, '"x@trusted.example"@attacker.example'))
			self.assertFalse(webmail_api.is_sender_trusted(BOX, "x@trusted.example@attacker.example"))
			self.assertTrue(webmail_api.is_sender_trusted(BOX, "someone@trusted.example"))

	# -------------------------------------------------------------------- a party, through what one may read

	def test_a_party_is_found_through_a_contact_the_person_may_read_only(self):
		from frappe_webmail.documents import parties_of

		customer = frappe.get_all("Customer", pluck="name", limit=1)
		if not customer:
			self.skipTest("no customer on this site")
		address = "webmail-hard-contact@hardening.test"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Webmail hardening",
				"email_ids": [{"email_id": address, "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer[0]}],
			}
		).insert(ignore_permissions=True)
		try:
			with as_role("sales_user", email=OWNER):
				self.assertIn(("Customer", customer[0]), parties_of([address]))
				with without_right("Contact", "read"):
					self.assertNotIn(("Customer", customer[0]), parties_of([address]))
		finally:
			frappe.delete_doc("Contact", contact.name, force=True, ignore_permissions=True)

	# -------------------------------------------------------------------- a NeoMail token and its desk session

	def test_a_token_is_no_longer_good_than_its_desk_session(self):
		sid = "webmail-hardening-" + frappe.generate_hash(length=10)
		now = now_datetime()

		def session(last_updated, end=None):
			data = {"last_updated": str(last_updated), "session_expiry": "06:00:00"}
			if end:
				data["session_end"] = end
			frappe.cache().hset("session", sid, {"user": OWNER, "sid": sid, "data": data})

		try:
			session(add_to_date(now, hours=-7))
			self.assertFalse(jmap._session_alive(sid), "idle past its expiry")
			# Someone working in NeoMail alone is not idle: the token's requests count
			self.assertTrue(jmap._session_alive(sid, str(add_to_date(now, minutes=-1))))
			session(add_to_date(now, minutes=-1))
			self.assertTrue(jmap._session_alive(sid))
			ended = (datetime.now(tz=timezone.utc) - timedelta(minutes=1)).isoformat()
			session(add_to_date(now, minutes=-1), end=ended)
			self.assertFalse(jmap._session_alive(sid, str(now)), "past its end")
		finally:
			frappe.cache().hdel("session", sid)

	def test_a_token_in_use_keeps_its_person_in(self):
		sid = "webmail-hardening-" + frappe.generate_hash(length=10)
		token = "webmail-hardening-" + frappe.generate_hash(length=20)
		frappe.cache().hset(
			"session",
			sid,
			{
				"user": OWNER,
				"sid": sid,
				"data": {"last_updated": str(now_datetime()), "session_expiry": "06:00:00"},
			},
		)
		frappe.cache().set_value(jmap._token_key(token), {"user": OWNER, "sid": sid}, expires_in_sec=60)
		try:
			self.assertEqual(jmap._person_of_token(token), OWNER)
			self.assertTrue(frappe.cache().get_value(jmap._active_key(token)))
		finally:
			frappe.cache().hdel("session", sid)
			frappe.cache().delete_value([jmap._token_key(token), jmap._active_key(token)])
