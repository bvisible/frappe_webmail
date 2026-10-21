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

Where the page is offered to the person (in_desk_for), the webmail of the desk gives way to it (Jérémy's decision of
21.10: the webmail goes, NeoMail takes its place): /app/webmail and the addresses below it lead to /app/neomail, with
what a link asked (a message, a folder, a new message), by the server for an address loaded (lead_to_neomail) and by
the webmail's page in the desk (webmail.js). What only the webmail has stays its own (WEBMAIL_ONLY: its signatures,
filters and automations, which NeoMail has no equivalent of yet). Elsewhere nothing changes, and the webmail's API
stays as it is (the phone uses it). A message the webmail's links name by (account, folder, uid) is opened in NeoMail
by its JMAP id (message_key).
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
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


def in_desk_for(user=None):
	"""Whether the page is offered here to `user` (the session's): one of the desk's people, as /neomail."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	return frappe.get_cached_value("User", user, "user_type") == "System User" and in_desk()


# The webmail's desk page and the addresses below it (not /app/webmail-account, its mailboxes' settings and sharing)
WEBMAIL_ROUTE = "/app/webmail"
NEOMAIL_ROUTE = "/app/" + PAGE
# What the webmail's address opens that NeoMail has no equivalent of yet: those addresses stay the webmail's
# (Webmail.vue, applyUrlIntent). Its signatures, where NeoMail's File > Signatures leads; its filters (the server's
# Email Filter rules, which NeoMail's own rules are not); its automations (Nora's, on the mailboxes).
WEBMAIL_ONLY = ("signatures", "filters", "automations")


def neomail_address(query):
	"""Where an address of the webmail leads where NeoMail is in the desk: /app/neomail with what the address asked
	(`compose`; a message: `account`, `folder`, `uid`, or `account`, `email`; a folder), as the webmail's links ask it
	(Webmail.vue, applyUrlIntent); None for what only the webmail does (WEBMAIL_ONLY). Kept the same as the page's own
	(public/js/neomail_host.js, deskAddress)."""
	from urllib.parse import urlencode

	query = query or {}
	if any(key in query for key in WEBMAIL_ONLY):
		return None
	if "compose" in query:
		kept = {"compose": "1"}
	else:
		kept = {
			key: str(query.get(key)).strip()
			for key in ("account", "folder", "uid", "email")
			if str(query.get(key) or "").strip()
		}
	return NEOMAIL_ROUTE + ("?" + urlencode(kept) if kept else "")


def _webmail_path(path):
	path = (path or "").rstrip("/")
	return path == WEBMAIL_ROUTE or path.startswith(WEBMAIL_ROUTE + "/")


def lead_to_neomail(context):
	"""update_website_context: a load of the webmail's desk page (/app/webmail, or below it) goes to /app/neomail
	where the page is offered to the person, with what the address asked (neomail_address); a 302, so that no browser
	keeps it. The desk's own address is rendered as a website page (www/app.py), and a redirect raised while it is
	rendered is answered as one (frappe.website.serve). Any other page, and the rest of the fleet, are left alone: the
	path is checked first, which costs nothing."""
	request = getattr(frappe.local, "request", None)
	if request is None or not _webmail_path(getattr(request, "path", "")):
		return None
	if not in_desk_for():
		return None
	args = getattr(request, "args", None) or {}
	target = neomail_address({key: args.get(key) for key in args})
	if target is None:
		return None
	frappe.local.flags.redirect_location = target
	raise frappe.Redirect(302)


@frappe.whitelist(methods=["POST"])
def hand_over(sample=None, build=None):
	"""What the page gives the build it frames, for the session's person: {build_url, host, no_mailbox}, made as
	/neomail makes it (www/neomail.py, `handover`; `sample` and `build` are its address's `?sample` and `?build=`),
	plus `chrome: "menu"`, `share` and `attachments` in `host`, and `editors` beside it (the extensions the Drive's
	editors open here, for the page itself).
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
	# never /neomail, whose page has no menu, and not where the site switched the desk's menu (NeoCockpit) off. The page
	# takes it back too where the menu cannot draw it in the browser (neomail.js).
	if not frappe.conf.get("neoffice_cockpit_disable"):
		framed["host"]["chrome"] = CHROME
	# NeoMail offers Share in Synk, for a person who may share a message there (neomail_share.py): this page only,
	# whose Synk view shows where it went.
	from frappe_webmail import neomail_share

	if neomail_share.offered():
		framed["host"]["share"] = True
	# NeoMail offers, on an attachment, what the old webmail's menu offers the person (neomail_attachments.py): the
	# Drive, the scanned documents, the Drive's editors; and the page knows which editors this site has (`editors`,
	# the extensions they open), to say so rather than open a copy no editor reads.
	# Never at the cost of NeoMail itself: what fails here offers nothing, and is logged.
	from frappe_webmail import neomail_attachments

	try:
		actions = neomail_attachments.offered()
		editors = sorted(neomail_attachments.installed_editors()) if "edit" in actions else []
	except Exception:
		frappe.log_error("NeoMail: the actions on an attachment could not be offered", frappe.get_traceback())
		actions, editors = [], []
	if actions:
		framed["host"]["attachments"] = actions
	if editors:
		framed["editors"] = editors
	return framed


@frappe.whitelist(methods=["GET"])
@rate_limit(limit=60, seconds=60)
def message_key(account=None, folder=None, uid=None):
	"""For the page: a message as the webmail's links name it (`account`, its `folder`, the inbox when left out, and its
	`uid`), as NeoMail opens it: {account (its address), mailbox (the folder's JMAP id), email (the message's JMAP id,
	made as the facade makes it, with the folder's UIDVALIDITY), or only the mailbox without a `uid`}. Only for a
	mailbox of the person's own or shared with them (the webmail's rule: another's is answered as one that does not
	exist), and with the session's CSRF token, as the page's other calls. `account` is the mailbox's name or its
	address, as the webmail took it. One IMAP STATUS a call: so many a minute at most (rate_limit)."""
	from frappe_webmail import mailcraft_jmap as jmap
	from frappe_webmail import webmail_api as webmail
	from frappe_webmail.www import neomail

	if not in_desk():
		raise frappe.PageDoesNotExistError
	jmap.page_request_only()
	neomail.desk_people_only()
	jmap.csrf_token_required()
	mailbox = webmail.get_account(_mailbox_name(account))
	folder = str(folder or "").strip() or "INBOX"
	answer = {"account": mailbox.email, "mailbox": jmap.mailbox_id(folder)}
	if uid is None or str(uid).strip() == "":
		return answer
	number = cint(uid)
	if number <= 0:
		frappe.throw(_("This message cannot be found."))
	validity = jmap._validities(mailbox, [folder]).get(folder) or 0
	if not validity:
		frappe.throw(_("This message cannot be found."))
	answer["email"] = jmap.email_id(folder, validity, number)
	return answer


def _mailbox_name(account):
	"""The name of the mailbox a link names by its name or its address (Webmail.vue took either), for get_account,
	which then says who may: a name or an address of no mailbox is left as it is, and answered as one."""
	account = str(account or "").strip()
	if account and not frappe.db.exists("Webmail Account", account):
		return frappe.db.get_value("Webmail Account", {"email": account}, "name") or account
	return account


def extend_bootinfo(bootinfo):
	"""The desk does not list the page where it is not offered (its search finds pages by the boot's `page_info`), and
	tells the webmail's page whether to lead to it (`neomail_in_desk`, webmail.js)."""
	offered = in_desk_for()
	if not offered and isinstance(bootinfo.get("page_info"), dict):
		bootinfo["page_info"].pop(PAGE, None)
	bootinfo["neomail_in_desk"] = 1 if offered else 0
