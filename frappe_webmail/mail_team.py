# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The team's mail, as the company's administrator and each person see it (18.11.2026, the « Courrier » canvas).

- `team`: every mailbox of the instance, by person, and the shared ones apart, with whether each is ready to be read
  (connected, waiting for its password, to connect at Google or Microsoft, disabled). For the mail's managers only
  (Administrator, System Manager, the company's administrator): it says who has which address, never a message, a
  folder or a secret.
- `detect`: where a domain receives its mail (its MX records), so that the mailbox Neoservice provides is set up from
  its address alone, whichever of its hosts serves it, which the customer never has to know.
- `add`: a mailbox made by a manager for one of the desk's people, with who else reads it. The person owns it; the
  manager is never among its readers, and for someone else only the servers of a known provider are set (Neoservice's,
  Google, Microsoft): a manager's own servers would receive the person's password and mail (review of 18.11.2026).
  The person sees who added it, and who else reads it before they connect it.
- `mine`: the person's own mailboxes and those shared with them, and what is waiting (« My mail », for everyone).

Nothing here changes who may open a mailbox in NeoMail or in the webmail (webmail_account.has_permission): a manager's
list is read with ignore_permissions and carries no more than an address, an owner and a state."""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import get_datetime, now_datetime

ACCOUNT = "Webmail Account"
SHARED = "Webmail Account User"
# Who manages the team's mail: Administrator, and these roles (Neoffice's company administrator is « Admin »,
# signature_builder.COMPANY_ADMIN)
MANAGER_ROLES = frozenset({"System Manager", "Admin"})
# The desk's people the team's list shows at most: far fewer on an instance
MAX_PEOPLE = 300

# Where a domain receives its mail, read from its MX records (exact host names, not guesses): the two hosts of the
# mailboxes Neoservice provides (EmailArray receives on `mx.emailarray.com` and `mx2.emailarray.com`, Infomaniak on
# `mta-gw.infomaniak.ch`), and the two big providers that sign in by OAuth.
MX_SUFFIXES = (
	(".emailarray.com", "neoservice", "EmailArray"),
	(".infomaniak.ch", "neoservice", "Infomaniak"),
	(".google.com", "google", ""),
	(".googlemail.com", "google", ""),
	(".mail.protection.outlook.com", "microsoft", ""),
)
# The providers « Add a mailbox » offers, and how each signs in
PROVIDERS = ("neoservice", "google", "microsoft", "other")
OAUTH_OF = {"google": "Gmail", "microsoft": "Outlook"}


def may_manage(user: str | None = None) -> bool:
	"""Whether *user* manages the team's mail: Administrator, or one of the desk's people with a manager's role."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		return False
	return bool(MANAGER_ROLES & set(frappe.get_roles(user)))


def _manager() -> str:
	if not may_manage():
		frappe.throw(
			_("Only the company's administrator manages the team's mailboxes."), frappe.PermissionError
		)
	return frappe.session.user


def _desk_person() -> str:
	user = frappe.session.user
	if user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return user


def _secrets(names: list[str]) -> set[tuple[str, str]]:
	"""Which of these mailboxes have which secret stored, as (name, fieldname): whether it is there, never its value."""
	if not names:
		return set()
	rows = frappe.db.sql(
		"""select `name`, `fieldname` from `__Auth`
		where `doctype` = %(doctype)s and `name` in %(names)s
		and `fieldname` in ('imap_password', 'oauth_access_token', 'oauth_refresh_token')""",
		{"doctype": ACCOUNT, "names": tuple(names)},
	)
	return {(name, fieldname) for name, fieldname in rows}


def _provider_of(row) -> str:
	"""The provider as the person knows it: Neoservice for the mailboxes we provide, whoever hosts them."""
	if row.auth_type == "OAuth2":
		return {"Gmail": _("Google"), "Outlook": _("Microsoft 365")}.get(
			row.oauth_provider or "", _("Another provider")
		)
	if row.provider_preset:
		return _("Neoservice e-mail")
	return _("Another provider")


def _state_of(row, stored: set[tuple[str, str]]) -> dict:
	"""Whether the mailbox can be read now, in words and in one of the five tones (§6.3 of the design system)."""
	if not row.enabled:
		return {"code": "disabled", "label": _("Disabled", context="Mailbox"), "tone": "muted"}
	if row.auth_type == "OAuth2":
		if (row.name, "oauth_refresh_token") in stored:
			return {"code": "ready", "label": _("Ready", context="Mailbox"), "tone": "success"}
		if (row.name, "oauth_access_token") in stored:
			expiry = row.oauth_token_expiry and get_datetime(row.oauth_token_expiry)
			if expiry and expiry > now_datetime():
				return {"code": "ready", "label": _("Ready", context="Mailbox"), "tone": "success"}
			return {"code": "reconnect", "label": _("To connect again", context="Mailbox"), "tone": "danger"}
		return {"code": "connect", "label": _("To connect", context="Mailbox"), "tone": "warn"}
	if (row.name, "imap_password") not in stored:
		return {"code": "password", "label": _("Waiting for its password", context="Mailbox"), "tone": "warn"}
	return {"code": "ready", "label": _("Ready", context="Mailbox"), "tone": "success"}


WAITING = frozenset({"reconnect", "connect", "password"})
FIELDS = (
	"name",
	"email",
	"user",
	"enabled",
	"auth_type",
	"provider_preset",
	"oauth_provider",
	"oauth_token_expiry",
	"owner",
)


def _boxes(filters: dict | None = None) -> list:
	return frappe.get_all(ACCOUNT, filters=filters or {}, fields=list(FIELDS), order_by="email asc")


def _readers(names: list[str]) -> dict[str, list[str]]:
	"""Who else reads each mailbox (its « Shared With »), by mailbox."""
	out: dict[str, list[str]] = {}
	if not names:
		return out
	for row in frappe.get_all(
		SHARED,
		filters={"parenttype": ACCOUNT, "parent": ["in", names]},
		fields=["parent", "user"],
		order_by="idx asc",
	):
		out.setdefault(row.parent, []).append(row.user)
	return out


def _people() -> list:
	"""The desk's people, as the reader's list of users shows them (so an app that hides a service account from it
	hides it here too), Administrator and Guest left out."""
	filters = {"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]}
	fields = ["name", "full_name", "user_image"]
	try:
		return frappe.get_list(
			"User", filters=filters, fields=fields, order_by="full_name asc", limit=MAX_PEOPLE
		)
	except frappe.PermissionError:
		return frappe.get_all(
			"User", filters=filters, fields=fields, order_by="full_name asc", limit=MAX_PEOPLE
		)


def _job_titles(users: list[str]) -> dict[str, str]:
	"""Each person's job title, from the Employee linked to them, where the site has employees."""
	if not users or not frappe.db.table_exists("Employee"):
		return {}
	meta = frappe.get_meta("Employee")
	if not (meta.has_field("user_id") and meta.has_field("designation")):
		return {}
	out = {}
	for row in frappe.get_all(
		"Employee",
		filters={"user_id": ["in", users], "status": "Active"},
		fields=["user_id", "designation"],
	):
		if row.designation:
			out[row.user_id] = row.designation
	return out


def _box(row, stored, readers, names) -> dict:
	return {
		"name": row.name,
		"email": row.email,
		"owner": row.user,
		"owner_name": names.get(row.user) or row.user,
		"provider": _provider_of(row),
		"oauth": row.auth_type == "OAuth2",
		"state": _state_of(row, stored),
		"readers": [
			{"user": user, "full_name": names.get(user) or user} for user in readers.get(row.name, [])
		],
		# Who made it, when it is not its owner (« Add a mailbox » by the company's administrator)
		"added_by": (
			names.get(row.owner) or frappe.get_cached_value("User", row.owner, "full_name") or row.owner
		)
		if row.owner and row.owner != row.user
		else "",
	}


@frappe.whitelist()
def team() -> dict:
	"""Every mailbox of the instance for the mail's managers: `people` (each of the desk's people, with the mailboxes
	that are theirs alone), `shared` (the mailboxes others read too, with who answers for each), and `figures`."""
	manager = _manager()
	people = _people()
	names = {person.name: person.full_name or person.name for person in people}
	# Administrator is Neoservice's account on a customer's instance: its own mailboxes are not the team's
	rows = _boxes() if manager == "Administrator" else _boxes({"user": ["!=", "Administrator"]})
	for row in rows:
		if row.user and row.user not in names:
			names[row.user] = frappe.get_cached_value("User", row.user, "full_name") or row.user
	stored = _secrets([row.name for row in rows])
	readers = _readers([row.name for row in rows])
	for users in readers.values():
		for user in users:
			names.setdefault(user, frappe.get_cached_value("User", user, "full_name") or user)
	boxes = [_box(row, stored, readers, names) for row in rows]
	shared = [box for box in boxes if box["readers"]]
	own: dict[str, list] = {}
	for box in boxes:
		if not box["readers"]:
			own.setdefault(box["owner"], []).append(box)
	titles = _job_titles([person.name for person in people])
	# The shared mailboxes each person answers for or reads: a person with none of their own may still have mail
	reads: dict[str, list[str]] = {}
	for box in shared:
		for user in [box["owner"], *(reader["user"] for reader in box["readers"])]:
			reads.setdefault(user, []).append(box["email"])

	def person_of(user, full_name, image, job_title):
		return {
			"user": user,
			"full_name": full_name,
			"image": image,
			"job_title": job_title,
			"boxes": own.get(user, []),
			"reads": reads.get(user, []),
		}

	listed = [
		person_of(
			person.name, person.full_name or person.name, person.user_image, titles.get(person.name, "")
		)
		for person in people
	]
	# A mailbox whose owner is not among the desk's people listed (disabled since, or Administrator) is still shown
	listed_users = {person["user"] for person in listed}
	for user in own:
		if user not in listed_users:
			listed.append(person_of(user, names.get(user) or user, None, ""))
	return {
		"people": listed,
		"shared": shared,
		"figures": {
			"boxes": len(boxes),
			"shared": len(shared),
			"waiting": sum(1 for box in boxes if box["state"]["code"] in WAITING),
			"without": sum(1 for person in listed if not person["boxes"] and not person["reads"]),
		},
		"oauth": {provider: bool(_oauth_configured(oauth)) for provider, oauth in OAUTH_OF.items()},
	}


def _oauth_configured(provider: str) -> bool:
	"""Whether the site has the credentials to sign in at this provider (webmail_oauth_<provider> in site_config)."""
	from frappe_webmail.frappe_webmail.doctype.webmail_account.webmail_account import get_oauth_config

	return bool(get_oauth_config(provider))


def mx_hosts(domain: str) -> list[str] | None:
	"""The MX hosts of *domain*, best first, lower case without the final dot; empty when it has none, None when the
	lookup could not be made (no resolver, no network, a timeout), which is not the same answer."""
	try:
		import dns.resolver

		answer = dns.resolver.resolve(domain, "MX", lifetime=5)
	except ImportError:
		frappe.log_error(
			"NeoMail: dnspython is missing, the MX of a domain cannot be read", frappe.get_traceback()
		)
		return None
	except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
		return []
	except Exception:
		return None
	return [
		str(row.exchange).rstrip(".").lower()
		for row in sorted(answer, key=lambda r: r.preference)
		if row.exchange
	]


def provider_of_domain(domain: str) -> dict:
	"""Where *domain* receives its mail: `provider` (one of PROVIDERS but « other », or empty when unknown) and, for the
	mailboxes Neoservice provides, the `preset` that sets up their servers."""
	hosts = mx_hosts(domain)
	if hosts is None:
		return {"provider": "", "preset": "", "found": False, "failed": True}
	for host in hosts:
		for suffix, provider, preset in MX_SUFFIXES:
			if ("." + host).endswith(suffix):
				return {"provider": provider, "preset": preset, "found": True, "failed": False}
	return {"provider": "", "preset": "", "found": bool(hosts), "failed": False}


def _address(email: str) -> str:
	"""One plain address, lower case: never a list, a name before it, or spaces (the desk's check takes all three)."""
	email = (email or "").strip().lower()
	if (
		not email
		or any(char in email for char in ",;<> \t")
		or email.count("@") != 1
		or frappe.utils.validate_email_address(email) != email
	):
		frappe.throw(_("Invalid email address: {0}").format(frappe.utils.escape_html(email)))
	return email


def _domain_of(email: str) -> str:
	return _address(email).rsplit("@", 1)[1]


@frappe.whitelist()
@rate_limit(limit=60, seconds=60)
def detect(email: str) -> dict:
	"""Where the domain of *email* receives its mail, for « Add a mailbox »: `provider`, `preset` and `found` (the
	domain has MX records). Managers only, as adding is."""
	_manager()
	return dict(provider_of_domain(_domain_of(email)), domain=_domain_of(email))


def _servers(
	provider: str, domain: str, imap_host=None, imap_port=None, smtp_host=None, smtp_port=None
) -> dict:
	"""The servers a password mailbox signs in to: those of the preset Neoservice's host gives, found from the domain,
	or those the provider gave (« other »)."""
	from frappe_webmail.frappe_webmail.doctype.webmail_account.webmail_account import PASSWORD_PROVIDERS

	if provider == "neoservice":
		found = provider_of_domain(domain)
		if found["failed"]:
			frappe.throw(
				_("Neoffice could not look up where {0} receives its mail: try again in a moment.").format(
					domain
				)
			)
		if found["provider"] != "neoservice":
			frappe.throw(
				_(
					"The domain {0} does not receive its mail at Neoservice's: choose the provider that hosts it."
				).format(domain)
			)
		return dict(PASSWORD_PROVIDERS[found["preset"]], provider_preset=found["preset"])
	if not ((imap_host or "").strip() and (smtp_host or "").strip()):
		frappe.throw(_("Type the servers the provider gives: IMAP and SMTP."))
	smtp = int(smtp_port or 465)
	return {
		"imap_host": imap_host.strip(),
		"imap_port": int(imap_port or 993),
		"imap_ssl": 1,
		"smtp_host": smtp_host.strip(),
		"smtp_port": smtp,
		"smtp_ssl": 1 if smtp == 465 else 0,
		"smtp_starttls": 0 if smtp == 465 else 1,
		"provider_preset": "",
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=60)
def try_connection(
	email: str,
	provider: str,
	password: str,
	imap_host: str | None = None,
	imap_port: int | None = None,
	smtp_host: str | None = None,
	smtp_port: int | None = None,
) -> dict:
	"""Whether the mailbox signs in to its servers with this password, before « Add a mailbox » makes it: the webmail's own
	connection test (webmail_api.test_connection_live, rate-limited), on the servers `add` would set."""
	_manager()
	from frappe_webmail import webmail_api

	servers = _servers(
		(provider or "").strip().lower(), _domain_of(email), imap_host, imap_port, smtp_host, smtp_port
	)
	return webmail_api.test_connection_live(
		email=_address(email),
		imap_host=servers["imap_host"],
		imap_port=servers["imap_port"],
		imap_ssl=servers["imap_ssl"],
		smtp_host=servers["smtp_host"],
		smtp_port=servers["smtp_port"],
		smtp_ssl=servers["smtp_ssl"],
		smtp_starttls=servers["smtp_starttls"],
		auth_type="Password",
		imap_password=password,
		smtp_password=password,
		smtp_verify_certificate=1,
	)


def _readers_given(readers, owner: str, maker: str) -> list[str]:
	"""Who else reads a mailbox being made: the desk's people named, its owner left out. The manager who makes it for
	someone else is never among them: a mailbox at Google or Microsoft is connected by its owner alone, and a reader
	named by its maker would then read the owner's mail without their word (the owner shares it, from its form)."""
	if isinstance(readers, str):
		try:
			readers = frappe.parse_json(readers) if readers.strip().startswith("[") else [readers]
		except Exception:
			# Said, not raised as a server error: the error's record would keep the password the same call carries
			frappe.throw(_("The readers of the mailbox could not be read."))
	if not isinstance(readers, list | tuple):
		readers = []
	out = []
	for user in readers or []:
		if not isinstance(user, str) or user in out or user == owner:
			continue
		if user == maker:
			frappe.throw(
				_("You make this mailbox for someone else: its owner shares it with you, if they wish."),
				frappe.PermissionError,
			)
		if frappe.get_cached_value("User", user, "user_type") != "System User" or not frappe.get_cached_value(
			"User", user, "enabled"
		):
			frappe.throw(_("{0} is not one of the desk's people.").format(frappe.utils.escape_html(user)))
		out.append(user)
	return out


@frappe.whitelist(methods=["POST"])
def add(
	user: str,
	email: str,
	provider: str,
	password: str | None = None,
	readers: str | list | None = None,
	imap_host: str | None = None,
	imap_port: int | None = None,
	smtp_host: str | None = None,
	smtp_port: int | None = None,
) -> dict:
	"""A mailbox for *user*, one of the desk's people, made by a manager: `provider` « neoservice » (its servers found
	from the domain), « google » or « microsoft » (the person then connects it once at their provider), or « other »
	(the servers given, for the manager's own mailbox only). *readers*: who else reads it. Answers the mailbox and
	whether it waits to be connected."""
	maker = _manager()
	provider = (provider or "").strip().lower()
	if provider not in PROVIDERS:
		frappe.throw(_("Choose where the mailbox is."))
	if frappe.get_cached_value("User", user, "user_type") != "System User" or not frappe.get_cached_value(
		"User", user, "enabled"
	):
		frappe.throw(_("{0} is not one of the desk's people.").format(frappe.utils.escape_html(user)))
	# Servers of one's own choosing are for one's own mailbox: for someone else, they would receive that person's
	# password when NeoMail asks it again, and the mail they send (review of 18.11.2026)
	if provider == "other" and user != maker:
		frappe.throw(
			_(
				"Another provider's servers are set by the mailbox's owner: add it for yourself, or choose Neoservice, Google or Microsoft."
			),
			frappe.PermissionError,
		)
	if provider in OAUTH_OF and not _oauth_configured(OAUTH_OF[provider]):
		frappe.throw(_("This site cannot sign in at this provider yet: ask Neoservice."))
	email = _address(email)
	domain = _domain_of(email)
	if frappe.db.exists(ACCOUNT, {"email": email}):
		frappe.throw(_("The mailbox {0} is already there.").format(email))
	doc = frappe.new_doc(ACCOUNT)
	doc.update({"user": user, "email": email, "enabled": 1})
	if provider in OAUTH_OF:
		doc.update({"auth_type": "OAuth2", "oauth_provider": OAUTH_OF[provider]})
	else:
		if not (password or "").strip():
			frappe.throw(_("Type the mailbox's password."))
		doc.update({"auth_type": "Password", "imap_password": password, "smtp_password": password})
		# The preset, when there is one, writes the servers itself as the account is saved
		doc.update(_servers(provider, domain, imap_host, imap_port, smtp_host, smtp_port))
	for reader in _readers_given(readers, user, maker):
		doc.append("allowed_users", {"user": reader})
	# The manager makes it for its owner: the account's own rules let only its owner write it
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"name": doc.name, "email": doc.email, "waits_to_connect": doc.auth_type == "OAuth2"}


@frappe.whitelist()
def mine() -> dict:
	"""« My mail »: the person's own mailboxes and those shared with them, each with its state and who else reads it,
	and how many of their own wait for them (to connect, or a password)."""
	user = _desk_person()
	own = _boxes({"user": user})
	shared_names = frappe.get_all(SHARED, filters={"parenttype": ACCOUNT, "user": user}, pluck="parent")
	shared = _boxes({"name": ["in", shared_names], "user": ["!=", user]}) if shared_names else []
	rows = own + shared
	stored = _secrets([row.name for row in rows])
	readers = _readers([row.name for row in rows])
	names = {}
	for row in rows:
		for person in [row.user, *readers.get(row.name, [])]:
			if person and person not in names:
				names[person] = frappe.get_cached_value("User", person, "full_name") or person
	boxes = [_box(row, stored, readers, names) for row in rows]
	for box in boxes:
		box["mine"] = box["owner"] == user
		box["may_connect"] = box["mine"] and box["oauth"] and box["state"]["code"] in WAITING
	return {
		"boxes": boxes,
		"waiting": sum(1 for box in boxes if box["mine"] and box["state"]["code"] in WAITING),
		"may_manage": may_manage(user),
	}


def waiting_count(user: str) -> int:
	"""How many of *user*'s own mailboxes wait for them: what the user menu's « My mail » counts, read at each boot."""
	rows = _boxes({"user": user, "enabled": 1})
	stored = _secrets([row.name for row in rows])
	return sum(1 for row in rows if _state_of(row, stored)["code"] in WAITING)


def day_summary(scope=None) -> list[dict]:
	"""« Mon espace »'s « Not to forget » (the theme's hook `neoffice_day_summary`): one line when the reader's own
	mailboxes wait for them (to connect at Google or Microsoft, again, or a password), which opens « My mail ». A
	person's own mailboxes only, whatever the scope: nothing of anyone else's."""
	user = frappe.session.user
	if user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		return []
	rows = _boxes({"user": user, "enabled": 1})
	stored = _secrets([row.name for row in rows])
	waiting = [(row, _state_of(row, stored)) for row in rows]
	waiting = [(row, state) for row, state in waiting if state["code"] in WAITING]
	if not waiting:
		return []
	if len(waiting) == 1:
		row, state = waiting[0]
		title = _("Your mailbox {0} waits for you").format(row.email)
		meta = f"{state['label']} · {_provider_of(row)}"
	else:
		title = _("{0} of your mailboxes wait for you").format(len(waiting))
		meta = ", ".join(row.email for row, _state in waiting[:3])
	return [
		{
			"title": title,
			"meta": meta,
			"route": "/app/neomail?my_mail=1",
			"icon": "mail",
			"tone": "amber",
			# Its part of the day's sentence (« You have {0}. »)
			"phrase": _("a mailbox to set up")
			if len(waiting) == 1
			else _("{0} mailboxes to set up").format(len(waiting)),
		}
	]
