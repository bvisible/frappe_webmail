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
		fields=["name", "email", "sender_name", "default_signature", "auth_type", "oauth_provider"],
	)


# ============================================
# OAUTH2
# ============================================


OAUTH_PROVIDERS = {
	"Gmail": {
		"auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
		"token_url": "https://oauth2.googleapis.com/token",
		"scope": "https://mail.google.com/",
	},
	"Outlook": {
		"auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
		"token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
		"scope": "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access",
	},
}


@frappe.whitelist()
def get_oauth_authorization_url(account_name):
	"""Get OAuth authorization URL to redirect user"""
	import urllib.parse

	account = get_account(account_name)

	if account.auth_type != "OAuth2":
		frappe.throw(_("Account is not configured for OAuth2"))

	provider = OAUTH_PROVIDERS.get(account.oauth_provider)
	if not provider:
		frappe.throw(_("Unknown OAuth provider"))

	# Get OAuth credentials from site config
	oauth_config = get_oauth_config(account.oauth_provider)
	if not oauth_config:
		frappe.throw(
			_("OAuth credentials not configured. Add webmail_oauth_{0} to site_config.json").format(
				account.oauth_provider.lower()
			)
		)

	# Generate state token for security
	import secrets

	state = secrets.token_urlsafe(32)
	frappe.cache().set_value(
		f"webmail_oauth_state_{state}",
		{"account": account_name, "user": frappe.session.user},
		expires_in_sec=600,  # 10 minutes
	)

	# Build authorization URL
	redirect_uri = get_oauth_redirect_uri()

	params = {
		"client_id": oauth_config["client_id"],
		"redirect_uri": redirect_uri,
		"response_type": "code",
		"scope": provider["scope"],
		"state": state,
		"access_type": "offline",  # For refresh token
		"prompt": "consent",  # Force consent to get refresh token
	}

	# Outlook specific
	if account.oauth_provider == "Outlook":
		params["login_hint"] = account.email

	auth_url = f"{provider['auth_url']}?{urllib.parse.urlencode(params)}"

	return {"authorization_url": auth_url, "state": state}


@frappe.whitelist(allow_guest=True)
def oauth_callback(code=None, state=None, error=None):
	"""Handle OAuth callback from provider"""
	import requests

	if error:
		frappe.throw(_("OAuth error: {0}").format(error))

	if not code or not state:
		frappe.throw(_("Invalid OAuth callback"))

	# Verify state
	state_data = frappe.cache().get_value(f"webmail_oauth_state_{state}")
	if not state_data:
		frappe.throw(_("Invalid or expired OAuth state"))

	frappe.cache().delete_value(f"webmail_oauth_state_{state}")

	account_name = state_data["account"]
	user = state_data["user"]

	# Get account
	account = frappe.get_doc("Webmail Account", account_name)
	if account.user != user:
		frappe.throw(_("Access denied"))

	provider = OAUTH_PROVIDERS.get(account.oauth_provider)
	oauth_config = get_oauth_config(account.oauth_provider)

	redirect_uri = get_oauth_redirect_uri()

	# Exchange code for tokens
	try:
		response = requests.post(
			provider["token_url"],
			data={
				"client_id": oauth_config["client_id"],
				"client_secret": oauth_config["client_secret"],
				"code": code,
				"redirect_uri": redirect_uri,
				"grant_type": "authorization_code",
			},
			timeout=30,
		)

		if response.status_code != 200:
			frappe.log_error(f"OAuth token exchange failed: {response.text}", "Webmail OAuth")
			frappe.throw(_("Failed to get OAuth tokens"))

		data = response.json()

		# Save tokens
		account.oauth_access_token = data["access_token"]
		if "refresh_token" in data:
			account.oauth_refresh_token = data["refresh_token"]

		expires_in = data.get("expires_in", 3600)
		account.oauth_token_expiry = frappe.utils.add_to_date(
			frappe.utils.now_datetime(), seconds=expires_in
		)
		account.oauth_status = "Connected"

		account.save(ignore_permissions=True)
		frappe.db.commit()

		# Redirect to webmail with success message
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"/app/webmail-account/{account_name}?oauth=success"

	except requests.RequestException as e:
		frappe.log_error(f"OAuth error: {str(e)}", "Webmail OAuth")
		frappe.throw(_("OAuth authentication failed"))


@frappe.whitelist()
def disconnect_oauth(account_name):
	"""Disconnect OAuth and clear tokens"""
	account = get_account(account_name)

	if account.auth_type != "OAuth2":
		frappe.throw(_("Account is not using OAuth2"))

	account.oauth_access_token = ""
	account.oauth_refresh_token = ""
	account.oauth_token_expiry = None
	account.oauth_status = "Disconnected"

	account.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


def get_oauth_config(provider):
	"""Get OAuth credentials from site config"""
	config_key = f"webmail_oauth_{provider.lower()}"
	config = frappe.conf.get(config_key, {})

	if not config.get("client_id") or not config.get("client_secret"):
		return None

	return config


def get_oauth_redirect_uri():
	"""Get the OAuth redirect URI"""
	return frappe.utils.get_url("/api/method/frappe_webmail.api.oauth_callback")


def imap_login(client, account):
	"""Login to IMAP server using password or OAuth2"""
	if account.auth_type == "OAuth2":
		access_token = account.get_oauth_access_token()
		if not access_token:
			frappe.throw(_("OAuth token not available. Please reconnect your account."))

		client.oauth2_login(account.email, access_token)
	else:
		# Password authentication
		password = account.get_password("imap_password")
		client.login(account.email, password)


def smtp_login(server, account):
	"""Login to SMTP server using password or OAuth2"""
	if account.auth_type == "OAuth2":
		access_token = account.get_oauth_access_token()
		if not access_token:
			frappe.throw(_("OAuth token not available. Please reconnect your account."))

		# Build XOAUTH2 authentication string
		auth_string = build_xoauth2_string(account.email, access_token)
		server.auth("XOAUTH2", lambda x: auth_string)
	else:
		# Password authentication
		password = account.get_password("smtp_password")
		server.login(account.email, password)


def build_xoauth2_string(user, access_token):
	"""Build XOAUTH2 authentication string for SMTP"""
	auth_string = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
	return auth_string


@frappe.whitelist()
def test_connection(account_name):
	"""Test IMAP/SMTP connection for an existing account"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	return _test_connection_internal(account)


@frappe.whitelist()
def test_connection_live(
	email,
	imap_host,
	imap_port,
	imap_ssl,
	smtp_host,
	smtp_port,
	smtp_ssl,
	smtp_starttls,
	auth_type="Password",
	imap_password=None,
	smtp_password=None,
	oauth_provider=None,
	oauth_access_token=None,
):
	"""Test IMAP/SMTP connection with provided values (before saving)"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	# Create a mock account object with the provided values
	class MockAccount:
		pass

	account = MockAccount()
	account.email = email
	account.imap_host = imap_host
	account.imap_port = int(imap_port)
	account.imap_ssl = int(imap_ssl)
	account.smtp_host = smtp_host
	account.smtp_port = int(smtp_port)
	account.smtp_ssl = int(smtp_ssl)
	account.smtp_starttls = int(smtp_starttls)
	account.auth_type = auth_type
	account.oauth_provider = oauth_provider
	account.oauth_access_token = oauth_access_token

	# For password auth, we need to handle passwords specially
	if auth_type == "Password":
		# Store passwords as attributes
		account._imap_password = imap_password
		account._smtp_password = smtp_password

		# Add get_password method
		def get_password(field):
			if field == "imap_password":
				return account._imap_password
			elif field == "smtp_password":
				return account._smtp_password
			return None

		account.get_password = get_password
	else:
		# OAuth2
		def get_oauth_access_token():
			return oauth_access_token

		account.get_oauth_access_token = get_oauth_access_token

	return _test_connection_internal(account)


def _test_connection_internal(account):
	"""Internal function to test connection with an account object"""
	# Check OAuth2 status
	if account.auth_type == "OAuth2":
		oauth_token = getattr(account, "oauth_access_token", None)
		if not oauth_token:
			return {
				"success": False,
				"imap_success": False,
				"smtp_success": False,
				"errors": [_("OAuth2 not connected. Please authorize your account first.")],
			}

	errors = []
	imap_success = False
	smtp_success = False
	imap_error = None
	smtp_error = None

	# Test IMAP
	try:
		with IMAPClient(
			host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl, timeout=15
		) as client:
			imap_login(client, account)
			imap_success = True
	except Exception as e:
		imap_error = _format_connection_error("IMAP", e, account)
		errors.append(imap_error)

	# Test SMTP
	try:
		smtp_class = smtplib.SMTP_SSL if account.smtp_ssl else smtplib.SMTP
		with smtp_class(account.smtp_host, account.smtp_port, timeout=15) as server:
			if account.smtp_starttls and not account.smtp_ssl:
				server.starttls()
			smtp_login(server, account)
			smtp_success = True
	except Exception as e:
		smtp_error = _format_connection_error("SMTP", e, account)
		errors.append(smtp_error)

	if errors:
		return {
			"success": False,
			"imap_success": imap_success,
			"smtp_success": smtp_success,
			"errors": errors,
		}
	return {
		"success": True,
		"imap_success": True,
		"smtp_success": True,
		"message": _("Connection successful"),
	}


def _format_connection_error(protocol, exception, account):
	"""Format connection error with helpful messages"""
	error_str = str(exception)
	error_lower = error_str.lower()

	# Common error patterns and user-friendly messages
	if "connection refused" in error_lower:
		host = account.imap_host if protocol == "IMAP" else account.smtp_host
		port = account.imap_port if protocol == "IMAP" else account.smtp_port
		return _("{0}: Connection refused to {1}:{2}. Check that the server address and port are correct.").format(
			protocol, host, port
		)

	if "timed out" in error_lower or "timeout" in error_lower:
		return _("{0}: Connection timeout. The server is not responding. Check your network and server settings.").format(protocol)

	if "hostname" in error_lower or "getaddrinfo" in error_lower or "name or service not known" in error_lower:
		host = account.imap_host if protocol == "IMAP" else account.smtp_host
		return _("{0}: Cannot resolve server address '{1}'. Check the server hostname.").format(protocol, host)

	if "authentication" in error_lower or "login" in error_lower or "authenticationfailed" in error_lower:
		return _("{0}: Authentication failed. Check your email address and password.").format(protocol)

	if "ssl" in error_lower or "certificate" in error_lower:
		ssl_enabled = account.imap_ssl if protocol == "IMAP" else account.smtp_ssl
		if ssl_enabled:
			return _("{0}: SSL/TLS error. Try disabling SSL or check the server's SSL configuration.").format(protocol)
		else:
			return _("{0}: SSL/TLS error. This server may require SSL. Try enabling SSL.").format(protocol)

	if "starttls" in error_lower:
		return _("{0}: STARTTLS error. Try toggling the STARTTLS option.").format(protocol)

	if "connection reset" in error_lower:
		return _("{0}: Connection was reset by the server. Check SSL/TLS settings.").format(protocol)

	if "eof" in error_lower or "unexpected eof" in error_lower:
		return _("{0}: Connection closed unexpectedly. Check SSL settings - you may need SSL enabled.").format(protocol)

	# Default: show the original error
	return _("{0}: {1}").format(protocol, error_str)


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
		imap_login(client, account)
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
		imap_login(client, account)
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
		imap_login(client, account)
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

		smtp_login(server, account)

		recipients = [r.strip() for r in to.split(",")]
		if cc:
			recipients.extend([r.strip() for r in cc.split(",")])
		if bcc:
			recipients.extend([r.strip() for r in bcc.split(",")])

		server.sendmail(account.email, recipients, msg.as_string())
		server.quit()

		# Copy sent message to Sent folder via IMAP
		try:
			_copy_to_sent_folder(account, msg)
		except Exception as e:
			# Log but don't fail - email was already sent
			frappe.log_error("Copy to Sent folder", f"Failed to copy to Sent folder: {str(e)}")

		return {"success": True, "message": _("Email sent successfully")}

	except Exception as e:
		frappe.log_error("Email send error", str(e))
		frappe.throw(_("Failed to send email: {0}").format(str(e)))


def _copy_to_sent_folder(account, msg):
	"""Copy sent message to the Sent folder via IMAP"""
	if not IMAPClient:
		return

	# Common sent folder names
	sent_folder_names = ["Sent", "Sent Items", "Sent Mail", "INBOX.Sent", "Envoyés"]

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		imap_login(client, account)

		# Find the Sent folder
		folders = client.list_folders()
		sent_folder = None

		for flags, delimiter, name in folders:
			# Check for \Sent flag first
			if b"\\Sent" in flags:
				sent_folder = name
				break
			# Fallback to common names
			if name in sent_folder_names:
				sent_folder = name

		if sent_folder:
			# Append message with \Seen flag
			import datetime
			client.append(sent_folder, msg.as_bytes(), flags=[b"\\Seen"], msg_time=datetime.datetime.now())


@frappe.whitelist()
def save_draft_imap(
	account_name,
	to=None,
	cc=None,
	subject=None,
	html_content=None,
	draft_uid=None,
	draft_folder=None,
):
	"""Save a draft to the IMAP Drafts folder. If draft_uid is provided, delete the old draft."""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	# Build draft message
	msg = MIMEMultipart("mixed")
	msg["From"] = (
		f'"{account.sender_name}" <{account.email}>'
		if account.sender_name
		else account.email
	)
	if to:
		msg["To"] = to
	if cc:
		msg["Cc"] = cc
	if subject:
		msg["Subject"] = subject

	# Body
	body = MIMEMultipart("alternative")
	if html_content:
		if bleach:
			text_content = bleach.clean(html_content, tags=[], strip=True)
		else:
			import re
			text_content = re.sub(r"<[^>]+>", "", html_content)
		body.attach(MIMEText(text_content, "plain", "utf-8"))
		body.attach(MIMEText(html_content, "html", "utf-8"))
	msg.attach(body)

	# Common drafts folder names
	drafts_folder_names = ["Drafts", "Draft", "INBOX.Drafts", "Brouillons"]

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		imap_login(client, account)

		# Find the Drafts folder
		folders = client.list_folders()
		drafts_folder = None

		for flags, delimiter, name in folders:
			# Check for \Drafts flag first
			if b"\\Drafts" in flags:
				drafts_folder = name
				break
			# Fallback to common names
			if name in drafts_folder_names:
				drafts_folder = name

		if not drafts_folder:
			frappe.throw(_("Drafts folder not found"))

		# If updating an existing draft, delete the old one first
		if draft_uid and draft_folder:
			try:
				client.select_folder(draft_folder)
				client.delete_messages([int(draft_uid)])
				client.expunge()
			except Exception:
				# Ignore errors when deleting old draft
				pass

		# Append message to Drafts folder with \Draft flag
		import datetime
		client.append(drafts_folder, msg.as_bytes(), flags=[b"\\Draft", b"\\Seen"], msg_time=datetime.datetime.now())

	return {"success": True, "message": _("Draft saved")}


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
		imap_login(client, account)
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
		imap_login(client, account)
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
		imap_login(client, account)
		client.select_folder(folder)

		if permanent:
			client.add_flags(uids, [b"\\Deleted"])
			client.expunge()
			return {"success": True, "action": "permanent_delete"}
		else:
			# Try to find trash folder
			folders = client.list_folders()
			trash_folder = None

			# Common trash folder names
			trash_names = [
				"trash", "corbeille", "deleted", "deleted items",
				"deleted messages", "bin", "papierkorb", "cestino"
			]

			# Debug: log all folders
			folder_debug = []
			for flags, _, name in folders:
				# Normalize folder name to string
				folder_name = name if isinstance(name, str) else name.decode()
				folder_name_lower = folder_name.lower()
				# Normalize flags to strings for comparison
				flags_str = [f.decode() if isinstance(f, bytes) else f for f in flags]
				folder_debug.append({"name": folder_name, "flags": flags_str})

				# Check for \Trash flag (handle both bytes and string)
				has_trash_flag = b"\\Trash" in flags or "\\Trash" in flags_str
				if has_trash_flag and not trash_folder:
					trash_folder = folder_name
				# Check folder name as fallback
				if not trash_folder and (folder_name_lower in trash_names or folder_name_lower.endswith("/trash") or folder_name_lower.endswith("/corbeille")):
					trash_folder = folder_name

			# Normalize current folder for comparison
			current_folder = folder if isinstance(folder, str) else folder.decode() if isinstance(folder, bytes) else str(folder)

			# Log debug info
			frappe.log_error(
				"Delete email debug",
				f"Current folder: {current_folder}\nTrash folder found: {trash_folder}\nAll folders: {folder_debug}"
			)

			if trash_folder and current_folder.lower() != trash_folder.lower():
				# Move to trash (copy then delete from source)
				client.copy(uids, trash_folder)
				client.add_flags(uids, [b"\\Deleted"])
				client.expunge()
				return {"success": True, "action": "moved_to_trash", "trash_folder": trash_folder}
			else:
				# No trash folder found or already in trash - mark as deleted
				client.add_flags(uids, [b"\\Deleted"])
				client.expunge()
				return {"success": True, "action": "deleted", "reason": "no_trash_folder" if not trash_folder else "already_in_trash"}


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
		imap_login(client, account)
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


# ============================================
# SEARCH
# ============================================


@frappe.whitelist()
def search_emails(
	account_name,
	folder="INBOX",
	query=None,
	from_filter=None,
	to_filter=None,
	subject_filter=None,
	date_from=None,
	date_to=None,
	has_attachment=None,
	is_unread=None,
	is_flagged=None,
	limit=50,
	offset=0,
):
	"""Advanced email search with multiple criteria"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	limit = min(int(limit), 100)
	offset = int(offset)

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		imap_login(client, account)
		client.select_folder(folder)

		# Build search criteria
		criteria = []

		# Simple text search across common fields
		if query:
			criteria.append(
				["OR", ["OR", ["SUBJECT", query], ["FROM", query]], ["TO", query]]
			)

		# Specific field searches
		if from_filter:
			criteria.append(["FROM", from_filter])

		if to_filter:
			criteria.append(["TO", to_filter])

		if subject_filter:
			criteria.append(["SUBJECT", subject_filter])

		# Date range
		if date_from:
			# IMAP date format: DD-Mon-YYYY
			from datetime import datetime

			try:
				dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
				criteria.append(["SINCE", dt.strftime("%d-%b-%Y")])
			except ValueError:
				pass

		if date_to:
			from datetime import datetime

			try:
				dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
				criteria.append(["BEFORE", dt.strftime("%d-%b-%Y")])
			except ValueError:
				pass

		# Flags
		if is_unread:
			criteria.append(["UNSEEN"])

		if is_flagged:
			criteria.append(["FLAGGED"])

		# Default: not deleted
		if not criteria:
			criteria.append(["NOT", "DELETED"])

		# Flatten criteria for IMAP
		if len(criteria) == 1:
			search_criteria = criteria[0]
		else:
			# AND all criteria together
			search_criteria = criteria[0]
			for c in criteria[1:]:
				search_criteria = search_criteria + c

		messages = client.search(search_criteria)
		total = len(messages)

		# Pagination (newest first)
		messages = list(reversed(messages))
		page = messages[offset : offset + limit]

		if not page:
			return {"emails": [], "total": total, "has_more": False}

		# Fetch envelope data
		data = client.fetch(page, ["ENVELOPE", "FLAGS", "BODYSTRUCTURE", "RFC822.SIZE"])

		emails = []
		for uid in page:
			if uid not in data:
				continue
			msg_data = data[uid]
			env = msg_data[b"ENVELOPE"]
			flags = msg_data[b"FLAGS"]
			body_structure = msg_data.get(b"BODYSTRUCTURE")

			# Filter by attachment if requested
			email_has_attachments = has_attachments(body_structure)
			if has_attachment is not None:
				if has_attachment and not email_has_attachments:
					continue
				if not has_attachment and email_has_attachments:
					continue

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
					"has_attachments": email_has_attachments,
					"size": msg_data.get(b"RFC822.SIZE", 0),
				}
			)

		return {"emails": emails, "total": total, "has_more": offset + limit < total}


# ============================================
# DRAFTS
# ============================================


@frappe.whitelist()
def save_draft(
	account_name,
	to=None,
	cc=None,
	bcc=None,
	subject=None,
	html_content=None,
	reply_to_message_id=None,
	reply_to_uid=None,
	reply_to_folder=None,
	forward_uid=None,
	forward_folder=None,
	attachments_json=None,
	draft_id=None,
):
	"""Save or update a draft"""
	# Validate account access
	get_account(account_name)

	if draft_id and frappe.db.exists("Email Draft", draft_id):
		# Update existing draft
		draft = frappe.get_doc("Email Draft", draft_id)
		if draft.user != frappe.session.user:
			frappe.throw(_("Access denied"))
	else:
		# Create new draft
		draft = frappe.new_doc("Email Draft")
		draft.account = account_name

	draft.to_recipients = to or ""
	draft.cc_recipients = cc or ""
	draft.bcc_recipients = bcc or ""
	draft.subject = subject or ""
	draft.html_content = html_content or ""
	draft.reply_to_message_id = reply_to_message_id
	draft.reply_to_uid = int(reply_to_uid) if reply_to_uid else None
	draft.reply_to_folder = reply_to_folder
	draft.forward_uid = int(forward_uid) if forward_uid else None
	draft.forward_folder = forward_folder
	draft.attachments_json = attachments_json

	draft.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"success": True,
		"draft_id": draft.name,
		"last_saved": draft.last_saved.isoformat() if draft.last_saved else None,
	}


@frappe.whitelist()
def get_drafts(account_name=None):
	"""Get all drafts for current user, optionally filtered by account"""
	filters = {"user": frappe.session.user}
	if account_name:
		# Validate account access
		get_account(account_name)
		filters["account"] = account_name

	drafts = frappe.get_all(
		"Email Draft",
		filters=filters,
		fields=[
			"name",
			"account",
			"to_recipients",
			"subject",
			"last_saved",
			"reply_to_message_id",
		],
		order_by="last_saved desc",
	)

	return drafts


@frappe.whitelist()
def get_draft(draft_id):
	"""Get a specific draft"""
	if not frappe.db.exists("Email Draft", draft_id):
		frappe.throw(_("Draft not found"))

	draft = frappe.get_doc("Email Draft", draft_id)

	if draft.user != frappe.session.user:
		frappe.throw(_("Access denied"))

	return {
		"name": draft.name,
		"account": draft.account,
		"to": draft.to_recipients,
		"cc": draft.cc_recipients,
		"bcc": draft.bcc_recipients,
		"subject": draft.subject,
		"html_content": draft.html_content,
		"reply_to_message_id": draft.reply_to_message_id,
		"reply_to_uid": draft.reply_to_uid,
		"reply_to_folder": draft.reply_to_folder,
		"forward_uid": draft.forward_uid,
		"forward_folder": draft.forward_folder,
		"attachments_json": draft.attachments_json,
		"last_saved": draft.last_saved.isoformat() if draft.last_saved else None,
	}


@frappe.whitelist()
def delete_draft(draft_id):
	"""Delete a draft"""
	if not frappe.db.exists("Email Draft", draft_id):
		frappe.throw(_("Draft not found"))

	draft = frappe.get_doc("Email Draft", draft_id)

	if draft.user != frappe.session.user:
		frappe.throw(_("Access denied"))

	draft.delete(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


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
# CONTACTS (ERPNext Integration)
# ============================================


@frappe.whitelist()
def search_contacts(query, limit=10):
	"""Search contacts by name or email for autocomplete"""
	if not query or len(query) < 2:
		return []

	limit = min(int(limit), 50)

	# Search in Contact DocType (ERPNext standard)
	contacts = []

	# Search by name
	name_results = frappe.get_all(
		"Contact",
		filters=[
			["Contact", "full_name", "like", f"%{query}%"],
		],
		fields=["name", "first_name", "last_name", "full_name", "email_id", "image"],
		limit=limit,
	)

	# Search by email in Contact Email child table
	email_results = frappe.db.sql(
		"""
		SELECT DISTINCT
			c.name, c.first_name, c.last_name, c.full_name, c.email_id, c.image
		FROM `tabContact` c
		INNER JOIN `tabContact Email` ce ON ce.parent = c.name
		WHERE ce.email_id LIKE %(query)s
		LIMIT %(limit)s
		""",
		{"query": f"%{query}%", "limit": limit},
		as_dict=True,
	)

	# Combine and deduplicate
	seen = set()
	for contact in name_results + email_results:
		if contact.name not in seen:
			seen.add(contact.name)
			# Get all email addresses for this contact
			emails = frappe.get_all(
				"Contact Email",
				filters={"parent": contact.name},
				fields=["email_id", "is_primary"],
				order_by="is_primary desc",
			)

			contacts.append(
				{
					"name": contact.name,
					"full_name": contact.full_name or f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
					"email": contact.email_id or (emails[0].email_id if emails else ""),
					"emails": [e.email_id for e in emails],
					"image": contact.image,
				}
			)

	return contacts[:limit]


@frappe.whitelist()
def get_contact_by_email(email):
	"""Get contact details by email address"""
	if not email:
		return None

	# Search in Contact Email child table
	contact_email = frappe.db.get_value(
		"Contact Email",
		{"email_id": email},
		["parent", "is_primary"],
		as_dict=True,
	)

	if not contact_email:
		return None

	contact = frappe.get_doc("Contact", contact_email.parent)

	# Get all emails
	emails = [e.email_id for e in contact.email_ids]

	# Get linked documents
	links = []
	for link in contact.links:
		links.append(
			{
				"link_doctype": link.link_doctype,
				"link_name": link.link_name,
				"link_title": link.link_title,
			}
		)

	return {
		"name": contact.name,
		"first_name": contact.first_name,
		"last_name": contact.last_name,
		"full_name": contact.full_name,
		"emails": emails,
		"primary_email": contact.email_id,
		"phone": contact.phone,
		"mobile_no": contact.mobile_no,
		"image": contact.image,
		"company_name": contact.company_name,
		"links": links,
	}


@frappe.whitelist()
def create_contact_from_email(email, name=None):
	"""Create a new contact from an email address"""
	if not email:
		frappe.throw(_("Email address is required"))

	# Check if contact with this email already exists
	existing = frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
	if existing:
		return {"success": False, "message": _("Contact with this email already exists"), "contact": existing}

	# Parse name from email if not provided
	if not name:
		# Try to extract name from email (e.g., john.doe@example.com -> John Doe)
		local_part = email.split("@")[0]
		name_parts = local_part.replace(".", " ").replace("_", " ").replace("-", " ").split()
		name = " ".join(word.capitalize() for word in name_parts)

	# Split name into first and last
	name_parts = name.split(" ", 1)
	first_name = name_parts[0] if name_parts else ""
	last_name = name_parts[1] if len(name_parts) > 1 else ""

	# Create contact
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first_name,
			"last_name": last_name,
			"email_ids": [{"email_id": email, "is_primary": 1}],
		}
	)

	contact.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"success": True,
		"contact": contact.name,
		"full_name": contact.full_name,
	}


@frappe.whitelist()
def extract_contacts_from_email(account_name, uid, folder="INBOX"):
	"""Extract and optionally save contacts from an email"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uid = int(uid)

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		imap_login(client, account)
		client.select_folder(folder)

		data = client.fetch([uid], ["ENVELOPE"])

		if uid not in data:
			frappe.throw(_("Email not found"))

		env = data[uid][b"ENVELOPE"]

		contacts = []

		# Extract from From field
		if env.from_:
			for addr in env.from_:
				email_addr = format_address(addr)
				name = decode_mime_header(addr.name) if addr.name else None
				if email_addr:
					contacts.append({"email": email_addr, "name": name, "type": "from"})

		# Extract from To field
		if env.to:
			for addr in env.to:
				email_addr = format_address(addr)
				name = decode_mime_header(addr.name) if addr.name else None
				if email_addr:
					contacts.append({"email": email_addr, "name": name, "type": "to"})

		# Extract from CC field
		if env.cc:
			for addr in env.cc:
				email_addr = format_address(addr)
				name = decode_mime_header(addr.name) if addr.name else None
				if email_addr:
					contacts.append({"email": email_addr, "name": name, "type": "cc"})

		# Check which contacts already exist
		for contact in contacts:
			existing = frappe.db.get_value("Contact Email", {"email_id": contact["email"]}, "parent")
			contact["exists"] = bool(existing)
			contact["contact_name"] = existing

		return contacts


@frappe.whitelist()
def bulk_create_contacts(contacts_json):
	"""Create multiple contacts from a list"""
	contacts = frappe.parse_json(contacts_json)

	created = []
	skipped = []

	for contact_data in contacts:
		email = contact_data.get("email")
		name = contact_data.get("name")

		if not email:
			continue

		# Check if already exists
		existing = frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
		if existing:
			skipped.append({"email": email, "contact": existing})
			continue

		# Create contact
		result = create_contact_from_email(email, name)
		if result.get("success"):
			created.append({"email": email, "contact": result["contact"]})
		else:
			skipped.append({"email": email, "reason": result.get("message")})

	return {
		"created": created,
		"skipped": skipped,
		"created_count": len(created),
		"skipped_count": len(skipped),
	}


@frappe.whitelist()
def get_recent_contacts(limit=20):
	"""Get recently used contacts for quick access"""
	limit = min(int(limit), 50)

	# Get contacts ordered by modification date
	contacts = frappe.get_all(
		"Contact",
		filters={"email_id": ["is", "set"]},
		fields=["name", "full_name", "email_id", "image"],
		order_by="modified desc",
		limit=limit,
	)

	return [
		{
			"name": c.name,
			"full_name": c.full_name,
			"email": c.email_id,
			"image": c.image,
		}
		for c in contacts
	]


@frappe.whitelist()
def link_contact_to_document(contact_name, link_doctype, link_name):
	"""Link a contact to a document (Customer, Supplier, etc.)"""
	if not frappe.db.exists("Contact", contact_name):
		frappe.throw(_("Contact not found"))

	contact = frappe.get_doc("Contact", contact_name)

	# Check if link already exists
	for link in contact.links:
		if link.link_doctype == link_doctype and link.link_name == link_name:
			return {"success": True, "message": _("Link already exists")}

	# Add new link
	contact.append(
		"links",
		{
			"link_doctype": link_doctype,
			"link_name": link_name,
		},
	)

	contact.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


# ============================================
# EMAIL FILTERS
# ============================================


@frappe.whitelist()
def get_filters(account_name=None):
	"""Get all email filters for current user"""
	filters = {"user": frappe.session.user}

	if account_name:
		get_account(account_name)  # Validate access
		filters["account"] = account_name

	return frappe.get_all(
		"Email Filter",
		filters=filters,
		fields=[
			"name",
			"filter_name",
			"account",
			"enabled",
			"match_type",
			"from_contains",
			"to_contains",
			"subject_contains",
			"has_attachment",
			"action_type",
			"target_folder",
			"mark_as_read",
			"mark_as_starred",
			"times_applied",
			"last_applied",
		],
		order_by="creation desc",
	)


@frappe.whitelist()
def create_filter(
	account_name,
	filter_name,
	match_type="any",
	from_contains=None,
	to_contains=None,
	subject_contains=None,
	has_attachment=False,
	action_type="move",
	target_folder=None,
	mark_as_read=False,
	mark_as_starred=False,
):
	"""Create a new email filter"""
	get_account(account_name)  # Validate access

	filter_doc = frappe.get_doc(
		{
			"doctype": "Email Filter",
			"account": account_name,
			"filter_name": filter_name,
			"match_type": match_type,
			"from_contains": from_contains,
			"to_contains": to_contains,
			"subject_contains": subject_contains,
			"has_attachment": has_attachment,
			"action_type": action_type,
			"target_folder": target_folder,
			"mark_as_read": mark_as_read,
			"mark_as_starred": mark_as_starred,
			"enabled": 1,
		}
	)

	filter_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "filter_name": filter_doc.name}


@frappe.whitelist()
def update_filter(filter_name, **kwargs):
	"""Update an existing email filter"""
	if not frappe.db.exists("Email Filter", filter_name):
		frappe.throw(_("Filter not found"))

	filter_doc = frappe.get_doc("Email Filter", filter_name)

	if filter_doc.user != frappe.session.user:
		frappe.throw(_("Access denied"))

	# Update allowed fields
	allowed_fields = [
		"filter_name",
		"enabled",
		"match_type",
		"from_contains",
		"to_contains",
		"subject_contains",
		"has_attachment",
		"action_type",
		"target_folder",
		"mark_as_read",
		"mark_as_starred",
	]

	for field in allowed_fields:
		if field in kwargs:
			setattr(filter_doc, field, kwargs[field])

	filter_doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def delete_filter(filter_name):
	"""Delete an email filter"""
	if not frappe.db.exists("Email Filter", filter_name):
		frappe.throw(_("Filter not found"))

	filter_doc = frappe.get_doc("Email Filter", filter_name)

	if filter_doc.user != frappe.session.user:
		frappe.throw(_("Access denied"))

	filter_doc.delete(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def apply_filters_to_email(account_name, uid, folder="INBOX"):
	"""Apply all filters to a specific email"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	# Get all enabled filters for this account
	filters = frappe.get_all(
		"Email Filter",
		filters={
			"user": frappe.session.user,
			"account": account_name,
			"enabled": 1,
		},
		fields=["name"],
	)

	if not filters:
		return {"success": True, "applied": []}

	# Fetch email data
	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		imap_login(client, account)
		client.select_folder(folder)

		data = client.fetch([int(uid)], ["ENVELOPE", "FLAGS", "BODYSTRUCTURE"])

		if int(uid) not in data:
			frappe.throw(_("Email not found"))

		msg_data = data[int(uid)]
		env = msg_data[b"ENVELOPE"]

		email_info = {
			"uid": uid,
			"from_email": format_address(env.from_[0]) if env.from_ else "",
			"from_name": decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else "",
			"to": ", ".join([format_address(a) for a in (env.to or [])]),
			"subject": decode_mime_header(env.subject),
			"has_attachments": has_attachments(msg_data.get(b"BODYSTRUCTURE")),
		}

		applied = []

		for filter_ref in filters:
			filter_doc = frappe.get_doc("Email Filter", filter_ref.name)

			if filter_doc.matches_email(email_info):
				# Apply the filter action
				result = apply_filter_action(client, account, filter_doc, uid, folder)
				if result:
					filter_doc.increment_applied()
					applied.append(
						{
							"filter": filter_doc.filter_name,
							"action": filter_doc.action_type,
							"target": filter_doc.target_folder if filter_doc.action_type == "move" else None,
						}
					)

		return {"success": True, "applied": applied}


def apply_filter_action(client, account, filter_doc, uid, current_folder):
	"""Apply a filter's action to an email"""
	uid = int(uid)
	flags_to_add = []

	# Additional flags
	if filter_doc.mark_as_read:
		flags_to_add.append(b"\\Seen")

	if filter_doc.mark_as_starred:
		flags_to_add.append(b"\\Flagged")

	if flags_to_add:
		client.add_flags([uid], flags_to_add)

	# Main action
	if filter_doc.action_type == "move":
		if filter_doc.target_folder and filter_doc.target_folder != current_folder:
			client.copy([uid], filter_doc.target_folder)
			client.add_flags([uid], [b"\\Deleted"])
			client.expunge()
			return True

	elif filter_doc.action_type == "delete":
		client.add_flags([uid], [b"\\Deleted"])
		client.expunge()
		return True

	elif filter_doc.action_type == "mark_read":
		if b"\\Seen" not in flags_to_add:
			client.add_flags([uid], [b"\\Seen"])
		return True

	elif filter_doc.action_type == "mark_starred":
		if b"\\Flagged" not in flags_to_add:
			client.add_flags([uid], [b"\\Flagged"])
		return True

	return bool(flags_to_add)


@frappe.whitelist()
def apply_filters_to_folder(account_name, folder="INBOX", limit=50):
	"""Apply all filters to emails in a folder"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	# Get all enabled filters
	filters = frappe.get_all(
		"Email Filter",
		filters={
			"user": frappe.session.user,
			"account": account_name,
			"enabled": 1,
		},
		fields=["name"],
	)

	if not filters:
		return {"success": True, "processed": 0, "applied": 0}

	filter_docs = [frappe.get_doc("Email Filter", f.name) for f in filters]

	with IMAPClient(
		host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl
	) as client:
		imap_login(client, account)
		client.select_folder(folder)

		# Get recent unread messages
		messages = client.search(["UNSEEN"])
		messages = list(reversed(messages))[:limit]

		if not messages:
			return {"success": True, "processed": 0, "applied": 0}

		data = client.fetch(messages, ["ENVELOPE", "BODYSTRUCTURE"])

		applied_count = 0

		for uid in messages:
			if uid not in data:
				continue

			msg_data = data[uid]
			env = msg_data[b"ENVELOPE"]

			email_info = {
				"uid": uid,
				"from_email": format_address(env.from_[0]) if env.from_ else "",
				"from_name": decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else "",
				"to": ", ".join([format_address(a) for a in (env.to or [])]),
				"subject": decode_mime_header(env.subject),
				"has_attachments": has_attachments(msg_data.get(b"BODYSTRUCTURE")),
			}

			for filter_doc in filter_docs:
				if filter_doc.matches_email(email_info):
					result = apply_filter_action(client, account, filter_doc, uid, folder)
					if result:
						filter_doc.increment_applied()
						applied_count += 1
					break  # Only apply first matching filter

		return {"success": True, "processed": len(messages), "applied": applied_count}


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
