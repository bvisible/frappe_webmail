# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The person's photo in the company signature (the "Photo left" layout, signatures.py).

Never without the person's consent: it is drawn only for a person whose Email Signature Preference says `photo_allowed`,
a choice that is theirs (and a System Manager's) to make and theirs to take back; taken back, the copy is deleted.

The photo is their Employee's picture (`image`) when it has one, else their User's (`user_image`), and only a picture of
the instance's own files: a picture elsewhere on the web is not fetched. The User's must be a public file: a person can
point their own User's picture at any address, and Frappe lets anyone make a File record of any address, which would
pass for theirs; the copy would then be theirs to read. A private picture is taken only from the Employee record, the
one HR chose and the person cannot point elsewhere, and only as a File attached to that very record.

What a message carries is a reduced copy, never the source: a square of PHOTO_SIZE pixels cut from it (a little above
its middle, where a portrait has the face), upright, round by its own pixels (a PNG transparent outside the circle:
every mail client shows it round, Outlook on Windows too), without the source's metadata (a phone's photo says where
it was taken), kept as a private File attached to the person's preference. It is made once, and again only when its
source changes (its address, its size or its time on the disk: `photo_source`): when the person agrees (their
preference's on_update), and, when a signature finds its copy out of date, by a worker (`refresh_later`: a signature is
often written while a page is read, and what a page's request writes is rolled back). A source that can't be read
leaves the photo out and is logged once: the preference keeps what the copy would have been made from, and nothing is
tried again until the source changes.
"""

import io
import os
from urllib.parse import unquote

import frappe

from frappe_webmail import signatures
from frappe_webmail.signatures import PHOTO_SIZE, PREFERENCE

# The largest source read: its file on the disk, and its pixels (a picture that says it has more is not decoded)
MAX_SOURCE_BYTES = 20 << 20
MAX_SOURCE_PIXELS = 40_000_000
# Where the square is cut from a picture taller or wider than it: across, the middle; down, a little above it
PORTRAIT_CENTRE = (0.5, 0.4)
# What a copy is, part of what it is made from (fingerprint_of): a copy of another kind, the square JPEG of before, is
# made again the next time the signature is written
COPY_KIND = "round-png"
# The background job that makes a copy again, one waiting at a time for each person
JOB = "frappe_webmail.signature_photos.refresh"


def source_of(user: str, employee=None, account=None) -> tuple[str, str | None, str | None]:
	"""The person's photo as stored, and the record that names it (its doctype and name): their Employee's picture when
	it has one, else their User's; ("", None, None) when neither has one. `employee` and `account` are those records'
	values when the caller has them (person_of)."""
	if employee is None:
		employee = signatures._employee_of(user)
	if account is None:
		account = frappe.db.get_value("User", user, ["user_image"], as_dict=True) or frappe._dict()
	image = (employee.get("image") or "").strip()
	if image and employee.get("name"):
		return image, "Employee", employee.get("name")
	image = (account.get("user_image") or "").strip()
	if image:
		return image, "User", user
	return "", None, None


def fingerprint_of(src: str) -> str:
	"""What a copy is made from, to tell when its source changed: the source's address, and the size and the time of
	its file on the disk when it is a file of the instance, and what kind of copy is made of it ('' for no source)."""
	if not src:
		return ""
	path = signatures._file_on_disk(src)
	try:
		found = os.stat(path) if path else None
	except OSError:
		found = None
	made_from = f"{src}|{found.st_size}|{found.st_mtime_ns}" if found else src
	return f"{made_from}|{COPY_KIND}"


def copy_on_disk(photo: str | None) -> bool:
	"""Whether the reduced copy at that address is a file of the instance still on the disk."""
	path = signatures._file_on_disk(photo) if signatures._plain_instance_file(photo) else None
	return bool(path and os.path.isfile(path))


def photo_state(user: str, choices, employee=None, account=None) -> tuple[str, str]:
	"""The address of the person's reduced photo and how it stands: ("<address>", "ready"); else "" and why there is
	none: "off" (they did not agree), "missing" (no photo of them in Neoffice), "unreadable" (one that can't be used),
	or "pending" (its source changed since the copy was made: a worker is asked to make it again). `choices` is their
	preference (signatures.preference_of). It writes nothing itself: it is asked while a page is read."""
	if not choices.photo_allowed:
		return "", "off"
	src, _doctype, _name = source_of(user, employee, account)
	made_from = choices.photo_source or ""
	photo = (choices.photo or "").strip()
	if fingerprint_of(src) == made_from:
		if photo and copy_on_disk(photo):
			return photo, "ready"
		if not photo:
			return "", "unreadable" if src else "missing"
	elif not src and not photo and not made_from:
		# No photo now, and none ever made: nothing to do
		return "", "missing"
	refresh_later(user)
	return "", "pending" if src else "missing"


def photo_of(user: str, choices, employee=None, account=None) -> str:
	"""The address of the person's reduced photo when they agreed to show it and it is ready, '' otherwise (photo_state)."""
	return photo_state(user, choices, employee, account)[0]


def sent_photo(user: str) -> str | None:
	"""The person's own reduced photo, as a message they send may carry it (inline_images.sender_photo): only when they
	agree to show it, and only the copy made for them, a File attached to their own preference; None otherwise."""
	if not frappe.db.table_exists(PREFERENCE):
		return None
	found = frappe.db.get_value(PREFERENCE, {"user": user}, ["name", "photo_allowed", "photo"], as_dict=True)
	if not found or not found.photo_allowed or not signatures._plain_instance_file(found.photo):
		return None
	made = frappe.db.exists(
		"File",
		{
			"file_url": found.photo,
			"attached_to_doctype": PREFERENCE,
			"attached_to_name": found.name,
			"is_folder": 0,
		},
	)
	return found.photo if made else None


def refresh_later(user: str) -> None:
	"""Ask a worker to make the person's copy again (refresh), one such job waiting at a time for each person. A queue
	that can't be reached leaves the photo out, and the log says why."""
	try:
		frappe.enqueue(
			JOB,
			queue="short",
			job_id=f"email-signature-photo::{user}",
			deduplicate=True,
			user=user,
		)
	except Exception:
		frappe.log_error("Email signature photo could not be queued", frappe.get_traceback())


def refresh(user: str) -> str:
	"""Make the person's reduced photo again when its source changed, or delete it when they took back their consent or
	have no photo any more: its address ('' when there is none). The worker's job (refresh_later)."""
	name = frappe.db.get_value(PREFERENCE, {"user": user}, "name")
	return frappe.get_doc(PREFERENCE, name).refresh_photo() if name else ""


def usable_path(src: str, doctype: str | None, name: str | None) -> str | None:
	"""The path on the disk of the person's photo when it may be used: a public file of the instance; a private one only
	as the picture of their Employee record (`doctype`, `name`), a File of that address attached to it. None otherwise:
	an address elsewhere (nothing is fetched), a file gone from the disk, a private picture of their User record (the
	module's notes: one the person may name at will, and make a File record of)."""
	src = signatures._plain_instance_file(src)
	path = signatures._file_on_disk(src) if src else None
	if not path or not os.path.isfile(path):
		return None
	if not src.startswith("/private/files/"):
		return path
	if doctype != "Employee" or not name:
		return None
	address = unquote(src.split("?", 1)[0])
	# The database compares addresses without case or accents: only a row of this very address is this file
	rows = frappe.get_all(
		"File",
		filters={
			"file_url": address,
			"is_folder": 0,
			"attached_to_doctype": "Employee",
			"attached_to_name": name,
		},
		fields=["file_url"],
		limit=20,
	)
	return path if any(row.file_url == address for row in rows) else None


def reduced(path: str) -> bytes:
	"""The reduced copy of the picture at `path`: a square of PHOTO_SIZE pixels cut from it, upright (a phone's photo says
	which way is up), a transparent picture on white, as a round PNG (transparent outside the circle, its edge smoothed),
	without the source's metadata. Raises ValueError for a
	file or a picture too big, and Pillow's or the system's errors for a file that is no picture Pillow reads."""
	from PIL import Image, ImageDraw, ImageOps

	if os.path.getsize(path) > MAX_SOURCE_BYTES:
		raise ValueError(f"the file is larger than {MAX_SOURCE_BYTES} bytes")
	with Image.open(path) as source:
		if source.width * source.height > MAX_SOURCE_PIXELS:
			raise ValueError(f"the picture has more than {MAX_SOURCE_PIXELS} pixels")
		# A JPEG is decoded at a fraction of its size when that is still enough (a phone's photo, quickly)
		source.draft("RGB", (PHOTO_SIZE * 4, PHOTO_SIZE * 4))
		upright = ImageOps.exif_transpose(source).convert("RGBA")
	flat = Image.alpha_composite(Image.new("RGBA", upright.size, (255, 255, 255, 255)), upright).convert(
		"RGB"
	)
	square = ImageOps.fit(
		flat, (PHOTO_SIZE, PHOTO_SIZE), method=Image.Resampling.LANCZOS, centering=PORTRAIT_CENTRE
	)
	# Round by its own pixels: the circle drawn four times as large, then averaged down, so that its edge is smooth
	mask = Image.new("L", (PHOTO_SIZE * 4, PHOTO_SIZE * 4), 0)
	ImageDraw.Draw(mask).ellipse((0, 0, PHOTO_SIZE * 4 - 1, PHOTO_SIZE * 4 - 1), fill=255)
	round_copy = square.convert("RGBA")
	round_copy.putalpha(mask.resize((PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.BOX))
	buffer = io.BytesIO()
	round_copy.save(buffer, "PNG", optimize=True)
	return buffer.getvalue()
