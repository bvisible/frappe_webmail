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
	client.select_folder(folder, readonly=True)
	head = client.fetch([uid], [HEADERS]).get(uid, {})
	own, related = thread_ids(head.get(HEADERS_KEY))
	criteria = criteria_for(own, related)
	if criteria is None:
		return []
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
	return places
