# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""MailCraft's JMAP facade (mailcraft_jmap.py, maintenance#1630): who gets in, and what a mailbox looks like through it.

The IMAP server is a fake that keeps its folders in memory, so a flag set, a move, an import and a send can be read
back. The webmail's own functions run unchanged under it (they are what the facade calls).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_jmap
"""

import json
import secrets
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_jmap as jmap

OWNER = "mailcraft_jmap_owner@example.com"
SHARED = "mailcraft_jmap_shared@example.com"
STRANGER = "mailcraft_jmap_stranger@example.com"
PORTAL = "mailcraft_jmap_portal@example.com"
MAILBOX = "mailcraft_jmap_box@webmail.test"
VALIDITY = 7
API = "/api/method/frappe_webmail.mailcraft_jmap.api"
SESSION = "/api/method/frappe_webmail.mailcraft_jmap.session"

HELLO = (
	b"Message-ID: <hello@example.com>\r\n"
	b"From: Ann <ann@example.com>\r\n"
	b"To: " + MAILBOX.encode() + b"\r\n"
	b"Subject: A long subject\r\n that goes on\r\n"
	b"Date: Fri, 16 Oct 2026 09:00:00 +0200\r\n"
	b"\r\n"
	b"Hello, the proof is ready.\r\n"
)


def message(subject, sender=MAILBOX, extra=""):
	return (
		f"Message-ID: <{subject.replace(' ', '.')}@example.com>\r\nFrom: Box <{sender}>\r\nTo: zoe@example.com\r\n"
		f"{extra}Subject: {subject}\r\n\r\nBody\r\n"
	).encode()


class FakeServer:
	"""An IMAP server with folders, flags, UIDs and UIDVALIDITY, answering as imapclient does (UID commands)."""

	def __init__(self, sort=False, uidplus=True, move=False):
		self.uidplus, self.can_move = uidplus, move
		self.folders = {
			"INBOX": {"flags": (b"\\HasNoChildren",), "messages": {}},
			"Sent": {"flags": (b"\\HasNoChildren", b"\\Sent"), "messages": {}},
			"Trash": {"flags": (b"\\HasNoChildren", b"\\Trash"), "messages": {}},
			"Projects": {"flags": (b"\\HasChildren", b"\\Noselect"), "messages": {}},
			"Projects/Film": {"flags": (b"\\HasNoChildren",), "messages": {}},
		}
		self.validity = {name: VALIDITY for name in self.folders}
		self.next_uid = {name: 1 for name in self.folders}
		self.selected = None
		self.can_sort = sort

	def __getattr__(self, name):
		# login, logout, noop…: nothing to do
		return lambda *args, **kwargs: None

	def put(self, folder, raw, flags=(), when=datetime(2026, 10, 16, 9, 0)):
		uid = self.next_uid[folder]
		self.next_uid[folder] += 1
		self.folders[folder]["messages"][uid] = {"raw": raw, "flags": set(flags), "date": when}
		return uid

	def capabilities(self):
		return (
			(b"IMAP4REV1",)
			+ ((b"UIDPLUS",) if self.uidplus else ())
			+ ((b"MOVE",) if self.can_move else ())
			+ ((b"SORT",) if self.can_sort else ())
		)

	def list_folders(self, *args, **kwargs):
		return [(f["flags"], b"/", name) for name, f in self.folders.items()]

	def select_folder(self, name, readonly=False):
		if name not in self.folders or b"\\Noselect" in self.folders[name]["flags"]:
			raise Exception(f"[NONEXISTENT] {name}")
		self.selected = name
		return {b"EXISTS": len(self.folders[name]["messages"]), b"UIDVALIDITY": self.validity[name]}

	def _messages(self):
		return self.folders[self.selected]["messages"]

	def search(self, criteria, charset=None):
		if criteria[:1] == ["HEADER"]:
			wanted = criteria[2].encode()
			return [u for u, m in self._messages().items() if wanted in m["raw"]]
		return [u for u, m in self._messages().items() if b"\\Deleted" not in m["flags"]]

	def sort(self, sort_criteria, criteria):
		alive = [(m["date"], u) for u, m in self._messages().items() if b"\\Deleted" not in m["flags"]]
		return [u for _date, u in sorted(alive)]

	def fetch(self, uids, items):
		out = {}
		for uid in uids:
			m = self._messages().get(uid)
			if not m:
				continue
			got = {}
			for item in items:
				if item == "FLAGS":
					got[b"FLAGS"] = tuple(sorted(m["flags"]))
				elif item == "RFC822.SIZE":
					got[b"RFC822.SIZE"] = len(m["raw"])
				elif item == "INTERNALDATE":
					got[b"INTERNALDATE"] = m["date"]
				elif item == "BODY.PEEK[HEADER]":
					got[b"BODY[HEADER]"] = m["raw"].split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
				elif item == "BODY.PEEK[]":
					got[b"BODY[]"] = m["raw"]
			out[uid] = got
		return out

	def add_flags(self, uids, flags):
		for uid in uids:
			self._messages()[uid]["flags"].update(flags)

	def remove_flags(self, uids, flags):
		for uid in uids:
			self._messages()[uid]["flags"].difference_update(flags)

	def copy(self, uids, folder):
		for uid in uids:
			m = self._messages()[uid]
			self.put(folder, m["raw"], m["flags"] - {b"\\Deleted"}, m["date"])

	def delete_messages(self, uids):
		self.add_flags(uids, [b"\\Deleted"])

	def expunge(self, *args):
		gone = [u for u, m in self._messages().items() if b"\\Deleted" in m["flags"]]
		for uid in gone:
			del self._messages()[uid]

	def uid_expunge(self, uids):
		assert self.uidplus, "UID EXPUNGE needs UIDPLUS"
		for uid in uids:
			if b"\\Deleted" in self._messages().get(uid, {}).get("flags", ()):
				del self._messages()[uid]

	def move(self, uids, folder):
		assert self.can_move, "MOVE needs the MOVE capability"
		for uid in uids:
			m = self._messages().pop(uid)
			self.put(folder, m["raw"], m["flags"], m["date"])

	def append(self, folder, data, flags=(), msg_time=None):
		uid = self.put(folder, data, flags)
		return f"[APPENDUID {self.validity[folder]} {uid}] Append completed".encode()

	def folder_status(self, folder, items):
		messages = self.folders[folder]["messages"].values()
		return {
			b"MESSAGES": len(messages),
			b"UNSEEN": sum(1 for m in messages if b"\\Seen" not in m["flags"]),
			b"UIDVALIDITY": self.validity[folder],
		}


@contextmanager
def served(server):
	with patch("frappe_webmail.webmail_api.IMAPClient") as imap_class:
		imap_class.return_value.__enter__ = MagicMock(return_value=server)
		imap_class.return_value.__exit__ = MagicMock(return_value=False)
		yield server


@contextmanager
def smtp():
	"""The SMTP server, whichever way the mailbox reaches it: every recipient takes the message."""
	server = MagicMock()
	server.sendmail.return_value = {}
	with (
		patch("frappe_webmail.mailcraft_jmap.smtplib.SMTP", return_value=server),
		patch("frappe_webmail.mailcraft_jmap.smtplib.SMTP_SSL", return_value=server),
	):
		yield server


def _user(email, desk=True):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	if desk:
		user.append("roles", {"role": "Blogger"})
	else:
		user.user_type = "Website User"
	user.insert(ignore_permissions=True)


def _client(app_name):
	"""An OAuth client that grants what the mobile sign-in asks for."""
	return (
		frappe.get_doc(
			{
				"doctype": "OAuth Client",
				"app_name": app_name,
				"scopes": "all openid",
				"default_redirect_uri": "http://127.0.0.1/callback",
				"grant_type": "Authorization Code",
				"response_type": "Code",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def eid(folder, uid, validity=VALIDITY):
	return jmap.email_id(folder, validity, uid)


class TestMailCraftJmap(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email, desk in ((OWNER, True), (SHARED, True), (STRANGER, True), (PORTAL, False)):
			_user(email, desk)
		if not frappe.db.exists("Webmail Account", MAILBOX):
			account = frappe.get_doc(
				{
					"doctype": "Webmail Account",
					"email": MAILBOX,
					"user": OWNER,
					"sender_name": "Box",
					"auth_type": "Password",
					"imap_host": "imap.test.local",
					"imap_password": "x",
					"smtp_host": "smtp.test.local",
					"smtp_password": "x",
					"enabled": 1,
				}
			)
			account.append("allowed_users", {"user": SHARED})
			account.insert(ignore_permissions=True)
		cls.aid = jmap.account_id(MAILBOX)
		# The OAuth client Neodesk's bearer tokens come from, as the mobile sign-in mints them.
		cls.client = frappe.db.get_value("OAuth Client", {"app_name": "mailcraft-jmap-test"}) or _client(
			"mailcraft-jmap-test"
		)

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"mailcraft_trial": 1})
		self.trial.start()
		self._as(SHARED)
		for key in (jmap._uploads_key(SHARED), jmap._sends_key()):
			frappe.cache().delete_value(key)

	def tearDown(self):
		self.trial.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.set_user("Administrator")

	def _as(self, user):
		"""The session of `user`, as authenticate() leaves a request that came with its token."""
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = user

	# Who gets in -------------------------------------------------------------------------------------------------

	def _authenticated(self, path, token, cmd=None, alive=True, signed_in=None, form=None):
		"""The person a request to `path` with this token is made as, and the arguments it is left with. `alive` says
		whether the desk session the token is bound to is still there: a yes or no, or a test of the session id."""
		frappe.set_user(signed_in or "Guest")
		frappe.local.flags.mailcraft_jmap_user = None
		args = frappe._dict(form or {})
		if cmd:
			args.cmd = cmd
		with (
			patch.object(frappe.local, "request", SimpleNamespace(path=path), create=True),
			patch.object(frappe.local, "form_dict", args),
			patch("frappe.get_request_header", return_value=f"Bearer {token}"),
			patch.object(jmap, "_session_alive", side_effect=alive if callable(alive) else lambda sid: alive),
		):
			jmap.authenticate()
			kept = dict(frappe.local.form_dict)
		return frappe.session.user, kept

	def test_a_token_lets_its_person_in_on_the_facade_only(self):
		token = jmap.give_token(SHARED)
		self.assertEqual(self._authenticated(API, token)[0], SHARED)
		self.assertEqual(frappe.local.flags.mailcraft_jmap_user, SHARED)
		self.assertEqual(
			self._authenticated("/api/v2/method/frappe_webmail.mailcraft_jmap.session", token)[0], SHARED
		)
		self.assertEqual(
			self._authenticated("/api/method/frappe.client.get_list", token)[0], "Guest", "another address"
		)
		self.assertEqual(self._authenticated(API, token + "x")[0], "Guest", "a token it never gave")
		self.assertEqual(
			self._authenticated(API, token, alive=False)[0], "Guest", "the desk session that asked ended"
		)
		with patch.dict(frappe.local.conf, {"mailcraft_trial": 0}):
			self.assertEqual(self._authenticated(API, token)[0], "Guest", "the trial is off")

	def test_a_cmd_runs_only_the_method_the_address_names(self):
		"""Frappe runs a `cmd` form field whatever the path: a token must not open another method that way."""
		token = jmap.give_token(SHARED)
		self.assertEqual(
			self._authenticated(SESSION, token, cmd="frappe_webmail.mailcraft_jmap.session")[0], SHARED
		)
		for other in (
			"frappe_webmail.mailcraft_jmap.api",
			"frappe.client.get_list",
			"frappe_webmail.webmail_api.get_accounts",
		):
			self.assertEqual(self._authenticated(SESSION, token, cmd=other)[0], "Guest", other)

	def test_the_request_keeps_its_arguments(self):
		"""set_user empties form_dict: without them back, ?account= would be lost and every mailbox refused."""
		token = jmap.give_token(SHARED)
		self.assertEqual(
			self._authenticated(SESSION, token, form={"account": MAILBOX}), (SHARED, {"account": MAILBOX})
		)

	def test_a_signed_in_request_is_left_alone(self):
		token = jmap.give_token(SHARED)
		self.assertEqual(self._authenticated(API, token, signed_in=OWNER)[0], OWNER)
		self.assertIsNone(
			frappe.local.flags.mailcraft_jmap_user, "a desk cookie with a token opens nothing here"
		)

	def test_a_session_cookie_alone_opens_nothing(self):
		"""A desk session (its cookie) without the token: refused, so another site can't drive a signed-in browser."""
		frappe.set_user(OWNER)
		frappe.local.flags.mailcraft_jmap_user = None
		self.assertEqual(jmap.session(MAILBOX).status_code, 403)

	def test_a_token_is_not_kept_in_the_clear(self):
		token = jmap.give_token(SHARED)
		self.assertIsNone(frappe.cache().get_value(token))
		self.assertEqual(frappe.cache().get_value(jmap._token_key(token))["user"], SHARED)

	def test_a_portal_account_is_refused_even_with_a_token(self):
		token = jmap.give_token(PORTAL)
		self.assertEqual(self._authenticated(API, token)[0], "Guest")
		self._as(PORTAL)
		self.assertEqual(jmap.session(MAILBOX).status_code, 403)

	def test_a_mailbox_one_cannot_open_is_refused(self):
		self._as(STRANGER)
		self.assertEqual(jmap.session(MAILBOX).status_code, 403)
		with served(FakeServer()):
			out = self._call("Mailbox/get", {"accountId": self.aid, "ids": None})
		self.assertEqual((out[0], out[1]["type"]), ("error", "forbidden"))

	def test_an_outage_is_not_a_refusal(self):
		"""MailCraft forgets its token on a 401 or a 403: a mail server that is down answers 503."""
		down = jmap.webmail.WebmailConnectionError("down")
		with patch.object(jmap.webmail, "imap_session", side_effect=down):
			self.assertEqual(self._download("B" + eid("INBOX", 1)[1:]).status_code, 503)

	# What a mailbox looks like -----------------------------------------------------------------------------------

	def _post(self, body):
		with patch.object(frappe.local, "request", SimpleNamespace(get_data=lambda: body), create=True):
			return jmap.api()

	def _call(self, name, args):
		answer = self._post(
			json.dumps({"using": [jmap.CORE, jmap.MAIL], "methodCalls": [[name, args, "c0"]]}).encode()
		)
		self.assertEqual(answer.status_code, 200, answer.get_data())
		return json.loads(answer.get_data())["methodResponses"][0]

	def _download(self, blob):
		with patch.object(frappe.local, "form_dict", frappe._dict({"accountId": self.aid, "blobId": blob})):
			return jmap.download()

	def test_the_session_names_one_mailbox_and_the_addresses(self):
		session = json.loads(jmap.session(MAILBOX).get_data())
		self.assertEqual(session["primaryAccounts"][jmap.MAIL], self.aid)
		self.assertEqual(session["capabilities"][jmap.SUBMISSION], {})
		self.assertGreaterEqual(session["capabilities"][jmap.CORE]["maxObjectsInGet"], 300)
		self.assertIn(jmap.MAIL, session["accounts"][self.aid]["accountCapabilities"])
		self.assertTrue(session["apiUrl"].endswith(API))
		self.assertIn("{blobId}", session["downloadUrl"])
		self.assertIn("{accountId}", session["uploadUrl"])

	def test_a_request_out_of_bounds_is_refused(self):
		self.assertEqual(self._post(b"{nope").status_code, 400)
		calls = [["Identity/get", {"accountId": self.aid}, f"c{i}"] for i in range(jmap.MAX_CALLS + 1)]
		self.assertEqual(
			self._post(json.dumps({"using": [jmap.CORE], "methodCalls": calls}).encode()).status_code, 400
		)
		out = self._call("Thread/get", {"accountId": self.aid})
		self.assertEqual((out[0], out[1]["type"]), ("error", "unknownMethod"))

	def test_folders_with_their_roles_parents_and_counts(self):
		server = FakeServer()
		server.put("INBOX", HELLO)
		server.put("INBOX", message("seen"), {b"\\Seen"})
		with served(server):
			name, out, _cid = self._call("Mailbox/get", {"accountId": self.aid, "ids": None})
			_n, refused, _c = self._call(
				"Mailbox/set", {"accountId": self.aid, "create": {"n": {"name": "New"}}}
			)
		self.assertEqual(name, "Mailbox/get")
		boxes = {b["id"]: b for b in out["list"]}
		inbox = boxes[jmap.mailbox_id("INBOX")]
		self.assertEqual((inbox["role"], inbox["totalEmails"], inbox["unreadEmails"]), ("inbox", 2, 1))
		self.assertEqual(boxes[jmap.mailbox_id("Sent")]["role"], "sent")
		self.assertEqual(boxes[jmap.mailbox_id("Trash")]["role"], "trash")
		film = boxes[jmap.mailbox_id("Projects/Film")]
		self.assertEqual((film["name"], film["parentId"]), ("Film", jmap.mailbox_id("Projects")))
		self.assertEqual(
			refused["notCreated"]["n"]["type"], "forbidden", "folders are managed in the webmail"
		)

	def test_the_newest_first_then_their_rows(self):
		server = FakeServer()
		older = server.put("INBOX", message("older"), {b"\\Seen"})
		newer = server.put("INBOX", HELLO, {b"\\Flagged", b"$Forwarded"})
		newest_first = [{"property": "receivedAt", "isAscending": False}]
		inbox = {"inMailbox": jmap.mailbox_id("INBOX")}
		with served(server):
			_n, query, _c = self._call(
				"Email/query", {"accountId": self.aid, "filter": inbox, "limit": 300, "sort": newest_first}
			)
			self.assertEqual(query["ids"], [eid("INBOX", newer), eid("INBOX", older)])
			# The rows MailCraft asks for at each sync.
			rows = ["id", "keywords", "size", "receivedAt", "preview", "hasAttachment", "headers"]
			_n, got, _c = self._call(
				"Email/get", {"accountId": self.aid, "ids": query["ids"][:1], "properties": rows}
			)
			# A folder that holds no messages lists none.
			_n, parent, _c = self._call(
				"Email/query", {"accountId": self.aid, "filter": {"inMailbox": jmap.mailbox_id("Projects")}}
			)
		self.assertEqual(parent["ids"], [])
		row = got["list"][0]
		self.assertEqual(set(row), set(rows))
		self.assertEqual(row["keywords"], {"$flagged": True, "$forwarded": True})
		self.assertEqual(row["size"], len(HELLO))
		self.assertRegex(row["receivedAt"], r"^2026-10-1[56]T\d\d:00:00Z$")
		self.assertIsInstance(row["preview"], str)
		self.assertIs(row["hasAttachment"], False)
		subject = next(h for h in row["headers"] if h["name"] == "Subject")
		self.assertEqual(
			subject["value"],
			" A long subject\r\n that goes on",
			"the Raw form: the leading space and folding kept",
		)

	def test_received_order_where_the_server_sorts(self):
		"""A message moved in late but received early is not the newest: INTERNALDATE decides, not the UID."""
		server = FakeServer(sort=True)
		late = server.put("INBOX", message("received late"), when=datetime(2026, 10, 16, 12, 0))
		early = server.put("INBOX", message("received early, filed last"), when=datetime(2026, 10, 1, 8, 0))
		newest_first = [{"property": "receivedAt", "isAscending": False}]
		with served(server):
			_n, query, _c = self._call(
				"Email/query",
				{
					"accountId": self.aid,
					"filter": {"inMailbox": jmap.mailbox_id("INBOX")},
					"sort": newest_first,
				},
			)
		self.assertEqual(query["ids"], [eid("INBOX", late), eid("INBOX", early)])

	def test_an_id_from_before_its_folder_was_recreated_names_nothing(self):
		server = FakeServer()
		uid = server.put("INBOX", HELLO)
		stale = eid("INBOX", uid, validity=VALIDITY - 1)
		with served(server):
			_n, got, _c = self._call(
				"Email/get", {"accountId": self.aid, "ids": [stale], "properties": ["id", "blobId"]}
			)
			_n, out, _c = self._call("Email/set", {"accountId": self.aid, "update": {}, "destroy": [stale]})
			self.assertEqual(self._download("B" + stale[1:]).status_code, 404)
		self.assertEqual(got["notFound"], [stale])
		self.assertEqual((out["destroyed"], out["notDestroyed"][stale]["type"]), ([], "notFound"))
		self.assertIn(uid, server.folders["INBOX"]["messages"], "nothing deleted")

	def test_ids_that_dont_read_are_refused_cleanly(self):
		folder = jmap._b64("INBOX")
		# Outside JMAP's alphabet: a superscript two, an Arabic-Indic seven (which int() reads); and a zero UIDVALIDITY.
		odd = [
			"E7V" + chr(0xB2) + "Z" + folder,
			"E" + chr(0x667) + "V1Z" + folder,
			"E0V1Z" + folder,
			"nonsense",
		]
		with served(FakeServer()):
			_n, got, _c = self._call("Email/get", {"accountId": self.aid, "ids": odd, "properties": ["id"]})
		self.assertEqual(got["notFound"], odd)
		self.assertEqual(self._download("Bnonsense").status_code, 404)

	def test_a_source_is_saved_not_shown_and_not_marked_read(self):
		server = FakeServer()
		uid = server.put("INBOX", HELLO)
		with served(server):
			_n, got, _c = self._call(
				"Email/get",
				{"accountId": self.aid, "ids": [eid("INBOX", uid)], "properties": ["id", "blobId"]},
			)
			answer = self._download(got["list"][0]["blobId"])
		self.assertEqual(answer.status_code, 200)
		self.assertEqual(answer.get_data(), HELLO)
		self.assertIn("attachment", answer.headers["Content-Disposition"])
		self.assertEqual(answer.headers["Content-Security-Policy"], "sandbox")
		self.assertEqual(answer.headers["X-Content-Type-Options"], "nosniff")
		self.assertNotIn(b"\\Seen", server.folders["INBOX"]["messages"][uid]["flags"])

	def test_keywords_moves_and_destroys(self):
		server = FakeServer()
		a = server.put("INBOX", message("a"))
		b = server.put("INBOX", message("b"))
		c = server.put("INBOX", message("c"))
		# Marked deleted by another mail client, not expunged: it must outlive a destroy here (maintenance#1633).
		foreign = server.put("INBOX", message("foreign"), {b"\\Deleted"})
		ea, eb, ec = (eid("INBOX", u) for u in (a, b, c))
		to_trash = {
			f"mailboxIds/{jmap.mailbox_id('INBOX')}": None,
			f"mailboxIds/{jmap.mailbox_id('Trash')}": True,
		}
		with served(server):
			_n, out, _c = self._call(
				"Email/set",
				{
					"accountId": self.aid,
					"update": {ea: {"keywords/$seen": True, "keywords/$flagged": True}, eb: to_trash},
					"destroy": [ec],
				},
			)
		self.assertEqual(set(out["updated"]), {ea, eb})
		self.assertEqual(out["destroyed"], [ec])
		self.assertEqual(out["notUpdated"], {})
		inbox = server.folders["INBOX"]["messages"]
		self.assertEqual(set(inbox), {a, foreign})
		self.assertTrue({b"\\Seen", b"\\Flagged"} <= inbox[a]["flags"])
		self.assertEqual([m["raw"] for m in server.folders["Trash"]["messages"].values()], [message("b")])

	def test_a_patch_is_all_or_nothing(self):
		server = FakeServer()
		uid = server.put("INBOX", message("a"))
		one = eid("INBOX", uid)
		with served(server):
			bad = {one: {"keywords/$flagged": True, "keywords/a*b": True}}
			_n, out, _c = self._call("Email/set", {"accountId": self.aid, "update": bad, "destroy": []})
			nowhere = {one: {f"mailboxIds/{jmap.mailbox_id('INBOX')}": None}}
			_n, alone, _c = self._call("Email/set", {"accountId": self.aid, "update": nowhere, "destroy": []})
		self.assertEqual(out["notUpdated"][one]["type"], "invalidPatch")
		self.assertNotIn(
			b"\\Flagged",
			server.folders["INBOX"]["messages"][uid]["flags"],
			"the valid keyword wasn't written",
		)
		self.assertEqual(
			alone["notUpdated"][one]["type"], "invalidProperties", "a message stays in one folder"
		)
		self.assertIn(uid, server.folders["INBOX"]["messages"])

	# Filing and sending ------------------------------------------------------------------------------------------

	def _filed(self, raw, blob="Utest"):
		"""Email/import of `raw` into Sent, as MailCraft files a message before sending it."""
		frappe.cache().set_value(jmap._upload_key(blob), {"user": SHARED, "data": raw}, expires_in_sec=60)
		spec = {"blobId": blob, "mailboxIds": {jmap.mailbox_id("Sent"): True}, "keywords": {"$seen": True}}
		return self._call("Email/import", {"accountId": self.aid, "emails": {"m": spec}})[1]

	def _submission(self, jid, sender=MAILBOX, to=("zoe@example.com",)):
		return {
			"identityId": "I" + jmap._b64(MAILBOX),
			"emailId": jid,
			"envelope": {"mailFrom": {"email": sender}, "rcptTo": [{"email": address} for address in to]},
		}

	def _submit(self, spec):
		return self._call("EmailSubmission/set", {"accountId": self.aid, "create": {"s": spec}})[1]

	def test_import_then_submit_sends_the_filed_message_once(self):
		server = FakeServer()
		raw = message("Plans", extra="Bcc: hidden@example.com\r\n")
		with served(server), smtp() as outgoing:
			jid = self._filed(raw)["created"]["m"]["id"]
			again = self._call(
				"Email/import",
				{
					"accountId": self.aid,
					"emails": {"m": {"blobId": "Utest", "mailboxIds": {jmap.mailbox_id("Sent"): True}}},
				},
			)[1]
			self.assertEqual(again["notCreated"]["m"]["type"], "blobNotFound", "an upload is filed once")
			sent = self._submit(self._submission(jid, to=("zoe@example.com", "hidden@example.com")))
			self.assertIn("s", sent["created"], sent)
			args = outgoing.sendmail.call_args.args
			self.assertEqual(args[:2], (MAILBOX, ["zoe@example.com", "hidden@example.com"]))
			self.assertNotIn(b"Bcc:", args[2], "Bcc is the envelope's, never a header")
			# The same message can't go out twice, nor one this person didn't just file here.
			self.assertEqual(self._submit(self._submission(jid))["notCreated"]["s"]["type"], "invalidEmail")
			old = server.put("Sent", message("old sent mail"))
			self.assertEqual(
				self._submit(self._submission(eid("Sent", old)))["notCreated"]["s"]["type"], "invalidEmail"
			)
		self.assertEqual(outgoing.sendmail.call_count, 1)
		copies = [m for m in server.folders["Sent"]["messages"].values() if m["raw"] == raw]
		self.assertEqual(len(copies), 1, "the copy MailCraft filed, and no second one from sending")
		self.assertIn(b"\\Seen", copies[0]["flags"])

	def test_sending_as_someone_else_is_refused(self):
		server = FakeServer()
		with served(server), smtp() as outgoing:
			jid = self._filed(message("ok"))["created"]["m"]["id"]
			self.assertEqual(
				self._submit(self._submission(jid, sender="boss@example.com"))["notCreated"]["s"]["type"],
				"forbiddenFrom",
			)
			other_identity = dict(self._submission(jid), identityId="I" + jmap._b64("boss@example.com"))
			self.assertEqual(self._submit(other_identity)["notCreated"]["s"]["type"], "forbiddenFrom")
			forged = (
				message("x", sender="boss@example.com"),
				message("y", extra="From: Boss <boss@example.com>\r\n"),
			)
			for n, raw in enumerate(forged):
				jid = self._filed(raw, blob=f"Uforged{n}")["created"]["m"]["id"]
				self.assertEqual(
					self._submit(self._submission(jid))["notCreated"]["s"]["type"], "forbiddenFrom", raw
				)
		outgoing.sendmail.assert_not_called()

	def test_sending_is_bounded(self):
		server = FakeServer()
		with served(server), smtp() as outgoing:
			jid = self._filed(message("ok"))["created"]["m"]["id"]
			self.assertEqual(
				self._submit(self._submission(jid, to=("not an address",)))["notCreated"]["s"]["type"],
				"invalidRecipients",
			)
			self.assertEqual(
				self._submit(self._submission(jid, to=()))["notCreated"]["s"]["type"], "noRecipients"
			)
			many = [f"r{i}@example.com" for i in range(jmap.MAX_RECIPIENTS + 1)]
			self.assertEqual(
				self._submit(self._submission(jid, to=many))["notCreated"]["s"]["type"], "tooManyRecipients"
			)
			frappe.cache().set_value(jmap._sends_key(), jmap.MAX_SENDS, expires_in_sec=60)
			self.assertEqual(self._submit(self._submission(jid))["notCreated"]["s"]["type"], "rateLimit")
		outgoing.sendmail.assert_not_called()

	def test_what_goes_to_smtp_has_crlf_lines_and_no_bcc(self):
		sent = jmap._as_sent(b"From: a@b.c\nBcc: x@y.z,\n w@v.u\nSubject: s\r\rBody\nline\r\n")
		self.assertEqual(sent, b"From: a@b.c\r\nSubject: s\r\n\r\nBody\r\nline\r\n")

	# For Nora: the key of a message, never its text -------------------------------------------------------------

	def test_the_place_nora_reads_is_checked_first(self):
		"""quick_reply gets a message's id: its folder and UID, from a mailbox the person may open, still the same
		message (the UIDVALIDITY the id carries)."""
		server = FakeServer()
		uid = server.put("INBOX", HELLO)
		with served(server):
			self.assertEqual(jmap.message_place(MAILBOX, eid("INBOX", uid)), ("INBOX", uid))
			for wrong in (
				eid("INBOX", uid, validity=VALIDITY - 1),
				"B" + eid("INBOX", uid)[1:],
				"nonsense",
				None,
			):
				with self.assertRaises(frappe.ValidationError, msg=wrong):
					jmap.message_place(MAILBOX, wrong)
			self._as(STRANGER)
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
				jmap.message_place(MAILBOX, eid("INBOX", uid))
		self.assertNotIn(b"\\Seen", server.folders["INBOX"]["messages"][uid]["flags"], "nothing read here")

	def test_uploads_belong_to_their_person_and_are_capped(self):
		def upload(data):
			with (
				patch.object(frappe.local, "form_dict", frappe._dict({"accountId": self.aid})),
				patch.object(frappe.local, "request", SimpleNamespace(get_data=lambda: data), create=True),
			):
				return jmap.upload()

		first = upload(b"x" * 10)
		self.assertEqual(first.status_code, 201)
		blob = json.loads(first.get_data())["blobId"]
		self.assertEqual(jmap._upload_data(blob), b"x" * 10)
		for _i in range(jmap.MAX_UPLOADS - 1):
			self.assertEqual(upload(b"y").status_code, 201)
		self.assertEqual(upload(b"z").status_code, 429, "at most MAX_UPLOADS waiting at once")
		self._as(OWNER)
		self.assertIsNone(jmap._upload_data(blob), "another person's upload is not found")

	# The page that hands MailCraft the mailboxes -----------------------------------------------------------------

	def test_the_page_gives_the_mailboxes_and_a_token_that_works(self):
		from frappe_webmail.www import neomail

		context = frappe._dict()
		with (
			patch.object(frappe.local, "form_dict", frappe._dict()),
			patch.object(neomail, "nora_installed", return_value=True),
		):
			neomail.get_context(context)
		self.assertTrue(context.build_url.endswith("index.html?nora"))
		self.assertNotIn("<", context.host_json)
		box = next(a for a in json.loads(context.host_json)["accounts"] if a["email"] == MAILBOX)
		self.assertEqual(box["scheme"], "bearer")
		self.assertTrue(
			box["session"].endswith(
				"frappe_webmail.mailcraft_jmap.session?account=" + MAILBOX.replace("@", "%40")
			)
		)
		self.assertEqual(self._authenticated(SESSION, box["secret"])[0], SHARED)
		self._as(SHARED)
		sample = frappe._dict()
		with (
			patch.object(frappe.local, "form_dict", frappe._dict({"sample": ""})),
			patch.object(neomail, "nora_installed", return_value=True),
		):
			neomail.get_context(sample)
		self.assertTrue(sample.build_url.endswith("?sample&nora"), "?sample opens the sample mailbox")
		self.assertEqual(
			json.loads(sample.host_json), {"accounts": [], "language": context.lang, "product": "NeoMail"}
		)
		self.assertEqual(
			json.loads(context.host_json)["language"], frappe.local.lang or "en", "the desk's language"
		)

	# Neodesk's hand-over, and the page's renewal ------------------------------------------------------------------

	def _bearer(self, user=SHARED, status="Active", seconds=3600, client=None, scopes="all openid"):
		"""An OAuth bearer token as Neodesk signs in with (its name is the token)."""
		name = "mailcraft-jmap-" + secrets.token_hex(16)
		frappe.get_doc(
			{
				"doctype": "OAuth Bearer Token",
				"access_token": name,
				"client": client or self.client,
				"user": user,
				"status": status,
				"scopes": scopes,
				"expires_in": seconds,
				"expiration_time": frappe.utils.add_to_date(None, seconds=seconds),
			}
		).insert(ignore_permissions=True, ignore_links=True)
		return name

	def _hand_over(self, bearer, user=SHARED):
		"""hand_over, for a request Frappe signed in as `user` with that bearer token in Authorization."""
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = None
		with patch("frappe.get_request_header", return_value=f"Bearer {bearer}" if bearer else None):
			return jmap.hand_over()

	def test_neodesk_gets_the_mailboxes_for_its_bearer_and_they_live_with_it(self):
		bearer = self._bearer()
		given = self._hand_over(bearer)
		box = next(a for a in given["accounts"] if a["email"] == MAILBOX)
		self.assertEqual((given["product"], box["scheme"]), ("NeoMail", "bearer"))
		self.assertTrue(given["language"])
		self.assertEqual(
			given["nora"], "nora" in frappe.get_installed_apps(), "Nora only where the instance has her"
		)
		self.assertEqual(
			self._authenticated(SESSION, box["secret"], alive=False)[0],
			SHARED,
			"bound to the bearer token, not to a desk session",
		)
		frappe.db.set_value("OAuth Bearer Token", bearer, "status", "Revoked")
		self.assertEqual(
			self._authenticated(SESSION, box["secret"])[0], "Guest", "signed out of Neodesk: dead"
		)

	def test_an_expired_bearer_ends_its_tokens(self):
		bearer = self._bearer()
		secret = self._hand_over(bearer)["accounts"][0]["secret"]
		frappe.db.set_value(
			"OAuth Bearer Token", bearer, "expiration_time", frappe.utils.add_to_date(None, seconds=-5)
		)
		self.assertEqual(self._authenticated(SESSION, secret)[0], "Guest")

	def test_the_hand_over_wants_the_person_s_own_live_bearer(self):
		for bearer, user, why in (
			(None, SHARED, "a desk cookie alone"),
			("not-a-token", SHARED, "a token Frappe never gave"),
			(self._bearer(user=OWNER), SHARED, "another person's token"),
			(self._bearer(status="Revoked"), SHARED, "a revoked token"),
			(self._bearer(seconds=-5), SHARED, "an expired token"),
			(self._bearer(user=PORTAL), PORTAL, "a portal account"),
		):
			with self.assertRaises(frappe.PermissionError, msg=why):
				self._hand_over(bearer, user)
		with (
			patch.dict(frappe.local.conf, {"mailcraft_trial": 0}),
			self.assertRaises(frappe.PageDoesNotExistError),
		):
			self._hand_over(self._bearer())

	def test_a_bearer_counts_only_as_frappe_would_take_it(self):
		"""Its OAuth client still there and granting its scopes, and an expiry: Frappe refuses a bearer token otherwise."""
		gone = _client("mailcraft-jmap-gone")
		orphan = self._bearer(client=gone)
		secret = self._hand_over(orphan)["accounts"][0]["secret"]
		self.assertEqual(self._authenticated(SESSION, secret)[0], SHARED)
		# Removed from the table, as Frappe's own check would then find it (the desk refuses it while tokens link to it).
		frappe.db.delete("OAuth Client", gone)
		self.assertEqual(self._authenticated(SESSION, secret)[0], "Guest", "its client was deleted")
		with self.assertRaises(frappe.PermissionError):
			self._hand_over(orphan)
		with self.assertRaises(frappe.PermissionError, msg="a scope its client does not grant"):
			self._hand_over(self._bearer(scopes="all openid fileshare"))
		endless = self._bearer()
		frappe.db.set_value("OAuth Bearer Token", endless, "expiration_time", None)
		with self.assertRaises(frappe.PermissionError, msg="no expiry"):
			self._hand_over(endless)

	def test_the_page_renews_its_tokens_with_its_own_session_only(self):
		frappe.set_user(SHARED)
		page = frappe.session.sid
		with patch("frappe.get_request_header", return_value=None):
			fresh = jmap.renew()
		box = next(a for a in fresh["accounts"] if a["email"] == MAILBOX)
		self.assertEqual(
			self._authenticated(SESSION, box["secret"], alive=lambda sid: sid == page)[0],
			SHARED,
			"bound to the page's own desk session",
		)
		self.assertEqual(
			self._authenticated(SESSION, box["secret"], alive=False)[0], "Guest", "which has ended"
		)
		frappe.set_user(SHARED)
		with (
			patch("frappe.get_request_header", return_value="Bearer something"),
			self.assertRaises(frappe.PermissionError),
		):
			jmap.renew()
		with (
			patch.dict(frappe.local.conf, {"mailcraft_trial": 0}),
			patch("frappe.get_request_header", return_value=None),
			self.assertRaises(frappe.PageDoesNotExistError),
		):
			jmap.renew()
		frappe.set_user(PORTAL)
		with patch("frappe.get_request_header", return_value=None), self.assertRaises(frappe.PermissionError):
			jmap.renew()

	def test_the_page_and_the_mail_are_not_kept_by_a_cache(self):
		for path in (
			"/neomail",
			"/mailcraft",
			SESSION,
			"/api/method/frappe_webmail.mailcraft_jmap.download",
			"/api/method/frappe_webmail.mailcraft_jmap.hand_over",
			"/api/v2/method/frappe_webmail.mailcraft_jmap.renew",
		):
			response = SimpleNamespace(headers={})
			jmap.no_store(response=response, request=SimpleNamespace(path=path))
			self.assertEqual(response.headers["Cache-Control"], "no-store", path)
		other = SimpleNamespace(headers={})
		jmap.no_store(response=other, request=SimpleNamespace(path="/app/webmail"))
		self.assertEqual(other.headers, {})
