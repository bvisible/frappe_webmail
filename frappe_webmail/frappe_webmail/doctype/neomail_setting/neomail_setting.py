# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""NeoMail Setting: what NeoMail keeps of a person's window between two visits (mailcraft_settings.py): the person's
rules and categories (`account` "*"), or the Safe Senders and Blocked Senders of one of their mailboxes. Written and
read by the facade alone, for the person whose token it is; a System Manager may look."""

import frappe
from frappe.model.document import Document


class NeoMailSetting(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Data | None
		blocked_senders: DF.JSON | None
		categories: DF.JSON | None
		rules: DF.JSON | None
		safe_senders: DF.JSON | None
		user: DF.Link
	# end: auto-generated types

	pass


def on_doctype_update():
	"""One record per person and mailbox (and one of the person's own): two first writes at once make one."""
	frappe.db.add_unique("NeoMail Setting", ["user", "account"], constraint_name="unique_user_account")
