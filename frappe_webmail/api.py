# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Frappe Webmail API

This module provides the API endpoints for the webmail client,
including IMAP/SMTP operations, email management, and signatures.
"""

import base64
import email
import smtplib
from email import encoders
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import frappe
from frappe import _

try:
	import bleach
except ImportError:
	bleach = None

try:
	from imapclient import IMAPClient
except ImportError:
	IMAPClient = None


# ============================================
# ACCOUNT MANAGEMENT
# ============================================


@frappe.whitelist()
def get_accounts():
	"""Get all email accounts for current user"""
	return frappe.get_all(
		"Webmail Account",
		filters={"user": frappe.session.user, "enabled": 1},
		fields=["name", "email", "sender_name", "default_signature"],
	)


@frappe.whitelist()
def test_connection(account_name):
	"""Test IMAP/SMTP connection for an account"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	errors = []

	# Test IMAP
	try:
		with IMAPClient(
			host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
		) as client:
			client.login(account.email, account.get_password("imap_password"))
	except Exception as e:
		errors.append(f"IMAP: {str(e)}")

	# Test SMTP
	try:
		smtp_class = smtplib.SMTP_SSL if account.smtp_ssl else smtplib.SMTP
		with smtp_class(account.smtp_host, account.smtp_port, timeout=10) as server:
			if account.smtp_starttls and not account.smtp_ssl:
				server.starttls()
			server.login(account.email, account.get_password("smtp_password"))
	except Exception as e:
		errors.append(f"SMTP: {str(e)}")

	if errors:
		return {"success": False, "errors": errors}
	return {"success": True, "message": _("Connection successful")}


# ============================================
# FOLDERS
# ============================================


@frappe.whitelist()
def get_folders(account_name):
	"""List IMAP folders for an account"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		folders = client.list_folders()

		result = []
		for flags, delimiter, name in folders:
			result.append(
				{
					"name": name,
					"delimiter": delimiter.decode() if isinstance(delimiter, bytes) else delimiter,
					"flags": [f.decode() if isinstance(f, bytes) else f for f in flags],
					"selectable": b"\\Noselect" not in flags,
				}
			)

		return result


# ============================================
# EMAILS - LIST
# ============================================


@frappe.whitelist()
def get_emails(account_name, folder="INBOX", limit=50, offset=0, search=None):
	"""Get emails from a folder with pagination"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	limit = min(int(limit), 100)  # Max 100 per request
	offset = int(offset)

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		client.select_folder(folder)

		# Search criteria
		if search:
			criteria = ["OR", "OR", ["SUBJECT", search], ["FROM", search], ["TO", search]]
		else:
			criteria = ["NOT", "DELETED"]

		messages = client.search(criteria)
		total = len(messages)

		# Pagination (newest first)
		messages = list(reversed(messages))
		page = messages[offset : offset + limit]

		if not page:
			return {"emails": [], "total": total, "has_more": False}

		# Fetch envelope data
		data = client.fetch(page, ["ENVELOPE", "FLAGS", "BODYSTRUCTURE", "RFC822.SIZE"])

		emails = []
		for uid in page:  # Maintain order
			if uid not in data:
				continue
			msg_data = data[uid]
			env = msg_data[b"ENVELOPE"]
			flags = msg_data[b"FLAGS"]

			emails.append(
				{
					"uid": uid,
					"subject": decode_mime_header(env.subject),
					"from_email": format_address(env.from_[0]) if env.from_ else "",
					"from_name": (
						decode_mime_header(env.from_[0].name)
						if env.from_ and env.from_[0].name
						else ""
					),
					"to": format_address(env.to[0]) if env.to else "",
					"date": env.date.isoformat() if env.date else None,
					"seen": b"\\Seen" in flags,
					"flagged": b"\\Flagged" in flags,
					"answered": b"\\Answered" in flags,
					"has_attachments": has_attachments(msg_data.get(b"BODYSTRUCTURE")),
					"size": msg_data.get(b"RFC822.SIZE", 0),
				}
			)

		return {"emails": emails, "total": total, "has_more": offset + limit < total}


# ============================================
# EMAILS - READ
# ============================================


@frappe.whitelist()
def get_email_content(account_name, uid, folder="INBOX", mark_read=True):
	"""Get full email content"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uid = int(uid)

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		client.select_folder(folder)

		# Mark as read
		if mark_read:
			client.add_flags([uid], [b"\\Seen"])

		# Fetch full message
		data = client.fetch([uid], ["RFC822", "ENVELOPE", "FLAGS"])

		if uid not in data:
			frappe.throw(_("Email not found"))

		raw = data[uid][b"RFC822"]
		msg = email.message_from_bytes(raw)
		env = data[uid][b"ENVELOPE"]
		flags = data[uid][b"FLAGS"]

		# Parse content
		html_content = None
		text_content = None
		attachments = []
		inline_images = {}

		for part in msg.walk():
			content_type = part.get_content_type()
			content_disposition = str(part.get("Content-Disposition", ""))
			content_id = part.get("Content-ID", "").strip("<>")

			if "attachment" in content_disposition:
				payload = part.get_payload(decode=True)
				attachments.append(
					{
						"id": content_id or str(len(attachments)),
						"filename": decode_mime_header(part.get_filename())
						or f"attachment_{len(attachments)}",
						"content_type": content_type,
						"size": len(payload) if payload else 0,
					}
				)
			elif content_type.startswith("image/") and content_id:
				# Inline image
				payload = part.get_payload(decode=True)
				if payload:
					inline_images[content_id] = (
						f"data:{content_type};base64,{base64.b64encode(payload).decode()}"
					)
			elif content_type == "text/html":
				payload = part.get_payload(decode=True)
				if payload:
					charset = part.get_content_charset() or "utf-8"
					html_content = payload.decode(charset, errors="replace")
			elif content_type == "text/plain" and not html_content:
				payload = part.get_payload(decode=True)
				if payload:
					charset = part.get_content_charset() or "utf-8"
					text_content = payload.decode(charset, errors="replace")

		# Replace CID references with inline data
		if html_content and inline_images:
			for cid, data_uri in inline_images.items():
				html_content = html_content.replace(f"cid:{cid}", data_uri)

		return {
			"uid": uid,
			"message_id": msg.get("Message-ID", ""),
			"subject": decode_mime_header(env.subject),
			"from_email": format_address(env.from_[0]) if env.from_ else "",
			"from_name": (
				decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else ""
			),
			"to": ", ".join([format_address(a) for a in (env.to or [])]),
			"cc": ", ".join([format_address(a) for a in (env.cc or [])]),
			"reply_to": format_address(env.reply_to[0]) if env.reply_to else "",
			"date": env.date.isoformat() if env.date else None,
			"html": html_content,
			"text": text_content,
			"attachments": attachments,
			"seen": b"\\Seen" in flags,
			"flagged": b"\\Flagged" in flags,
		}


# ============================================
# EMAILS - SEND
# ============================================


@frappe.whitelist()
def send_email(
	account_name,
	to,
	subject,
	html_content,
	cc=None,
	bcc=None,
	reply_to_message_id=None,
	attachments=None,
):
	"""Send an email"""
	account = get_account(account_name)

	# Sanitize HTML content if bleach is available
	if bleach:
		# Allow safe HTML tags for email
		allowed_tags = [
			"a",
			"abbr",
			"acronym",
			"b",
			"blockquote",
			"br",
			"code",
			"div",
			"em",
			"h1",
			"h2",
			"h3",
			"h4",
			"h5",
			"h6",
			"hr",
			"i",
			"img",
			"li",
			"ol",
			"p",
			"pre",
			"span",
			"strong",
			"table",
			"tbody",
			"td",
			"th",
			"thead",
			"tr",
			"u",
			"ul",
		]
		allowed_attributes = {
			"*": ["class", "style"],
			"a": ["href", "title", "target", "rel"],
			"img": ["src", "alt", "width", "height"],
			"table": ["border", "cellpadding", "cellspacing", "width"],
			"td": ["colspan", "rowspan", "width", "valign", "align"],
			"th": ["colspan", "rowspan", "width", "valign", "align"],
		}
		html_content = bleach.clean(
			html_content, tags=allowed_tags, attributes=allowed_attributes, strip=True
		)

	# Build message
	msg = MIMEMultipart("mixed")
	msg["From"] = (
		f'"{account.sender_name}" <{account.email}>'
		if account.sender_name
		else account.email
	)
	msg["To"] = to
	msg["Subject"] = subject

	if cc:
		msg["Cc"] = cc

	if reply_to_message_id:
		msg["In-Reply-To"] = reply_to_message_id
		msg["References"] = reply_to_message_id

	# Body (multipart/alternative for text + html)
	body = MIMEMultipart("alternative")

	# Plain text version
	if bleach:
		text_content = bleach.clean(html_content, tags=[], strip=True)
	else:
		# Simple HTML stripping if bleach not available
		import re

		text_content = re.sub(r"<[^>]+>", "", html_content)

	body.attach(MIMEText(text_content, "plain", "utf-8"))

	# HTML version
	body.attach(MIMEText(html_content, "html", "utf-8"))
	msg.attach(body)

	# Attachments
	if attachments:
		for att in frappe.parse_json(attachments):
			# att = {"filename": "...", "data": "base64...", "content_type": "..."}
			part = MIMEBase("application", "octet-stream")
			part.set_payload(base64.b64decode(att["data"]))
			encoders.encode_base64(part)
			part.add_header("Content-Disposition", f'attachment; filename="{att["filename"]}"')
			msg.attach(part)

	# Send via SMTP
	try:
		if account.smtp_ssl:
			server = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=30)
		else:
			server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=30)
			if account.smtp_starttls:
				server.starttls()

		server.login(account.email, account.get_password("smtp_password"))

		recipients = [r.strip() for r in to.split(",")]
		if cc:
			recipients.extend([r.strip() for r in cc.split(",")])
		if bcc:
			recipients.extend([r.strip() for r in bcc.split(",")])

		server.sendmail(account.email, recipients, msg.as_string())
		server.quit()

		return {"success": True, "message": _("Email sent successfully")}

	except Exception as e:
		frappe.log_error(f"Email send error: {str(e)}", "Frappe Webmail")
		frappe.throw(_("Failed to send email: {0}").format(str(e)))


# ============================================
# EMAILS - ACTIONS
# ============================================


@frappe.whitelist()
def set_flags(account_name, uids, folder, add_flags=None, remove_flags=None):
	"""Set or remove flags on emails"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uids = frappe.parse_json(uids) if isinstance(uids, str) else uids

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		client.select_folder(folder)

		if add_flags:
			flags = [
				f.encode() if isinstance(f, str) else f for f in frappe.parse_json(add_flags)
			]
			client.add_flags(uids, flags)

		if remove_flags:
			flags = [
				f.encode() if isinstance(f, str) else f for f in frappe.parse_json(remove_flags)
			]
			client.remove_flags(uids, flags)

		return {"success": True}


@frappe.whitelist()
def move_emails(account_name, uids, from_folder, to_folder):
	"""Move emails to another folder"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uids = frappe.parse_json(uids) if isinstance(uids, str) else uids

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		client.select_folder(from_folder)

		# Copy then delete
		client.copy(uids, to_folder)
		client.add_flags(uids, [b"\\Deleted"])
		client.expunge()

		return {"success": True}


@frappe.whitelist()
def delete_emails(account_name, uids, folder, permanent=False):
	"""Delete emails (move to trash or permanent)"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uids = frappe.parse_json(uids) if isinstance(uids, str) else uids

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		client.select_folder(folder)

		if permanent:
			client.add_flags(uids, [b"\\Deleted"])
			client.expunge()
		else:
			# Try to find trash folder
			folders = client.list_folders()
			trash_folder = None
			for flags, _, name in folders:
				if b"\\Trash" in flags or name.lower() in [
					"trash",
					"corbeille",
					"deleted",
					"deleted items",
				]:
					trash_folder = name
					break

			if trash_folder and folder != trash_folder:
				client.copy(uids, trash_folder)

			client.add_flags(uids, [b"\\Deleted"])
			client.expunge()

		return {"success": True}


@frappe.whitelist()
def get_attachment(account_name, uid, folder, attachment_id):
	"""Download an attachment"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uid = int(uid)

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		client.login(account.email, account.get_password("imap_password"))
		client.select_folder(folder)

		data = client.fetch([uid], ["RFC822"])

		if uid not in data:
			frappe.throw(_("Email not found"))

		raw = data[uid][b"RFC822"]
		msg = email.message_from_bytes(raw)

		# Find the attachment
		idx = 0
		for part in msg.walk():
			content_disposition = str(part.get("Content-Disposition", ""))
			content_id = part.get("Content-ID", "").strip("<>")

			if "attachment" in content_disposition:
				current_id = content_id or str(idx)
				if current_id == attachment_id:
					payload = part.get_payload(decode=True)
					filename = decode_mime_header(part.get_filename()) or f"attachment_{idx}"
					content_type = part.get_content_type()

					return {
						"filename": filename,
						"content_type": content_type,
						"data": base64.b64encode(payload).decode(),
						"size": len(payload),
					}
				idx += 1

		frappe.throw(_("Attachment not found"))


# ============================================
# SIGNATURES
# ============================================


@frappe.whitelist()
def get_signatures():
	"""Get all signatures for current user"""
	return frappe.get_all(
		"Email Signature",
		filters={"user": frappe.session.user},
		fields=["name", "signature_name", "content", "is_default"],
		order_by="is_default desc, signature_name asc",
	)


@frappe.whitelist()
def get_default_signature():
	"""Get default signature content"""
	sig = frappe.db.get_value(
		"Email Signature", {"user": frappe.session.user, "is_default": 1}, "content"
	)
	return sig or ""


# ============================================
# HELPERS
# ============================================


def get_account(account_name):
	"""Get and validate email account"""
	if not frappe.db.exists("Webmail Account", account_name):
		frappe.throw(_("Account not found"))

	account = frappe.get_doc("Webmail Account", account_name)

	if account.user != frappe.session.user:
		frappe.throw(_("Access denied"))

	if not account.enabled:
		frappe.throw(_("Account is disabled"))

	return account


def decode_mime_header(header):
	"""Decode MIME encoded header"""
	if not header:
		return ""
	if isinstance(header, bytes):
		header = header.decode("utf-8", errors="replace")

	try:
		decoded_parts = decode_header(header)
		result = []
		for part, charset in decoded_parts:
			if isinstance(part, bytes):
				result.append(part.decode(charset or "utf-8", errors="replace"))
			else:
				result.append(part)
		return "".join(result)
	except Exception:
		return str(header)


def format_address(addr):
	"""Format email address from IMAP envelope"""
	if not addr:
		return ""
	try:
		mailbox = addr.mailbox.decode() if isinstance(addr.mailbox, bytes) else addr.mailbox
		host = addr.host.decode() if isinstance(addr.host, bytes) else addr.host
		return f"{mailbox}@{host}"
	except Exception:
		return ""


def has_attachments(bodystructure):
	"""Check if email has attachments from BODYSTRUCTURE"""
	if not bodystructure:
		return False

	def check_part(part):
		if isinstance(part, tuple):
			if len(part) >= 2:
				# Check for attachment disposition
				for item in part:
					if isinstance(item, tuple) and len(item) >= 2:
						if (
							item[0]
							and isinstance(item[0], bytes)
							and item[0].lower() == b"attachment"
						):
							return True
					if isinstance(item, tuple):
						if check_part(item):
							return True
		return False

	return check_part(bodystructure)
