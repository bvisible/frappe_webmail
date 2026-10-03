# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
The /webmail address.

The webmail lives in the desk (/app/webmail, loaded by app_include_js). This website page only had the website's
scripts, so `frappe.webmail` never existed and it waited forever on « Chargement de Webmail… » (03.10). A typed
address or an old bookmark now lands in the desk, its query kept (a link to a message); a visitor signs in first;
a portal account, which has no desk, is told so instead of waiting.
"""

import frappe
from frappe import _

DESK_ROUTE = "/app/webmail"


def get_context(context):
	if frappe.session.user == "Guest":
		_redirect("/login?redirect-to=" + DESK_ROUTE)
	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		frappe.throw(
			_("Webmail is part of the desk: your account has no access to it."), frappe.PermissionError
		)
	request = getattr(frappe, "request", None)
	query = request.query_string.decode() if request is not None and request.query_string else ""
	_redirect(DESK_ROUTE + ("?" + query if query else ""))


def _redirect(location):
	frappe.local.flags.redirect_location = location
	redirect = frappe.Redirect()
	# A 302: a cached 301 would keep sending browsers here if the address ever changes.
	redirect.http_status_code = 302
	raise redirect
