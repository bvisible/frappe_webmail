# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The desk's page /app/neomail: NeoMail inside Neoffice's shell, under the desk's header and beside its menu, framing the
build /neomail frames, with the same handover (www/neomail.py, `handover`) and the same functions on the page
(public/js/neomail_host.js), plus `chrome: "menu"`: NeoMail leaves its navigation to the desk's menu, which the page
lends it (neomail.js). The contract it follows: neoffice-apps, docs/neomail-desk-menu-contract.md.

Off unless the site's configuration says `neomail_in_desk: 1`, and only where /neomail can be opened (NeoMail on, its
build installed); /neomail and /app/webmail stay as they are. The desk's people only, as /neomail: the page's role is
Desk User, and its handover refuses a portal account and a visitor.

The handover holds tokens: the page asks for it each time it opens (`hand_over`, never in the page's script, which the
desk keeps in the browser's storage, nor in the boot), and no cache keeps the answer (mailcraft_jmap.no_store).
"""

import frappe
from frappe.utils import cint

# The site's configuration key that puts NeoMail in the desk.
FLAG = "neomail_in_desk"
PAGE = "neomail"
# What the handover tells NeoMail: the desk's menu draws its navigation.
CHROME = "menu"


def in_desk():
	"""Whether the desk's page /app/neomail is offered here: the site says so, and /neomail can be opened."""
	from frappe_webmail.www import neomail

	return bool(cint(frappe.conf.get(FLAG))) and neomail.available()


@frappe.whitelist(methods=["POST"])
def hand_over(sample=None, build=None):
	"""What the page gives the build it frames, for the session's person: {build_url, host, no_mailbox}, made as
	/neomail makes it (www/neomail.py, `handover`; `sample` and `build` are its address's `?sample` and `?build=`),
	plus `chrome: "menu"` in `host`.
	Refused where the page is not offered (as a page that does not exist), to a portal account and a visitor, to a
	request that carries any Authorization rather than the desk's cookie alone (the facade tokens given are bound to
	the desk session), and to one without the session's CSRF token, whatever the site's settings
	(mailcraft_jmap.page_request_only, csrf_token_required)."""
	from frappe_webmail.mailcraft_jmap import csrf_token_required, page_request_only
	from frappe_webmail.www import neomail

	if not in_desk():
		raise frappe.PageDoesNotExistError
	page_request_only()
	neomail.desk_people_only()
	csrf_token_required()
	framed = neomail.handover(sample=bool(cint(sample)), build=build)
	# NeoMail leaves its navigation to the desk's menu (docs/neomail-desk-menu-contract.md, section 1): this page only,
	# never /neomail, whose page has no menu. The page takes it back where the desk's menu cannot draw it (neomail.js).
	framed["host"]["chrome"] = CHROME
	return framed


def extend_bootinfo(bootinfo):
	"""The desk does not list the page where it is not offered (its search finds pages by the boot's `page_info`)."""
	if not in_desk() and isinstance(bootinfo.get("page_info"), dict):
		bootinfo["page_info"].pop(PAGE, None)
