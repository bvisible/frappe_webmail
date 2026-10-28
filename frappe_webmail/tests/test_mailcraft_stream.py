# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""NeomailStream/get (mailcraft_stream.py): the kind of sender of each message of a window, for NeoMail's tabs. Offered only where the
site asks; asks nothing of a message that is in the cache; the headers settle what they can and the model has a few seconds for the
rest, which comes back as pending and is finished by a job; what the cache keeps is a kind and a source, never a word of a message;
nothing is written to a mailbox. The mailbox, the cache and the model are replaced by recorders: no network, no database."""

import time
from types import SimpleNamespace

import frappe
import pytest

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import mailcraft_stream as ms

ACCOUNT = SimpleNamespace(name="marc@garage.example")


class FakeCache:
	def __init__(self):
		self.store, self.ttl = {}, {}

	def get_value(self, key):
		return self.store.get(key)

	def set_value(self, key, value, expires_in_sec=None):
		self.store[key] = value
		self.ttl[key] = expires_in_sec


def _message(address="marc@garage.example", headers=None, subject="devis", name="Marc"):
	return {"name": name, "address": address, "subject": subject, "headers": headers or {}}


@pytest.fixture
def box(monkeypatch):
	"""A site that offers the tabs, with a mailbox of three messages, a cache of dicts and a model that says what the test says."""
	state = SimpleNamespace(
		cache=FakeCache(),
		messages={
			1: _message("news@brand.example", {"List-Unsubscribe": "<https://brand.example/out>"}),
			2: _message("noreply@tool.example", {}),
			3: _message("marie.favre@exemple.ch"),
		},
		gone=False,
		reads=[],
		previews=[],
		asked=[],
		enqueued=[],
		counts=[],
		model={"label": "person", "probability": 0.99, "abstain": False, "source": "student:laya-fr"},
		delay=0.0,
	)

	def read(account, folder, validity, uids):
		state.reads.append((folder, validity, list(uids)))
		return ({} if state.gone else {u: state.messages[u] for u in uids if u in state.messages}), state.gone

	def previews(account, folder, validity, uids):
		state.previews.append(list(uids))
		return {u: "Ok pour mardi." for u in uids}

	def model():
		def ask(text):
			time.sleep(state.delay)
			state.asked.append(text)
			return state.model

		return ask

	monkeypatch.setattr(ms, "enabled", lambda: True)
	monkeypatch.setattr(ms, "_cache", lambda: state.cache)
	monkeypatch.setattr(ms, "_read", read)
	monkeypatch.setattr(ms, "_previews", previews)
	monkeypatch.setattr(ms, "_model", model)
	monkeypatch.setattr(ms, "_count", lambda outcome, amount=1: state.counts.append((outcome, amount)))
	monkeypatch.setattr(jmap, "_account", lambda jmap_id: ACCOUNT)
	monkeypatch.setattr(frappe, "enqueue", lambda *a, **k: state.enqueued.append((a, k)), raising=False)
	return state


def _ids(*uids, folder="INBOX", validity=7):
	return [jmap.email_id(folder, validity, u) for u in uids]


def _ask(ids):
	return ms.stream_get({"accountId": "Aaaa", "ids": ids})


def test_the_capability_is_offered_only_where_the_site_asks(monkeypatch):
	monkeypatch.setattr(ms, "enabled", lambda: False)
	assert ms.session_parts(ACCOUNT) == ({}, {})
	monkeypatch.setattr(ms, "enabled", lambda: True)
	session, account = ms.session_parts(ACCOUNT)
	assert ms.STREAM in session and account[ms.STREAM]["maxIds"] == ms.MAX_IDS


def test_the_method_is_unknown_where_the_site_does_not_offer_it(box, monkeypatch):
	monkeypatch.setattr(ms, "enabled", lambda: False)
	with pytest.raises(jmap.JmapError) as error:
		_ask(_ids(1))
	assert error.value.type == "unknownMethod" and box.reads == []


@pytest.mark.parametrize("ids", [None, [], "E1", [1], ["x"] * (ms.MAX_IDS + 1), ["x" * 300]])
def test_the_ids_are_checked(box, ids):
	with pytest.raises(jmap.JmapError) as error:
		ms.stream_get({"accountId": "Aaaa", "ids": ids})
	assert error.value.type == "invalidArguments"


def test_the_headers_settle_what_they_can_and_the_model_the_rest(box):
	answer = _ask(_ids(1, 2, 3))
	by_id = {e["id"]: e for e in answer["list"]}
	one, two, three = _ids(1, 2, 3)
	assert (by_id[one]["stream"], by_id[one]["source"]) == ("newsletter", "headers")
	assert (by_id[two]["stream"], by_id[two]["source"]) == ("notification", "headers")
	assert (by_id[three]["stream"], by_id[three]["source"]) == ("person", "model")
	assert answer["notFound"] == [] and answer["pending"] == []
	# the body's first words were read only for the message the headers did not settle, and only that one went to the model
	assert box.previews == [[3]] and len(box.asked) == 1 and "marie.favre@exemple.ch" in box.asked[0]


def test_a_message_in_the_cache_is_not_read_nor_asked_again(box):
	_ask(_ids(1, 2, 3))
	box.reads.clear()
	box.asked.clear()
	again = _ask(_ids(1, 2, 3))
	assert len(again["list"]) == 3 and box.reads == [] and box.asked == []


def test_the_cache_keeps_a_kind_and_a_source_and_never_a_word_of_a_message(box):
	_ask(_ids(1, 2, 3))
	assert all(set(v) == {"stream", "source"} for v in box.cache.store.values())
	text = " ".join(list(box.cache.store) + [str(v) for v in box.cache.store.values()])
	assert "garage" not in text and "brand.example" not in text and "devis" not in text
	# settled by the headers or the model: long; settled by nothing: short
	assert set(box.cache.ttl.values()) == {ms.CACHE_S}


def test_without_a_model_a_message_nothing_settles_is_a_person_for_a_short_while(box, monkeypatch):
	monkeypatch.setattr(ms, "_model", lambda: None)
	answer = _ask(_ids(3))
	assert (
		answer["list"][0]["stream"] == "person"
		and answer["list"][0]["source"] == "default"
		and answer["pending"] == []
	)
	assert set(box.cache.ttl.values()) == {ms.DEFAULT_CACHE_S}
	assert ("unavailable", 1) in box.counts


def test_a_model_that_is_not_sure_leaves_a_person(box):
	box.model = {"label": "newsletter", "probability": 0.55, "abstain": True}
	answer = _ask(_ids(3))
	assert (answer["list"][0]["stream"], answer["list"][0]["source"]) == ("person", "default")


def test_a_slow_model_comes_back_as_pending_and_is_finished_by_a_job(box, monkeypatch):
	box.delay = 0.6
	monkeypatch.setattr(ms, "BUDGET_S", 0.05)
	answer = _ask(_ids(1, 3))
	one, three = _ids(1, 3)
	assert [e["id"] for e in answer["list"]] == [one] and answer["pending"] == [three]
	assert len(box.enqueued) == 1
	args, kwargs = box.enqueued[0]
	assert (
		args == ("frappe_webmail.mailcraft_stream.finish",)
		and kwargs["uids"] == [3]
		and kwargs["queue"] == "short"
	)
	assert kwargs["deduplicate"] is True and kwargs["account_name"] == ACCOUNT.name
	assert not any(
		"model" in str(v) for v in box.cache.store.values()
	)  # nothing kept for the one that is still pending


def test_the_job_puts_the_answers_in_the_cache(box, monkeypatch):
	monkeypatch.setattr(jmap.webmail, "get_account", lambda name: ACCOUNT, raising=False)
	ms.finish(ACCOUNT.name, "INBOX", 7, [1, 3])
	assert {v["stream"] for v in box.cache.store.values()} == {"newsletter", "person"}


def test_ids_of_a_folder_that_was_recreated_are_not_found(box):
	box.gone = True
	answer = _ask(_ids(1, 2))
	assert answer["list"] == [] and sorted(answer["notFound"]) == sorted(_ids(1, 2))


def test_ids_that_are_not_message_ids_are_not_found(box):
	answer = _ask(["not-an-id", *_ids(1)])
	assert answer["notFound"] == ["not-an-id"] and len(answer["list"]) == 1


def test_a_message_gone_from_the_folder_is_not_found(box):
	answer = _ask(_ids(1, 9))
	assert answer["notFound"] == _ids(9) and len(answer["list"]) == 1


def test_classify_without_any_message_asks_nothing(box):
	assert ms.classify({}, lambda uids: {}, None, time.monotonic() + 1) == ({}, [])


def test_the_same_message_in_two_folders_is_two_keys():
	assert ms._key("a@b.example", "INBOX", 7, 1) != ms._key("a@b.example", "Archive", 7, 1)
	assert ms._key("a@b.example", "INBOX", 7, 1) != ms._key("a@b.example", "INBOX", 8, 1)
	assert ms._key("a@b.example", "INBOX", 7, 1) == ms._key("a@b.example", "INBOX", 7, 1)
