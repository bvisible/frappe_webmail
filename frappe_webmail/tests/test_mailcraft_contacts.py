# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The instance's contacts as NeoMail's address book (mailcraft_contacts, JMAP for Contacts; maintenance#1630).

One mailbox of the person offers it; its cards are the contacts the person may read, with their addresses, phone
numbers, company and title. NeoMail creates and changes contacts with the person's own rights (Jérémy, 17.10), never
deletes one; a create sent again (its answer lost) comes back to the same contact by its card's uid. The queries follow
RFC 8620 §5.5 (a limit of 0, a position from the end, the total when asked).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_contacts
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_contacts as contacts
from frappe_webmail import mailcraft_jmap as jmap

READER = (
	"mailcraft_contacts_reader@example.com"  # Sales User: reads the contacts; owns BOX, is given SHARED_BOX
)
LIMITED = "mailcraft_contacts_limited@example.com"  # Sales User, its contacts restricted to Alpha
PLAIN = "mailcraft_contacts_plain@example.com"  # of the desk, no right to contacts
BOX = "mailcraft_contacts_box@webmail.test"
SHARED_BOX = "mailcraft_contacts_shared@webmail.test"
LIMITED_BOX = "mailcraft_contacts_limited@webmail.test"
PLAIN_BOX = "mailcraft_contacts_plain@webmail.test"


def _user(email, roles):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	for role in roles:
		user.append("roles", {"role": role})
	user.insert(ignore_permissions=True)


def _mailbox(email, owner, shared_with=()):
	if frappe.db.exists("Webmail Account", email):
		return
	account = frappe.get_doc(
		{
			"doctype": "Webmail Account",
			"email": email,
			"user": owner,
			"sender_name": "Box",
			"auth_type": "Password",
			"imap_host": "imap.test.local",
			"imap_password": "x",
			"smtp_host": "smtp.test.local",
			"smtp_password": "x",
			"enabled": 1,
		}
	)
	for user in shared_with:
		account.append("allowed_users", {"user": user})
	account.insert(ignore_permissions=True)


def _contact(first, last, email, mobile=None, company=None, title=None):
	existing = frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first,
			"last_name": last,
			"company_name": company,
			"designation": title,
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"phone_nos": [{"phone": mobile, "is_primary_mobile_no": 1}] if mobile else [],
		}
	)
	return doc.insert(ignore_permissions=True).name


class TestMailCraftContacts(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_user(READER, ["Sales User"])
		_user(LIMITED, ["Sales User"])
		_user(PLAIN, ["Blogger"])
		_mailbox(BOX, READER)
		_mailbox(SHARED_BOX, PLAIN, shared_with=[READER])
		_mailbox(LIMITED_BOX, LIMITED)
		_mailbox(PLAIN_BOX, PLAIN)
		cls.alpha = _contact(
			"Alpha", "Contactsperm", "alpha@contacts.test", "+41 79 111 11 11", "Example SA", "Comptable"
		)
		cls.beta = _contact("Beta", "Contactsperm", "beta@contacts.test")
		if not frappe.db.exists("User Permission", {"user": LIMITED, "allow": "Contact"}):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": LIMITED,
					"allow": "Contact",
					"for_value": cls.alpha,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"mailcraft_trial": 1})
		self.trial.start()

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
				"using": [jmap.CORE, contacts.CONTACTS],
				"methodCalls": [[name, args, f"c{n}"] for n, (name, args) in enumerate(calls)],
			}
		).encode()
		# A request as the facade reads it, with the headers Frappe reads when a contact is saved (its log).
		request = SimpleNamespace(
			get_data=lambda: body, headers={}, method="POST", path="/api/method/" + jmap.METHOD_PREFIX + "api"
		)
		with patch.object(frappe.local, "request", request, create=True):
			answer = jmap.api()
		self.assertEqual(answer.status_code, 200, answer.get_data())
		return json.loads(answer.get_data())["methodResponses"]

	def _cards(self, user, box, ids=None):
		self._as(user)
		aid = jmap.account_id(box)
		by_query = {"resultOf": "c0", "name": "ContactCard/query", "path": "/ids"}
		query, get = self._calls(
			("ContactCard/query", {"accountId": aid}),
			(
				"ContactCard/get",
				{"accountId": aid, "ids": ids} if ids else {"accountId": aid, "#ids": by_query},
			),
		)
		return query[1], get[1]

	def test_one_mailbox_of_the_person_offers_the_address_book(self):
		self._as(READER)
		own = json.loads(jmap.session(BOX).get_data())
		aid = jmap.account_id(BOX)
		self.assertIn(contacts.CONTACTS, own["capabilities"])
		self.assertIn(contacts.CONTACTS, own["accounts"][aid]["accountCapabilities"])
		self.assertEqual(own["primaryAccounts"][contacts.CONTACTS], aid)
		shared = json.loads(jmap.session(SHARED_BOX).get_data())
		self.assertNotIn(
			contacts.CONTACTS, shared["capabilities"], "listed once, with the person's own mailbox"
		)
		self.assertNotIn(contacts.CONTACTS, shared["primaryAccounts"])
		book = self._calls(("AddressBook/get", {"accountId": jmap.account_id(SHARED_BOX), "ids": None}))[0]
		self.assertEqual((book[0], book[1]["type"]), ("error", "accountNotSupportedByMethod"))
		listed = self._calls(("AddressBook/get", {"accountId": aid, "ids": None}))[0][1]["list"]
		self.assertEqual([(b["id"], b["myRights"]["mayWrite"]) for b in listed], [(contacts.BOOK, True)])

	def test_the_book_is_writable_by_whoever_may_create_contacts(self):
		for user, box, writes in (
			(READER, BOX, True),
			(LIMITED, LIMITED_BOX, False),
			(PLAIN, PLAIN_BOX, False),
		):
			self._as(user)
			book = self._calls(
				("AddressBook/get", {"accountId": jmap.account_id(box), "ids": [contacts.BOOK]})
			)[0]
			self.assertEqual(book[1]["list"][0]["myRights"]["mayWrite"], writes, user)
			self.assertFalse(book[1]["list"][0]["myRights"]["mayDelete"], user)

	def test_the_cards_are_the_contacts_with_what_neomail_shows(self):
		# By the ids asked: a client reads them as many at a time as maxObjectsInGet allows (the clone has more).
		query, get = self._cards(READER, BOX, ids=[self.alpha, self.beta])
		self.assertTrue({self.alpha, self.beta} <= set(query["ids"]))
		self.assertEqual({c["id"] for c in get["list"]}, {self.alpha, self.beta})
		alpha = next(c for c in get["list"] if c["id"] == self.alpha)
		self.assertEqual(alpha["name"]["full"], "Alpha Contactsperm")
		self.assertEqual(
			[(p["kind"], p["value"]) for p in alpha["name"]["components"]],
			[("given", "Alpha"), ("surname", "Contactsperm")],
		)
		self.assertEqual([e["address"] for e in alpha["emails"].values()], ["alpha@contacts.test"])
		self.assertEqual(
			[(p["number"], p["features"]) for p in alpha["phones"].values()],
			[("+41 79 111 11 11", {"mobile": True})],
		)
		self.assertEqual(alpha["organizations"]["o1"]["name"], "Example SA")
		self.assertEqual(alpha["titles"]["t1"]["name"], "Comptable")
		self.assertEqual(alpha["addressBookIds"], {contacts.BOOK: True})

	def test_a_reader_gets_only_what_its_user_permissions_allow(self):
		query, get = self._cards(LIMITED, LIMITED_BOX)
		self.assertEqual(query["ids"], [self.alpha])
		_, asked = self._cards(LIMITED, LIMITED_BOX, ids=[self.alpha, self.beta])
		self.assertEqual([c["id"] for c in asked["list"]], [self.alpha])
		self.assertEqual(asked["notFound"], [self.beta], "another's contact reads as not found")

	def test_without_the_right_to_read_contacts_the_book_is_empty(self):
		query, get = self._cards(PLAIN, PLAIN_BOX)
		self.assertEqual((query["ids"], get["list"]), ([], []))
		_, asked = self._cards(PLAIN, PLAIN_BOX, ids=[self.alpha])
		self.assertEqual((asked["list"], asked["notFound"]), ([], [self.alpha]))

	def test_nothing_is_deleted_and_asked_properties_only_come_back(self):
		self._as(READER)
		aid = jmap.account_id(BOX)
		changed, got = self._calls(
			("ContactCard/set", {"accountId": aid, "destroy": [self.alpha]}),
			("ContactCard/get", {"accountId": aid, "ids": [self.alpha], "properties": ["emails", "secret"]}),
		)
		self.assertEqual(changed[1]["notDestroyed"][self.alpha]["type"], "forbidden")
		self.assertEqual(changed[1]["destroyed"], [])
		self.assertTrue(frappe.db.exists("Contact", self.alpha))
		self.assertEqual(set(got[1]["list"][0]) - {"@type", "version"}, {"id", "emails"})

	def _set(self, user, box, **changes):
		self._as(user)
		return self._calls(("ContactCard/set", {"accountId": jmap.account_id(box), **changes}))[0]

	def test_a_card_made_in_neomail_becomes_a_contact_once(self):
		uid = f"mc-test-{uuid.uuid4()}"
		card = {
			"@type": "Card",
			"version": "1.0",
			"uid": uid,
			"addressBookIds": {contacts.BOOK: True},
			"name": {
				"@type": "Name",
				"full": "Gamma Contactsperm",
				"components": [
					{"kind": "given", "value": "Gamma"},
					{"kind": "surname", "value": "Contactsperm"},
				],
			},
			"emails": {
				"e1": {"address": "gamma@contacts.test"},
				"e2": {"address": "gamma.private@contacts.test"},
			},
			"phones": {
				"p1": {"number": "+41 21 000 00 00", "features": {"voice": True}},
				"p2": {"number": "+41 79 000 00 00", "features": {"mobile": True}},
				"p3": {"number": "+41 78 000 00 00", "features": {"mobile": True}},
			},
			"organizations": {"o1": {"name": "Gamma SA"}},
			"titles": {"t1": {"name": "Directrice"}},
		}
		answer = self._set(READER, BOX, create={"k1": card})
		self.assertEqual(answer[0], "ContactCard/set", answer)
		made = answer[1]["created"]["k1"]["id"]
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Contact", made)
		self.assertEqual(
			(doc.first_name, doc.last_name, doc.company_name, doc.designation),
			("Gamma", "Contactsperm", "Gamma SA", "Directrice"),
		)
		self.assertEqual(doc.owner, READER, "made with the person's own rights")
		self.assertEqual(
			[(row.email_id, row.is_primary) for row in doc.email_ids],
			[("gamma@contacts.test", 1), ("gamma.private@contacts.test", 0)],
		)
		self.assertEqual(
			[(row.phone, row.is_primary_phone, row.is_primary_mobile_no) for row in doc.phone_nos],
			[("+41 21 000 00 00", 1, 0), ("+41 79 000 00 00", 0, 1), ("+41 78 000 00 00", 0, 0)],
			"one primary of each kind: the Contact refuses two",
		)
		again = self._set(READER, BOX, create={"k2": card})[1]
		self.assertEqual(again["created"]["k2"]["id"], made, "sent again: the same contact")
		self.assertEqual(frappe.db.count("Contact Email", {"email_id": "gamma@contacts.test"}), 1)
		self.assertNotEqual(answer[1]["oldState"], answer[1]["newState"])

	def test_a_card_changed_in_neomail_changes_its_contact_and_keeps_its_primaries(self):
		frappe.set_user("Administrator")
		name = (
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Delta",
					"last_name": "Contactsperm",
					"company_name": "Delta SA",
					"email_ids": [
						{"email_id": "delta.old@contacts.test", "is_primary": 0},
						{"email_id": "delta@contacts.test", "is_primary": 1},
					],
					"phone_nos": [{"phone": "+41 79 222 22 22", "is_primary_mobile_no": 1}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		patch = {
			"name": {
				"full": "Delta Changed",
				"components": [{"kind": "given", "value": "Delta"}, {"kind": "surname", "value": "Changed"}],
			},
			"emails": {
				"e1": {"address": "delta.old@contacts.test"},
				"e2": {"address": "delta@contacts.test"},
				"e3": {"address": "delta.new@contacts.test"},
			},
			"phones": {
				"p1": {"number": "+41 22 333 33 33", "features": {"voice": True}},
				"p2": {"number": "+41 79 222 22 22", "features": {"mobile": True}},
			},
			"organizations": {},
		}
		answer = self._set(READER, BOX, update={name: patch})[1]
		self.assertEqual((answer["updated"], answer["notUpdated"]), ({name: None}, {}))
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Contact", name)
		self.assertEqual((doc.first_name, doc.last_name, doc.company_name), ("Delta", "Changed", ""))
		self.assertEqual(doc.email_id, "delta@contacts.test", "the primary address stays the primary")
		self.assertEqual(
			[row.email_id for row in doc.email_ids],
			["delta.old@contacts.test", "delta@contacts.test", "delta.new@contacts.test"],
		)
		self.assertEqual((doc.mobile_no, doc.phone), ("+41 79 222 22 22", "+41 22 333 33 33"))
		emptied = self._set(READER, BOX, update={name: {"name": {"full": ""}}})[1]
		self.assertEqual(emptied["updated"], {name: None})
		self.assertEqual(
			frappe.db.get_value("Contact", name, "first_name"), "Delta", "a contact keeps a name"
		)

	def test_writing_follows_the_persons_rights(self):
		card = {
			"name": {"full": "Epsilon Contactsperm"},
			"emails": {"e1": {"address": "epsilon@contacts.test"}},
		}
		for user, box in ((PLAIN, PLAIN_BOX), (LIMITED, LIMITED_BOX)):
			answer = self._set(
				user, box, create={"k": card}, update={self.beta: {"titles": {"t1": {"name": "x"}}}}
			)[1]
			self.assertEqual(answer["notCreated"]["k"]["type"], "forbidden", user)
			self.assertEqual(
				answer["notUpdated"][self.beta]["type"], "notFound", f"{user}: another's contact is not there"
			)
		self.assertFalse(frappe.db.exists("Contact Email", {"email_id": "epsilon@contacts.test"}))
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Contact", self.beta, "designation") or "", "")
		# The contact a User Permission gives the reader is theirs to change.
		answer = self._set(
			LIMITED, LIMITED_BOX, update={self.alpha: {"titles": {"t1": {"name": "Comptable"}}}}
		)[1]
		self.assertEqual(answer["updated"], {self.alpha: None})
		missing = self._set(READER, BOX, update={"mc-test-no-such-contact": {"titles": {}}})[1]
		self.assertEqual(missing["notUpdated"]["mc-test-no-such-contact"]["type"], "notFound")

	def test_a_card_neomail_cannot_write_is_refused_and_says_why(self):
		refused = self._set(
			READER,
			BOX,
			create={
				"notes": {"name": {"full": "Zeta"}, "notes": {"n1": {"note": "x"}}},
				"book": {"name": {"full": "Zeta"}, "addressBookIds": {"other": True}},
				"nameless": {"phones": {"p1": {"number": "+41 79 999 99 99"}}},
				"shape": {"name": "Zeta", "emails": []},
			},
			update={self.alpha: {"emails/e1/address": "x@contacts.test"}},
		)[1]
		self.assertEqual(set(refused["notCreated"]), {"notes", "book", "nameless", "shape"})
		self.assertTrue(
			all(e["type"] == "invalidProperties" for e in refused["notCreated"].values()), refused
		)
		self.assertEqual(refused["notUpdated"][self.alpha]["type"], "invalidProperties")
		self.assertIn("whole property", refused["notUpdated"][self.alpha]["description"], "not a part of one")
		self.assertEqual(refused["created"], {})
		self.assertEqual(
			frappe.db.get_value("Contact Email", {"parent": self.alpha, "is_primary": 1}, "email_id"),
			"alpha@contacts.test",
		)

	def test_queries_follow_rfc_8620(self):
		self._as(LIMITED)
		aid = jmap.account_id(LIMITED_BOX)
		none, total, last, unbounded, changes = self._calls(
			("ContactCard/query", {"accountId": aid, "limit": 0, "calculateTotal": True}),
			("ContactCard/query", {"accountId": aid, "calculateTotal": True}),
			("ContactCard/query", {"accountId": aid, "position": -1}),
			("ContactCard/query", {"accountId": aid, "limit": None}),
			("ContactCard/changes", {"accountId": aid, "sinceState": "0"}),
		)
		self.assertEqual((none[1]["ids"], none[1]["total"]), ([], 1), "a limit of 0 is none")
		self.assertNotIn("limit", none[1])
		self.assertEqual(
			(total[1]["ids"], total[1]["total"], total[1]["limit"]), ([self.alpha], 1, contacts.MAX_CARDS)
		)
		self.assertEqual((last[1]["ids"], last[1]["position"]), ([self.alpha], 0), "from the end")
		self.assertNotIn("total", last[1], "only when asked")
		self.assertEqual(unbounded[1]["limit"], contacts.MAX_CARDS)
		self.assertEqual((changes[0], changes[1]["type"]), ("error", "cannotCalculateChanges"))
		self._as(READER)
		aid = jmap.account_id(BOX)
		count, end, wrong, every = self._calls(
			("ContactCard/query", {"accountId": aid, "limit": 0, "calculateTotal": True}),
			("ContactCard/query", {"accountId": aid, "position": -2}),
			("ContactCard/get", {"accountId": aid, "ids": [self.alpha], "properties": [1]}),
			("ContactCard/get", {"accountId": aid, "ids": None}),
		)
		self.assertEqual(end[1]["position"], count[1]["total"] - 2)
		self.assertEqual(len(end[1]["ids"]), 2)
		self.assertEqual((wrong[0], wrong[1]["type"]), ("error", "invalidArguments"))
		if count[1]["total"] > jmap.MAX_OBJECTS:
			self.assertEqual(
				(every[0], every[1]["type"]), ("error", "requestTooLarge"), "never a part of them silently"
			)
		for bad in ({"position": "1"}, {"limit": -1}, {"anchor": "x"}, {"sort": [{"property": "name"}]}):
			answer = self._calls(("ContactCard/query", {"accountId": aid, **bad}))[0]
			self.assertEqual(answer[0], "error", bad)

	def test_what_neomail_cannot_say_is_left_as_it_was(self):
		"""A company's contact reads as its company, and a number that is no primary reads as a number: sent back with a
		change of title only, neither its name nor its primaries move."""
		frappe.set_user("Administrator")
		company = frappe.get_doc(
			{
				"doctype": "Contact",
				"company_name": "Zeta Contactsperm SA",
				"email_ids": [{"email_id": "zeta@contacts.test", "is_primary": 1}],
				"phone_nos": [
					{"phone": "+41 79 444 44 44", "is_primary_mobile_no": 1},
					{"phone": "+41 78 555 55 55"},
				],
			}
		).insert(ignore_permissions=True)
		read = self._cards(READER, BOX, ids=[company.name])[1]["list"][0]
		# What NeoMail sends back: the full name only (it keeps no parts of it), the numbers as it read them.
		patch = {
			"name": {"full": read["name"]["full"], "components": []},
			"phones": read["phones"],
			"titles": {"t1": {"name": "Comptable"}},
		}
		answer = self._set(READER, BOX, update={company.name: patch})[1]
		self.assertEqual(answer["updated"], {company.name: None})
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Contact", company.name)
		self.assertEqual((doc.first_name or "", doc.last_name or "", doc.designation), ("", "", "Comptable"))
		self.assertEqual(
			[(row.phone, row.is_primary_phone, row.is_primary_mobile_no) for row in doc.phone_nos],
			[("+41 79 444 44 44", 0, 1), ("+41 78 555 55 55", 0, 0)],
			"the second mobile does not become the primary phone",
		)

	def test_a_create_sent_again_comes_back_only_to_the_contact_it_made(self):
		uid = f"mc-test-{uuid.uuid4()}"
		card = {
			"uid": uid,
			"name": {"full": "Eta Contactsperm"},
			"emails": {"e1": {"address": "eta@contacts.test"}},
		}
		first = self._set(READER, BOX, create={"k": card})[1]["created"]["k"]["id"]
		self._as(READER)
		key = contacts._uid_key(uid)
		kept = frappe.cache().get_value(key)
		self.assertEqual(kept["name"], first)
		# Its transaction was lost, and another contact took the name since: that one is not the answer.
		frappe.cache().set_value(key, {**kept, "creation": "2000-01-01 00:00:00"})
		second = self._set(READER, BOX, create={"k": card})[1]["created"]["k"]["id"]
		self.assertNotEqual(second, first)
