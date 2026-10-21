# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Share an e-mail in Synk from NeoMail (neomail_share.py): what the post says and never says, which attachments go,
and who may share, where. The server's mail and Raven's send are stood in for: nothing reaches a mailbox or a channel.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_neomail_share
"""

import sys
import types
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import neomail_share as share

PORTAL = "webmail_neomail_share_portal@example.com"
STAFF = "webmail_neomail_share_staff@example.com"
MAILBOX = "webmail_neomail_share_box@webmail.test"
EMAIL_ID = "E7V31ZSU5CT1g"


def _make_user(email, desk_user, raven=False):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	if desk_user:
		user.append("roles", {"role": "Blogger"})
	else:
		user.user_type = "Website User"
	if raven:
		user.append("roles", {"role": share.RAVEN_ROLE})
	user.insert(ignore_permissions=True)


def _raven(module, **functions):
	"""Raven's `module` with `functions`, stood in for as `share` imports it (`from raven.api… import …`), whether
	Raven is installed on the bench or not (the CI's bench has no Raven)."""
	stand_in = types.ModuleType(module)
	for name, function in functions.items():
		setattr(stand_in, name, function)
	parents = {name: sys.modules.get(name) or types.ModuleType(name) for name in ("raven", "raven.api")}
	return patch.dict(sys.modules, {**parents, module: stand_in})


def _mail(text="Bonjour,\nla scie sera prête demain.", html=None, attachments=()):
	"""A message as a server would hold it, its bytes as `_source` gives them."""
	message = EmailMessage()
	message["Subject"] = "Livraison <b>scie</b>"
	message["From"] = "Grace Hopper <grace@example.org>"
	message["To"] = MAILBOX
	message["Date"] = "Wed, 14 Oct 2026 16:00:00 +0000"
	message.set_content(text)
	if html:
		message.add_alternative(html, subtype="html")
	for name, data, inline in attachments:
		message.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
		if inline:
			part = list(message.iter_attachments())[-1]
			part.replace_header("Content-Disposition", "inline")
			part["Content-ID"] = "<pic@example.org>"
	return message.as_bytes()


class TestNeoMailShare(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_make_user(PORTAL, desk_user=False)
		_make_user(STAFF, desk_user=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in (PORTAL, STAFF):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		super().tearDownClass()

	def test_the_post_quotes_the_message_escaped_and_links_back_to_neomail(self):
		from email import message_from_bytes, policy

		raw = _mail(text="Le prix : <script>alert(1)</script>\n\n\n\nMerci")
		message = message_from_bytes(raw, policy=policy.default)
		html = share._content(message, "Pour info <i>urgent</i>\nmerci", MAILBOX, EMAIL_ID)
		# The person's words first, then the message quoted, then the link
		self.assertTrue(html.startswith("<p>Pour info &lt;i&gt;urgent&lt;/i&gt;<br>merci</p><blockquote>"))
		self.assertIn("<strong>Livraison &lt;b&gt;scie&lt;/b&gt;</strong>", html)
		self.assertIn("Grace Hopper &lt;grace@example.org&gt;", html)
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
		self.assertNotIn("<script>", html)
		self.assertNotIn("<b>scie", html)
		# Blank lines kept to one: two paragraphs of text
		self.assertIn("<p>Le prix : &lt;script&gt;alert(1)&lt;/script&gt;</p><p>Merci</p>", html)
		self.assertIn(
			"/app/neomail?account=webmail_neomail_share_box%40webmail.test&amp;email=" + EMAIL_ID, html
		)

	def test_an_html_message_is_read_as_text_never_as_html_and_cut_at_a_word(self):
		from email import message_from_bytes, policy

		long_words = " ".join(["mot"] * 1000)
		html = f'<p>Voir <a href="https://tracker.example/x">le devis</a></p><img src="https://tracker.example/p.gif"><p>{long_words}</p>'
		# With a plain part beside it, the plain part is the text
		with_plain = message_from_bytes(_mail(text="x", html=html), policy=policy.default)
		only_html = EmailMessage()
		only_html["Subject"] = "HTML"
		only_html.set_content(html, subtype="html")
		text = share._text(only_html)
		self.assertIn("Voir le devis", text)
		self.assertNotIn("tracker.example", text)
		self.assertNotIn("<", text)
		self.assertLessEqual(len(text), share.MAX_TEXT + 2)
		self.assertTrue(text.endswith(" …"))
		self.assertEqual(share._text(with_plain), "x")

	def test_only_real_attachments_go_within_their_limits(self):
		from email import message_from_bytes, policy

		raw = _mail(
			attachments=[
				("devis.txt", b"montant 62.83", False),
				("logo.png", b"\x89PNG inline", True),
				("trop-gros.bin", b"x" * (share.MAX_FILE + 1), False),
			]
		)
		message = message_from_bytes(raw, policy=policy.default)
		saved = []

		class Saved:
			def __init__(self, doc):
				self.doc = doc

			def insert(self):
				saved.append(self.doc)
				self.file_url = "/private/files/" + self.doc["file_name"]
				self.file_size = len(self.doc["content"])
				return self

		with patch.object(share.frappe, "get_doc", side_effect=lambda doc: Saved(doc)):
			files, left_out = share._attachments(message)
		self.assertEqual([doc["file_name"] for doc in saved], ["devis.txt"])
		self.assertTrue(all(doc["is_private"] == 1 for doc in saved))
		self.assertEqual(files, [{"file_url": "/private/files/devis.txt", "file_size": 13}])
		# The inline picture is not an attachment; the one too large is left out, and counted
		self.assertEqual(left_out, 1)

	def test_the_date_is_the_site_s_hour_its_month_in_words(self):
		with patch("frappe.utils.get_system_timezone", return_value="Europe/Zurich"):
			for header in (
				"Sat, 04 Jul 2026 08:50:00 -0000",
				"Sat, 04 Jul 2026 08:50:00 +0000",
				"Sat, 04 Jul 2026 10:50:00 +0200",
			):
				message = EmailMessage()
				message["Date"] = header
				written = share._date(message)
				# Summer in Zurich: two hours after UTC; no run of digits Raven would take for a telephone number
				self.assertIn("2026", written, header)
				self.assertIn("10:50", written, header)
				self.assertNotIn("04-07", written, header)
			message = EmailMessage()
			message["Date"] = "not a date"
			self.assertEqual(share._date(message), "")

	def test_an_attachment_s_name_keeps_nothing_a_path_or_a_header_could_slip_in(self):
		self.assertEqual(share._file_name("../../etc/passwd"), "passwd")
		self.assertEqual(share._file_name('C:\\temp\\fac<t>ure".pdf'), "facture.pdf")
		self.assertEqual(share._file_name(""), "attachment")
		long_name = "a" * 300 + ".pdf"
		self.assertEqual(len(share._file_name(long_name)), share.MAX_FILE_NAME)
		self.assertTrue(share._file_name(long_name).endswith(".pdf"))

	def test_a_portal_account_and_someone_without_synk_are_refused(self):
		with (
			patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk", return_value=True),
			patch("frappe_webmail.mailcraft_jmap.page_request_only"),
			patch("frappe_webmail.mailcraft_jmap.csrf_token_required"),
		):
			frappe.set_user(PORTAL)
			self.assertFalse(share.offered())
			self.assertRaises(frappe.PermissionError, share.destinations)
			frappe.set_user(STAFF)
			# A desk account without the Raven role (Raven may give it to every desk account it adds: taken away here)
			with (
				patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk_for", return_value=True),
				patch.object(share.frappe, "get_roles", return_value=["Blogger", "All"]),
			):
				self.assertFalse(share.offered())
				self.assertRaises(frappe.PermissionError, share.destinations)

	def test_a_site_without_synk_says_it_is_not_installed_here(self):
		apps = [app for app in frappe.get_installed_apps() if app != "raven"]
		with (
			patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk", return_value=True),
			patch("frappe_webmail.mailcraft_jmap.page_request_only"),
			patch("frappe_webmail.mailcraft_jmap.csrf_token_required"),
			patch.object(share.frappe, "get_installed_apps", return_value=apps),
		):
			frappe.set_user(STAFF)
			self.assertFalse(share.installed())
			self.assertFalse(share.offered())
			for call, kwargs in (
				(share.destinations, {}),
				(share.share, {"account": MAILBOX, "email": EMAIL_ID, "to": "user:x"}),
			):
				with self.assertRaisesRegex(frappe.ValidationError, "Synk is not installed here"):
					call(**kwargs)

	def test_the_message_goes_where_the_person_chose_as_the_person(self):
		sent = {}

		def send(**kwargs):
			sent.update(kwargs)
			return [SimpleNamespace(name="m-1"), SimpleNamespace(name="m-2")]

		box = SimpleNamespace(email=MAILBOX)
		with (
			patch.object(share, "_gate"),
			patch("frappe_webmail.webmail_api.get_account", return_value=box) as account,
			patch("frappe_webmail.mailcraft_jmap._source", return_value=_mail()) as source,
			patch.object(share, "_conversation", return_value="synk-atelier") as conversation,
			_raven("raven.api.raven_message", send_message_with_attachments=send),
		):
			answer = share.share(
				account=MAILBOX, email=EMAIL_ID, to="channel:synk-atelier", note="Pour info", client_id="c-1"
			)
		self.assertEqual(answer, {"channel": "synk-atelier", "message": "m-2", "files": 0, "left_out": 0})
		account.assert_called_once()
		source.assert_called_once_with(box, EMAIL_ID)
		conversation.assert_called_once_with("channel:synk-atelier")
		self.assertEqual(sent["channel_id"], "synk-atelier")
		self.assertEqual(sent["files"], [])
		self.assertEqual(sent["client_id"], "c-1")
		self.assertIn("<p>Pour info</p>", sent["content"])

	def test_an_id_that_is_not_a_message_s_is_refused_before_any_mail_is_read(self):
		with (
			patch.object(share, "_gate"),
			patch("frappe_webmail.webmail_api.get_account", return_value=SimpleNamespace(email=MAILBOX)),
			patch("frappe_webmail.mailcraft_jmap._source") as source,
		):
			for wrong in ("M7", "B7V31ZSU5CT1g", "../../etc", ""):
				self.assertRaises(
					frappe.ValidationError, share.share, account=MAILBOX, email=wrong, to="user:x"
				)
			source.assert_not_called()

	def test_only_a_channel_of_the_person_s_or_a_person_is_a_conversation(self):
		with (
			patch.object(share.frappe.db, "get_value", return_value=None),
			patch.object(share.frappe.db, "exists", return_value=None),
		):
			self.assertRaises(frappe.ValidationError, share._conversation, "channel:synk-someone-elses")
		self.assertRaises(frappe.ValidationError, share._conversation, "")
		self.assertRaises(frappe.ValidationError, share._conversation, "team:everyone")
		asked = []

		def direct_message(user_id):
			asked.append(user_id)
			return "dm-1"

		with _raven("raven.api.raven_channel", create_direct_message_channel=direct_message):
			self.assertEqual(share._conversation("user:bruno@example.org"), "dm-1")
		self.assertEqual(asked, ["bruno@example.org"])
