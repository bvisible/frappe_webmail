# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The new senders of a mailbox (new_senders.py), for the phone's « Nouveaux expéditeurs »: NeoMail's rule (14 days, not in
the person's lists, not a contact, never written to, no older mail, nothing answered), « Accepter » into the Safe Senders,
« Bloquer » into the Blocked Senders with the inbox's mail moved to the Junk folder; the lists are NeoMail's own. The
mailbox, the contacts, the lists and the cache are replaced by recorders: no network, no database."""

from types import SimpleNamespace

import frappe
import pytest

from frappe_webmail import new_senders as ns
from frappe_webmail import webmail_api as webmail

ACCOUNT = SimpleNamespace(name="atelier@exemple.test")


def _mail(address, subject="Bonjour", answered=False, name=""):
	return {
		"address": address,
		"name": name,
		"subject": subject,
		"date": "2026-11-14 08:00:00",
		"answered": answered,
	}


class FakeCache:
	def __init__(self):
		self.store, self.deleted = {}, []

	def get_value(self, key):
		return self.store.get(key)

	def set_value(self, key, value, expires_in_sec=None):
		self.store[key] = value

	def delete_value(self, key):
		self.deleted.append(key)
		self.store.pop(key, None)


@pytest.fixture
def box(monkeypatch):
	state = SimpleNamespace(
		messages=[
			_mail("lea@nouveau.test", "Une question", name="Léa"),
			_mail("client@connu.test", "Re: devis"),
			_mail("lea@nouveau.test", "Encore une question"),
			_mail("deja@repondu.test", "Merci", answered=True),
			_mail("promo@marque.test", "Soldes"),
			_mail("ami@contact.test", "Salut"),
		],
		known={"client@connu.test"},
		contacts={"ami@contact.test"},
		lists=([], ["marque.test"]),
		kept=[],
		moved=[],
		scans=0,
		cache=FakeCache(),
	)

	def scan(account, since, lists):
		state.scans += 1
		return state.messages, set(state.known)

	monkeypatch.setattr(ns, "_scan", scan)
	monkeypatch.setattr(ns, "_contacts", lambda addresses: {a for a in addresses if a in state.contacts})
	monkeypatch.setattr(ns, "_lists", lambda user, account_name: (list(state.lists[0]), list(state.lists[1])))

	def keep(user, account_name, safe, blocked):
		state.kept.append((account_name, safe, blocked))
		state.lists = (safe, blocked)

	monkeypatch.setattr(ns, "_keep_lists", keep)

	def move(account, address):
		state.moved.append(address)
		return 2

	monkeypatch.setattr(ns, "_block_move", move)
	monkeypatch.setattr(ns, "_cache", lambda: state.cache)
	monkeypatch.setattr(webmail, "get_account", lambda name: ACCOUNT)
	return state


def test_a_new_sender_is_none_of_those_the_mailbox_knows(box):
	answer = ns.get_new_senders(ACCOUNT.name)
	assert answer["count"] == 1
	(lea,) = answer["senders"]
	assert (lea["address"], lea["name"], lea["count"], lea["subject"]) == (
		"lea@nouveau.test",
		"Léa",
		2,
		"Une question",
	)


def test_a_domain_in_a_list_leaves_out_its_every_address():
	assert ns.listed("promo@marque.test", ["marque.test"])
	assert ns.listed("promo@marque.test", ["@marque.test"])
	assert ns.listed("Promo@Marque.test", ["promo@marque.test"])
	assert not ns.listed("promo@marque.test", ["autre.test", "x@marque.test"])


def test_the_answer_is_kept_a_while_and_dropped_once_someone_is_accepted(box):
	ns.get_new_senders(ACCOUNT.name)
	ns.get_new_senders(ACCOUNT.name)
	assert box.scans == 1
	ns.set_new_sender(ACCOUNT.name, "lea@nouveau.test", "accept")
	ns.get_new_senders(ACCOUNT.name)
	assert box.scans == 2


def test_accepting_puts_the_address_in_the_safe_senders_and_moves_nothing(box):
	answer = ns.set_new_sender(ACCOUNT.name, " Lea@Nouveau.test ", "accept")
	assert answer == {"verdict": "accept", "moved": 0}
	assert box.kept == [(ACCOUNT.name, ["lea@nouveau.test"], ["marque.test"])]
	assert box.moved == []
	assert ns.get_new_senders(ACCOUNT.name)["count"] == 0


def test_blocking_puts_the_address_in_the_blocked_senders_and_moves_its_mail_to_junk(box):
	box.lists = (["lea@nouveau.test"], ["marque.test"])
	answer = ns.set_new_sender(ACCOUNT.name, "lea@nouveau.test", "block")
	assert answer == {"verdict": "block", "moved": 2}
	# out of the safe senders, into the blocked ones: one list at a time
	assert box.kept == [(ACCOUNT.name, [], ["marque.test", "lea@nouveau.test"])]
	assert box.moved == ["lea@nouveau.test"]


@pytest.mark.parametrize(
	"address, verdict",
	[("lea@nouveau.test", "maybe"), ("", "accept"), ("pas une adresse", "block"), ("exemple.test", "accept")],
)
def test_the_verdict_and_the_address_are_checked(box, address, verdict):
	with pytest.raises(frappe.ValidationError):
		ns.set_new_sender(ACCOUNT.name, address, verdict)
	assert box.kept == [] and box.moved == []


def test_newcomers_keeps_the_order_of_the_newest_mail():
	messages = [_mail("b@x.test"), _mail("a@x.test"), _mail("b@x.test"), _mail("c@x.test", answered=True)]
	assert [s["address"] for s in ns.newcomers(messages, ([], []), set())] == ["b@x.test", "a@x.test"]
	assert ns.candidates(messages, ([], ["a@x.test"])) == ["b@x.test"]
