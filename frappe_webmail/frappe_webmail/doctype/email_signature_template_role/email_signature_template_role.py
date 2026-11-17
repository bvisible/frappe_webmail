# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EmailSignatureTemplateRole(Document):
	# A role an Email Signature Template is given to (its `roles`, when it applies to roles): every person of the desk
	# who has one of them gets the template, unless a more specific one applies to them (signatures.template_for).
	pass
