# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The webmail takes out of a folder only the messages it was asked to (maintenance#1633).

Deleting for good, moving, sending to the trash and a rule's « move » or « delete » used to mark the messages
\\Deleted, then EXPUNGE the folder: that erased with them every other message of the folder marked deleted by another
mail client (one set to « mark as deleted ») or by another person of a shared mailbox. UID EXPUNGE now names the
messages where the server has UIDPLUS, and MOVE moves them where it has MOVE; a server without UIDPLUS keeps the plain
EXPUNGE, the only way it knows.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_removal_takes_only_its_messages
"""

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import webmail_api as webmail
from frappe_webmail.tests.test_mailcraft_jmap import MAILBOX, OWNER, FakeServer, _user, message, served


class TestRemovalTakesOnlyItsMessages(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(OWNER)
		if not frappe.db.exists("Webmail Account", MAILBOX):
			frappe.get_doc(
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
			).insert(ignore_permissions=True)

	def setUp(self):
		frappe.set_user(OWNER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _inbox(self, server):
		"""Two messages of the person, and a third another client marked deleted without expunging it."""
		mine = server.put("INBOX", message("mine"))
		other = server.put("INBOX", message("other"))
		foreign = server.put("INBOX", message("foreign"), {b"\\Deleted"})
		return mine, other, foreign

	def _raws(self, server, folder):
		return [m["raw"] for m in server.folders[folder]["messages"].values()]

	def test_deleting_for_good_takes_that_message_only(self):
		server = FakeServer()
		mine, other, foreign = self._inbox(server)
		with served(server):
			webmail.delete_emails(MAILBOX, [mine], "INBOX", permanent=True)
		self.assertEqual(set(server.folders["INBOX"]["messages"]), {other, foreign}, "the foreign one stays")

	def test_the_trash_and_a_move_leave_the_other_messages(self):
		for can_move in (False, True):
			server = FakeServer(move=can_move)
			mine, other, foreign = self._inbox(server)
			with served(server):
				webmail.delete_emails(MAILBOX, [mine], "INBOX")
				webmail.move_emails(MAILBOX, [str(other)], "INBOX", "Projects/Film")
			self.assertEqual(set(server.folders["INBOX"]["messages"]), {foreign}, f"MOVE: {can_move}")
			self.assertEqual(self._raws(server, "Trash"), [message("mine")])
			self.assertEqual(self._raws(server, "Projects/Film"), [message("other")])

	def test_move_alone_keeps_the_other_messages_on_a_server_without_uidplus(self):
		"""There MOVE is what keeps the foreign message: a copy, then a plain EXPUNGE, would erase it."""
		server = FakeServer(uidplus=False, move=True)
		mine, other, foreign = self._inbox(server)
		with served(server):
			webmail.delete_emails(MAILBOX, [mine], "INBOX")
			webmail.move_emails(MAILBOX, [other], "INBOX", "Projects/Film")
		self.assertEqual(set(server.folders["INBOX"]["messages"]), {foreign})

	def test_a_draft_deleted_after_sending_or_saving_takes_no_other(self):
		"""The composer saves a draft every few seconds and deletes the one it replaces each time."""
		server = FakeServer()
		mine, other, foreign = self._inbox(server)
		webmail._delete_draft(server, "INBOX", str(mine))
		self.assertEqual(set(server.folders["INBOX"]["messages"]), {other, foreign})

	def test_nothing_to_remove_does_nothing(self):
		server = FakeServer()
		mine, other, foreign = self._inbox(server)
		with served(server):
			webmail.delete_emails(MAILBOX, "[]", "INBOX", permanent=True)
			webmail.move_emails(MAILBOX, [], "INBOX", "Trash")
		self.assertEqual(set(server.folders["INBOX"]["messages"]), {mine, other, foreign})

	def test_a_rule_moves_or_deletes_its_message_only(self):
		server = FakeServer()
		mine, other, foreign = self._inbox(server)
		move = SimpleNamespace(
			mark_as_read=0, mark_as_starred=0, action_type="move", target_folder="Projects/Film"
		)
		delete = SimpleNamespace(mark_as_read=0, mark_as_starred=0, action_type="delete", target_folder=None)
		server.select_folder("INBOX")
		self.assertTrue(webmail.apply_filter_action(server, None, move, mine, "INBOX"))
		self.assertTrue(webmail.apply_filter_action(server, None, delete, other, "INBOX"))
		self.assertEqual(set(server.folders["INBOX"]["messages"]), {foreign})
		self.assertEqual(self._raws(server, "Projects/Film"), [message("mine")])

	def test_a_server_without_uidplus_keeps_the_plain_expunge(self):
		"""Its only way: the message asked for goes, and the foreign one with it, as before."""
		server = FakeServer(uidplus=False)
		mine, other, foreign = self._inbox(server)
		with served(server):
			webmail.delete_emails(MAILBOX, [mine], "INBOX", permanent=True)
		self.assertEqual(set(server.folders["INBOX"]["messages"]), {other})
