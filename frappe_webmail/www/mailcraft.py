# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The /mailcraft address: the trial of MailCraft with Nora (« Reply with Nora »), on its sample mailbox.

Off unless the site's configuration says `mailcraft_trial: 1` (osiris, while the first step of the plan
« Nora dans mailcraft » is tried, maintenance#1629): everywhere else the address does not exist. The page
frames the browser build of MailCraft (bvisible/mailcraft) that the Suite's installer puts next to the
editors (suite/public/craft/mailcraft), and asks it to reach Nora with this page's session: the build
reads this page's CSRF token (same origin) and calls Nora's methods, which apply their own rights.
The desk's people only: a visitor signs in first, a portal account is refused, as for the webmail.
"""

import frappe
from frappe import _

BUILD = "/assets/suite/craft/mailcraft/index.html"
ROUTE = "/mailcraft"

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
	context.build_url = BUILD + "?sample&nora"
	context.lang = frappe.local.lang or "en"


def _redirect(location):
	frappe.local.flags.redirect_location = location
	redirect = frappe.Redirect()
	# A 302: a cached 301 would keep sending browsers here if the address ever changes.
	redirect.http_status_code = 302
	raise redirect
