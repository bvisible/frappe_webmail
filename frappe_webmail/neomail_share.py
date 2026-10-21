# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
Share an e-mail in Synk (the instance's Raven) from NeoMail, in the desk's page /app/neomail (neoffice-apps,
docs/raven-in-neomail-study.md, section 8.2). NeoMail hands the page a message by its mailbox and its JMAP email id
alone (`mailcraft:share`, where the handover says `share: true`, `offered`); the page asks the person where to share it
(`destinations`), and `share` posts it there as the person: their own words, the sender, the subject and the date, the
start of the text (from the e-mail's HTML when it has no plain text, never the HTML as it is), the attachments when
asked, and the link that opens the message in NeoMail for whoever shares the mailbox.

Who may is the webmail's rule for the mailbox (owned or shared with the person: webmail_api.get_account, which answers
another's as one that does not exist) and Raven's for the conversation: a channel the person is a member of, or a
direct message with someone who uses Synk, found or made by Raven itself. The post is the person's own, made by Raven's
own method, so Raven's permissions apply to it as to a message written in Synk. Desk people only, on the page's session
with its CSRF token, as the page's other calls.

Chat in Synk about a message (`mailcraft:chat`, section 8.6): `chat` opens the conversation with its sender (their
direct message) or with everyone on it who uses Synk (the direct message for one person, else a private channel of the
message's thread, the same one whoever opens it from the thread), and posts nothing in the person's name: they write in
Synk. A channel to make, or people to add to one, is asked first, as Raven tells them.
"""

import hashlib
import re
import unicodedata
from email import message_from_bytes, policy
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import quote, urlencode

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, escape_html, get_url

# The role that opens Synk (Raven).
RAVEN_ROLE = "Raven User"
# The largest message read whole from its server, the start of its text that goes into the post, and the person's own
# words, in characters.
MAX_SOURCE = 30 * 1024 * 1024
MAX_TEXT = 1500
MAX_NOTE = 2000
# The attachments shared with a message: so many at most, each and all together so large at most. What does not fit
# is left out, and the answer says how many were.
MAX_FILES = 10
MAX_FILE = 10 * 1024 * 1024
MAX_FILES_TOTAL = 25 * 1024 * 1024
# The longest name an attachment keeps.
MAX_FILE_NAME = 140
# How the post writes the message's date (babel's pattern, in the person's language).
DATE_FORMAT = "d MMMM yyyy, HH:mm"
# A thread's channel: the words of its subject that its name keeps (in characters), and the key of the thread after them.
MAX_CHAT_WORDS = 40
CHAT_KEY = 6
# The prefixes a reply or a forward puts before a subject, in the languages of the site's people.
_REPLY_PREFIX = re.compile(r"^\s*((re|fwd?|tr|aw|wg|sv|antw|rif|r)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)


def installed():
	"""Whether Synk (Raven) is installed on this site: without it, nothing here imports it."""
	return "raven" in frappe.get_installed_apps()


def has_synk(user=None):
	"""Whether `user` (the session's) has Synk: Raven installed here, and its role held. What Neodesk's NeoMail window
	asks before it offers Synk, Neodesk's own chat, as a module of NeoMail's (mailcraft_jmap.hand_over)."""
	user = user or frappe.session.user
	return installed() and RAVEN_ROLE in frappe.get_roles(user)


def offered(user=None):
	"""Whether a message can be shared in Synk by `user` (the session's): one of the desk's people for whom the page
	/app/neomail is offered, on a site with Raven, holding its role."""
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

	user = user or frappe.session.user
	return desk.in_desk_for(user) and installed() and RAVEN_ROLE in frappe.get_roles(user)


def _gate():
	"""The page's calls only: where the page is offered, on the desk's cookie with the session's CSRF token, for one
	of the desk's people who may share in Synk."""
	from frappe_webmail import mailcraft_jmap as jmap
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk
	from frappe_webmail.www import neomail

	if not desk.in_desk():
		raise frappe.PageDoesNotExistError
	jmap.page_request_only()
	neomail.desk_people_only()
	jmap.csrf_token_required()
	# A site without Raven says so, rather than failing to import it: NeoMail never offers the share there (the
	# handover's `share` follows `offered`), but a call can still come.
	if not installed():
		frappe.throw(_("Synk is not installed here."), title=_("Synk"))
	if not offered():
		frappe.throw(_("Synk is not open for you."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def destinations():
	"""Where the person may share a message: {channels: [{id, label, private}], people: [{id, label}]}, the channels
	they are a member of (not archived, no thread, no direct message: a person is chosen among `people`, whose direct
	message Raven finds or makes), and the people who use Synk (its users, not its bots), each by name."""
	_gate()
	user = frappe.session.user
	member = frappe.get_all("Raven Channel Member", filters={"user_id": user}, pluck="channel_id")
	channels = (
		frappe.get_all(
			"Raven Channel",
			filters={"name": ["in", member], "is_archived": 0, "is_thread": 0, "is_direct_message": 0},
			fields=["name", "channel_name", "type"],
			order_by="channel_name asc",
		)
		if member
		else []
	)
	people = frappe.get_all(
		"Raven User",
		filters={"enabled": 1, "type": "User", "user": ["not in", [user, "Administrator", "Guest"]]},
		fields=["user", "full_name"],
		order_by="full_name asc",
	)
	return {
		"channels": [
			{"id": c.name, "label": c.channel_name or c.name, "private": c.type == "Private"}
			for c in channels
		],
		"people": [{"id": p.user, "label": p.full_name or p.user} for p in people],
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=60)
def share(account=None, email=None, to=None, note=None, attachments=None, client_id=None):
	"""Share in Synk the message of the mailbox `account` (its address or its name) whose JMAP email id is `email`
	(`E<validity>V<uid>Z<folder>`, as the facade makes it), in `to`: `channel:<id>` (a channel of the person's) or
	`user:<id>` (a direct message with someone who uses Synk). `note`: the person's own words, above the message;
	`attachments`: 1 to share its attachments too; `client_id`: what makes a send that is asked again (a double
	click) one send only (Raven's idempotency key). Answers {channel, message (the post's last message), files (the
	attachments shared), left_out (those that did not fit)}."""
	from frappe_webmail import webmail_api as webmail
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

	_gate()
	mailbox = webmail.get_account(desk._mailbox_name(account))
	message = _message(mailbox, email)
	channel = _conversation(to)
	files, left_out = _attachments(message) if cint(attachments) else ([], 0)
	content = _content(message, note, mailbox.email, email)

	from raven.api.raven_message import send_message_with_attachments

	sent = send_message_with_attachments(
		channel_id=channel,
		content=content,
		files=files,
		client_id=str(client_id or "")[:64] or frappe.generate_hash(length=20),
	)
	last = sent[-1] if sent else None
	return {
		"channel": channel,
		"message": last.name if last else None,
		"files": len(files),
		"left_out": left_out,
	}


def _message(mailbox, email, headers_only=False):
	"""The message of `mailbox` whose JMAP email id is `email`, read from its server: an id that is not a message's is
	refused before any mail is read. `headers_only`: its headers alone, whatever its size (who is on it); otherwise
	all of it, MAX_SOURCE at most."""
	from email.parser import BytesHeaderParser

	from frappe_webmail import mailcraft_jmap as jmap

	if str(email or "")[:1] != "E" or not jmap._message_of(email):
		frappe.throw(_("This message cannot be found."))
	raw = jmap._source(mailbox, email)
	if not raw:
		frappe.throw(_("This message is no longer in its folder: refresh the list and try again."))
	if headers_only:
		return BytesHeaderParser(policy=policy.default).parsebytes(raw)
	if len(raw) > MAX_SOURCE:
		frappe.throw(_("This message is too large to be shared."))
	return message_from_bytes(raw, policy=policy.default)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=60)
def chat(account=None, email=None, who=None, confirmed=None):
	"""Open in Synk a conversation about the message of the mailbox `account` whose JMAP email id is `email` (as
	`share` takes them), `who`: "sender", the direct message with its sender; "all", everyone on it who uses Synk (its
	sender, To and Cc: never a Bcc, which would tell the others who was hidden), the person aside: the direct message
	when that is one person, else the private channel of the message's thread (`_thread_channel`). Nothing is posted
	in the person's name. A channel to make, or people to add to it, is asked first: the answer is then {ask: true,
	with (the names of those it adds), adds (to a channel there already is), left_out}, and the same call with
	`confirmed` 1 does it. Otherwise {channel, route (Raven's address of the conversation), with (the names of the
	people in it), left_out (those Raven would not take: not in the channel's workspace)}."""
	from frappe_webmail import webmail_api as webmail
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

	_gate()
	if who not in ("sender", "all"):
		frappe.throw(_("Choose with whom to chat."))
	mailbox = webmail.get_account(desk._mailbox_name(account))
	message = _message(mailbox, email, headers_only=True)
	me = frappe.session.user
	senders = _addresses(message, ("from",))
	if who == "sender":
		if not senders:
			frappe.throw(_("This message has no sender."))
		found = _people(senders[:1])
		if found and found[0]["user"] == me:
			frappe.throw(_("You wrote this message: chat with everyone on it instead."))
		if not found:
			frappe.throw(_("{0} does not use Synk.").format(senders[0]))
		return _direct(found[0])
	people = [p for p in _people(senders + _addresses(message, ("to", "cc"))) if p["user"] != me]
	if not people:
		frappe.throw(_("No one else on this message uses Synk."))
	if len(people) == 1:
		return _direct(people[0])
	return _group(message, people, cint(confirmed))


def _addresses(message, headers):
	"""The addresses of the message's `headers`, in lower case, each once, in their order."""
	values = [str(value) for header in headers for value in (message.get_all(header) or [])]
	found = []
	for _name, address in getaddresses(values):
		address = address.strip().lower()
		if "@" in address and address not in found:
			found.append(address)
	return found


def _people(addresses):
	"""The people who use Synk among `addresses`, in their order: [{user, label}] (an enabled account of the site
	with that e-mail address, a Raven user of the person kind), the person included (the caller leaves them out),
	never Administrator nor Guest."""
	if not addresses:
		return []
	accounts = {}
	for row in frappe.get_all(
		"User", filters={"email": ["in", addresses], "enabled": 1}, fields=["name", "email"]
	):
		accounts.setdefault(str(row.email or "").lower(), row.name)
	users = [user for user in accounts.values() if user not in ("Administrator", "Guest")]
	if not users:
		return []
	labels = {
		row.user: row.full_name or row.user
		for row in frappe.get_all(
			"Raven User",
			filters={"enabled": 1, "type": "User", "user": ["in", users]},
			fields=["user", "full_name"],
		)
	}
	people = []
	for address in addresses:
		user = accounts.get(address)
		if user in labels and all(p["user"] != user for p in people):
			people.append({"user": user, "label": labels[user]})
	return people


def _direct(person):
	"""The direct message with `person`, found or made by Raven (whose own rules apply): the conversation `chat`
	answers."""
	from raven.api.raven_channel import create_direct_message_channel

	channel = create_direct_message_channel(person["user"])
	return {
		"channel": channel,
		"route": "/raven/dm-channel/" + quote(channel, safe=""),
		"with": [person["label"]],
		"left_out": 0,
	}


def _group(message, people, confirmed):
	"""The private channel of the message's thread with `people` (two or more): the person's channel of that thread,
	with whoever is missing added, or one made in their workspace, asked first (see `chat`). Raven takes in a channel
	only the members of its workspace (raven.permissions.channel_member_has_permission); its `add_members` does not
	ask, so the others are left out here, and counted."""
	me = frappe.session.user
	key = _thread_key(message)
	found, taken = _thread_channel(key)
	if not found and taken:
		# The thread's channel is someone else's (or archived): the person's own, under a key of theirs.
		key = _thread_key(message, me)
		found, taken = _thread_channel(key)
		if not found and taken:
			frappe.throw(
				_(
					"This message's channel in Synk is archived: open it again in Synk, or ask one of its admins."
				)
			)
	workspace = found.workspace if found else _workspace(people)
	in_workspace = set(
		frappe.get_all(
			"Raven Workspace Member",
			filters={"workspace": workspace, "user": ["in", [p["user"] for p in people]]},
			pluck="user",
		)
	)
	welcome = [p for p in people if p["user"] in in_workspace]
	left_out = len(people) - len(welcome)
	if not welcome:
		frappe.throw(_("No one else on this message is in your Synk workspace."))
	if not found and len(welcome) == 1:
		return {**_direct(welcome[0]), "left_out": left_out}
	members = (
		set(frappe.get_all("Raven Channel Member", filters={"channel_id": found.name}, pluck="user_id"))
		if found
		else set()
	)
	adding = [p for p in welcome if p["user"] not in members]
	if (adding or not found) and not confirmed:
		return {"ask": True, "with": [p["label"] for p in adding], "adds": bool(found), "left_out": left_out}
	if found:
		channel = frappe.get_doc("Raven Channel", found.name)
	else:
		channel = frappe.get_doc(
			{
				"doctype": "Raven Channel",
				"channel_name": _chat_name(message, key),
				"channel_description": _about(message),
				"type": "Private",
				"workspace": workspace,
			}
		).insert()
	if adding:
		channel.add_members([p["user"] for p in adding])
	return {
		"channel": channel.name,
		"route": "/raven/" + quote(workspace, safe="") + "/" + quote(channel.name, safe=""),
		"with": [p["label"] for p in welcome],
		"left_out": left_out,
	}


def _thread_key(message, salt=""):
	"""The key of the message's thread, the same for every message of it: from the first message it answers
	(`References`, else `In-Reply-To`), else from its own id; `salt` makes another, the person's own."""
	root = ""
	for header in ("references", "in-reply-to", "message-id"):
		ids = re.findall(r"<[^<>\s]+>", str(message.get(header) or ""))
		if ids:
			root = ids[0].lower()
			break
	if not root:
		root = (str(message.get("subject") or "") + str(message.get("from") or "")).lower()
	return hashlib.sha1((root + "\n" + salt).encode()).hexdigest()[:CHAT_KEY]


def _chat_name(message, key):
	"""The name of the thread's channel, as Raven writes one (lower case, hyphens): the words of the message's
	subject without « Re: » or « Fwd: », then the thread's key (`_thread_key`), which finds it again whatever the
	subject became."""
	subject = _REPLY_PREFIX.sub("", str(message.get("subject") or "")).strip() or _("(no subject)")
	words = unicodedata.normalize("NFKD", subject).encode("ascii", "ignore").decode().lower()
	slug = "-".join(re.findall(r"[a-z0-9]+", words))[:MAX_CHAT_WORDS].strip("-") or "e-mail"
	return f"{slug}-{key}"


def _thread_channel(key):
	"""(the person's channel of the thread whose key is `key`, whether there is one of that thread that is not: not
	theirs, or archived)."""
	rows = frappe.get_all(
		"Raven Channel",
		filters={"channel_name": ["like", f"%-{key}"], "is_direct_message": 0, "is_thread": 0},
		fields=["name", "workspace", "is_archived"],
	)
	for row in rows:
		if not row.is_archived and frappe.db.exists(
			"Raven Channel Member", {"channel_id": row.name, "user_id": frappe.session.user}
		):
			return row, True
	return None, bool(rows)


def _workspace(people):
	"""The workspace a channel for `people` is made in: one of the person's in which they may make a channel (a
	workspace admin, or one open to every member), with the most of `people` among its members."""
	users = [p["user"] for p in people]
	best, most = None, -1
	for row in frappe.get_all(
		"Raven Workspace Member",
		filters={"user": frappe.session.user},
		fields=["workspace", "is_admin"],
		order_by="workspace asc",
	):
		if not row.is_admin and frappe.db.get_value(
			"Raven Workspace", row.workspace, "only_admins_can_create_channels"
		):
			continue
		count = frappe.db.count("Raven Workspace Member", {"workspace": row.workspace, "user": ["in", users]})
		if count > most:
			best, most = row.workspace, count
	if not best:
		frappe.throw(_("You cannot make a channel in Synk: ask an admin of your workspace."))
	return best


def _about(message):
	"""The thread's channel's description: the message it is about, its subject and its sender."""
	subject = str(message.get("subject") or "").strip()[:200] or _("(no subject)")
	senders = getaddresses([str(value) for value in (message.get_all("from") or [])])
	sender = (senders[0][0] or senders[0][1]) if senders else ""
	if sender:
		return _('About the e-mail "{0}" from {1}').format(subject, sender)
	return _('About the e-mail "{0}"').format(subject)


def _conversation(to):
	"""The Raven channel `to` names: a channel the person is a member of, or the direct message Raven finds or makes
	with a person who uses Synk (Raven refuses another)."""
	kind, _sep, name = str(to or "").strip().partition(":")
	if kind == "channel" and name:
		found = frappe.db.get_value(
			"Raven Channel", name, ["name", "is_archived", "is_thread", "is_direct_message"], as_dict=True
		)
		member = frappe.db.exists(
			"Raven Channel Member", {"channel_id": name, "user_id": frappe.session.user}
		)
		if not found or not member or found.is_archived or found.is_thread or found.is_direct_message:
			frappe.throw(_("You can only share a message in a channel you are a member of."))
		return found.name
	if kind == "user" and name:
		from raven.api.raven_channel import create_direct_message_channel

		return create_direct_message_channel(name)
	frappe.throw(_("Choose where to share the message."))


def _date(message):
	"""The message's date in the site's time zone, its month in words in the person's language (« 4 juillet 2026,
	10:50 »); empty when it has none that can be read."""
	from datetime import timezone
	from zoneinfo import ZoneInfo

	from frappe.utils import format_datetime, get_system_timezone

	try:
		moment = parsedate_to_datetime(str(message.get("date") or ""))
	except (TypeError, ValueError, IndexError):
		return ""
	if moment is None:
		return ""
	# A date without a zone (`-0000`) is in UTC (RFC 5322 3.3): seen as it is, it read two hours early in summer.
	if moment.tzinfo is None:
		moment = moment.replace(tzinfo=timezone.utc)
	moment = moment.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	# The month in words: Raven takes digits such as « 04-07-2026 08 » for a telephone number and links them.
	return format_datetime(moment, DATE_FORMAT)


def _text(message):
	"""The start of the message's text: its plain text, or its HTML read as text, never as HTML; MAX_TEXT
	characters at most, cut at a word, its blank lines kept to one."""
	try:
		body = message.get_body(preferencelist=("plain", "html"))
		words = body.get_content() if body is not None else ""
		if body is not None and body.get_content_subtype() == "html":
			words = _html_words(words)
	except Exception:
		return ""
	lines, blank = [], False
	for line in str(words or "").replace("\r\n", "\n").split("\n"):
		line = " ".join(line.split())
		if not line.strip():
			if lines and not blank:
				lines.append("")
			blank = True
			continue
		lines.append(line)
		blank = False
	text = "\n".join(lines).strip()
	if len(text) > MAX_TEXT:
		cut = text[:MAX_TEXT].rsplit(" ", 1)[0] or text[:MAX_TEXT]
		text = cut.rstrip() + " …"
	return text


# The elements that end a line of text, when an HTML message is read as text.
_BLOCKS = (
	"p",
	"div",
	"li",
	"tr",
	"table",
	"ul",
	"ol",
	"blockquote",
	"h1",
	"h2",
	"h3",
	"h4",
	"h5",
	"h6",
	"section",
)


def _html_words(html):
	"""An HTML message's words, a line for each block: never its pictures (a tracking pixel's address), its scripts,
	its styles, nor the addresses of its links, only their words (the post links to the message itself)."""
	from bs4 import BeautifulSoup

	soup = BeautifulSoup(html, "html.parser")
	for tag in soup(["script", "style", "head", "title", "img"]):
		tag.decompose()
	for br in soup.find_all("br"):
		br.replace_with("\n")
	for tag in soup.find_all(_BLOCKS):
		tag.insert_after("\n")
	return soup.get_text()


def _content(message, note, address, email_id):
	"""The post's HTML: the person's words, then the message quoted (subject, sender, date, the start of its text),
	then the link that opens it in NeoMail. Every word of the message and of the person is escaped."""

	def lines(text):
		return "<br>".join(escape_html(line) for line in str(text).split("\n"))

	subject = str(message.get("subject") or "").strip() or _("(no subject)")
	sender = str(message.get("from") or "").strip()
	date = _date(message)
	link = get_url("/app/neomail?" + urlencode({"account": address, "email": email_id}))
	parts = []
	note = str(note or "").strip()[:MAX_NOTE]
	if note:
		parts.append(f"<p>{lines(note)}</p>")
	quoted = [f"<p><strong>{escape_html(subject)}</strong></p>"]
	about = [_("From: {0}").format(sender)] if sender else []
	if date:
		about.append(_("Date: {0}").format(date))
	if about:
		quoted.append("<p>" + "<br>".join(escape_html(line) for line in about) + "</p>")
	text = _text(message)
	if text:
		quoted.append("".join(f"<p>{lines(block)}</p>" for block in text.split("\n\n")))
	parts.append("<blockquote>" + "".join(quoted) + "</blockquote>")
	parts.append(f'<p><a href="{escape_html(link)}">{escape_html(_("Open in NeoMail"))}</a></p>')
	return "".join(parts)


def _attachments(message):
	"""The message's attachments as private files of the person's, for Raven to attach to the post: ([{file_url,
	file_size}], how many were left out). Not the pictures its HTML shows inline; MAX_FILES at most, each MAX_FILE and
	all MAX_FILES_TOTAL at most; one the site refuses (Frappe checks a PDF, for one) is left out, and logged."""
	files, left_out, total = [], 0, 0
	for part in message.iter_attachments():
		if part.get_content_disposition() != "attachment" and part.get("Content-ID"):
			continue
		try:
			data = part.get_payload(decode=True) or b""
		except Exception:
			data = b""
		size = len(data)
		if not size or len(files) >= MAX_FILES or size > MAX_FILE or total + size > MAX_FILES_TOTAL:
			left_out += 1
			continue
		name = _file_name(part.get_filename())
		try:
			saved = frappe.get_doc({"doctype": "File", "file_name": name, "content": data, "is_private": 1})
			saved.insert()
		except Exception:
			frappe.log_error("NeoMail share: an attachment was not saved", frappe.get_traceback())
			left_out += 1
			continue
		files.append({"file_url": saved.file_url, "file_size": saved.file_size or size})
		total += size
	return files, left_out


def _file_name(name):
	"""An attachment's name, as a file of the site may be called: its last part, without what a path or a header
	could slip in, MAX_FILE_NAME characters at most; « attachment » when it has none."""
	name = str(name or "").replace("\\", "/").split("/")[-1]
	name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(" .")
	if len(name) > MAX_FILE_NAME:
		stem, dot, extension = name.rpartition(".")
		name = (
			(stem[: MAX_FILE_NAME - len(extension) - 1] + dot + extension)
			if dot and len(extension) <= 10
			else name[:MAX_FILE_NAME]
		)
	return name or "attachment"
