# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
NeoMail's actions on an attachment, in the desk's page /app/neomail, as the old webmail's attachment menu has them
(attachments.py): save it in the Drive, in a folder the person chooses (`save_to_drive`); send a PDF or a picture to
the scanned documents (`to_scans`); or save it in the Drive and open it in the Drive's editor of its type, NeoDoc,
NeoGrille, NeoPrés or NeoPDF (`save_to_drive` with `edit`, then the page opens the copy).

« Ouvrir dans NeoGrille » (`open_in_editor`, the handover's "open", 18.11.2026): NeoMail's first action on a file one of
the Drive's editors opens, the formats it imports included (a .xls, a .csv, a .odt…, which the Drive saves as a new .xlsx
or .docx: suite's `opened_extensions`), in one click and with no folder to pick: the copy goes into the person's own Drive,
in « Pièces jointes » / « <the message's date> <its subject> », private to them as all of their Drive is; the same
attachment opened again opens the same copy, edits and all (`_copy_key`, a default of the person's).

NeoMail offers what the handover's `attachments` lists (`offered`: "drive", "scan", "edit", "open") and names the attachment to
the page (`mailcraft:attachment`): the mailbox, the message's JMAP id, and what NeoMail knows of the file, its rank
among NeoMail's attachments and how many it sees, its name, size, type and Content-ID. None of it is trusted. The
server reads the message from its server itself, under the webmail's rule for the mailbox (owned or shared with the
person: get_account; its place checked by mailcraft_jmap.message_place), counts its attachments as NeoMail counts them
(`candidates`: the pictures of the text among them, an attached e-mail one file, a type read as NeoMail reads it,
which mime_parts does not), and finds the attachment by what identifies it (`find`): its Content-ID first, then its
name, size and type, NeoMail's rank only telling apart files that are otherwise alike, and only when NeoMail sees as
many as the server counts. One it cannot tell apart is refused, never guessed.

The message's size is asked of its server before a byte of it is read (MAX_SOURCE, as for a share), and the file's
name is cleaned as a share cleans it (neomail_share._file_name) for the Drive and for the scanned documents alike. The
file is saved by the old webmail's doors (drive.deposit, scans.create), with the person's own rights. Desk people
only, on the page's session with its CSRF token, as the page's other calls, or from Neodesk's NeoMail window with the
person's own OAuth bearer token (`_gate`): no facade token reaches here; so many calls a minute for each person
(`per_person`). Neodesk's window draws its own folder picker (the webmail's `attachments.get_drive_folders` and
`create_drive_folder`, which its bearer token calls as the phone does) and opens an edited file in its own editor
window, in place, from the Drive file `save_to_drive` answers.
"""

import functools
import json
import mimetypes
import re
import unicodedata
from email import message_from_bytes, policy
from email.errors import HeaderParseError
from email.header import decode_header
from email.message import Message
from typing import NamedTuple

import frappe
from frappe import _
from frappe.utils import cint

# The largest message read whole from its server, and a file's name as it is saved: as for a share.
from frappe_webmail.neomail_share import MAX_SOURCE, _file_name

# What is taken of NeoMail's description of the file: so many characters of a text at most.
MAX_HINT = 1024
# The longest name of a Drive folder taken from the page.
MAX_FOLDER = 140
# So many calls of each method a minute, for each person (`per_person`).
CALLS_A_MINUTE = 20
# How deep and how many parts of a message are looked through, as NeoMail reads one (crates/mime/src/parse.rs).
MAX_DEPTH = 20
MAX_PARTS = 1000
# What the scanned documents take: a PDF or a picture, by the name's extension, else by its type when the name has
# none. Never a drawing (SVG), which is text a browser runs. The same rule as NeoMail's (host_attachments.rs).
SCAN_EXTENSIONS = frozenset(
	("pdf", "png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif")
)
SCAN_TYPES = frozenset(
	(
		"application/pdf",
		"image/png",
		"image/jpeg",
		"image/gif",
		"image/bmp",
		"image/tiff",
		"image/webp",
		"image/heic",
		"image/heif",
	)
)
# The Drive's editors, by the extension they open and write back: the editor's key in suite (EDITORS of
# suite/drive/wopi/craft.py) and its name, which is a product's and is not translated.
EDITORS = {
	"docx": ("word", "NeoDoc"),
	"xlsx": ("sheet", "NeoGrille"),
	"pptx": ("deck", "NeoPrés"),
	"pdf": ("pdf", "NeoPDF"),
}
# The products by the editor's key in suite, for a format an editor imports (suite's `opened_extensions`).
PRODUCTS = {"word": "NeoDoc", "sheet": "NeoGrille", "deck": "NeoPrés", "pdf": "NeoPDF"}
# The longest name of the folder of a message's attachments (« 2026-11-18 Liste des clients »).
MAX_MESSAGE_FOLDER = 100


class Wanted(NamedTuple):
	"""What NeoMail says of the file: hints only."""

	index: int | None
	name: str
	size: int | None
	mime: str
	cid: str
	# How many attachments NeoMail sees in the message: its rank is taken only when the server counts as many.
	count: int | None = None


class Candidate(NamedTuple):
	"""A part of the message that NeoMail lists among its attachments."""

	# Its rank among them, counted as NeoMail counts (`candidates`).
	rank: int
	part: Message
	# Its file name as the message gives it (decoded), or None when it gives none.
	name: str | None
	# The name as two readings of it are compared (`_key`).
	key: str | None
	mime: str
	cid: str
	size: int


class _Ambiguous(Exception):
	"""Several parts fit what NeoMail said, and nothing tells them apart."""


def per_person(fn):
	"""CALLS_A_MINUTE calls of `fn` a minute for each person, over HTTP. Frappe's rate_limit counts by address (its `key`
	is a field of the request, which the caller writes), and a whole office behind one address would share one count."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		if getattr(frappe.local, "request", None) is not None:
			key = _count_key(fn.__name__)
			# Counted first, then given its minute: the first call of a minute, or a count left without one (a
			# reading then a write would have made one again without its expiry, and kept the person out for good)
			calls = frappe.cache.incrby(key, 1)
			if calls == 1 or frappe.cache.ttl(key) == -1:
				frappe.cache.expire(key, 60)
			if calls > CALLS_A_MINUTE:
				frappe.throw(
					_("You hit the rate limit because of too many requests. Please try after sometime."),
					frappe.RateLimitExceededError,
				)
		return fn(*args, **kwargs)

	return wrapper


def _count_key(method):
	"""Where `per_person` counts the session's person's calls of `method`."""
	return frappe.cache.make_key(f"neomail-attachments:{method}:{frappe.session.user}")


def _gate():
	"""The calls of the desk's page, as a share's (neomail_share._gate, without Synk): where the page is offered, on
	the desk's cookie with the session's CSRF token, for one of the desk's people. Or those of Neodesk's NeoMail window,
	whose shell calls with the person's own OAuth bearer token, as hand_over takes it (mailcraft_jmap.neodesk_request_only:
	alive, of one of the desk's people, where NeoMail is on), and never with anything else that signs a request in (an
	API key, a password). The rights are the same either way, the person's: the mailbox (get_account), the Drive folder
	(drive.folder_entry), the scanned documents (scans.can_create)."""
	from frappe_webmail import mailcraft_jmap as jmap
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk
	from frappe_webmail.www import neomail

	try:
		signed = frappe.get_request_header("Authorization")
	except RuntimeError:
		# No request: a console, a test
		signed = None
	if signed:
		# Neodesk: its token, never anything else that signs a request in
		jmap.neodesk_request_only()
		return
	if not desk.in_desk():
		raise frappe.PageDoesNotExistError
	jmap.page_request_only()
	neomail.desk_people_only()
	jmap.csrf_token_required()


def installed_editors():
	"""The extensions whose editor the Drive has a build of here ({"docx", "pdf", …}): none without the Drive, or with
	a suite that has no Craft editors yet."""
	from frappe_webmail import drive

	if not drive.available():
		return set()
	try:
		from suite.drive.wopi.craft import get_installed_editors
	except ImportError:
		return set()
	have = get_installed_editors() or {}
	return {extension for extension, (editor, _product) in EDITORS.items() if editor in have}


def openable():
	"""The extensions this site's Drive opens in one of its editors, by the editor's key ({"xlsx": "sheet", "csv":
	"sheet", "odt": "word", …}): the formats they write back and those they import (suite's `opened_extensions`, a
	suite that has it), else the formats they write back only (`installed_editors`)."""
	from frappe_webmail import drive

	if not drive.available():
		return {}
	try:
		from suite.drive.wopi.craft import opened_extensions
	except ImportError:
		return {extension: EDITORS[extension][0] for extension in installed_editors()}
	return {
		str(extension).lower(): key
		for extension, key in (opened_extensions() or {}).items()
		if key in PRODUCTS and str(extension).isalnum()
	}


def offered():
	"""What NeoMail offers on an attachment to the session's person, the handover's `attachments`: the old webmail's
	menu (attachments.get_attachment_actions) says "drive" where the Drive is installed and "scan" where they may create
	a scanned document; "edit" (a folder to pick first) and "open" (one click, `open_in_editor`) where the Drive has an
	editor too."""
	from frappe_webmail import attachments

	keys = {action.get("key") for action in attachments.get_attachment_actions()}
	out = []
	if "save_to_drive" in keys:
		out.append("drive")
	if "document_scan" in keys:
		out.append("scan")
	if "drive" in out and installed_editors():
		out.append("edit")
		out.append("open")
	return out


def extension(name):
	"""The extension of a file name, in lower case; empty without one."""
	name = str(name or "")
	return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def scannable(name, mime):
	"""Whether the scanned documents take the file `name` of type `mime`: a PDF or a picture (SCAN_EXTENSIONS), by its
	extension, else by its type when it has none."""
	found = extension(name)
	if found:
		return found in SCAN_EXTENSIONS
	return str(mime or "").strip().lower() in SCAN_TYPES


def editor(name):
	"""The editor that opens the file `name` in the Drive: (extension, product name), or None."""
	found = extension(name)
	return (found, EDITORS[found][1]) if found in EDITORS else None


def _cid(value):
	return str(value or "").strip().strip("<>").strip()


def _key(name):
	"""A file name as two readings of it are compared: cleaned as it is saved, its accents composed, its case folded;
	None without a name."""
	name = str(name or "")
	if not name.strip():
		return None
	return unicodedata.normalize("NFC", _file_name(name)).casefold()


def _wanted(attachment):
	"""NeoMail's description of the file (`{index, name, size, mime, cid}`, an object or its JSON), each part taken
	only when it is of its kind and within its length."""
	given = attachment
	if isinstance(given, str):
		try:
			given = json.loads(given)
		except ValueError:
			given = None
	if not isinstance(given, dict):
		frappe.throw(_("This attachment cannot be found: open the message again and try again."))

	def text(key):
		value = given.get(key)
		return value[:MAX_HINT] if isinstance(value, str) else ""

	def number(key):
		value = given.get(key)
		if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**53:
			return None
		return value

	return Wanted(
		number("index"),
		text("name"),
		number("size"),
		text("mime").strip().lower(),
		_cid(text("cid")),
		number("count"),
	)


def _declared(part):
	"""The type the part declares, as NeoMail reads it (crates/mime/src/parse.rs, header.rs `parse_params`): the first
	word of its Content-Type, before any `;`, space or comment, in lower case, when it is `type/subtype`; else None.
	Python keeps a comment in the type (« text/plain (footer) »), and gives the parts of a digest that declare nothing
	the type message/rfc822: NeoMail does neither, and counting otherwise would shift the ranks."""
	value = str(part.get("Content-Type") or "").split(";", 1)[0].strip()
	word = re.split(r"[\s(]", value, maxsplit=1)[0].lower() if value else ""
	kind, slash, subtype = word.partition("/")
	return word if kind and slash and subtype and "/" not in subtype else None


def _name_of(part):
	"""The part's file name as NeoMail reads it, or None. The default policy decodes RFC 2231 and RFC 2047 and reads a
	name written in UTF-8 as it is, but is stricter than NeoMail with a name written against the rules: unquoted with a
	space (`filename=Scan 01.pdf`, read « Scan »), or an encoded word unquoted (`filename==?UTF-8?B?…?=`, read as none).
	Then the lenient reading is taken (`_lenient_name`): when the strict one gives nothing, or less of the name."""
	strict = str(part.get_filename() or "")
	lenient = _lenient_name(part)
	if not strict or len(strict) < len(lenient):
		return lenient or None
	return strict


# A line break before a space or a tab: a header a mailer folded over several lines (RFC 5322 §2.2.3).
_FOLDED = re.compile(r"\r?\n(?=[ \t])")


def _lenient_name(part):
	"""The part's file name read as compat32 reads it (a parameter's value up to the next `;`), from its headers' bytes
	decoded as NeoMail decodes them (UTF-8, else Latin-1), then its encoded words (RFC 2047); empty without one."""
	# A message of the compat32 policy, Message's own, given the headers as text: compat32 would read the surrogates
	# of a header written in 8 bits as replacement characters
	headers = Message()
	for key, value in part.raw_items():
		if key.lower() in ("content-disposition", "content-type"):
			# One line, as before the mailer folded it (RFC 5322): compat32 keeps the break inside a long quoted name.
			headers[key] = _FOLDED.sub("", _text_of(str(value)))
	return _decoded_words(str(headers.get_filename() or "")).strip()


def _text_of(value):
	"""A header's value with the bytes written in 8 bits (surrogates of them, as the parser keeps them) decoded as
	NeoMail decodes them: UTF-8, else Latin-1."""
	octets = value.encode("utf-8", "surrogateescape")
	try:
		return octets.decode("utf-8")
	except UnicodeDecodeError:
		return octets.decode("latin-1")


def _decoded_words(text):
	"""`text` with its encoded words (RFC 2047) decoded; a word that cannot be is kept as it is written."""
	try:
		pieces = decode_header(text)
	except (HeaderParseError, ValueError):
		return text
	out = []
	for piece, charset in pieces:
		if isinstance(piece, str):
			out.append(piece)
			continue
		try:
			out.append(piece.decode(charset or "utf-8", errors="replace"))
		except LookupError:
			out.append(piece.decode("utf-8", errors="replace"))
	return "".join(out)


def candidates(message):
	"""The parts of `message` NeoMail lists among its attachments, in its order (crates/mime/src/parse.rs, `Walk`): every
	leaf with `Content-Disposition: attachment` or a file name, and every other leaf that is neither the text of the
	message nor another rendering of it; an attached e-mail is one, not opened. Each part's type is read as NeoMail reads
	it (`_declared`; a part that declares none is plain text), and its name as NeoMail reads it (`_name_of`)."""
	from frappe_webmail.webmail_api import attachment_bytes

	found = []
	seen = 0

	def walk(part, parent, depth):
		nonlocal seen
		if seen >= MAX_PARTS:
			return
		seen += 1
		declared = _declared(part)
		# RFC 2045: a part that does not say what it is, is plain text.
		media = declared or "text/plain"
		if media.startswith("multipart/"):
			if depth >= MAX_DEPTH or not part.is_multipart():
				return
			kind = {"multipart/alternative": "alternative", "multipart/related": "related"}.get(
				media, "other"
			)
			for child in part.get_payload():
				walk(child, kind, depth + 1)
			return
		disposition = (part.get_content_disposition() or "").lower()
		name = _name_of(part)
		attached = disposition == "attachment" or bool(name)
		if not attached and media in ("text/plain", "text/html"):
			return
		# Other renderings of the text (AMP, enriched…) are not files; an invitation is.
		if (
			not attached
			and parent == "alternative"
			and media.startswith("text/")
			and media != "text/calendar"
		):
			return
		try:
			size = len(attachment_bytes(part))
		except (ValueError, TypeError, LookupError):
			# Bytes that cannot be decoded: a size no description has
			size = -1
		# Its type as NeoMail gives it: the declared one, else the one its name says
		mime = declared or (name and mimetypes.guess_type(name)[0]) or "application/octet-stream"
		found.append(Candidate(len(found), part, name, _key(name), mime, _cid(part.get("Content-ID")), size))

	walk(message, None, 0)
	return found


def _pick(found, tests, index):
	"""The one candidate the first test that holds for any singles out. Several alike are told apart by the tests
	after it, then by NeoMail's rank (`index`); _Ambiguous when nothing does. None when no test holds for any."""
	for position, test in enumerate(tests):
		matching = [c for c in found if test(c)]
		if not matching:
			continue
		if len(matching) == 1:
			return matching[0]
		narrowed = _pick(matching, tests[position + 1 :], index)
		if narrowed is not None:
			return narrowed
		ranked = [c for c in matching if index is not None and c.rank == index]
		if len(ranked) == 1:
			return ranked[0]
		raise _Ambiguous
	return None


def find(message, wanted):
	"""The part of `message` NeoMail named by `wanted`: by its Content-ID first, then by its name, size and type, then
	by what of them agrees (NeoMail and Python may read a name differently), its rank only telling apart parts that are
	otherwise alike, and only when NeoMail sees as many attachments as the server counts (`wanted.count`: NeoMail may
	have one less, removed on this computer, and then its ranks are not the server's). Refused when none fits, or when
	several do and nothing tells them apart."""
	parts = candidates(message)
	index = wanted.index if wanted.count is not None and wanted.count == len(parts) else None
	key = _key(wanted.name)
	tests = []
	if wanted.cid:
		tests.append(lambda c: c.cid == wanted.cid)
	if key is not None:
		tests.append(lambda c: c.key == key and c.size == wanted.size and c.mime == wanted.mime)
		tests.append(lambda c: c.key == key and c.size == wanted.size)
	if wanted.size is not None:
		tests.append(lambda c: c.size == wanted.size and c.mime == wanted.mime)
	if key is not None:
		tests.append(lambda c: c.key == key and c.mime == wanted.mime)
		tests.append(lambda c: c.key == key)
	# A part the message names nothing (an attached e-mail, a picture): NeoMail calls it after its type.
	if wanted.mime:
		tests.append(lambda c: c.name is None and c.mime == wanted.mime)
	try:
		found = _pick(parts, tests, index)
	except _Ambiguous:
		frappe.throw(
			_(
				"Several attachments of this message look alike, and it cannot be told which one you chose: save it with Save As instead."
			)
		)
	if found is None:
		frappe.throw(_("This attachment cannot be found: open the message again and try again."))
	return found


def _unnamed(found):
	"""The name of an attachment the message gives none: « attachment » with its type's extension (an attached
	e-mail's .eml, a report's .txt)."""
	if found.mime in ("message/rfc822", "message/global"):
		return "attachment.eml"
	if found.mime.startswith("message/"):
		return "attachment.txt"
	return "attachment" + (mimetypes.guess_extension(found.mime) or "")


def _source(mailbox, folder, validity, uid):
	"""The raw source of the message, its size asked of its server first: one over MAX_SOURCE is refused before a byte
	of it is read. The folder must still have the UIDVALIDITY the id carries."""
	from frappe_webmail import mailcraft_jmap as jmap
	from frappe_webmail import webmail_api as webmail

	gone = _("This message is no longer in its folder: refresh the list and try again.")
	too_large = _("This message is larger than {0} MB: save the attachment with Save As instead.").format(
		MAX_SOURCE // (1024 * 1024)
	)
	with webmail.imap_session(mailbox) as client:
		if jmap._select(client, folder) != validity:
			frappe.throw(gone)
		size = ((client.fetch([uid], ["RFC822.SIZE"]) or {}).get(uid) or {}).get(b"RFC822.SIZE")
		if size is None:
			frappe.throw(gone)
		if cint(size) > MAX_SOURCE:
			frappe.throw(too_large)
		raw = ((client.fetch([uid], ["BODY.PEEK[]"]) or {}).get(uid) or {}).get(b"BODY[]")
	if not raw:
		frappe.throw(gone)
	# A server that said less than it gave
	if len(raw) > MAX_SOURCE:
		frappe.throw(too_large)
	return raw


def read(account, email, attachment):
	"""(name, type, bytes) of the attachment NeoMail names: of a mailbox of the person's own or shared with them
	(get_account, which answers another's as one that does not exist), in the message whose JMAP id is `email`
	(mailcraft_jmap.message_place), found by `find`. The name is cleaned as it is saved (neomail_share._file_name)."""
	name, mime, data, _message = _read(account, email, attachment)
	return name, mime, data


def _read(account, email, attachment):
	"""`read`, and the message the attachment was found in."""
	from frappe_webmail import mailcraft_jmap as jmap
	from frappe_webmail import webmail_api as webmail
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

	wanted = _wanted(attachment)
	mailbox = webmail.get_account(desk._mailbox_name(account))
	folder, uid = jmap.message_place(mailbox.name, email)
	validity = jmap._message_of(email)[1]
	# Read with the default policy, which decodes a name RFC 2231 or RFC 2047 writes (« Relevé été.pdf »; one written
	# against the rules is read as NeoMail reads it: `_name_of`); an attached message is written back as the message
	# carries it all the same, to the few headers Python normalises (webmail_api.attachment_bytes).
	message = message_from_bytes(_source(mailbox, folder, validity, uid), policy=policy.default)
	found = find(message, wanted)
	data = webmail.attachment_bytes(found.part)
	# Nothing to save where NeoMail sees a file: never an empty file announced as saved
	if not data and (wanted.size or 0) > 0:
		frappe.throw(_("This attachment cannot be read from its message here: save it with Save As instead."))
	return _file_name(found.name or _unnamed(found)), found.mime, data, message


@frappe.whitelist(methods=["POST"])
@per_person
def save_to_drive(account=None, email=None, attachment=None, drive_folder=None, edit=None):
	"""Save the attachment NeoMail names (the mailbox `account`, its address or its name; the message's JMAP id
	`email`; `attachment`, NeoMail's description of the file: {index, name, size, mime, cid}) in the Drive folder
	`drive_folder`, with the person's right to add to it. `edit` 1: a file one of the Drive's editors opens (NeoDoc,
	NeoGrille, NeoPrés, NeoPDF), which the page then opens. Answers {name, file_name, folder, url (/drive/f/<name>),
	folder_url, message}."""
	from frappe_webmail import drive
	from frappe_webmail.attachments import LAST_DRIVE_FOLDER

	_gate()
	if not drive.available():
		frappe.throw(_("The Drive is not installed on this instance"))
	# A folder's name, never an object: one would become a filter of the query that finds the folder.
	drive_folder = drive_folder[:MAX_FOLDER] if isinstance(drive_folder, str) else ""
	# Refused before the mail is read: a folder the person may not file into costs no IMAP round trip.
	if not drive.folder_entry(drive_folder):
		frappe.throw(_("You cannot add files to this folder of the Drive"), frappe.PermissionError)
	editing = bool(cint(edit))
	if editing:
		# What NeoMail says of the name first, at no cost; then the name the message gives.
		_editable(_wanted(attachment).name)
	name, _mime, payload = read(account, email, attachment)
	if editing:
		_editable(name)
	saved = drive.deposit(payload, name, drive_folder)
	frappe.defaults.set_user_default(LAST_DRIVE_FOLDER, drive_folder)
	place = drive.folder_entry(drive_folder)
	return {
		"name": saved.name,
		"file_name": saved.file_name,
		"folder": drive_folder,
		"url": drive.file_url(saved.name),
		"folder_url": drive.folder_url(drive_folder),
		"message": _("Saved in the Drive: {0}").format((place or {}).get("path") or saved.file_name),
	}


def _editable(name):
	"""Refuse a file no editor of the Drive opens here: one of another type, or one whose editor this site has no
	build of."""
	found = editor(_file_name(name))
	if not found:
		frappe.throw(_("Only a .docx, .xlsx, .pptx or .pdf file opens in an editor of the Drive."))
	if found[0] not in installed_editors():
		frappe.throw(_("{0} is not installed on this site.").format(found[1]))


@frappe.whitelist(methods=["POST"])
@per_person
def open_in_editor(account=None, email=None, attachment=None):
	"""« Ouvrir dans NeoGrille »: the attachment NeoMail names (as `save_to_drive` takes it) copied into the person's own
	Drive, in « Pièces jointes » / « <date> <subject> » of its message (`_message_folder`), with no folder to pick, then
	opened by the page in the Drive's editor of its type, a format the editor imports included (`openable`). The same
	attachment opened again (the message moved to another folder included) opens the same copy, the person's edits and
	all, while it is in their Drive and theirs to write (`_kept_copy`; for an imported format, the file the editor saved
	its work in beside it). Answers {name, file_name, folder, url (/drive/f/<name>), editor (suite's key), product,
	reused, message}."""
	from frappe_webmail import drive

	_gate()
	if not drive.available():
		frappe.throw(_("The Drive is not installed on this instance"))
	# What NeoMail says of the name first, at no cost; then the name the message gives.
	_openable(_wanted(attachment).name)
	name, _mime, payload, message = _read(account, email, attachment)
	found = _openable(name)
	key = _copy_key(account, email, attachment, message)
	kept = _kept_copy(key)
	if kept:
		return _opened(kept, extension(kept.file_name), reused=True)
	saved = drive.deposit(payload, name, _message_folder(message))
	_keep_copy(key, saved.name)
	return _opened(saved, found, reused=False)


def _openable(name):
	"""The extension of `name` when an editor of this site's Drive opens it (`openable`), else refused, as `_editable`."""
	found = extension(_file_name(name))
	opens = openable()
	if found not in opens:
		frappe.throw(_("No editor of the Drive opens this type of file here."))
	return found


def _opened(row, found, reused):
	"""What `open_in_editor` answers for the Drive file `row` of extension `found`."""
	from frappe_webmail import drive

	key = openable().get(found) or (EDITORS.get(found) or ("", ""))[0]
	product = PRODUCTS.get(key, "")
	return {
		"name": row.name,
		"file_name": row.file_name,
		"folder": row.folder,
		"url": drive.file_url(row.name),
		"editor": key,
		"product": product,
		"reused": reused,
		"message": _("Opened in {0}: {1}").format(product, row.file_name),
	}


# Where the Drive copies of the attachments the person opened are kept, beside the site's defaults: rows of the defaults'
# table under a parent of their own (never the person's, which every page of the desk loads), one a copy.
COPIES = "__neomail_opened_copies"


def _copy_key(account, email, attachment, message):
	"""The key of the Drive copy of this attachment: the person, the message (its Message-ID, which a move to another
	folder keeps; else its id) and what identifies the file (its rank, name, size, Content-ID), hashed."""
	import hashlib

	wanted = _wanted(attachment)
	try:
		said_id = str(message.get("Message-ID") or "").strip()
	except Exception:
		said_id = ""
	which = said_id or f"{account}\n{email}"
	said = "\n".join(
		str(part) for part in (frappe.session.user, which, wanted.index, wanted.name, wanted.size, wanted.cid)
	)
	return "neomail_opened:" + hashlib.sha1(said.encode()).hexdigest()


def _kept_copy(key):
	"""The Drive copy kept under `key`, while it is in the Drive (not in its bin, nor under a folder in it) and the
	person may still write it; for an imported format, the file the editor saved the work in beside it when there is
	one (`_saved_beside`). None otherwise, and the key forgotten."""
	name = frappe.db.get_value("DefaultValue", {"parent": COPIES, "defkey": key}, "defvalue")
	if not name:
		return None
	row = _usable(name)
	if not row:
		frappe.db.delete("DefaultValue", {"parent": COPIES, "defkey": key})
		return None
	return _saved_beside(row) or row


def _keep_copy(key, name):
	"""Keep `name` as the Drive copy under `key`."""
	frappe.db.delete("DefaultValue", {"parent": COPIES, "defkey": key})
	frappe.get_doc(
		{
			"doctype": "DefaultValue",
			"parent": COPIES,
			"parenttype": "__neomail",
			"parentfield": "system_defaults",
			"defkey": key,
			"defvalue": name,
		}
	).insert(ignore_permissions=True)


# The type an editor saves an imported file as (suite's save_import): beside it, under its stem.
SAVED_AS = {"sheet": "xlsx", "word": "docx"}


def _saved_beside(row):
	"""For a copy of a format its editor imports, the newest file the editor saved the work in beside it (« Liste.xlsx »
	or « Liste (1).xlsx » for « Liste.xls »), that the person may write; None otherwise."""
	found = extension(row.file_name)
	native = SAVED_AS.get(openable().get(found, ""))
	if not native or found == native:
		return None
	stem = row.file_name[: -(len(found) + 1)]
	near = frappe.get_all(
		"File",
		filters={"folder": row.folder, "is_folder": 0, "file_name": ["like", f"{stem}%.{native}"]},
		fields=["name", "file_name"],
		order_by="creation desc",
		limit=20,
	)
	pattern = re.compile(re.escape(stem) + r"( \(\d+\))?\." + native + "$", re.IGNORECASE)
	for each in near:
		if pattern.match(each.file_name):
			usable = _usable(each.name)
			if usable:
				return usable
	return None


def _usable(name):
	"""The Drive file `name` ({name, file_name, folder}) while it is a file in the Drive, neither in its bin nor under a
	folder that is, that the person may write; else None."""
	from suite.drive.api.permissions import user_has_permission

	row = frappe.db.get_value(
		"File", name, ["name", "file_name", "folder", "is_folder", "status"], as_dict=True
	)
	if not row or row.is_folder or row.status not in (None, "", "Active"):
		return None
	folder, depth = row.folder, 0
	while folder and depth < 64:
		above = frappe.db.get_value("File", folder, ["status", "folder"], as_dict=True)
		if not above or above.status not in (None, "", "Active"):
			return None
		folder, depth = above.folder, depth + 1
	return row if user_has_permission(frappe.get_doc("File", name), "write") else None


def _message_folder(message):
	"""The folder of the person's own Drive where the attachments of `message` go: « Pièces jointes » (in their
	language), then « <its date> <its subject> », each made the first time (suite's create_folder, the person's right),
	private as all of their Drive is. The title is cleaned as a file's name is (no path, no character a system refuses
	or that changes how it reads)."""
	from email.utils import parsedate_to_datetime

	try:
		when = parsedate_to_datetime(str(message.get("Date") or "")).date()
	except Exception:
		# A date that cannot be read, or one whose zone is beyond any (an overflow): today's
		when = frappe.utils.getdate()
	try:
		subject = " ".join(str(message.get("Subject") or "").split())
	except Exception:
		subject = ""
	title = _file_name(f"{when.isoformat()} {subject or _('(no subject)')}")[:MAX_MESSAGE_FOLDER].strip(" .")
	attachments = _subfolder(_home(), _("Attachments"))
	return _subfolder(attachments, title or when.isoformat())


def _home():
	"""The person's own Drive folder (suite's, made the first time)."""
	from suite.drive.utils import get_user_folder

	return get_user_folder().name


def _subfolder(parent, title):
	"""The folder `title` of `parent` (one of the person's), made when it is not there. Two first opens at once: the
	one that made it second finds the other's."""
	from frappe_webmail import drive

	def found():
		names = frappe.get_all(
			"File",
			filters={"folder": parent, "is_folder": 1, "file_name": title, "status": "Active"},
			pluck="name",
			limit=1,
		)
		return names[0] if names else None

	existing = found()
	if existing:
		return existing
	try:
		return drive.create_folder(parent, title)["name"]
	except frappe.ValidationError:
		again = found()
		if again:
			return again
		raise


@frappe.whitelist(methods=["POST"])
@per_person
def to_scans(account=None, email=None, attachment=None, document_type="Invoice"):
	"""Send the attachment NeoMail names (as `save_to_drive` takes it) to the scanned documents, where the OCR reads
	it: a PDF or a picture only. As the old webmail's « Create a scanned document » (scans.create): a supplier invoice
	unless `document_type` says another of scans.TYPES; the same bytes are never scanned twice. Answers {name,
	duplicate, url, message}."""
	from frappe_webmail import scans

	_gate()
	if not scans.can_create():
		frappe.throw(_("You are not allowed to create a scanned document"), frappe.PermissionError)
	hint = _wanted(attachment)
	if not scannable(_file_name(hint.name) if hint.name else "", hint.mime):
		frappe.throw(_("Only a PDF or a picture can be sent to the scanned documents."))
	name, mime, payload = read(account, email, attachment)
	if not scannable(name, mime):
		frappe.throw(_("Only a PDF or a picture can be sent to the scanned documents."))
	result = scans.create(payload, name, str(document_type or "Invoice"))
	result["message"] = (
		_("Already among the scanned documents")
		if result.get("duplicate")
		else _("Sent to the scanned documents: the reading takes about a minute")
	)
	return result
