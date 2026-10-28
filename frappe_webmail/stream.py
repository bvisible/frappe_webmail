# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The stream of a message: a person, a notification or a newsletter (28.10.2026).

For the tabs of a mailbox (Principal / Notifications / Newsletters, as Gmail and Spark have them): which KIND OF SENDER wrote a
message. Computed on the way, from what a list already holds, and never written anywhere: no keyword on the message, no move, no
copy. Two stages, the cheap one first:

1. the HEADERS, which a sending system leaves and a person does not: `Auto-Submitted`, `X-Auto-Response-Suppress`, `List-Unsubscribe`,
   `Precedence: bulk`, a sender such as noreply@ or newsletter@, a reply that carries `In-Reply-To`. Deterministic and instant. Where
   two signals disagree (a « noreply@ » sender with a `List-Unsubscribe`, which is as often a marketing mailing as a receipt), the headers
   say nothing: the second stage reads the message.
2. the MODEL: the box's `nora-decide` task `mail_stream`, from the sender's name and address, the subject and the first 256 characters
   of the body (what a list shows), exactly as its student was trained on them.

A message that neither stage settles is a PERSON's: the Principal tab never hides mail that nobody was sure about.

Pure functions, no frappe, no network: the model is a callable the caller hands in.
"""

import re

PREVIEW = 256
# The fields the headers stage reads; asked of the server alone (never the whole header).
HEADER_FIELDS = (
	"Auto-Submitted",
	"X-Auto-Response-Suppress",
	"List-Unsubscribe",
	"List-Unsubscribe-Post",
	"List-Id",
	"Precedence",
	"In-Reply-To",
	"References",
	"X-Campaign",
	"X-Campaign-Id",
	"X-Mailchimp-Id",
	"X-Mailer",
)
NOTIFICATION_LOCALS = frozenset(
	"""noreply no-reply no_reply donotreply do-not-reply do_not_reply notification notifications notify alert alerts
	mailer-daemon postmaster bounce bounces automated auto-confirm robot daemon system security""".split()
)
NEWSLETTER_LOCALS = frozenset(
	"""newsletter newsletters news marketing promo promos promotion promotions offers deals digest weekly mailing
	campaign campaigns""".split()
)
BULK = frozenset({"bulk", "list", "junk"})
CAMPAIGN_HEADERS = ("x-campaign", "x-campaign-id", "x-mailchimp-id")


def header_map(raw):
	"""{lower-case name: first value} of headers given as a dict, a JMAP list [{name, value}] or a raw block of text. Values are
	trimmed and unfolded; an absent header is absent, an empty one is an empty string."""
	out = {}
	if isinstance(raw, dict):
		pairs = raw.items()
	elif isinstance(raw, list | tuple):
		pairs = ((h.get("name", ""), h.get("value", "")) for h in raw if isinstance(h, dict))
	else:
		text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
		text = re.sub(r"\r?\n[ \t]+", " ", text)
		pairs = (line.split(":", 1) for line in re.split(r"\r?\n", text) if ":" in line)
	for name, value in pairs:
		name = str(name).strip().lower()
		if name and name not in out:
			out[name] = " ".join(str(value).split())
	return out


def local_part(address):
	"""The part of an address before the @, lower case, without a `+tag`."""
	return (
		str(address or "").rsplit("@", 1)[0].split("+", 1)[0].strip().lower()
		if "@" in str(address or "")
		else ""
	)


def of_headers(headers, address=""):
	"""{stream, why}: `stream` is person, notification or newsletter when the headers settle it, else None; `why` names the signal."""
	h = header_map(headers)
	local = local_part(address)
	auto = h.get("auto-submitted", "").lower()
	automated = (bool(auto) and auto != "no") or "x-auto-response-suppress" in h
	bulk_mark = (
		"list-unsubscribe" in h
		or h.get("precedence", "").lower() in BULK
		or any(name in h for name in CAMPAIGN_HEADERS)
	)
	notification_sender = local in NOTIFICATION_LOCALS
	if automated and not bulk_mark:
		return {
			"stream": "notification",
			"why": "Auto-Submitted" if auto and auto != "no" else "X-Auto-Response-Suppress",
		}
	if automated and bulk_mark:
		return {"stream": None, "why": "automated and bulk at once"}
	if notification_sender and bulk_mark:
		return {"stream": None, "why": f"{local}@ with an unsubscribe link"}
	if notification_sender:
		return {"stream": "notification", "why": f"sender {local}@"}
	if bulk_mark:
		if "list-unsubscribe" in h:
			why = "List-Unsubscribe"
		elif h.get("precedence", "").lower() in BULK:
			why = "Precedence: " + h["precedence"].lower()
		else:
			why = "campaign header"
		return {"stream": "newsletter", "why": why}
	if local in NEWSLETTER_LOCALS:
		return {"stream": "newsletter", "why": f"sender {local}@"}
	if ("in-reply-to" in h or "references" in h) and "list-id" not in h:
		return {"stream": "person", "why": "a reply in a thread"}
	return {"stream": None, "why": None}


def preview_of(body):
	"""The first words of a body as a list shows them: lines folded, cut at a word boundary within PREVIEW characters."""
	text = " ".join(str(body or "").split())
	return text if len(text) <= PREVIEW else text[:PREVIEW].rsplit(" ", 1)[0]


def model_text(name, address, subject, preview):
	"""The text the `mail_stream` student was trained on: the sender, the subject and the first words, nothing else."""
	sender = f"{name} <{address}>" if name else str(address or "")
	return f"From: {sender}\nSubject: {subject or ''}\n\n{preview_of(preview)}"


def decide(message, ask_model=None):
	"""{stream, source, why, probability}: the stream of one message.

	`message`: name, address, subject, preview, headers (any form `header_map` takes, or None when they were not read).
	`ask_model(text)`: the answer of nora-decide as a dict (label, probability, abstain, source), or None; not called when the headers settle it.
	`source` is `headers`, `model`, or `default` (nothing settled it: a person's)."""
	first = of_headers(message.get("headers") or {}, message.get("address", ""))
	if first["stream"]:
		return {"stream": first["stream"], "source": "headers", "why": first["why"], "probability": None}
	answer = (
		ask_model(
			model_text(
				message.get("name"), message.get("address"), message.get("subject"), message.get("preview")
			)
		)
		if ask_model
		else None
	)
	if (
		answer
		and not answer.get("abstain")
		and answer.get("label") in ("person", "notification", "newsletter")
	):
		return {
			"stream": answer["label"],
			"source": "model",
			"why": answer.get("source"),
			"probability": answer.get("probability"),
		}
	return {
		"stream": "person",
		"source": "default",
		"why": first["why"] or ("the model was not sure" if answer else "the model was not asked"),
		"probability": answer.get("probability") if answer else None,
	}


def fetch_headers(client, uids):
	"""{uid: header map} of the fields the headers stage reads, for messages of the folder in view, without marking them read."""
	if not uids:
		return {}
	item = "BODY.PEEK[HEADER.FIELDS (" + " ".join(HEADER_FIELDS) + ")]"
	out = {}
	for uid, data in client.fetch(list(uids), [item]).items():
		for key, value in data.items():
			if isinstance(key, bytes) and key.upper().startswith(b"BODY[HEADER"):
				out[uid] = header_map(value)
				break
	return out
