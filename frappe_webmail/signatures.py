# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The company's signature: one template, set by a manager (Email Signature Template), written for each person from what
the instance knows of them (their User, their Employee, their Company).

`signature_for` is what the composers ask: the signature a person gets under a message, as {html, text}. It is the
template's, unless the template lets people keep their own (`allow_personal`) and the person wrote one that shows
something, or no template applies to them: then it is the signature the webmail has always given (their own default
one, or the mailbox's own). `template_for` finds the template that applies, the most specific first: a department's,
then a company's, then everyone's. `render` writes a template for a person.

The HTML is meant for mail clients, which drop what they do not know: tables to place things, a style written on each
element, no <style> block, no class, no margin on a table, no flex or grid, a picture with its width and, when its file
says it, its height. It keeps to the tags, attributes and CSS properties that the cleaning of a message sent keeps
(webmail_api.send_email, EMAIL_CSS_PROPERTIES), so that what the form shows is what leaves. A logo is the company's file
as stored: the message sent turns a file of the instance into a part of the message (inline_images.files_inlined), and
the signature never writes a `data:` image. Every value is escaped (the Jinja environment below escapes by default) and
no field is ever taken as HTML. Each line of text is a block of its own: the desk's composer (TipTap) keeps neither
tables nor styles nor the size of a picture, and reads the lines as paragraphs.

The layouts are the files of templates/signatures, each one more entry of LAYOUTS drawing the same card and look. "Photo
left" draws the person's photo, and only for a person who agreed to show it (Email Signature Preference, which they set
themselves and can take back; signature_photos.py makes the reduced copy that is drawn). The person also chooses whether
their mobile is shown. A banner (a link when it has an https address) goes under the signature whatever its layout: the
layout is drawn as it is, the banner on a row under it (_banner.html, `_draw`). The banner is a public picture of the
instance, which every composer shows; the photo a private file, which the person's own composer shows and the message
sent carries as its own part (inline_images.sender_photo).
"""

import os
import re
from functools import lru_cache
from html import unescape
from urllib.parse import unquote, urlsplit

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

# The layouts, by the name the template's Select gives them, and the file that draws each (templates/signatures).
LAYOUTS = {
	"Text only": "text_only.html",
	"Logo left": "logo_left.html",
	"Logo above": "logo_above.html",
	"Compact": "compact.html",
	"Photo left": "photo_left.html",
}
DEFAULT_LAYOUT = "Text only"
# The layouts that have a place for the logo (the others never fetch it); Photo left draws it under the details
WITH_LOGO = frozenset(("Logo left", "Logo above", "Photo left"))
# The layouts that have a place for the person's photo
WITH_PHOTO = frozenset(("Photo left",))

# The fonts of the Select, each with the ones a client falls back on (no quote needed: CSS takes a name of words as is)
FONTS = {
	"Arial": "Arial,Helvetica,sans-serif",
	"Helvetica": "Helvetica,Arial,sans-serif",
	"Verdana": "Verdana,Geneva,sans-serif",
	"Georgia": "Georgia,Times New Roman,serif",
	"Tahoma": "Tahoma,Geneva,sans-serif",
	"Trebuchet MS": "Trebuchet MS,Helvetica,sans-serif",
}
DEFAULT_FONT = "Arial"
# A neutral dark blue
DEFAULT_ACCENT = "#1f3a5f"
INK = "#333333"
MUTED = "#6b7280"
FONT_SIZE = (11, 16)
DEFAULT_FONT_SIZE = 13
LOGO_WIDTH = (60, 240)
DEFAULT_LOGO_WIDTH = 120
# The person's photo: a square of this many pixels (the reduced copy is made at that size, signature_photos.py), drawn
# at it, round where a client keeps rounded corners
PHOTO_SIZE = 96
# The banner's width, in pixels; its height follows its file
BANNER_WIDTH = (200, 600)
DEFAULT_BANNER_WIDTH = 400
# The person's own choices of the company signature: their photo, their mobile (one record per person)
PREFERENCE = "Email Signature Preference"

# The networks of a social link (the child table's Select), shown by their name
NETWORKS = ("LinkedIn", "X", "Facebook", "Instagram", "YouTube", "Website")

# What a signature may say: the template's checks, each with the value it has when the template does not say.
SWITCHES = {
	"show_full_name": 1,
	"show_job_title": 1,
	"show_department": 0,
	"show_phone": 1,
	# Often a private number (the Employee's cell number): shown only when the company wants it
	"show_mobile": 0,
	"show_email": 1,
	"show_website": 1,
	"show_company_name": 1,
	"show_company_address": 0,
	"show_logo": 1,
	# The company wants photos; each person's is shown only if they agreed (Email Signature Preference)
	"show_photo": 1,
	"show_social_links": 1,
	"show_disclaimer": 0,
}

# Between templates that apply to a person, the lower rank wins (then the most recently modified)
RANK = {"Department": 0, "Company": 1, "Everyone": 2}

# The files of the instance a logo may be (as Frappe stores them); the rest of the addresses it may be are https ones
INSTANCE_FILES = ("/files/", "/private/files/")
# The longest address: what the URL fields of the template hold (a Data field of 1000 characters, Frappe's most)
MAX_URL = 1000
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
# The scheme an address starts with ('https://'), told from a '://' further in (a query that holds a link)
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
# What an address in a link or a picture may not hold: spaces, quotes, angle brackets and control characters
_UNSAFE_IN_URL = re.compile(r"[\s<>\"'\x00-\x1f\x7f]")
_MAIL_ADDRESS = re.compile(r"[^\s@<>\"',;:()\[\]\\]+@[^\s@<>\"',;:()\[\]\\]+\.[^\s@<>\"',;:()\[\]\\]+")


# What is written ---------------------------------------------------------------------------------------------------


def clean_color(value) -> str | None:
	"""`#rrggbb`, in lower case, from what the Color field holds; None for anything else."""
	if isinstance(value, str) and HEX_COLOR.fullmatch(value.strip()):
		return value.strip().lower()
	return None


def https_url(value) -> str | None:
	"""The address as an `https://` link, None for anything else. It goes into the href of a message others read: no
	other scheme (`javascript:`, `http:`, `data:`), no space, quote or angle bracket, a host."""
	if not isinstance(value, str):
		return None
	value = value.strip()
	if not 8 < len(value) <= MAX_URL or value[:8].lower() != "https://" or _UNSAFE_IN_URL.search(value):
		return None
	try:
		parts = urlsplit(value)
		parts.port  # a port that is not a number raises
	except ValueError:
		return None
	return "https://" + value[8:] if parts.hostname else None


def web_address(value) -> tuple[str, str] | None:
	"""(the words, the link) of a website written as people write one ('example.com', 'www.example.com/shop',
	'https://example.com'); None when it is no web address. Only http and https are links."""
	if not isinstance(value, str) or not value.strip():
		return None
	value = value.strip()
	scheme = _SCHEME.match(value)
	if scheme and scheme.group(0)[:-3].lower() not in ("http", "https"):
		return None
	href = value if scheme else "https://" + value
	if len(href) > MAX_URL or _UNSAFE_IN_URL.search(href):
		return None
	try:
		parts = urlsplit(href)
		parts.port
	except ValueError:
		return None
	# A host with a dot and no credentials: 'mailto:x@y' or 'javascript:alert(1)' would pass as hosts otherwise
	if not parts.hostname or "." not in parts.hostname or "@" in parts.netloc:
		return None
	return re.sub(r"^https?://", "", value, flags=re.IGNORECASE).rstrip("/"), href


def mail_link(address: str) -> str | None:
	"""`mailto:` link of an e-mail address, None when it does not look like one (it is then shown as words only)."""
	return "mailto:" + address if _MAIL_ADDRESS.fullmatch(address) else None


def _one_line(value) -> str:
	"""A value as one line of words: its spaces and line breaks made single spaces."""
	return " ".join(str(value).split()) if value else ""


def _number(value, bounds: tuple[int, int], default: int) -> int:
	"""An Int field as a number between the bounds: the nearest bound when it is outside, the default when it is empty."""
	return max(bounds[0], min(bounds[1], cint(value) or default))


def _instance_file(value) -> str | None:
	"""The address of a file of the instance as Frappe stores it, None for anything else (no `..`, no markup)."""
	if value.startswith(INSTANCE_FILES) and not _UNSAFE_IN_URL.search(value.replace(" ", "")):
		return value if ".." not in value.split("/") else None
	return None


def _plain_instance_file(value) -> str | None:
	"""_instance_file, and no `..` written encoded either (`%2e%2e`): the address of a photo or a banner. (Every read
	of the disk keeps to the files anyway, _file_on_disk; this keeps such an address out of what is drawn.)"""
	src = _instance_file(value.strip()) if isinstance(value, str) else None
	return src if src and ".." not in unquote(src.split("?", 1)[0]).split("/") else None


def _logo_src(value) -> str | None:
	"""A logo's address as the signature writes it: the company's file as stored, or an https address."""
	if not isinstance(value, str):
		return None
	value = value.strip()
	return _instance_file(value) or https_url(value)


def _file_on_disk(src: str) -> str | None:
	"""The path on the disk of a file of the instance that an address names (without a `?fid=` after it), None for any
	other address, and for one that would lead out of the files."""
	for prefix, folder in (("/private/files/", "private"), ("/files/", "public")):
		if src.startswith(prefix):
			try:
				root = os.path.realpath(frappe.get_site_path(folder, "files"))
				path = os.path.realpath(os.path.join(root, unquote(src[len(prefix) :].split("?", 1)[0])))
			except (OSError, ValueError):
				# An address that cannot be a path (a NUL byte, written as %00): no file
				return None
			return path if path.startswith(root + os.sep) else None
	return None


def _logo_height(src: str, width: int) -> int | None:
	"""The height a picture (the logo, the banner) takes at that width, from the proportions of its file, so that a
	client reserves its place before the picture is there. None when they cannot be read (an address elsewhere, a file
	gone from the disk, a vector picture): the width alone then decides, the height following."""
	path = _file_on_disk(src)
	if not path:
		return None
	try:
		from PIL import Image

		with Image.open(path) as picture:
			across, down = picture.size
	except Exception:
		return None
	return max(1, round(width * down / across)) if across and down else None


# The person ---------------------------------------------------------------------------------------------------------


def person_of(user: str) -> frappe._dict:
	"""What the instance knows of a person that a signature may say, one text per item, empty where it knows none.

	The User gives the name, the e-mail address and the numbers; the Employee linked to it (`user_id`), when there is one,
	the job title and the department, and its own values, which win; the Company gives what is the company's (name, logo,
	website, address) and its main number and address for a person with none of their own. The Company is the Employee's,
	else the person's default one. ERPNext's doctypes may be missing from a site: each is read where it exists.

	The person's own choices (preference_of) are honoured: a mobile they hide is not there, and their photo (the reduced
	copy, signature_photos.photo_of) is there only when they agreed to show it."""
	from frappe_webmail import signature_photos

	account = (
		frappe.db.get_value(
			"User",
			user,
			["full_name", "first_name", "last_name", "email", "phone", "mobile_no", "user_image"],
			as_dict=True,
		)
		or frappe._dict()
	)
	employee = _employee_of(user)
	company_name = employee.company or _default_company(user)
	company = _company_of(company_name)
	choices = preference_of(user)
	return frappe._dict(
		user=user,
		name=_one_line(
			employee.employee_name
			or account.full_name
			or " ".join(filter(None, (account.first_name, account.last_name)))
			or user
		),
		job_title=_one_line(employee.designation),
		department=_one_line(_department_name(employee.department)),
		phone=_one_line(account.phone or company.phone_no),
		mobile="" if choices.hide_mobile else _one_line(employee.cell_number or account.mobile_no),
		email=_one_line(employee.company_email or account.email or company.email),
		company_name=_one_line(company.company_name or company_name),
		website=_one_line(company.website),
		address=_one_line(company.address),
		logo=(company.company_logo or "").strip(),
		photo=signature_photos.photo_of(user, choices, employee, account) if choices.photo_allowed else "",
	)


def preference_of(user: str) -> frappe._dict:
	"""The person's own choices of the company signature (their Email Signature Preference): whether they agreed to show
	their photo, whether they hide their mobile, and the reduced copy of their photo with what it was made from. All off
	and empty for a person who made none, and on a site that has not the DocType yet."""
	if user and frappe.db.table_exists(PREFERENCE):
		found = frappe.db.get_value(
			PREFERENCE,
			{"user": user},
			["name", "photo_allowed", "hide_mobile", "photo", "photo_source"],
			as_dict=True,
		)
		if found:
			return found
	return frappe._dict(name=None, photo_allowed=0, hide_mobile=0, photo=None, photo_source=None)


def _employee_of(user: str) -> frappe._dict:
	"""The Employee linked to the user (the latest one still with the company), empty where there is none."""
	if not frappe.db.table_exists("Employee"):
		return frappe._dict()
	return (
		frappe.db.get_value(
			"Employee",
			{"user_id": user, "status": ["!=", "Left"]},
			[
				"name",
				"employee_name",
				"designation",
				"department",
				"cell_number",
				"company_email",
				"company",
				"image",
			],
			as_dict=True,
			order_by="modified desc",
		)
		or frappe._dict()
	)


def _default_company(user: str) -> str | None:
	"""The person's default company, else the site's. (For a person other than the one signed in, Frappe reads the
	signed-in person's user permissions: a preview made as someone else may name another company for them.)"""
	if not frappe.db.table_exists("Company"):
		return None
	return frappe.defaults.get_user_default("Company", user) or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


def _department_name(department: str | None) -> str:
	"""A department as people call it ('Sales', not 'Sales - ABC')."""
	if not department:
		return ""
	return frappe.db.get_value("Department", department, "department_name") or department


def _company_of(name: str | None) -> frappe._dict:
	"""The company's own values: its words, its logo and its address."""
	if not name or not frappe.db.table_exists("Company"):
		return frappe._dict()
	company = frappe.db.get_value(
		"Company", name, ["company_name", "company_logo", "phone_no", "email", "website"], as_dict=True
	)
	if not company:
		return frappe._dict()
	company.address = _company_address(name)
	return company


# The field that keeps a house number apart from its street, where an app of the instance adds it to Address
HOUSE_NUMBER_FIELD = "custom_house_number"


def _company_address(company: str) -> str:
	"""The company's address on one line: the first of the addresses linked to it and marked as its own (a field that
	ERPNext adds to Address), the preferred one first.

	Where Address has a field for the house number, address_line1 holds the street alone: the number is put back after
	it, as the address templates do (a line read as it is would give the street without its number)."""
	meta = frappe.get_meta("Address")
	if not meta.has_field("is_your_company_address"):
		return ""
	fields = ["address_line1", "address_line2", "pincode", "city"]
	if meta.has_field(HOUSE_NUMBER_FIELD):
		fields.append(HOUSE_NUMBER_FIELD)
	rows = frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", "Company"],
			["Dynamic Link", "link_name", "=", company],
			["Address", "is_your_company_address", "=", 1],
			["Address", "disabled", "=", 0],
		],
		fields=fields,
		order_by="is_primary_address DESC, `tabAddress`.creation ASC",
		limit=1,
	)
	if not rows:
		return ""
	row = rows[0]
	street = " ".join(filter(None, (row.address_line1, row.get(HOUSE_NUMBER_FIELD))))
	town = " ".join(filter(None, (row.pincode, row.city)))
	return ", ".join(part for part in (street, row.address_line2, town) if part)


# The template that applies -----------------------------------------------------------------------------------------


def template_for(user: str):
	"""The enabled Email Signature Template that applies to the person, None when none does.

	The most specific first: one for the department of their Employee, then one for their company, then one for
	everyone. Between templates of the same kind, the most recently modified."""
	if not frappe.db.table_exists("Email Signature Template"):
		return None
	# The desk's people only: a portal account writes no mail from the instance and is told nothing of the company
	if frappe.db.get_value("User", user, "user_type") != "System User":
		return None
	candidates = frappe.get_all(
		"Email Signature Template",
		filters={"enabled": 1},
		fields=["name", "applies_to", "company", "department"],
		order_by="modified desc, name asc",
	)
	if not candidates:
		return None
	employee = _employee_of(user)
	departments, company = _departments_above(employee.department), employee.company or _default_company(user)
	fitting = [row for row in candidates if _applies(row, departments, company)]
	if not fitting:
		return None

	# A stable sort: the order of the query (the latest first) stays within each rank, and a department's template
	# comes before the one of a department above it
	def rank(row):
		nearest = departments.index(row.department) if row.applies_to == "Department" else 0
		return (RANK[row.applies_to], nearest)

	fitting.sort(key=rank)
	return frappe.get_doc("Email Signature Template", fitting[0].name)


def _departments_above(department: str | None) -> list[str]:
	"""The person's department and every department above it (Department is a tree), the nearest first: a template for
	a department applies to the departments under it too."""
	if not department:
		return []
	if not frappe.db.table_exists("Department"):
		return [department]
	node = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not node or node.lft is None or node.rgt is None:
		return [department]
	above = frappe.get_all(
		"Department",
		filters={"lft": ["<=", node.lft], "rgt": [">=", node.rgt]},
		order_by="lft desc",
		pluck="name",
	)
	return above or [department]


def _applies(row, departments: list[str], company: str | None) -> bool:
	"""Whether a template (its kind and what it names) is for a person of those departments and that company."""
	if row.applies_to == "Department":
		return bool(row.department) and row.department in departments
	if row.applies_to == "Company":
		return bool(row.company) and row.company == company
	return row.applies_to == "Everyone"


# The signature -----------------------------------------------------------------------------------------------------


def signature_for(user: str, account: dict | None = None, memo: dict | None = None) -> dict | None:
	"""The signature the person gets under their messages, {html, text}; None when they get none.

	The template's, written for them, unless it lets people use their own (`allow_personal`) and they have one that
	shows something, or no template applies to them: then the signature they wrote, as the webmail has always given it,
	the one their mailbox names as its own (`account`, a row of get_accounts) or else their default one. A template
	that has nothing to show for them leaves them their own too.

	A mailbox shared with the person (`account` is someone else's) signs as its owner set it to, when it names a
	signature of its own: a team's card under info@. Without one, the template is written for the mailbox (its name and
	address, the company's number): under a template, it never carries the writer's own signature, job or numbers. With
	no template, the webmail signs as it always has (the writer's default one).

	`memo`, a dict the caller keeps for one request, spares working out the template and the person again for each of
	their mailboxes. A failure is logged once a request and answered as if no template could be read: the mailbox's own
	signature for a shared mailbox, the person's own for theirs, or None. Whoever asks (the composer of the desk,
	NeoMail's page) carries on rather than meets an error."""
	memo = {} if memo is None else memo
	shared = isinstance(account, dict) and account.get("user") not in (None, "", user)
	if not memo.get("failed"):
		try:
			return _signature_for(user, account, memo, shared)
		except Exception:
			memo["failed"] = True
			frappe.log_error("Email signature could not be built", frappe.get_traceback())
	try:
		return mailbox_signature(account) if shared else own_signature(user, account)
	except Exception:
		return None


def _signature_for(user: str, account: dict | None, memo: dict, shared: bool) -> dict | None:
	"""signature_for, failures and all."""
	if shared and (team := mailbox_signature(account)):
		return team
	if "template" not in memo:
		memo["template"] = template_for(user)
	template = memo["template"]
	if template is None:
		return own_signature(user, account)
	# The person's own, when the template lets them keep it: under their own mailboxes, never under a shared one
	if template.allow_personal and not shared:
		own = own_signature(user, account)
		if own and _shows_something(own["html"]):
			return own
	if "person" not in memo:
		memo["person"] = person_of(user)
	person = memo["person"]
	if shared:
		if "company_phone" not in memo:
			memo["company_phone"] = _company_phone(user)
		person = _team_of(person, account, memo["company_phone"])
	key = ("written", tuple(sorted(person.items())))
	if key not in memo:
		memo[key] = render_person(template, person)
	signature = memo[key]
	if signature["html"]:
		return signature
	# A template that has nothing to show leaves a person their own; a shared mailbox has none of its own here
	return None if shared else own_signature(user, account)


def _team_of(person: frappe._dict, account: dict, phone: str) -> frappe._dict:
	"""A shared mailbox as a signature writes it: its name and address, the company's details and its main number
	(`phone`); nothing of the person who writes from it (their job, their department, their numbers, their photo)."""
	return frappe._dict(
		person,
		name=_one_line(account.get("sender_name") or account.get("email")),
		job_title="",
		department="",
		mobile="",
		phone=_one_line(phone),
		email=_one_line(account.get("email")),
		photo="",
	)


def company_of_user(user: str) -> str | None:
	"""The person's company: their Employee's, else their default one (None where there is none). A person without an
	Employee chooses their default company themselves, within their user permissions."""
	return _employee_of(user).company or _default_company(user)


def _company_phone(user: str) -> str:
	"""The main number of the person's company ('' when it has none)."""
	company = company_of_user(user)
	if not company or not frappe.db.table_exists("Company"):
		return ""
	return _one_line(frappe.db.get_value("Company", company, "phone_no"))


def mailbox_signature(account: dict | None) -> dict | None:
	"""The signature a mailbox names as its own, {html, text}, when it is one of its owner's and has something to show.

	Read below the rights: it goes under every message sent from the mailbox, by whoever it is shared with. But the Link
	can be pointed at anyone's signature (Frappe checks only that it exists, and a mailbox is written by its owner and
	those it is shared with): another person's stays theirs."""
	# The page of NeoMail owns what 'something to show' means for a signature
	from frappe_webmail.www.neomail import handed_signature

	if not account or not account.get("default_signature") or not account.get("user"):
		return None
	html = frappe.db.get_value(
		"Email Signature", {"name": account["default_signature"], "user": account["user"]}, "content"
	)
	if not html or not handed_signature(html):
		return None
	return {"html": html, "text": _read_as_text(html)}


def own_signature(user: str, account: dict | None = None) -> dict | None:
	"""The signature a person wrote, {html, text}: the one their mailbox names as its own (mailbox_signature), else
	their default one. The HTML is as stored. None when they have none."""
	mailbox = mailbox_signature(account)
	if mailbox:
		return mailbox
	html = frappe.db.get_value("Email Signature", {"user": user, "is_default": 1}, "content")
	if not html:
		return None
	return {"html": html, "text": _read_as_text(html)}


def _shows_something(html: str) -> bool:
	"""Whether a signature has words or a picture to show (what NeoMail's page asks of one), and is not an emptied
	one: a paragraph of a non-breaking space, as Word and Outlook leave."""
	from frappe_webmail.www.neomail import handed_signature

	return bool(handed_signature(html))


def _read_as_text(html: str) -> str:
	"""A signature's words, as NeoMail's page reads them; empty when it is too big to be read (the page does not read
	it either), or, and the log says why, when it cannot be."""
	from frappe_webmail.www.neomail import MAX_SIGNATURE_SOURCE, signature_text

	if len(html) > MAX_SIGNATURE_SOURCE:
		return ""
	try:
		return signature_text(html)
	except Exception:
		frappe.log_error("Email signature could not be read as text", frappe.get_traceback())
		return ""


def render(template, user: str) -> dict:
	"""The template written for the person: {html, text}. `template` is a document, saved or not."""
	return render_person(template, person_of(user))


def render_person(template, person: frappe._dict) -> dict:
	"""The template written for what is known of a person (person_of): {html, text}, both empty when it says nothing."""
	layout = template.get("layout")
	if layout not in LAYOUTS:
		layout = DEFAULT_LAYOUT
	card = card_of(template, person, layout)
	if not any(
		card[item]
		for item in (
			"identity",
			"contacts",
			"address",
			"social",
			"action",
			"disclaimer",
			"logo",
			"photo",
			"banner",
		)
	):
		return {"html": "", "text": ""}
	html = _draw(layout, card, look_of(template))
	# The templates are written as lines: no newline, no indentation in what leaves (a space that matters is on its line).
	# The logo, the photo, the banner and the layout go with them for NeoMail, which keeps a signature's pictures by
	# their bytes (www/neomail.py).
	return {
		"html": re.sub(r"\s*\n\s*", "", html).strip(),
		"text": text_of(card),
		"logo": card["logo"],
		"photo": card["photo"],
		"banner": card["banner"],
		"layout": layout,
	}


def _draw(layout: str, card: dict, look: dict) -> str:
	"""The card drawn by its layout. A banner goes under the signature and above its small print, whatever the layout:
	the layout draws the rest as it always has, and _banner.html puts it on a row above the banner."""
	from markupsafe import Markup

	environment = _environment()
	if not card["banner"]:
		return environment.get_template(LAYOUTS[layout]).render(card=card, look=look)
	above = {**card, "disclaimer": []}
	signature = ""
	if above["has_details"] or above["logo"] or above["photo"]:
		# Drawn by our own templates, every value escaped: the banner's template takes it as it is
		signature = Markup(environment.get_template(LAYOUTS[layout]).render(card=above, look=look))
	return environment.get_template("_banner.html").render(signature=signature, card=card, look=look)


def card_of(template, person: frappe._dict, layout: str = DEFAULT_LAYOUT) -> dict:
	"""What the signature says, from the template's checks and the person's values: an item that is off, or empty for
	this person, is not there at all (never a label alone), and an address that is no https one is not a link."""

	def shown(switch: str) -> bool:
		value = template.get(switch)
		return bool(SWITCHES[switch] if value is None else cint(value))

	def given(switch: str, text: str) -> str:
		return _one_line(text) if shown(switch) else ""

	identity = []
	if name := given("show_full_name", person.name):
		identity.append({"kind": "name", "text": name})
	role = ", ".join(
		filter(None, (given("show_job_title", person.job_title), given("show_department", person.department)))
	)
	if role:
		identity.append({"kind": "role", "text": role})
	if company := given("show_company_name", person.company_name):
		identity.append({"kind": "company", "text": company})

	contacts = []
	if phone := given("show_phone", person.phone):
		contacts.append({"label": _("Phone"), "text": phone, "href": None})
	if mobile := given("show_mobile", person.mobile):
		contacts.append({"label": _("Mobile"), "text": mobile, "href": None})
	if email := given("show_email", person.email):
		contacts.append({"label": _("Email"), "text": email, "href": mail_link(email)})
	if shown("show_website") and (site := web_address(person.website)):
		contacts.append({"label": _("Website"), "text": site[0], "href": site[1]})

	social = []
	if shown("show_social_links"):
		for row in template.get("social_links") or []:
			network, link = row.get("network"), https_url(row.get("url"))
			if network in NETWORKS and link:
				# The names of the networks are their own in every language; only 'Website' is a word
				social.append({"label": _("Website") if network == "Website" else network, "url": link})

	# Frappe stores what is typed in these fields with its characters escaped; the layout escapes them once more, so
	# they are read back as typed first.
	action_label = _one_line(unescape(template.get("cta_label") or ""))
	action_url = https_url(template.get("cta_url"))
	action = {"label": action_label, "url": action_url} if action_label and action_url else None

	disclaimer = []
	if shown("show_disclaimer"):
		disclaimer = [line.strip() for line in unescape(template.get("disclaimer") or "").splitlines()]
		while disclaimer and not disclaimer[0]:
			disclaimer.pop(0)
		while disclaimer and not disclaimer[-1]:
			disclaimer.pop()

	address = given("show_company_address", person.address)
	return {
		"identity": identity,
		"contacts": contacts,
		"address": address,
		"social": social,
		"action": action,
		# Whether there are lines to draw (a layout draws no column or row for none, nor a rule beside nothing)
		"has_details": bool(identity or contacts or address or social or action),
		"disclaimer": disclaimer,
		"logo": _logo_of(template, person) if shown("show_logo") and layout in WITH_LOGO else None,
		# The person's photo is in `person` only when they agreed to show it (person_of)
		"photo": _photo_of(person) if shown("show_photo") and layout in WITH_PHOTO else None,
		"banner": _banner_of(template, person),
	}


def _logo_of(template, person: frappe._dict) -> dict | None:
	"""The logo as the layout draws it: its address as stored, its width and, when its file says, its height."""
	src = _logo_src(person.logo)
	if not src:
		return None
	width = _number(template.get("logo_width"), LOGO_WIDTH, DEFAULT_LOGO_WIDTH)
	height = _logo_height(src, width)
	return {
		"src": src,
		"width": width,
		"height": height,
		"alt": _one_line(person.company_name) or _("Logo"),
		"style": f"display:block;border:0;text-decoration:none;width:{width}px;"
		+ (f"height:{height}px;" if height else "height:auto;"),
	}


def _photo_of(person: frappe._dict) -> dict | None:
	"""The person's photo as the layout draws it: the reduced copy (a file of the instance), at its own size, round by
	its own pixels (a PNG transparent outside the circle, signature_photos.reduced) and by its style where a mail client
	keeps rounded corners."""
	src = _plain_instance_file(person.get("photo"))
	if not src:
		return None
	return {
		"src": src,
		"width": PHOTO_SIZE,
		"height": PHOTO_SIZE,
		"alt": _one_line(person.name) or _("Photo"),
		"style": f"display:block;border:0;text-decoration:none;width:{PHOTO_SIZE}px;height:{PHOTO_SIZE}px;"
		f"border-radius:{PHOTO_SIZE // 2}px;",
	}


def banner_src(template) -> str | None:
	"""The address of the template's banner, a public picture of the instance; None when it has none (no banner then).
	Public: every person who writes with the signature shows it in their composer, and a private file of a template is
	the System Manager's to read (the form refuses one)."""
	src = _plain_instance_file(template.get("banner_image"))
	return src if src and src.startswith("/files/") else None


def _banner_of(template, person: frappe._dict) -> dict | None:
	"""The banner as the signature draws it: the template's picture at its width (and its height, from its file), its
	description for the words a client shows in its place, and its link when it is an https address."""
	src = banner_src(template)
	if not src:
		return None
	width = _number(template.get("banner_width"), BANNER_WIDTH, DEFAULT_BANNER_WIDTH)
	height = _logo_height(src, width)
	return {
		"src": src,
		"width": width,
		"height": height,
		# Frappe stores what is typed with its characters escaped (card_of): read back as typed, escaped once when drawn
		"alt": _one_line(unescape(template.get("banner_description") or ""))
		or _one_line(person.get("company_name"))
		or _("Banner"),
		"href": https_url(template.get("banner_url")),
		"style": f"display:block;border:0;text-decoration:none;width:{width}px;"
		+ (f"height:{height}px;" if height else "height:auto;"),
	}


def text_of(card: dict) -> str:
	"""The signature as plain text, from the same card: one line for each item, the disclaimer after a blank one. A
	banner that is a link is its description and its address; a picture says nothing else in text."""
	lines = [part["text"] for part in card["identity"]]
	lines += [f"{contact['label']}: {contact['text']}" for contact in card["contacts"]]
	if card["address"]:
		lines.append(card["address"])
	lines += [f"{link['label']}: {link['url']}" for link in card["social"]]
	if card["action"]:
		lines.append(f"{card['action']['label']}: {card['action']['url']}")
	if card.get("banner") and card["banner"]["href"]:
		lines.append(f"{card['banner']['alt']}: {card['banner']['href']}")
	if card["disclaimer"]:
		lines += ["", *card["disclaimer"]]
	return "\n".join(lines)


def look_of(template) -> dict:
	"""The styles of a signature, from the template's font, accent colour and sizes. Each is written in full on the
	elements that use it: a client inherits nothing from a table (Outlook not even the font of a cell)."""
	size = _number(template.get("font_size"), FONT_SIZE, DEFAULT_FONT_SIZE)
	small = max(size - 2, 10)
	accent = clean_color(template.get("accent_color")) or DEFAULT_ACCENT
	face = FONTS.get(template.get("font")) or FONTS[DEFAULT_FONT]

	def text(px: int, color: str = INK, extra: str = "") -> str:
		# A line height in pixels: the one that every client reads the same
		return f"font-family:{face};font-size:{px}px;line-height:{round(px * 1.4)}px;color:{color};{extra}"

	return {
		"table": "border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;" + text(size),
		"cell": "vertical-align:top;" + text(size),
		"name": text(size + 2, accent, "font-weight:bold;"),
		"role": text(size),
		"company": text(size, INK, "font-weight:bold;"),
		"line": text(size),
		"small": text(small, MUTED),
		"fine": "vertical-align:top;" + text(small, MUTED),
		"label": f"color:{MUTED};",
		"strong": f"font-weight:bold;color:{accent};",
		"link": f"color:{accent};text-decoration:none;",
		"action": f"color:{accent};text-decoration:underline;",
		"rule": f"border-left:1px solid {accent};",
		# A picture that is a link (the banner): no underline, no border around it
		"picture_link": "display:block;border:0;text-decoration:none;",
	}


@lru_cache(maxsize=1)
def _environment():
	"""The Jinja environment of the layouts: its own rather than Frappe's, which does not escape what it writes."""
	from jinja2 import Environment, FileSystemLoader, StrictUndefined

	return Environment(
		loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates", "signatures")),
		autoescape=True,
		undefined=StrictUndefined,
		trim_blocks=True,
		lstrip_blocks=True,
	)


# The form ----------------------------------------------------------------------------------------------------------


@frappe.whitelist()
def preview(doc, user: str | None = None) -> dict:
	"""The signature a template gives, from the form as it stands (saved or not), written for a person (the one who asks
	by default): {html, text}. Only for those who may write the template: it shows a person's numbers and address."""
	frappe.has_permission("Email Signature Template", "write", throw=True)
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	if not isinstance(doc, dict):
		frappe.throw(_("Not a template"))
	user = user or frappe.session.user
	if not frappe.db.exists("User", user):
		frappe.throw(_("User {0} not found").format(user), frappe.DoesNotExistError)
	# Whatever the form said it is, it is a template: it is not saved, and only read
	template = frappe.get_doc({**doc, "doctype": "Email Signature Template"})
	written = render(template, user)
	return {"html": written["html"], "text": written["text"]}


# The person's own choices ------------------------------------------------------------------------------------------


def _choosing() -> str:
	"""The person who asks, when they are one of the desk's people: only they have a company signature to make choices
	of (template_for); anyone else, a portal account or a visitor, is refused."""
	user = frappe.session.user
	if user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return user


def _shows(template, switch: str) -> bool:
	"""Whether a template shows an item, its default when it says nothing (card_of reads its checks the same way)."""
	value = template.get(switch)
	return bool(SWITCHES[switch] if value is None else cint(value))


@frappe.whitelist()
def my_choices() -> dict:
	"""What the person who asks may choose of the company signature that applies to them, and what they chose.

	`template`: whether one applies; `photo` and `mobile`: whether the person has that choice to make, because the
	template shows photos (in a layout with a place for one) or mobile numbers, or because they made it already (a
	yes is always theirs to take back, whatever the template now shows); `photo_allowed` and `hide_mobile`: their
	choices; `photo_url`: the copy of their photo that their messages carry, when it is ready; `photo_state`: how their
	photo stands (signature_photos.photo_state: ready, off, missing, unreadable, pending). Their own only: it names
	nobody."""
	from frappe_webmail import signature_photos

	user = _choosing()
	template = template_for(user)
	choices = preference_of(user)
	photo_url, photo_state = signature_photos.photo_state(user, choices)
	shows_photos = bool(template) and _shows(template, "show_photo") and template.get("layout") in WITH_PHOTO
	return {
		"template": bool(template),
		"photo": shows_photos or bool(cint(choices.photo_allowed)),
		"mobile": (bool(template) and _shows(template, "show_mobile")) or bool(cint(choices.hide_mobile)),
		"photo_allowed": cint(choices.photo_allowed),
		"hide_mobile": cint(choices.hide_mobile),
		"photo_url": photo_url,
		"photo_state": photo_state,
	}


def _flag(value) -> int:
	"""A check as the desk sends it (1, "1", true, "true"...): 1 or 0."""
	if isinstance(value, str):
		return int(value.strip().lower() in ("1", "true", "yes", "on"))
	return int(bool(value))


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=60)
def save_my_choices(photo_allowed=None, hide_mobile=None) -> dict:
	"""Save the choices of the person who asks, in their own record, made for them the first time; what is not said
	stays as it was. The copy of their photo is made, or deleted, with the choice (Email Signature Preference). There is
	no way to name another person: one may change one's own choices only. Answers what my_choices answers."""
	user = _choosing()
	if not frappe.db.table_exists(PREFERENCE):
		# The code is there, its DocType not yet (a site between an update and its migration)
		frappe.throw(_("Your choice could not be saved"))
	name = frappe.db.get_value(PREFERENCE, {"user": user}, "name")
	doc = frappe.get_doc(PREFERENCE, name) if name else frappe.get_doc({"doctype": PREFERENCE, "user": user})
	if photo_allowed is not None:
		doc.photo_allowed = _flag(photo_allowed)
	if hide_mobile is not None:
		doc.hide_mobile = _flag(hide_mobile)
	# With the person's own rights: their record is theirs to read and write (has_permission of the DocType)
	doc.save()
	return my_choices()
