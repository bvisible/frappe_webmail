# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""MailCraft's JMAP facade (mailcraft_jmap.py, maintenance#1630): who gets in, and what a mailbox looks like through it.

The IMAP server is a fake that keeps its folders in memory, so a flag set, a move, an import and a send can be read
back. The webmail's own functions run unchanged under it (they are what the facade calls). The mail server is a fake
on the loopback that answers each step of a send as a test sets it, so that smtplib meets what a real one says.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_jmap
"""

import json
import secrets
import smtplib
import socketserver
import threading
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint
from werkzeug.wrappers import Response

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

	def __init__(self, sort=False, uidplus=True, move=False, quota=None, uidnext=True):
		self.uidplus, self.can_move, self.says_uidnext = uidplus, move, uidnext
		# (usage, limit) in kilobytes, as IMAP QUOTA counts them (RFC 2087); None: the server keeps no quota.
		self.quota = quota
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
			+ ((b"QUOTA",) if self.quota else ())
		)

	def get_quota_root(self, mailbox):
		usage, limit = self.quota
		return None, [SimpleNamespace(quota_root="", resource=b"STORAGE", usage=usage, limit=limit)]

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
		if criteria[:1] == ["UID"]:
			# The messages the set names that are there, marked deleted or not, as a server answers UID SEARCH
			return [u for u in self._uids(criteria[1]) if u in self._messages()]
		return [u for u, m in self._messages().items() if b"\\Deleted" not in m["flags"]]

	def _uids(self, messages):
		"""UIDs as a list, or a set as IMAP writes one (`3,5:7`, `4:*`). `n:*` past the last UID names the last one, as
		IMAP says (`*` is the highest UID there is)."""
		if not isinstance(messages, str):
			return list(messages)
		highest = max(self._messages(), default=0)
		out = []
		for part in messages.split(","):
			low, _sep, high = part.partition(":")
			low = highest if low == "*" else int(low)
			high = low if not _sep else (highest if high == "*" else int(high))
			out.extend(range(min(low, high), max(low, high) + 1))
		return out

	def sort(self, sort_criteria, criteria):
		alive = [(m["date"], u) for u, m in self._messages().items() if b"\\Deleted" not in m["flags"]]
		return [u for _date, u in sorted(alive)]

	def fetch(self, uids, items):
		out = {}
		for uid in self._uids(uids):
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
				elif item == "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]":
					head = m["raw"].split(b"\r\n\r\n", 1)[0].split(b"\r\n")
					found = [line for line in head if line.lower().startswith(b"message-id:")]
					got[b"BODY[HEADER.FIELDS (MESSAGE-ID)]"] = (
						b"".join(line + b"\r\n" for line in found) + b"\r\n"
					)
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
		status = {
			b"MESSAGES": len(messages),
			b"UNSEEN": sum(1 for m in messages if b"\\Seen" not in m["flags"]),
			b"UIDVALIDITY": self.validity[folder],
		}
		if self.says_uidnext:
			status[b"UIDNEXT"] = self.next_uid[folder]
		return status


@contextmanager
def served(server):
	with patch("frappe_webmail.webmail_api.IMAPClient") as imap_class:
		imap_class.return_value.__enter__ = MagicMock(return_value=server)
		imap_class.return_value.__exit__ = MagicMock(return_value=False)
		yield server


REAL_SMTP = smtplib.SMTP
# What the fake mail server answers to each step when a test doesn't say otherwise: everything goes through.
SMTP_STEPS = {"greeting": 220, "auth": 235, "mail": 250, "rcpt": 250, "data": 354, "end": 250, "quit": 221}


class FakeSmtp(socketserver.ThreadingTCPServer):
	"""A mail server on the loopback that answers each step as a test sets it (`answers`): a code, or "drop" to end the
	connection without one. What it took, (MAIL FROM, RCPT TO, data), is in `taken`."""

	daemon_threads = True
	allow_reuse_address = True

	def __init__(self):
		self.taken = []
		self.set()
		super().__init__(("127.0.0.1", 0), _SmtpSession)

	def set(self, unreachable=False, refused=None, **answers):
		"""Every step goes through but those `answers` names; `refused`: RCPT answers by address."""
		self.unreachable, self.refused, self.answers = unreachable, refused or {}, {**SMTP_STEPS, **answers}

	def connect(self, host, port, timeout=None, **_options):
		"""What smtplib.SMTP and SMTP_SSL give the facade: a connection to this server (its STARTTLS taken as done)."""
		if self.unreachable:
			raise ConnectionRefusedError(111, "Connection refused")
		connection = REAL_SMTP("127.0.0.1", self.server_address[1], timeout=5)
		connection.starttls = lambda **_k: (220, b"ready")
		return connection


class _SmtpSession(socketserver.StreamRequestHandler):
	def say(self, code):
		if code == "drop":
			return False
		self.wfile.write(f"{code} fake\r\n".encode())
		return True

	def handle(self):
		fake = self.server
		if not self.say(fake.answers["greeting"]):
			return
		sender, recipients = None, []
		while line := self.rfile.readline(4096):
			verb = line[:4].upper()
			if verb in (b"EHLO", b"HELO"):
				self.wfile.write(b"250-fake\r\n250-SIZE 10000000\r\n250 AUTH PLAIN\r\n")
			elif verb in (b"AUTH", b"MAIL", b"QUIT"):
				if verb == b"MAIL":
					sender = line.split(b"<", 1)[1].split(b">", 1)[0].decode()
				if (
					not self.say(fake.answers[{b"AUTH": "auth", b"MAIL": "mail", b"QUIT": "quit"}[verb]])
					or verb == b"QUIT"
				):
					return
			elif verb == b"RCPT":
				address = line.split(b"<", 1)[1].split(b">", 1)[0].decode()
				code = fake.refused.get(address, fake.answers["rcpt"])
				if code in (250, 251):
					recipients.append(address)
				if not self.say(code):
					return
			elif verb == b"DATA":
				if not self.say(fake.answers["data"]):
					return
				if fake.answers["data"] != 354:
					continue
				lines = []
				while (chunk := self.rfile.readline(65536)) not in (b".\r\n", b""):
					lines.append(chunk[1:] if chunk.startswith(b"..") else chunk)
				if fake.answers["end"] == 250:
					fake.taken.append((sender, recipients, b"".join(lines)))
				if not self.say(fake.answers["end"]):
					return
				sender, recipients = None, []
			else:
				self.say(250)


@contextmanager
def smtp():
	"""A mail server on the loopback in place of the mailbox's, whichever way the mailbox reaches it: unless a test sets
	it otherwise (`set`), every step goes through and every recipient takes the message."""
	fake = FakeSmtp()
	threading.Thread(target=fake.serve_forever, daemon=True).start()
	try:
		with (
			patch("frappe_webmail.mailcraft_jmap.smtplib.SMTP", side_effect=fake.connect),
			patch("frappe_webmail.mailcraft_jmap.smtplib.SMTP_SSL", side_effect=fake.connect),
		):
			yield fake
	finally:
		fake.shutdown()
		fake.server_close()


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


def _page_headers(csrf="session", authorization=None):
	"""What get_request_header answers for a request of a page of the instance: the session's CSRF token in
	X-Frappe-CSRF-Token (or the one given, None for none), and Authorization only when given."""

	def header(key, default=None):
		if key == "X-Frappe-CSRF-Token":
			return frappe.sessions.get_csrf_token() if csrf == "session" else csrf
		if key == "Authorization":
			return authorization
		return default

	return header


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
		self.trial = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
		self.trial.start()
		self._as(SHARED)
		troubles = [f"mailcraft_jmap_smtp_trouble:{MAILBOX}:{kind}" for kind in ("down", "doubt")]
		for key in (jmap._uploads_key(SHARED), jmap._sends_key(), *troubles):
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
		with patch.dict(frappe.local.conf, {"neomail_disabled": 1}):
			self.assertEqual(self._authenticated(API, token)[0], "Guest", "NeoMail is off")

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

	def test_the_session_offers_the_quota(self):
		session = json.loads(jmap.session(MAILBOX).get_data())
		self.assertEqual(session["capabilities"][jmap.QUOTA], {})
		self.assertIn(jmap.QUOTA, session["accounts"][self.aid]["accountCapabilities"])
		self.assertEqual(session["primaryAccounts"][jmap.QUOTA], self.aid)

	def test_the_quota_is_the_storage_the_webmail_reads(self):
		"""16 MB used out of 20 GB, as the webmail's storage bar shows it: octets for NeoMail (RFC 9425)."""
		frappe.cache().delete_value(f"mailcraft_jmap:quota:{MAILBOX}")
		with served(FakeServer(quota=(16 * 1024, 20 * 1024 * 1024))):
			_n, every, _c = self._call("Quota/get", {"accountId": self.aid, "ids": None})
			_n, some, _c = self._call("Quota/get", {"accountId": self.aid, "ids": ["q", "nope"]})
		(quota,) = every["list"]
		self.assertEqual(
			(quota["resourceType"], quota["scope"], quota["types"]), ("octets", "account", ["Mail"])
		)
		self.assertEqual((quota["used"], quota["hardLimit"]), (16 * 1024 * 1024, 20 * 1024**3))
		self.assertEqual([q["id"] for q in some["list"]], ["q"])
		self.assertEqual(some["notFound"], ["nope"])

	def test_a_server_without_quota_gives_none_and_is_not_asked_again_at_once(self):
		frappe.cache().delete_value(f"mailcraft_jmap:quota:{MAILBOX}")
		with (
			served(FakeServer()),
			patch.object(jmap.webmail, "get_quota", wraps=jmap.webmail.get_quota) as read,
		):
			_n, first, _c = self._call("Quota/get", {"accountId": self.aid, "ids": None})
			_n, again, _c = self._call("Quota/get", {"accountId": self.aid, "ids": None})
		self.assertEqual((first["list"], again["list"]), ([], []))
		self.assertEqual(read.call_count, 1, "read once, then kept for a few minutes")

	def test_the_quota_of_a_mailbox_one_cannot_open_is_refused(self):
		self._as(STRANGER)
		with served(FakeServer(quota=(1, 2))):
			out = self._call("Quota/get", {"accountId": self.aid, "ids": None})
		self.assertEqual((out[0], out[1]["type"]), ("error", "forbidden"))

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

	def test_the_roles_come_from_the_server_s_marks_then_from_usual_names(self):
		"""RFC 8621 roles: a special-use attribute first (RFC 6154), then a name mail programs give a folder, in the
		languages of the people served, at the top or under INBOX; one folder to a role, read from the listing Mailbox/get
		makes (no second IMAP listing)."""
		server = FakeServer()
		bare = (b"\\HasNoChildren",)
		server.folders = {
			name: {"flags": flags, "messages": {}}
			for name, flags in (
				("INBOX", bare),
				("Archive", bare),
				("Archives", bare),
				("Gesendete Objekte", bare),
				("Sent Items", (*bare, b"\\Sent")),
				("Entw\u00fcrfe", bare),
				("INBOX/Papierkorb", bare),
				("Projects", (b"\\HasChildren",)),
				("Projects/Spam", bare),
				("Junk-E-Mail", bare),
			)
		}
		server.validity = {name: VALIDITY for name in server.folders}
		server.next_uid = {name: 1 for name in server.folders}
		with served(server), patch("frappe_webmail.webmail_api.get_folder_mapping", side_effect=AssertionError):
			_n, out, _c = self._call("Mailbox/get", {"accountId": self.aid, "ids": None})
		roles = {b["id"]: b["role"] for b in out["list"]}
		expected = {
			"INBOX": "inbox",
			# Two folders a name gives the archive to: the first listed takes it, the other stays a folder.
			"Archive": "archive",
			"Archives": None,
			# The server's own mark wins over a name, whichever comes first.
			"Gesendete Objekte": None,
			"Sent Items": "sent",
			"Entw\u00fcrfe": "drafts",
			"INBOX/Papierkorb": "trash",
			# A project's own "Spam" is not the mailbox's.
			"Projects/Spam": None,
			"Junk-E-Mail": "junk",
		}
		self.assertEqual({name: roles[jmap.mailbox_id(name)] for name in expected}, expected)

	def test_the_account_s_own_folder_settings_come_first(self):
		frappe.db.set_value("Webmail Account", MAILBOX, "archive_folder", "Archives")
		self.addCleanup(frappe.db.set_value, "Webmail Account", MAILBOX, "archive_folder", "")
		server = FakeServer()
		for name in ("Archive", "Archives"):
			server.folders[name] = {"flags": (b"\\HasNoChildren",), "messages": {}}
			server.validity[name], server.next_uid[name] = VALIDITY, 1
		with served(server):
			_n, out, _c = self._call("Mailbox/get", {"accountId": self.aid, "ids": None})
		roles = {b["id"]: b["role"] for b in out["list"]}
		self.assertEqual((roles[jmap.mailbox_id("Archives")], roles[jmap.mailbox_id("Archive")]), ("archive", None))

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
		self.assertIsNone(out["updated"][ea], "marks give no new id")
		self.assertEqual(out["updated"][eb], {"id": eid("Trash", 1)}, "a move says where the message is now")
		self.assertEqual(out["destroyed"], [ec])
		self.assertEqual(out["notUpdated"], {})
		inbox = server.folders["INBOX"]["messages"]
		self.assertEqual(set(inbox), {a, foreign})
		self.assertTrue({b"\\Seen", b"\\Flagged"} <= inbox[a]["flags"])
		self.assertEqual([m["raw"] for m in server.folders["Trash"]["messages"].values()], [message("b")])

	def _to(self, folder, source="INBOX"):
		"""The patch of a move from `source` to `folder`."""
		return {f"mailboxIds/{jmap.mailbox_id(source)}": None, f"mailboxIds/{jmap.mailbox_id(folder)}": True}

	def test_a_moved_message_comes_back_with_its_new_id(self):
		"""An id names a place: the answer to a move says the id the message has where it went, so that MailCraft keeps it
		as the same message, whichever way the server moves (MOVE, or a copy and an expunge)."""
		for can_move in (True, False):
			server = FakeServer(move=can_move)
			# A message of the same Message-ID already there: the one that arrives is told from it
			server.put("Trash", message("b"))
			b = server.put("INBOX", message("b"))
			eb = eid("INBOX", b)
			with served(server):
				out = self._call("Email/set", {"accountId": self.aid, "update": {eb: self._to("Trash")}})[1]
			landed = max(server.folders["Trash"]["messages"])
			self.assertEqual(out["updated"], {eb: {"id": eid("Trash", landed)}}, can_move)
			self.assertNotIn(b, server.folders["INBOX"]["messages"])

	def test_a_move_whose_new_place_cannot_be_told_says_no_id(self):
		# Two messages of one Message-ID moved together: both moved, neither id said (which is which can't be told)
		server = FakeServer(move=True)
		twins = [eid("INBOX", server.put("INBOX", message("twin"))) for _n in range(2)]
		with served(server):
			out = self._call(
				"Email/set", {"accountId": self.aid, "update": {i: self._to("Trash") for i in twins}}
			)[1]
		self.assertEqual(out["updated"], dict.fromkeys(twins))
		self.assertEqual(len(server.folders["Trash"]["messages"]), 2)
		# A server that gives no UIDNEXT: moved, no id said
		server = FakeServer(move=True, uidnext=False)
		one = eid("INBOX", server.put("INBOX", message("c")))
		with served(server):
			out = self._call("Email/set", {"accountId": self.aid, "update": {one: self._to("Trash")}})[1]
		self.assertEqual(out["updated"], {one: None})
		self.assertEqual(len(server.folders["Trash"]["messages"]), 1)

	def test_a_message_no_longer_there_is_not_found(self):
		"""Another client deleted it: the server would say nothing of a STORE, a MOVE or an expunge of its UID, so it is not
		answered as done."""
		server = FakeServer(move=True)
		ea, eb, ec = (eid("INBOX", server.put("INBOX", message(name))) for name in ("a", "b", "c"))
		server.folders["INBOX"]["messages"].clear()
		with served(server):
			out = self._call(
				"Email/set",
				{
					"accountId": self.aid,
					"update": {ea: {"keywords/$seen": True}, eb: self._to("Trash")},
					"destroy": [ec],
				},
			)[1]
		self.assertEqual(out["updated"], {})
		self.assertEqual(
			{k: v["type"] for k, v in out["notUpdated"].items()}, {ea: "notFound", eb: "notFound"}
		)
		self.assertEqual((out["destroyed"], out["notDestroyed"]), ([], {ec: {"type": "notFound"}}))
		self.assertEqual(server.folders["Trash"]["messages"], {})

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
			sender, recipients, data = outgoing.taken[0]
			self.assertEqual((sender, recipients), (MAILBOX, ["zoe@example.com", "hidden@example.com"]))
			self.assertNotIn(b"Bcc:", data, "Bcc is the envelope's, never a header")
			self.assertIn(b"Subject: Plans", data)
			# The same message can't go out twice, nor one this person didn't just file here.
			self.assertEqual(self._submit(self._submission(jid))["notCreated"]["s"]["type"], "invalidEmail")
			old = server.put("Sent", message("old sent mail"))
			self.assertEqual(
				self._submit(self._submission(eid("Sent", old)))["notCreated"]["s"]["type"], "invalidEmail"
			)
		self.assertEqual(len(outgoing.taken), 1)
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
		self.assertEqual(outgoing.taken, [])

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
		self.assertEqual(outgoing.taken, [])

	def _sent_through(self, to=("zoe@example.com",)):
		"""A message filed and submitted: its id, and the call's whole answer (its name, "error" for an error of the
		call, and what it says)."""
		jid = self._filed(message("Plans"), blob="U" + secrets.token_hex(4))["created"]["m"]["id"]
		create = {"s": self._submission(jid, to=to)}
		name, answer, _c = self._call("EmailSubmission/set", {"accountId": self.aid, "create": create})
		return jid, name, answer

	def test_a_mail_server_that_cannot_take_it_now_leaves_the_message_waiting(self):
		"""Nothing went: the call says the server can't serve it just now, which MailCraft reads as a message to keep for
		its next try (an error of the whole call that made no change), never as one that may have gone."""
		server = FakeServer()
		cases = {
			"unreachable": {"unreachable": True},
			"busy at the greeting": {"greeting": 421},
			"sign-in refused": {"auth": 535},
			"lost at the sign-in": {"auth": "drop"},
			"sender, not now": {"mail": 451},
			"lost before the sender": {"mail": "drop"},
			"recipients, not now": {"rcpt": 450},
			"data, not now": {"data": 451},
			"end of the data, not now": {"end": 452},
		}
		with served(server), smtp() as outgoing, patch.object(frappe, "log_error") as logged:
			for case, answers in cases.items():
				outgoing.set(**answers)
				jid, name, answer = self._sent_through()
				self.assertEqual(
					(name, answer.get("type")), ("error", "serverUnavailable"), f"{case}: {answer}"
				)
				# It can be sent once the server is back, and nothing counted against the limit.
				self.assertTrue(frappe.cache().get_value(jmap._filed_key(jid)), case)
			self.assertEqual(outgoing.taken, [])
			self.assertFalse(frappe.cache().get_value(jmap._sends_key()))
			# One line in the Error Log for the mailbox, not one per try.
			self.assertEqual(logged.call_count, 1, logged.call_args_list)
			outgoing.set()
			_jid, name, answer = self._sent_through()
			self.assertIn("s", answer["created"], answer)
		self.assertEqual(len(outgoing.taken), 1)

	def test_a_mail_server_that_will_not_take_it_says_why(self):
		"""Nothing went either: the standard's refusal, which MailCraft holds the message with, the reason in plain words."""
		server = FakeServer()
		cases = [
			({"mail": 550}, "forbiddenMailFrom"),
			({"mail": 552}, "tooLarge"),
			({"rcpt": 550}, "invalidRecipients"),
			({"data": 554}, "forbiddenToSend"),
			({"end": 554}, "invalidEmail"),
			({"end": 552}, "tooLarge"),
		]
		with served(server), smtp() as outgoing:
			for answers, kind in cases:
				outgoing.set(**answers)
				jid, name, answer = self._sent_through()
				self.assertEqual(name, "EmailSubmission/set", answers)
				self.assertEqual(answer["notCreated"]["s"]["type"], kind, answers)
				self.assertTrue(frappe.cache().get_value(jmap._filed_key(jid)), answers)
			# The recipients it turned down are named, as the standard has it; a "not now" for one of them waits.
			outgoing.set(rcpt=550)
			_jid, _name, answer = self._sent_through(to=("zoe@example.com", "bob@example.com"))
			self.assertEqual(
				answer["notCreated"]["s"]["invalidRecipients"], ["zoe@example.com", "bob@example.com"]
			)
			outgoing.set(rcpt=550, refused={"bob@example.com": 450})
			_jid, name, _answer = self._sent_through(to=("zoe@example.com", "bob@example.com"))
			self.assertEqual(name, "error")
		self.assertEqual(outgoing.taken, [])

	def test_a_message_the_server_took_is_sent_whatever_comes_after(self):
		server = FakeServer()
		with served(server), smtp() as outgoing, patch.object(frappe, "log_error") as logged:
			outgoing.set(quit="drop")
			jid, _name, answer = self._sent_through()
			self.assertIn("s", answer["created"], answer)
			self.assertFalse(frappe.cache().get_value(jmap._filed_key(jid)), "sent once, never again")
			# One recipient turned down, the other took it: it went.
			outgoing.set(refused={"bob@example.com": 550})
			_jid, _name, answer = self._sent_through(to=("zoe@example.com", "bob@example.com"))
			self.assertIn("s", answer["created"], answer)
		self.assertEqual([recipients for _s, recipients, _d in outgoing.taken], [["zoe@example.com"]] * 2)
		self.assertIn(
			"bob@example.com", str(logged.call_args), "the recipient turned down, for the administrator"
		)
		self.assertEqual(cint(frappe.cache().get_value(jmap._sends_key())), 2)

	def test_a_connection_lost_while_the_message_was_on_its_way_is_a_doubt(self):
		"""The one case nobody can know: MailCraft holds the message as one that may have been sent, and it can't be sent
		again from here."""
		server = FakeServer()
		with served(server), smtp() as outgoing, patch.object(frappe, "log_error") as logged:
			outgoing.set(end="drop")
			jid, name, answer = self._sent_through()
			self.assertEqual(name, "EmailSubmission/set")
			self.assertEqual(answer["notCreated"]["s"]["type"], "serverFail", answer)
			self.assertFalse(frappe.cache().get_value(jmap._filed_key(jid)))
			again = self._submit(self._submission(jid))
			self.assertEqual(again["notCreated"]["s"]["type"], "invalidEmail")
		self.assertEqual(logged.call_count, 1)
		self.assertEqual(cint(frappe.cache().get_value(jmap._sends_key())), 1, "it may have gone: it counts")

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
			patch.object(neomail, "build_installed", return_value=True),
		):
			neomail.get_context(context)
		# The build is told who is signed in, for the initials of its account button
		named = "author=" + quote(frappe.utils.get_fullname(frappe.session.user), safe="")
		self.assertTrue(context.build_url.endswith("index.html?nora&" + named))
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
			patch.object(neomail, "build_installed", return_value=True),
		):
			neomail.get_context(sample)
		shared = "author=" + quote(frappe.utils.get_fullname(SHARED), safe="")
		self.assertTrue(
			sample.build_url.endswith("?sample&nora&" + shared), "?sample opens the sample mailbox"
		)
		self.assertEqual(
			json.loads(sample.host_json),
			{
				"accounts": [],
				"language": context.lang,
				"product": "NeoMail",
				"signatures": frappe.utils.get_url("/app/webmail?signatures=1"),
			},
		)
		self.assertEqual(
			json.loads(context.host_json)["language"], frappe.local.lang or "en", "the desk's language"
		)

	def _signature(self, user, content, default=True):
		"""An Email Signature of `user`, removed after the test (which also clears it from the mailbox)."""
		doc = frappe.get_doc(
			{
				"doctype": "Email Signature",
				"user": user,
				"signature_name": "mailcraft-jmap-" + secrets.token_hex(4),
				"is_default": int(default),
				"content": content,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Email Signature", doc.name, force=True, ignore_permissions=True)
		return doc.name

	def test_each_mailbox_carries_its_signature_or_the_person_s_own(self):
		from frappe_webmail.www import neomail

		# The signatures people wrote, as before any company signature: none applies here (a site may hold one)
		no_template = patch("frappe_webmail.signatures.template_for", return_value=None)
		no_template.start()
		self.addCleanup(no_template.stop)

		def handed():
			return next(a for a in neomail.host_mailboxes() if a["email"] == MAILBOX).get("signature")

		frappe.db.delete("Email Signature", {"user": SHARED})
		frappe.db.set_value("Webmail Account", MAILBOX, "default_signature", None)
		self.assertIsNone(handed(), "no signature anywhere: none handed over")
		own = '<div class="ql-editor read-mode"><p>Camille Favre</p><p><strong>Atelier</strong>&nbsp;&amp; Co</p></div>'
		self._signature(SHARED, own)
		self.assertEqual(
			handed(),
			{"html": own, "text": "Camille Favre\nAtelier & Co"},
			"the person's default, as the webmail",
		)
		team = self._signature(OWNER, "<p>Le service client</p>", default=False)
		frappe.db.set_value("Webmail Account", MAILBOX, "default_signature", team)
		self.addCleanup(frappe.db.set_value, "Webmail Account", MAILBOX, "default_signature", None)
		self.assertEqual(
			handed()["text"], "Le service client", "the mailbox's own first, for whoever writes from it"
		)
		logo = '<p>Camille</p><p><img src="data:image/png;base64,iVBORw0KGgo="></p>'
		frappe.db.set_value(
			"Webmail Account", MAILBOX, "default_signature", self._signature(OWNER, logo, False)
		)
		given = handed()
		self.assertEqual(given["text"], "Camille")
		self.assertIn(
			'src="/private/files/', given["html"], "Frappe keeps a pasted picture as a file of the instance"
		)

	def test_a_company_signature_comes_with_its_logo_by_its_bytes(self):
		"""Under a template that draws the company's logo, the page hands MailCraft the logo itself and its place: MailCraft
		keeps a signature's pictures by their bytes and takes none from its HTML."""
		import base64
		import io

		from PIL import Image

		from frappe_webmail.www import neomail

		buffer = io.BytesIO()
		Image.new("RGB", (40, 10), (31, 58, 95)).save(buffer, "PNG")
		logo = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "mailcraft-jmap-test-logo.png",
				"content": buffer.getvalue(),
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "File", logo.name, force=True, ignore_permissions=True)
		writer = frappe._dict(
			user=SHARED,
			name="Camille Favre",
			job_title="",
			department="",
			phone="",
			mobile="",
			email=SHARED,
			company_name="Atelier",
			website="",
			address="",
			logo=logo.file_url,
		)
		company = frappe._dict(layout="Logo left", logo_width=90)
		with (
			patch("frappe_webmail.signatures.template_for", return_value=company),
			patch("frappe_webmail.signatures.person_of", return_value=writer),
			patch("frappe_webmail.signatures._team_of", side_effect=lambda person, account, phone: person),
		):
			box = next(a for a in neomail.host_mailboxes() if a["email"] == MAILBOX)
		signature = box["signature"]
		self.assertIn("Camille Favre", signature["text"])
		self.assertEqual(signature["layout"], "pictureLeft")
		self.assertEqual((signature["logo"]["width"], signature["logo"]["alt"]), (90, "Atelier"))
		self.assertEqual(base64.b64decode(signature["logo"]["data"]), buffer.getvalue())
		# Its picture leaves the HTML: MailCraft would show the logo twice, the second time by its description
		self.assertNotIn(logo.file_url, signature["html"])
		self.assertIn("Camille Favre", signature["html"])

	def test_a_mailbox_says_whether_it_is_shared_with_the_person(self):
		"""Nora's pane in NeoMail asks the person before she writes into a message of a mailbox shared with them: the page
		says which of their mailboxes are shared with them rather than theirs."""
		from frappe_webmail.www import neomail

		no_template = patch("frappe_webmail.signatures.template_for", return_value=None)
		no_template.start()
		self.addCleanup(no_template.stop)
		self._as(OWNER)
		self.assertIs(next(a for a in neomail.host_mailboxes() if a["email"] == MAILBOX)["shared"], False)
		self._as(SHARED)
		self.assertIs(next(a for a in neomail.host_mailboxes() if a["email"] == MAILBOX)["shared"], True)

	def test_a_mailbox_hands_over_only_a_signature_of_its_owner(self):
		"""The Link can name anyone's signature (Frappe checks only that it exists): another person's stays theirs."""
		from frappe_webmail.www import neomail

		no_template = patch("frappe_webmail.signatures.template_for", return_value=None)
		no_template.start()
		self.addCleanup(no_template.stop)

		frappe.db.delete("Email Signature", {"user": ["in", (OWNER, SHARED)]})
		someone_else = self._signature(STRANGER, "<p>Private to the stranger</p>", default=False)
		frappe.db.set_value("Webmail Account", MAILBOX, "default_signature", someone_else)
		self.addCleanup(frappe.db.set_value, "Webmail Account", MAILBOX, "default_signature", None)
		for person in (SHARED, OWNER):
			self._as(person)
			box = next(a for a in neomail.host_mailboxes() if a["email"] == MAILBOX)
			self.assertNotIn("signature", box, person)
		self._signature(SHARED, "<p>Camille</p>")
		self._as(SHARED)
		box = next(a for a in neomail.host_mailboxes() if a["email"] == MAILBOX)
		self.assertEqual(box["signature"]["text"], "Camille", "the person's own instead")

	def test_a_signature_reads_as_text_the_way_it_shows(self):
		from frappe_webmail.www.neomail import (
			MAX_SIGNATURE_HTML,
			MAX_SIGNATURE_SOURCE,
			MAX_SIGNATURE_TEXT,
			handed_signature,
			signature_text,
		)

		for html, text in (
			("<p>Camille</p><p><br></p><p>Favre</p><p><br></p>", "Camille\n\nFavre"),
			("<p>Camille<br>Favre<br></p>", "Camille\nFavre"),
			("<div><p>Camille</p></div>\n  <div><p>  Favre\n  SA</p></div>", "Camille\nFavre SA"),
			(
				'<p><a href="https://example.ch/team">Notre équipe</a></p>',
				"Notre équipe <https://example.ch/team>",
			),
			('<p><a href="https://www.example.ch/">www.example.ch</a></p>', "www.example.ch"),
			('<p><a href="mailto:camille@example.ch">Écrire</a></p>', "Écrire"),
			('<p><a href="https://example.ch"><img src="logo.png" alt="Logo"></a>Camille</p>', "Camille"),
			("<style>p { color: red }</style><!--[if mso]>x<![endif]--><p>Camille</p>", "Camille"),
			(
				"<table><tr><td>Tél.</td><td>+41 21 000 00 00</td></tr><tr><td>Web</td><td>example.ch</td></tr></table>",
				"Tél. +41 21 000 00 00\nWeb example.ch",
			),
			("<p>Camille</p><p>&nbsp;</p><p>Favre</p>", "Camille\n\nFavre"),
			("<p>&nbsp;</p><p>Camille</p><p>&nbsp;</p>", "Camille"),
			("<div>" * 5000 + "Camille" + "</div>" * 5000, "Camille"),
		):
			self.assertEqual(signature_text(html), text, html)
		self.assertIsNone(handed_signature("<p><br></p>"), "emptied: nothing to show")
		self.assertIsNone(handed_signature(None))
		self.assertEqual(
			handed_signature('<p><img src="logo.png"></p>')["text"], "", "a logo alone still counts"
		)
		heavy = '<p>Camille</p><img src="data:image/png;base64,' + "A" * MAX_SIGNATURE_HTML + '">'
		self.assertEqual(
			handed_signature(heavy), {"html": "", "text": "Camille"}, "too heavy: its text alone"
		)
		self.assertEqual(
			len(handed_signature("<p>" + "x" * (MAX_SIGNATURE_TEXT + 9) + "</p>")["text"]), MAX_SIGNATURE_TEXT
		)
		heavy_logo = '<p><img src="data:image/png;base64,' + "A" * MAX_SIGNATURE_HTML + '"></p>'
		self.assertIsNone(handed_signature(heavy_logo), "too heavy and no words: nothing to show")
		self.assertIsNone(handed_signature("<p>" + "x" * MAX_SIGNATURE_SOURCE + "</p>"), "not read at all")
		with (
			patch("bs4.BeautifulSoup", side_effect=RuntimeError("unreadable")),
			patch.object(frappe, "log_error") as log_error,
		):
			self.assertIsNone(handed_signature("<p>Camille</p>"), "left out, the mailboxes still open")
		self.assertEqual(log_error.call_args.args[0], "NeoMail: a signature could not be read as text")

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

	def _hand_over(self, bearer, user=SHARED, client=None):
		"""hand_over, for a request Frappe signed in as `user` with that bearer token in Authorization, on an instance
		whose apps (Neodesk) sign in with `client` (the test's own OAuth client unless told)."""
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = None
		with (
			patch("frappe.get_request_header", return_value=f"Bearer {bearer}" if bearer else None),
			patch.object(jmap, "neodesk_client", return_value=client or self.client),
		):
			return jmap.hand_over()

	def test_neodesk_gets_the_mailboxes_for_its_bearer_and_they_live_with_it(self):
		bearer = self._bearer()
		given = self._hand_over(bearer)
		box = next(a for a in given["accounts"] if a["email"] == MAILBOX)
		self.assertEqual((given["product"], box["scheme"]), ("NeoMail", "bearer"))
		self.assertTrue(given["language"])
		self.assertEqual(given["signatures"], frappe.utils.get_url("/app/webmail?signatures=1"))
		self.assertEqual(
			given["nora"], "nora" in frappe.get_installed_apps(), "Nora only where the instance has her"
		)
		# Synk, Neodesk's own chat, only where Raven is and for whom holds its role
		self.assertEqual(
			given["synk"], "raven" in frappe.get_installed_apps() and "Raven User" in frappe.get_roles(SHARED)
		)
		# What NeoMail offers on an attachment in Neodesk's window, as on the desk's page (neomail_attachments.offered)
		from frappe_webmail import neomail_attachments

		self.assertEqual(given["attachments"], neomail_attachments.offered())
		self.assertEqual(
			given["editors"],
			sorted(neomail_attachments.installed_editors()) if "edit" in given["attachments"] else [],
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
			patch.dict(frappe.local.conf, {"neomail_disabled": 1}),
			self.assertRaises(frappe.PageDoesNotExistError),
		):
			self._hand_over(self._bearer())

	def test_a_bearer_counts_only_as_frappe_would_take_it(self):
		"""Its OAuth client still there and granting its scopes, and an expiry: Frappe refuses a bearer token otherwise."""
		gone = _client("mailcraft-jmap-gone")
		orphan = self._bearer(client=gone)
		secret = self._hand_over(orphan, client=gone)["accounts"][0]["secret"]
		self.assertEqual(self._authenticated(SESSION, secret)[0], SHARED)
		# Removed from the table, as Frappe's own check would then find it (the desk refuses it while tokens link to it).
		frappe.db.delete("OAuth Client", gone)
		self.assertEqual(self._authenticated(SESSION, secret)[0], "Guest", "its client was deleted")
		with self.assertRaises(frappe.PermissionError):
			self._hand_over(orphan, client=gone)
		with self.assertRaises(frappe.PermissionError, msg="a scope its client does not grant"):
			self._hand_over(self._bearer(scopes="all openid fileshare"))
		endless = self._bearer()
		frappe.db.set_value("OAuth Bearer Token", endless, "expiration_time", None)
		with self.assertRaises(frappe.PermissionError, msg="no expiry"):
			self._hand_over(endless)

	def test_only_a_token_given_to_neodesk_s_client_opens_the_hand_over(self):
		"""Neodesk signs in with the OAuth client this instance hands its apps (Raven Settings, raven_mobile.get_client_id):
		a live token of the person given to any other client of theirs (an integration, another app) is refused, as is
		every token where the instance names no such client. Real tokens, compared by their hash."""
		other = frappe.db.get_value("OAuth Client", {"app_name": "mailcraft-jmap-other"}) or _client(
			"mailcraft-jmap-other"
		)
		self.assertIn(MAILBOX, [a["email"] for a in self._hand_over(self._bearer())["accounts"]])
		with self.assertRaises(frappe.PermissionError, msg="another client of the person's"):
			self._hand_over(self._bearer(client=other))
		frappe.set_user(SHARED)
		with (
			patch("frappe.get_request_header", return_value=f"Bearer {self._bearer()}"),
			patch.object(jmap, "neodesk_client", return_value=None),
			self.assertRaises(frappe.PermissionError, msg="no client named for the apps"),
		):
			jmap.hand_over()

	def test_neodesk_s_client_is_the_one_the_instance_hands_its_apps(self):
		"""Raven's setting, which raven.api.raven_mobile.get_client_id hands Neodesk's page before it signs in; none
		without Raven. On a bench that has Raven (the clone), a token minted for that very client opens the hand-over."""
		with patch.object(frappe, "get_installed_apps", return_value=["frappe", "frappe_webmail"]):
			self.assertIsNone(jmap.neodesk_client())
		with (
			patch.object(frappe, "get_installed_apps", return_value=["frappe", "raven", "frappe_webmail"]),
			patch.object(frappe.db, "get_single_value", return_value="apps-client"),
		):
			self.assertEqual(jmap.neodesk_client(), "apps-client")
		if "raven" not in frappe.get_installed_apps():
			return
		apps = frappe.db.get_single_value("Raven Settings", "oauth_client")
		if not apps or not frappe.db.exists("OAuth Client", apps):
			return
		frappe.set_user(SHARED)
		frappe.local.flags.mailcraft_jmap_user = None
		with patch("frappe.get_request_header", return_value=f"Bearer {self._bearer(client=apps)}"):
			self.assertIn(MAILBOX, [a["email"] for a in jmap.hand_over()["accounts"]])
		with (
			patch("frappe.get_request_header", return_value=f"Bearer {self._bearer()}"),
			self.assertRaises(frappe.PermissionError, msg="the test's own client is not the apps' one"),
		):
			jmap.hand_over()

	def test_neodesk_s_hand_over_offers_the_attachment_actions_and_never_fails_for_them(self):
		"""Neodesk's NeoMail window offers on an attachment what the desk's page offers (neomail_attachments.offered):
		the Drive, the scanned documents, the Drive's editors. What fails there offers nothing, logged, and the
		mailboxes are still handed over."""
		from frappe_webmail import neomail_attachments

		with (
			patch.object(neomail_attachments, "offered", return_value=["drive", "scan", "edit"]),
			patch.object(neomail_attachments, "installed_editors", return_value={"xlsx", "docx"}),
		):
			given = self._hand_over(self._bearer())
		self.assertEqual(
			(given["attachments"], given["editors"]), (["drive", "scan", "edit"], ["docx", "xlsx"])
		)
		with (
			patch.object(neomail_attachments, "offered", return_value=["drive"]),
			patch.object(neomail_attachments, "installed_editors", return_value={"docx"}),
		):
			self.assertEqual(
				self._hand_over(self._bearer())["editors"], [], "no editor where none is offered"
			)
		with (
			patch.object(neomail_attachments, "offered", side_effect=RuntimeError("no Drive")),
			patch.object(frappe, "log_error") as log_error,
		):
			given = self._hand_over(self._bearer())
		self.assertEqual((given["attachments"], given["editors"]), ([], []))
		self.assertIn(MAILBOX, [a["email"] for a in given["accounts"]])
		self.assertEqual(
			log_error.call_args.args[0], "NeoMail: the actions on an attachment could not be offered"
		)

	def test_neodesk_s_hand_over_needs_no_build_here_and_the_page_s_renewal_does(self):
		"""Neodesk brings its own build of NeoMail: hand_over answers wherever NeoMail is on. renew serves the page
		only, which opens where the build is installed."""
		from frappe_webmail.www import neomail

		with patch.object(neomail, "build_installed", return_value=False):
			given = self._hand_over(self._bearer())
			self.assertIn(MAILBOX, [a["email"] for a in given["accounts"]])
			frappe.set_user(SHARED)
			with (
				patch("frappe.get_request_header", return_value=None),
				self.assertRaises(frappe.PageDoesNotExistError),
			):
				jmap.renew()

	def test_neomail_switched_off_closes_the_facade_to_a_token_too(self):
		self._as(SHARED)
		with patch.dict(frappe.local.conf, {"neomail_disabled": 1}):
			self.assertEqual(jmap.session(MAILBOX).status_code, 404)

	def test_the_page_renews_its_tokens_with_its_own_session_only(self):
		from frappe_webmail.www import neomail

		built = patch.object(neomail, "build_installed", return_value=True)
		built.start()
		self.addCleanup(built.stop)
		frappe.set_user(SHARED)
		page = frappe.session.sid
		with patch("frappe.get_request_header", side_effect=_page_headers()):
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
			patch.dict(frappe.local.conf, {"neomail_disabled": 1}),
			patch("frappe.get_request_header", return_value=None),
			self.assertRaises(frappe.PageDoesNotExistError),
		):
			jmap.renew()
		frappe.set_user(PORTAL)
		with patch("frappe.get_request_header", return_value=None), self.assertRaises(frappe.PermissionError):
			jmap.renew()

	def test_the_page_s_renewal_wants_its_session_s_csrf_token_and_its_cookie_only(self):
		"""This fork's CSRF check refuses nothing unless the site sets `neoffice_csrf_enforce` (maintenance#310):
		renew asks for the session's token itself. A request that carries any Authorization (a bearer token, an API
		key, a password) is not the page's."""
		from frappe_webmail.www import neomail

		built = patch.object(neomail, "build_installed", return_value=True)
		built.start()
		self.addCleanup(built.stop)
		frappe.set_user(SHARED)
		for sent, why in ((None, "no token"), ("", "an empty one"), ("not-the-session-s", "another one")):
			with (
				patch("frappe.get_request_header", side_effect=_page_headers(csrf=sent)),
				self.assertRaises(frappe.CSRFTokenError, msg=why),
			):
				jmap.renew()
		with (
			patch.dict(frappe.local.conf, {"ignore_csrf": 1, "neoffice_csrf_enforce": 0}),
			patch("frappe.get_request_header", side_effect=_page_headers(csrf=None)),
			self.assertRaises(frappe.CSRFTokenError, msg="whatever the site's settings"),
		):
			jmap.renew()
		for authorization in ("Bearer something", "token api-key:api-secret", "Basic dXNlcjpwYXNz"):
			with (
				patch("frappe.get_request_header", side_effect=_page_headers(authorization=authorization)),
				self.assertRaises(frappe.PermissionError, msg=authorization),
			):
				jmap.renew()
		with patch("frappe.get_request_header", side_effect=_page_headers()):
			self.assertIn(MAILBOX, [a["email"] for a in jmap.renew()["accounts"]])

	def test_a_change_cut_off_with_its_connection_is_a_doubt_not_a_retry(self):
		"""serverUnavailable says nothing was changed, and MailCraft makes the change again: an APPEND the server had
		taken, its answer lost, would be filed twice. A connection lost after a change was sent says serverFail (it
		may have been made, MailCraft checks); one lost before, or on a read, stays serverUnavailable."""
		lost = jmap.webmail.WebmailConnectionLost("IMAP: Connection timeout.")
		down = jmap.webmail.WebmailConnectionError("IMAP: Connection timeout.")
		for error, kind in ((lost, "serverFail"), (down, "serverUnavailable")):

			def fail(args, error=error):
				raise error

			with patch.dict(jmap.METHODS, {"Email/import": fail}):
				name, answer, _call_id = self._call("Email/import", {"accountId": self.aid})
			self.assertEqual((name, answer["type"]), ("error", kind), kind)

			def cut(uids, error=error):
				raise error

			failed = {}
			jmap._apply([("E1", 1)], failed, {}, cut)
			self.assertEqual(failed["E1"]["type"], kind, "one object of Email/set")

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
		# The former way of calling a method: its name in the form's `cmd`, whatever the address
		for cmd in ("frappe_webmail.mailcraft_jmap.hand_over", "frappe_webmail.mailcraft_jmap.renew"):
			response = SimpleNamespace(headers={})
			with patch.object(frappe.local, "form_dict", frappe._dict(cmd=cmd)):
				jmap.no_store(response=response, request=SimpleNamespace(path="/"))
			self.assertEqual(response.headers.get("Cache-Control"), "no-store", cmd)
		unrelated = SimpleNamespace(headers={})
		with patch.object(frappe.local, "form_dict", frappe._dict(cmd="frappe.auth.get_logged_user")):
			jmap.no_store(response=unrelated, request=SimpleNamespace(path="/"))
		self.assertEqual(unrelated.headers, {})

	def test_a_page_of_another_origin_gets_in_only_where_the_site_names_it(self):
		origin = "https://mail.example.org"

		def answered(path=SESSION, method="GET", sent=origin, named=(origin,), cmd=None, frappes=None):
			response = SimpleNamespace(headers={})
			request = SimpleNamespace(path=path, method=method, headers={"Origin": sent} if sent else {})
			conf = {
				"mailcraft_jmap_cors_origins": list(named) if named is not None else None,
				"allow_cors": frappes,
			}
			with (
				patch.dict(frappe.local.conf, conf),
				patch.object(frappe.local, "form_dict", frappe._dict(cmd=cmd)),
			):
				jmap.cors(response=response, request=request)
			return response.headers

		self.assertIn("frappe_webmail.mailcraft_jmap.cors", frappe.get_hooks("after_request"))

		self.assertEqual(answered(named=None), {}, "nobody by default")
		got = answered()
		self.assertEqual((got["Access-Control-Allow-Origin"], got["Vary"]), (origin, "Origin"))
		self.assertEqual(got["Access-Control-Expose-Headers"], "Retry-After")
		self.assertNotIn("Access-Control-Allow-Credentials", got, "never the browser's cookies")
		self.assertNotIn("Access-Control-Allow-Methods", got, "only a preflight is told the methods")
		preflight = answered(path=API, method="OPTIONS")
		self.assertEqual(preflight["Access-Control-Allow-Methods"], "GET, POST")
		self.assertEqual(preflight["Access-Control-Allow-Headers"], "Authorization, Content-Type, Accept")
		# Another origin, an address that isn't the facade's (one that hands tokens out among them), `*` named,
		# a sandboxed page's `null`, and no origin at all: nothing.
		self.assertEqual(answered(sent="https://other.example.org"), {})
		self.assertEqual(answered(path="/api/method/frappe.client.get_list"), {})
		self.assertEqual(answered(path="/api/method/frappe_webmail.mailcraft_jmap.hand_over"), {})
		self.assertEqual(answered(sent="https://other.example.org", named=("*",)), {})
		self.assertEqual(answered(sent="*", named=("*",)), {})
		self.assertEqual(answered(sent="null", named=("null",)), {})
		# Frappe runs a `cmd` whatever the path: only the method the address names is answered.
		self.assertEqual(answered(cmd="frappe_webmail.mailcraft_jmap.hand_over"), {})
		self.assertEqual(
			answered(cmd="frappe_webmail.mailcraft_jmap.session")["Access-Control-Allow-Origin"], origin
		)
		# An origin Frappe's own allow_cors names is left to it: one answer, never two.
		self.assertEqual(answered(frappes="*"), {})
		self.assertEqual(answered(frappes=[origin]), {})
		self.assertEqual(answered(frappes=["http://127.0.0.1:8081"])["Access-Control-Allow-Origin"], origin)
		self.assertEqual(answered(sent=None), {})
		# A configuration that isn't a list of origins names none.
		self.assertEqual(answered(named=None), {})
		with patch.dict(frappe.local.conf, {"mailcraft_jmap_cors_origins": origin}):
			response = SimpleNamespace(headers={})
			jmap.cors(
				response=response,
				request=SimpleNamespace(path=SESSION, method="GET", headers={"Origin": origin}),
			)
		self.assertEqual(response.headers, {})
		# On a real response: one origin, and `Vary` kept with what it had.
		real = Response(status=401)
		real.headers["Vary"] = "Accept-Encoding"
		request = SimpleNamespace(path=SESSION, method="GET", headers={"Origin": origin})
		with patch.dict(frappe.local.conf, {"mailcraft_jmap_cors_origins": [origin], "allow_cors": None}):
			jmap.cors(response=real, request=request)
		self.assertEqual(real.headers.getlist("Access-Control-Allow-Origin"), [origin])
		self.assertEqual(real.headers["Vary"], "Accept-Encoding, Origin")
