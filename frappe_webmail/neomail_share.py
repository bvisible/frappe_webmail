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
"""

from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

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


def offered(user=None):
	"""Whether a message can be shared in Synk by `user` (the session's): one of the desk's people for whom the page
	/app/neomail is offered, on a site with Raven, holding its role."""
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

	user = user or frappe.session.user
	return (
		desk.in_desk_for(user)
		and "raven" in frappe.get_installed_apps()
		and RAVEN_ROLE in frappe.get_roles(user)
	)


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
	from frappe_webmail import mailcraft_jmap as jmap
	from frappe_webmail import webmail_api as webmail
	from frappe_webmail.frappe_webmail.page.neomail import neomail as desk

	_gate()
	mailbox = webmail.get_account(desk._mailbox_name(account))
	if str(email or "")[:1] != "E" or not jmap._message_of(email):
		frappe.throw(_("This message cannot be found."))
	raw = jmap._source(mailbox, email)
	if not raw:
		frappe.throw(_("This message is no longer in its folder: refresh the list and try again."))
	if len(raw) > MAX_SOURCE:
		frappe.throw(_("This message is too large to be shared."))
	message = message_from_bytes(raw, policy=policy.default)
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
	"""The message's date as the site writes it, in the site's time zone; empty when it has none that can be read."""
	from zoneinfo import ZoneInfo

	from frappe.utils import format_datetime, get_system_timezone

	try:
		moment = parsedate_to_datetime(str(message.get("date") or ""))
	except (TypeError, ValueError, IndexError):
		return ""
	if moment is None:
		return ""
	if moment.tzinfo:
		moment = moment.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	return format_datetime(moment)


def _text(message):
	"""The start of the message's text: its plain text, or its HTML read as text, never as HTML; MAX_TEXT
	characters at most, cut at a word, its blank lines kept to one."""
	from frappe.core.utils import html2text

	try:
		body = message.get_body(preferencelist=("plain", "html"))
		words = body.get_content() if body is not None else ""
		if body is not None and body.get_content_subtype() == "html":
			# The words of its links, not their addresses: the post links to the message itself.
			words = html2text(words, strip_links=True, wrap=False)
	except Exception:
		return ""
	lines, blank = [], False
	for line in str(words or "").replace("\r\n", "\n").split("\n"):
		line = line.rstrip()
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
