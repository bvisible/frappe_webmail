# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What was said with someone, for NeoMail's « Échanges » pane (neomail_history, 1.11.2026): who an address is and all the
addresses of that someone (`NeomailContact/get`), the messages with them in every folder but Trash, Junk and Drafts, a page at
a time (`NeomailHistory/get`), and what Neoffice links them to (`NeomailLinked/get`). The IMAP server is a fake (no server is
reached): it answers SEARCH and SORT by the From, To and Cc of its messages and the day, and gives their envelope and structure.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_neomail_history
"""

import email
from datetime import date, datetime
from email.utils import getaddresses
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import neomail_history
from frappe_webmail.mailcraft_jmap import JmapError, _more_methods, _session, account_id, mailbox_id
from frappe_webmail.tests.test_mailcraft_jmap import FakeServer, _user, served

OWNER = "neomail_history_owner@example.com"
STRANGER = "neomail_history_stranger@example.com"
MAILBOX = "neomail_history_box@webmail.test"
CLIENT = "claire@atelier-exemple.example"
COLLEAGUE = "marc@atelier-exemple.example"
ME = MAILBOX
OTHER = "someone@elsewhere.example"
PDF = (
	(b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 20, 1, None, None, None),
	(
		b"application",
		b"pdf",
		(b"name", b"Offre.pdf"),
		None,
		None,
		b"base64",
		84000,
		None,
		(b"attachment", (b"filename", b"Offre.pdf")),
		None,
		None,
	),
	b"mixed",
)
BODY_ONLY = (b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 20, 1, None, None, None)


def _address(text):
	name, address = getaddresses([text])[0]
	mailbox, _at, host = address.partition("@")
	return SimpleNamespace(
		name=name.encode() if name else None, route=None, mailbox=mailbox.encode(), host=host.encode()
	)


class HistoryServer(FakeServer):
	"""The fake IMAP server, with the folders of a real mailbox and the searches the history makes."""

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.folders["Drafts"] = {"flags": (b"\\HasNoChildren", b"\\Drafts"), "messages": {}}
		self.folders["Archive"] = {"flags": (b"\\HasNoChildren", b"\\Archive"), "messages": {}}
		for name in ("Drafts", "Archive"):
			self.validity[name], self.next_uid[name] = 1, 1
		self.asked = []

	def add(self, folder, sender, to, subject, when, flags=(b"\\Seen",), structure=BODY_ONLY, cc=""):
		raw = f"From: {sender}\r\nTo: {to}\r\nCc: {cc}\r\nSubject: {subject}\r\n\r\nbody".encode()
		uid = self.put(folder, raw, flags, when)
		self.folders[folder]["messages"][uid]["structure"] = structure
		return uid

	def _wanted(self, criteria):
		"""The (field, text) the criteria look for, and the day before which."""
		atoms, before, i = [], None, 0
		while i < len(criteria):
			if criteria[i] in ("FROM", "TO", "CC"):
				atoms.append((criteria[i], criteria[i + 1].lower()))
				i += 2
			elif criteria[i] == "BEFORE":
				before = datetime.strptime(criteria[i + 1], "%d-%b-%Y").date()
				i += 2
			else:
				i += 1
		return atoms, before

	def _matching(self, criteria):
		atoms, before = self._wanted(criteria)
		found = []
		for uid, message in self._messages().items():
			if b"\\Deleted" in message["flags"]:
				continue
			head = email.message_from_bytes(message["raw"])
			if before and message["date"].date() >= before:
				continue
			if any(text in str(head.get(field.title()) or "").lower() for field, text in atoms):
				found.append(uid)
		return found

	def search(self, criteria, charset=None):
		self.asked.append((self.selected, list(criteria)))
		return self._matching(criteria)

	def sort(self, sort_criteria, criteria):
		self.asked.append((self.selected, list(criteria)))
		messages = self._messages()
		return sorted(self._matching(criteria), key=lambda uid: (messages[uid]["date"], uid), reverse=True)

	def fetch(self, uids, items):
		known = [i for i in items if i in ("FLAGS", "INTERNALDATE", "RFC822.SIZE")]
		out = super().fetch(uids, known)
		for uid in list(out):
			message = self._messages()[uid]
			head = email.message_from_bytes(message["raw"])
			if "ENVELOPE" in items:
				out[uid][b"ENVELOPE"] = SimpleNamespace(
					from_=[_address(head["From"])],
					to=[_address(each) for each in head["To"].split(",") if each.strip()],
					subject=head["Subject"].encode(),
				)
			if "BODYSTRUCTURE" in items:
				out[uid][b"BODYSTRUCTURE"] = message.get("structure")
		return out


class TestNeomailHistory(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email_address in (OWNER, STRANGER):
			_user(email_address, True)
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

	def tearDown(self):
		frappe.set_user("Administrator")

	def server(self):
		server = HistoryServer()
		add = server.add
		add("INBOX", CLIENT, ME, "Re: Offre", datetime(2026, 10, 29, 10, 0))
		add("INBOX", OTHER, ME, "Not them", datetime(2026, 10, 28, 9, 0))
		add("INBOX", CLIENT, ME, "Offre", datetime(2026, 10, 27, 8, 0), structure=PDF)
		add("Sent", ME, CLIENT, "Re: Offre", datetime(2026, 10, 29, 12, 0))
		add("Archive", CLIENT, ME, "Facture", datetime(2026, 9, 30, 14, 0))
		add("Trash", CLIENT, ME, "Thrown away", datetime(2026, 10, 30, 8, 0))
		add("Drafts", ME, CLIENT, "Not sent yet", datetime(2026, 10, 31, 8, 0))
		return server

	def ask(self, server, user=OWNER, **args):
		frappe.set_user(user)
		with served(server):
			return neomail_history.history_get(
				{"accountId": account_id(MAILBOX), "addresses": [CLIENT], **args}
			)

	def test_the_messages_of_someone_are_in_every_folder_but_trash_and_drafts_the_newest_first(self):
		answer = self.ask(self.server())
		self.assertEqual(
			[(row["subject"], row["folder"], row["direction"]) for row in answer["list"]],
			[
				("Re: Offre", "Sent", "out"),
				("Re: Offre", "INBOX", "in"),
				("Offre", "INBOX", "in"),
				("Facture", "Archive", "in"),
			],
		)
		self.assertEqual(answer["total"], 4)
		self.assertIsNone(answer["next"])
		self.assertEqual(answer["scanned"], {"folders": 4, "of": 4})
		self.assertEqual([row["role"] for row in answer["list"]], ["sent", "inbox", "inbox", "archive"])
		self.assertEqual(answer["list"][0]["receivedAt"][:10], "2026-10-29")
		self.assertTrue(answer["list"][1]["mailboxId"] == mailbox_id("INBOX"))

	def test_a_page_at_a_time_and_the_total_on_the_first_one_only(self):
		server = self.server()
		first = self.ask(server, limit=2)
		self.assertEqual(len(first["list"]), 2)
		self.assertEqual(first["total"], 4)
		self.assertEqual(first["next"], first["list"][-1]["receivedAt"])
		second = self.ask(server, limit=2, before=first["next"])
		self.assertEqual([row["subject"] for row in second["list"]], ["Offre", "Facture"])
		self.assertIsNone(second["total"])
		self.assertIsNone(second["next"])
		everything = {row["id"] for row in first["list"] + second["list"]}
		self.assertEqual(len(everything), 4)

	def test_what_came_in_and_what_went_out(self):
		server = self.server()
		self.assertEqual({row["direction"] for row in self.ask(server, direction="in")["list"]}, {"in"})
		self.assertEqual([row["folder"] for row in self.ask(server, direction="out")["list"]], ["Sent"])
		with self.assertRaises(JmapError):
			self.ask(server, direction="sideways")

	def test_the_attachments_have_their_names_and_the_folders_can_be_chosen(self):
		answer = self.ask(self.server(), mailboxIds=[mailbox_id("INBOX")])
		offer = next(row for row in answer["list"] if row["subject"] == "Offre")
		self.assertTrue(offer["hasAttachment"])
		self.assertEqual(
			offer["attachments"], [{"id": "0", "name": "Offre.pdf", "type": "application/pdf", "size": 84000}]
		)
		self.assertEqual({row["folder"] for row in answer["list"]}, {"INBOX"})
		self.assertEqual([row["hasAttachment"] for row in answer["list"]], [False, True])

	def test_the_other_addresses_and_the_company_s_domain_are_searched_when_asked(self):
		server = self.server()
		server.add("INBOX", COLLEAGUE, ME, "From a colleague", datetime(2026, 10, 26, 8, 0))
		alone = self.ask(server)
		self.assertNotIn("From a colleague", [row["subject"] for row in alone["list"]])
		both = self.ask(server, addresses=[CLIENT, COLLEAGUE])
		self.assertIn("From a colleague", [row["subject"] for row in both["list"]])
		domain = self.ask(server, domains=True)
		self.assertIn("From a colleague", [row["subject"] for row in domain["list"]])
		# A public provider is never « the whole domain »
		self.assertEqual(neomail_history._domains(["someone@gmail.com", "x@bluewin.ch"]), [])
		self.assertEqual(neomail_history._domains([CLIENT, COLLEAGUE]), ["atelier-exemple.example"])

	def test_the_criteria_are_flat_and_ask_the_cc_only_when_told_to(self):
		two = neomail_history._criteria([CLIENT, COLLEAGUE], "all", False, [], "", None)
		self.assertEqual(
			two,
			[
				"OR",
				"OR",
				"OR",
				"FROM",
				CLIENT,
				"TO",
				CLIENT,
				"FROM",
				COLLEAGUE,
				"TO",
				COLLEAGUE,
				"NOT",
				"DELETED",
			],
		)
		self.assertIn("CC", neomail_history._criteria([CLIENT], "all", True, [], "", None))
		self.assertNotIn("CC", neomail_history._criteria([CLIENT], "in", True, [], "", None))
		before = neomail_history._criteria([CLIENT], "out", False, [], "", datetime(2026, 10, 29, 12, 0))
		self.assertEqual(before[-2:], ["BEFORE", date(2026, 10, 30).strftime("%d-%b-%Y")])

	def test_what_is_asked_is_checked(self):
		server = self.server()
		for args in (
			{"addresses": []},
			{"addresses": ["not an address"]},
			{"addresses": [CLIENT] * 9 + ["a@b.example"]},
			{"before": "yesterday"},
			{"limit": "ten"},
			{"mailboxIds": "INBOX"},
		):
			with self.subTest(args=args), self.assertRaises(JmapError):
				self.ask(server, **args)

	def test_a_mailbox_that_is_not_the_person_s_is_not_read(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask(self.server(), user=STRANGER)

	def test_the_session_offers_the_three_methods(self):
		frappe.set_user(OWNER)
		session = _session(MAILBOX)
		self.assertIn(neomail_history.HISTORY, session["capabilities"])
		self.assertIn(neomail_history.HISTORY, session["primaryAccounts"])
		methods = _more_methods()
		for name in ("NeomailContact/get", "NeomailHistory/get", "NeomailLinked/get"):
			self.assertIn(name, methods)

	def test_the_attachments_of_a_structure_follow_the_rule_of_the_webmail(self):
		inline = (
			b"image",
			b"png",
			(b"name", b"logo.png"),
			b"<logo1>",
			None,
			b"base64",
			900,
			None,
			(b"inline", (b"filename", b"logo.png")),
			None,
			None,
		)
		structure = (BODY_ONLY, PDF[1], inline, b"mixed")
		found = neomail_history.attachments_of(structure)
		self.assertEqual([each["name"] for each in found], ["Offre.pdf", "logo.png"])
		# The id is the part's Content-ID, else its rank among the attachments (mime_parts.iter_attachments)
		self.assertEqual([each["id"] for each in found], ["0", "logo1"])
		self.assertEqual(neomail_history.attachments_of(BODY_ONLY), [])
		self.assertEqual(neomail_history.attachments_of(None), [])

	def test_who_someone_is_and_the_addresses_of_the_whole_company(self):
		contacts = []
		for address in (CLIENT, COLLEAGUE):
			contact = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": address.split("@")[0],
					"email_ids": [{"email_id": address, "is_primary": 1}],
					"links": [{"link_doctype": "User", "link_name": "Administrator"}],
				}
			)
			contact.insert(ignore_permissions=True)
			contacts.append(contact.name)
		try:
			self.assertLessEqual(
				{CLIENT, COLLEAGUE}, set(neomail_history.party_addresses("User", "Administrator"))
			)
			frappe.set_user("Administrator")
			frappe.db.set_value("Webmail Account", MAILBOX, "user", "Administrator")
			asked = f"Claire <{CLIENT.upper()}>"
			answer = neomail_history.contact_get({"accountId": account_id(MAILBOX), "address": asked})
			self.assertTrue(answer["known"])
			self.assertEqual(answer["address"], CLIENT)
			self.assertEqual(answer["addresses"][0], CLIENT)
			self.assertEqual(answer["contact"]["fullName"], "claire")
			self.assertIsNone(answer["party"])
			self.assertEqual(answer["domains"], ["atelier-exemple.example"])
			nobody = neomail_history.contact_get({"accountId": account_id(MAILBOX), "address": OTHER})
			self.assertFalse(nobody["known"])
			self.assertEqual(nobody["addresses"], [OTHER])
			with self.assertRaises(JmapError):
				neomail_history.contact_get({"accountId": account_id(MAILBOX), "address": "nobody"})
		finally:
			frappe.db.set_value("Webmail Account", MAILBOX, "user", OWNER)
			for name in contacts:
				frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)

	def test_what_neoffice_links_someone_to_without_the_mails_and_the_cancelled_waiting_ones_first(self):
		def row(doctype, name, cat, kind, docstatus, tone, day, **more):
			return {
				"doctype": doctype,
				"name": name,
				"cat": cat,
				"kind": kind,
				"docstatus": docstatus,
				"tone": tone,
				"date": day,
				**more,
			}

		rows = [
			row("Quotation", "Q-1", "sales", "Quote", 1, None, "2026-10-27"),
			row("Communication", "C-1", "mail", "Mail", 0, None, "2026-10-29"),
			row("Sales Invoice", "SI-1", "sales", "Invoice", 2, None, "2026-10-20"),
			row(
				"Sales Invoice",
				"SI-2",
				"sales",
				"Invoice",
				1,
				"warn",
				"2026-09-30",
				status="Unpaid",
				amount=1260.0,
				currency="CHF",
			),
		]
		found = {"contact": {"name": "c"}, "card": {"doctype": "Customer", "name": "CUST-1"}}
		frappe.set_user("Administrator")
		frappe.db.set_value("Webmail Account", MAILBOX, "user", "Administrator")
		try:
			with (
				patch.object(neomail_history, "_party_of", return_value=(found, None)),
				patch.object(
					neomail_history, "_everything", return_value=lambda doctype, name: {"items": rows}
				),
			):
				answer = neomail_history.linked_get({"accountId": account_id(MAILBOX), "address": CLIENT})
			self.assertEqual(answer["thing"]["doctype"], "Customer")
			self.assertIn("/app/history/Customer/CUST-1", answer["thing"]["everything"])
			self.assertEqual([row["name"] for row in answer["rows"]], ["SI-2", "Q-1"])
			self.assertEqual(answer["total"], 2)
			self.assertEqual(answer["rows"][0]["amount"], 1260.0)
			self.assertIn("/app/", answer["rows"][1]["url"])
			# A site without « Tout voir »: no rows, no error
			with patch.object(neomail_history, "_everything", return_value=None):
				bare = neomail_history.linked_get({"accountId": account_id(MAILBOX), "address": CLIENT})
			self.assertEqual((bare["thing"], bare["rows"]), (None, []))
		finally:
			frappe.db.set_value("Webmail Account", MAILBOX, "user", OWNER)
