# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The person a signature preview is written for is chosen in a control the form draws, no longer in a field of
Email Signature Template (maintenance#2463: every choice made the template unsaved). The column the field left is
dropped, so that every site has the same table; it never held anything, the template emptied it at every save."""

import frappe


def execute():
	if not frappe.db.has_column("Email Signature Template", "preview_user"):
		return
	frappe.db.sql_ddl("alter table `tabEmail Signature Template` drop column `preview_user`")
	frappe.cache.hdel("table_columns", "tabEmail Signature Template")
