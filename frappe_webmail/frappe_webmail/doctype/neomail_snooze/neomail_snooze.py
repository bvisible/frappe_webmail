# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""NeoMail Snooze: a message a person put away until a chosen time (neomail_snooze.py). Written and read by the facade and
its job alone, for the person whose record it is; a System Manager may look."""

import frappe
from frappe.model.document import Document


class NeoMailSnooze(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Data
		active_key: DF.Data | None
		folder: DF.SmallText | None
		from_folder: DF.SmallText | None
		last_error: DF.SmallText | None
		message_id: DF.SmallText | None
		next_try: DF.Datetime | None
		returned_at: DF.Datetime | None
		state: DF.Literal["Waiting", "Returned", "CalledOff", "Failed"]
		tries: DF.Int
		uid: DF.Int
		uidvalidity: DF.Int
		until_utc: DF.Datetime
		user: DF.Link
	# end: auto-generated types

	pass


def on_doctype_update():
	"""The minute's job asks for what is due: by state and time."""
	frappe.db.add_index("NeoMail Snooze", ["state", "until_utc"], index_name="state_until")
