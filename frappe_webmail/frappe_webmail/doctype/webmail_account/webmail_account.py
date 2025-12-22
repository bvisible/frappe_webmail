# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WebmailAccount(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		default_signature: DF.Link | None
		email: DF.Data
		enabled: DF.Check
		imap_host: DF.Data
		imap_password: DF.Password
		imap_port: DF.Int
		imap_ssl: DF.Check
		sender_name: DF.Data | None
		smtp_host: DF.Data
		smtp_password: DF.Password
		smtp_port: DF.Int
		smtp_ssl: DF.Check
		smtp_starttls: DF.Check
		user: DF.Link
	# end: auto-generated types

	def validate(self):
		"""Validate the account settings"""
		self.validate_email()
		self.validate_ports()

	def validate_email(self):
		"""Validate email format"""
		if self.email and not frappe.utils.validate_email_address(self.email):
			frappe.throw(_("Invalid email address: {0}").format(self.email))

	def validate_ports(self):
		"""Validate port numbers"""
		if self.imap_port and (self.imap_port < 1 or self.imap_port > 65535):
			frappe.throw(_("Invalid IMAP port number"))
		if self.smtp_port and (self.smtp_port < 1 or self.smtp_port > 65535):
			frappe.throw(_("Invalid SMTP port number"))

	def before_insert(self):
		"""Set default values before insert"""
		if not self.user:
			self.user = frappe.session.user

	def has_permission(self, permtype="read", doc=None):
		"""Check if user has permission to access this account"""
		if frappe.session.user == "Administrator":
			return True
		if self.user == frappe.session.user:
			return True
		return False
