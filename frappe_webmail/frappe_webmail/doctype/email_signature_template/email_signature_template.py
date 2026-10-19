# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from frappe_webmail.signatures import (
	DEFAULT_ACCENT,
	DEFAULT_FONT_SIZE,
	DEFAULT_LOGO_WIDTH,
	FONT_SIZE,
	LOGO_WIDTH,
	clean_color,
	https_url,
)


class EmailSignatureTemplate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from frappe_webmail.frappe_webmail.doctype.email_signature_social_link.email_signature_social_link import (
			EmailSignatureSocialLink,
		)

		accent_color: DF.Color | None
		allow_personal: DF.Check
		applies_to: DF.Literal["Everyone", "Company", "Department"]
		company: DF.Link | None
		cta_label: DF.Data | None
		cta_url: DF.Data | None
		department: DF.Link | None
		disclaimer: DF.SmallText | None
		enabled: DF.Check
		font: DF.Literal["Arial", "Helvetica", "Verdana", "Georgia", "Tahoma", "Trebuchet MS"]
		font_size: DF.Int
		layout: DF.Literal["Text only", "Logo left", "Logo above", "Compact"]
		logo_width: DF.Int
		preview_user: DF.Link | None
		show_company_address: DF.Check
		show_company_name: DF.Check
		show_department: DF.Check
		show_disclaimer: DF.Check
		show_email: DF.Check
		show_full_name: DF.Check
		show_job_title: DF.Check
		show_logo: DF.Check
		show_mobile: DF.Check
		show_phone: DF.Check
		show_social_links: DF.Check
		show_website: DF.Check
		social_links: DF.Table[EmailSignatureSocialLink]
		template_name: DF.Data
	# end: auto-generated types

	def validate(self):
		self.validate_scope()
		self.validate_look()
		self.validate_links()
		# Whom the preview was written for is the form's business, not the template's: kept, it would link the template
		# to that user (who could then not be deleted).
		self.preview_user = None

	def validate_scope(self):
		"""A template for a company or a department names it; one for everyone names neither."""
		if self.applies_to == "Company":
			if not self.company:
				frappe.throw(_("Choose the company this template applies to."))
			self.department = None
		elif self.applies_to == "Department":
			if not self.department:
				frappe.throw(_("Choose the department this template applies to."))
			self.company = None
		else:
			self.company = self.department = None

	def validate_look(self):
		"""The accent colour is written #rrggbb, the sizes are within the bounds that keep a signature readable. What the
		form leaves empty takes its default: the renderer would, but the document then says what is used."""
		if self.accent_color:
			accent = clean_color(self.accent_color)
			if not accent:
				frappe.throw(
					_("The accent colour must be written as #rrggbb, for example {0}.").format(DEFAULT_ACCENT)
				)
			self.accent_color = accent
		else:
			self.accent_color = DEFAULT_ACCENT

		self.font_size = cint(self.font_size) or DEFAULT_FONT_SIZE
		if not FONT_SIZE[0] <= self.font_size <= FONT_SIZE[1]:
			frappe.throw(_("The base font size must be between {0} and {1} pixels.").format(*FONT_SIZE))
		self.logo_width = cint(self.logo_width) or DEFAULT_LOGO_WIDTH
		if not LOGO_WIDTH[0] <= self.logo_width <= LOGO_WIDTH[1]:
			frappe.throw(_("The logo width must be between {0} and {1} pixels.").format(*LOGO_WIDTH))

	def validate_links(self):
		"""Only https:// addresses go into a signature (a link in a message that others read), and a call to action is
		a label with its address, never one without the other."""
		for row in self.social_links:
			url = https_url(row.url)
			if not url:
				frappe.throw(
					_("Row {0}: the address of a social link must start with https://").format(row.idx)
				)
			row.url = url

		self.cta_label = (self.cta_label or "").strip()
		if bool(self.cta_label) != bool((self.cta_url or "").strip()):
			frappe.throw(_("A call to action needs both its label and its address."))
		if self.cta_url:
			url = https_url(self.cta_url)
			if not url:
				frappe.throw(_("The address of the call to action must start with https://"))
			self.cta_url = url
