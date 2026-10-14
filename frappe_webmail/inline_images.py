# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Images written in a message's text travel as parts of the message (multipart/related), each named by the
Content-ID its `<img>` points to (« cid: »).

The composers put an image pasted, dropped or inserted in the text as a `data:` address. Mail clients drop those,
and the server's own cleaning (bleach, which lets only http, https and mailto through) removed them first: the person
saw the image while writing, the recipient never did. A message read back turns its `cid:` images into `data:` again
(get_email_content), so a draft taken back shows them, and once saved or sent again they leave as parts once more.

The parts carry no file name: a part with one is an attachment (mime_parts.is_attachment), shown under the message
instead of in its text.
"""

import base64
import binascii
import re
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid

# <img … src="data:image/png;base64,…">: the quote kept, the type and the bytes read
_DATA_IMAGE = re.compile(
	r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])data:(image/[a-z0-9.+-]+);base64,([a-z0-9+/=\s]+)\2""",
	re.IGNORECASE,
)

# What the cleaning of a message lets through in an address: the web's and mail's, and its own parts'
SAFE_PROTOCOLS = ["http", "https", "mailto", "cid"]


def to_parts(html: str | None, domain: str) -> tuple[str, list[MIMEImage]]:
	"""The HTML with each `data:` image pointing to a part of its own, and those parts, in their order in the text.

	An image whose bytes are not base64 is left as it was."""
	parts: list[MIMEImage] = []

	def swap(match: re.Match) -> str:
		try:
			data = base64.b64decode(re.sub(r"\s+", "", match.group(4)), validate=True)
		except (binascii.Error, ValueError):
			return match.group(0)
		subtype = match.group(3).lower().split("/", 1)[1]
		cid = make_msgid(domain=domain or "webmail.local")[1:-1]
		part = MIMEImage(data, _subtype=subtype)
		part.add_header("Content-ID", f"<{cid}>")
		part.add_header("Content-Disposition", "inline")
		parts.append(part)
		return f"{match.group(1)}{match.group(2)}cid:{cid}{match.group(2)}"

	return _DATA_IMAGE.sub(swap, html or ""), parts


def body_with(alternative: MIMEMultipart, parts: list[MIMEImage]) -> MIMEMultipart:
	"""The message's body: its text and HTML alone, or with the images the HTML points to (multipart/related)."""
	if not parts:
		return alternative
	related = MIMEMultipart("related")
	related.attach(alternative)
	for part in parts:
		related.attach(part)
	return related
