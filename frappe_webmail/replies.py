# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Who an answer goes to, and where a draft went: rules both screens of the mail (the desk's webmail and the desktop
app) read from the server, written once.

Reply all was a flag the desk's composer never read (it answered the sender alone) and was missing from the desktop
app; a draft saved again and again became as many drafts, because the server never said which UID the last one got.
"""

import re
from email.utils import getaddresses


def addresses(*fields: str | None) -> list[str]:
	"""The bare addresses of header-like fields (« a@b.ch, Name <c@d.ch> »), in order, each once (case ignored)."""
	seen: set[str] = set()
	found: list[str] = []
	for field in fields:
		for _name, address in getaddresses([field or ""]):
			address = (address or "").strip()
			if "@" not in address or address.lower() in seen:
				continue
			seen.add(address.lower())
			found.append(address)
	return found


def reply_recipients(
	own: str | None,
	from_email: str | None,
	reply_to: str | None = None,
	to: str | None = None,
	cc: str | None = None,
	reply_all: bool = False,
) -> dict:
	"""The To and Cc of an answer written from the mailbox `own`.

	- Reply: the message's Reply-To, else its sender.
	- Reply all: everyone else the message went to as well, its To then its Cc — the mailbox itself never, nobody
	  twice.
	- A message the mailbox sent itself (from Sent) is answered to the people it went to, not to oneself.
	"""
	own_key = (own or "").strip().lower()

	def others(found: list[str]) -> list[str]:
		return [a for a in found if a.lower() != own_key]

	sender = addresses(reply_to) or addresses(from_email)
	first = others(sender) or others(addresses(to))
	if not reply_all:
		return {"to": ", ".join(first), "cc": ""}
	taken = {a.lower() for a in first}
	to_list = first + [a for a in others(addresses(to)) if a.lower() not in taken]
	taken.update(a.lower() for a in to_list)
	cc_list = [a for a in others(addresses(cc)) if a.lower() not in taken]
	return {"to": ", ".join(to_list), "cc": ", ".join(cc_list)}


_APPENDUID = re.compile(rb"\[APPENDUID \d+ (\d+)\]", re.IGNORECASE)


def appended_uid(response) -> int | None:
	"""The UID the server gave a message just appended — « [APPENDUID <validity> <uid>] » of servers with UIDPLUS — or
	None (the caller then finds the draft by its Message-ID)."""
	if response is None:
		return None
	if isinstance(response, str):
		response = response.encode()
	match = _APPENDUID.search(bytes(response))
	return int(match.group(1)) if match else None
