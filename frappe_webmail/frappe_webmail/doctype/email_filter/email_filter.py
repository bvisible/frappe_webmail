# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EmailFilter(Document):
	def before_insert(self):
		self.user = frappe.session.user

	def validate(self):
		self.validate_account_access()
		self.validate_conditions()
		self.validate_actions()

	def validate_account_access(self):
		"""Ensure user owns the account"""
		if self.account:
			account_user = frappe.db.get_value("Webmail Account", self.account, "user")
			if account_user != frappe.session.user:
				frappe.throw(_("Access denied to this account"))

	def validate_conditions(self):
		"""Ensure at least one condition is set"""
		has_condition = (
			self.from_contains
			or self.to_contains
			or self.subject_contains
			or self.has_attachment
		)
		if not has_condition:
			frappe.throw(_("At least one filter condition must be specified"))

	def validate_actions(self):
		"""Validate action configuration"""
		if self.action_type == "move" and not self.target_folder:
			frappe.throw(_("Target folder is required for move action"))

	def matches_email(self, email):
		"""Check if an email matches this filter's conditions"""
		conditions_met = []

		if self.from_contains:
			from_match = self.from_contains.lower() in (email.get("from_email", "") or "").lower()
			from_match = from_match or self.from_contains.lower() in (email.get("from_name", "") or "").lower()
			conditions_met.append(from_match)

		if self.to_contains:
			to_match = self.to_contains.lower() in (email.get("to", "") or "").lower()
			conditions_met.append(to_match)

		if self.subject_contains:
			subject_match = self.subject_contains.lower() in (email.get("subject", "") or "").lower()
			conditions_met.append(subject_match)

		if self.has_attachment:
			conditions_met.append(bool(email.get("has_attachments")))

		if not conditions_met:
			return False

		if self.match_type == "all":
			return all(conditions_met)
		else:  # any
			return any(conditions_met)

	def increment_applied(self):
		"""Increment the times_applied counter"""
		self.times_applied = (self.times_applied or 0) + 1
		self.last_applied = frappe.utils.now_datetime()
		self.db_update()


def get_permission_query_conditions(user):
	"""Only show user's own filters"""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return ""

	return f"(`tabEmail Filter`.user = {frappe.db.escape(user)})"


def has_permission(doc, ptype="read", user=None):
	"""Check if user can access this filter"""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return True

	return doc.user == user
