# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EmailSignature(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		content: DF.TextEditor
		is_default: DF.Check
		signature_name: DF.Data
		user: DF.Link
	# end: auto-generated types

	def validate(self):
		"""Validate and handle default signature logic"""
		self.handle_default_signature()

	def handle_default_signature(self):
		"""Ensure only one default signature per user"""
		if self.is_default:
			# Unset other default signatures for this user
			frappe.db.sql(
				"""
				UPDATE `tabEmail Signature`
				SET is_default = 0
				WHERE user = %s AND name != %s AND is_default = 1
				""",
				(self.user, self.name or ""),
			)

	def before_insert(self):
		"""Set default values before insert"""
		if not self.user:
			self.user = frappe.session.user

		# If this is the first signature for the user, make it default
		existing_count = frappe.db.count("Email Signature", {"user": self.user})
		if existing_count == 0:
			self.is_default = 1

	def on_trash(self):
		"""Clear this signature from any account that used it as default.

		default_signature is a convenience Link on Webmail Account, not a hard
		dependency. Frappe's default on-delete behaviour ("Restrict") otherwise
		blocks deleting a signature any account points to. We null the link
		(SET NULL semantics) so the signature can be removed and the account
		survives with no default signature.
		"""
		linked_accounts = frappe.get_all(
			"Webmail Account", filters={"default_signature": self.name}, pluck="name"
		)
		for account_name in linked_accounts:
			frappe.db.set_value(
				"Webmail Account", account_name, "default_signature", None, update_modified=False
			)

	def has_permission(self, permtype="read", doc=None):
		"""Check if user has permission to access this signature"""
		# Honour ignore_permissions like the base Document.has_permission does;
		# this override otherwise shadows it and breaks programmatic writes.
		if self.flags.ignore_permissions:
			return True
		if frappe.session.user == "Administrator":
			return True
		if self.user == frappe.session.user:
			return True
		return False


def before_save(doc, method):
	"""Hook called before saving Email Signature"""
	doc.handle_default_signature()
