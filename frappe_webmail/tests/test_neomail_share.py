# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Share an e-mail in Synk from NeoMail (neomail_share.py): what the post says and never says, which attachments go,
and who may share, where; chat in Synk about it: with whom, in which conversation, asked when. The server's mail and
Raven are stood in for: nothing reaches a mailbox or a channel.

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
# The person chatting, by their address alone: no account is made for it (`_people` is stood in for).
STAFF_CHAT = "webmail_neomail_chat_staff@example.com"
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
			# (Raven taken as installed, whether the bench has it or not: this is about the role.)
			with (
				patch("frappe_webmail.frappe_webmail.page.neomail.neomail.in_desk_for", return_value=True),
				patch.object(share.frappe, "get_roles", return_value=["Blogger", "All"]),
				patch.object(share, "installed", return_value=True),
			):
				self.assertFalse(share.offered())
				self.assertRaises(frappe.PermissionError, share.destinations)

	def test_synk_is_had_where_raven_is_by_whom_holds_its_role(self):
		with (
			patch.object(share, "installed", return_value=True),
			patch.object(share.frappe, "get_roles", return_value=["Raven User", "All"]),
		):
			self.assertTrue(share.has_synk(STAFF))
		with (
			patch.object(share, "installed", return_value=True),
			patch.object(share.frappe, "get_roles", return_value=["Blogger", "All"]),
		):
			self.assertFalse(share.has_synk(STAFF))
		with patch.object(share, "installed", return_value=False):
			self.assertFalse(share.has_synk(STAFF))

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
				(share.chat, {"account": MAILBOX, "email": EMAIL_ID, "who": "sender"}),
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


def _thread(subject, own_id, answers=(), to=MAILBOX, cc=None, bcc=None):
	"""A message of a thread: its subject, its own id, the ids of those it answers (the first is the thread's)."""
	message = EmailMessage()
	message["Subject"] = subject
	message["From"] = "Grace Hopper <grace@example.org>"
	message["To"] = to
	if cc:
		message["Cc"] = cc
	if bcc:
		message["Bcc"] = bcc
	message["Message-ID"] = own_id
	if answers:
		message["In-Reply-To"] = answers[-1]
		message["References"] = " ".join(answers)
	message.set_content("Bonjour")
	return message


def _no_post(**kwargs):
	raise AssertionError("chat posts nothing in the person's name")


class TestNeoMailChat(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def _chat(self, raw, who, people, **more):
		"""`chat` on the message `raw`, the Synk users among its addresses being `people` ({address: (user,
		label)}); answers (its answer, the addresses it asked about, the direct messages Raven was asked for)."""
		asked, direct = [], []

		def found(addresses):
			asked.append(list(addresses))
			return [{"user": people[a][0], "label": people[a][1]} for a in addresses if a in people]

		def direct_message(user_id):
			direct.append(user_id)
			return "dm-" + user_id.split("@")[0]

		with (
			patch.object(share, "_gate"),
			patch("frappe_webmail.webmail_api.get_account", return_value=SimpleNamespace(email=MAILBOX)),
			patch("frappe_webmail.mailcraft_jmap._source", return_value=raw),
			patch.object(share, "_people", side_effect=found),
			_raven("raven.api.raven_channel", create_direct_message_channel=direct_message),
			_raven("raven.api.raven_message", send_message_with_attachments=_no_post),
		):
			answer = share.chat(account=MAILBOX, email=EMAIL_ID, who=who, **more)
		return answer, asked, direct

	def test_chat_reads_who_is_on_a_message_whatever_its_size(self):
		message = _thread("Plans", "<a1@example.org>")
		message.set_content("x" * (share.MAX_SOURCE + 1))
		answer, asked, _direct = self._chat(
			message.as_bytes(), "sender", {"grace@example.org": ("grace@example.org", "Grace Hopper")}
		)
		self.assertEqual(asked, [["grace@example.org"]])
		self.assertEqual(answer["channel"], "dm-grace")

	def test_the_thread_s_channel_is_named_the_same_from_every_message_of_it(self):
		first = _thread("Devis cuisine", "<a1@example.org>")
		reply = _thread("RE: Fwd: Devis cuisine", "<b2@example.org>", answers=["<a1@example.org>"])
		later = _thread(
			"Re: Devis cuisine (suite)", "<c3@example.org>", answers=["<a1@example.org>", "<b2@example.org>"]
		)
		key = share._thread_key(first)
		self.assertEqual(share._thread_key(reply), key)
		self.assertEqual(share._thread_key(later), key)
		self.assertEqual(len(key), share.CHAT_KEY)
		self.assertEqual(share._chat_name(reply, key), "devis-cuisine-" + key)
		# Another thread, and the person's own key of the same one, are other channels
		self.assertNotEqual(share._thread_key(_thread("Devis cuisine", "<z9@example.org>")), key)
		self.assertNotEqual(share._thread_key(first, "staff@example.org"), key)
		# As Raven writes a name: lower case, words joined by hyphens, accents left out, the subject's words cut
		accents = _thread("Réunion d'équipe : l'été / « bilan »", "<d4@example.org>")
		self.assertEqual(share._chat_name(accents, "k"), "reunion-d-equipe-l-ete-bilan-k")
		long_words = _thread("mot " * 100, "<e5@example.org>")
		self.assertLessEqual(
			len(share._chat_name(long_words, key)), share.MAX_CHAT_WORDS + 1 + share.CHAT_KEY
		)
		self.assertIn('"Devis cuisine" from Grace Hopper', share._about(first))

	def test_chat_with_the_sender_opens_their_direct_message_and_posts_nothing(self):
		raw = _thread("Devis", "<a1@example.org>").as_bytes()
		answer, asked, direct = self._chat(
			raw, "sender", {"grace@example.org": ("grace@example.org", "Grace Hopper")}
		)
		self.assertEqual(asked, [["grace@example.org"]])
		self.assertEqual(direct, ["grace@example.org"])
		self.assertEqual(
			answer,
			{
				"channel": "dm-grace",
				"route": "/raven/dm-channel/dm-grace",
				"with": ["Grace Hopper"],
				"left_out": 0,
			},
		)

	def test_chat_with_the_sender_is_refused_on_one_s_own_message_and_when_they_do_not_use_synk(self):
		raw = _thread("Devis", "<a1@example.org>").as_bytes()
		with self.assertRaisesRegex(frappe.ValidationError, "does not use Synk"):
			self._chat(raw, "sender", {})
		frappe.set_user(STAFF_CHAT)
		with self.assertRaisesRegex(frappe.ValidationError, "You wrote this message"):
			self._chat(raw, "sender", {"grace@example.org": (STAFF_CHAT, "Me")})
		with self.assertRaisesRegex(frappe.ValidationError, "with whom"):
			self._chat(raw, "boss", {})

	def test_chat_with_everyone_never_reads_a_bcc_and_leaves_the_person_aside(self):
		raw = _thread(
			"Devis",
			"<a1@example.org>",
			to=f"Staff <{STAFF_CHAT}>, ada@example.org",
			cc="Linus <linus@example.org>",
			bcc="hidden@example.org",
		).as_bytes()
		frappe.set_user(STAFF_CHAT)
		people = {
			STAFF_CHAT: (STAFF_CHAT, "Me"),
			"linus@example.org": ("linus@example.org", "Linus"),
		}
		answer, asked, direct = self._chat(raw, "all", people)
		self.assertEqual(asked, [["grace@example.org", STAFF_CHAT, "ada@example.org", "linus@example.org"]])
		# One other person who uses Synk: their direct message
		self.assertEqual(direct, ["linus@example.org"])
		self.assertEqual(answer["route"], "/raven/dm-channel/dm-linus")
		with self.assertRaisesRegex(frappe.ValidationError, "No one else"):
			self._chat(raw, "all", {STAFF_CHAT: (STAFF_CHAT, "Me")})

	def test_a_new_thread_channel_is_asked_first_then_made_private_with_those_of_its_workspace(self):
		raw = _thread(
			"Re: Livraison scie",
			"<b2@example.org>",
			answers=["<a1@example.org>"],
			cc="ada@example.org, linus@example.org",
		).as_bytes()
		people = {
			"grace@example.org": ("grace@example.org", "Grace Hopper"),
			"ada@example.org": ("ada@example.org", "Ada Lovelace"),
			"linus@example.org": ("linus@example.org", "Linus"),
		}
		made, added = [], []

		class Channel:
			name = "synk-livraison-scie-k"

			def __init__(self, doc):
				made.append(doc)

			def insert(self):
				return self

			def add_members(self, members):
				added.append(list(members))

		def get_all(doctype, filters=None, **kwargs):
			# Linus is not in the workspace: Raven would not take him in a channel of it
			if doctype == "Raven Workspace Member":
				return [u for u in filters["user"][1] if u != "linus@example.org"]
			raise AssertionError(doctype)

		with (
			patch.object(share, "_thread_channel", return_value=(None, False)),
			patch.object(share, "_workspace", return_value="Synk"),
			patch.object(share.frappe, "get_all", side_effect=get_all),
			patch.object(share.frappe, "get_doc", side_effect=lambda doc: Channel(doc)),
		):
			asked_first, _asked, _direct = self._chat(raw, "all", people)
			self.assertEqual(made, [])
			self.assertEqual(
				asked_first,
				{"ask": True, "with": ["Grace Hopper", "Ada Lovelace"], "adds": False, "left_out": 1},
			)
			answer, _asked, direct = self._chat(raw, "all", people, confirmed="1")
		self.assertEqual(direct, [])
		self.assertEqual(len(made), 1)
		self.assertEqual(made[0]["type"], "Private")
		self.assertEqual(made[0]["workspace"], "Synk")
		key = share._thread_key(_thread("Livraison scie", "<a1@example.org>"))
		self.assertEqual(made[0]["channel_name"], "livraison-scie-" + key)
		self.assertEqual(added, [["grace@example.org", "ada@example.org"]])
		self.assertEqual(
			answer,
			{
				"channel": "synk-livraison-scie-k",
				"route": "/raven/Synk/synk-livraison-scie-k",
				"with": ["Grace Hopper", "Ada Lovelace"],
				"left_out": 1,
			},
		)

	def test_the_thread_s_channel_held_by_others_gives_the_person_their_own_and_adds_only_who_is_missing(
		self,
	):
		raw = _thread("Devis", "<a1@example.org>", cc="ada@example.org").as_bytes()
		people = {
			"grace@example.org": ("grace@example.org", "Grace Hopper"),
			"ada@example.org": ("ada@example.org", "Ada Lovelace"),
		}
		mine = SimpleNamespace(name="synk-devis-mine", workspace="Synk")
		keys, added = [], []

		def thread_channel(key):
			keys.append(key)
			# The thread's channel is someone else's; the person's own, under their key, is there already
			return (None, True) if len(keys) == 1 else (mine, True)

		def get_all(doctype, filters=None, **kwargs):
			if doctype == "Raven Workspace Member":
				return list(filters["user"][1])
			if doctype == "Raven Channel Member":
				return ["grace@example.org"]
			raise AssertionError(doctype)

		channel = SimpleNamespace(name=mine.name, add_members=lambda members: added.append(list(members)))
		with (
			patch.object(share, "_thread_channel", side_effect=thread_channel),
			patch.object(share.frappe, "get_all", side_effect=get_all),
			patch.object(share.frappe, "get_doc", return_value=channel),
		):
			asked_first, _asked, _direct = self._chat(raw, "all", people)
			self.assertEqual(
				asked_first, {"ask": True, "with": ["Ada Lovelace"], "adds": True, "left_out": 0}
			)
			self.assertEqual(added, [])
			answer, _asked, _direct = self._chat(raw, "all", people, confirmed=1)
		self.assertEqual(keys[1], share._thread_key(_thread("x", "<a1@example.org>"), "Administrator"))
		self.assertEqual(added, [["ada@example.org"]])
		self.assertEqual(answer["route"], "/raven/Synk/synk-devis-mine")
		self.assertEqual(answer["with"], ["Grace Hopper", "Ada Lovelace"])
