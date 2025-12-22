# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Webmail page controller.

This module handles the /webmail route for the website.
"""

import frappe


def get_context(context):
	"""
	Get context for the webmail page.

	Args:
		context: Frappe context object

	Returns:
		dict: Context with page configuration
	"""
	# Require login
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to access webmail"), frappe.PermissionError)

	context.no_cache = 1
	context.show_sidebar = False
	context.full_width = True

	return context
