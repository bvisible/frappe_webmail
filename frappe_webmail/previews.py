# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The line of text under a message's subject in the list (canvas « Neodesk », board 7).

The list already fetches each message's BODYSTRUCTURE: from it, the first text part (plain before HTML, never an
attachment) and its encoding; then the first bytes of that part only, one FETCH for each part path of the page
(`BODY.PEEK[1]<0.800>`, `BODY.PEEK[1.1]<0.800>`), so a page of fifty messages costs a few small requests. The bytes are
cut anywhere: the decoders below take a cut base64 or quoted-printable body, and a cut multibyte character.
"""

import base64
import html
import quopri
import re

PREVIEW_BYTES = 800
PREVIEW_LENGTH = 160


def _lower(value):
	if isinstance(value, bytes):
		return value.decode("ascii", errors="ignore").lower()
	return (value or "").lower() if isinstance(value, str) else ""


def _params(part):
	"""A body part's parameters (charset, name…) as a dict of lowercase names."""
	params = part[2] if len(part) > 2 else None
	if not isinstance(params, tuple | list):
		return {}
	values = list(params)
	return {_lower(values[i]): _lower(values[i + 1]) for i in range(0, len(values) - 1, 2)}


def _is_attachment(part):
	"""A disposition « attachment » anywhere in the part's extension data, or a file name."""
	for value in part[7:]:
		if isinstance(value, tuple | list) and value and _lower(value[0]) == "attachment":
			return True
	return "name" in _params(part)


def text_part(structure, prefix=""):
	"""The first text part of a message to take its preview from: (path, subtype, encoding, charset), or None.

	A message of one part is part « 1 »; the parts of a multipart are numbered from 1, a nested one « 2.1 ». Plain text
	wins over HTML anywhere in the message: a multipart/alternative carries both.
	"""
	if not isinstance(structure, tuple | list) or len(structure) < 2:
		return None
	found = {}

	def walk(part, path):
		if isinstance(part[0], list | tuple) and not isinstance(part[0], bytes | str):
			for index, child in enumerate(part[0], 1):
				if isinstance(child, tuple | list) and len(child) >= 2:
					walk(child, f"{path}.{index}" if path else str(index))
			return
		if _lower(part[0]) != "text" or _is_attachment(part):
			return
		subtype = _lower(part[1])
		if subtype in ("plain", "html") and subtype not in found:
			encoding = _lower(part[5]) if len(part) > 5 else ""
			found[subtype] = (path or "1", subtype, encoding, _params(part).get("charset") or "utf-8")

	walk(structure, prefix)
	return found.get("plain") or found.get("html")


def _decode_transfer(raw, encoding):
	if encoding == "base64":
		data = re.sub(rb"[^A-Za-z0-9+/=]", b"", raw)
		data = data[: len(data) - len(data) % 4]
		try:
			return base64.b64decode(data)
		except ValueError:
			return b""
	if encoding == "quoted-printable":
		# A cut escape at the end (« =C », « = ») would read as text
		return quopri.decodestring(re.sub(rb"=[0-9A-Fa-f]?$", b"", raw.rstrip(b"\r\n")))
	return raw


def _decode_charset(data, charset):
	try:
		text = data.decode(charset or "utf-8", errors="replace")
	except LookupError:
		text = data.decode("utf-8", errors="replace")
	# A multibyte character cut at the end
	return text.rstrip("�")


def _html_to_text(text):
	text = re.sub(r"(?is)<(style|script|head)\b.*?(</\1>|$)", " ", text)
	# A block ends a line (cells too, or « A</td><td>B » would read « AB »); an inline tag is only removed
	text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|td|th|h[1-6]|table|blockquote)\s*>", "\n", text)
	text = re.sub(r"(?s)<[^>]*>?", "", text)
	return html.unescape(text)


def preview_text(raw, subtype, encoding, charset, length=PREVIEW_LENGTH):
	"""The first words of a part's text, on one line, at most `length` characters (an ellipsis when cut)."""
	text = _decode_charset(_decode_transfer(raw or b"", encoding), charset)
	if subtype == "html":
		text = _html_to_text(text)
	# Quoted lines of a reply say what the other wrote: not this message's first words
	lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
	text = re.sub(r"\s+", " ", " ".join(lines)).strip()
	if len(text) > length:
		text = text[:length].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
	return text


def fetch_previews(client, structures, size=PREVIEW_BYTES):
	"""{uid: preview} for the messages whose BODYSTRUCTURE is given; one FETCH for each text part path."""
	by_path = {}
	parts = {}
	for uid, structure in structures.items():
		part = text_part(structure)
		if part:
			parts[uid] = part
			by_path.setdefault(part[0], []).append(uid)
	previews = {}
	for path, uids in by_path.items():
		data = client.fetch(uids, [f"BODY.PEEK[{path}]<0.{size}>"])
		key = f"BODY[{path}]<0>".encode()
		for uid in uids:
			raw = (data.get(uid) or {}).get(key)
			if raw:
				_path, subtype, encoding, charset = parts[uid]
				previews[uid] = preview_text(raw, subtype, encoding, charset)
	return previews
