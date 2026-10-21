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
language is often not the desk's), and where the signatures of those mailboxes are written (`signatures`), the address
MailCraft's own signatures name for them: they come from here, and what MailCraft would keep of them would be replaced
by the page's at the next visit. The build reaches Nora with this page's session (it reads this page's CSRF token, same origin) and Nora's
methods apply their own rights. The desk's people only: a visitor signs in first, a portal account is refused, as for
the webmail.

The desk's page /app/neomail (page/neomail) frames the same build with the same handover (`handover`), and both pages
give the build the same functions (public/js/neomail_host.js).
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
# Where the person writes their signatures and sees the company's: the webmail's signatures, opened by its address
# (Webmail.vue, applyUrlIntent).
SIGNATURES = "/app/webmail?signatures=1"

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
	desk_people_only()
	# The framed build's calls to Nora carry this session's token: make sure the session has one.
	frappe.sessions.get_csrf_token()
	context.no_cache = 1
	framed = handover(sample="sample" in frappe.form_dict, build=frappe.form_dict.get("build"))
	context.lang = framed["host"]["language"]
	context.no_mailbox = framed["no_mailbox"]
	context.build_url = framed["build_url"]
	context.host_json = _script_json(framed["host"])


def desk_people_only():
	"""The desk's people only, as for the webmail: a portal account (and a visitor) is refused."""
	if frappe.session.user == "Guest" or (
		frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User"
	):
		frappe.throw(
			_("Webmail is part of the desk: your account has no access to it."), frappe.PermissionError
		)


def handover(sample=False, build=None):
	"""What a page that frames NeoMail gives it, for the session's person: the build's address (`build_url`), what the
	build reads from the page that frames it (`host`: the mailboxes, the language, the product's name and where the
	signatures are written) and whether the person has no mailbox (`no_mailbox`: the page then says so and frames
	nothing). /neomail and the desk's page /app/neomail (page/neomail) both make it here.

	The person's mailboxes go through the JMAP facade (maintenance#1630). Without any, the page says so (made-up mail
	would pass for theirs); `sample` opens the sample mailbox, for a demonstration. Nora where the instance has her:
	elsewhere each of her calls would fail. `build` "ucs" frames the trial build where it is installed."""
	language = frappe.local.lang or "en"
	mailboxes = [] if sample else host_mailboxes()
	query = (["sample"] if sample else []) + (["nora"] if nora_installed() else [])
	# The person signed in, named as the Drive names them to the document editors: NeoMail's account button shows their
	# initials, the same as everywhere else.
	author = frappe.utils.get_fullname(frappe.session.user)
	if author:
		query.append("author=" + quote(author, safe=""))
	trial = build == "ucs" and build_installed(TRIAL)
	return {
		"build_url": (TRIAL_BUILD if trial else BUILD) + ("?" + "&".join(query) if query else ""),
		"host": {
			"accounts": mailboxes,
			"language": language,
			"product": PRODUCT,
			"signatures": signatures_url(),
		},
		"no_mailbox": not mailboxes and not sample,
	}


def signatures_url():
	"""The whole address of the webmail's signatures on this instance: Neodesk, which opens it too, is no page of it."""
	return frappe.utils.get_url(SIGNATURES)


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
			# The picture handed by its bytes leaves the HTML, where MailCraft would keep its description as words; so
			# does one MailCraft has no place for (pictures_left_out).
			for src in pictures_left_out(chosen, picture):
				signature["html"] = without_picture(signature["html"], src)
			if picture:
				signature.update(picture)
			# Every picture in the order it is read, for a page that places more than one (the logo under the words of
			# "Photo left", the banner under the signature); `logo` and `layout` stay for the builds that place one.
			handed = []
			pictures = handed_pictures(chosen, memo, handed)
			if pictures:
				signature["pictures"] = pictures
				# What a build that places every picture it is handed reads: the HTML without any of them, which it would
				# otherwise show a second time by its description (the banner's as a link). `html` stays as it was for
				# the builds that place one picture, where the banner's words are what shows of it.
				placed = signature["html"]
				for src in handed:
					placed = without_picture(placed, src)
				signature["placed_html"] = placed
			mailbox["signature"] = signature
		mailboxes.append(mailbox)
	return mailboxes


# How a company template places its picture, as MailCraft's signatures say it (`signature.layout`): beside the words, a
# two-cell table when sent, or above them. The other layouts draw no picture. "Photo left" hands the person's photo.
PICTURE_LAYOUTS = {"Logo left": "pictureLeft", "Logo above": "pictureAbove", "Photo left": "pictureLeft"}
# The layouts whose picture handed is the person's photo (signatures.WITH_PHOTO), not the logo
PHOTO_LAYOUTS = frozenset(("Photo left",))
# The most one picture of a signature may weigh in MailCraft (crates/model/src/signature.rs, MAX_PICTURE_BYTES).
MAX_PICTURE_BYTES = 256 * 1024
# The kinds of picture MailCraft keeps in a signature, by their first bytes.
_PICTURE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


def handed_picture(chosen, memo):
	"""The picture of a company signature as MailCraft keeps a signature's pictures, {logo: {data, name, alt, width},
	layout}: its bytes in base64, its file's name, its description and the width the template gives it, and its place.
	MailCraft takes the words of the HTML and leaves its pictures out (its `signature.set`); this hands it the picture
	itself, read from the instance's files: the logo, or in "Photo left" the person's photo (there only when they agreed
	to show it), under the same name, MailCraft keeping one picture in its place. None for a signature without one (a
	person's own, a layout without a picture, a person who shows no photo), for a picture that is no file of the
	instance (MailCraft fetches nothing for a signature), and for a file it would not keep: not a PNG, JPEG or GIF by its
	own bytes, or heavier than MAX_PICTURE_BYTES."""
	import base64
	import os
	from urllib.parse import unquote

	layout = PICTURE_LAYOUTS.get(chosen.get("layout"))
	logo = chosen.get("photo") if chosen.get("layout") in PHOTO_LAYOUTS else chosen.get("logo")
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


# The most the pictures of one signature may weigh together in MailCraft (crates/model/src/signature.rs,
# MAX_PICTURES_BYTES).
MAX_PICTURES_BYTES = 512 * 1024


def handed_pictures(chosen, memo, handed=None):
	"""The pictures of a company signature in the order they are read, by their bytes as MailCraft keeps a signature's
	pictures, for a page that places more than one: [{data, name, alt, width, lead?, href?}]. "Photo left": the
	person's photo beside the words (`lead`), then the company's logo under them; without a photo (the person did not
	agree), the logo alone, under the words. "Logo left" and "Logo above": the logo, beside or above them (`lead`).
	Whatever the layout, the template's banner last, under the signature, with the https address it leads to (`href`).
	None for a signature with none of these (another layout without a banner, a person's own signature), and for
	pictures MailCraft would not keep (handed_picture says which); one that would make them weigh more than
	MAX_PICTURES_BYTES together is left out. The address of each picture handed is added to `handed`, when given."""
	import base64
	import os
	from urllib.parse import unquote

	layout = chosen.get("layout")
	banner = [(chosen.get("banner"), False)]
	if layout in PHOTO_LAYOUTS:
		wanted = [(chosen.get("photo"), True), (chosen.get("logo"), False), *banner]
	elif layout in PICTURE_LAYOUTS:
		wanted = [(chosen.get("logo"), True), *banner]
	elif isinstance(chosen.get("banner"), dict):
		wanted = banner
	else:
		return None
	pictures, total = [], 0
	for picture, lead in wanted:
		if not isinstance(picture, dict) or not picture.get("src"):
			continue
		key = ("picture", picture["src"])
		if key not in memo:
			memo[key] = _picture_of(picture["src"])
		data = memo[key]
		if not data or total + len(data) > MAX_PICTURES_BYTES:
			continue
		total += len(data)
		name = os.path.basename(unquote(picture["src"].split("?", 1)[0])) or "picture"
		handed_item = {
			"data": base64.b64encode(data).decode("ascii"),
			"name": name[:100],
			"alt": picture.get("alt") or "",
			"width": picture.get("width"),
		}
		# Only the first picture read can be beside or above the words
		if lead and not pictures:
			handed_item["lead"] = True
		# The banner's link, an https address (signatures._banner_of)
		if picture.get("href"):
			handed_item["href"] = picture["href"]
		pictures.append(handed_item)
		if handed is not None:
			handed.append(picture["src"])
	return pictures or None


def pictures_left_out(chosen, handed):
	"""The addresses of the pictures of a signature that leave the HTML a page hands MailCraft: the one it hands by its
	bytes (`handed`), which MailCraft would otherwise show twice, the second time by its description; and in "Photo left"
	the photo and the logo, whether handed or not: MailCraft keeps a single picture, beside or above the words, and would
	write the logo under the details as its words (the company's name, a second time) and a photo it was not handed as
	the person's name. A banner stays: its description is a link to where it leads, which is what MailCraft can show of it."""
	sources = []
	if chosen.get("layout") in PHOTO_LAYOUTS:
		sources = [(chosen.get(item) or {}).get("src") for item in ("photo", "logo")]
	elif handed:
		sources = [(chosen.get("logo") or {}).get("src")]
	return [src for src in sources if src]


def without_picture(html, src):
	"""`html` without the pictures whose address is `src`: the logo a page hands MailCraft by its bytes, which MailCraft
	would otherwise show twice, by its description after the picture itself."""
	if not html or "<img" not in html.lower():
		return html
	from bs4 import BeautifulSoup

	tree = BeautifulSoup(html, "html.parser")
	for image in tree.find_all("img"):
		if (image.get("src") or "").strip() == src:
			link = image.find_parent("a")
			image.decompose()
			# A link that held nothing but the picture (the banner's) goes with it: empty, it would be a link to nowhere
			if link is not None and not link.get_text(strip=True) and not link.find("img"):
				link.decompose()
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
