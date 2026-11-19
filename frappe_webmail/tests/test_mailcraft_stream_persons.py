# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""NeomailStream (mailcraft_stream.py), several persons in one mailbox: a person's choice of tab is theirs alone, for that mailbox
(neoffice-maintenance#3142: « for that person and that mailbox »). Same seams as test_mailcraft_stream.py: no network, no database."""

import pytest

from frappe_webmail import mailcraft_stream as ms
from frappe_webmail.tests.test_mailcraft_stream import (  # the two fixtures are used by their names (request.getfixturevalue)
	ACCOUNT,
	_ask,
	_correct,
	_ids,
	_message,
	box,
	corrections,
)


@pytest.fixture
def two_persons(request, monkeypatch):
	"""A mailbox shared by alice and bob: what is kept of the choices is kept per person and mailbox, as NeoMail Setting does."""
	base = request.getfixturevalue("corrections")
	kept, who = {}, ["alice"]
	monkeypatch.setattr(ms, "_prefs", lambda user, account_name: dict(kept.get((user, account_name), {})))

	def keep(user, account_name, chosen):
		kept.setdefault((user, account_name), {}).update(chosen)

	monkeypatch.setattr(ms, "_keep_choices", keep)
	monkeypatch.setattr(ms, "_who", lambda: who[0])
	base.kept_by_person, base.sign_in = kept, lambda user: who.__setitem__(0, user)
	return base


def test_what_a_person_chose_moves_their_senders_other_messages_and_nobody_elses(two_persons):
	two_persons.messages[4] = _message("marie.favre@exemple.ch", subject="autre chose")
	three, four = _ids(3, 4)
	_correct((three, "newsletter"))
	assert list(two_persons.kept_by_person) == [("alice", ACCOUNT.name)]
	alice = {e["id"]: e for e in _ask([three, four])["list"]}
	assert {alice[i]["stream"] for i in (three, four)} == {"newsletter"}
	two_persons.sign_in("bob")
	assert two_persons.kept_by_person.get(("bob", ACCOUNT.name)) is None  # bob chose nothing


@pytest.mark.xfail(
	strict=True,
	reason="the corrected message is cached for the whole mailbox as `person`: another person of that mailbox reads it (neoffice-maintenance#3151)",
)
def test_another_person_of_the_mailbox_does_not_see_the_choice(two_persons):
	three = _ids(3)[0]
	_correct((three, "newsletter"))
	two_persons.sign_in("bob")
	entry = _ask([three])["list"][0]
	assert (entry["stream"], entry["source"]) != ("newsletter", "person")
