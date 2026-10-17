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
	# The person's mailboxes, through the JMAP facade (maintenance#1630); without any, the sample mailbox.
	context.build_url = BUILD + ("?nora" if mailboxes else "?sample&nora")
	context.host_json = _script_json({"accounts": mailboxes, "language": context.lang, "product": PRODUCT})


def host_mailboxes(bearer=None):
	"""The mailboxes of the person (owned or shared, enabled) as MailCraft opens them: the JMAP session of each, and
	a token good for the facade only, twelve hours at most, that MailCraft keeps in the tab's memory. It is bound to
	the desk session of the request, or to Neodesk's OAuth bearer token (`bearer`, mailcraft_jmap.hand_over)."""
	from urllib.parse import quote

	from frappe_webmail.mailcraft_jmap import give_token
	from frappe_webmail.webmail_api import get_accounts

	accounts = get_accounts()
	if not accounts:
		return []
	token = give_token(bearer=bearer)
	base = frappe.utils.get_url() + "/api/method/frappe_webmail.mailcraft_jmap.session?account="
	return [
		{
			"email": a["email"],
			"name": a.get("sender_name") or "",
			"session": base + quote(a["name"], safe=""),
			"username": a["email"],
			"secret": token,
			"scheme": "bearer",
		}
		for a in accounts
	]


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
