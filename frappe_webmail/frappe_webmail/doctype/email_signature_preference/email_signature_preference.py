# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Email Signature Preference: a person's own choices of the company signature, one record per person (named after
them): whether their photo is shown (never unless they say so) and whether their mobile is hidden.

Theirs to read and change, and a System Manager's (has_permission, get_permission_query_conditions, hooks.py); the
desk's people only. The copy of their photo (`photo`) and what it was made from (`photo_source`) are written by the
server alone (signature_photos.py): whatever a save says of them is put back as it was, since a message carries the
file the copy names."""

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_webmail.signatures import PREFERENCE


class EmailSignaturePreference(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		hide_mobile: DF.Check
		photo: DF.AttachImage | None
		photo_allowed: DF.Check
		photo_source: DF.SmallText | None
		user: DF.Link
	# end: auto-generated types

	def before_insert(self):
		self.user = self.user or frappe.session.user

	def validate(self):
		if frappe.db.get_value("User", self.user, "user_type") != "System User":
			frappe.throw(_("Only the desk's people have choices of the company signature."))
		# The copy and its source are the server's: kept as they were, whatever the save said
		before = self.get_doc_before_save()
		self.photo = before.photo if before else None
		self.photo_source = before.photo_source if before else None

	def on_update(self):
		# The copy of the photo follows the choice: made when the person agrees, deleted when they don't
		self.refresh_photo()

	def on_trash(self):
		self.delete_copies()

	def refresh_photo(self) -> str:
		"""Make the reduced copy of the person's photo when it is out of date, or delete it when they don't agree (any
		more) or have no photo: its address, '' when there is none. A photo that can't be used is left out and logged,
		once: what it would have been made from is kept, and nothing is tried again until it changes."""
		from frappe_webmail import signature_photos

		if not self.photo_allowed:
			self.delete_copies()
			self.write_photo(None, None)
			return ""
		src, doctype, name = signature_photos.source_of(self.user)
		made_from = signature_photos.fingerprint_of(src)
		if made_from == (self.photo_source or "") and (
			not self.photo or signature_photos.copy_on_disk(self.photo)
		):
			return self.photo or ""

		content, why = None, None
		if src:
			path = signature_photos.usable_path(src, doctype, name)
			if not path:
				why = (
					"it is not a file of this instance that may be used: a public picture of the User record, or a "
					"picture of the Employee record attached to it"
				)
			else:
				try:
					content = signature_photos.reduced(path)
				except Exception:
					why = frappe.get_traceback()
		if why:
			frappe.log_error(
				"Email signature photo could not be read",
				f"The photo of {self.user} ({src}) is left out of the company signature: {why}",
			)
		if not content:
			self.delete_copies()
			self.write_photo(None, made_from)
			return ""

		made = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"signature-photo-{frappe.generate_hash(length=10)}.png",
				"content": content,
				"is_private": 1,
				"attached_to_doctype": PREFERENCE,
				"attached_to_name": self.name,
				"attached_to_field": "photo",
			}
		).insert(ignore_permissions=True)
		# The person's own file, whoever made it (a worker started by a manager's preview, a manager ticking the box):
		# where the Drive decides who reads a file (suite), the owner reads it, and nobody else but a manager
		if made.owner != self.user:
			frappe.db.set_value("File", made.name, "owner", self.user, update_modified=False)
		# By its record: Frappe gives the same bytes the same address, and keeps them on the disk while a record has them
		self.delete_copies(keep=made.name)
		self.write_photo(made.file_url, made_from)
		return made.file_url

	def write_photo(self, photo: str | None, made_from: str | None):
		"""The copy's address and what it was made from, written as they are (no save: validate would put them back)."""
		if (self.photo or None, self.photo_source or None) != (photo or None, made_from or None):
			self.db_set({"photo": photo or None, "photo_source": made_from or None}, update_modified=False)

	def delete_copies(self, keep: str | None = None):
		"""Delete the copies of the person's photo (their File records), all but the one named `keep`."""
		for name in frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": PREFERENCE,
				"attached_to_name": self.name,
				"attached_to_field": "photo",
			},
			pluck="name",
		):
			if name != keep:
				frappe.delete_doc("File", name, force=True, ignore_permissions=True)


def has_permission(doc, ptype="read", user=None):
	"""A person's choices are theirs, and a System Manager's: nobody else reads or changes them. A new record is made
	for whoever makes it (before_insert)."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	if not doc.user:
		return ptype == "create"
	return doc.user == user


def get_permission_query_conditions(user=None):
	"""The lists show a person their own record only; a System Manager all of them."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	return f"(`tab{PREFERENCE}`.user = {frappe.db.escape(user)})"


def on_user_trash(doc, method=None):
	"""A person deleted takes their choices and the copy of their photo with them: the record links to them, and would
	keep them from being deleted."""
	if not frappe.db.table_exists(PREFERENCE):
		return
	name = frappe.db.get_value(PREFERENCE, {"user": doc.name}, "name")
	if name:
		frappe.delete_doc(PREFERENCE, name, force=True, ignore_permissions=True)
