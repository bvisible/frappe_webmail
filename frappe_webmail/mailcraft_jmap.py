# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
MailCraft's way into the webmail: a thin JMAP server (RFC 8620 core, RFC 8621 mail) over the webmail's own
functions, for the browser build of MailCraft (bvisible/mailcraft), named NeoMail, framed by /neomail (maintenance#1630, step 2
of the plan that brings Nora into MailCraft).

It serves what MailCraft's browser build asks for and reads, nothing more: the folders, a window of the newest
messages of a folder, their keywords, size, date, preview and raw header fields, the raw source of a message,
keyword changes, moves, deletes, drafts and sending. No */changes, no threads, no search: MailCraft re-reads its
window at each sync and searches its own cache. Every mailbox call goes through the webmail's own rules
(`get_account`: the owner or a person the mailbox is shared with) and its pooled IMAP connection (`imap_session`).
Only what the webmail has no function for is done here: the raw source, INTERNALDATE, UIDVALIDITY and the raw header
fields, appending a given message, sending a given message. The instance's contacts come as an address book
(JMAP for Contacts, RFC 9610) in one mailbox of the person: mailcraft_contacts; their own calendars likewise
(JMAP for Calendars), where the Suite is installed: mailcraft_calendars; and their Neoffice notes, where neoffice_theme
is installed: mailcraft_notes. Besides JMAP, `picture` fetches a picture on
the web that a message links to, once the person asked to see it, which a page can't read from another site itself
(pictures.py).

Who may call it: the desk's people (System Users), on a site where NeoMail is on (`neomail_enabled`), with a token and only
with a token. MailCraft sends no cookie: each request carries `Authorization: Bearer <token>`, a token kept hashed in
the cache, good for this module's five addresses only (`authenticate`, an auth hook), for twelve hours at most and no
longer than what it was given for: the desk session of the /neomail page, or the OAuth bearer token Neodesk signs in
with (`hand_over`; an hour, then Neodesk hands its renewed one over). A desk session's cookie alone opens nothing
here, so another page can't make a signed-in browser read or send mail (this fork's CSRF check refuses nothing
unless a site enforces it, maintenance#310).

Ids, in JMAP's alphabet (A-Z a-z 0-9 - _):
- account   "A" + base64url(mailbox address)
- mailbox   "M" + base64url(folder path)
- email     "E" + <UIDVALIDITY> + "V" + <IMAP UID> + "Z" + base64url(folder path): an id never names another message,
            even after its folder was recreated (RFC 8620 §1.2)
- blob      "B" + the email id without its "E" (the message's source), or "U" + random (an upload)
- identity  "I" + base64url(mailbox address)
"""

import base64
import contextlib
import email.policy
import hashlib
import json
import re
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.parser import BytesHeaderParser

import frappe
from frappe import _
from frappe.utils import cint
from werkzeug.wrappers import Response

from frappe_webmail import webmail_api as webmail
from frappe_webmail.attachments import get_folder_counts

CORE = "urn:ietf:params:jmap:core"
MAIL = "urn:ietf:params:jmap:mail"
SUBMISSION = "urn:ietf:params:jmap:submission"
QUOTA = "urn:ietf:params:jmap:quota"

METHOD_PREFIX = "frappe_webmail.mailcraft_jmap."
# The five addresses a token is good for, under each API prefix Frappe routes.
_OWN_PATH = re.compile(
	r"^/+api/+(?:v[12]/+)?method/+frappe_webmail\.mailcraft_jmap\.(session|api|download|upload|picture)/*$"
)
# The two that hand tokens out, which a token never opens.
_HANDING_OUT = re.compile(r"^/+api/+(?:v[12]/+)?method/+frappe_webmail\.mailcraft_jmap\.(hand_over|renew)/*$")

TOKEN_SECONDS = 12 * 3600
UPLOAD_SECONDS = 15 * 60
FILED_SECONDS = 3600
MAX_UPLOAD = 25 * 1024 * 1024
MAX_UPLOADS = 10  # kept at once by one person
MAX_UPLOAD_BYTES = 60 * 1024 * 1024  # kept at once by one person
MAX_OBJECTS = 500
MAX_CALLS = 16
MAX_PATCH = 64  # entries in one object's patch
MAX_IMPORTS = 5  # per call
MAX_SUBMISSIONS = 2  # per call
MAX_SENDS = 30  # per person and SEND_WINDOW
SEND_WINDOW = 600
MAX_RECIPIENTS = 100
SMTP_TIMEOUT = 30
SMTP_QUIET = 600  # seconds between two Error Log lines of the same trouble with one mailbox's mail server

# Keywords and the IMAP flags they stand for ($Forwarded as the webmail writes it); any other keyword is an IMAP
# keyword of the same name.
_FLAG_OF = {
	"$seen": b"\\Seen",
	"$flagged": b"\\Flagged",
	"$answered": b"\\Answered",
	"$draft": b"\\Draft",
	"$forwarded": b"$Forwarded",
}
_KEYWORD_OF = {flag.lower(): keyword for keyword, flag in _FLAG_OF.items()}
# RFC 8621 §4.1.1 (and IMAP's atom): printable ASCII but ( ) { ] % * " \ and the space.
_KEYWORD = re.compile(r"^[!#$&'+,\-./0-9:;<=>?@A-Z\[^_`a-z|}~]{1,255}$")
_ROLES = {
	"inbox": "inbox",
	"sent": "sent",
	"drafts": "drafts",
	"trash": "trash",
	"spam": "junk",
	"archive": "archive",
}
_MESSAGE_ID = re.compile(r"^[EB]([1-9][0-9]{0,9})V([1-9][0-9]{0,9})Z([A-Za-z0-9_-]{1,340})$")
_APPENDUID = re.compile(rb"\[APPENDUID (\d+) (\d+)\]", re.IGNORECASE)
_ADDRESS = re.compile(r"^[^@\s<>()\[\],;:\"]+@[^@\s<>()\[\],;:\"]+\.[^@\s<>()\[\],;:\"]+$")


class JmapError(Exception):
	"""A method-level error: `["error", {"type", "description"}, callId]`, or the SetError of one object, with the
	properties the standard gives its type (`invalidRecipients`, for one)."""

	def __init__(self, type_, description="", **properties):
		super().__init__(description)
		self.type = type_
		self.description = description
		self.properties = properties


class NotSent(Exception):
	"""Nothing went, and a later try may do: the mail server could not be reached or signed in to, the connection
	ended before the message was on its way, or the server answered "not now" (4xx)."""


class MayHaveGone(Exception):
	"""The connection to the mail server failed while the message was on its way, or while its answer was: nobody can
	know whether it went."""


# ---------------------------------------------------------------------------------------------------------------
# Who may call it
# ---------------------------------------------------------------------------------------------------------------


def _token_key(token):
	return "mailcraft_jmap_token:" + hashlib.sha256(token.encode()).hexdigest()


def give_token(user=None, bearer=None):
	"""A token for the session's person: MailCraft sends it as `Authorization: Bearer`. Twelve hours at most, and no
	longer than what asked for it: the desk session of the page, or the OAuth bearer token Neodesk signs in with
	(`bearer`, see hand_over); sign out, and it is dead. The cache keeps hashes only."""
	token = secrets.token_urlsafe(32)
	kept = {"user": user or frappe.session.user}
	if bearer:
		kept["oauth"] = _digest(bearer)
	else:
		kept["sid"] = getattr(frappe.session, "sid", None)
	frappe.cache().set_value(_token_key(token), kept, expires_in_sec=TOKEN_SECONDS)
	return token


def _digest(secret):
	return hashlib.sha256(secret.encode()).hexdigest()


def _request_bearer():
	"""The bearer token the request carries in `Authorization`, if any."""
	scheme, _sep, value = (frappe.get_request_header("Authorization") or "").partition(" ")
	return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def _bearer_alive(user, digest):
	"""A bearer token of `user` that Frappe itself would take has this hash: active, unexpired, of an OAuth client that
	is still there and grants the token's scopes (`frappe.oauth.OAuthWebRequestValidator.validate_bearer_token`). The
	name of an OAuth Bearer Token is the token itself: it is compared by its hash, never kept or shown. Only the
	person's unexpired tokens are read (the expired ones stay Active in the table for good)."""
	for name, client, scopes in frappe.get_all(
		"OAuth Bearer Token",
		filters={"user": user, "status": "Active", "expiration_time": (">", frappe.utils.now_datetime())},
		fields=["name", "client", "scopes"],
		as_list=True,
	):
		if _digest(name) == digest:
			return _client_grants(client, scopes)
	return False


def _client_grants(client, scopes):
	"""The OAuth client is still there and grants every scope of the token, as Frappe requires of a bearer token."""
	from frappe.oauth import get_url_delimiter

	granted = frappe.db.get_value("OAuth Client", client, "scopes") if client else None
	if not granted or scopes is None:
		return False
	delimiter = get_url_delimiter()
	return all(scope in granted.split(delimiter) for scope in scopes.split(delimiter))


def _binding_alive(kept):
	"""What a token was given for is still there: the OAuth bearer token (Neodesk), or the desk session (the page)."""
	if kept.get("oauth"):
		return _bearer_alive(kept.get("user"), kept["oauth"])
	return _session_alive(kept.get("sid"))


def _is_desk_user(user):
	return (
		bool(user) and user != "Guest" and frappe.get_cached_value("User", user, "user_type") == "System User"
	)


def _session_alive(sid):
	if not sid:
		return False
	if frappe.cache().hget("session", sid):
		return True
	return bool(frappe.db.sql("select 1 from `tabSessions` where sid=%s", sid))


def neomail_enabled():
	"""Whether NeoMail is on: on every instance since it went to all of them, unless the site's configuration switches it
	off (`neomail_disabled: 1`). While it was tried, only where the configuration said `mailcraft_trial` (osiris,
	maintenance#1629, #1630)."""
	return not frappe.conf.get("neomail_disabled")


def authenticate():
	"""auth_hooks: a request to one of this module's five addresses that carries a token /neomail or hand_over gave
	is made as that token's person. Anything else is left alone: another address; a `cmd` (Frappe runs a `cmd` form
	field whatever the path) other than the method the path names; a request already signed in (a desk cookie); a
	token unknown, expired, or whose desk session or bearer token ended; a person no longer enabled or no longer of
	the desk."""
	request = getattr(frappe.local, "request", None)
	if request is None or not neomail_enabled():
		return
	match = _OWN_PATH.match(getattr(request, "path", "") or "")
	if not match:
		return
	cmd = str((frappe.local.form_dict or {}).get("cmd") or "")
	if cmd and cmd != METHOD_PREFIX + match.group(1):
		return
	if frappe.session.user not in ("", "Guest"):
		return
	scheme, _sep, token = (frappe.get_request_header("Authorization") or "").partition(" ")
	token = token.strip()
	if scheme.lower() != "bearer" or not token:
		return
	try:
		user = _person_of_token(token)
	except Exception as e:
		# Answered as no token. Left to Frappe, the error would be logged with the values of these frames: the
		# request's form (a picture's address), the desk session the token is bound to.
		log_quietly("MailCraft JMAP: a token could not be checked", e)
		return
	if not user:
		return
	# set_user empties the request's arguments; Frappe's own token checks put them back the same way.
	form_dict = frappe.local.form_dict
	frappe.set_user(user)
	frappe.local.form_dict = form_dict
	frappe.local.flags.mailcraft_jmap_user = user


def _person_of_token(token):
	"""The person a token was given to, while it is good (`authenticate`); None otherwise."""
	kept = frappe.cache().get_value(_token_key(token))
	if not isinstance(kept, dict):
		return None
	user = kept.get("user")
	if user and frappe.db.get_value("User", user, "enabled") and _is_desk_user(user) and _binding_alive(kept):
		return user
	return None


def log_quietly(title, error):
	"""Log an error by its kind and where it happened, never its words nor the values of its frames, which may hold
	a token, a session or the address of a picture. A log that fails too is let go: what called this answers anyway."""
	import traceback

	try:
		where = "".join(traceback.format_tb(error.__traceback__))
		frappe.log_error(title, f"{type(error).__name__}\n{where}")
	except Exception:
		pass


def _gate():
	"""NeoMail is on, and the request came with a token (see `authenticate`) for the session's person."""
	if not neomail_enabled():
		raise frappe.PageDoesNotExistError
	user = frappe.session.user
	if frappe.local.flags.get("mailcraft_jmap_user") != user or not _is_desk_user(user):
		raise frappe.PermissionError


@frappe.whitelist(methods=["POST"])
def hand_over(**kwargs):
	"""For Neodesk: the person's mailboxes as /neomail hands them over (`accounts`, `language`, `product`, `signatures`,
	and `nora`: whether the instance has Nora), to a request
	that carries an OAuth bearer token of that person, never to a desk cookie alone, which a page of another site could
	make a browser send. Wherever NeoMail is on, the build installed here or not: Neodesk brings its own (pinned in its
	desktop/src/editors/manifest.json and the Suite's craft_editors.json). The facade tokens given live as long as that bearer token does: an hour for Neodesk's, whose
	refresh revokes the old one, so Neodesk hands its renewed one over again."""
	if not neomail_enabled():
		raise frappe.PageDoesNotExistError
	user = frappe.session.user
	bearer = _request_bearer()
	# A bearer token of this very person that Frappe itself would take: the one Frappe signed the request in with, or,
	# when a desk cookie signed it in, one Frappe would have taken all the same.
	if not (bearer and _is_desk_user(user) and _bearer_alive(user, _digest(bearer))):
		raise frappe.PermissionError
	from frappe_webmail.www.neomail import PRODUCT, host_mailboxes, nora_installed, signatures_url

	language = frappe.db.get_value("User", user, "language") or frappe.local.lang or "en"
	return {
		"accounts": host_mailboxes(bearer=bearer),
		"language": language,
		"product": PRODUCT,
		# Where the signatures of those mailboxes are written, which NeoMail's own signatures name for them.
		"signatures": signatures_url(),
		# Whether NeoMail's band may call Nora: the instance has her.
		"nora": nora_installed(),
	}


@frappe.whitelist(methods=["POST"])
def renew(**kwargs):
	"""For /neomail: fresh facade tokens for the page's own desk session, when the framed build's were refused (they die
	with the cache, or after twelve hours), so that it carries on without a reload. A desk cookie only: Neodesk, which
	signs in with a bearer token, asks hand_over. Only where the page can be opened: nothing else calls it."""
	from frappe_webmail.www.neomail import available

	if not available():
		raise frappe.PageDoesNotExistError
	if _request_bearer() or not _is_desk_user(frappe.session.user):
		raise frappe.PermissionError
	from frappe_webmail.www.neomail import host_mailboxes

	return {"accounts": host_mailboxes()}


def no_store(response=None, request=None):
	"""after_request: /neomail and the answers of hand_over and renew hold tokens, the facade's answers hold mail; no
	cache keeps any of them."""
	path = (getattr(request, "path", "") or "") if request is not None else ""
	if response is not None and (
		path.rstrip("/") in ("/neomail", "/mailcraft") or _OWN_PATH.match(path) or _HANDING_OUT.match(path)
	):
		response.headers["Cache-Control"] = "no-store"


# ---------------------------------------------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------------------------------------------


def _b64(text):
	return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _unb64(text):
	try:
		return base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode()).decode()
	except (ValueError, UnicodeDecodeError):
		return None


def account_id(address):
	return "A" + _b64(address)


def mailbox_id(folder):
	return "M" + _b64(folder)


def email_id(folder, validity, uid):
	return f"E{int(validity)}V{int(uid)}Z{_b64(folder)}"


def _account_of(jmap_id):
	return _unb64(jmap_id[1:]) if isinstance(jmap_id, str) and jmap_id[:1] == "A" else None


def _folder_of(jmap_id):
	return _unb64(jmap_id[1:]) if isinstance(jmap_id, str) and jmap_id[:1] == "M" else None


def _message_of(jmap_id):
	"""(folder, validity, uid) of an email id (or of a message's blob id, "B…"), or None."""
	match = _MESSAGE_ID.match(jmap_id) if isinstance(jmap_id, str) else None
	if not match:
		return None
	folder = _unb64(match.group(3))
	return (folder, int(match.group(1)), int(match.group(2))) if folder else None


# ---------------------------------------------------------------------------------------------------------------
# The addresses
# ---------------------------------------------------------------------------------------------------------------


def _json(data, status=200):
	return Response(
		json.dumps(data, separators=(",", ":"), default=str), status=status, content_type="application/json"
	)


def _problem(type_, status, detail=""):
	"""A request-level error (RFC 8620 §3.6.1, RFC 7807)."""
	return _json({"type": type_, "status": status, "detail": detail}, status=status)


def _answer(build):
	"""Run `build` behind the gate and answer. MailCraft forgets its token on a 401 or a 403, so those are kept for a
	real refusal: an outage of the mail server is a 503 (MailCraft retries), anything unforeseen a 500 without
	detail (the Error Log has it)."""
	try:
		_gate()
		return build()
	except frappe.PageDoesNotExistError:
		return _problem("about:blank", 404, "Not found")
	except frappe.PermissionError:
		return _problem("about:blank", 403, _("Not permitted"))
	except (webmail.WebmailConnectionError, webmail.WebmailAuthenticationError) as e:
		return _problem("about:blank", 503, str(e))
	except frappe.ValidationError as e:
		return _problem("about:blank", 403, str(e))
	except JmapError as e:
		return _problem(
			"about:blank", 404 if e.type == "accountNotFound" else 400, f"{e.type} {e.description}".strip()
		)
	except Exception as e:
		frappe.log_error("MailCraft JMAP: a request failed", f"{e!r}\n{frappe.get_traceback()}")
		return _problem("about:blank", 500, _("The mail server could not answer."))
	finally:
		frappe.local.message_log = []


@frappe.whitelist(methods=["GET"])
def session(account=None, **kwargs):
	"""The JMAP session of one mailbox (MailCraft reads one account per session): `?account=<name>`, the Webmail
	Account's name, which is its address as first given (an address changed later leaves the name as it was)."""
	return _answer(lambda: _json(_session(account)))


def _max_upload():
	return min(MAX_UPLOAD, cint(frappe.conf.get("max_file_size")) or MAX_UPLOAD)


def _session(address):
	from frappe_webmail import mailcraft_calendars, mailcraft_contacts, mailcraft_notes

	account = webmail.get_account(address)
	aid = account_id(account.name)
	base = frappe.utils.get_url() + "/api/method/" + METHOD_PREFIX
	# The instance's contacts, as an address book, and the person's own calendars, in one mailbox of the person
	# (mailcraft_contacts, mailcraft_calendars).
	contacts, account_contacts = _optional_parts(mailcraft_contacts.session_parts, account)
	calendars, account_calendars = _optional_parts(mailcraft_calendars.session_parts, account)
	# The person's Neoffice notes, in the same mailbox (mailcraft_notes).
	notes, account_notes = _optional_parts(mailcraft_notes.session_parts, account)
	return {
		"capabilities": {
			CORE: {
				"maxSizeUpload": _max_upload(),
				"maxConcurrentUpload": 1,
				"maxSizeRequest": 10 * 1024 * 1024,
				"maxConcurrentRequests": 2,
				"maxCallsInRequest": MAX_CALLS,
				"maxObjectsInGet": MAX_OBJECTS,
				"maxObjectsInSet": MAX_OBJECTS,
				"collationAlgorithms": [],
			},
			MAIL: {},
			SUBMISSION: {},
			QUOTA: {},
			**contacts,
			**calendars,
			**notes,
		},
		"accounts": {
			aid: {
				"name": account.name,
				"isPersonal": account.user == frappe.session.user,
				"isReadOnly": False,
				"accountCapabilities": {
					MAIL: {
						"maxMailboxesPerEmail": 1,
						"maxMailboxDepth": None,
						"maxSizeMailboxName": 255,
						"maxSizeAttachmentsPerEmail": _max_upload(),
						"emailQuerySortOptions": ["receivedAt"],
						"mayCreateTopLevelMailbox": False,
					},
					SUBMISSION: {"maxDelayedSend": 0, "submissionExtensions": {}},
					QUOTA: {},
					**account_contacts,
					**account_calendars,
					**account_notes,
				},
			}
		},
		"primaryAccounts": {
			MAIL: aid,
			SUBMISSION: aid,
			QUOTA: aid,
			**{capability: aid for capability in (*contacts, *calendars, *notes)},
		},
		"username": frappe.session.user,
		"apiUrl": base + "api",
		"downloadUrl": base + "download?accountId={accountId}&blobId={blobId}&name={name}&type={type}",
		"uploadUrl": base + "upload?accountId={accountId}",
		"state": "0",
	}


def _optional_parts(parts, account):
	"""What an optional part of the facade adds to a session (the address book, the calendars), or nothing when it fails:
	the mailbox opens all the same (a Suite older than the calendars' reading, a table missing, a database error)."""
	try:
		return parts(account)
	except Exception:
		frappe.log_error("MailCraft JMAP: a part of the session failed", frappe.get_traceback())
		return {}, {}


@frappe.whitelist(methods=["POST"])
def api(**kwargs):
	"""The JMAP API: a request of method calls, run in order, each answered under its call id."""
	return _answer(_api)


def _api():
	try:
		request = json.loads(frappe.request.get_data() or b"null")
	except ValueError:
		return _problem("urn:ietf:params:jmap:error:notJSON", 400, "The request is not JSON.")
	calls = request.get("methodCalls") if isinstance(request, dict) else None
	if not isinstance(calls, list) or not isinstance(request.get("using"), list):
		return _problem("urn:ietf:params:jmap:error:notRequest", 400, "The request is not a JMAP request.")
	if len(calls) > MAX_CALLS:
		return _problem("urn:ietf:params:jmap:error:limit", 400, "maxCallsInRequest")
	results, answers = {}, []
	for call in calls:
		well_formed = isinstance(call, list) and len(call) == 3
		if not (
			well_formed
			and isinstance(call[0], str)
			and isinstance(call[1], dict)
			and isinstance(call[2], str)
		):
			return _problem("urn:ietf:params:jmap:error:notRequest", 400, "A method call is malformed.")
		name, args, call_id = call
		try:
			handler = METHODS.get(name) or _more_methods().get(name)
			if handler is None:
				raise JmapError("unknownMethod", name)
			out = (name, handler(_resolve(args, results)))
		except JmapError as e:
			out = ("error", {"type": e.type, "description": e.description, **e.properties})
		except (webmail.WebmailConnectionError, webmail.WebmailAuthenticationError) as e:
			out = ("error", {"type": "serverUnavailable", "description": str(e)})
		except frappe.ValidationError as e:
			# The webmail's refusals: an account not one's own, a disabled one.
			out = ("error", {"type": "forbidden", "description": str(e)})
		except Exception as e:
			frappe.log_error("MailCraft JMAP: a method failed", f"{name}: {e!r}\n{frappe.get_traceback()}")
			out = ("error", {"type": "serverFail", "description": _("The mail server could not answer.")})
		results[call_id] = out
		answers.append([out[0], out[1], call_id])
	return _json({"methodResponses": answers, "sessionState": "0"})


def _more_methods():
	"""The address book's, the calendars' and the notes' methods (mailcraft_contacts, mailcraft_calendars,
	mailcraft_notes, which read this module: imported when first asked)."""
	from frappe_webmail.mailcraft_calendars import METHODS as CALENDAR_METHODS
	from frappe_webmail.mailcraft_contacts import METHODS as CONTACT_METHODS
	from frappe_webmail.mailcraft_notes import METHODS as NOTE_METHODS

	return {**CONTACT_METHODS, **CALENDAR_METHODS, **NOTE_METHODS}


@frappe.whitelist(methods=["GET"])
def download(**kwargs):
	"""A blob: the raw source of a message ("B…") or an upload ("U…"), as a file to save, never a page to show."""

	def build():
		form = frappe.local.form_dict
		account = _account(form.get("accountId"))
		blob = str(form.get("blobId") or "")
		data = _upload_data(blob) if blob.startswith("U") else _source(account, blob)
		if data is None:
			return _problem("about:blank", 404, "No such blob.")
		response = Response(data, status=200, content_type="message/rfc822")
		response.headers["Content-Disposition"] = 'attachment; filename="message.eml"'
		# Where the Suite is installed, its after_request replaces this policy on every /api/method/ answer. No browser
		# shows the source either way: the address answers only a request that carries the token, and a page can't
		# make a browser send one by opening the address.
		response.headers["Content-Security-Policy"] = "sandbox"
		response.headers["X-Content-Type-Options"] = "nosniff"
		return response

	return _answer(build)


@frappe.whitelist(methods=["POST"])
def upload(**kwargs):
	"""A whole message to import as a draft or a sent copy: kept a quarter of an hour for this person, at most
	MAX_UPLOADS of them and MAX_UPLOAD_BYTES at once."""

	def build():
		account = _account(frappe.local.form_dict.get("accountId"))
		data = frappe.request.get_data() or b""
		if len(data) > _max_upload():
			return _problem("urn:ietf:params:jmap:error:limit", 413, "maxSizeUpload")
		user = frappe.session.user
		now = time.time()
		kept = [u for u in (frappe.cache().get_value(_uploads_key(user)) or []) if u[2] > now]
		if len(kept) >= MAX_UPLOADS or sum(u[1] for u in kept) + len(data) > MAX_UPLOAD_BYTES:
			return _problem(
				"urn:ietf:params:jmap:error:limit", 429, _("Too many messages waiting to be filed.")
			)
		blob = "U" + secrets.token_hex(16)
		frappe.cache().set_value(
			_upload_key(blob), {"user": user, "data": data}, expires_in_sec=UPLOAD_SECONDS
		)
		kept.append((blob, len(data), now + UPLOAD_SECONDS))
		frappe.cache().set_value(_uploads_key(user), kept, expires_in_sec=UPLOAD_SECONDS)
		return _json(
			{
				"accountId": account_id(account.name),
				"blobId": blob,
				"type": "message/rfc822",
				"size": len(data),
			},
			201,
		)

	return _answer(build)


@frappe.whitelist(methods=["POST"])
def picture(url=None, **kwargs):
	"""A picture on the web that a message links to, which a page can't read from another site itself: fetched here
	under MailCraft's own rules, a few at a time for the whole bench (pictures.py). /neomail's
	`window.mailcraftFetchUrl` asks for it, once the person said to show a message's pictures; the address goes in the
	body, so that no log keeps it. The picture's bytes as their own kind, or a failure whose `detail` the person reads."""
	from frappe_webmail.pictures import failed, relay

	try:
		_gate()
	except frappe.PageDoesNotExistError:
		return _problem("about:blank", 404, "Not found")
	except frappe.PermissionError:
		return _problem("about:blank", 403, _("Not permitted"))
	except Exception as e:
		# Answered here: an error Frappe caught would be logged with the request's form, the address with it.
		failed(e)
		return _problem("about:blank", 500, _("The mail server could not answer."))
	return relay(url, frappe.session.user)


def _upload_key(blob):
	return "mailcraft_jmap_upload:" + blob


def _uploads_key(user):
	return "mailcraft_jmap_uploads:" + user


def _upload_data(blob):
	kept = frappe.cache().get_value(_upload_key(blob)) if blob[:1] == "U" else None
	return kept.get("data") if isinstance(kept, dict) and kept.get("user") == frappe.session.user else None


def _forget_upload(blob):
	frappe.cache().delete_value(_upload_key(blob))
	user = frappe.session.user
	kept = [u for u in (frappe.cache().get_value(_uploads_key(user)) or []) if u[0] != blob]
	frappe.cache().set_value(_uploads_key(user), kept, expires_in_sec=UPLOAD_SECONDS)


# ---------------------------------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------------------------------


def _resolve(args, results):
	"""Arguments with their back-references (`"#ids": {"resultOf", "name", "path"}`) replaced by what they point at."""
	out = {}
	for key, value in args.items():
		if not key.startswith("#"):
			out[key] = value
			continue
		if not isinstance(value, dict) or value.get("resultOf") not in results:
			raise JmapError("invalidResultReference", key)
		name, result = results[value["resultOf"]]
		if name != value.get("name"):
			raise JmapError("invalidResultReference", key)
		out[key[1:]] = _pointer(result, str(value.get("path") or ""))
	return out


def _pointer(value, path):
	"""A JSON pointer with JMAP's `*` (RFC 8620 §3.7)."""
	tokens = path.split("/")[1:]
	for i, token in enumerate(tokens):
		token = token.replace("~1", "/").replace("~0", "~")
		if token == "*" and isinstance(value, list):
			rest = "/" + "/".join(tokens[i + 1 :]) if tokens[i + 1 :] else ""
			found = []
			for item in value:
				got = _pointer(item, rest) if rest else item
				found.extend(got if isinstance(got, list) else [got])
			return found
		if isinstance(value, dict) and token in value:
			value = value[token]
		elif isinstance(value, list) and token.isdecimal() and len(token) < 7 and int(token) < len(value):
			value = value[int(token)]
		else:
			raise JmapError("invalidResultReference", path)
	return value


def _account(jmap_id):
	"""The webmail account a call names, under the webmail's rule (owner or shared, enabled)."""
	address = _account_of(jmap_id)
	if not address:
		raise JmapError("accountNotFound", str(jmap_id)[:200])
	return webmail.get_account(address)


def utc_of(value, precise=False):
	"""A date and time of the instance (naive, in its system zone) in UTC, as JMAP writes it; `precise`, with its
	milliseconds when it has any (a version two changes in one second must tell apart)."""
	from zoneinfo import ZoneInfo

	from frappe.utils import get_datetime, get_system_timezone

	moment = get_datetime(value)
	if moment.tzinfo is None:
		moment = moment.replace(tzinfo=ZoneInfo(get_system_timezone()))
	moment = moment.astimezone(timezone.utc)
	text = moment.strftime("%Y-%m-%dT%H:%M:%S")
	if precise and moment.microsecond // 1000:
		text += f".{moment.microsecond // 1000:03d}"
	return text + "Z"


def moment_of(text):
	"""The instant a JMAP date says (`…Z` or an offset, with or without a fraction), to the millisecond, in UTC; None
	for what is no date."""
	from datetime import datetime

	if not isinstance(text, str):
		return None
	try:
		moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
	except ValueError:
		return None
	if moment.tzinfo is None:
		return None
	moment = moment.astimezone(timezone.utc)
	return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


def _whole_number(value, name, default=None):
	"""A JMAP Int argument (RFC 8620 §1.3): a JSON integer; null is its default."""
	if value is None:
		return default
	if isinstance(value, bool) or not isinstance(value, int):
		raise JmapError("invalidArguments", name)
	return value


def _ids(args, key="ids"):
	ids = args.get(key)
	if ids is not None and (not isinstance(ids, list) or len(ids) > MAX_OBJECTS):
		raise JmapError("requestTooLarge" if isinstance(ids, list) else "invalidArguments", key)
	return ids


def _by_folder(ids):
	"""{folder: [(id, validity, uid)]} of the email ids that read, and the ones that don't."""
	folders, bad = {}, []
	for jid in ids:
		place = _message_of(jid)
		if place:
			folders.setdefault(place[0], []).append((jid, place[1], place[2]))
		else:
			bad.append(jid)
	return folders, bad


def _select(client, folder):
	"""Open `folder` read-only: its UIDVALIDITY, or None when it can't be (it holds no messages, or no longer
	exists)."""
	try:
		answer = client.select_folder(folder, readonly=True) or {}
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
		return None
	return int(answer.get(b"UIDVALIDITY") or 0)


def _validities(account, folders):
	"""The UIDVALIDITY of each folder (0 for one that can't be read)."""
	out = {}
	with webmail.imap_session(account) as client:
		for folder in folders:
			try:
				out[folder] = int(
					(client.folder_status(folder, [b"UIDVALIDITY"]) or {}).get(b"UIDVALIDITY") or 0
				)
			except Exception as e:
				if webmail._imap_is_connection_error(e):
					raise
				out[folder] = 0
	return out


# ---------------------------------------------------------------------------------------------------------------
# Mailbox/get
# ---------------------------------------------------------------------------------------------------------------


def mailbox_get(args):
	account = _account(args.get("accountId"))
	wanted = _ids(args)
	folders = webmail.get_folders(account.name)
	names = {f["name"] for f in folders}
	roles = {}
	for role, folder in (webmail.get_folder_mapping(account.name).get("effective") or {}).items():
		if folder and role in _ROLES and folder in names:
			roles.setdefault(folder, _ROLES[role])
	chosen = [f for f in folders if wanted is None or mailbox_id(f["name"]) in wanted]
	selectable = [f["name"] for f in chosen if f.get("selectable", True)]
	counts = get_folder_counts(account.name, json.dumps(selectable)) if selectable else {}
	listed = []
	for f in chosen:
		name, delimiter = f["name"], f.get("delimiter") or "/"
		parent, _sep, leaf = name.rpartition(delimiter) if delimiter else ("", "", name)
		count = counts.get(name) or {}
		entry = {
			"id": mailbox_id(name),
			"name": leaf or name,
			"parentId": mailbox_id(parent) if parent and parent in names else None,
			"role": roles.get(name),
			"sortOrder": 0,
			"totalEmails": int(count.get("messages") or 0),
			"unreadEmails": int(count.get("unseen") or 0),
			"totalThreads": int(count.get("messages") or 0),
			"unreadThreads": int(count.get("unseen") or 0),
			"myRights": {
				"mayReadItems": True,
				"mayAddItems": True,
				"mayRemoveItems": True,
				"maySetSeen": True,
				"maySetKeywords": True,
				"mayCreateChild": False,
				"mayRename": False,
				"mayDelete": False,
				"maySubmit": True,
			},
			"isSubscribed": True,
		}
		listed.append(_only(entry, args.get("properties")))
	found = {e["id"] for e in listed}
	return {
		"accountId": account_id(account.name),
		"state": "0",
		"list": listed,
		"notFound": [i for i in (wanted or []) if i not in found],
	}


def _only(entry, properties):
	if not properties:
		return entry
	return {k: v for k, v in entry.items() if k == "id" or k in properties}


# ---------------------------------------------------------------------------------------------------------------
# Email/query, Email/get
# ---------------------------------------------------------------------------------------------------------------


def email_query(args):
	account = _account(args.get("accountId"))
	flt = args.get("filter") or {}
	folder = _folder_of(flt.get("inMailbox")) if isinstance(flt, dict) else None
	if not folder or set(flt) - {"inMailbox"}:
		raise JmapError("unsupportedFilter", _("Only a folder can be listed."))
	sort = args.get("sort") or []
	if not isinstance(sort, list) or any(
		not isinstance(s, dict) or s.get("property") != "receivedAt" for s in sort
	):
		raise JmapError("unsupportedSort", "receivedAt")
	# RFC 8620 §5.5: ascending unless said otherwise.
	ascending = bool(sort[0].get("isAscending", True)) if sort else True
	limit = max(0, min(cint(args.get("limit") or MAX_OBJECTS), MAX_OBJECTS))
	position = max(0, cint(args.get("position") or 0))
	with webmail.imap_session(account) as client:
		validity = _select(client, folder)
		# A folder that holds no messages (\Noselect, a parent only) lists none, rather than failing every sync.
		uids = _arrival_order(client) if validity else []
	if not ascending:
		uids.reverse()
	window = uids[position : position + limit]
	return {
		"accountId": account_id(account.name),
		"queryState": "0",
		"canCalculateChanges": False,
		"position": position,
		"ids": [email_id(folder, validity, uid) for uid in window],
		"total": len(uids),
	}


def _arrival_order(client):
	"""The folder's messages, oldest received first: by INTERNALDATE where the server sorts (RFC 5256), else by UID
	(the order they were filed in)."""
	try:
		if b"SORT" in (client.capabilities() or ()):
			return list(client.sort(["ARRIVAL"], ["NOT", "DELETED"]))
	except Exception as e:
		if webmail._imap_is_connection_error(e):
			raise
	return sorted(client.search(["NOT", "DELETED"]))


_ITEMS = {
	"keywords": b"FLAGS",
	"size": b"RFC822.SIZE",
	"receivedAt": b"INTERNALDATE",
	"hasAttachment": b"BODYSTRUCTURE",
	"preview": b"BODYSTRUCTURE",
	"headers": b"BODY.PEEK[HEADER]",
}


def email_get(args):
	account = _account(args.get("accountId"))
	ids = _ids(args)
	if ids is None:
		raise JmapError("requestTooLarge", _("Name the messages to read."))
	properties = args.get("properties") or ["id", "blobId", "keywords", "mailboxIds", "size", "receivedAt"]
	if not isinstance(properties, list):
		raise JmapError("invalidArguments", "properties")
	items = sorted({_ITEMS[p] for p in properties if p in _ITEMS} | {b"FLAGS"})
	folders, not_found = _by_folder(ids)
	listed = []
	with webmail.imap_session(account) as client:
		for folder, wanted in folders.items():
			validity = _select(client, folder)
			current = [(jid, uid) for jid, valid, uid in wanted if validity and valid == validity]
			not_found.extend(jid for jid, valid, _uid in wanted if not validity or valid != validity)
			if not current:
				continue
			data = client.fetch([uid for _jid, uid in current], [i.decode() for i in items])
			previews = webmail._list_previews(client, data) if "preview" in properties else {}
			for jid, uid in current:
				msg = data.get(uid)
				if not msg:
					not_found.append(jid)
					continue
				listed.append(_email(jid, folder, uid, msg, previews, properties))
	return {"accountId": account_id(account.name), "state": "0", "list": listed, "notFound": not_found}


def _email(jid, folder, uid, msg, previews, properties):
	entry = {"id": jid}
	for p in properties:
		if p == "blobId":
			entry[p] = "B" + jid[1:]
		elif p == "threadId":
			entry[p] = jid
		elif p == "mailboxIds":
			entry[p] = {mailbox_id(folder): True}
		elif p == "keywords":
			entry[p] = keywords(msg.get(b"FLAGS") or ())
		elif p == "size":
			entry[p] = int(msg.get(b"RFC822.SIZE") or 0)
		elif p == "receivedAt":
			entry[p] = utc_date(msg.get(b"INTERNALDATE"))
		elif p == "hasAttachment":
			entry[p] = bool(msg.get(b"BODYSTRUCTURE") and webmail.has_attachments(msg[b"BODYSTRUCTURE"]))
		elif p == "preview":
			entry[p] = (previews.get(uid) or "")[:256]
		elif p == "headers":
			entry[p] = raw_headers(msg.get(b"BODY[HEADER]") or b"")
	return entry


def keywords(flags):
	"""IMAP flags as JMAP keywords: \\Seen is $seen…, an IMAP keyword is itself in lower case; \\Deleted and \\Recent
	have no keyword."""
	out = {}
	for flag in flags:
		flag = flag if isinstance(flag, bytes) else str(flag).encode()
		keyword = _KEYWORD_OF.get(flag.lower())
		if keyword is None and not flag.startswith(b"\\"):
			keyword = flag.decode("ascii", "replace").lower()
		if keyword and _KEYWORD.match(keyword):
			out[keyword] = True
	return out


def utc_date(value):
	"""INTERNALDATE as a JMAP UTCDate. imapclient gives it naive, in this process's local time."""
	if not isinstance(value, datetime):
		return None
	if value.tzinfo is None:
		value = value.astimezone()
	return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_headers(block):
	"""Header fields in JMAP's Raw form (RFC 8621 §4.1.2): the name, and everything after its colon, folding kept."""
	text = block.decode("utf-8", "surrogateescape") if isinstance(block, bytes) else str(block or "")
	fields = []
	for line in re.split(r"\r?\n", text):
		if not line:
			continue
		if line[:1] in (" ", "\t") and fields:
			fields[-1]["value"] += "\r\n" + line
		elif ":" in line:
			name, value = line.split(":", 1)
			if name and not name[-1:].isspace():
				fields.append({"name": name, "value": value})
	return [
		{"name": f["name"], "value": f["value"].encode("utf-8", "surrogateescape").decode("utf-8", "replace")}
		for f in fields[:500]
	]


def _source(account, blob):
	"""The raw RFC 5322 source of a message, read without marking it read; None when the id names nothing (its
	folder is gone, or was recreated)."""
	place = _message_of(blob)
	if not place:
		return None
	folder, validity, uid = place
	with webmail.imap_session(account) as client:
		if _select(client, folder) != validity:
			return None
		data = client.fetch([uid], ["BODY.PEEK[]"])
	return (data.get(uid) or {}).get(b"BODY[]")


# ---------------------------------------------------------------------------------------------------------------
# For another app's method
# ---------------------------------------------------------------------------------------------------------------


def message_place(account_name, message):
	"""(folder, uid) of the message MailCraft names by its email id, for another app's method that reads the message on
	the server itself: Nora's quick_reply gets the key of the message, never its text. The webmail's rule says who may
	(`get_account`), and the folder must still have the UIDVALIDITY the id carries, or the UID could now name another
	message. A Python call, not an address."""
	account = webmail.get_account(account_name)
	place = _message_of(message) if str(message or "")[:1] == "E" else None
	if not place:
		frappe.throw(_("This message cannot be found."))
	folder, validity, uid = place
	with webmail.imap_session(account) as client:
		if _select(client, folder) != validity:
			frappe.throw(_("This message is no longer in its folder: refresh the list and try again."))
	return folder, uid


# ---------------------------------------------------------------------------------------------------------------
# Email/set
# ---------------------------------------------------------------------------------------------------------------


def email_set(args):
	account = _account(args.get("accountId"))
	if args.get("create"):
		raise JmapError("invalidArguments", _("Messages are imported, not created."))
	update = args.get("update") or {}
	destroy = args.get("destroy") or []
	if (
		not isinstance(update, dict)
		or not isinstance(destroy, list)
		or len(update) + len(destroy) > MAX_OBJECTS
	):
		raise JmapError("invalidArguments", "update, destroy")
	not_updated, not_destroyed = {}, {}
	# Each object's patch is read whole before anything is written (JMAP: all or nothing per object).
	changes = {}  # id -> (folder, validity, uid, {(how, flag)}, target folder)
	for jid, patch in update.items():
		place = _message_of(jid)
		if not place or not isinstance(patch, dict):
			not_updated[jid] = {"type": "notFound" if not place else "invalidPatch"}
		elif len(patch) > MAX_PATCH:
			not_updated[jid] = {"type": "tooLarge", "description": str(MAX_PATCH)}
		else:
			change = _patch(place, patch)
			if isinstance(change, dict):
				not_updated[jid] = change
			else:
				changes[jid] = change
	gone = {}  # folder -> [(id, uid)]
	for jid in destroy:
		place = _message_of(jid)
		if place:
			gone.setdefault(place[0], []).append((jid, place[1], place[2]))
		else:
			not_destroyed[jid] = {"type": "notFound"}
	# An id whose folder was recreated since names nothing any more.
	folders = {c[0] for c in changes.values()} | set(gone)
	validities = _validities(account, sorted(folders)) if folders else {}
	for jid in [j for j, c in changes.items() if c[1] != validities.get(c[0])]:
		del changes[jid]
		not_updated[jid] = {"type": "notFound"}
	# A message another client deleted or moved since is not found, not "done": the mail server says nothing of a STORE
	# or a MOVE of a UID it no longer has.
	asked = {}
	for folder, _validity, uid, _flags, _target in changes.values():
		asked.setdefault(folder, set()).add(uid)
	for folder, items in gone.items():
		asked.setdefault(folder, set()).update(
			uid for _jid, validity, uid in items if validity == validities.get(folder)
		)
	present = _present(account, asked) if asked else {}
	for jid in [j for j, c in changes.items() if c[2] not in present.get(c[0], ())]:
		del changes[jid]
		not_updated[jid] = {"type": "notFound"}
	for folder, items in gone.items():
		for jid, validity, uid in items:
			if validity == validities.get(folder) and uid not in present.get(folder, ()):
				not_destroyed[jid] = {"type": "notFound"}
		gone[folder] = [item for item in items if item[0] not in not_destroyed]
	# Keywords: one STORE per folder, direction and flag, for all its messages.
	stores = {}
	for jid, (folder, _validity, uid, flags, _target) in changes.items():
		for how, flag in flags:
			stores.setdefault((folder, how, flag), []).append((jid, uid))
	for (folder, how, flag), items in stores.items():
		_apply(
			items,
			not_updated,
			changes,
			lambda uids, folder=folder, how=how, flag=flag: webmail.set_flags(
				account.name, uids, folder, **{f"{how}_flags": json.dumps([flag.decode()])}
			),
		)
	moves = {}
	for jid, (folder, _validity, uid, _flags, target) in changes.items():
		if target != folder:
			moves.setdefault((folder, target), []).append((jid, uid))
	# A moved message has another id (an id names a place): the answer says which, where it can be told.
	moved_to = {}
	for (source, target), items in moves.items():
		_apply(
			items,
			not_updated,
			changes,
			lambda _uids, source=source, target=target, items=items: moved_to.update(
				_move(account, source, target, items)
			),
		)
	destroyed = []
	for folder, wanted in gone.items():
		items = []
		for jid, validity, uid in wanted:
			if validity == validities.get(folder):
				items.append((jid, uid))
			else:
				not_destroyed[jid] = {"type": "notFound"}
		if not items:
			continue
		failed = {}
		_apply(
			items,
			failed,
			None,
			lambda uids, folder=folder: webmail.delete_emails(account.name, uids, folder, permanent=True),
		)
		not_destroyed.update(failed)
		destroyed.extend(jid for jid, _uid in items if jid not in failed)
	return {
		"accountId": account_id(account.name),
		"oldState": "0",
		"newState": "0",
		"updated": {jid: ({"id": moved_to[jid]} if moved_to.get(jid) else None) for jid in changes},
		"destroyed": destroyed,
		"notUpdated": not_updated,
		"notDestroyed": not_destroyed,
	}


def _patch(place, patch):
	"""One object's patch: the change, or the SetError."""
	folder, validity, uid = place
	flags, target = set(), folder
	for path, value in patch.items():
		kind, _sep, what = str(path).partition("/")
		if kind == "keywords" and what and value in (True, None):
			flag = _FLAG_OF.get(what.lower()) or (what.encode() if _KEYWORD.match(what) else None)
			if flag is None:
				return {"type": "invalidPatch", "description": str(path)[:200]}
			flags.add(("add" if value else "remove", flag))
		elif kind == "mailboxIds" and what and value in (True, None):
			named = _folder_of(what)
			if not named:
				return {"type": "invalidPatch", "description": str(path)[:200]}
			if value:
				target = named
			elif named == folder and target == folder:
				target = None
		else:
			return {"type": "invalidPatch", "description": str(path)[:200]}
	if target is None:
		return {"type": "invalidProperties", "description": _("A message stays in one folder.")}
	return (folder, validity, uid, flags, target)


def _present(account, wanted):
	"""Of these UIDs by folder, those the mail server still has (a message marked deleted and not expunged is still there)."""
	out = {}
	with webmail.imap_session(account) as client:
		for folder, uids in wanted.items():
			if not uids or _select(client, folder) is None:
				continue
			found = client.search(["UID", ",".join(str(uid) for uid in sorted(uids))])
			out[folder] = {int(uid) for uid in found} & set(uids)
	return out


# A message's Message-ID, as a server hands the field back (folded or not)
_HEADER_ID = re.compile(rb"^Message-ID:\s*(<[^>\r\n]+>)", re.IGNORECASE | re.MULTILINE)
_ID_FIELD = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
# The most messages of one move whose new place is looked for (more: they are found again by MailCraft's windows)
MAX_MOVED_FOUND = 500


def _message_ids(client, messages):
	"""The Message-ID of each of these messages of the selected folder (UIDs, or a set as IMAP writes one), by UID."""
	out = {}
	for uid, got in (client.fetch(messages, [_ID_FIELD]) or {}).items():
		field = next(
			(value for key, value in got.items() if key.upper().startswith(b"BODY[HEADER.FIELDS")), b""
		)
		match = _HEADER_ID.search(field or b"")
		if match:
			out[int(uid)] = match.group(1).lower()
	return out


def _move(account, source, target, items):
	"""Move these (id, UID) of `source` to `target` in one session, and the new id of each moved message that can be told:
	the messages that arrived in `target` from its UIDNEXT before the move on, matched by their Message-ID, where exactly
	one arrival has it. One that can't be told (no Message-ID, two alike, a server without UIDNEXT) has none: MailCraft
	finds it again when it reads `target`."""
	uids = [uid for _jid, uid in items]
	with webmail.imap_session(account) as client:
		try:
			before = int((client.folder_status(target, [b"UIDNEXT"]) or {}).get(b"UIDNEXT") or 0)
		except Exception as e:
			if webmail._imap_is_connection_error(e):
				raise
			before = 0
		client.select_folder(source)
		ids = _message_ids(client, uids[:MAX_MOVED_FOUND]) if before else {}
		webmail._move_messages(client, uids, target)
		if not ids:
			return {}
		# The messages moved: what follows only tells their new ids, and never makes the move a failure.
		try:
			validity = _select(client, target)
			arrived = {}
			for uid, mid in _message_ids(client, f"{before}:*").items():
				if uid >= before:
					arrived.setdefault(mid, []).append(uid)
		except Exception as e:
			log_quietly("MailCraft JMAP: where moved messages went could not be read", e)
			return {}
	if not validity:
		return {}
	out = {}
	for jid, uid in items:
		landed = arrived.get(ids.get(uid))
		if landed and len(landed) == 1:
			out[jid] = email_id(target, validity, landed[0])
	return out


def _apply(items, failed, changes, run):
	"""Run one write for these (id, uid); on failure each id gets a SetError, and the other writes go on."""
	try:
		run([uid for _jid, uid in items])
	except Exception as e:
		if isinstance(e, webmail.WebmailConnectionError | webmail.WebmailAuthenticationError):
			kind = "serverUnavailable"
		elif isinstance(e, frappe.ValidationError):
			kind = "forbidden"
		else:
			kind = "serverFail"
			frappe.log_error("MailCraft JMAP: a change failed", f"{e!r}")
		for jid, _uid in items:
			failed[jid] = {"type": kind, "description": str(e)[:300]}
			if changes is not None:
				changes.pop(jid, None)


# ---------------------------------------------------------------------------------------------------------------
# Email/import, Identity/get, EmailSubmission/set
# ---------------------------------------------------------------------------------------------------------------


def _filed_key(jid):
	return f"mailcraft_jmap_filed:{frappe.session.user}:{jid}"


def email_import(args):
	account = _account(args.get("accountId"))
	emails = args.get("emails") or {}
	if not isinstance(emails, dict) or len(emails) > MAX_IMPORTS:
		raise JmapError("invalidArguments", "emails")
	created, not_created = {}, {}
	for cid, spec in emails.items():
		spec = spec if isinstance(spec, dict) else {}
		blob = str(spec.get("blobId") or "")
		data = _upload_data(blob)
		boxes = [m for m, on in (spec.get("mailboxIds") or {}).items() if on]
		folder = _folder_of(boxes[0]) if len(boxes) == 1 else None
		if data is None:
			not_created[cid] = {
				"type": "blobNotFound",
				"description": _("The message to file was not found."),
			}
			continue
		if not folder:
			not_created[cid] = {
				"type": "invalidProperties",
				"description": _("A message goes into one folder."),
			}
			continue
		flags = [
			_FLAG_OF[str(k).lower()]
			for k, on in (spec.get("keywords") or {}).items()
			if on and str(k).lower() in _FLAG_OF
		]
		with webmail.imap_session(account) as client:
			answer = client.append(folder, data, flags=flags)
			appended = _APPENDUID.search(answer if isinstance(answer, bytes) else str(answer or "").encode())
			if appended:
				validity, uid = int(appended.group(1)), int(appended.group(2))
			else:
				validity, uid = _found_by_message_id(client, folder, data)
		if not uid or not validity:
			not_created[cid] = {
				"type": "serverFail",
				"description": _("The message was filed but cannot be found."),
			}
			continue
		_forget_upload(blob)
		jid = email_id(folder, validity, uid)
		# Only what this person has just filed may be sent (EmailSubmission/set).
		frappe.cache().set_value(_filed_key(jid), 1, expires_in_sec=FILED_SECONDS)
		created[cid] = {"id": jid, "blobId": "B" + jid[1:], "threadId": jid, "size": len(data)}
	return {
		"accountId": account_id(account.name),
		"oldState": "0",
		"newState": "0",
		"created": created,
		"notCreated": not_created,
	}


def _found_by_message_id(client, folder, data):
	"""(UIDVALIDITY, UID) of a message just appended, by the Message-ID of its header, on a server without UIDPLUS."""
	head = re.split(rb"\r?\n\r?\n", data, maxsplit=1)[0]
	match = re.search(rb"^Message-ID:\s*(<[^>\r\n]+>)", head, re.IGNORECASE | re.MULTILINE)
	if not match:
		return 0, None
	validity = _select(client, folder)
	if not validity:
		return 0, None
	found = client.search(["HEADER", "Message-ID", match.group(1).decode("ascii", "replace")])
	return (validity, max(found)) if found else (0, None)


def identity_get(args):
	account = _account(args.get("accountId"))
	return {
		"accountId": account_id(account.name),
		"state": "0",
		"list": [
			{
				"id": "I" + _b64(account.email),
				"name": account.sender_name or "",
				"email": account.email,
				"replyTo": None,
				"bcc": None,
				"textSignature": "",
				"htmlSignature": "",
				"mayDelete": False,
			}
		],
		"notFound": [],
	}


def submission_set(args):
	account = _account(args.get("accountId"))
	create = args.get("create") or {}
	if (
		not isinstance(create, dict)
		or len(create) > MAX_SUBMISSIONS
		or args.get("update")
		or args.get("destroy")
	):
		raise JmapError("invalidArguments", "create")
	created, not_created, down = {}, {}, None
	for cid, spec in create.items():
		if down:
			# The mail server could not take the one before: it is not asked again in this call.
			not_created[cid] = {"type": "serverUnavailable", "description": down}
			continue
		try:
			_submit(account, spec if isinstance(spec, dict) else {})
			created[cid] = {
				"id": "S" + secrets.token_hex(8),
				"sendAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
			}
		except (NotSent, webmail.WebmailConnectionError, webmail.WebmailAuthenticationError) as e:
			# (The webmail's own errors come from reading the filed message, before anything is sent.)
			if not created:
				# Nothing of this call went: the error of a whole call that the server can't serve just now, which
				# made no change (RFC 8620 §3.6.2), so that MailCraft keeps the message for its next try. Said of one
				# submission, the same type reads as one that may have gone.
				raise JmapError("serverUnavailable", str(e)) from e
			down = str(e)
			not_created[cid] = {"type": "serverUnavailable", "description": down}
		except JmapError as e:
			not_created[cid] = {"type": e.type, "description": e.description, **e.properties}
	return {
		"accountId": account_id(account.name),
		"oldState": "0",
		"newState": "0",
		"created": created,
		"notCreated": not_created,
	}


def _sends_key():
	return f"mailcraft_jmap_sends:{frappe.session.user}"


def _submit(account, spec):
	"""Send a message this person has just filed (Email/import) to its envelope's recipients, from the mailbox's own
	address, through the mailbox's SMTP server. The filed copy is not touched and no second copy goes to Sent."""
	if spec.get("identityId") != "I" + _b64(account.email):
		raise JmapError("forbiddenFrom", _("This mailbox can only send as itself."))
	envelope = spec.get("envelope") or {}
	sender = str((envelope.get("mailFrom") or {}).get("email") or "")
	if sender.lower() != account.email.lower():
		raise JmapError("forbiddenFrom", _("This mailbox can only send as itself."))
	recipients = []
	for rcpt in envelope.get("rcptTo") or []:
		address = str(rcpt.get("email") or "").strip() if isinstance(rcpt, dict) else ""
		if not _ADDRESS.match(address):
			raise JmapError("invalidRecipients", address[:200])
		recipients.append(address)
	if not recipients:
		raise JmapError("noRecipients", _("Add at least one recipient."))
	if len(recipients) > MAX_RECIPIENTS:
		raise JmapError("tooManyRecipients", str(MAX_RECIPIENTS))
	jid = str(spec.get("emailId") or "")
	if not frappe.cache().get_value(_filed_key(jid)):
		raise JmapError("invalidEmail", _("Only a message just written here can be sent."))
	sends = cint(frappe.cache().get_value(_sends_key()))
	if sends >= MAX_SENDS:
		raise JmapError("rateLimit", _("Too many messages sent in a short time; try again in a few minutes."))
	data = _source(account, "B" + jid[1:])
	if not data:
		raise JmapError("invalidEmail", _("The message to send was not found."))
	if not _sender_is(data, account.email):
		raise JmapError("forbiddenFrom", _("The message must be from this mailbox."))
	try:
		_hand_over(account, recipients, _as_sent(data))
	except MayHaveGone as e:
		# It may have gone: it counts, and it can't be sent again from here.
		_went(jid, sends)
		raise JmapError("serverFail", str(e)) from e
	_went(jid, sends)


def _went(jid, sends):
	frappe.cache().set_value(_sends_key(), sends + 1, expires_in_sec=SEND_WINDOW)
	frappe.cache().delete_value(_filed_key(jid))


def _hand_over(account, recipients, data):
	"""Give the message to the mailbox's SMTP server a step at a time (RFC 5321 §3.3), so that what goes wrong says
	whether anything went: nothing has gone until the server answers 250 to the end of the data, and from that answer
	on it has, whatever the goodbye does.

	- NotSent: nothing went, and a later try may do (the server could not be reached or signed in to, the connection
	  ended before the data, or the server answered "not now", 4xx).
	- JmapError, of the standard's refusals (RFC 8621 §7.5): the server will not take it (5xx). Nothing went either.
	- MayHaveGone: the connection failed while the message was on its way or its answer was, the one case that
	  can't be known; MailCraft then holds the message as one that may have been sent."""
	server = _signed_in(account)
	try:
		refused = _envelope(server, account, recipients, len(data))
		try:
			code, answer = server.data(data)
		except smtplib.SMTPDataError as e:
			# The DATA command itself was turned down: the message never left.
			raise _no(e.smtp_code, e.smtp_error, "forbiddenToSend") from e
		except (smtplib.SMTPException, OSError) as e:
			_noted(account, "doubt", "a message may not have reached the mail server", e)
			raise MayHaveGone(
				_("The connection to the mail server failed while the message was on its way.")
			) from e
		if code != 250:
			raise _no(code, answer, "invalidEmail")
	finally:
		_goodbye(server)
	if refused:
		# Some recipients took it: it is sent (a refusal here would have MailCraft delete the sent copy).
		frappe.log_error("MailCraft JMAP: some recipients refused", f"{account.name}: {', '.join(refused)}")


def _signed_in(account):
	"""The mailbox's SMTP server, connected (TLS, or STARTTLS when the mailbox says so) and signed in to; NotSent when
	it can't be."""
	server = None
	try:
		context = ssl.create_default_context()
		if account.smtp_ssl:
			server = smtplib.SMTP_SSL(
				account.smtp_host, account.smtp_port, timeout=SMTP_TIMEOUT, context=context
			)
		else:
			server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=SMTP_TIMEOUT)
			if account.smtp_starttls:
				server.starttls(context=context)
		webmail.smtp_login(server, account)
	except (smtplib.SMTPException, OSError, frappe.ValidationError) as e:
		_goodbye(server)
		_noted(account, "down", "the mail server could not be reached or signed in to", e)
		raise NotSent(_("The mail server could not be reached or signed in to.")) from e
	return server


def _envelope(server, account, recipients, size):
	"""MAIL and RCPT: who the message is from and whom it goes to. The recipients the server turned down when others
	take it; NotSent, or the standard's refusal, when nobody can."""
	try:
		server.ehlo_or_helo_if_needed()
		options = [f"size={size}"] if server.does_esmtp and server.has_extn("size") else []
		code, answer = server.mail(account.email, options)
		if code != 250:
			raise _no(code, answer, "forbiddenMailFrom")
		refused = {}
		for address in recipients:
			code, answer = server.rcpt(address)
			if code not in (250, 251):
				refused[address] = code
		if len(refused) == len(recipients):
			if all(500 <= code <= 599 for code in refused.values()):
				raise JmapError(
					"invalidRecipients",
					_("The mail server takes none of the recipients."),
					invalidRecipients=list(refused),
				)
			raise NotSent(_("The mail server can't take the recipients just now."))
		return refused
	except (smtplib.SMTPException, OSError) as e:
		_noted(account, "down", "the connection to the mail server ended before a message", e)
		raise NotSent(_("The connection to the mail server ended before the message was sent.")) from e


def _no(code, answer, kind):
	"""The server's no: the refusal `kind` when it is for good (5xx; a message too large for it is tooLarge, whatever the
	step), "not now" otherwise."""
	said = f"{code} {answer.decode('utf-8', 'replace') if isinstance(answer, bytes) else answer}"[:300]
	if code == 552:
		return JmapError("tooLarge", said)
	if 500 <= code <= 599:
		return JmapError(kind, said)
	return NotSent(said)


def _goodbye(server):
	"""QUIT, and the connection closed whatever the server answers to it: the message's fate is settled by then."""
	if server is None:
		return
	try:
		server.quit()
	except (smtplib.SMTPException, OSError):
		with contextlib.suppress(OSError):
			server.close()


def _noted(account, trouble, title, error):
	"""A trouble with a mailbox's mail server in the Error Log, once in SMTP_QUIET for each kind of trouble: MailCraft
	tries again at its next run, a few minutes later, and the same line would be written each time."""
	key = f"mailcraft_jmap_smtp_trouble:{account.name}:{trouble}"
	if frappe.cache().get_value(key):
		return
	frappe.cache().set_value(key, 1, expires_in_sec=SMTP_QUIET)
	frappe.log_error(f"MailCraft JMAP: {title}", f"{account.name}: {error!r}")


def _sender_is(data, address):
	"""The message is from `address` and from it alone: exactly one From with one address, no defect, and a Sender
	absent or the same."""
	try:
		head = BytesHeaderParser(policy=email.policy.default).parsebytes(data)
		froms = head.get_all("From") or []
		senders = head.get_all("Sender") or []
		if len(froms) != 1 or froms[0].defects or len(froms[0].addresses) != 1:
			return False
		if froms[0].addresses[0].addr_spec.lower() != address.lower():
			return False
		return all(
			len(s.addresses) == 1 and s.addresses[0].addr_spec.lower() == address.lower() for s in senders
		)
	except Exception:
		return False


def _as_sent(data):
	"""The bytes that go to SMTP: every line ending CRLF (no bare CR or LF to smuggle with), and no Bcc header."""
	data = re.sub(rb"\r\n|\r|\n", b"\r\n", data)
	head, sep, body = data.partition(b"\r\n\r\n")
	lines, skipping = [], False
	for line in head.split(b"\r\n"):
		if line[:1] in (b" ", b"\t") and skipping:
			continue
		skipping = line.lower().startswith(b"bcc:")
		if not skipping:
			lines.append(line)
	return b"\r\n".join(lines) + sep + body


def mailbox_set(args):
	_account(args.get("accountId"))
	refused = {"type": "forbidden", "description": _("Folders are managed in the webmail for now.")}
	return {
		"accountId": args.get("accountId"),
		"oldState": "0",
		"newState": "0",
		"notCreated": {k: refused for k in (args.get("create") or {})},
		"notUpdated": {k: refused for k in (args.get("update") or {})},
		"notDestroyed": {k: refused for k in (args.get("destroy") or [])},
	}


# ---------------------------------------------------------------------------------------------------------------
# Quota/get
# ---------------------------------------------------------------------------------------------------------------

QUOTA_ID = "q"
QUOTA_TTL = 300


def quota_get(args):
	"""The space the mailbox uses on its server and its limit (RFC 9425), as the webmail's own storage bar reads it
	(IMAP QUOTA on INBOX): one quota of the whole account in octets, or none when the server keeps none. NeoMail shows
	it in its File page and at the foot of its folder pane. Read again at most every five minutes: NeoMail asks at each
	sync, and each reading opens an IMAP session."""
	account = _account(args.get("accountId"))
	ids = _ids(args)
	key = f"mailcraft_jmap:quota:{account.name}"
	kept = frappe.cache().get_value(key)
	if kept is None:
		read = webmail.get_quota(account.name)
		kept = {"used": int(read["usage_kb"]) * 1024, "limit": int(read["limit_kb"]) * 1024} if read else {}
		frappe.cache().set_value(key, kept, expires_in_sec=QUOTA_TTL)
	quotas = []
	if kept:
		quotas.append(
			{
				"id": QUOTA_ID,
				"resourceType": "octets",
				"used": kept["used"],
				"hardLimit": kept["limit"],
				"scope": "account",
				"name": account.name,
				"types": ["Mail"],
			}
		)
	known = {q["id"] for q in quotas}
	return {
		"accountId": args.get("accountId"),
		"state": "0",
		"list": [q for q in quotas if ids is None or q["id"] in ids],
		"notFound": [] if ids is None else [i for i in ids if i not in known],
	}


METHODS = {
	"Mailbox/get": mailbox_get,
	"Mailbox/set": mailbox_set,
	"Email/query": email_query,
	"Email/get": email_get,
	"Email/set": email_set,
	"Email/import": email_import,
	"Identity/get": identity_get,
	"EmailSubmission/set": submission_set,
	"Quota/get": quota_get,
}
