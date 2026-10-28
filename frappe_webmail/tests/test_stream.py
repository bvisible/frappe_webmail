# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The stream of a message (stream.py): a person, a notification or a newsletter. The headers settle what a sending system leaves
behind; where two signals disagree they say nothing and the model reads the message; a message that nothing settles is a person's,
so that the Principal tab never hides mail nobody was sure about. Pure functions: the model is a recorder, nothing is read or written."""

from frappe_webmail import stream


def _kind(headers, address="someone@example.org"):
	return stream.of_headers(headers, address)["stream"]


def test_headers_are_read_from_a_dict_a_jmap_list_or_raw_text():
	raw = "List-Unsubscribe: <mailto:out@x.example>,\r\n <https://x.example/out>\r\nPrecedence: Bulk\r\nSubject: not kept\r\n"
	assert stream.header_map(raw)["list-unsubscribe"] == "<mailto:out@x.example>, <https://x.example/out>"
	assert stream.header_map([{"name": "Auto-Submitted", "value": " auto-generated "}]) == {
		"auto-submitted": "auto-generated"
	}
	assert stream.header_map({"List-Id": "<a.example>"}) == {"list-id": "<a.example>"}
	assert stream.header_map(None) == {} and stream.header_map(b"") == {}


def test_the_local_part_drops_a_plus_tag_and_the_case():
	assert stream.local_part("NoReply+abc@Brand.Example") == "noreply"
	assert stream.local_part("not-an-address") == ""


def test_a_message_that_says_it_is_automatic_is_a_notification():
	assert _kind({"Auto-Submitted": "auto-generated"}) == "notification"
	assert _kind({"Auto-Submitted": "auto-replied"}) == "notification"
	assert _kind({"X-Auto-Response-Suppress": "All"}) == "notification"
	assert _kind({"Auto-Submitted": "no"}) is None


def test_a_noreply_sender_is_a_notification_but_not_with_an_unsubscribe_link():
	assert _kind({}, "no-reply@tool.example") == "notification"
	assert _kind({}, "Notifications@forge.example") == "notification"
	assert _kind({"List-Unsubscribe": "<https://x.example/out>"}, "noreply@brand.example") is None


def test_an_unsubscribe_link_or_bulk_mark_is_a_newsletter():
	assert _kind({"List-Unsubscribe": "<https://x.example/out>"}, "hello@brand.example") == "newsletter"
	assert _kind({"Precedence": "bulk"}) == "newsletter"
	assert _kind({"X-Mailchimp-Id": "abc"}) == "newsletter"
	assert _kind({}, "newsletter@club.example") == "newsletter"
	assert _kind({}, "marketing@brand.example") == "newsletter"


def test_automatic_and_bulk_at_once_settles_nothing():
	assert _kind({"Auto-Submitted": "auto-generated", "List-Unsubscribe": "<https://x.example/out>"}) is None
	# a mailing list's or a forge's notification: a list id and a precedence, from a notifications address
	assert (
		_kind({"List-Id": "<proj.forge.example>", "Precedence": "list"}, "notifications@forge.example")
		is None
	)


def test_a_reply_in_a_thread_is_a_person_unless_it_comes_through_a_list():
	assert _kind({"In-Reply-To": "<abc@mail.example>"}, "marc@garage.example") == "person"
	assert _kind({"References": "<a@x> <b@x>"}) == "person"
	assert _kind({"In-Reply-To": "<abc@mail.example>", "List-Id": "<proj.forge.example>"}) is None


def test_small_firms_and_people_are_not_decided_by_their_address():
	assert _kind({}, "info@garage-du-lac.example") is None
	assert _kind({}, "support@helpdesk-tool.example") is None
	assert _kind({}, "marie.favre@exemple.ch") is None


class Model:
	"""nora-decide, replaced by a recorder."""

	def __init__(self, answer):
		self.answer, self.asked = answer, []

	def __call__(self, text):
		self.asked.append(text)
		return self.answer


def _message(**kw):
	return {
		"name": "Marc Favre",
		"address": "marc@garage.example",
		"subject": "devis",
		"preview": "Ok pour mardi.",
		**kw,
	}


def test_when_the_headers_settle_it_the_model_is_not_asked():
	model = Model({"label": "person", "probability": 0.99})
	out = stream.decide(_message(address="noreply@tool.example", headers={}), model)
	assert (out["stream"], out["source"]) == ("notification", "headers") and model.asked == []


def test_when_the_headers_say_nothing_a_sure_model_decides():
	model = Model({"label": "newsletter", "probability": 0.97, "abstain": False, "source": "student:laya-fr"})
	out = stream.decide(_message(), model)
	assert (out["stream"], out["source"], out["probability"]) == ("newsletter", "model", 0.97)
	assert model.asked == ["From: Marc Favre <marc@garage.example>\nSubject: devis\n\nOk pour mardi."]


def test_a_model_that_is_not_sure_or_absent_leaves_a_person():
	unsure = stream.decide(_message(), Model({"label": "newsletter", "probability": 0.55, "abstain": True}))
	assert (unsure["stream"], unsure["source"]) == ("person", "default")
	assert stream.decide(_message(), Model(None))["stream"] == "person"
	assert stream.decide(_message(), None)["why"] == "the model was not asked"
	assert (
		stream.decide(_message(), Model({"label": "other", "probability": 1.0, "abstain": False}))["source"]
		== "default"
	)


def test_the_text_the_model_reads_is_the_sender_the_subject_and_the_first_words():
	assert stream.model_text("", "a@b.example", "Hi", "x") == "From: a@b.example\nSubject: Hi\n\nx"
	long = "mot " * 100
	cut = stream.model_text("N", "a@b.example", "S", long)
	assert (
		cut.split("\n\n", 1)[1] == stream.preview_of(long) and len(stream.preview_of(long)) <= stream.PREVIEW
	)
	assert stream.preview_of("a\n\n b\t c") == "a b c"
	assert not stream.preview_of(long).endswith(" ")


class FakeClient:
	"""imapclient's answer to a fetch of header fields: the key is the one the server echoes."""

	def __init__(self):
		self.asked = []

	def fetch(self, uids, items):
		self.asked.append((list(uids), list(items)))
		return {
			7: {
				b"SEQ": 1,
				b"BODY[HEADER.FIELDS (LIST-UNSUBSCRIBE PRECEDENCE)]": b"List-Unsubscribe: <https://x.example/out>\r\n\r\n",
			},
			8: {b"BODY[HEADER.FIELDS (LIST-UNSUBSCRIBE PRECEDENCE)]": b"\r\n"},
		}


def test_the_header_fields_are_asked_without_marking_the_message_read():
	client = FakeClient()
	out = stream.fetch_headers(client, [7, 8])
	assert out == {7: {"list-unsubscribe": "<https://x.example/out>"}, 8: {}}
	assert (
		client.asked[0][1][0].startswith("BODY.PEEK[HEADER.FIELDS (")
		and "List-Unsubscribe" in client.asked[0][1][0]
	)
	assert stream.fetch_headers(client, []) == {} and len(client.asked) == 1
