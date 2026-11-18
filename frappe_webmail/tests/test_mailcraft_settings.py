# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What NeoMail keeps of a person's window between two visits (mailcraft_settings, maintenance#1956): their rules and
categories, and the Safe Senders and Blocked Senders of each of their mailboxes and what was marked done in it.

Every mailbox offers it; the person reads and writes their own, in a mailbox they may open: a mailbox shared with them
holds their own lists, not its owner's, and a mailbox of somebody else is refused. What is not a rule, a category, a
list of addresses or a list of messages marked done is refused, and so is too much of it. A site whose records have no
field for what was marked done yet (its `bench migrate` to come) neither says it nor takes it. A person or a mailbox
deleted takes its records with it.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_settings
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import mailcraft_settings as settings
from frappe_webmail.tests.test_mailcraft_contacts import _mailbox, _user

OWNER = "mailcraft_settings_owner@example.com"  # of the desk, owns OWNER_BOX and SECOND_BOX, shares OWNER_BOX
COLLEAGUE = "mailcraft_settings_colleague@example.com"  # of the desk, OWNER_BOX is shared with them
STRANGER = "mailcraft_settings_stranger@example.com"  # of the desk, nothing shared
OWNER_BOX = "mailcraft_settings_owner@webmail.test"
SECOND_BOX = "mailcraft_settings_second@webmail.test"
STRANGER_BOX = "mailcraft_settings_stranger@webmail.test"
GONE_BOX = "mailcraft_settings_gone@webmail.test"
USERS = (OWNER, COLLEAGUE, STRANGER)

RULE = {
	"name": "Invoices",
	"enabled": True,
	"conditions": [{"type": "subjectContains", "value": "invoice"}],
	"actions": [{"type": "moveTo", "value": {"mailbox": OWNER_BOX, "folder": "MSW52b2ljZXM"}}],
	"stop": False,
}
CATEGORY = {"name": "Customers", "color": [46, 139, 87]}
DONE = {
	"messageId": "plans.42@example.com",
	"from": "MSU5CT1g",
	"at": 1_792_000_000,
	"who": "Grace",
	"subject": "The plans",
}


class TestMailCraftSettings(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for user in USERS:
			_user(user, ["Sales User"])
		_mailbox(OWNER_BOX, OWNER, shared_with=(COLLEAGUE,))
		_mailbox(SECOND_BOX, OWNER)
		_mailbox(STRANGER_BOX, STRANGER)
		frappe.db.commit()  # nosemgrep: the users and mailboxes the requests below read

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete(settings.DOCTYPE, {"user": ["in", USERS]})
		frappe.db.commit()  # nosemgrep: what the methods committed goes too
		super().tearDownClass()

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
		self.trial.start()
		frappe.set_user("Administrator")
		frappe.db.delete(settings.DOCTYPE, {"user": ["in", USERS]})
		frappe.db.commit()  # nosemgrep: each test starts from nothing kept

	def tearDown(self):
		self.trial.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.set_user("Administrator")

	def _as(self, user):
		frappe.set_user(user)
		frappe.local.flags.mailcraft_jmap_user = user

	def _calls(self, *calls):
		body = json.dumps(
			{
				"using": [jmap.CORE, settings.SETTINGS],
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
		with patch.object(frappe.local, "request", request, create=True):
			answer = jmap.api()
		self.assertEqual(answer.status_code, 200, answer.get_data())
		return json.loads(answer.get_data())["methodResponses"]

	def _get(self, box):
		answer = self._calls(("NeomailSettings/get", {"accountId": jmap.account_id(box)}))[0]
		self.assertEqual(answer[0], "NeomailSettings/get", answer)
		return answer[1]

	def _set(self, box, **patch_):
		args = {"accountId": jmap.account_id(box), "update": {settings.SINGLETON: patch_}}
		answer = self._calls(("NeomailSettings/set", args))[0]
		self.assertEqual(answer[0], "NeomailSettings/set", answer)
		return answer[1]

	def test_every_mailbox_offers_it(self):
		self._as(OWNER)
		for box in (OWNER_BOX, SECOND_BOX):
			session = json.loads(jmap.session(box).get_data())
			aid = jmap.account_id(box)
			self.assertIn(settings.SETTINGS, session["capabilities"])
			self.assertEqual(session["primaryAccounts"][settings.SETTINGS], aid)
			taken = session["accounts"][aid]["accountCapabilities"][settings.SETTINGS]
			self.assertEqual(taken["maxSenders"], settings.MAX_SENDERS)
			self.assertEqual(taken["maxDone"], settings.MAX_DONE)

	def test_nothing_kept_says_so(self):
		self._as(OWNER)
		got = self._get(OWNER_BOX)
		self.assertEqual(
			got["list"],
			[
				{
					"id": "singleton",
					"rules": None,
					"categories": None,
					"safeSenders": [],
					"blockedSenders": [],
					"done": [],
				}
			],
		)

	def test_what_is_written_is_read_at_the_next_visit(self):
		self._as(OWNER)
		before = self._get(OWNER_BOX)["state"]
		done = self._set(
			OWNER_BOX,
			rules=[RULE],
			categories=[CATEGORY],
			safeSenders=["boss@example.com"],
			blockedSenders=["spam.example"],
		)
		self.assertEqual(done["updated"], {"singleton": None}, done)
		self.assertEqual(done["oldState"], before)
		self.assertNotEqual(done["newState"], before)
		got = self._get(OWNER_BOX)["list"][0]
		self.assertEqual(got["rules"], [RULE])
		self.assertEqual(got["categories"], [CATEGORY])
		self.assertEqual(
			(got["safeSenders"], got["blockedSenders"]), (["boss@example.com"], ["spam.example"])
		)
		self.assertEqual(got, self._get(OWNER_BOX)["list"][0], "read twice, the same")

	def test_the_rules_and_categories_are_the_persons_the_lists_each_mailboxs(self):
		self._as(OWNER)
		self._set(OWNER_BOX, rules=[RULE], categories=[CATEGORY], blockedSenders=["spam.example"])
		second = self._get(SECOND_BOX)["list"][0]
		self.assertEqual((second["rules"], second["categories"]), ([RULE], [CATEGORY]), "the whole window's")
		self.assertEqual(second["blockedSenders"], [], "another mailbox has its own lists")
		self._set(SECOND_BOX, blockedSenders=["other.example"])
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["blockedSenders"], ["spam.example"])

	def test_a_shared_mailbox_holds_each_persons_own_lists(self):
		self._as(OWNER)
		self._set(OWNER_BOX, safeSenders=["owner-friend@example.com"], rules=[RULE])
		self._as(COLLEAGUE)
		got = self._get(OWNER_BOX)["list"][0]
		self.assertEqual((got["safeSenders"], got["rules"]), ([], None), "nothing of the owner's")
		self._set(OWNER_BOX, safeSenders=["colleague-friend@example.com"])
		self._as(OWNER)
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["safeSenders"], ["owner-friend@example.com"])

	def test_somebody_elses_mailbox_is_refused(self):
		self._as(STRANGER)
		for name, args in (
			("NeomailSettings/get", {"accountId": jmap.account_id(OWNER_BOX)}),
			(
				"NeomailSettings/set",
				{
					"accountId": jmap.account_id(OWNER_BOX),
					"update": {"singleton": {"blockedSenders": ["x.example"]}},
				},
			),
		):
			answer = self._calls((name, args))[0]
			self.assertEqual((answer[0], answer[1]["type"]), ("error", "forbidden"), answer)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists(settings.DOCTYPE, {"user": STRANGER}))
		self._as(STRANGER)
		missing = self._calls(("NeomailSettings/get", {"accountId": "Anope"}))[0]
		self.assertEqual(missing[0], "error")

	def test_what_is_not_a_rule_a_category_or_a_list_is_refused(self):
		self._as(OWNER)
		for patch_ in (
			{"rules": "all"},
			{"rules": [{"name": 3}]},
			{"rules": [{"name": "x", "actions": "delete"}]},
			{"rules": [RULE] * (settings.MAX_RULES + 1)},
			{
				"rules": [
					{
						**RULE,
						"name": "x" * 100,
						"conditions": [{"type": "bodyContains", "value": "y" * 9000}] * 60,
					}
				]
			},
			{"categories": [{"name": "", "color": [1, 2, 3]}]},
			{"categories": [{"name": "Red", "color": [1, 2]}]},
			{"categories": [{"name": "Red", "color": [1, 2, 300]}]},
			{"categories": [{"name": "Red", "color": [True, 2, 3]}]},
			{"blockedSenders": ["two words@example.com"]},
			{"blockedSenders": [""]},
			{"blockedSenders": ["x" * 400]},
			{"safeSenders": ["a@example.com"] * (settings.MAX_SENDERS + 1)},
			{"signatures": []},
		):
			done = self._set(OWNER_BOX, **patch_)
			self.assertIsNone(done["updated"], patch_)
			self.assertEqual(done["notUpdated"]["singleton"]["type"], "invalidProperties", patch_)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists(settings.DOCTYPE, {"user": OWNER}), "nothing was written")

	def test_ids_that_are_not_a_list_of_strings_are_refused(self):
		self._as(OWNER)
		for ids in ("singleton", 3, [3], ["x"] * 51):
			args = {"accountId": jmap.account_id(OWNER_BOX), "ids": ids}
			answer = self._calls(("NeomailSettings/get", args))[0]
			self.assertEqual((answer[0], answer[1]["type"]), ("error", "invalidArguments"), ids)
		got = self._calls(
			("NeomailSettings/get", {"accountId": jmap.account_id(OWNER_BOX), "ids": ["other"]})
		)[0][1]
		self.assertEqual((got["list"], got["notFound"]), ([], ["other"]))

	def test_one_record_per_person_and_mailbox(self):
		self._as(OWNER)
		self._set(OWNER_BOX, categories=[CATEGORY], blockedSenders=["a.example"])
		self._set(OWNER_BOX, categories=[], blockedSenders=["b.example"])
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count(settings.DOCTYPE, {"user": OWNER, "account": settings.PERSON}), 1)
		self.assertEqual(frappe.db.count(settings.DOCTYPE, {"user": OWNER, "account": OWNER_BOX}), 1)
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc({"doctype": settings.DOCTYPE, "user": OWNER, "account": OWNER_BOX}).insert(
				ignore_permissions=True
			)
		frappe.db.rollback()

	def test_the_one_object_is_neither_made_nor_destroyed(self):
		self._as(OWNER)
		args = {
			"accountId": jmap.account_id(OWNER_BOX),
			"create": {"k": {"rules": []}},
			"destroy": ["singleton"],
			"update": {"other": {"rules": []}},
		}
		answer = self._calls(("NeomailSettings/set", args))[0][1]
		self.assertEqual(answer["notCreated"], {"k": {"type": "forbidden"}})
		self.assertEqual(answer["notDestroyed"], {"singleton": {"type": "forbidden"}})
		self.assertEqual(answer["notUpdated"], {"other": {"type": "notFound"}})

	def test_a_change_from_an_older_state_is_refused_when_asked(self):
		self._as(OWNER)
		old = self._get(OWNER_BOX)["state"]
		self._set(OWNER_BOX, categories=[CATEGORY])
		args = {
			"accountId": jmap.account_id(OWNER_BOX),
			"ifInState": old,
			"update": {"singleton": {"categories": []}},
		}
		answer = self._calls(("NeomailSettings/set", args))[0]
		self.assertEqual((answer[0], answer[1]["type"]), ("error", "stateMismatch"))
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["categories"], [CATEGORY])

	def test_a_mailbox_or_a_person_deleted_takes_its_records(self):
		frappe.set_user("Administrator")
		_mailbox(GONE_BOX, STRANGER)
		self._as(STRANGER)
		self._set(GONE_BOX, blockedSenders=["x.example"], categories=[CATEGORY])
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists(settings.DOCTYPE, {"user": STRANGER, "account": GONE_BOX}))
		frappe.delete_doc("Webmail Account", GONE_BOX, ignore_permissions=True, force=True)
		self.assertFalse(frappe.db.exists(settings.DOCTYPE, {"account": GONE_BOX}))
		self.assertTrue(frappe.db.exists(settings.DOCTYPE, {"user": STRANGER}), "the person's own stays")
		settings.on_user_trash(SimpleNamespace(name=STRANGER))
		self.assertFalse(frappe.db.exists(settings.DOCTYPE, {"user": STRANGER}))

	def test_only_a_system_manager_reads_the_records_in_the_desk(self):
		self._as(OWNER)
		self._set(OWNER_BOX, categories=[CATEGORY])
		frappe.set_user(OWNER)
		self.assertFalse(frappe.has_permission(settings.DOCTYPE, "read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(settings.DOCTYPE)

	def test_what_was_marked_done_is_each_mailboxs_and_each_persons(self):
		self._as(OWNER)
		later = {**DONE, "messageId": "offer.7@example.com", "at": DONE["at"] + 60}
		done = self._set(OWNER_BOX, done=[later, DONE], blockedSenders=["spam.example"])
		self.assertEqual(done["updated"], {"singleton": None}, done)
		got = self._get(OWNER_BOX)["list"][0]
		self.assertEqual((got["done"], got["blockedSenders"]), ([later, DONE], ["spam.example"]))
		self.assertEqual(self._get(SECOND_BOX)["list"][0]["done"], [], "another mailbox has its own")
		# Changed: what it holds changes, and the state with it.
		before = self._get(OWNER_BOX)["state"]
		self._set(OWNER_BOX, done=[DONE])
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["done"], [DONE])
		self.assertNotEqual(self._get(OWNER_BOX)["state"], before)
		# A mailbox shared with a colleague: their own, not the owner's.
		self._as(COLLEAGUE)
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["done"], [])
		self._set(OWNER_BOX, done=[later])
		self._as(OWNER)
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["done"], [DONE])

	def test_what_is_not_a_list_of_messages_marked_done_is_refused(self):
		self._as(OWNER)
		for done in (
			"all",
			[DONE] * (settings.MAX_DONE + 1),
			["plans.42@example.com"],
			[{**DONE, "messageId": ""}],
			[{**DONE, "messageId": 42}],
			[{**DONE, "messageId": "x" * 1_001}],
			[{key: value for key, value in DONE.items() if key != "at"}],
			[{**DONE, "at": "today"}],
			[{**DONE, "at": True}],
			[{**DONE, "at": -1}],
			[{**DONE, "who": 3}],
			[{**DONE, "subject": "s" * 1_001}],
			# (Each entry within its bounds, but too much of them: past MAX_DONE_BYTES.)
			[
				{
					**DONE,
					"messageId": f"m{n}@example.com",
					"from": "f" * 1_000,
					"subject": "s" * 1_000,
					"who": "w" * 1_000,
				}
				for n in range(200)
			],
		):
			answer = self._set(OWNER_BOX, done=done)
			self.assertIsNone(answer["updated"], str(done)[:80])
			self.assertEqual(answer["notUpdated"]["singleton"]["type"], "invalidProperties", str(done)[:80])
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists(settings.DOCTYPE, {"user": OWNER}), "nothing was written")

	def test_each_message_marked_done_is_kept_once_and_in_its_shape(self):
		self._as(OWNER)
		other = {**DONE, "messageId": "offer.7@example.com"}
		# Whatever else an entry carries is not kept (a number JSON can't hold would fail in the database), and a message
		# named twice is kept as it is named first.
		loose = {**DONE, "extra": {"deep": [1]}, "score": float("nan")}
		bare = {"messageId": "bare.1@example.com", "at": DONE["at"]}
		answer = self._set(OWNER_BOX, done=[loose, {**DONE, "at": DONE["at"] - 60}, other, bare])
		self.assertEqual(answer["updated"], {"singleton": None}, answer)
		got = self._get(OWNER_BOX)
		whole_bare = {**bare, "from": "", "who": "", "subject": ""}
		self.assertEqual(got["list"][0]["done"], [DONE, other, whole_bare])
		self.assertEqual(self._get(OWNER_BOX)["state"], got["state"], "read twice, the same state")
		# As many as NeoMail keeps go through.
		most = [{**DONE, "messageId": f"m{n}@example.com"} for n in range(settings.MAX_DONE)]
		self.assertEqual(self._set(OWNER_BOX, done=most)["updated"], {"singleton": None})
		self.assertEqual(len(self._get(OWNER_BOX)["list"][0]["done"]), settings.MAX_DONE)

	def test_a_site_still_to_migrate_neither_says_nor_takes_what_was_marked_done(self):
		self._as(OWNER)
		with patch.object(settings, "_keeps_done", return_value=False):
			session = json.loads(jmap.session(OWNER_BOX).get_data())
			taken = session["accounts"][jmap.account_id(OWNER_BOX)]["accountCapabilities"][settings.SETTINGS]
			self.assertNotIn("maxDone", taken, "its session doesn't offer what it refuses")
			self.assertEqual(taken["maxSenders"], settings.MAX_SENDERS)
			got = self._get(OWNER_BOX)["list"][0]
			self.assertNotIn("done", got, "NeoMail then never sends it")
			answer = self._set(OWNER_BOX, done=[DONE])
			self.assertEqual(answer["notUpdated"]["singleton"]["type"], "invalidProperties")
			self.assertEqual(
				self._set(OWNER_BOX, blockedSenders=["spam.example"])["updated"], {"singleton": None}
			)
			self.assertEqual(self._get(OWNER_BOX)["list"][0]["blockedSenders"], ["spam.example"])
		self.assertEqual(self._get(OWNER_BOX)["list"][0]["done"], [])

	def test_a_site_without_the_table_yet_doesnt_fail_on_what_was_marked_done(self):
		with patch.object(frappe.db, "table_exists", return_value=False):
			self.assertFalse(settings._keeps_done())
