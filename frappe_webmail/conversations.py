# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""A message's conversation: the other messages it answers or that answer it, found by their Message-IDs.

Both screens list one message per line (Jérémy's choice, 14.10.2026) and unfold the conversation while a message is
read: « 2 messages plus anciens dans cette conversation ». The thread is what the headers say (References, In-Reply-To,
Message-ID), looked for in the message's folder, the inbox and the sent: an answer of the person's own sits in « Envoyés ».
"""

import email
from collections.abc import Iterable

# The sent folder by name, where the server marks none \\Sent (the names _copy_to_sent_folder knows)
SENT_NAMES = ("Sent", "Sent Items", "Sent Mail", "INBOX.Sent", "Envoyés")

# The thread's headers, read without marking the message read
HEADERS = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES)]"
HEADERS_KEY = b"BODY[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES)]"

# The newest ancestors a search asks for: a long thread keeps its last references
MAX_REFERENCES = 10

# The References an answer carries at most: the first (the conversation's start) and the newest
MAX_CHAIN = 20


def _ids(value: str | None) -> list[str]:
	"""The `<…>` Message-IDs of a header, in order."""
	found: list[str] = []
	for part in (value or "").replace("\n", " ").split():
		part = part.strip()
		if part.startswith("<") and part.endswith(">") and part not in found:
			found.append(part)
	return found


def thread_ids(raw_headers: bytes | str | None) -> tuple[str | None, list[str]]:
	"""(the message's own Message-ID, the Message-IDs it answers — its References then its In-Reply-To, newest last)."""
	if not raw_headers:
		return None, []
	if isinstance(raw_headers, bytes):
		raw_headers = raw_headers.decode("utf-8", errors="replace")
	headers = email.message_from_string(raw_headers)
	own = (_ids(headers.get("Message-ID")) or [None])[0]
	related: list[str] = []
	for value in _ids(headers.get("References")) + _ids(headers.get("In-Reply-To")):
		if value != own and value not in related:
			related.append(value)
	return own, related[-MAX_REFERENCES:]


def criteria_for(own: str | None, related: Iterable[str]) -> list | None:
	"""The IMAP search for a conversation: the messages it answers (by their Message-ID) and those answering it (whose
	References or In-Reply-To name it), as nested ORs; None when nothing ties the message to another."""
	terms = [["HEADER", "Message-ID", value] for value in related]
	if own:
		terms += [["HEADER", "References", own], ["HEADER", "In-Reply-To", own]]
	if not terms:
		return None
	criteria = terms[-1]
	for term in reversed(terms[:-1]):
		criteria = ["OR", term, criteria]
	return criteria


def sent_folder(folders: Iterable[tuple]) -> str | None:
	"""The sent folder of `list_folders()`: the one flagged \\Sent, else one of the usual names."""
	by_name = None
	for flags, _delimiter, name in folders:
		if b"\\Sent" in (flags or ()):
			return name
		if name in SENT_NAMES:
			by_name = name
	return by_name


def conversation_places(client, folder: str, uid: int, inbox: str = "INBOX") -> list[tuple[str, int]]:
	"""(folder, uid) of the other messages of the conversation of `uid` in `folder`: in that folder, the inbox and the
	sent folder, the message itself left out. Read only (EXAMINE, BODY.PEEK)."""
	return conversation_of(client, folder, uid, inbox)[1]


def conversation_of(
	client, folder: str, uid: int, inbox: str = "INBOX"
) -> tuple[str | None, list[tuple[str, int]]]:
	"""(the message's own Message-ID, the places of the other messages of its conversation): conversation_places."""
	client.select_folder(folder, readonly=True)
	head = client.fetch([uid], [HEADERS]).get(uid, {})
	own, related = thread_ids(head.get(HEADERS_KEY))
	criteria = criteria_for(own, related)
	if criteria is None:
		return own, []
	places: list[tuple[str, int]] = []
	for each in dict.fromkeys([folder, inbox, sent_folder(client.list_folders())]):
		if not each:
			continue
		try:
			client.select_folder(each, readonly=True)
			found = client.search(criteria)
		except Exception:
			# A folder the server refuses (gone, no right): the others still tell the conversation
			continue
		places += [
			(each, int(found_uid)) for found_uid in found if (each, int(found_uid)) != (folder, int(uid))
		]
	return own, places


def message_id_of(envelope) -> str | None:
	"""The Message-ID of a message's ENVELOPE, `<…>`, or None."""
	value = getattr(envelope, "message_id", None)
	if isinstance(value, bytes):
		value = value.decode("utf-8", errors="replace")
	return (_ids(value) or [None])[0]


def one_per_message(
	found: Iterable[tuple[str | None, dict]], own: str | None, folder: str, inbox: str = "INBOX"
):
	"""The rows of a conversation, each message once. A message sent to oneself, or copied to one's own mailbox, sits
	in the inbox and in the sent under one Message-ID: the copy in the folder read is kept, else the inbox's, else the
	first found. A copy of the message read is not another message of its conversation."""
	rank = {folder: 0, inbox: 1}
	kept: dict = {}
	for message_id, row in found:
		if message_id and message_id == own:
			continue
		key = message_id or (row["folder"], row["uid"])
		if key not in kept or rank.get(row["folder"], 2) < rank.get(kept[key]["folder"], 2):
			kept[key] = row
	return list(kept.values())


def references_for(client, folder: str, uid: int, answered: str | None) -> str | None:
	"""The References of an answer (RFC 5322, 3.6.4): those of the message answered, then its own Message-ID, so that
	the whole conversation is found from any of its messages (an answer used to name its parent only, and the older
	messages fell out of the conversation). The message answered alone when it cannot be read. Read only."""
	parent = None
	try:
		client.select_folder(folder, readonly=True)
		raw = client.fetch([int(uid)], [HEADERS]).get(int(uid), {}).get(HEADERS_KEY)
		if raw:
			parent = email.message_from_string(
				raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
			)
	except Exception:
		parent = None
	last = _ids(answered)[:1]
	chain: list[str] = []
	if parent is not None:
		chain = _ids(parent.get("References")) or _ids(parent.get("In-Reply-To"))[:1]
		last = last or _ids(parent.get("Message-ID"))[:1]
	chain = [value for value in chain if value not in last] + last
	if len(chain) > MAX_CHAIN:
		chain = chain[:1] + chain[-(MAX_CHAIN - 1) :]
	return " ".join(chain) or None
