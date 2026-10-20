# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The person's Neoffice notes as NeoMail's notes (mailcraft_notes; Jérémy, 20.10: one place for notes).

One mailbox of the person offers them; its notes are those the desk's Notes list shows them (their own, and those
shared with them), pinned first. A plain note is written here as the desk writes it, a rich one only read; a note shared
for reading is not written, nor deleted by anyone but its owner; a note changed elsewhere since it was read is not
written over; a create sent again (its answer lost) comes back to the same note by its uid.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_notes
"""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import mailcraft_notes as notes
from frappe_webmail.tests.test_mailcraft_contacts import _mailbox, _user

OWNER = "mailcraft_notes_owner@example.com"  # of the desk, owns OWNER_BOX and the notes
COLLEAGUE = "mailcraft_notes_colleague@example.com"  # of the desk, a note is shared with them for reading
STRANGER = "mailcraft_notes_stranger@example.com"  # of the desk, nothing shared
MANAGER = "mailcraft_notes_manager@example.com"  # a System Manager a note is shared with for reading
OWNER_BOX = "mailcraft_notes_owner@webmail.test"
SECOND_BOX = "mailcraft_notes_second@webmail.test"
COLLEAGUE_BOX = "mailcraft_notes_colleague@webmail.test"
STRANGER_BOX = "mailcraft_notes_stranger@webmail.test"
MANAGER_BOX = "mailcraft_notes_manager@webmail.test"
USERS = (OWNER, COLLEAGUE, STRANGER, MANAGER)


@unittest.skipUnless("neoffice_theme" in frappe.get_installed_apps(), "the notes are neoffice_theme's")
class TestMailCraftNotes(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for user in (OWNER, COLLEAGUE, STRANGER):
			_user(user, ["Sales User"])
		_user(MANAGER, ["System Manager"])
		_mailbox(OWNER_BOX, OWNER)
		_mailbox(MANAGER_BOX, MANAGER)
		_mailbox(SECOND_BOX, OWNER)
		_mailbox(COLLEAGUE_BOX, COLLEAGUE)
		_mailbox(STRANGER_BOX, STRANGER)
		frappe.db.commit()  # nosemgrep: the users and mailboxes the requests below read

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		names = frappe.get_all(notes.NOTE_DOCTYPE, filters={"owner": ["in", USERS]}, pluck="name")
		for name in names:
			frappe.delete_doc(
				notes.NOTE_DOCTYPE, name, ignore_permissions=True, force=True, delete_permanently=True
			)
		frappe.db.delete("DocShare", {"share_doctype": notes.NOTE_DOCTYPE, "user": ["in", USERS]})
		frappe.db.delete("Deleted Document", {"deleted_doctype": notes.NOTE_DOCTYPE, "owner": ["in", USERS]})
		# The System Manager made for the test goes (a Sales User of the test site may stay, as the other tests' do).
		frappe.delete_doc("Webmail Account", MANAGER_BOX, ignore_permissions=True, force=True)
		frappe.delete_doc("User", MANAGER, ignore_permissions=True, force=True)
		frappe.db.commit()  # nosemgrep: what the notes' functions committed goes too
		super().tearDownClass()

	def setUp(self):
		self.trial = patch.dict(frappe.local.conf, {"neomail_disabled": 0})
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
				"using": [jmap.CORE, notes.NOTES],
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

	def _set(self, box, **changes):
		answer = self._calls(("Note/set", {"accountId": jmap.account_id(box), **changes}))[0]
		self.assertEqual(answer[0], "Note/set", answer)
		return answer[1]

	def _get(self, box, ids=None, **more):
		args = {"accountId": jmap.account_id(box), **({"ids": ids} if ids is not None else {}), **more}
		answer = self._calls(("Note/get", args))[0]
		self.assertEqual(answer[0], "Note/get", answer)
		return answer[1]

	def _query(self, box, **args):
		answer = self._calls(("Note/query", {"accountId": jmap.account_id(box), **args}))[0]
		self.assertEqual(answer[0], "Note/query", answer)
		return answer[1]

	def _make(self, **note):
		made = self._set(OWNER_BOX, create={"k": note})
		self.assertEqual(made["notCreated"], {}, made)
		return made["created"]["k"]["id"]

	def test_the_persons_first_mailbox_offers_the_notes(self):
		self._as(OWNER)
		session = json.loads(jmap.session(OWNER_BOX).get_data())
		aid = jmap.account_id(OWNER_BOX)
		self.assertIn(notes.NOTES, session["capabilities"])
		self.assertEqual(session["primaryAccounts"][notes.NOTES], aid)
		written = session["accounts"][aid]["accountCapabilities"][notes.NOTES]["writableProperties"]
		self.assertEqual(written, ["isArchived", "isPinned", "text", "title"])
		second = json.loads(jmap.session(SECOND_BOX).get_data())
		self.assertNotIn(notes.NOTES, second["capabilities"], "offered once, not in every mailbox")
		refused = self._calls(("Note/get", {"accountId": jmap.account_id(SECOND_BOX)}))[0]
		self.assertEqual((refused[0], refused[1]["type"]), ("error", "accountNotSupportedByMethod"))

	def test_a_plain_note_is_made_read_and_changed_as_the_desk_does(self):
		self._as(OWNER)
		uid = f"note-{uuid.uuid4()}"
		name = self._make(uid=uid, text="Groceries\nMilk & eggs\n\nBread")
		doc = frappe.get_doc(notes.NOTE_DOCTYPE, name)
		self.assertEqual((doc.title, doc.status, doc.note_type), ("Groceries", "Draft", "Text"))
		self.assertEqual(doc.content, "<p>Groceries</p><p>Milk &amp; eggs</p><p><br></p><p>Bread</p>")
		note = self._get(OWNER_BOX, [name])["list"][0]
		self.assertEqual(
			(note["title"], note["text"], note["isRich"], note["isShared"]),
			("Groceries", "Groceries\nMilk & eggs\n\nBread", False, False),
		)
		self.assertEqual(note["myRights"], {"mayWrite": True, "mayWriteText": True, "mayDelete": True})
		self.assertTrue(note["webUrl"].endswith("/app/notes?note=" + name), note["webUrl"])
		self.assertTrue(note["updated"].endswith("Z"))
		# Sent again (its answer lost on the way): the same note, not a second one.
		self.assertEqual(self._make(uid=uid, text="Groceries\nMilk & eggs\n\nBread"), name)
		# Changed: the title and the text replace them; the client's version is the one read.
		changed = self._set(
			OWNER_BOX, update={name: {"title": "Shopping", "text": "Milk", "updated": note["updated"]}}
		)
		self.assertEqual(changed["notUpdated"], {}, changed)
		self.assertEqual(frappe.db.get_value(notes.NOTE_DOCTYPE, name, "title"), "Shopping")
		self.assertEqual(self._get(OWNER_BOX, [name])["list"][0]["text"], "Milk")
		# Changed elsewhere since it was read: not written over.
		frappe.db.set_value(
			notes.NOTE_DOCTYPE, name, "modified", "2030-01-01 10:00:00", update_modified=False
		)
		stale = self._set(OWNER_BOX, update={name: {"text": "Butter", "updated": note["updated"]}})
		self.assertEqual(stale["notUpdated"][name]["type"], "stateMismatch", stale)
		self.assertEqual(self._get(OWNER_BOX, [name])["list"][0]["text"], "Milk")
		# Pinned first; archived, in the desk's second list.
		other = self._make(title="Another", text="")
		self._set(OWNER_BOX, update={other: {"isPinned": True}})
		ids = self._query(OWNER_BOX, filter={"isArchived": False})["ids"]
		self.assertEqual(ids[0], other)
		self._set(OWNER_BOX, update={other: {"isArchived": True}})
		self.assertNotIn(other, self._query(OWNER_BOX, filter={"isArchived": False})["ids"])
		self.assertIn(other, self._query(OWNER_BOX, filter={"isArchived": True})["ids"])
		# Deleted by its owner, as the desk deletes it: kept in the Deleted Documents.
		gone = self._set(OWNER_BOX, destroy=[name])
		self.assertEqual(gone["destroyed"], [name], gone)
		self.assertFalse(frappe.db.exists(notes.NOTE_DOCTYPE, name))
		self.assertTrue(
			frappe.db.exists(
				"Deleted Document", {"deleted_doctype": notes.NOTE_DOCTYPE, "deleted_name": name}
			)
		)

	def test_a_rich_note_is_read_and_its_words_changed_in_the_desk(self):
		self._as(OWNER)
		rich = frappe.get_doc(
			{
				"doctype": notes.NOTE_DOCTYPE,
				"title": "Plan",
				"content": '<div class="ql-editor read-mode"><p><strong>Bold</strong> start</p></div>',
				"status": "Draft",
			}
		).insert()
		checklist = frappe.get_doc(
			{
				"doctype": notes.NOTE_DOCTYPE,
				"title": "Tasks",
				"content": "<p>To do</p>",
				"status": "Draft",
				"checklist": [{"description": "Call back"}],
			}
		).insert()
		read = {n["id"]: n for n in self._get(OWNER_BOX, [rich.name, checklist.name])["list"]}
		self.assertEqual((read[rich.name]["isRich"], read[rich.name]["text"]), (True, "Bold start"))
		self.assertTrue(read[checklist.name]["isRich"], "a checklist is no plain text")
		self.assertEqual(read[rich.name]["myRights"]["mayWriteText"], False)
		refused = self._set(OWNER_BOX, update={rich.name: {"text": "Plain now"}})
		self.assertEqual(refused["notUpdated"][rich.name]["type"], "forbidden", refused)
		self.assertIn("<strong>", frappe.db.get_value(notes.NOTE_DOCTYPE, rich.name, "content"))
		pinned = self._set(OWNER_BOX, update={rich.name: {"isPinned": True}})
		self.assertEqual(pinned["notUpdated"], {}, pinned)

	def test_a_note_shared_for_reading_is_read_not_written_and_a_strangers_is_not_there(self):
		self._as(OWNER)
		name = self._make(title="Shared", text="Read only")
		import frappe.share

		frappe.share.add(notes.NOTE_DOCTYPE, name, COLLEAGUE, read=1, write=0, notify=0)
		self._as(COLLEAGUE)  # the share is read in the next request
		self.assertIn(name, self._query(COLLEAGUE_BOX)["ids"])
		note = self._get(COLLEAGUE_BOX, [name])["list"][0]
		self.assertEqual(
			(note["isShared"], note["myRights"]),
			(True, {"mayWrite": False, "mayWriteText": False, "mayDelete": False}),
		)
		refused = self._set(COLLEAGUE_BOX, update={name: {"text": "Mine now"}}, destroy=[name])
		self.assertEqual(refused["notUpdated"][name]["type"], "forbidden", refused)
		self.assertEqual(refused["notDestroyed"][name]["type"], "forbidden", refused)
		self.assertEqual(frappe.db.get_value(notes.NOTE_DOCTYPE, name, "content"), "<p>Read only</p>")
		self._as(STRANGER)
		self.assertNotIn(name, self._query(STRANGER_BOX)["ids"])
		self.assertEqual(self._get(STRANGER_BOX, [name])["notFound"], [name])
		hidden = self._set(STRANGER_BOX, update={name: {"text": "x"}}, destroy=[name])
		self.assertEqual(hidden["notUpdated"][name]["type"], "notFound")
		self.assertEqual(hidden["notDestroyed"][name]["type"], "notFound")

	def test_a_whole_note_sent_back_writes_only_what_differs(self):
		"""A client that pins a note by sending back the whole note it read changes nothing else: a plain note's content
		stays as the desk wrote it, a rich one is pinned; a rich note's title may change, its content stays; the version
		read is the same instant however the client writes it."""
		self._as(OWNER)
		desk = '<div class="ql-editor read-mode"><p>a</p><p><br></p><p><br></p><p>b</p></div>'
		plain = frappe.get_doc(
			{"doctype": notes.NOTE_DOCTYPE, "title": "Desk", "content": desk, "status": "Draft"}
		).insert()
		read = self._get(OWNER_BOX, [plain.name])["list"][0]
		self.assertFalse(read["isRich"])
		sent = self._set(OWNER_BOX, update={plain.name: {**read, "isPinned": True}})
		self.assertEqual(sent["notUpdated"], {}, sent)
		self.assertEqual(
			frappe.db.get_value(notes.NOTE_DOCTYPE, plain.name, ["content", "pinned"]), (desk, 1)
		)
		rich = frappe.get_doc(
			{
				"doctype": notes.NOTE_DOCTYPE,
				"title": "Rich",
				"content": "<p><em>x</em></p>",
				"status": "Draft",
			}
		).insert()
		read = self._get(OWNER_BOX, [rich.name])["list"][0]
		pinned = self._set(OWNER_BOX, update={rich.name: {**read, "isPinned": True}})
		self.assertEqual(pinned["notUpdated"], {}, pinned)
		read = self._get(OWNER_BOX, [rich.name])["list"][0]
		# The same instant as read, written as another client would (an offset rather than Z).
		renamed = self._set(
			OWNER_BOX,
			update={
				rich.name: {"title": "Rich (renamed)", "updated": read["updated"].replace("Z", "+00:00")}
			},
		)
		self.assertEqual(renamed["notUpdated"], {}, renamed)
		self.assertEqual(
			frappe.db.get_value(notes.NOTE_DOCTYPE, rich.name, ["title", "content"]),
			("Rich (renamed)", "<p><em>x</em></p>"),
		)

	def test_only_its_owner_deletes_a_note_and_a_colleague_given_writing_edits_it(self):
		import frappe.share

		self._as(OWNER)
		read_only = self._make(title="For reading", text="Keep me")
		writable = self._make(title="For writing", text="Draft")
		frappe.set_user("Administrator")
		frappe.share.add(notes.NOTE_DOCTYPE, read_only, MANAGER, read=1, write=0, notify=0)
		frappe.share.add(notes.NOTE_DOCTYPE, writable, COLLEAGUE, read=1, write=1, notify=0)
		self._as(MANAGER)
		refused = self._set(MANAGER_BOX, destroy=[read_only])
		self.assertEqual(refused["notDestroyed"][read_only]["type"], "forbidden", refused)
		self.assertTrue(
			frappe.db.exists(notes.NOTE_DOCTYPE, read_only), "a System Manager's wider right is not used"
		)
		self._as(COLLEAGUE)
		note = self._get(COLLEAGUE_BOX, [writable])["list"][0]
		self.assertEqual(note["myRights"], {"mayWrite": True, "mayWriteText": True, "mayDelete": False})
		edited = self._set(COLLEAGUE_BOX, update={writable: {"text": "Final"}}, destroy=[writable])
		self.assertEqual(edited["notUpdated"], {}, edited)
		self.assertEqual(edited["notDestroyed"][writable]["type"], "forbidden", edited)
		self.assertEqual(frappe.db.get_value(notes.NOTE_DOCTYPE, writable, "content"), "<p>Final</p>")

	def test_what_a_note_is_written_with_is_checked(self):
		self._as(OWNER)
		for note in (
			{"title": "x" * 141},
			{"title": "two\nlines"},
			{"isPinned": "yes"},
			{"color": 2},
		):
			made = self._set(OWNER_BOX, create={"k": note})
			self.assertEqual(made["notCreated"]["k"]["type"], "invalidProperties", note)

	def test_plain_text_and_its_content(self):
		self.assertEqual(notes.plain_text("<p>One</p><p>Two&nbsp;words</p>"), "One\nTwo words")
		self.assertEqual(notes.plain_text("<p>A<br>B</p>"), "A\nB")
		self.assertEqual(notes.content_of("a < b"), "<p>a &lt; b</p>")
		self.assertEqual(notes.content_of(""), "")
		self.assertFalse(notes._rich_markup('<div class="ql-editor read-mode"><p>x</p><p><br></p></div>'))
		for rich in (
			"<p><em>x</em></p>",
			'<p class="ql-align-center">x</p>',
			"<ul><li>x</li></ul>",
			'<img src="a">',
		):
			self.assertTrue(notes._rich_markup(rich), rich)

	def test_the_words_a_client_wrote_are_read_back_exactly(self):
		"""A client compares what it wrote with what it reads: a space at the end of a line, a run of empty lines or a
		line break at either end come back as they went, or it would take its own words for someone else's change."""
		for text in [
			"Hello ",
			"Line1\n",
			"a\n\n\nb",
			"\nHello\n",
			"\n",
			"\n\n\n",
			"x",
			"  indented\n\ttab",
			"a < b & c > d",
			"&nbsp; and &amp; typed",
			"trailing   \nspaces  ",
			"non\xa0breaking",
			"<p>not markup</p>",
			"   ",
		]:
			with self.subTest(text=text):
				self.assertEqual(notes.plain_text(notes.content_of(text)), text)

	def test_the_desks_own_markup_reads_as_its_lines(self):
		for content, text in [
			('<div class="ql-editor"><p>a</p><p><br></p><p>b</p></div>', "a\n\nb"),
			("<p>one&nbsp;two</p>\n<p>three</p>", "one two\nthree"),
			("<ul><li>x</li><li>y</li></ul><p>z</p>", "x\ny\nz"),
			("<h1>T</h1><p><strong>b</strong> c</p>", "T\nb c"),
			("plain", "plain"),
		]:
			with self.subTest(content=content):
				self.assertEqual(notes.plain_text(content), text)
