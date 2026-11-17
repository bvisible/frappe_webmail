# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The signature builder (public/js/signature_builder.js): the window where the company's signatures are made, one model
per group of people (a role, a user group, a department, a company, everyone), each seen as the people it reaches will
send it, and where each person sees which one is theirs and makes their own choices of it.

Opened from NeoMail (File > Signatures, and `?signature_builder=1` of its desk page), from the webmail's signatures and from the list of
Email Signature Templates. The templates are written by those who may write Email Signature Template (System Manager,
and the company's administrator: let_the_company_admin_write); the rest see only their own signature and their choices (signatures.my_choices, save_my_choices)."""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from frappe_webmail import signatures

TEMPLATE = "Email Signature Template"
# The people the builder lists and reckons with at most: the desk's people of an instance, far fewer in practice
MAX_PEOPLE = 500
# Roles every person of the desk has, or no person: giving a template to one of them says nothing
UNGIVEN_ROLES = ("Administrator", "Guest", "All", "Desk User")
# What the builder may write of a template: its fields, never its name or anything Frappe keeps of it
NOT_WRITTEN = frozenset(
	("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "preview_html")
)


def _can_edit() -> bool:
	return bool(frappe.has_permission(TEMPLATE, "write"))


def _desk_person() -> str:
	"""The person who asks, when they are one of the desk's people (the builder is theirs only)."""
	user = frappe.session.user
	if user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return user


def _people() -> list[dict]:
	"""The desk's people a template may reach: enabled, not Administrator, the first MAX_PEOPLE by name."""
	return frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]},
		fields=["name as user", "full_name"],
		order_by="full_name asc",
		limit=MAX_PEOPLE,
	)


def _template_dict(doc) -> dict:
	"""A template as the builder edits it: its fields, and its roles as a list of names."""
	values = doc.as_dict(no_default_fields=True)
	values["name"] = doc.name
	values["roles"] = [row.role for row in doc.get("roles") or []]
	values["social_links"] = [
		{"network": row.network, "url": row.url} for row in doc.get("social_links") or []
	]
	values.pop("preview_html", None)
	return values


@frappe.whitelist()
def state() -> dict:
	"""What the builder opens on: for those who may write the templates, every template (`templates`), what one may be
	given to (`choices`) and the people it may reach (`people`); for everyone, their own signature (`mine`: which
	template applies to them and the choices they may make of it)."""
	user = _desk_person()
	mine = signatures.my_choices()
	applying = signatures.template_for(user)
	mine["template_name"] = applying.template_name if applying else None
	mine["name"] = applying.name if applying else None
	out = {"can_edit": _can_edit(), "mine": mine, "layouts": list(signatures.LAYOUTS)}
	if not out["can_edit"]:
		return out
	names = frappe.get_all(TEMPLATE, order_by="enabled desc, modified desc", pluck="name")
	out["templates"] = [_template_dict(frappe.get_doc(TEMPLATE, name)) for name in names]
	meta = frappe.get_meta(TEMPLATE)
	out["choices"] = {
		"roles": frappe.get_all(
			"Role",
			filters={"disabled": 0, "desk_access": 1, "name": ["not in", list(UNGIVEN_ROLES)]},
			order_by="name asc",
			pluck="name",
		),
		"user_groups": frappe.get_all("User Group", order_by="name asc", pluck="name")
		if frappe.db.table_exists("User Group")
		else [],
		"departments": frappe.get_all(
			"Department", filters={"is_group": 0}, order_by="name asc", pluck="name"
		)
		if frappe.db.table_exists("Department")
		else [],
		"companies": frappe.get_all("Company", order_by="name asc", pluck="name")
		if frappe.db.table_exists("Company")
		else [],
		"fonts": (meta.get_field("font").options or "").split("\n"),
	}
	out["people"] = _people()
	return out


def _unsaved(doc) -> "frappe.model.document.Document":
	"""A template from what the builder sends (saved or not), only read: its roles made rows."""
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	if not isinstance(doc, dict):
		frappe.throw(_("Not a template"))
	values = {key: value for key, value in doc.items() if key not in NOT_WRITTEN}
	values["roles"] = [{"role": role} for role in (doc.get("roles") or []) if isinstance(role, str) and role]
	values["social_links"] = [
		{"network": row.get("network"), "url": row.get("url")}
		for row in (doc.get("social_links") or [])
		if isinstance(row, dict)
	]
	template = frappe.get_doc({**values, "doctype": TEMPLATE})
	template.name = doc.get("name") or "__unsaved__"
	return template


@frappe.whitelist(methods=["POST"])
def reach(doc) -> dict:
	"""Who a template (as the builder has it, saved or not) reaches: each of the desk's people, whether it applies to them
	(`applies`), whether they would send it once saved (`sends`: no more specific template takes them), the template they
	send today, as the templates are saved (`today`), and what their card lacks (`missing`: job title, mobile). Only for those who may write the templates:
	it lists people and what their record holds."""
	_desk_person()
	frappe.has_permission(TEMPLATE, "write", throw=True)
	template = _unsaved(doc)
	saved = signatures.enabled_templates()
	saved_given = signatures.roles_given(r.name for r in saved if r.applies_to == "Role")
	others = [row for row in saved if row.name != template.name]
	row = frappe._dict(
		name=template.name,
		applies_to=template.applies_to,
		company=template.get("company"),
		department=template.get("department"),
		user_group=template.get("user_group"),
	)
	with_it = ([row] if template.enabled else []) + others
	given = signatures.roles_given(r.name for r in others if r.applies_to == "Role")
	given[template.name] = {r.role for r in template.get("roles") or []}
	people = []
	for person in _people():
		scope = signatures.scope_of(person.user, [*saved, row])
		applies = signatures._applies(row, scope, given[template.name])
		today = signatures.winning_template(scope, saved, saved_given)
		sends = (
			applies
			and bool(template.enabled)
			and signatures.winning_template(scope, with_it, given) == template.name
		)
		card = signatures.person_of(person.user)
		missing = [
			label
			for label, value in ((_("job title"), card.job_title), (_("mobile"), card.mobile))
			if not value
		]
		people.append(
			{
				"user": person.user,
				"full_name": person.full_name or person.user,
				"applies": applies,
				"sends": sends,
				"today": today,
				"missing": missing,
			}
		)
	return {"people": people, "count": sum(1 for p in people if p["sends"])}


@frappe.whitelist(methods=["POST"])
def preview(doc, user: str | None = None) -> dict:
	"""The signature a template (saved or not) gives a person, as their messages carry it: {html, text}. The person who
	asks by default; another person only for those who may write the templates."""
	asker = _desk_person()
	if user and user != asker:
		frappe.has_permission(TEMPLATE, "write", throw=True)
	user = user or asker
	if not frappe.db.exists("User", user):
		frappe.throw(_("User {0} not found").format(user), frappe.DoesNotExistError)
	template = _unsaved(doc)
	written = signatures.render(template, user)
	return {"html": written["html"], "text": written["text"]}


@frappe.whitelist()
def my_preview() -> dict:
	"""The signature of the person who asks, as their messages carry it today: {html, text, template}."""
	user = _desk_person()
	written = signatures.signature_for(user) or {}
	applying = signatures.template_for(user)
	return {
		"html": written.get("html") or "",
		"text": written.get("text") or "",
		"template": applying.template_name if applying else None,
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=60)
def save(doc) -> dict:
	"""Save a template from the builder: a new one when it names none, else the one it names, with the template's own
	checks (EmailSignatureTemplate.validate). Answers the template as the builder edits it."""
	_desk_person()
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	if not isinstance(doc, dict):
		frappe.throw(_("Not a template"))
	name = doc.get("name")
	if name and frappe.db.exists(TEMPLATE, name):
		template = frappe.get_doc(TEMPLATE, name)
		template.check_permission("write")
	else:
		frappe.has_permission(TEMPLATE, "create", throw=True)
		template = frappe.new_doc(TEMPLATE)
	values = {
		key: value
		for key, value in doc.items()
		if key not in NOT_WRITTEN and key not in ("roles", "social_links")
	}
	template.update(values)
	template.set(
		"roles", [{"role": role} for role in (doc.get("roles") or []) if isinstance(role, str) and role]
	)
	if "social_links" in doc:
		template.set(
			"social_links",
			[
				{"network": row.get("network"), "url": row.get("url")}
				for row in (doc.get("social_links") or [])
				if isinstance(row, dict)
			],
		)
	template.save()
	return _template_dict(template)


# The company's administrator (the Admin role of Neoffice, every right but the platform's): the one who makes the
# company's signatures in the builder, as the team's are made on the hub, where nobody of the team is System Manager
COMPANY_ADMIN = "Admin"
ADMIN_RIGHTS = ("read", "write", "create", "delete")


def let_the_company_admin_write():
	"""after_migrate: the company's administrator (COMPANY_ADMIN) may read, write, create and delete the company's
	signature templates, as System Manager may. Added through Frappe's own way in (add_permission, which first copies the
	standard rules when a doctype has no custom one: a custom rule alone would make Frappe forget the standard ones),
	then each right set on that rule. Idempotent; a site without the role is left alone; a failure is logged and never
	stops the migration."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("Role", COMPANY_ADMIN) or not frappe.db.exists("DocType", TEMPLATE):
		return
	try:
		rule = {"parent": TEMPLATE, "role": COMPANY_ADMIN, "permlevel": 0, "if_owner": 0}
		if not frappe.db.exists("Custom DocPerm", rule):
			add_permission(TEMPLATE, COMPANY_ADMIN, 0)
		held = frappe.db.get_value("Custom DocPerm", rule, list(ADMIN_RIGHTS), as_dict=True) or {}
		missing = [right for right in ADMIN_RIGHTS if not held.get(right)]
		for right in missing:
			update_permission_property(TEMPLATE, COMPANY_ADMIN, 0, right, 1, validate=False)
		if missing:
			frappe.clear_cache(doctype=TEMPLATE)
	except Exception:
		frappe.log_error("Company admin could not be given the signature templates", frappe.get_traceback())
