# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Permission utilities for Frappe Webmail.
"""

import frappe


def has_app_permission():
	"""
	Check if the current user has permission to access the webmail app.

	Returns:
		bool: True if user has access, False otherwise
	"""
	# Guest users cannot access webmail
	if frappe.session.user == "Guest":
		return False

	# All logged-in users can access webmail
	return True


@frappe.whitelist()
def check_webmail_access():
	"""
	API endpoint to check webmail access.

	Returns:
		dict: Access status and user info
	"""
	return {
		"has_access": has_app_permission(),
		"user": frappe.session.user,
	}
