# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EmailSignatureSocialLink(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		network: DF.Literal["LinkedIn", "X", "Facebook", "Instagram", "YouTube", "Website"]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		url: DF.Data
	# end: auto-generated types

	pass
