# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What is done to a folder of NeoMail's, on the mailbox's IMAP server: from the right-click menu of a folder in the desk's
NeoMail menu (neomail_folders.act, 29.10), and from NeoMail itself, by JMAP's Mailbox/set (neomail_folders.mailbox_set,
31.10). The person's own mailbox only; a special folder keeps its name and its place; only Trash and Junk Email are
emptied. The IMAP server is a fake (no server is reached)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import neomail_folders
from frappe_webmail.mailcraft_jmap import JmapError, account_id, mailbox_id
from frappe_webmail.tests.test_mailcraft_jmap import FakeServer, _user, served

OWNER = "neomail_folders_owner@example.com"
SHARED = "neomail_folders_shared@example.com"
PORTAL = "neomail_folders_portal@example.com"
MAILBOX = "neomail_folders_box@webmail.test"


class FoldersServer(FakeServer):
	"""The fake IMAP server, with what a folder's right-click asks of it."""

	def create_folder(self, name):
		self.folders[name] = {"flags": (b"\\HasNoChildren",), "messages": {}}
		self.validity[name], self.next_uid[name] = 1, 1

	def rename_folder(self, old, new):
		# The folders in it go with it (IMAP RENAME)
		for name in [n for n in self.folders if n == old or n.startswith(old + "/")]:
			moved = new + name[len(old) :]
			self.folders[moved] = self.folders.pop(name)
			self.validity[moved], self.next_uid[moved] = self.validity.pop(name), self.next_uid.pop(name)

	def folder_status(self, name, what):
		return {b"MESSAGES": len(self.folders[name]["messages"])}

	def delete_folder(self, name):
		del self.folders[name]

	def search(self, criteria, *args, **kwargs):
		messages = self.folders[self.selected]["messages"]
		if criteria == ["UNSEEN"]:
			return [uid for uid, m in messages.items() if b"\\Seen" not in m["flags"]]
		return list(messages)


class TestNeomailFolders(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email, desk in ((OWNER, True), (SHARED, True), (PORTAL, False)):
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

	def tearDown(self):
		frappe.set_user("Administrator")

	def _act(self, server, folder, action, name=None, user=OWNER, account=MAILBOX):
		frappe.set_user(user)
		with served(server):
			return neomail_folders.act(account, mailbox_id(folder), action, name)

	def test_a_folder_is_made_in_the_folder_right_clicked(self):
		server = FoldersServer()
		made = self._act(server, "Projects/Film", "create", "  Rushes  ")
		self.assertIn("Projects/Film/Rushes", server.folders)
		self.assertEqual(made, {"mailbox": mailbox_id("Projects/Film/Rushes")})
		# In the Inbox too (as NeoMail's own New Folder does under the folder it is asked on)
		self._act(server, "INBOX", "create", "Clients")
		self.assertIn("INBOX/Clients", server.folders)

	def test_a_folder_of_the_person_s_own_is_renamed_in_its_place_and_deleted(self):
		server = FoldersServer()
		renamed = self._act(server, "Projects/Film", "rename", "Cinema")
		self.assertEqual(renamed, {"mailbox": mailbox_id("Projects/Cinema")})
		self.assertIn("Projects/Cinema", server.folders)
		self.assertNotIn("Projects/Film", server.folders)
		self._act(server, "Projects/Cinema", "delete")
		self.assertNotIn("Projects/Cinema", server.folders)

	def test_a_special_folder_keeps_its_name_and_its_place(self):
		# 29.10: Inbox, Sent, Drafts, Trash, Junk are fixed; « Sent » is known here by its special-use flag alone
		for folder in ("INBOX", "Sent", "Trash"):
			for action, name in (("rename", "Other"), ("delete", None)):
				with self.subTest(folder=folder, action=action), self.assertRaises(frappe.ValidationError):
					self._act(FoldersServer(), folder, action, name)

	def test_only_trash_and_junk_are_emptied_and_all_of_a_folder_is_marked_read(self):
		server = FoldersServer()
		server.put("Trash", b"Subject: a\r\n\r\nx")
		server.put("Trash", b"Subject: b\r\n\r\ny")
		self._act(server, "Trash", "empty")
		self.assertEqual(server.folders["Trash"]["messages"], {})
		server.put("INBOX", b"Subject: c\r\n\r\nz")
		with self.assertRaises(frappe.ValidationError):
			self._act(server, "INBOX", "empty")
		self.assertEqual(len(server.folders["INBOX"]["messages"]), 1)
		self._act(server, "INBOX", "read")
		self.assertTrue(all(b"\\Seen" in m["flags"] for m in server.folders["INBOX"]["messages"].values()))

	def test_a_name_must_be_given_and_hold_no_separator(self):
		for name in (None, "", "   ", "a/b", "x" * 201):
			with self.subTest(name=name), self.assertRaises(frappe.ValidationError):
				self._act(FoldersServer(), "Projects/Film", "create", name)

	def test_a_shared_mailbox_is_set_up_by_its_owner_and_a_stranger_s_or_portal_s_by_nobody(self):
		server = FoldersServer()
		with self.assertRaises(frappe.PermissionError):
			self._act(server, "Projects/Film", "create", "Rushes", user=SHARED)
		with self.assertRaises(frappe.PermissionError):
			self._act(server, "Projects/Film", "create", "Rushes", user=PORTAL)
		with self.assertRaises(frappe.PermissionError):
			self._act(server, "Projects/Film", "create", "Rushes", account="nobody@webmail.test")
		self.assertNotIn("Projects/Film/Rushes", server.folders)

	def test_an_unknown_action_or_folder_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._act(FoldersServer(), "INBOX", "move")
		with self.assertRaises(frappe.ValidationError):
			self._act(FoldersServer(), "Nowhere", "read")
		frappe.set_user(OWNER)
		with served(FoldersServer()), self.assertRaises(frappe.ValidationError):
			neomail_folders.act(MAILBOX, "not-a-mailbox-id", "read")

	# Mailbox/set: NeoMail's own folder pane and Folder tab (in the desk and in Neodesk), under the same rules

	def _set(self, server, user=OWNER, account=MAILBOX, **args):
		frappe.set_user(user)
		with served(server):
			return neomail_folders.mailbox_set({"accountId": account_id(account), **args})

	def test_folders_are_made_under_a_folder_at_the_top_and_under_one_the_call_makes(self):
		server = FoldersServer()
		out = self._set(
			server,
			create={
				"a": {"name": " Rushes ", "parentId": mailbox_id("Projects/Film")},
				"b": {"name": "Clients", "parentId": None},
				"c": {"name": "2026", "parentId": "#b"},
			},
		)
		self.assertEqual(
			out["created"],
			{
				"a": {"id": mailbox_id("Projects/Film/Rushes")},
				"b": {"id": mailbox_id("Clients")},
				"c": {"id": mailbox_id("Clients/2026")},
			},
		)
		self.assertTrue({"Projects/Film/Rushes", "Clients", "Clients/2026"} <= set(server.folders))
		self.assertEqual(out["accountId"], account_id(MAILBOX))

	def test_a_folder_renamed_and_moved_has_the_id_of_its_new_place_and_the_folders_in_it_go_with_it(self):
		server = FoldersServer()
		server.create_folder("Projects/Film/Rushes")
		out = self._set(
			server, update={mailbox_id("Projects/Film"): {"name": "Cinema", "parentId": mailbox_id("INBOX")}}
		)
		self.assertEqual(out["updated"], {mailbox_id("Projects/Film"): {"id": mailbox_id("INBOX/Cinema")}})
		self.assertIn("INBOX/Cinema/Rushes", server.folders)
		self.assertNotIn("Projects/Film", server.folders)
		# Into Trash, as NeoMail deletes a folder (Outlook's way), then at the top again; nothing changed is answered so
		out = self._set(server, update={mailbox_id("INBOX/Cinema"): {"parentId": mailbox_id("Trash")}})
		self.assertEqual(out["updated"], {mailbox_id("INBOX/Cinema"): {"id": mailbox_id("Trash/Cinema")}})
		out = self._set(server, update={mailbox_id("Trash/Cinema"): {"parentId": None, "isSubscribed": True}})
		self.assertIn("Cinema/Rushes", server.folders)
		out = self._set(server, update={mailbox_id("Cinema"): {"name": "Cinema", "sortOrder": 2}})
		self.assertEqual(out["updated"], {mailbox_id("Cinema"): None})

	def test_a_folder_is_destroyed_with_the_folders_in_it_and_their_mail_when_asked(self):
		server = FoldersServer()
		server.create_folder("Projects/Film/Rushes")
		server.put("Projects/Film/Rushes", b"Subject: a\r\n\r\nx")
		gone = mailbox_id("Projects/Film")
		out = self._set(server, destroy=[gone])
		self.assertEqual(out["notDestroyed"][gone]["type"], "mailboxHasEmail")
		self.assertIn("Projects/Film/Rushes", server.folders)
		out = self._set(server, destroy=[gone, gone], onDestroyRemoveEmails=True)
		self.assertEqual(out["destroyed"], [gone])
		self.assertFalse({"Projects/Film", "Projects/Film/Rushes"} & set(server.folders))

	def test_what_is_refused_is_said_for_each_folder_and_nothing_else_changes(self):
		server = FoldersServer()
		before = set(server.folders)
		film = mailbox_id("Projects/Film")
		out = self._set(
			server,
			create={
				"bad": {"name": "a/b"},
				"empty": {"name": "  "},
				"there": {"name": "Film", "parentId": mailbox_id("Projects")},
				"orphan": {"name": "X", "parentId": mailbox_id("Nowhere")},
				"odd": {"name": "Y", "role": "inbox"},
			},
			update={
				mailbox_id("INBOX"): {"name": "Other"},
				film: {"parentId": film},
				mailbox_id("Nowhere"): {"name": "Z"},
			},
			destroy=[mailbox_id("Trash"), mailbox_id("Nowhere")],
		)
		self.assertEqual(
			{k: v["type"] for k, v in out["notCreated"].items()},
			dict.fromkeys(["bad", "empty", "there", "orphan", "odd"], "invalidProperties"),
		)
		self.assertEqual(
			{k: v["type"] for k, v in out["notUpdated"].items()},
			{mailbox_id("INBOX"): "forbidden", film: "invalidProperties", mailbox_id("Nowhere"): "notFound"},
		)
		self.assertEqual(
			{k: v["type"] for k, v in out["notDestroyed"].items()},
			{mailbox_id("Trash"): "forbidden", mailbox_id("Nowhere"): "notFound"},
		)
		self.assertEqual(set(server.folders), before)

	def test_a_shared_mailbox_is_set_up_by_its_owner_and_a_stranger_s_by_nobody(self):
		for user, account in ((SHARED, MAILBOX), (PORTAL, MAILBOX), (OWNER, "nobody@webmail.test")):
			with self.subTest(user=user, account=account), self.assertRaises(JmapError) as refused:
				self._set(FoldersServer(), user=user, account=account, create={"n": {"name": "New"}})
			self.assertEqual(refused.exception.type, "forbidden")
		with self.assertRaises(JmapError) as refused:
			self._set(FoldersServer(), create="New")
		self.assertEqual(refused.exception.type, "invalidArguments")
