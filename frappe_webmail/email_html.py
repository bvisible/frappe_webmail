# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What the HTML of a message sent may carry, and of a signature pasted as HTML.

A message sent keeps text and boxes, links, pictures and tables: SENT_TAGS, SENT_ATTRIBUTES, the styles of
webmail_api.EMAIL_CSS_PROPERTIES and the addresses of SAFE_PROTOCOLS; anything else is dropped, never shown as text
(`clean_sent_html`, which the sending uses).

A signature pasted as HTML (from a signature generator, from Outlook, from a designer) keeps the same, so that what the
signature manager shows is what leaves, and a little less (`clean_signature_html`): what a mail client keeps out of
sight or never runs goes whole, with its content (scripts, style sheets, the head, comments, Outlook's conditional
comments, forms and frames), and its pictures are those a recipient can be shown: on the web over https, files of this
instance (the sending writes them into the message), or written into the HTML itself (`data:`, the same). A link goes
to the web, to an address or to a phone number.
"""

import re

from bs4 import BeautifulSoup, Comment, NavigableString
from bs4.dammit import EntitySubstitution
from bs4.formatter import HTMLFormatter

try:
	import bleach
except ImportError:
	bleach = None

from frappe_webmail.inline_images import SAFE_PROTOCOLS


class _SignatureFormatter(HTMLFormatter):
	"""How a cleaned signature is written: as BeautifulSoup does by default, but for two things. A non-breaking space
	is written `&nbsp;`, as it was pasted: as a bare character, Frappe takes a signature of `<p>&nbsp;</p>` (what Word
	and Outlook leave of an emptied one) for no content at all, and refuses to keep it. And each element's attributes
	keep their order instead of being sorted: a picture's address first (clean_signature_html)."""

	def __init__(self):
		super().__init__(
			entity_substitution=lambda text: EntitySubstitution.substitute_xml(text).replace("\xa0", "&nbsp;")
		)

	def attributes(self, tag):
		return list(tag.attrs.items()) if tag.attrs else []


_KEEPS_NBSP = _SignatureFormatter()

SENT_TAGS = [
	"a",
	"abbr",
	"acronym",
	"b",
	"blockquote",
	"br",
	"code",
	"div",
	"em",
	"h1",
	"h2",
	"h3",
	"h4",
	"h5",
	"h6",
	"hr",
	"i",
	"img",
	"li",
	"ol",
	"p",
	"pre",
	"span",
	"strong",
	"table",
	"tbody",
	"td",
	"th",
	"thead",
	"tr",
	"u",
	"ul",
]
SENT_ATTRIBUTES = {
	"*": ["class", "style"],
	"a": ["href", "title", "target", "rel"],
	"img": ["src", "alt", "width", "height"],
	"table": ["border", "cellpadding", "cellspacing", "width"],
	"td": ["colspan", "rowspan", "width", "valign", "align"],
	"th": ["colspan", "rowspan", "width", "valign", "align"],
}

# What goes whole, content and all, from a signature pasted as HTML: a mail client never shows it, and its text
# (a style sheet, a script) must not turn up as words in the signature.
_HIDDEN = (
	"script",
	"style",
	"head",
	"title",
	"template",
	"noscript",
	"iframe",
	"frame",
	"frameset",
	"object",
	"embed",
	"applet",
	"svg",
	"math",
	"xml",
	"form",
	"select",
	"textarea",
	"button",
	"input",
)
# The largest signature read, its HTML as pasted.
MAX_SIGNATURE_SOURCE = 1_000_000
# A picture written into the signature itself: a kind every mail client shows, in base64.
_DATA_PICTURE = re.compile(r"^data:image/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$", re.IGNORECASE)
_LINKS = ("http:", "https:", "mailto:", "tel:")


def clean_sent_html(html):
	"""`html` as a message sent may carry it. Unchanged where bleach is missing (the sending said so before)."""
	if not bleach or not html:
		return html
	from frappe_webmail.webmail_api import email_css_sanitizer

	return bleach.clean(
		html,
		tags=SENT_TAGS,
		attributes=SENT_ATTRIBUTES,
		protocols=SAFE_PROTOCOLS,
		css_sanitizer=email_css_sanitizer(),
		strip=True,
	)


def _picture(value):
	"""Whether a signature may show the picture at `value` to a recipient."""
	value = (value or "").strip()
	return (
		value.lower().startswith("https://")
		or value.startswith(("/files/", "/private/files/"))
		or bool(_DATA_PICTURE.match(value))
	)


def _signature_attribute(tag, name, value):
	if name in SENT_ATTRIBUTES["*"]:
		return True
	if tag == "a" and name == "href":
		return (value or "").strip().lower().startswith(_LINKS)
	if tag == "img" and name == "src":
		return _picture(value)
	return name in SENT_ATTRIBUTES.get(tag, ())


def clean_signature_html(html):
	"""A signature pasted as HTML as it is kept, previewed and sent (the module's notes): '' when nothing is left."""
	if not html or not isinstance(html, str):
		return ""
	soup = BeautifulSoup(html, "html.parser")
	for hidden in soup.find_all(_HIDDEN):
		hidden.decompose()
	for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
		comment.extract()
	# The body of a whole page pasted (Outlook copies one), else what was pasted.
	body = soup.body or soup
	html = "".join(str(child) for child in body.contents)
	if bleach:
		from frappe_webmail.webmail_api import email_css_sanitizer

		html = bleach.clean(
			html,
			tags=SENT_TAGS,
			attributes=_signature_attribute,
			# `data:` goes through to the pictures only: _signature_attribute refuses it in a link.
			protocols=[*SAFE_PROTOCOLS, "tel", "data"],
			css_sanitizer=email_css_sanitizer(),
			strip=True,
		)
	else:
		# Never kept uncleaned: the field leaves Frappe's own cleaning out, so it does it here (Frappe depends on
		# bleach, so this is a safety net that should never be needed).
		from frappe.utils.html_utils import sanitize_html

		html = sanitize_html(html, always_sanitize=True)
	soup = BeautifulSoup(html, "html.parser")
	for picture in soup.find_all("img"):
		source = picture.get("src")
		# A picture whose address was refused shows nothing: it goes.
		if not source:
			picture.decompose()
			continue
		# Its address first: Frappe, when it keeps a picture written in as a file, rewrites the tag up to the address,
		# and what came before it (its height, its words) would be lost.
		picture.attrs = {"src": source, **{k: v for k, v in picture.attrs.items() if k != "src"}}
	# The space between elements once, as a second cleaning leaves it: saved again, a signature stays as it is.
	soup.smooth()
	for text in soup.find_all(string=True):
		if (
			type(text) is NavigableString
			and text
			and not text.strip(" \t\r\n\f")
			and text.find_parent("pre") is None
		):
			text.replace_with("\n" if "\n" in text else " ")
	return soup.decode(formatter=_KEEPS_NBSP).strip()
