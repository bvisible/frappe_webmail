# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The one rule for what an attachment of an e-mail is, and what its id is.

The list of a message's attachments (`webmail_api.get_email_content`), its download (`webmail_api.get_attachment`) and
every action on an attachment (`attachments.py`) find them with this rule. It used to be written twice, which is how an
attachment shown in the list could not be downloaded; a third copy for the new actions would have made it three.

No import from the rest of the app here: both `webmail_api` and `attachments` import this module.
"""

from collections.abc import Iterator
from email.message import Message
from typing import NamedTuple

# Parts with a file name that are still not attachments: the bodies and their containers.
NOT_ATTACHMENTS = frozenset(("text/plain", "text/html", "multipart/alternative", "multipart/mixed"))


class AttachmentPart(NamedTuple):
	# The id the screens use: the part's Content-ID, else its rank among the attachments.
	id: str
	# Its rank among the attachments (0, 1, …), which also names an attachment that has no file name.
	rank: int
	part: Message


def is_attachment(part: Message) -> bool:
	"""An explicit `Content-Disposition: attachment`, or any part with a file name that is not a body or a container."""
	disposition = str(part.get("Content-Disposition") or "").lower()
	return "attachment" in disposition or bool(
		part.get_filename() and part.get_content_type() not in NOT_ATTACHMENTS
	)


def iter_attachments(msg: Message) -> Iterator[AttachmentPart]:
	"""The attachments of `msg`, in the order of the message."""
	rank = 0
	for part in msg.walk():
		if not is_attachment(part):
			continue
		content_id = str(part.get("Content-ID") or "").strip("<>")
		yield AttachmentPart(content_id or str(rank), rank, part)
		rank += 1
