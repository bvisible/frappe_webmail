# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The icon of a sender's domain, for the round of NeoMail's rows (16.11.2026): the round shows the sender's initials, or
the icon of the site of their address's domain where there is one, as Spark does.

`NeomailSenderIcon/get {accountId, domain}` → `{domain, type, data}`: the icon's bytes in base64 and their kind, or
`data: null` where the domain has none (or none that may be asked for). Under a capability of its own, on the pattern of
`neomail_history`: a server without it leaves NeoMail's initials.

NeoMail asks only for the senders its person knows (a contact, someone they wrote to) or whose pictures they chose to
download, never for Junk, never for a free mail service's domain; this server never asks for one either (`free_mail`),
whatever it is asked. The browser asks no third
party: this server asks the domain's own site, and nothing else,
- for the site of the domain only, never a name under it (`example.com` for `news.example.com` and for
  `x7f3.example.com`, so that a name made for one recipient can't tell when its mail was listed), and at two fixed
  places only: `https://<site>/apple-touch-icon.png`, then `https://<site>/favicon.ico` (where the site's own redirects
  lead, five at most, as for the pictures in mail);
- under the rules of the pictures in mail (`pictures.fetch`: the public internet only, the usual ports, no Frappe method,
  five redirects at most, no cookie, no referrer, a plain user agent), each try within TRY_PATIENCE seconds and all of a
  site's within BUDGET; a PNG, a JPEG, a GIF, a WebP or an ICO by its own bytes, of MAX_BYTES at most as they come;
- a few at a time for the whole bench, and so many for a person in ten minutes, as the pictures are (`pictures._take_turn`,
  waited for WAIT_TURN seconds at most; `pictures._may_fetch`);
- once a week for everyone of the instance: what was found (or that nothing was) is kept FOUND_S (NONE_S; a site that
  could not be reached, FAILED_S).

What the domain's site learns is that this instance's server asked for its icon, at most once a week: not who asked, nor
which message, nor whom it was for.
"""

import base64
import re
import time

import frappe

from frappe_webmail import pictures
from frappe_webmail.mailcraft_jmap import JmapError, _account
from frappe_webmail.neomail_history import PUBLIC_DOMAINS

ICONS = "https://neoffice.me/jmap/neomail-sender-icons"
MAX_BYTES = 100 * 1024
# Seconds: one try, and all the tries of one domain.
TRY_PATIENCE = 6.0
BUDGET = 12.0
# Seconds: how long a turn among the bench's pictures is waited for, and how often it is asked for meanwhile.
WAIT_TURN = 6.0
TURN_EVERY = 0.25
# How long what was learnt of a domain is kept, in seconds: an icon, no icon, a site that could not be reached.
FOUND_S = 7 * 86400
NONE_S = 86400
FAILED_S = 3600
PLACES = ("/apple-touch-icon.png", "/favicon.ico")
# The free mail services: what follows their `@` stands for a service, not for whoever writes (NeoMail's
# `sender_images::FREE_MAIL_NAMES`). A name of these under one ending (`gmail.com`) or a country's of two (`yahoo.co.uk`).
FREE_MAIL_NAMES = frozenset(
	"""gmail googlemail yahoo ymail outlook hotmail live msn icloud me mac aol gmx web bluewin sunrise hispeed
	swissonline bluemail proton protonmail pm tutanota tuta infomaniak ik yopmail orange free wanadoo laposte sfr libero
	virgilio t-online freenet yandex mail zoho seznam posteo mailbox fastmail hey duck""".split()
)
COUNTRY_SECOND = frozenset(("co", "com", "net", "org", "ne", "or"))
_DOMAIN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def session_parts(account):
	"""What every mailbox's session adds: the capability."""
	return {ICONS: {}}, {ICONS: {"maxBytes": MAX_BYTES}}


def free_mail(domain):
	"""Whether `domain` is a free mail service's."""
	if domain in PUBLIC_DOMAINS:
		return True
	parts = domain.split(".")
	if len(parts) == 2:
		return parts[0] in FREE_MAIL_NAMES
	if len(parts) == 3:
		return parts[1] in COUNTRY_SECOND and len(parts[2]) == 2 and parts[0] in FREE_MAIL_NAMES
	return False


def _domain(value):
	"""The domain a text is, lower case, without a trailing dot; None for what is none (an address written as numbers
	included: the ending is letters)."""
	text = str(value or "").strip().lower().rstrip(".")
	return text if _DOMAIN.match(text) else None


def site_of(domain):
	"""The site `domain` is under, whose icon stands for it: its last two names (`example.com` for `news.example.com`), or
	its last three under a country's ending of two (`example.co.uk`)."""
	parts = domain.split(".")
	keep = 3 if len(parts) >= 3 and parts[-2] in COUNTRY_SECOND and len(parts[-1]) == 2 else 2
	return ".".join(parts[-keep:])


def _places(site):
	"""Where the icon of `site` is looked for, in order."""
	return [f"https://{site}{place}" for place in PLACES]


def icon_kind(data):
	"""The kind of picture `data` is by its own bytes: a picture's (pictures.picture_kind), or an ICO's."""
	if data.startswith(b"\x00\x00\x01\x00") and len(data) > 6:
		return "image/x-icon"
	return pictures.picture_kind(data)


def _key(domain):
	return f"neomail_icon:{domain}"


def _found(domain):
	"""What was learnt of `domain`, and kept: {"type", "data"}, {"none": 1}, or None (nothing yet)."""
	kept = frappe.cache().get_value(_key(domain))
	return kept if isinstance(kept, dict) else None


def _keep(domain, learnt, seconds):
	frappe.cache().set_value(_key(domain), learnt, expires_in_sec=seconds)


def _look(site):
	"""The icon of `site`, asked of it under the pictures' rules: (what is kept, for how long)."""
	start, reached = time.monotonic(), False
	for url in _places(site):
		left = BUDGET - (time.monotonic() - start)
		if left <= 1.0:
			break
		try:
			body, kind = pictures.fetch(
				url, patience=min(TRY_PATIENCE, left), kind_of=icon_kind, max_bytes=MAX_BYTES
			)
		except pictures.PictureError as e:
			# The site answered (a 404, something that is no picture): it was reached.
			reached = reached or e.kind in ("status", "not_picture", "too_large", "redirects")
			continue
		reached = True
		if 0 < len(body) <= MAX_BYTES:
			return {"type": kind, "data": base64.b64encode(body).decode()}, FOUND_S
	return {"none": 1}, NONE_S if reached else FAILED_S


def _turn():
	"""A turn among the bench's pictures on their way, waited for WAIT_TURN seconds at most; None when none came."""
	until = time.monotonic() + WAIT_TURN
	while True:
		holder = pictures._take_turn()
		if holder is not None or time.monotonic() >= until:
			return holder
		time.sleep(TURN_EVERY)


def icon_get(args):
	"""`NeomailSenderIcon/get {accountId, domain}` → the icon of the domain's site, or `data: null`."""
	_account(args.get("accountId"))
	domain = _domain(args.get("domain"))
	if not domain:
		raise JmapError("invalidArguments", "domain")
	answer = {"accountId": args.get("accountId"), "domain": domain, "type": None, "data": None}
	site = site_of(domain)
	if free_mail(domain) or free_mail(site):
		return answer
	learnt = _found(site)
	if learnt is None:
		user = frappe.session.user
		if not pictures._may_fetch(user):
			raise JmapError("serverUnavailable", "so many icons were asked for that the next ones must wait")
		holder = _turn()
		if holder is None:
			raise JmapError("serverUnavailable", "busy")
		try:
			pictures._count(user, pictures=1)
			learnt, seconds = _look(site)
		finally:
			pictures._give_back(holder)
		pictures._count(user, size=len(learnt.get("data") or ""))
		_keep(site, learnt, seconds)
	if learnt.get("data"):
		answer.update(type=learnt.get("type"), data=learnt.get("data"))
	return answer


METHODS = {"NeomailSenderIcon/get": icon_get}
