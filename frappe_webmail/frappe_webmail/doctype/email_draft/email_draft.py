# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class EmailDraft(Document):
	def before_insert(self):
		self.user = frappe.session.user
		self.last_saved = now_datetime()

	def before_save(self):
		self.last_saved = now_datetime()
		self.validate_account_access()

	def validate_account_access(self):
		"""Ensure user owns the account"""
		if self.account:
			account_user = frappe.db.get_value("Webmail Account", self.account, "user")
			if account_user != frappe.session.user:
				frappe.throw(_("Access denied to this account"))

	def has_permission(self, permtype="read", doc=None, *, debug=False, user=None):
		"""User can only access their own drafts: whose it is as stored, since the rights are checked on the draft as it is
		being saved, and a `user` changed in the same request made the person who typed it its owner (maintenance#2296)."""
		if self.flags.ignore_permissions:
			return True
		user = user or frappe.session.user
		if user == "Administrator":
			return True
		if self.is_new() or not self.name:
			# For new documents, user field is not yet set (before_insert sets it to the session's person)
			return not self.user or self.user == user
		return frappe.db.get_value("Email Draft", self.name, "user") == user


def get_permission_query_conditions(user):
	"""Only show user's own drafts"""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return ""

	return f"(`tabEmail Draft`.user = {frappe.db.escape(user)})"


def has_permission(doc, ptype="read", user=None):
	"""Check if user can access this draft"""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return True

	# For new documents (create), user field is set in before_insert
	if not doc.user:
		return True

	return doc.user == user
