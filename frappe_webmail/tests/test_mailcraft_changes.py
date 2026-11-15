# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Real JMAP states of the facade (mailcraft_changes.py): what changed in a mailbox since a state NeoMail holds.

The IMAP server is the fake of test_mailcraft_jmap, as is (no CONDSTORE: the flags of every message are its
fingerprint) or with CONDSTORE (ModseqServer: a mod-sequence for each change, FETCH CHANGEDSINCE, HIGHESTMODSEQ), changed
between two calls as another client would change it.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_changes
"""

import contextlib
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_changes as changes
from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail.tests.test_mailcraft_jmap import VALIDITY, FakeServer, _user, message, served

OWNER = "mailcraft_changes_owner@example.com"
SHARED = "mailcraft_changes_shared@example.com"
STRANGER = "mailcraft_changes_stranger@example.com"
MAILBOX = "mailcraft_changes_box@webmail.test"


class ModseqServer(FakeServer):
	"""The fake with CONDSTORE (RFC 7162): every message carries the mod-sequence of its last change, a folder its
	highest, raised by an arrival, a flag changed or an expunge; FETCH answers CHANGEDSINCE. It counts the reads that cost."""

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.modseq = 1
		self.highest = dict.fromkeys(self.folders, 1)
		self.reads = {"fetch": 0, "changedsince": 0, "search_all": 0}

	def _bump(self, folder):
		self.modseq += 1
		self.highest[folder] = self.modseq
		return self.modseq

	def capabilities(self):
		return (*super().capabilities(), b"CONDSTORE")

	def put(self, folder, raw, flags=(), when=datetime(2026, 10, 16, 9, 0)):
		uid = super().put(folder, raw, flags, when)
		self.folders[folder]["messages"][uid]["modseq"] = self._bump(folder)
		return uid

	def flag(self, folder, uid, *flags, remove=False):
		"""Another client sets (or takes off) flags of a message."""
		m = self.folders[folder]["messages"][uid]
		(m["flags"].difference_update if remove else m["flags"].update)(flags)
		m["modseq"] = self._bump(folder)

	def add_flags(self, uids, flags):
		super().add_flags(uids, flags)
		for uid in uids:
			self._messages()[uid]["modseq"] = self._bump(self.selected)

	def remove_flags(self, uids, flags):
		super().remove_flags(uids, flags)
		for uid in uids:
			self._messages()[uid]["modseq"] = self._bump(self.selected)

	def expunge(self, *args):
		super().expunge(*args)
		self._bump(self.selected)

	def uid_expunge(self, uids):
		super().uid_expunge(uids)
		self._bump(self.selected)

	def move(self, uids, folder):
		source = self.selected
		super().move(uids, folder)
		self._bump(source)

	def search(self, criteria, charset=None):
		if criteria == ["ALL"]:
			self.reads["search_all"] += 1
			return list(self._messages())
		return super().search(criteria, charset)

	def fetch(self, uids, items, modifiers=None):
		self.reads["fetch"] += 1
		got = super().fetch(uids, items)
		since = next(
			(int(m.split()[1]) for m in modifiers or () if m.upper().startswith("CHANGEDSINCE")), None
		)
		if since is None:
			return got
		self.reads["changedsince"] += 1
		return {uid: data for uid, data in got.items() if self._messages()[uid]["modseq"] > since}

	def folder_status(self, folder, items):
		status = super().folder_status(folder, items)
		if b"HIGHESTMODSEQ" in items:
			status[b"HIGHESTMODSEQ"] = self.highest[folder]
		return status


def eid(folder, uid, validity=VALIDITY):
	return jmap.email_id(folder, validity, uid)


def expunged(server, folder, uid):
	"""Another client deletes a message for good."""
	del server.folders[folder]["messages"][uid]
	if isinstance(server, ModseqServer):
		server._bump(folder)


class TestMailCraftChanges(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email in (OWNER, SHARED, STRANGER):
			_user(email)
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

	def setUp(self):
		self.on = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
		self.on.start()
		self._as(SHARED)
		frappe.cache().delete_value(
			[
				changes._head_key(MAILBOX),
				changes._log_key(MAILBOX),
				changes._views_key(MAILBOX),
				*(changes._boxes_key(MAILBOX, user) for user in (OWNER, SHARED)),
			]
		)

	def tearDown(self):
		self.on.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.set_user("Administrator")

	def _as(self, user):
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = user

	def _call(self, name, args):
		body = json.dumps({"using": [jmap.CORE, jmap.MAIL], "methodCalls": [[name, args, "c0"]]}).encode()
		with patch.object(frappe.local, "request", SimpleNamespace(get_data=lambda: body), create=True):
			answer = jmap.api()
		self.assertEqual(answer.status_code, 200, answer.get_data())
		return json.loads(answer.get_data())["methodResponses"][0]

	def _ok(self, name, args):
		out_name, out, _cid = self._call(name, {"accountId": self.aid, **args})
		self.assertEqual(out_name, name, out)
		return out

	def _state(self):
		return self._ok("Email/get", {"ids": []})["state"]

	def _changes(self, since, **more):
		return self._ok("Email/changes", {"sinceState": since, **more})

	def _cannot(self, name, args):
		out_name, out, _cid = self._call(name, {"accountId": self.aid, **args})
		self.assertEqual((out_name, out.get("type")), ("error", "cannotCalculateChanges"), out)

	@staticmethod
	def _lists(out):
		return {k: sorted(out[k]) for k in ("created", "updated", "destroyed")}

	# Email/changes ---------------------------------------------------------------------------------------------

	def test_without_condstore_a_state_says_what_changed_since(self):
		server = FakeServer()
		for subject in ("one", "two", "three"):
			server.put("INBOX", message(subject))
		with served(server):
			before = self._state()
			self.assertEqual(self._state(), before, "nothing changed: the same state")
			server.put("INBOX", message("four"))
			expunged(server, "INBOX", 2)
			server.folders["INBOX"]["messages"][3]["flags"].add(b"\\Seen")
			out = self._changes(before)
			self.assertEqual(
				self._lists(out),
				{"created": [eid("INBOX", 4)], "updated": [eid("INBOX", 3)], "destroyed": [eid("INBOX", 2)]},
			)
			self.assertEqual((out["oldState"], out["hasMoreChanges"]), (before, False))
			self.assertNotEqual(out["newState"], before)
			again = self._changes(out["newState"])
			self.assertEqual(self._lists(again), {"created": [], "updated": [], "destroyed": []})
			self.assertEqual(again["newState"], out["newState"], "nothing since: the state stays")
			self.assertEqual(self._state(), out["newState"])

	def test_without_condstore_a_flag_status_does_not_show_is_seen_at_the_next_reading_of_the_flags(self):
		server = FakeServer()
		server.put("INBOX", message("one"))
		with served(server):
			before = self._state()
			server.folders["INBOX"]["messages"][1]["flags"].add(b"\\Flagged")
			self.assertEqual(
				self._changes(before)["updated"], [], "within FLAGS_RECHECK, STATUS alone is read"
			)
			later = changes.time.time() + changes.FLAGS_RECHECK + 1
			with patch.object(changes.time, "time", return_value=later):
				self.assertEqual(self._changes(before)["updated"], [eid("INBOX", 1)])

	def test_with_condstore_only_what_moved_is_read(self):
		server = ModseqServer()
		for subject in ("one", "two", "three"):
			server.put("INBOX", message(subject))
		server.put("Sent", message("sent"))
		with served(server):
			before = self._state()
			server.reads.update(fetch=0, changedsince=0, search_all=0)
			self.assertEqual(
				self._lists(self._changes(before)), {"created": [], "updated": [], "destroyed": []}
			)
			self.assertEqual(server.reads, {"fetch": 0, "changedsince": 0, "search_all": 0}, "STATUS only")

			server.flag("INBOX", 1, b"\\Flagged")
			out = self._changes(before)
			self.assertEqual(self._lists(out)["updated"], [eid("INBOX", 1)])
			self.assertEqual((server.reads["changedsince"], server.reads["search_all"]), (1, 0))

			server.put("INBOX", message("four"))
			expunged(server, "INBOX", 2)
			server.flag("INBOX", 3, b"\\Deleted")
			out = self._changes(out["newState"])
			self.assertEqual(
				self._lists(out),
				{
					"created": [eid("INBOX", 4)],
					"updated": [],
					"destroyed": sorted([eid("INBOX", 2), eid("INBOX", 3)]),
				},
			)
			self.assertEqual(server.reads["search_all"], 1, "the count said one went: its UIDs read once")
			# From the first state, all of it at once, made and let go of since said once
			whole = self._lists(self._changes(before))
			self.assertEqual(whole["created"], [eid("INBOX", 4)])
			self.assertEqual(whole["updated"], [eid("INBOX", 1)])

	def test_a_folder_made_again_or_a_state_not_known_here_cannot_be_answered(self):
		server = ModseqServer()
		server.put("INBOX", message("one"))
		with served(server):
			before = self._state()
			for strange in ("0", "nonsense", f"{before.rpartition('-')[0]}-999", "ffff-0"):
				self._cannot("Email/changes", {"sinceState": strange})
			server.validity["INBOX"] = VALIDITY + 1
			self._cannot("Email/changes", {"sinceState": before})
			# Read again, NeoMail has a state that answers
			fresh = self._state()
			self.assertEqual(
				self._lists(self._changes(fresh)), {"created": [], "updated": [], "destroyed": []}
			)
			# A journal the cache lost: every state of before is unknown
			frappe.cache().delete_value(changes._head_key(MAILBOX))
			self._cannot("Email/changes", {"sinceState": fresh})

	def test_many_changes_come_in_pages_and_a_bad_max_is_refused(self):
		server = ModseqServer()
		server.put("INBOX", message("one"))
		with served(server):
			before = self._state()
			server.put("INBOX", message("two"))
			middle = self._changes(before)["newState"]
			server.put("INBOX", message("three"))
			first = self._changes(before, maxChanges=1)
			self.assertEqual((first["created"], first["hasMoreChanges"]), ([eid("INBOX", 2)], True))
			self.assertEqual(first["newState"], middle)
			rest = self._changes(first["newState"], maxChanges=1)
			self.assertEqual((rest["created"], rest["hasMoreChanges"]), ([eid("INBOX", 3)], False))
			for bad in (0, -1, "2", 1.5):
				out_name, out, _cid = self._call(
					"Email/changes", {"accountId": self.aid, "sinceState": before, "maxChanges": bad}
				)
				self.assertEqual((out_name, out["type"]), ("error", "invalidArguments"), bad)

	def test_set_and_import_log_what_they_did(self):
		server = ModseqServer(move=True)
		for subject in ("one", "two"):
			server.put("INBOX", message(subject))
		with served(server):
			before = self._state()
			out = self._ok("Email/set", {"update": {eid("INBOX", 1): {"keywords/$flagged": True}}})
			self.assertEqual(out["oldState"], before)
			self.assertNotEqual(out["newState"], before)
			flagged = self._changes(before)
			self.assertIn(eid("INBOX", 1), flagged["updated"])
			moved = self._ok(
				"Email/set", {"update": {eid("INBOX", 2): {f"mailboxIds/{jmap.mailbox_id('Trash')}": True}}}
			)
			# The head just before: the sweep of that Email/changes logged the flag once more (told twice, never missed)
			self.assertEqual(moved["oldState"], flagged["newState"])
			seen = self._changes(flagged["newState"])
			self.assertIn(eid("INBOX", 2), seen["destroyed"])
			self.assertIn(eid("Trash", 1), seen["created"])
			# Nothing done: the state as it stands, twice
			idle = self._ok("Email/set", {"update": {}})
			self.assertEqual(idle["oldState"], idle["newState"])

			blob = "U" + "1" * 32
			frappe.cache().set_value(
				jmap._upload_key(blob), {"user": SHARED, "data": message("filed")}, expires_in_sec=60
			)
			filed = self._ok(
				"Email/import",
				{"emails": {"k": {"blobId": blob, "mailboxIds": {jmap.mailbox_id("Sent"): True}}}},
			)
			self.assertNotEqual(filed["oldState"], filed["newState"])
			self.assertIn(filed["created"]["k"]["id"], self._changes(filed["oldState"])["created"])

	def test_a_sweep_that_lost_its_lock_writes_nothing(self):
		"""A sweep that outlived its lock (another worker took it since) writes nothing: what it saw is seen again by the
		next one, never written over another's entry."""
		server = ModseqServer()
		server.put("INBOX", message("one"))

		@contextlib.contextmanager
		def lost(key, wait=None):
			def guard():
				raise changes._Busy

			yield guard

		with served(server):
			before = self._state()
			server.put("INBOX", message("two"))
			with patch.object(changes, "_locked", lost):
				stale = self._changes(before)
			self.assertEqual(
				(stale["newState"], stale["created"]), (before, []), "answered from the journal as is"
			)
			self.assertEqual(self._changes(before)["created"], [eid("INBOX", 2)])

	def test_a_folder_the_server_answers_wrongly_stops_nothing(self):
		server = ModseqServer()
		server.put("INBOX", message("one"))
		server.put("Sent", message("sent"))
		with served(server):
			before = self._state()
			server.flag("INBOX", 1, b"\\Flagged")
			server.flag("Sent", 1, b"\\Flagged")
			fetch = server.fetch

			def broken(uids, items, modifiers=None):
				if server.selected == "Sent":
					raise Exception("BAD Internal error")
				return fetch(uids, items, modifiers)

			with patch.object(server, "fetch", broken), patch.object(changes, "log_quietly") as noted:
				out = self._changes(before)
			self.assertEqual((out["updated"], noted.call_count), ([eid("INBOX", 1)], 1))
			self.assertEqual(
				self._changes(out["newState"])["updated"], [eid("Sent", 1)], "seen once it answers"
			)

	def test_a_message_that_comes_and_goes_between_two_sweeps_is_told_gone(self):
		"""It came between STATUS and FETCH, so the sweep told it made; it went before the next one, so that the count
		alone says nothing moved: the view counted it all the same, and its going is told."""
		server = ModseqServer()
		server.put("INBOX", message("one"))
		with served(server):
			before = self._state()
			status = server.folder_status
			came = []

			def late(folder, items):
				out = status(folder, items)
				if folder == "INBOX" and not came:
					came.append(server.put("INBOX", message("late")))
				return out

			server.flag("INBOX", 1, b"\\Seen")
			with patch.object(server, "folder_status", late):
				first = self._changes(before)
			self.assertEqual(first["created"], [eid("INBOX", came[0])])
			expunged(server, "INBOX", came[0])
			self.assertEqual(self._changes(first["newState"])["destroyed"], [eid("INBOX", came[0])])

	def test_a_stranger_is_refused(self):
		self._as(STRANGER)
		with served(FakeServer()):
			for name, args in (
				("Email/changes", {"sinceState": "x-0"}),
				("Mailbox/changes", {"sinceState": "x-0"}),
				(
					"Email/queryChanges",
					{"sinceQueryState": "x-0", "filter": {"inMailbox": jmap.mailbox_id("INBOX")}},
				),
			):
				out = self._call(name, {"accountId": self.aid, **args})
				self.assertEqual((out[0], out[1]["type"]), ("error", "forbidden"), name)

	# Email/query, Email/queryChanges ---------------------------------------------------------------------------

	def _query(self, folder="INBOX", **more):
		return self._ok(
			"Email/query",
			{
				"filter": {"inMailbox": jmap.mailbox_id(folder)},
				"sort": [{"property": "receivedAt", "isAscending": False}],
				**more,
			},
		)

	def _query_changes(self, since, folder="INBOX", **more):
		return self._ok(
			"Email/queryChanges",
			{
				"filter": {"inMailbox": jmap.mailbox_id(folder)},
				"sort": [{"property": "receivedAt", "isAscending": False}],
				"sinceQueryState": since,
				**more,
			},
		)

	def test_a_query_state_holds_until_its_list_changes(self):
		server = ModseqServer(sort=True)
		server.put("INBOX", message("one"), when=datetime(2026, 11, 1, 9, 0))
		server.put("INBOX", message("two"), when=datetime(2026, 11, 2, 9, 0))
		with served(server):
			first = self._query()
			self.assertTrue(first["canCalculateChanges"])
			self.assertEqual(self._query()["queryState"], first["queryState"])
			server.flag("INBOX", 1, b"\\Seen")
			server.put("Sent", message("elsewhere"))
			self.assertEqual(self._query()["queryState"], first["queryState"], "a flag, another folder")

			server.put("INBOX", message("three"), when=datetime(2026, 11, 3, 9, 0))
			now = self._query()
			self.assertNotEqual(now["queryState"], first["queryState"])
			self.assertEqual(now["ids"][0], eid("INBOX", 3))
			out = self._query_changes(first["queryState"], calculateTotal=True)
			self.assertEqual(out["added"], [{"id": eid("INBOX", 3), "index": 0}])
			self.assertEqual(out["removed"], [eid("INBOX", 3)], "listed twice never: removed, then added")
			self.assertEqual((out["newQueryState"], out["total"]), (now["queryState"], 3))

			expunged(server, "INBOX", 1)
			server.put("INBOX", message("four"), when=datetime(2026, 11, 4, 9, 0))
			later = self._query_changes(now["queryState"])
			self.assertEqual(later["added"], [{"id": eid("INBOX", 4), "index": 0}])
			self.assertEqual(sorted(later["removed"]), sorted([eid("INBOX", 1), eid("INBOX", 4)]))
			self.assertEqual(self._query_changes(later["newQueryState"])["removed"], [])
			out_name, out, _cid = self._call(
				"Email/queryChanges",
				{
					"accountId": self.aid,
					"filter": {"inMailbox": jmap.mailbox_id("INBOX")},
					"sinceQueryState": now["queryState"],
					"maxChanges": 1,
				},
			)
			self.assertEqual((out_name, out["type"]), ("error", "tooManyChanges"))
			server.validity["INBOX"] = VALIDITY + 1
			self._cannot(
				"Email/queryChanges",
				{"filter": {"inMailbox": jmap.mailbox_id("INBOX")}, "sinceQueryState": now["queryState"]},
			)

	# Mailbox/get, Mailbox/changes, Mailbox/set ------------------------------------------------------------------

	def _boxes(self):
		return self._ok("Mailbox/get", {"ids": None})

	def test_the_folders_state_says_what_changed_and_whether_only_counts_did(self):
		server = FakeServer()
		server.put("INBOX", message("one"))
		with served(server):
			before = self._boxes()["state"]
			self.assertEqual(self._boxes()["state"], before)
			self.assertEqual(
				self._ok("Mailbox/get", {"ids": [jmap.mailbox_id("INBOX")]})["state"],
				before,
				"a few folders: the state as it stands",
			)
			server.folders["INBOX"]["messages"][1]["flags"].add(b"\\Seen")
			counted = self._ok("Mailbox/changes", {"sinceState": before})
			self.assertEqual(
				(counted["updated"], counted["updatedProperties"]),
				([jmap.mailbox_id("INBOX")], changes.COUNTS),
			)
			server.folders["Archive"] = {"flags": (b"\\HasNoChildren",), "messages": {}}
			server.validity["Archive"], server.next_uid["Archive"] = VALIDITY, 1
			del server.folders["Projects/Film"]
			made = self._ok("Mailbox/changes", {"sinceState": counted["newState"]})
			self.assertEqual(made["created"], [jmap.mailbox_id("Archive")])
			self.assertEqual(made["destroyed"], [jmap.mailbox_id("Projects/Film")])
			self.assertIsNone(made["updatedProperties"])
			whole = self._ok("Mailbox/changes", {"sinceState": before})
			self.assertEqual(whole["updatedProperties"], changes.COUNTS, "made and let go are not updated")
			self._cannot("Mailbox/changes", {"sinceState": "elsewhere-0"})

	def test_a_folder_made_by_neomail_moves_the_folders_state(self):
		self._as(OWNER)
		server = FakeServer()

		def create_folder(name):
			server.folders.setdefault(name, {"flags": (b"\\HasNoChildren",), "messages": {}})
			server.validity[name], server.next_uid[name] = VALIDITY, 1

		server.create_folder = create_folder
		with served(server):
			before = self._boxes()["state"]
			out = self._ok("Mailbox/set", {"create": {"k": {"name": "Clients", "parentId": None}}})
			self.assertEqual(out["oldState"], before)
			self.assertNotEqual(out["newState"], before)
			self.assertIn(
				out["created"]["k"]["id"], self._ok("Mailbox/changes", {"sinceState": before})["created"]
			)

	# The units -------------------------------------------------------------------------------------------------

	def test_every_key_of_the_journal_outlives_bench_clear_cache(self):
		"""frappe.clear_cache (every `bench clear-cache`: a translation, a deploy, a migrate) erases every key of the site
		but those `persistent_cache_keys` names, read as a glob with a `*` added (RedisWrapper.get_keys). A journal erased
		makes every state NeoMail kept unknown, and every mailbox read again whole (15.11, osiris)."""
		from fnmatch import fnmatchcase

		kept = frappe.get_hooks("persistent_cache_keys")
		for key in (
			changes._head_key(MAILBOX),
			changes._log_key(MAILBOX),
			changes._views_key(MAILBOX),
			changes._flags_key(MAILBOX),
			changes._boxes_key(MAILBOX, SHARED),
			"mailcraft_jmap_changes_lock:" + MAILBOX,
		):
			self.assertTrue(any(fnmatchcase(key, pattern + "*") for pattern in kept), key)

	def test_uids_are_packed_as_imap_writes_a_set(self):
		self.assertEqual(changes.pack([7, 3, 5, 6, 3, 1]), "1,3,5:7")
		self.assertEqual(list(changes.unpack("1,3,5:7")), [1, 3, 5, 6, 7])
		self.assertEqual((changes.pack([]), list(changes.unpack(""))), ("", []))
		self.assertEqual(changes._digest([b"\\Seen", b"\\Recent"]), changes._digest([b"\\seen"]))
		self.assertEqual(changes._parse("ab12-7"), ("ab12", 7))
		for strange in (None, 7, "", "-", "ab12-", "ab12-x", "0"):
			self.assertEqual(changes._parse(strange), (None, None), strange)

	def test_an_id_made_and_let_go_since_is_not_told(self):
		merged = changes._Merged()
		for jid, kind in (
			("a", "c"),
			("a", "u"),
			("b", "c"),
			("b", "d"),
			("c", "u"),
			("c", "d"),
			("d", "d"),
			("d", "c"),
		):
			merged.note(jid, kind)
		self.assertEqual(merged.lists(), {"created": ["a"], "updated": ["d"], "destroyed": ["c"]})
		self.assertEqual(merged.count, 3)
		marks = [merged.note("e", "c"), merged.note("a", "d")]
		merged.undo(marks)
		self.assertEqual((merged.lists()["created"], merged.count), (["a"], 3))
		# Told gone by a sweep, then updated by a call's own entry: still gone
		merged.note("f", "d")
		merged.note("f", "u")
		self.assertIn("f", merged.lists()["destroyed"])
