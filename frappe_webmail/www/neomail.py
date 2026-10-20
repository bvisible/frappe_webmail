# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The /neomail address: NeoMail (the browser build of our MailCraft fork, under the name the person reads) with Nora, on
the person's own mailboxes. The former /mailcraft address redirects here (hooks.py, website_redirects).

On wherever the browser build of MailCraft (bvisible/mailcraft) is installed, unless the site's configuration switches
NeoMail off (`neomail_disabled: 1`): elsewhere the address does not exist. The page frames that build, which the
Suite's installer puts next to the editors (suite/public/craft/mailcraft) as craft_editors.json pins it. It was on
osiris only (`mailcraft_trial`) while the plan that brings Nora into MailCraft was tried (maintenance#1629, #1630).
It hands the build the person's mailboxes (owned or shared, as the webmail lists them), each with its JMAP session on
the facade (mailcraft_jmap.py) and a token for it; without any mailbox, or with `?sample`, MailCraft opens its sample
mailbox. It hands the person's language too: MailCraft draws in it unless one is chosen in its settings (the browser's
language is often not the desk's). The build reaches Nora with this page's session (it reads this page's CSRF token, same origin) and Nora's
methods apply their own rights. The desk's people only: a visitor signs in first, a portal account is refused, as for
the webmail.
"""

import os
from urllib.parse import quote

import frappe
from frappe import _

from frappe_webmail.mailcraft_jmap import neomail_enabled

BUILD = "/assets/suite/craft/mailcraft/index.html"
# A second build tried beside the one in service, opened by `?build=ucs`: NeoMail on its new base, which a trial
# instance installs by hand next to the other (suite/public/craft/mailcraft-ucs). Where it is not installed the
# parameter changes nothing.
TRIAL = "mailcraft-ucs"
TRIAL_BUILD = f"/assets/suite/craft/{TRIAL}/index.html"
ROUTE = "/neomail"
# The name the person reads; the build, a fork of MailCraft, shows it in place of its own.
PRODUCT = "NeoMail"

no_cache = 1


def build_installed(folder="mailcraft"):
	"""The browser build is where the page frames it: the Suite's installer put it there (craft_editors.json), or, for
	the trial build, the instance's administrator did."""
	if "suite" not in frappe.get_installed_apps():
		return False
	return os.path.isfile(frappe.get_app_path("suite", "public", "craft", folder, "index.html"))


def available():
	"""NeoMail can be opened here: it is on, and its build is installed."""
	return neomail_enabled() and build_installed()


def get_context(context):
	if not available():
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
	sample = "sample" in frappe.form_dict
	mailboxes = [] if sample else host_mailboxes()
	# The person's mailboxes, through the JMAP facade (maintenance#1630). Without any, the page says so (made-up mail would
	# pass for theirs); `?sample` opens the sample mailbox, for a demonstration. Nora where the instance has her: elsewhere
	# each of her calls would fail.
	context.no_mailbox = not mailboxes and not sample
	query = (["sample"] if sample else []) + (["nora"] if nora_installed() else [])
	# The person signed in, named as the Drive names them to the document editors: NeoMail's account button shows their
	# initials, the same as everywhere else.
	author = frappe.utils.get_fullname(frappe.session.user)
	if author:
		query.append("author=" + quote(author, safe=""))
	trial = frappe.form_dict.get("build") == "ucs" and build_installed(TRIAL)
	context.build_url = (TRIAL_BUILD if trial else BUILD) + ("?" + "&".join(query) if query else "")
	context.host_json = _script_json({"accounts": mailboxes, "language": context.lang, "product": PRODUCT})


def nora_installed():
	"""Whether the instance has Nora, whom NeoMail's band calls."""
	return "nora" in frappe.get_installed_apps()


def host_mailboxes(bearer=None):
	"""The mailboxes of the person (owned or shared, enabled) as MailCraft opens them: the JMAP session of each, and
	a token good for the facade only, twelve hours at most, that MailCraft keeps in the tab's memory. It is bound to
	the desk session of the request, or to Neodesk's OAuth bearer token (`bearer`, mailcraft_jmap.hand_over).

	Each carries the signature MailCraft puts under a message written from it (`signature`, {html, text}, left out
	without any): the company's, written for the person, when an Email Signature Template applies to them and does not
	leave them their own; else the mailbox's own (its Webmail Account's default signature, when it is one of its
	owner's), else the person's default one, the one the webmail puts under every message (signatures.signature_for)."""
	from urllib.parse import quote

	from frappe_webmail.mailcraft_jmap import give_token
	from frappe_webmail.signatures import signature_for
	from frappe_webmail.webmail_api import get_accounts

	accounts = get_accounts()
	if not accounts:
		return []
	token = give_token(bearer=bearer)
	base = frappe.utils.get_url() + "/api/method/frappe_webmail.mailcraft_jmap.session?account="
	mailboxes = []
	# The template and the person are worked out once for every mailbox of the page (signatures.signature_for)
	memo = {}
	for a in accounts:
		mailbox = {
			"email": a["email"],
			"name": a.get("sender_name") or "",
			"session": base + quote(a["name"], safe=""),
			"username": a["email"],
			"secret": token,
			"scheme": "bearer",
		}
		chosen = signature_for(frappe.session.user, a, memo) or {}
		signature = handed_signature(chosen.get("html"), chosen.get("text"))
		if signature:
			picture = handed_picture(chosen, memo)
			if picture:
				# The logo goes by its bytes: its picture leaves the HTML, where MailCraft would keep its description as words.
				signature["html"] = without_picture(signature["html"], chosen["logo"]["src"])
				signature.update(picture)
			mailbox["signature"] = signature
		mailboxes.append(mailbox)
	return mailboxes


# How a company template places its logo, as MailCraft's signatures say it (`signature.layout`): beside the words, a
# two-cell table when sent, or above them. The other layouts draw no logo.
PICTURE_LAYOUTS = {"Logo left": "pictureLeft", "Logo above": "pictureAbove"}
# The most one picture of a signature may weigh in MailCraft (crates/model/src/signature.rs, MAX_PICTURE_BYTES).
MAX_PICTURE_BYTES = 256 * 1024
# The kinds of picture MailCraft keeps in a signature, by their first bytes.
_PICTURE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


def handed_picture(chosen, memo):
	"""The logo of a company signature as MailCraft keeps a signature's pictures, {logo: {data, name, alt, width},
	layout}: its bytes in base64, its file's name, its description and the width the template gives it, and its place.
	MailCraft takes the words of the HTML and leaves its pictures out (its `signature.set`); this hands it the logo
	itself, read from the instance's files. None for a signature without one (a person's own, a layout without a logo),
	for a logo that is no file of the instance (MailCraft fetches nothing for a signature), and for a file it would not
	keep: not a PNG, JPEG or GIF by its own bytes, or heavier than MAX_PICTURE_BYTES."""
	import base64
	import os
	from urllib.parse import unquote

	logo, layout = chosen.get("logo"), PICTURE_LAYOUTS.get(chosen.get("layout"))
	if not isinstance(logo, dict) or not logo.get("src") or not layout:
		return None
	key = ("picture", logo["src"])
	if key not in memo:
		memo[key] = _picture_of(logo["src"])
	data = memo[key]
	if not data:
		return None
	name = os.path.basename(unquote(logo["src"].split("?", 1)[0])) or "logo"
	return {
		"logo": {
			"data": base64.b64encode(data).decode("ascii"),
			"name": name[:100],
			"alt": logo.get("alt") or "",
			"width": logo.get("width"),
		},
		"layout": layout,
	}


def without_picture(html, src):
	"""`html` without the pictures whose address is `src`: the logo a page hands MailCraft by its bytes, which MailCraft
	would otherwise show twice, by its description after the picture itself."""
	if not html or "<img" not in html.lower():
		return html
	from bs4 import BeautifulSoup

	tree = BeautifulSoup(html, "html.parser")
	for image in tree.find_all("img"):
		if (image.get("src") or "").strip() == src:
			image.decompose()
	return str(tree)


def _picture_of(src):
	"""The bytes of a file of the instance that a logo's address names, when MailCraft would keep them; None else."""
	from frappe_webmail.signatures import _file_on_disk

	path = _file_on_disk(src)
	if not path:
		return None
	try:
		with open(path, "rb") as picture:
			data = picture.read(MAX_PICTURE_BYTES + 1)
	except OSError:
		return None
	if len(data) > MAX_PICTURE_BYTES or not data.startswith(_PICTURE_MAGIC):
		return None
	return data


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


def handed_signature(html, text=None):
	"""A signature as MailCraft takes it, {html, text}: None when there is nothing to show (no words, no picture).

	The HTML is the signature as stored: a picture in it is a file of the instance (Frappe saves a pasted one under
	/private/files/), which only the instance's own pages can show. MailCraft writes the text: `text` when the signature
	comes with its own (the company's, written line for line), else the HTML read as text."""
	html = (html or "").strip()
	if not html or len(html) > MAX_SIGNATURE_SOURCE:
		return None
	try:
		text = (text.strip() if isinstance(text, str) and text.strip() else signature_text(html))[
			:MAX_SIGNATURE_TEXT
		].rstrip()
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
