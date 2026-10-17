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

A picture of the instance's own files (a signature's logo: Frappe keeps a pasted picture as a file, `/private/files/…`)
is written in too, in the message sent only (`files_inlined`): sent as an address, it reached the recipient as a private
address of another site, and showed nothing (maintenance#1650). The draft and the copy for the document's timeline keep
the address, which the webmail's editor and the desk show.
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
# <img … src="/private/files/logo.png">, or the same address with this site's name in front: the quote kept, the address read
_FILE_IMAGE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])([^"']+)\2""", re.IGNORECASE)
# The pictures a file of the instance may be written in as: the ones every mail client shows (an SVG stays an address)
_FILE_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
# A file of the instance goes in up to this size, a message carries at most this much of them, and at most this many
# different files are looked up for one message
MAX_FILE_IMAGE = 5 << 20
MAX_FILE_IMAGES = 15 << 20
MAX_FILES_LOOKED_UP = 20


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


def files_inlined(html: str | None) -> str:
	"""The HTML with each picture of the instance written in as a `data:` image, which `to_parts` then turns into a part
	of the message: a public file (`/files/…`), or a private one (`/private/files/…`) attached to a signature of the
	person sending (Frappe keeps a signature's pasted logo as a private file of that signature). Anything else is left as
	it was: a private file the person may well read, but which a message they reply to may name (a quoted address must
	not bring the file along), a picture too big, of a type mail clients do not show, missing on the disk, or of another
	site."""
	left = MAX_FILE_IMAGES
	found: dict[str, tuple[str, bytes] | None] = {}

	def swap(match: re.Match) -> str:
		nonlocal left
		path = _local_path(match.group(3))
		if not path:
			return match.group(0)
		if path not in found:
			# At most this many different files of the instance looked up per message: past them, the addresses stay.
			found[path] = _picture(path) if len(found) < MAX_FILES_LOOKED_UP else None
		picture = found[path]
		if not picture or len(picture[1]) > left:
			return match.group(0)
		kind, content = picture
		left -= len(content)
		data = base64.b64encode(content).decode()
		return f"{match.group(1)}{match.group(2)}data:{kind};base64,{data}{match.group(2)}"

	return _FILE_IMAGE.sub(swap, html or "")


def _local_path(address: str) -> str | None:
	"""The path of a file of this instance a picture's address names (`/private/files/logo.png`, from the address alone
	or with this site's name, any `?fid=` dropped), when it is one of the pictures mail clients show; None otherwise."""
	import mimetypes
	from urllib.parse import unquote, urlsplit

	import frappe

	address = address.strip()
	if not address.startswith(("/files/", "/private/files/", "http://", "https://")):
		return None
	try:
		parts = urlsplit(address)
		if parts.netloc and parts.netloc.lower() != urlsplit(frappe.utils.get_url()).netloc.lower():
			return None
	except ValueError:
		# An address Python cannot even read (`http://[x/a.png`, in a quoted message): it stays.
		return None
	path = unquote(parts.path)
	if not path.startswith(("/files/", "/private/files/")):
		return None
	return path if mimetypes.guess_type(path)[0] in _FILE_IMAGE_TYPES else None


def _picture(path: str) -> tuple[str, bytes] | None:
	"""(type, bytes) of the instance's file at `path` when it may go in (`files_inlined`); None otherwise. Whether it is
	private follows its address, as Frappe serves it: a `/private/files/` one only from a signature of the person."""
	import mimetypes

	import frappe

	filters: dict = {"file_url": path, "is_folder": 0}
	if path.startswith("/private/files/"):
		signatures = frappe.get_all("Email Signature", filters={"user": frappe.session.user}, pluck="name")
		if not signatures:
			return None
		# In the query, not after it: one logo pasted by many shares one address, one row each.
		filters |= {"attached_to_doctype": "Email Signature", "attached_to_name": ["in", signatures]}
	name = frappe.db.get_value("File", filters, "name")
	if not name:
		return None
	try:
		content = frappe.get_doc("File", name).get_content()
	except Exception:
		# Its row is there, its bytes are not (a file gone from the disk): the address stays.
		return None
	if isinstance(content, str):
		content = content.encode()
	if not 0 < len(content) <= MAX_FILE_IMAGE:
		return None
	return mimetypes.guess_type(path)[0], content
