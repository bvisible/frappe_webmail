# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The /neomail address: NeoMail (the browser build of our MailCraft fork, under the name the person reads) with Nora, on
the person's own mailboxes. The former /mailcraft address redirects here (hooks.py, website_redirects).

Off unless the site's configuration says `mailcraft_trial: 1` (osiris, while the plan that brings Nora into MailCraft
is tried, maintenance#1629 and #1630): everywhere else the address does not exist. The page frames the browser build
of MailCraft (bvisible/mailcraft) that the Suite's installer puts next to the editors (suite/public/craft/mailcraft).
It hands the build the person's mailboxes (owned or shared, as the webmail lists them), each with its JMAP session on
the facade (mailcraft_jmap.py) and a token for it; without any mailbox, or with `?sample`, MailCraft opens its sample
mailbox. It hands the person's language too: MailCraft draws in it unless one is chosen in its settings (the browser's
language is often not the desk's). The build reaches Nora with this page's session (it reads this page's CSRF token, same origin) and Nora's
methods apply their own rights. The desk's people only: a visitor signs in first, a portal account is refused, as for
the webmail.
"""

import frappe
from frappe import _

BUILD = "/assets/suite/craft/mailcraft/index.html"
ROUTE = "/neomail"
# The name the person reads; the build, a fork of MailCraft, shows it in place of its own.
PRODUCT = "NeoMail"

no_cache = 1


def get_context(context):
	if not frappe.conf.get("mailcraft_trial"):
		raise frappe.PageDoesNotExistError
	if frappe.session.user == "Guest":
		_redirect("/login?redirect-to=" + ROUTE)
	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		frappe.throw(
			_("Webmail is part of the desk: your account has no access to it."), frappe.PermissionError
		)
	# The framed build's calls to Nora carry this session's token: make sure the session has one.
	frappe.sessions.get_csrf_token()
	context.no_cache = 1
	context.lang = frappe.local.lang or "en"
	mailboxes = [] if "sample" in frappe.form_dict else host_mailboxes()
	# The person's mailboxes, through the JMAP facade (maintenance#1630); without any, the sample mailbox. Nora where the
	# instance has her: elsewhere each of her calls would fail.
	query = ([] if mailboxes else ["sample"]) + (["nora"] if nora_installed() else [])
	context.build_url = BUILD + ("?" + "&".join(query) if query else "")
	context.host_json = _script_json({"accounts": mailboxes, "language": context.lang, "product": PRODUCT})


def nora_installed():
	"""Whether the instance has Nora, whom NeoMail's band calls."""
	return "nora" in frappe.get_installed_apps()


def host_mailboxes(bearer=None):
	"""The mailboxes of the person (owned or shared, enabled) as MailCraft opens them: the JMAP session of each, and
	a token good for the facade only, twelve hours at most, that MailCraft keeps in the tab's memory. It is bound to
	the desk session of the request, or to Neodesk's OAuth bearer token (`bearer`, mailcraft_jmap.hand_over).

	Each carries the signature MailCraft puts under a message written from it (`signature`, {html, text}, left out
	without any): the mailbox's own (its Webmail Account's default signature, when it is one of its owner's), else
	the person's default one, the one the webmail puts under every message."""
	from urllib.parse import quote

	from frappe_webmail.mailcraft_jmap import give_token
	from frappe_webmail.webmail_api import get_accounts

	accounts = get_accounts()
	if not accounts:
		return []
	token = give_token(bearer=bearer)
	base = frappe.utils.get_url() + "/api/method/frappe_webmail.mailcraft_jmap.session?account="
	# The person's own default signature, the one the webmail puts under every message: read and turned once.
	own = handed_signature(
		frappe.db.get_value("Email Signature", {"user": frappe.session.user, "is_default": 1}, "content")
	)
	mailboxes = []
	for a in accounts:
		mailbox = {
			"email": a["email"],
			"name": a.get("sender_name") or "",
			"session": base + quote(a["name"], safe=""),
			"username": a["email"],
			"secret": token,
			"scheme": "bearer",
		}
		signature = _mailbox_signature(a) or own
		if signature:
			mailbox["signature"] = signature
		mailboxes.append(mailbox)
	return mailboxes


def _mailbox_signature(account):
	"""The signature a mailbox names as its own, handed over, when it is one of its owner's. Read below the rights: it goes
	under every message sent from the mailbox, by whoever it is shared with. But the Link can be pointed at anyone's
	signature (Frappe checks only that it exists, and a mailbox is written by its owner and those it is shared with):
	another person's stays theirs."""
	if not account.get("default_signature") or not account.get("user"):
		return None
	html = frappe.db.get_value(
		"Email Signature", {"name": account["default_signature"], "user": account["user"]}, "content"
	)
	return handed_signature(html)


# A signature is a few lines and perhaps a logo. A bigger one goes as its text alone (the page carries every mailbox's
# whole), its text no longer than this, and a source bigger still is not read at all. Neodesk keeps to the same sizes
# (neoffice-mobile, desktop/src/editors/mail.js).
MAX_SIGNATURE_HTML = 200_000
MAX_SIGNATURE_TEXT = 10_000
MAX_SIGNATURE_SOURCE = 1_000_000
# The elements that start and end a line when a signature is read as text.
_LINE_ELEMENTS = frozenset(
	("p", "div", "li", "ul", "ol", "tr", "table", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6")
)


def handed_signature(html):
	"""A signature as MailCraft takes it, {html, text}: None when there is nothing to show (no words, no picture).

	The HTML is the signature as stored: a picture in it is a file of the instance (Frappe saves a pasted one under
	/private/files/), which only the instance's own pages can show. MailCraft writes the text."""
	html = (html or "").strip()
	if not html or len(html) > MAX_SIGNATURE_SOURCE:
		return None
	try:
		text = signature_text(html)[:MAX_SIGNATURE_TEXT].rstrip()
	except Exception:
		# A signature never keeps the mailboxes from opening: one that cannot be read is left out, and the log says why.
		frappe.log_error("NeoMail: a signature could not be read as text", frappe.get_traceback())
		return None
	if len(html) > MAX_SIGNATURE_HTML:
		html = ""
	if not text and "<img" not in html.lower():
		return None
	return {"html": html, "text": text}


def signature_text(html):
	"""A signature read as text, as MailCraft writes it under `-- `: its lines as they show (a paragraph, a line break,
	a table's row each make one), links by their words and their address when the words do not say it, no pictures."""
	import re

	from bs4 import BeautifulSoup, NavigableString, Tag

	lines = [""]

	def end_line():
		# One line break, whatever the blocks within blocks and the source's spacing between them. A non-breaking space
		# is something on its line: a paragraph of one alone (Word's and Outlook's spacing) shows as an empty line.
		if lines[-1].strip(" "):
			lines.append("")

	# Walked with a stack of its own rather than by recursion: no nesting, however deep, can exhaust Python's.
	stack = [(BeautifulSoup(html or "", "html.parser"), False)]
	while stack:
		node, after = stack.pop()
		if after:
			if node.name in _LINE_ELEMENTS:
				end_line()
			elif node.name in ("td", "th"):
				lines[-1] += " "
			elif node.name == "a":
				words = node.get_text(" ", strip=True)
				address = (node.get("href") or "").strip()
				if words and address.lower().startswith(("http://", "https://")):
					if _bare_address(address) not in _bare_address(words):
						lines[-1] += f" <{address}>"
		elif type(node) is NavigableString:
			# Spaces and line breaks of the HTML source show as one space; a non-breaking one stays until the end.
			lines[-1] += re.sub(r"[^\S\xa0]+", " ", str(node))
		elif isinstance(node, Tag) and node.name not in ("style", "script", "head", "title", "img"):
			if node.name == "br":
				lines.append("")
				continue
			if node.name in _LINE_ELEMENTS:
				end_line()
			stack.append((node, True))
			stack.extend((child, False) for child in reversed(node.contents))
	lines = [" ".join(line.split()) for line in lines]
	while lines and not lines[0]:
		lines.pop(0)
	while lines and not lines[-1]:
		lines.pop()
	return "\n".join(lines)


def _bare_address(address):
	"""An address as one reads it: no scheme, no www., no final slash, any case."""
	import re

	return re.sub(r"^[a-z]+://(www\.)?|^www\.", "", address.strip().lower()).rstrip("/")


def _script_json(data):
	"""JSON safe inside a <script> element."""
	import json

	return json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _redirect(location):
	frappe.local.flags.redirect_location = location
	redirect = frappe.Redirect()
	# A 302: a cached 301 would keep sending browsers here if the address ever changes.
	redirect.http_status_code = 302
	raise redirect
