# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The webmail's door into the Neoffice Drive (the `suite` app): the folders a person may file into, and putting the
bytes of an attachment in one of them.

The Drive is Frappe's own File doctype as suite extends it: a folder is a File row (`is_folder`), the shared tree hangs
from « Drive », each person's private tree from « Users/<user> », and `user_has_permission(folder, "upload")` decides
who may add to a folder (owner, explicit grant, inherited share; a deny wins). suite only takes a file from a browser
(a multipart, chunked upload), so `deposit` repeats the steps of `suite.drive.api.files.upload_file` for bytes the
server already holds: the right to the folder, the owner's quota under its lock, a name free in the folder, the row,
the bytes in place (or on S3) with their thumbnail, the folder sizes, the person's live list.

Every import from suite is made in this module: a change on its side breaks here, under this module's tests (run on a
site with suite, the clone of osiris; the app's own CI installs no suite and skips them).
"""

import os
from pathlib import Path

import frappe
from frappe import _

# How deep a search result's path is spelled out (« Mon Drive / Clients / … »)
PATH_DEPTH = 6
# A file name the Drive can store: what a sender wrote, without what would cut a path
UNSAFE_IN_NAME = str.maketrans({"/": "-", "\\": "-", "\x00": "", "\r": " ", "\n": " ", "\t": " "})


def available() -> bool:
	return "suite" in frappe.get_installed_apps()


def _require():
	if not available():
		frappe.throw(_("The Drive is not installed on this instance"))


def can_upload(folder) -> bool:
	from suite.drive.api.permissions import user_has_permission

	return bool(user_has_permission(folder, "upload"))


def can_read(folder) -> bool:
	from suite.drive.api.permissions import user_has_permission

	return bool(user_has_permission(folder, "read"))


def _folder_row(folder):
	row = frappe.db.get_value(
		"File", folder, ["name", "file_name", "folder", "is_folder", "status"], as_dict=True
	)
	if not row or not row.is_folder or (row.status and row.status != "Active"):
		return None
	return row


def _has_subfolders(folder) -> bool:
	return bool(frappe.db.exists("File", {"folder": folder, "is_folder": 1, "status": "Active"}))


def _entry(row, kind="folder", title=None, path=None):
	return {
		"name": row.name,
		"title": title or row.file_name,
		"kind": kind,
		"can_write": can_upload(row.name),
		"has_children": _has_subfolders(row.name),
		"path": path,
	}


def _path(row) -> str:
	"""« Mon Drive / Clients / Garage » for a folder found by a search: where it is, in the person's words."""
	from suite.drive.utils import get_user_folder

	home = get_user_folder().name
	parts = []
	current = row
	for _depth in range(PATH_DEPTH):
		if current.name == home:
			parts.append(_("My Drive"))
			break
		parts.append(current.file_name)
		if not current.folder:
			break
		current = frappe.db.get_value("File", current.folder, ["name", "file_name", "folder"], as_dict=True)
		if not current:
			break
	return " / ".join(reversed(parts))


def roots() -> list[dict]:
	"""Where the folder tree starts for this person: their own Drive, the shared Drive, what was shared with them."""
	from suite.drive.utils import get_root_folder as shared_root
	from suite.drive.utils import get_user_folder

	out = [_entry(get_user_folder(), kind="home", title=_("My Drive"))]
	shared = shared_root()
	if can_read(shared.name):
		out.append(_entry(shared, kind="shared_drive", title=_("Shared Drive")))
	shared_with_me = _shared_folders()
	if shared_with_me:
		out.append(
			{
				"name": "__shared_with_me__",
				"title": _("Shared with me"),
				"kind": "shared_with_me",
				"can_write": False,
				"has_children": True,
				"path": None,
			}
		)
	return out


def _shared_folders():
	"""Folders shared explicitly with the person (or a group of theirs), not their own: suite's own query."""
	from suite.drive.api.list import shared

	rows = shared(shared_type="with", file_kinds='["Folder"]') or []
	if isinstance(rows, dict):  # paginated shape
		rows = rows.get("rows") or []
	# file_kinds already keeps the folders; a row that says otherwise is not one
	return [r for r in rows if r.get("is_folder", 1)]


def children(parent) -> list[dict]:
	"""The subfolders of `parent` the person may see, with whether they may file into each."""
	if parent == "__shared_with_me__":
		return [
			_entry(frappe._dict(name=r["name"], file_name=r.get("file_name") or r.get("title")))
			for r in _shared_folders()
		]
	row = _folder_row(parent)
	if not row or not can_read(row.name):
		frappe.throw(_("This folder no longer exists in the Drive"), frappe.DoesNotExistError)
	rows = frappe.get_all(
		"File",
		filters={"folder": row.name, "is_folder": 1, "status": "Active"},
		fields=["name", "file_name", "folder"],
		order_by="file_name asc",
		limit=500,
	)
	return [_entry(r) for r in rows if can_read(r.name)]


def search(text, limit=30) -> list[dict]:
	"""Folders whose name contains `text`, among those the person may file into, with their path."""
	text = (text or "").strip()
	if not text:
		return []
	rows = frappe.get_all(
		"File",
		filters={"is_folder": 1, "status": "Active", "file_name": ["like", f"%{text}%"]},
		fields=["name", "file_name", "folder"],
		order_by="modified desc",
		limit=200,
	)
	out = []
	for row in rows:
		if can_upload(row.name):
			out.append(_entry(row, path=_path(row)))
			if len(out) >= limit:
				break
	return out


def folder_entry(folder):
	"""One folder as the picker shows it, or None if it is gone or may no longer be filed into."""
	row = _folder_row(folder) if folder else None
	if not row or not can_upload(row.name):
		return None
	return _entry(row, path=_path(row))


def free_name(file_name, folder) -> str:
	"""A name not yet taken in `folder`: « Facture.pdf », else « Facture (1).pdf », « Facture (2).pdf »…

	Unfiltered on purpose: suite's own get_new_file_name counts siblings with frappe.db.get_list, which only sees the
	rows the person may read, and so can miss a sibling in a shared folder (and, with a non-flat storage, overwrite its
	bytes)."""
	stem, ext = os.path.splitext(file_name)
	taken = set(
		frappe.get_all(
			"File",
			filters={"folder": folder, "status": "Active", "file_name": ["like", f"{stem}%{ext}"]},
			pluck="file_name",
		)
	)
	if file_name not in taken:
		return file_name
	n = 1
	while f"{stem} ({n}){ext}" in taken:
		n += 1
	return f"{stem} ({n}){ext}"


def safe_name(file_name) -> str:
	name = (file_name or "").translate(UNSAFE_IN_NAME).strip(" .") or "attachment"
	stem, ext = os.path.splitext(name)
	return stem[: 140 - len(ext)] + ext


def deposit(payload: bytes, file_name: str, folder: str):
	"""Put `payload` in the Drive folder `folder` as `file_name`, the way suite's own upload does. Returns the File."""
	_require()
	import mimemapper
	from suite.drive.api.files import get_upload_path
	from suite.drive.api.storage import acquire_owner_storage_lock, validate_quota
	from suite.drive.utils import apply_file_size_delta, create_drive_file, get_file_type
	from suite.drive.utils.api import prettify_file
	from suite.drive.utils.files import FileManager, get_s3_key, get_s3_url, storage_key
	from werkzeug.utils import secure_filename

	row = _folder_row(folder)
	if not row:
		frappe.throw(_("This folder no longer exists in the Drive"), frappe.DoesNotExistError)
	if not can_upload(row.name):
		frappe.throw(_("You cannot add files to this folder of the Drive"), frappe.PermissionError)

	file_name = free_name(safe_name(file_name), row.name)
	size = len(payload)
	temp_path = get_upload_path(
		f"{frappe.generate_hash(length=12)}_{secure_filename(file_name) or 'attachment'}"
	)
	temp_path.write_bytes(payload)
	try:
		acquire_owner_storage_lock(frappe.session.user)
		validate_quota(incoming_size=size)

		mime_type = mimemapper.get_mime_type(str(temp_path), native_first=False)
		manager = FileManager()
		drive_file = create_drive_file(
			file_name,
			row.name,
			get_file_type(mime_type),
			lambda file: "/" + str(manager.get_disk_path(file)),
			mime_type,
			size,
		)
		if not manager.s3_enabled:
			# A non-flat storage keeps the folder tree on disk: its directory may not exist yet (suite's WOPI does the same)
			Path(manager.site_folder / storage_key(drive_file.file_url)).parent.mkdir(
				parents=True, exist_ok=True
			)
		manager.upload_file(temp_path, drive_file)
		if manager.s3_enabled:
			drive_file.file_url = get_s3_url(get_s3_key(drive_file.file_url))
			drive_file.save()
	finally:
		# Moved into place on disk, uploaded on S3: either way nothing must stay in .uploads
		temp_path.unlink(missing_ok=True)

	apply_file_size_delta(row.name, size)
	# To the person only: suite broadcasts its uploads to every session of the site
	frappe.publish_realtime(
		"list-add", {"file": prettify_file(drive_file.as_dict())}, user=frappe.session.user
	)
	return drive_file


def create_folder(parent, title):
	"""« New folder » in the picker: made by suite's own create_folder (the right to add to the parent, no two folders
	of the same name), returned as the picker shows a folder."""
	_require()
	from suite.drive.api.files import create_folder as suite_create_folder

	row = _folder_row(parent)
	if not row:
		frappe.throw(_("This folder no longer exists in the Drive"), frappe.DoesNotExistError)
	if not can_upload(row.name):
		frappe.throw(_("You cannot add files to this folder of the Drive"), frappe.PermissionError)
	folder = suite_create_folder(safe_name(title), parent=row.name)
	return _entry(frappe._dict(name=folder.name, file_name=folder.file_name, folder=row.name))


def listing(folder=None, search=None, limit=20) -> dict:
	"""A folder's subfolders and files (the person's own Drive without a folder), or a search across what they may
	read, as suite lists them with its own rules of access. For the composer's « From the Drive »."""
	_require()
	from suite.drive.api.list import files

	rows = files(
		entity_name=folder or None, search=search or None, order_by="modified", ascending=False, limit=200
	)
	if isinstance(rows, dict):  # paginated shape
		rows = rows.get("rows") or []
	folders = sorted(
		(
			{"name": r["name"], "title": r.get("file_name"), "modified": r.get("modified")}
			for r in rows
			if r.get("is_folder")
		),
		key=lambda f: (f["title"] or "").lower(),
	)
	found = [
		{
			"name": r["name"],
			"title": r.get("file_name"),
			"file_size": r.get("file_size"),
			"mime_type": r.get("mime_type"),
			"modified": r.get("modified"),
		}
		for r in rows
		if not r.get("is_folder")
	]
	return {"folders": folders, "files": found[: int(limit)]}


def read(name):
	"""(file name, MIME type, bytes) of a Drive file the person may read: for attaching it to a message."""
	_require()
	from suite.drive.utils.files import FileManager

	row = frappe.db.get_value(
		"File", name, ["name", "file_name", "mime_type", "is_folder", "status"], as_dict=True
	)
	if not row or row.is_folder or (row.status and row.status != "Active"):
		frappe.throw(_("This file no longer exists in the Drive"), frappe.DoesNotExistError)
	if not can_read(row.name):
		frappe.throw(_("You cannot read this file of the Drive"), frappe.PermissionError)
	content = FileManager().get_file(frappe.get_doc("File", row.name)).read()
	return row.file_name, row.mime_type or "application/octet-stream", content


def file_url(name) -> str:
	return f"/drive/f/{name}"


def folder_url(name) -> str:
	return f"/drive/d/{name}"
