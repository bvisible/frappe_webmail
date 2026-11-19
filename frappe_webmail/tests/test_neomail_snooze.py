# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""« Plus tard » (neomail_snooze): a message put away until a chosen time leaves its folder for the mailbox's Snoozed
folder, and comes back to it at that time, unread, by the minute's job.

The IMAP server is the facade's fake (test_mailcraft_jmap.FakeServer), which keeps its folders in memory, with folders
that can be made: what was moved, flagged and made can be read back. The clock is set by the tests (`_now`), and the
job is run where the minute's look would enqueue it.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_neomail_snooze
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import neomail_snooze as snooze
from frappe_webmail.tests.test_mailcraft_jmap import VALIDITY, FakeServer, _user, served

OWNER = "neomail_snooze_owner@example.com"  # of the desk, owns MAILBOX
SHARED = "neomail_snooze_shared@example.com"  # of the desk, MAILBOX is shared with them
STRANGER = "neomail_snooze_stranger@example.com"  # of the desk, nothing shared
PORTAL = "neomail_snooze_portal@example.com"  # a Website User
USERS = (OWNER, SHARED, STRANGER, PORTAL)
MAILBOX = "neomail_snooze_box@webmail.test"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def raw(name, extra=b""):
	return (
		b"Message-ID: <"
		+ name.encode()
		+ b"@example.com>\r\nFrom: Ann <ann@example.com>\r\nTo: box@webmail.test\r\n"
		b"Subject: " + name.encode() + b"\r\n" + extra + b"\r\nBody\r\n"
	)


def utc(moment):
	return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Server(FakeServer):
	"""The facade's fake IMAP server, whose folders can also be made, subscribed to and deleted."""

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.subscribed = set()
		self.made = []

	def create_folder(self, name):
		if name in self.folders:
			raise Exception(f"[ALREADYEXISTS] {name}")
		self.folders[name] = {"flags": (b"\\HasNoChildren",), "messages": {}}
		self.validity[name] = VALIDITY
		self.next_uid[name] = 1
		self.made.append(name)

	def subscribe_folder(self, name):
		self.subscribed.add(name)

	def search(self, criteria, charset=None):
		# A UID search that leaves out what is marked deleted, as a server answers it.
		if criteria[:1] == ["UID"] and criteria[2:4] == ["NOT", "DELETED"]:
			found = super().search(criteria[:2], charset)
			return [u for u in found if b"\\Deleted" not in self._messages()[u]["flags"]]
		return super().search(criteria, charset)

	def drop_folder(self, name):
		del self.folders[name]

	def renumber(self, name, validity):
		"""The server numbers the folder anew (its UIDVALIDITY changes, and every UID with it)."""
		messages = list(self.folders[name]["messages"].values())
		self.folders[name]["messages"] = {}
		self.validity[name] = validity
		self.next_uid[name] = 100
		for m in messages:
			self.put(name, m["raw"], m["flags"], m["date"])

	def subjects(self, folder):
		return sorted(
			m["raw"].split(b"Subject: ", 1)[1].split(b"\r\n", 1)[0].decode()
			for m in self.folders[folder]["messages"].values()
		)

	def flags_of(self, folder, subject):
		for m in self.folders[folder]["messages"].values():
			if b"Subject: " + subject.encode() + b"\r\n" in m["raw"]:
				return m["flags"]
		raise KeyError(subject)


class TestNeomailSnooze(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email in (OWNER, SHARED, STRANGER):
			_user(email)
		_user(PORTAL, desk=False)
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
		frappe.db.commit()  # nosemgrep: the users and the mailbox the calls below read
		cls.aid = jmap.account_id(MAILBOX)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete(snooze.DOCTYPE, {"account": ("in", (MAILBOX, "renamed_box@webmail.test"))})
		frappe.db.commit()  # nosemgrep: what the methods committed goes too
		super().tearDownClass()

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
		self.trial.start()
		frappe.set_user("Administrator")
		frappe.db.delete(snooze.DOCTYPE, {"account": ("in", (MAILBOX, "renamed_box@webmail.test"))})
		frappe.db.commit()  # nosemgrep: each test starts from nothing put away
		frappe.cache().delete_value(snooze._folder_key(SimpleNamespace(name=MAILBOX)))
		frappe.cache().delete_value(f"neomail_snooze_failed:{MAILBOX}")
		self.server = Server()
		self.at(NOW)
		self._as(SHARED)

	def tearDown(self):
		self.clock.stop()
		self.trial.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.set_user("Administrator")

	def at(self, moment):
		if getattr(self, "clock", None):
			self.clock.stop()
		self.clock = patch.object(snooze, "_now", return_value=moment)
		self.clock.start()

	def _as(self, user):
		"""The session of `user`, as the facade's authenticate() leaves a request that came with its token."""
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = user

	def _calls(self, *calls, status=200):
		body = json.dumps(
			{
				"using": [jmap.CORE, snooze.SNOOZE],
				"methodCalls": [[name, args, f"c{n}"] for n, (name, args) in enumerate(calls)],
			}
		).encode()
		request = SimpleNamespace(
			get_data=lambda: body,
			headers={},
			host="webmail.test",
			method="POST",
			path="/api/method/" + jmap.METHOD_PREFIX + "api",
		)
		with served(self.server), patch.object(frappe.local, "request", request, create=True):
			answer = jmap.api()
		self.assertEqual(answer.status_code, status, answer.get_data())
		return json.loads(answer.get_data()).get("methodResponses") if status == 200 else answer

	def _get(self, **args):
		answer = self._calls(("NeomailSnooze/get", {"accountId": self.aid, **args}))[0]
		self.assertEqual(answer[0], "NeomailSnooze/get", answer)
		return answer[1]

	def _set(self, **args):
		answer = self._calls(("NeomailSnooze/set", {"accountId": self.aid, **args}))[0]
		self.assertEqual(answer[0], "NeomailSnooze/set", answer)
		return answer[1]

	def _put_away(self, folder="INBOX", name="hello", until=None, flags=(b"\\Seen",)):
		uid = self.server.put(folder, raw(name), flags)
		until = until or NOW + timedelta(hours=3)
		done = self._set(create={"k": {"emailId": jmap.email_id(folder, VALIDITY, uid), "until": utc(until)}})
		self.assertIn("k", done["created"] or {}, done)
		return done["created"]["k"]

	def _record(self, name):
		return frappe.db.get_value(snooze.DOCTYPE, name, ["*"], as_dict=True)

	def _job(self):
		"""The minute's look, and the jobs it enqueues run at once, as the mailbox's owner (their own user)."""
		queued = []
		with patch.object(frappe, "enqueue", side_effect=lambda *a, **k: queued.append(k)):
			snooze.tick()
		frappe.set_user("Administrator")
		with served(self.server):
			for job in queued:
				snooze.return_due(job["account"])
		self._as(SHARED)
		return queued

	def folder(self):
		return snooze._(
			snooze.SNOOZED, lang=snooze._owner_language(frappe.get_doc("Webmail Account", MAILBOX))
		)

	# Offered -----------------------------------------------------------------------------------------------------

	def test_the_session_offers_it_where_the_records_are_kept(self):
		with served(self.server):
			session = json.loads(jmap.session(MAILBOX).get_data())
		self.assertEqual(session["capabilities"].get(snooze.SNOOZE), {}, sorted(session["capabilities"]))
		takes = session["accounts"][self.aid]["accountCapabilities"][snooze.SNOOZE]
		self.assertEqual(takes["maxTries"], snooze.MAX_TRIES)
		self.assertEqual(session["primaryAccounts"][snooze.SNOOZE], self.aid)
		with patch.object(snooze, "ready", return_value=False), served(self.server):
			session = json.loads(jmap.session(MAILBOX).get_data())
		self.assertNotIn(snooze.SNOOZE, session["capabilities"], "a site whose migrate is still to run")

	# Putting away ------------------------------------------------------------------------------------------------

	def test_put_away_the_message_leaves_its_folder_for_the_snoozed_folder_and_is_recorded(self):
		made = self._put_away("Projects/Film")
		folder = self.folder()
		self.assertEqual(self.server.subjects("Projects/Film"), [])
		self.assertEqual(self.server.subjects(folder), ["hello"])
		self.assertEqual(self.server.made, [folder])
		self.assertIn(folder, self.server.subscribed, "other clients list it")
		self.assertEqual(made["state"], "waiting")
		self.assertEqual(made["mailboxId"], jmap.mailbox_id(folder))
		self.assertEqual(made["fromMailboxId"], jmap.mailbox_id("Projects/Film"))
		self.assertEqual(made["until"], utc(NOW + timedelta(hours=3)))
		self.assertEqual(made["emailId"], jmap.email_id(folder, VALIDITY, 1), "its new place")
		kept = self._record(made["id"])
		self.assertEqual((kept.user, kept.account, kept.message_id), (SHARED, MAILBOX, "hello@example.com"))
		self.assertEqual(
			(kept.folder, kept.uid, kept.uidvalidity, kept.from_folder),
			(folder, 1, VALIDITY, "Projects/Film"),
		)
		# A second one goes into the same folder: none is made again.
		self._put_away(name="other")
		self.assertEqual(self.server.made, [folder])
		self.assertEqual(self.server.subjects(folder), ["hello", "other"])

	def test_the_folder_is_found_again_by_its_name(self):
		self.server.create_folder("Plus tard")
		self.server.made.clear()
		self._put_away()
		self.assertEqual(self.server.made, [], "the folder another NeoMail made is taken")
		self.assertEqual(self.server.subjects("Plus tard"), ["hello"])

	def test_a_time_in_the_past_is_refused_and_nothing_moves(self):
		uid = self.server.put("INBOX", raw("hello"))
		for when in (NOW - timedelta(minutes=1), NOW, "tomorrow"):
			until = utc(when) if isinstance(when, datetime) else when
			done = self._set(create={"k": {"emailId": jmap.email_id("INBOX", VALIDITY, uid), "until": until}})
			self.assertEqual(done["notCreated"]["k"]["type"], "invalidProperties", when)
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertEqual(self.server.made, [])
		self.assertFalse(frappe.db.count(snooze.DOCTYPE, {"account": MAILBOX}))

	def test_a_time_beyond_five_years_is_brought_back_to_five_years(self):
		made = self._put_away(until=NOW + timedelta(days=9000))
		self.assertEqual(made["until"], utc(NOW + snooze.MAX_AHEAD))

	def test_two_tabs_putting_the_same_message_away_make_one_record(self):
		uid = self.server.put("INBOX", raw("hello"))
		old = jmap.email_id("INBOX", VALIDITY, uid)
		first = self._set(create={"a": {"emailId": old, "until": utc(NOW + timedelta(hours=1))}})["created"][
			"a"
		]
		# The other tab still has the message where it was, and its Message-ID.
		second = self._set(
			create={
				"b": {
					"emailId": old,
					"messageId": "<hello@example.com>",
					"until": utc(NOW + timedelta(hours=2)),
				}
			}
		)["created"]["b"]
		self.assertEqual(first["id"], second["id"])
		self.assertEqual(second["until"], utc(NOW + timedelta(hours=2)), "the later word holds")
		self.assertEqual(frappe.db.count(snooze.DOCTYPE, {"account": MAILBOX}), 1)
		# And put away again from the folder itself: the same record, another time.
		third = self._set(create={"c": {"emailId": first["emailId"], "until": utc(NOW + timedelta(hours=5))}})
		self.assertEqual(third["created"]["c"]["id"], first["id"])
		self.assertEqual(frappe.db.count(snooze.DOCTYPE, {"account": MAILBOX}), 1)
		self.assertEqual(self.server.subjects(self.folder()), ["hello"])

	def test_a_move_that_fails_records_nothing(self):
		uid = self.server.put("INBOX", raw("hello"))
		with patch.object(snooze.webmail, "_move_messages", side_effect=Exception("NO [CANNOT] refused")):
			done = self._set(
				create={
					"k": {
						"emailId": jmap.email_id("INBOX", VALIDITY, uid),
						"until": utc(NOW + timedelta(hours=1)),
					}
				}
			)
		self.assertEqual(done["notCreated"]["k"]["type"], "serverFail")
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertFalse(frappe.db.count(snooze.DOCTYPE, {"account": MAILBOX}))

	def test_a_record_that_cannot_be_written_moves_nothing(self):
		"""The record is written before the move: one that can't be written leaves the message where it was."""
		uid = self.server.put("INBOX", raw("hello"))
		with patch.object(snooze, "_record", side_effect=frappe.DuplicateEntryError("x")):
			done = self._set(
				create={
					"k": {
						"emailId": jmap.email_id("INBOX", VALIDITY, uid),
						"until": utc(NOW + timedelta(hours=1)),
					}
				}
			)
		self.assertEqual(done["notCreated"]["k"]["type"], "serverFail")
		self.assertEqual(self.server.subjects("INBOX"), ["hello"], "where it was")
		self.assertEqual(self.server.subjects(self.folder()), [])
		self.assertFalse(frappe.db.count(snooze.DOCTYPE, {"account": MAILBOX}))

	def test_a_connection_lost_during_the_move_keeps_the_record_and_the_message_still_comes_back(self):
		"""The connection went as the message was moved: nobody can say it was not, so its record stays, and the job finds the
		message by its Message-ID at its time."""
		uid = self.server.put("INBOX", raw("hello"), (b"\\Seen",))
		real = snooze.webmail._move_messages

		def moved_then_lost(client, uids, to):
			real(client, uids, to)
			raise snooze.webmail.WebmailConnectionLost("lost")

		with patch.object(snooze.webmail, "_move_messages", side_effect=moved_then_lost):
			done = self._set(
				create={
					"k": {
						"emailId": jmap.email_id("INBOX", VALIDITY, uid),
						"until": utc(NOW + timedelta(hours=1)),
					}
				}
			)
		self.assertEqual(done["notCreated"]["k"]["type"], "serverFail")
		self.assertEqual(self.server.subjects(self.folder()), ["hello"])
		kept = frappe.get_all(snooze.DOCTYPE, filters={"account": MAILBOX}, fields=["name", "state", "uid"])
		self.assertEqual(
			[(k.state, k.uid) for k in kept], [(snooze.WAITING, 0)], "not left without its record"
		)
		self.at(NOW + timedelta(hours=2))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])

	def test_a_message_gone_from_its_folder_or_without_message_id_is_refused(self):
		gone = self._set(
			create={
				"k": {"emailId": jmap.email_id("INBOX", VALIDITY, 99), "until": utc(NOW + timedelta(hours=1))}
			}
		)
		self.assertEqual(gone["notCreated"]["k"]["type"], "notFound")
		uid = self.server.put("INBOX", b"From: ann@example.com\r\nSubject: bare\r\n\r\nBody\r\n")
		bare = self._set(
			create={
				"k": {
					"emailId": jmap.email_id("INBOX", VALIDITY, uid),
					"until": utc(NOW + timedelta(hours=1)),
				}
			}
		)
		self.assertEqual(bare["notCreated"]["k"]["type"], "invalidProperties")
		self.assertEqual(self.server.subjects("INBOX"), ["bare"])

	# Coming back -------------------------------------------------------------------------------------------------

	def test_at_its_time_it_comes_back_unread_to_the_folder_it_came_from(self):
		made = self._put_away("Projects/Film")
		self.at(NOW + timedelta(hours=2, minutes=59))
		self.assertEqual(self._job(), [], "not yet")
		self.at(NOW + timedelta(hours=3))
		queued = self._job()
		self.assertEqual(
			queued,
			[
				{
					"account": MAILBOX,
					"queue": "short",
					"job_id": f"neomail_snooze_return:{MAILBOX}",
					"deduplicate": True,
				}
			],
		)
		self.assertEqual(self.server.subjects("Projects/Film"), ["hello"])
		self.assertNotIn(b"\\Seen", self.server.flags_of("Projects/Film", "hello"), "unread")
		self.assertEqual(self.server.subjects(self.folder()), [])
		kept = self._record(made["id"])
		self.assertEqual(kept.state, snooze.RETURNED)
		self.assertIsNone(kept.active_key)
		self.assertEqual(self._get()["list"], [], "no longer waiting")
		self.assertEqual(self._get(ids=[made["id"]])["list"][0]["state"], "returned")
		self.assertEqual(self._job(), [], "once")

	def test_nothing_due_is_one_read_and_no_job(self):
		self._put_away(until=NOW + timedelta(days=1))
		with patch.object(frappe, "enqueue") as enqueue:
			snooze.tick()
		enqueue.assert_not_called()

	def test_a_message_numbered_anew_is_found_by_its_message_id(self):
		made = self._put_away()
		folder = self.folder()
		self.server.put(folder, raw("other"))
		self.server.renumber(folder, VALIDITY + 5)
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertEqual(self.server.subjects(folder), ["other"], "only that one")
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_moved_or_deleted_meanwhile_it_is_called_off_and_nothing_reappears(self):
		made = self._put_away()
		folder = self.folder()
		# The person moved it on to Trash in another client.
		self.server.selected = folder
		self.server.copy([1], "Trash")
		self.server.folders[folder]["messages"].clear()
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), [])
		self.assertEqual(self.server.subjects("Trash"), ["hello"])
		self.assertEqual(self._record(made["id"]).state, snooze.CALLED_OFF)
		self.assertEqual(self._job(), [], "not looked for again")
		asked = self._set(update={made["id"]: {"state": "returned"}})["notUpdated"][made["id"]]
		self.assertEqual(asked["type"], "notFound")
		self.assertEqual(self.server.subjects("INBOX"), [])

	def test_its_folder_gone_it_comes_back_to_the_inbox(self):
		made = self._put_away("Projects/Film")
		self.server.drop_folder("Projects/Film")
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_brought_back_now_and_the_job_together_move_it_once(self):
		made = self._put_away()
		self.at(NOW + timedelta(hours=4))
		# The person's call holds the mailbox's lock: the job of that minute moves nothing.
		with snooze._locked(MAILBOX):
			self._job()
		self.assertEqual(self.server.subjects("INBOX"), [])
		said = self._set(update={made["id"]: {"state": "returned"}})["updated"][made["id"]]
		self.assertEqual(
			said,
			{
				"state": "returned",
				"emailId": jmap.email_id("INBOX", VALIDITY, 2),
				"mailboxId": jmap.mailbox_id("INBOX"),
			},
		)
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		# The job read its list before the person's call ended: it reads each record again before it moves.
		row = frappe.get_all(snooze.DOCTYPE, filters={"name": made["id"]}, fields=[*snooze.FIELDS, "account"])
		with patch.object(frappe, "get_all", return_value=row), served(self.server):
			frappe.set_user("Administrator")
			snooze.return_due(MAILBOX)
		self._as(SHARED)
		self.assertEqual(self.server.subjects("INBOX"), ["hello"], "once")
		self.assertEqual(
			self._set(update={made["id"]: {"state": "returned"}})["updated"],
			{made["id"]: {"state": "returned"}},
		)
		self.assertEqual(self.server.subjects("INBOX"), ["hello"], "asked twice, moved once")
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_another_time_and_called_off(self):
		made = self._put_away()
		later = NOW + timedelta(days=2)
		self._set(update={made["id"]: {"until": utc(later)}})
		self.assertEqual(self._get()["list"][0]["until"], utc(later))
		past = self._set(update={made["id"]: {"until": utc(NOW - timedelta(hours=1))}})
		self.assertEqual(past["notUpdated"][made["id"]]["type"], "invalidProperties")
		self.assertEqual(self._set(destroy=[made["id"]])["destroyed"], [made["id"]])
		self.assertEqual(self._record(made["id"]).state, snooze.CALLED_OFF)
		self.assertEqual(self.server.subjects(self.folder()), ["hello"], "called off, it stays where it is")
		self.at(NOW + timedelta(days=3))
		self.assertEqual(self._job(), [])

	def test_a_change_of_the_clocks_between_the_choice_and_the_return(self):
		"""Chosen on 24 October (Zurich at UTC+2) for 08:00 on Monday 26 October (Zurich at UTC+1 since the 25th): NeoMail
		sends the instant, 07:00 UTC, and it comes back then, not an hour early or late."""
		self.at(datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc))
		# As NeoMail sends it: the instant, with its offset (08:00 at UTC+1), kept in UTC.
		made = self._put_away(until=datetime(2026, 10, 26, 8, 0, tzinfo=timezone(timedelta(hours=1))))
		self.assertEqual(self._record(made["id"]).until_utc, datetime(2026, 10, 26, 7, 0))
		self.at(datetime(2026, 10, 26, 6, 59, tzinfo=timezone.utc))
		self.assertEqual(self._job(), [], "not an hour early")
		self.at(datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc))
		self.assertEqual(len(self._job()), 1)
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])

	def test_a_mail_server_that_refuses_is_tried_again_then_the_record_fails_and_the_message_stays(self):
		started = frappe.utils.now_datetime()
		made = self._put_away()
		refused = snooze.webmail.WebmailAuthenticationError("password")
		moment = NOW + timedelta(hours=4)
		for attempt in range(1, snooze.MAX_TRIES + 1):
			self.at(moment)
			with patch.object(snooze.webmail, "imap_session", side_effect=refused):
				self.assertEqual(len(self._job()), 1, attempt)
			kept = self._record(made["id"])
			self.assertEqual(kept.tries, attempt)
			if attempt < snooze.MAX_TRIES:
				self.assertEqual(kept.state, snooze.WAITING)
				self.at(moment + timedelta(seconds=30))
				self.assertEqual(self._job(), [], "not again before its next try")
				moment = kept.next_try.replace(tzinfo=timezone.utc)
		self.assertEqual(kept.state, snooze.FAILED)
		self.assertTrue(
			frappe.db.exists(
				"Error Log",
				{"method": "NeoMail: a snoozed message could not come back", "creation": (">=", started)},
			),
			"the Error Log says so",
		)
		self.assertEqual(self.server.subjects(self.folder()), ["hello"], "not lost")
		seen = self._get()["list"]
		self.assertEqual(
			[(r["id"], r["state"]) for r in seen], [(made["id"], "failed")], "the person sees it"
		)
		self.assertTrue(seen[0]["error"])
		self.at(moment + timedelta(hours=1))
		self.assertEqual(self._job(), [], "no endless retry")
		# The person brings it back by hand once the mailbox is right again.
		self._set(update={made["id"]: {"state": "returned"}})
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])

	def test_a_folder_the_server_refuses_for_now_is_tried_again_not_called_off(self):
		made = self._put_away()
		folder = self.folder()
		real = self.server.select_folder
		refusals = []

		def refuse_once(name, readonly=False):
			if name == folder and not refusals:
				refusals.append(name)
				raise Exception("NO [UNAVAILABLE] Temporary System Error")
			return real(name, readonly)

		self.at(NOW + timedelta(hours=4))
		with patch.object(self.server, "select_folder", side_effect=refuse_once):
			self._job()
		kept = self._record(made["id"])
		self.assertEqual(
			(kept.state, kept.tries), (snooze.WAITING, 1), "a try that failed, not a message gone"
		)
		self.assertEqual(self.server.subjects("INBOX"), [])
		self.at(kept.next_try.replace(tzinfo=timezone.utc))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_the_folder_renamed_meanwhile_its_messages_are_found_and_come_back(self):
		made = self._put_away()
		folder = self.folder()
		other = "Snoozed" if folder.lower() != "snoozed" else "Plus tard"
		self.server.folders[other] = self.server.folders.pop(folder)
		self.server.validity[other] = VALIDITY + 1
		self.server.next_uid[other] = self.server.next_uid.pop(folder)
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_two_copies_of_one_message_in_two_folders_make_two_records_and_both_come_back(self):
		"""A message to oneself, in Sent and in the Inbox: each copy is put away, and each comes back to its folder."""
		inbox = self.server.put("INBOX", raw("hello"))
		sent = self.server.put("Sent", raw("hello"))
		until = utc(NOW + timedelta(hours=1))
		done = self._set(
			create={
				"a": {"emailId": jmap.email_id("INBOX", VALIDITY, inbox), "until": until},
				"b": {"emailId": jmap.email_id("Sent", VALIDITY, sent), "until": until},
			}
		)
		self.assertEqual(sorted(done["created"]), ["a", "b"], done)
		self.assertNotEqual(done["created"]["a"]["id"], done["created"]["b"]["id"])
		self.assertEqual(self.server.subjects(self.folder()), ["hello", "hello"])
		self.at(NOW + timedelta(hours=2))
		self._job()
		self.assertEqual(
			(self.server.subjects("INBOX"), self.server.subjects("Sent")), (["hello"], ["hello"])
		)
		self.assertEqual(self.server.subjects(self.folder()), [])

	def test_one_that_failed_put_away_again_waits_again_in_its_record(self):
		made = self._put_away("Projects/Film")
		frappe.db.set_value(
			snooze.DOCTYPE,
			made["id"],
			{"state": snooze.FAILED, "tries": 3, "active_key": None, "last_error": "connection"},
		)
		frappe.db.commit()  # nosemgrep: as the job leaves a record that failed
		again = self._set(create={"k": {"emailId": made["emailId"], "until": utc(NOW + timedelta(days=1))}})
		self.assertEqual(again["created"]["k"]["id"], made["id"], "the same record")
		kept = self._record(made["id"])
		self.assertEqual((kept.state, kept.tries, kept.from_folder), (snooze.WAITING, 0, "Projects/Film"))
		self.assertEqual([r["state"] for r in self._get()["list"]], ["waiting"], "no « Pas revenu » left")

	def test_another_time_forgets_the_tries(self):
		made = self._put_away()
		frappe.db.set_value(snooze.DOCTYPE, made["id"], {"tries": 2, "next_try": NOW.replace(tzinfo=None)})
		frappe.db.commit()  # nosemgrep: as a job leaves a record that failed twice
		self._set(update={made["id"]: {"until": utc(NOW + timedelta(days=2))}})
		kept = self._record(made["id"])
		self.assertEqual((kept.tries, kept.next_try), (0, None))

	def test_a_move_a_server_without_move_left_half_done_is_finished_not_copied_again(self):
		made = self._put_away()
		folder = self.folder()
		# The last try copied it to the Inbox, marked it deleted here, and the expunge failed.
		self.server.selected = folder
		self.server.copy([1], "INBOX")
		self.server.folders[folder]["messages"][1]["flags"].add(b"\\Deleted")
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"], "one copy, not two")
		self.assertEqual(self.server.subjects(folder), [])
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_a_server_whose_folders_lie_under_its_inbox_gets_the_folder_there(self):
		class Dotted(Server):
			def list_folders(self, *args, **kwargs):
				return [(f["flags"], b".", name) for name, f in self.folders.items()]

			def namespace(self):
				return SimpleNamespace(personal=((b"INBOX.", b"."),), other=None, shared=None)

		self.server = Dotted()
		self._put_away()
		self.assertEqual(self.server.made, ["INBOX." + self.folder()])
		self.assertEqual(self.server.subjects("INBOX." + self.folder()), ["hello"])

	def test_a_person_deleted_what_they_put_away_goes_on_as_the_owners(self):
		made = self._put_away()
		snooze.on_user_trash(SimpleNamespace(name=SHARED))
		kept = self._record(made["id"])
		self.assertEqual((kept.user, kept.state), (OWNER, snooze.WAITING))
		self.assertTrue(kept.active_key)
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])

	def test_a_mailbox_renamed_keeps_its_records_and_one_gone_is_not_tried_forever(self):
		made = self._put_away()
		snooze.on_account_rename(None, None, MAILBOX, "renamed_box@webmail.test")
		kept = self._record(made["id"])
		self.assertEqual(kept.account, "renamed_box@webmail.test")
		self.assertEqual(
			kept.active_key, snooze._key(SHARED, "renamed_box@webmail.test", kept.message_id, "INBOX")
		)
		# That name is no mailbox here: the job calls it off rather than trying every minute.
		self.at(NOW + timedelta(hours=4))
		snooze.return_due("renamed_box@webmail.test")
		self.assertEqual(self._record(made["id"]).state, snooze.CALLED_OFF)

	def test_a_server_with_move_puts_away_and_brings_back_the_same(self):
		self.server = Server(move=True)
		made = self._put_away("Projects/Film")
		self.assertEqual(self.server.subjects(self.folder()), ["hello"])
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("Projects/Film"), ["hello"])
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_taken_out_by_hand_then_put_away_from_elsewhere_it_comes_back_at_its_new_time_and_place(self):
		first = self._put_away(until=NOW + timedelta(hours=1))
		folder = self.folder()
		# In NeoMail, the person drags it from « Plus tard » to Projects/Film, then puts it away from there until tomorrow.
		self.server.selected = folder
		self.server.copy([1], "Projects/Film")
		self.server.folders[folder]["messages"].clear()
		uid = max(self.server.folders["Projects/Film"]["messages"])
		second = self._set(
			create={
				"k": {
					"emailId": jmap.email_id("Projects/Film", VALIDITY, uid),
					"until": utc(NOW + timedelta(days=1)),
				}
			}
		)["created"]["k"]
		self.assertEqual(self._record(first["id"]).state, snooze.CALLED_OFF, "the first time no longer holds")
		self.at(NOW + timedelta(hours=2))
		self._job()
		self.assertEqual(self.server.subjects(folder), ["hello"], "not back an hour later")
		self.at(NOW + timedelta(days=1, minutes=1))
		self._job()
		self.assertEqual(self.server.subjects("Projects/Film"), ["hello"])
		self.assertEqual(self._record(second["id"]).state, snooze.RETURNED)

	def test_a_copy_made_and_its_original_not_taken_out_is_taken_back_and_nothing_kept(self):
		"""A server without MOVE copied the message, then would not mark the original deleted."""
		uid = self.server.put("INBOX", raw("hello"))
		server = self.server

		def refused_in_the_inbox(uids):
			if server.selected == "INBOX":
				raise Exception("NO [NOPERM] read-only")
			return Server.delete_messages(server, uids)

		with patch.object(server, "delete_messages", side_effect=refused_in_the_inbox):
			done = self._set(
				create={
					"k": {
						"emailId": jmap.email_id("INBOX", VALIDITY, uid),
						"until": utc(NOW + timedelta(hours=1)),
					}
				}
			)
		self.assertEqual(done["notCreated"]["k"]["type"], "serverFail")
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])
		self.assertEqual(self.server.subjects(self.folder()), [], "no copy left away without its record")
		self.assertFalse(frappe.db.count(snooze.DOCTYPE, {"account": MAILBOX}))

	def test_a_return_whose_connection_went_after_the_copy_is_finished_not_copied_again(self):
		made = self._put_away()
		folder = self.folder()
		real = snooze.webmail._move_messages

		def copied_then_lost(client, uids, to):
			client.copy(uids, to)
			raise snooze.webmail.WebmailConnectionLost("lost")

		self.at(NOW + timedelta(hours=4))
		with patch.object(snooze.webmail, "_move_messages", side_effect=copied_then_lost):
			self._job()
		self.assertEqual(self._record(made["id"]).tries, 1)
		self.at(self._record(made["id"]).next_try.replace(tzinfo=timezone.utc))
		with patch.object(snooze.webmail, "_move_messages", side_effect=real):
			self._job()
		self.assertEqual(self.server.subjects("INBOX"), ["hello"], "one copy, not two")
		self.assertEqual(self.server.subjects(folder), [])
		self.assertEqual(self._record(made["id"]).state, snooze.RETURNED)

	def test_deleted_meanwhile_in_another_client_it_does_not_come_back(self):
		made = self._put_away()
		self.server.folders[self.folder()]["messages"][1]["flags"].add(b"\\Deleted")
		self.at(NOW + timedelta(hours=4))
		self._job()
		self.assertEqual(self.server.subjects("INBOX"), [])
		self.assertEqual(self._record(made["id"]).state, snooze.CALLED_OFF)

	def test_one_that_failed_put_away_again_beside_one_that_waits_is_one_record_that_waits(self):
		waiting = self._put_away()
		folder = self.folder()
		# A second copy of the same message in the folder, whose record failed.
		uid = self.server.put(folder, raw("hello"))
		failed = frappe.get_doc(
			{
				"doctype": snooze.DOCTYPE,
				"user": SHARED,
				"account": MAILBOX,
				"message_id": "hello@example.com",
				"folder": folder,
				"uid": uid,
				"uidvalidity": VALIDITY,
				"from_folder": "INBOX",
				"until_utc": NOW.replace(tzinfo=None),
				"state": snooze.FAILED,
				"tries": 3,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: as the job leaves a record that failed
		again = self._set(
			create={
				"k": {"emailId": jmap.email_id(folder, VALIDITY, uid), "until": utc(NOW + timedelta(days=1))}
			}
		)
		self.assertIn("k", again["created"] or {}, again)
		self.assertEqual(again["created"]["k"]["id"], waiting["id"], "the one that waits takes the time")
		self.assertEqual(self._record(failed.name).state, snooze.CALLED_OFF)
		self.assertEqual([r["state"] for r in self._get()["list"]], ["waiting"])

	def test_past_the_calls_time_the_rest_is_refused_as_not_now(self):
		uid = self.server.put("INBOX", raw("hello"))
		with patch.object(snooze, "CALL_BUDGET_S", -1):
			done = self._set(
				create={
					"k": {
						"emailId": jmap.email_id("INBOX", VALIDITY, uid),
						"until": utc(NOW + timedelta(hours=1)),
					}
				}
			)
		self.assertEqual(done["notCreated"]["k"]["type"], "serverUnavailable")
		self.assertEqual(self.server.subjects("INBOX"), ["hello"])

	def test_a_create_that_is_no_object_is_refused_as_such(self):
		done = self._set(create={"k": "not an object"})
		self.assertEqual(done["notCreated"]["k"]["type"], "invalidProperties")

	# Whose -------------------------------------------------------------------------------------------------------

	def test_another_persons_records_can_be_neither_read_nor_changed(self):
		made = self._put_away()
		# Staff who own the mailbox, but did not put it away.
		self._as(OWNER)
		self.assertEqual(self._get()["list"], [])
		self.assertEqual(self._get(ids=[made["id"]])["notFound"], [made["id"]])
		changed = self._set(
			update={made["id"]: {"until": utc(NOW + timedelta(days=9))}}, destroy=[made["id"]]
		)
		self.assertEqual(changed["notUpdated"][made["id"]]["type"], "notFound")
		self.assertEqual(changed["notDestroyed"][made["id"]]["type"], "notFound")
		back = self._set(update={made["id"]: {"state": "returned"}})
		self.assertEqual(back["notUpdated"][made["id"]]["type"], "notFound")
		# Staff without the mailbox.
		self._as(STRANGER)
		refused = self._calls(("NeomailSnooze/get", {"accountId": self.aid}))[0]
		self.assertEqual((refused[0], refused[1]["type"]), ("error", "forbidden"))
		# A Website User, with a token or not, and nobody at all.
		self._as(PORTAL)
		self.assertEqual(
			self._calls(("NeomailSnooze/get", {"accountId": self.aid}), status=403).status_code, 403
		)
		frappe.set_user("Guest")
		frappe.local.flags.mailcraft_jmap_user = None
		self.assertEqual(
			self._calls(("NeomailSnooze/get", {"accountId": self.aid}), status=403).status_code, 403
		)
		# Nothing changed.
		self._as(SHARED)
		kept = self._record(made["id"])
		self.assertEqual(
			(kept.state, kept.until_utc), (snooze.WAITING, (NOW + timedelta(hours=3)).replace(tzinfo=None))
		)
		self.assertEqual(self.server.subjects(self.folder()), ["hello"])

	def test_the_folder_is_hidden_from_nothing(self):
		self._put_away()
		folder = self.folder()
		listed = self._calls(("Mailbox/get", {"accountId": self.aid}))[0][1]["list"]
		entry = next(e for e in listed if e["id"] == jmap.mailbox_id(folder))
		self.assertEqual((entry["role"], entry["isSubscribed"], entry["totalEmails"]), (None, True, 1))
		self.assertIn(folder, self.server.subscribed)
		self.assertEqual(self._get()["mailboxId"], jmap.mailbox_id(folder))
