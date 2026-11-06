# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The SMTP certificate check (Webmail Account `smtp_verify_certificate`) is on for every mailbox made from now on, and
stays off for the mailboxes there already, which send today without it: a server whose certificate is self-signed or
made out to another name would stop sending at once, with nothing said. Each owner may turn it on, on the mailbox's
form; whether to turn it on for all of them is a decision of its own (maintenance#2296).

Run once, right after the column is made (post_model_sync): every mailbox there is then one made before the setting."""

import frappe


def execute():
	if not frappe.db.has_column("Webmail Account", "smtp_verify_certificate"):
		return
	frappe.db.sql("update `tabWebmail Account` set smtp_verify_certificate = 0")
