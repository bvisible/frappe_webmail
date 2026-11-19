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
		busy=set(),
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
	monkeypatch.setattr(ms, "_who", lambda: "marc@garage.example")
	monkeypatch.setattr(ms, "_job_busy", lambda job_id: job_id in state.busy)
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
	answer = _ask(_ids(1, 2, 3))
	# and a hash of the sender (a person's corrections move their others, neoffice-maintenance#3142), never told to NeoMail
	assert all(set(v) == {"stream", "source", "from"} for v in box.cache.store.values())
	assert all(set(e) == {"id", "stream", "source"} for e in answer["list"])
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


def test_one_person_keeps_so_many_jobs_for_a_mailbox_whatever_the_sets_asked(box, monkeypatch):
	"""Each different set of pending messages made a job of its own: one person asking with other sets kept the short
	queue busy for everyone. A job takes one of JOBS_PER_MAILBOX places; while they are all taken, nothing more is queued
	and the ids stay pending (the next ask tries again)."""
	box.delay = 0.6
	monkeypatch.setattr(ms, "BUDGET_S", 0.05)
	# Messages from people, which the headers do not settle: each set asked leaves them pending
	box.messages.update({4: _message("anne.rochat@exemple.ch"), 5: _message("luc.monnet@exemple.ch")})

	def ask_and_hold(uids):
		before = len(box.enqueued)
		answer = _ask(_ids(*uids))
		for _args, kwargs in box.enqueued[before:]:
			box.busy.add(kwargs["job_id"])  # the job queued is now running
		return answer

	answers = [ask_and_hold(uids) for uids in ((3,), (4,), (5,), (3, 4, 5))]
	assert len(box.enqueued) == ms.JOBS_PER_MAILBOX
	assert len({kwargs["job_id"] for _a, kwargs in box.enqueued}) == ms.JOBS_PER_MAILBOX
	assert answers[-1]["pending"], "what could not be queued stays pending, to be asked again"
	# A place freed, the next ask queues again: the legitimate tab carries on
	box.busy.clear()
	ask_and_hold((3, 4, 5))
	assert len(box.enqueued) == ms.JOBS_PER_MAILBOX + 1


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


# The phone's Mail tab (get_streams): the same answer, named by a folder and the UIDs of its list


@pytest.fixture
def phone(box, monkeypatch):
	box.validity = 7
	box.accounts = []
	monkeypatch.setattr(ms, "_validity", lambda account, folder: box.validity)

	def get_account(name):
		box.accounts.append(name)
		return ACCOUNT

	monkeypatch.setattr(jmap.webmail, "get_account", get_account)
	return box


def test_the_phone_reads_the_kind_of_each_message_by_its_uid(phone):
	answer = ms.get_streams(ACCOUNT.name, "INBOX", "[1, 2, 3]")
	assert answer == {
		"enabled": True,
		"streams": {"1": "newsletter", "2": "notification", "3": "person"},
		"pending": [],
	}
	# the mailbox is checked under the webmail's rule (owner or shared), and the same cache serves NeoMail's tabs
	assert phone.accounts == [ACCOUNT.name]
	assert len(phone.cache.store) == 3


def test_the_phone_reads_numbers_separated_by_commas_and_never_twice_the_same(phone):
	answer = ms.get_streams(ACCOUNT.name, "INBOX", "2, 2,1")
	assert set(answer["streams"]) == {"1", "2"} and phone.reads == [("INBOX", 7, [2, 1])]


def test_the_phone_asks_again_what_the_model_has_not_answered(phone, monkeypatch):
	phone.delay = 0.6
	monkeypatch.setattr(ms, "BUDGET_S", 0.05)
	answer = ms.get_streams(ACCOUNT.name, "INBOX", "[1, 3]")
	assert answer["streams"] == {"1": "newsletter"} and answer["pending"] == [3]


def test_nothing_is_read_where_the_site_does_not_offer_the_tabs(phone, monkeypatch):
	monkeypatch.setattr(ms, "enabled", lambda: False)
	assert ms.get_streams(ACCOUNT.name, "INBOX", "[1]") == {"enabled": False, "streams": {}, "pending": []}
	assert phone.reads == [] and phone.accounts == []


def test_a_folder_that_cannot_be_opened_says_nothing(phone):
	phone.validity = None
	assert ms.get_streams(ACCOUNT.name, "Gone", "[1]") == {"enabled": True, "streams": {}, "pending": []}
	assert phone.reads == []


TOO_MANY = ",".join(str(n) for n in range(1, ms.MAX_IDS + 2))


@pytest.mark.parametrize("uids", ['["x"]', "a,b", "[0]", "[-3]", TOO_MANY])
def test_the_uids_are_checked(phone, uids):
	with pytest.raises(frappe.ValidationError):
		ms.get_streams(ACCOUNT.name, "INBOX", uids)
	assert phone.reads == []


# ---------------------------------------------------------------------------------------------------------------
# A person's corrections (neoffice-maintenance#3142)
# ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def corrections(box, monkeypatch):
	"""The site also takes corrections; what is kept of the person's choices and what goes to the box are recorded."""
	box.kept, box.prefs, box.taught = [], {}, []
	monkeypatch.setattr(ms, "corrections_enabled", lambda: True)
	monkeypatch.setattr(ms, "_prefs", lambda user, account_name: dict(box.prefs))

	def keep(user, account_name, chosen):
		box.kept.append((user, account_name, dict(chosen)))
		box.prefs.update(chosen)

	monkeypatch.setattr(ms, "_keep_choices", keep)
	return box


def _correct(*pairs, sender=None):
	corrections = [{"id": i, "stream": s} for i, s in pairs]
	if sender is not None:
		corrections = [{**c, "sender": sender} for c in corrections]
	return ms.stream_set({"accountId": "Aaaa", "corrections": corrections})


def test_the_capability_says_correct_only_where_the_site_takes_corrections(monkeypatch):
	monkeypatch.setattr(ms, "enabled", lambda: True)
	monkeypatch.setattr(ms, "corrections_enabled", lambda: False)
	assert "correct" not in ms.session_parts(ACCOUNT)[1][ms.STREAM]
	monkeypatch.setattr(ms, "corrections_enabled", lambda: True)
	assert ms.session_parts(ACCOUNT)[1][ms.STREAM]["correct"] is True


def test_the_set_method_is_unknown_without_the_key(box):
	with pytest.raises(jmap.JmapError) as error:
		_correct((_ids(3)[0], "newsletter"))
	assert error.value.type == "unknownMethod" and box.reads == [] and box.enqueued == []


@pytest.mark.parametrize(
	"bad",
	[
		None,
		[],
		[{"id": "x"}],
		[{"id": "x", "stream": "spam"}],
		[{"id": 3, "stream": "person"}],
		[{"id": "x" * 300, "stream": "person"}],
		[{"id": "x", "stream": "person", "sender": "yes"}],
	],
)
def test_the_corrections_are_checked(bad, monkeypatch, box):
	monkeypatch.setattr(ms, "corrections_enabled", lambda: True)
	with pytest.raises(jmap.JmapError) as error:
		ms.stream_set({"accountId": "Aaaa", "corrections": bad})
	assert error.value.type == "invalidArguments"


def test_a_corrected_message_moves_at_once_and_the_box_hears_of_it_in_a_job(corrections):
	three = _ids(3)[0]
	answer = _correct((three, "newsletter"))
	assert answer["updated"] == [three] and answer["notUpdated"] == {}
	entry = _ask([three])["list"][0]
	assert (entry["stream"], entry["source"]) == ("newsletter", "person")
	# The message alone: its sender is not chosen unless the person says yes to the next ones too.
	assert corrections.kept == [
		("marc@garage.example", ACCOUNT.name, {ms.message_key("INBOX", 7, 3): "newsletter"})
	]
	((_args, job),) = corrections.enqueued
	assert job["taught"] == [[3, "newsletter"]] and job["folder"] == "INBOX" and job["validity"] == 7


def test_the_persons_choice_moves_the_senders_other_messages(corrections):
	corrections.messages[4] = _message("marie.favre@exemple.ch", subject="autre chose")
	corrections.prefs[ms.sender_hash("marie.favre@exemple.ch")] = "notification"
	by_id = {e["id"]: e for e in _ask(_ids(3, 4, 1))["list"]}
	three, four, one = _ids(3, 4, 1)
	assert (by_id[three]["stream"], by_id[three]["source"]) == ("notification", "person")
	assert (by_id[four]["stream"], by_id[four]["source"]) == ("notification", "person")
	assert by_id[one]["source"] == "headers"  # another sender stays as it was
	again = {e["id"]: e for e in _ask(_ids(3, 4))["list"]}  # from the cache too
	assert again[three]["source"] == again[four]["source"] == "person"


def test_a_message_gone_is_not_updated(corrections):
	corrections.gone = True
	three = _ids(3)[0]
	answer = _correct((three, "person"))
	assert (
		answer["updated"] == []
		and three in answer["notUpdated"]
		and corrections.kept == []
		and corrections.enqueued == []
	)


def test_the_job_tells_the_box_what_the_model_reads_and_the_persons_tab(corrections, monkeypatch):
	decide = pytest.importorskip("nora.api.decide")  # the app's own CI does not install nora

	told = []
	monkeypatch.setattr(
		decide, "feedback", lambda task, text, label: told.append((task, text, label)), raising=False
	)
	monkeypatch.setattr(jmap.webmail, "get_account", lambda name: ACCOUNT)
	ms.teach(ACCOUNT.name, "INBOX", 7, [[3, "newsletter"]])
	((task, text, label),) = told
	assert (task, label) == ("mail_stream", "newsletter")
	assert text == ms.stream.model_text("Marc", "marie.favre@exemple.ch", "devis", "Ok pour mardi.")


def test_the_newest_choices_are_kept_and_no_more_than_the_limit(monkeypatch):
	written = []
	from frappe_webmail import mailcraft_settings

	monkeypatch.setattr(mailcraft_settings, "_write", lambda user, account, fields: written.append(fields))
	monkeypatch.setattr(ms, "MAX_PREFS", 3)
	monkeypatch.setattr(
		ms, "_prefs", lambda user, account_name: {"a": "person", "b": "person", "c": "newsletter"}
	)
	ms._keep_choices("marc@garage.example", ACCOUNT.name, {"a": "notification", "d": "person"})
	assert list(written[0][ms.PREFS_FIELD].items()) == [
		("c", "newsletter"),
		("a", "notification"),
		("d", "person"),
	]


def test_a_sender_is_kept_as_a_hash_never_as_its_address():
	h = ms.sender_hash(" Marie.Favre@Exemple.ch ")
	assert h == ms.sender_hash("marie.favre@exemple.ch") and "exemple" not in h and len(h) == 20


# A message alone, or its sender too (« the next ones from this sender too ? », as Gmail asks)


def test_a_correction_moves_its_message_and_not_its_senders_others(corrections):
	corrections.messages[4] = _message("marie.favre@exemple.ch", subject="autre chose")
	three, four = _ids(3, 4)
	_correct((three, "newsletter"))
	by_id = {e["id"]: e for e in _ask([three, four])["list"]}
	assert (by_id[three]["stream"], by_id[three]["source"]) == ("newsletter", "person")
	assert by_id[four]["source"] != "person", "the sender's other message is left as the model says"


def test_with_the_sender_its_others_and_next_ones_follow(corrections):
	corrections.messages[4] = _message("marie.favre@exemple.ch", subject="autre chose")
	three, four = _ids(3, 4)
	_correct((three, "notification"), sender=True)
	sender = ms.sender_hash("marie.favre@exemple.ch")
	assert corrections.prefs[sender] == "notification"
	by_id = {e["id"]: e for e in _ask([three, four])["list"]}
	assert {by_id[i]["stream"] for i in (three, four)} == {"notification"}


def test_a_messages_own_choice_wins_over_its_senders(corrections):
	corrections.messages[4] = _message("marie.favre@exemple.ch", subject="autre chose")
	three, four = _ids(3, 4)
	_correct((three, "person"))
	_correct((four, "newsletter"), sender=True)
	by_id = {e["id"]: e for e in _ask([three, four])["list"]}
	assert (by_id[three]["stream"], by_id[four]["stream"]) == ("person", "newsletter")


def test_the_yes_after_a_correction_does_not_teach_the_box_twice(corrections):
	three = _ids(3)[0]
	_correct((three, "newsletter"))
	_correct((three, "newsletter"), sender=True)
	assert len(corrections.enqueued) == 1, "the same message under the same tab is taught once"
	_correct((three, "notification"))
	assert len(corrections.enqueued) == 2, "a new tab for it is new"
