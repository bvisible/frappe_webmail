# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Frappe Webmail API

This module provides the API endpoints for the webmail client,
including IMAP/SMTP operations, email management, and signatures.
"""

import base64
import email
import email.policy
import re
import smtplib
from email import encoders
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

from frappe_webmail.conversations import conversation_of, message_id_of, one_per_message, references_for

# Served as frappe_webmail.api.list_attachable_documents, like every method of this module
from frappe_webmail.documents import list_attachable_documents
from frappe_webmail.email_html import clean_sent_html, plain_text
from frappe_webmail.inline_images import (
	body_with,
	files_inlined,
	logo_sized,
	sender_logo,
	to_parts,
)
from frappe_webmail.mime_parts import iter_attachments
from frappe_webmail.previews import fetch_previews
from frappe_webmail.replies import appended_uid, reply_recipients

# The IMAPClient the app builds: imapclient's, bounded with TLS too and watched (utils/imap_client.py)
from frappe_webmail.utils.imap_client import IMAP_PROBE_TIMEOUT, IMAP_READ_TIMEOUT, IMAPClient, imap_timeout

try:
	import bleach
except ImportError:
	bleach = None

# The styles a message sent may carry: the properties that Frappe keeps when it cleans a mail it receives
# (frappe.utils.html_utils.clean_email_html), and the two that Outlook reads to leave the sides of a table alone. None
# of them fetches anything (no background image, no url()) or positions an element (no position, no float); they style
# text and boxes, and a sender can hide or shift their own text with them as in any mail. Without a sanitizer for them,
# bleach 6 empties every style attribute it is told to keep, and the company's signature (tables, fonts, colours:
# signatures.py) would leave as bare cells.
EMAIL_CSS_PROPERTIES = [
	"color",
	"border-color",
	"width",
	"height",
	"max-width",
	"background-color",
	"border-collapse",
	"border-radius",
	"border",
	"border-top",
	"border-bottom",
	"border-left",
	"border-right",
	"margin",
	"margin-top",
	"margin-bottom",
	"margin-left",
	"margin-right",
	"padding",
	"padding-top",
	"padding-bottom",
	"padding-left",
	"padding-right",
	"font-size",
	"font-weight",
	"font-family",
	"text-decoration",
	"line-height",
	"text-align",
	"vertical-align",
	"display",
	"mso-table-lspace",
	"mso-table-rspace",
]


def email_css_sanitizer():
	"""The sanitizer for the style attributes of a message sent. None where bleach is without its CSS extra (tinycss2,
	which Frappe depends on): the styles are then dropped, as they were before."""
	try:
		from bleach.css_sanitizer import CSSSanitizer
	except ImportError:
		return None
	# No SVG property either (bleach keeps a list of its own by default, some of which take a url()): a message sent
	# carries no SVG.
	return CSSSanitizer(allowed_css_properties=EMAIL_CSS_PROPERTIES, allowed_svg_properties=[])


class WebmailAuthenticationError(frappe.ValidationError):
	"""Raised when an IMAP/SMTP sign-in fails because the credentials are wrong.

	Subclasses frappe.ValidationError so Frappe answers with HTTP 417 and a clean
	error payload (exc_type set) instead of a 500 traceback. The frontend listens
	for this exc_type to show a re-authentication dialog.
	"""


class WebmailConnectionError(frappe.ValidationError):
	"""Raised when an IMAP/SMTP server cannot be reached (network, SSL, timeout).

	Subclasses frappe.ValidationError for the same reason as
	WebmailAuthenticationError: a clean HTTP 417 payload instead of a traceback.
	"""


class WebmailConnectionLost(WebmailConnectionError):
	"""The IMAP connection failed after a command that changes something was sent on it (APPEND, STORE, MOVE…): the
	server may have done it, its answer lost. Asking again could do it twice (a message filed twice): NeoMail's facade
	says `serverFail` (it may have been done) rather than `serverUnavailable` (nothing was done, try again)."""


def to_bool(value, default=False):
	"""Convert a value to boolean, handling string 'true'/'false' from JS"""
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.lower() in ("true", "1", "yes")
	return bool(value)


# ============================================
# ACCOUNT MANAGEMENT
# ============================================


@frappe.whitelist()
def get_accounts():
	"""Get all email accounts for current user (owned or shared)"""
	user = frappe.session.user

	# Get accounts owned by user
	owned = frappe.get_all(
		"Webmail Account",
		filters={"user": user, "enabled": 1},
		fields=["name", "email", "sender_name", "default_signature", "auth_type", "oauth_provider", "user"],
	)

	# Get accounts shared with user
	shared_account_names = frappe.get_all(
		"Webmail Account User", filters={"user": user, "parenttype": "Webmail Account"}, pluck="parent"
	)

	shared = []
	if shared_account_names:
		shared = frappe.get_all(
			"Webmail Account",
			filters={"name": ["in", shared_account_names], "enabled": 1},
			fields=[
				"name",
				"email",
				"sender_name",
				"default_signature",
				"auth_type",
				"oauth_provider",
				"user",
			],
		)

	# Mark shared accounts and add shared_with info for owned accounts
	for acc in shared:
		acc["is_shared"] = True

	for acc in owned:
		# Get list of users this account is shared with
		shared_users = frappe.get_all("Webmail Account User", filters={"parent": acc["name"]}, pluck="user")
		if shared_users:
			acc["shared_with"] = shared_users

	return owned + shared


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
		account.oauth_token_expiry = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=expires_in)
		account.oauth_status = "Connected"

		account.save(ignore_permissions=True)
		frappe.db.commit()

		# Redirect to webmail with success message
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"/app/webmail-account/{account_name}?oauth=success"

	except requests.RequestException as e:
		frappe.log_error(f"OAuth error: {e!s}", "Webmail OAuth")
		frappe.throw(_("OAuth authentication failed"))


@frappe.whitelist()
def disconnect_oauth(account_name):
	"""Disconnect OAuth and clear tokens"""
	account = _owned_account(account_name)

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


def _imap_login_raw(client, account):
	"""Perform the raw IMAP login. Raises low-level exceptions on failure.

	Used directly by the connection tester, which wants the original exception.
	Regular operations should call imap_login() instead, which translates
	failures into typed, user-friendly webmail errors.
	"""
	if account.auth_type == "OAuth2":
		access_token = account.get_oauth_access_token()
		if not access_token:
			raise WebmailAuthenticationError(_("OAuth token not available"))

		client.oauth2_login(account.email, access_token)
	else:
		# Password authentication
		password = account.get_password("imap_password")
		client.login(account.email, password)


def imap_login(client, account):
	"""Login to the IMAP server, translating failures into typed webmail errors.

	Any low-level error (bad credentials, network, SSL...) is converted into a
	WebmailAuthenticationError or WebmailConnectionError so callers never leak a
	raw traceback to the user.
	"""
	try:
		_imap_login_raw(client, account)
	except Exception as e:
		_raise_webmail_login_error("IMAP", e, account)


# ============================================
# IMAP CONNECTION POOL
# ============================================
#
# Every endpoint used to open a brand-new IMAP connection (TLS handshake + LOGIN)
# per request: 100-800 ms of pure overhead before any useful work, paid 5-6 times
# on a single page load and again on every 60 s poll. The pool keeps ONE
# authenticated connection per account in this worker process and hands it to
# consecutive requests; a connection idle for a while is checked with NOOP first
# and dropped after a few minutes so a server-side timeout never surfaces to the
# user. Gunicorn runs sync workers (one request at a time per process) and the RQ
# workers are single-threaded, so the per-connection lock is a belt-and-braces
# guard: a nested or concurrent lease simply gets a fresh, unpooled connection.

import socket
import ssl as _ssl
import threading
import time as _time
from contextlib import contextmanager

_IMAP_POOL = {}
_IMAP_POOL_LOCK = threading.Lock()
_IMAP_IDLE_RECHECK = 20  # seconds idle past which we NOOP before reusing
_IMAP_MAX_IDLE = 240  # seconds idle past which we reconnect instead


class _PooledIMAP:
	__slots__ = ("client", "last_used", "lock")

	def __init__(self, client):
		self.client = client
		self.last_used = _time.monotonic()
		self.lock = threading.Lock()


def _imap_connect(account):
	"""Open and authenticate a new IMAP connection (typed errors via imap_login), within imap_timeout."""
	try:
		client = IMAPClient(
			host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl, timeout=imap_timeout()
		)
	except Exception as e:
		# Refused, unreachable, too slow, a TLS failure: the server could not be reached, said as the webmail says it
		# (WebmailConnectionError: NeoMail's facade answers 503 and tries again), never a raw error (a 500).
		_raise_webmail_login_error("IMAP", e, account)
	try:
		imap_login(client, account)
	except Exception:
		try:
			client.shutdown()
		except Exception:
			pass
		raise
	return client


def _imap_discard(entry):
	"""Close a pooled connection. LOGOUT first; on a connection whose read timed out, or that is gone, it fails at once
	(a socket that timed out refuses any further read) and the socket is shut down instead."""
	try:
		entry.client.logout()
	except Exception:
		try:
			entry.client.shutdown()
		except Exception:
			pass


def _socket_failed(client):
	"""Whether a read or a write of this connection failed (it timed out, or broke), whoever caught the error."""
	return getattr(client, "socket_failed", False) is True


def _raise_connection_failure(exc, account, client=None):
	"""A connection that failed while in use (it timed out, or broke) as the webmail says it, raised from the socket's
	own error: WebmailConnectionError (nothing was changed: NeoMail's facade says the server is unavailable, and it
	tries again), or WebmailConnectionLost once a command that changes something was sent in this session (it may have
	been done). Anything else is left as is."""
	if not _imap_is_connection_error(exc):
		return
	try:
		_raise_webmail_login_error("IMAP", exc, account)
	except WebmailConnectionError as typed:
		if getattr(client, "wrote", False) is True:
			raise WebmailConnectionLost(str(typed)) from exc
		raise typed from exc
	except WebmailAuthenticationError as typed:
		raise typed from exc


def _imap_is_alive(entry):
	if _socket_failed(entry.client):
		return False
	idle = _time.monotonic() - entry.last_used
	if idle > _IMAP_MAX_IDLE:
		return False
	if idle < _IMAP_IDLE_RECHECK:
		return True
	# A live server answers a NOOP at once; one that dropped the connection without a word answers nothing, and the
	# request should not wait a whole read (IMAP_READ_TIMEOUT) to find out.
	try:
		entry.client.set_read_timeout(IMAP_PROBE_TIMEOUT)
		entry.client.noop()
		entry.client.set_read_timeout(IMAP_READ_TIMEOUT)
		return True
	except Exception:
		return False


def _imap_is_connection_error(exc):
	"""True when the exception means the socket itself is unusable (as opposed to a
	plain IMAP error such as 'select failed: Mailbox doesn't exist', after which the
	connection is perfectly fine)."""
	if isinstance(exc, OSError | EOFError | _ssl.SSLError | socket.error):
		return True
	try:
		from imapclient import exceptions as imap_exc

		if isinstance(exc, imap_exc.IMAPClientAbortError):
			return True
	except Exception:
		pass
	import imaplib

	return isinstance(exc, imaplib.IMAP4.abort)


@contextmanager
def imap_session(account):
	"""Yield an authenticated IMAPClient for `account`, reusing the pooled
	connection when there is one. Callers select their own folder; nothing is
	assumed about the previous request's state."""
	if frappe.flags.in_test:
		# The test suite mocks IMAPClient as a context manager and configures the
		# client behind __enter__ — keep that contract (fresh connection, logout at
		# exit) so the tests exercise the endpoints, not the pool.
		with IMAPClient(
			host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl, timeout=imap_timeout()
		) as client:
			imap_login(client, account)
			try:
				yield client
			except Exception as exc:
				_raise_connection_failure(exc, account, client)
				raise
		return

	key = account.name
	entry = None
	with _IMAP_POOL_LOCK:
		cand = _IMAP_POOL.get(key)
		if cand is not None and cand.lock.acquire(blocking=False):
			entry = cand
	if entry is not None and not _imap_is_alive(entry):
		with _IMAP_POOL_LOCK:
			if _IMAP_POOL.get(key) is entry:
				_IMAP_POOL.pop(key, None)
		entry.lock.release()
		_imap_discard(entry)
		entry = None
	if entry is None:
		entry = _PooledIMAP(_imap_connect(account))
		entry.lock.acquire()
	# Nothing written yet in this session (a failure then reads as one that changed nothing)
	begin = getattr(entry.client, "begin_session", None)
	if callable(begin):
		begin()

	broken = False
	try:
		yield entry.client
	except Exception as exc:
		broken = _imap_is_connection_error(exc)
		_raise_connection_failure(exc, account, entry.client)
		raise
	finally:
		entry.last_used = _time.monotonic()
		# A connection that failed is never used again, even when the caller caught the error and went on
		broken = broken or _socket_failed(entry.client)
		if broken:
			with _IMAP_POOL_LOCK:
				if _IMAP_POOL.get(key) is entry:
					_IMAP_POOL.pop(key, None)
			entry.lock.release()
			_imap_discard(entry)
		else:
			with _IMAP_POOL_LOCK:
				current = _IMAP_POOL.get(key)
				if current is None or current is entry:
					_IMAP_POOL[key] = entry
					entry.lock.release()
				else:
					# Another connection took the slot meanwhile: keep that one.
					entry.lock.release()
					_imap_discard(entry)


def _smtp_login_raw(server, account):
	"""Perform the raw SMTP login. Raises low-level exceptions on failure.

	Used directly by the connection tester; regular operations should call
	smtp_login() instead.
	"""
	if account.auth_type == "OAuth2":
		access_token = account.get_oauth_access_token()
		if not access_token:
			raise WebmailAuthenticationError(_("OAuth token not available"))

		# Build XOAUTH2 authentication string
		auth_string = build_xoauth2_string(account.email, access_token)
		server.auth("XOAUTH2", lambda x: auth_string)
	else:
		# Password authentication
		password = account.get_password("smtp_password")
		server.login(account.email, password)


def smtp_login(server, account):
	"""Login to the SMTP server, translating failures into typed webmail errors."""
	try:
		_smtp_login_raw(server, account)
	except Exception as e:
		_raise_webmail_login_error("SMTP", e, account)


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
def update_account_password(account_name, imap_password=None, smtp_password=None):
	"""Update the stored IMAP/SMTP password of a webmail account.

	Used by the re-authentication dialog shown when a sign-in fails. Only the
	account owner may change credentials (a shared user cannot).

	Args:
		account_name: Webmail Account name
		imap_password: New IMAP password (optional)
		smtp_password: New SMTP password (optional)

	Returns:
		dict: success status
	"""
	account = get_account(account_name)

	if account.user != frappe.session.user:
		frappe.throw(_("Only the account owner can change the password"), frappe.PermissionError)

	if account.auth_type == "OAuth2":
		frappe.throw(_("This account uses OAuth2. Please reconnect it instead of setting a password."))

	if not imap_password and not smtp_password:
		frappe.throw(_("A password is required"))

	if imap_password:
		account.imap_password = imap_password
	if smtp_password:
		account.smtp_password = smtp_password

	account.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


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
	account.imap_ssl = 1 if to_bool(imap_ssl) else 0
	account.smtp_host = smtp_host
	account.smtp_port = int(smtp_port)
	account.smtp_ssl = 1 if to_bool(smtp_ssl) else 0
	account.smtp_starttls = 1 if to_bool(smtp_starttls) else 0
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
			host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl, timeout=imap_timeout()
		) as client:
			_imap_login_raw(client, account)
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
			_smtp_login_raw(server, account)
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
		return _(
			"{0}: Connection refused to {1}:{2}. Check that the server address and port are correct."
		).format(protocol, host, port)

	if "timed out" in error_lower or "timeout" in error_lower:
		return _(
			"{0}: Connection timeout. The server is not responding. Check your network and server settings."
		).format(protocol)

	if (
		"hostname" in error_lower
		or "getaddrinfo" in error_lower
		or "name or service not known" in error_lower
	):
		host = account.imap_host if protocol == "IMAP" else account.smtp_host
		return _("{0}: Cannot resolve server address '{1}'. Check the server hostname.").format(
			protocol, host
		)

	if "authentication" in error_lower or "login" in error_lower or "authenticationfailed" in error_lower:
		return _("{0}: Authentication failed. Check your email address and password.").format(protocol)

	if "ssl" in error_lower or "certificate" in error_lower:
		ssl_enabled = account.imap_ssl if protocol == "IMAP" else account.smtp_ssl
		if ssl_enabled:
			return _("{0}: SSL/TLS error. Try disabling SSL or check the server's SSL configuration.").format(
				protocol
			)
		else:
			return _("{0}: SSL/TLS error. This server may require SSL. Try enabling SSL.").format(protocol)

	if "starttls" in error_lower:
		return _("{0}: STARTTLS error. Try toggling the STARTTLS option.").format(protocol)

	if "connection reset" in error_lower:
		return _("{0}: Connection was reset by the server. Check SSL/TLS settings.").format(protocol)

	if "eof" in error_lower or "unexpected eof" in error_lower:
		return _(
			"{0}: Connection closed unexpectedly. Check SSL settings - you may need SSL enabled."
		).format(protocol)

	# Default: show the original error
	return _("{0}: {1}").format(protocol, error_str)


def _raise_webmail_login_error(protocol, exception, account):
	"""Translate a low-level IMAP/SMTP exception into a typed webmail error.

	Raises WebmailAuthenticationError for bad credentials, WebmailConnectionError
	otherwise. Both subclass frappe.ValidationError, so Frappe replies with a
	clean HTTP 417 payload (exc_type set) instead of a 500 traceback. The extra
	``webmail_error`` payload lets the frontend show a tailored re-auth dialog.
	"""
	error_text = str(exception).lower()

	# Identify authentication failures by exception type or well-known markers.
	is_auth_error = isinstance(exception, WebmailAuthenticationError | smtplib.SMTPAuthenticationError)
	if not is_auth_error:
		try:
			from imapclient.exceptions import LoginError as IMAPLoginError

			is_auth_error = isinstance(exception, IMAPLoginError)
		except ImportError:
			pass
	if not is_auth_error:
		auth_markers = (
			"invalid login",
			"invalid credentials",
			"authentication failed",
			"authenticationfailed",
			"auth failed",
			"username and password not accepted",
			"incorrect password",
			"password is incorrect",
			"login failed",
			"login denied",
			"logindenied",
		)
		is_auth_error = any(marker in error_text for marker in auth_markers)

	account_email = getattr(account, "email", "") or ""
	account_name = getattr(account, "name", None)
	auth_type = getattr(account, "auth_type", "Password") or "Password"

	if is_auth_error:
		if auth_type == "OAuth2":
			message = _(
				"Could not sign in to {0} for {1}. The OAuth connection is no longer valid - please reconnect the account."
			).format(protocol, account_email or _("this account"))
		else:
			message = _(
				"Could not sign in to {0} for {1}. The email address or password is incorrect."
			).format(protocol, account_email or _("this account"))
		frappe.local.response["webmail_error"] = {
			"type": "authentication",
			"protocol": protocol,
			"account": account_name,
			"email": account_email,
			"auth_type": auth_type,
		}
		frappe.throw(message, exc=WebmailAuthenticationError, title=_("Email Sign-in Failed"))

	# Not an auth error: reuse the friendly connection-error formatter.
	message = _format_connection_error(protocol, exception, account)
	frappe.local.response["webmail_error"] = {
		"type": "connection",
		"protocol": protocol,
		"account": account_name,
		"email": account_email,
		"auth_type": auth_type,
	}
	frappe.throw(message, exc=WebmailConnectionError, title=_("Email Connection Failed"))


# ============================================
# FOLDERS
# ============================================


@frappe.whitelist()
def get_folders(account_name):
	"""List IMAP folders for an account"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	with imap_session(account) as client:
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


@frappe.whitelist()
def get_quota(account_name):
	"""IMAP STORAGE quota for the account (RFC 2087). Returns None when the
	server does not advertise the QUOTA capability — the UI hides the block."""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	try:
		with imap_session(account) as client:
			if b"QUOTA" not in client.capabilities():
				return None
			quotas = client.get_quota_root("INBOX")[1] or []
			for q in quotas:
				resource = q.resource.decode() if isinstance(q.resource, bytes) else str(q.resource)
				if resource.upper() == "STORAGE" and q.limit:
					# RFC 2087: usage/limit are in KILOBYTES
					return {"usage_kb": int(q.usage), "limit_kb": int(q.limit)}
			return None
	except Exception:
		# quota is cosmetic — never break the mailbox over it
		return None


@frappe.whitelist()
def create_folder(account_name, folder_name, parent_folder=None):
	"""Create a new IMAP folder.

	Args:
		account_name: Webmail Account name
		folder_name: Name of the new folder
		parent_folder: Parent folder path (optional, for nested folders)

	Returns:
		dict: success status and folder path
	"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	if not folder_name or not folder_name.strip():
		frappe.throw(_("Folder name is required"))

	account = get_account(account_name)
	folder_name = folder_name.strip()

	with imap_session(account) as client:
		# Get folder delimiter from existing folders
		folders = client.list_folders()
		delimiter = "/"
		for _flags, delim, _name in folders:
			delimiter = delim.decode() if isinstance(delim, bytes) else delim
			break

		# Build full path with delimiter
		if parent_folder:
			full_path = f"{parent_folder}{delimiter}{folder_name}"
		else:
			full_path = folder_name

		# Check if folder already exists
		for _flags, _delim, name in folders:
			if name == full_path:
				frappe.throw(_("Folder already exists"))

		client.create_folder(full_path)

		return {"success": True, "folder": full_path}


def _search_charset(criteria):
	"""Return "UTF-8" when a SEARCH criterion carries non-ASCII text, else None.

	IMAPClient encodes the text of a search as US-ASCII unless it is given a charset, so an accented
	word ("démonstration") raised UnicodeEncodeError and could not be searched at all. An all-ASCII
	search is sent exactly as before.

	Criteria must stay flat lists (OR OR SUBJECT x FROM x TO x): IMAPClient 3.x drops the charset inside
	a nested list, and glues the closing parenthesis to a literal, so a grouped criterion cannot carry
	non-ASCII text.
	"""
	if isinstance(criteria, str):
		return None if criteria.isascii() else "UTF-8"
	if isinstance(criteria, list | tuple):
		return "UTF-8" if any(_search_charset(item) for item in criteria) else None
	return None


# The shortest word a search sends on its own: servers with a full-text index (Infomaniak's Dovecot) keep shorter words
# out of their index, and a search holding one of them finds nothing at all.
SEARCH_MIN_WORD = 3


def _search_words(text):
	"""The words of a search, each to be found somewhere in the message, in any order: full-text servers read a phrase
	that way anyway (« facture plan » finds « facture et plan »), and a server without an index finds each word as a
	substring. Words of one or two letters are left out when a longer one remains (« ZZ », « W4 », « et »): an indexed
	server never finds them, so the whole search found nothing."""
	words = (text or "").split()
	return [word for word in words if len(word) >= SEARCH_MIN_WORD] or words


def _text_criteria(text):
	"""SEARCH criteria for words typed in a search box: each word in the subject, the sender or the recipients, all the
	words together (IMAP joins criteria with AND). Flat on purpose: see _search_charset."""
	criteria = []
	for word in _search_words(text):
		criteria += ["OR", "OR", "SUBJECT", word, "FROM", word, "TO", word]
	return criteria


# ============================================
# EMAILS - LIST
# ============================================


@frappe.whitelist()
def get_emails(account_name, folder="INBOX", limit=50, offset=0, search=None, only=None, order="newest"):
	"""Get emails from a folder with pagination.

	`only`: « unread » or « flagged » (asked of the server, so that every such message is found, not those of the first
	page alone); `order`: « newest » first (the default) or « oldest » first."""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	limit = min(int(limit), 100)  # Max 100 per request
	offset = int(offset)

	with imap_session(account) as client:
		client.select_folder(folder)

		# Search criteria (flat on purpose: see _search_charset)
		criteria = _text_criteria(search) or ["NOT", "DELETED"]
		if only == "unread":
			criteria = [*criteria, "UNSEEN"]
		elif only == "flagged":
			criteria = [*criteria, "FLAGGED"]

		messages = client.search(criteria, charset=_search_charset(criteria))
		total = len(messages)

		# Pagination (newest first, unless the oldest are asked for)
		messages = list(messages) if order == "oldest" else list(reversed(messages))
		page = messages[offset : offset + limit]

		if not page:
			return {"emails": [], "total": total, "has_more": False}

		# Fetch envelope data
		data = client.fetch(page, ["ENVELOPE", "FLAGS", "BODYSTRUCTURE", "RFC822.SIZE"])
		previews = _list_previews(client, data)

		emails = [_summary(uid, data[uid], previews) for uid in page if uid in data]  # Maintain order

		return {"emails": emails, "total": total, "has_more": offset + limit < total}


def _summary(uid, msg_data, previews, folder=None):
	"""A message as a list shows it (get_emails, get_conversation): who, what, when, its flags, its first words."""
	env = msg_data[b"ENVELOPE"]
	flags = msg_data[b"FLAGS"]
	row = {
		"uid": uid,
		"subject": decode_mime_header(env.subject),
		"from_email": format_address(env.from_[0]) if env.from_ else "",
		"from_name": (decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else ""),
		"to": format_address(env.to[0]) if env.to else "",
		"date": env.date.isoformat() if env.date else None,
		"seen": b"\\Seen" in flags,
		"flagged": b"\\Flagged" in flags,
		"answered": b"\\Answered" in flags,
		"forwarded": b"$Forwarded" in flags,
		"nora_seen": b"$NoraSeen" in flags,
		"has_attachments": has_attachments(msg_data.get(b"BODYSTRUCTURE")),
		"size": msg_data.get(b"RFC822.SIZE", 0),
		"preview": previews.get(uid, ""),
	}
	if folder:
		row["folder"] = folder
	return row


@frappe.whitelist()
def get_conversation(account_name, folder="INBOX", uid=None, limit=20):
	"""The other messages of a message's conversation, oldest first (conversations.py): what it answers and what
	answers it, in its folder, the inbox and the sent. Read only: nothing is marked read."""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))
	if not uid:
		frappe.throw(_("The message is required"))

	account = get_account(account_name)
	limit = max(1, min(int(limit), 50))
	with imap_session(account) as client:
		own, places = conversation_of(client, folder, int(uid))
		found = []
		for each in dict.fromkeys(f for f, _uid in places):
			uids = [u for f, u in places if f == each]
			client.select_folder(each, readonly=True)
			data = client.fetch(uids, ["ENVELOPE", "FLAGS", "BODYSTRUCTURE", "RFC822.SIZE"])
			previews = _list_previews(client, data)
			found += [
				(message_id_of(data[u][b"ENVELOPE"]), _summary(u, data[u], previews, folder=each))
				for u in uids
				if u in data
			]
	# A message in two folders (sent to oneself) is one message of the conversation
	rows = one_per_message(found, own, folder)
	rows.sort(key=lambda row: row["date"] or "")
	return {"messages": rows[-limit:]}


def _list_previews(client, data):
	"""The first words of each message of a page, under its subject in the list (previews.py). A server that cannot
	give them leaves the list without them, never without its messages: a warning in the app's log, not an Error Log
	at every refresh of the list."""
	try:
		return fetch_previews(client, {uid: msg.get(b"BODYSTRUCTURE") for uid, msg in data.items()})
	except Exception:
		frappe.logger("frappe_webmail").warning("Webmail list previews failed", exc_info=True)
		return {}


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
	mark_read = to_bool(mark_read, default=True)

	with imap_session(account) as client:
		client.select_folder(folder)

		# Mark as read
		if mark_read:
			client.add_flags([uid], [b"\\Seen"])

		# Fetch full message: a peek when it is not to be marked read (fetching RFC822 marks a message read by itself,
		# RFC 3501 6.4.5: « Répondre » from a message's menu, a draft taken back, marked it read all the same)
		body = "RFC822" if mark_read else "BODY.PEEK[]"
		data = client.fetch([uid], [body, "ENVELOPE", "FLAGS"])

		if uid not in data:
			frappe.throw(_("Email not found"))

		raw = data[uid][b"RFC822" if mark_read else b"BODY[]"]
		msg = email.message_from_bytes(raw)
		env = data[uid][b"ENVELOPE"]
		flags = data[uid][b"FLAGS"]

		# Parse content
		html_content = None
		text_content = None
		attachments = []
		inline_images = {}
		# The same rule as the download and every action on an attachment (mime_parts)
		attachment_of = {id(a.part): a for a in iter_attachments(msg)}

		for part in msg.walk():
			content_type = part.get_content_type()
			content_id = part.get("Content-ID", "").strip("<>")
			attachment = attachment_of.get(id(part))

			if attachment:
				attachments.append(
					{
						"id": attachment.id,
						"filename": attachment_filename(attachment),
						"content_type": content_type,
						"size": len(attachment_bytes(part)),
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

		from_email = format_address(env.from_[0]) if env.from_ else ""
		to = ", ".join([format_address(a) for a in (env.to or [])])
		cc = ", ".join([format_address(a) for a in (env.cc or [])])
		# A draft or a message sent keeps its Bcc: resuming a draft must not lose its hidden copies
		bcc = ", ".join([format_address(a) for a in (getattr(env, "bcc", None) or [])])
		reply_to = format_address(env.reply_to[0]) if env.reply_to else ""
		return {
			"uid": uid,
			"message_id": msg.get("Message-ID", ""),
			"subject": decode_mime_header(env.subject),
			"from_email": from_email,
			"from_name": (decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else ""),
			"to": to,
			"cc": cc,
			"bcc": bcc,
			"reply_to": reply_to,
			# Who « Reply » and « Reply all » write to, the same rule for both screens (replies.reply_recipients)
			"reply": reply_recipients(account.email, from_email, reply_to, to, cc),
			"reply_all": reply_recipients(account.email, from_email, reply_to, to, cc, reply_all=True),
			"date": env.date.isoformat() if env.date else None,
			"html": html_content,
			"text": text_content,
			"attachments": attachments,
			"seen": b"\\Seen" in flags,
			"flagged": b"\\Flagged" in flags,
			"answered": b"\\Answered" in flags,
			"forwarded": b"$Forwarded" in flags,
		}


@frappe.whitelist()
def mark_email_nora_seen(account_name, uid, seen=True, folder="INBOX"):
	"""Mark/unmark an email with the NORA-specific IMAP flag $NoraSeen.

	Independent of the standard \\Seen flag (the "read by user" indicator).
	NORA uses $NoraSeen to track which emails it has already processed,
	without touching the human-facing read state.
	"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uid = int(uid)
	seen = to_bool(seen, default=True)

	with imap_session(account) as client:
		client.select_folder(folder)

		if seen:
			client.add_flags([uid], [b"$NoraSeen"])
		else:
			client.remove_flags([uid], [b"$NoraSeen"])

		return {"success": True, "uid": uid, "nora_seen": seen}


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
	reply_to_uid=None,
	reply_to_folder=None,
	forward_uid=None,
	forward_folder=None,
	reference_doctype=None,
	reference_name=None,
	forward_attachments=None,
	draft_uid=None,
	draft_folder=None,
):
	"""Send an email. `forward_attachments`: the ids of the forwarded message's attachments the person kept, read
	again on the server from `forward_uid` in `forward_folder` (never through the browser). `draft_uid` in
	`draft_folder`: the draft this message was written in, deleted once it has left."""
	account = get_account(account_name)

	# Images written in the text leave as parts of the message, before the cleaning (it would drop a `data:` image)
	html_content, inline_parts = to_parts(html_content, (account.email or "webmail.local").split("@")[-1])

	# What a message sent may carry (email_html.py: the signature manager previews a pasted signature by the same rules)
	html_content = clean_sent_html(html_content)

	# A picture of the instance (a signature's logo) leaves as a part too, in the message only: the copy for the
	# document's timeline keeps its address, which the desk shows (maintenance#1650). The company's logo first gets
	# back the width its template draws it at, which the desk's editor doesn't keep; it is worked out once for both.
	logo = sender_logo() if "<img" in (html_content or "").lower() else ""
	mail_html, file_parts = to_parts(
		files_inlined(logo_sized(html_content, logo), logo), (account.email or "webmail.local").split("@")[-1]
	)
	inline_parts = inline_parts + file_parts

	# Build message
	msg = MIMEMultipart("mixed")
	msg["From"] = f'"{account.sender_name}" <{account.email}>' if account.sender_name else account.email
	msg["To"] = to
	msg["Subject"] = subject
	# Its date and its Message-ID, the same in the copy kept in « Envoyés » as in the message received: the copy had
	# neither, so it showed no date and the answers to it could not find it (a conversation, get_conversation)
	msg["Date"] = formatdate(localtime=True)
	msg["Message-ID"] = make_msgid(domain=(account.email or "webmail.local").split("@")[-1])

	if cc:
		msg["Cc"] = cc

	if reply_to_message_id:
		msg["In-Reply-To"] = reply_to_message_id
		msg["References"] = _references(account, reply_to_message_id, reply_to_uid, reply_to_folder)

	# Body (multipart/alternative for text + html)
	body = MIMEMultipart("alternative")

	# Plain text version: what a reader of the text alone gets, links and banners with where they lead
	text_content = plain_text(html_content)

	body.attach(MIMEText(text_content, "plain", "utf-8"))

	# HTML version
	body.attach(MIMEText(mail_html, "html", "utf-8"))
	msg.attach(body_with(body, inline_parts))

	# Attachments: the files the person joined (base64), then the forwarded message's they kept
	if attachments:
		for att in frappe.parse_json(attachments):
			# att = {"filename": "...", "data": "base64...", "content_type": "..."}
			_attach(msg, att["filename"], att.get("content_type"), base64.b64decode(att["data"]))
	if forward_attachments and forward_uid and forward_folder:
		kept = frappe.parse_json(forward_attachments)
		for filename, content_type, data in _forwarded_attachments(
			account, forward_folder, forward_uid, kept
		):
			_attach(msg, filename, content_type, data)

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
			frappe.log_error("Copy to Sent folder", f"Failed to copy to Sent folder: {e!s}")

		# Mark original email as answered or forwarded
		try:
			_mark_original_email(account, reply_to_uid, reply_to_folder, forward_uid, forward_folder)
		except Exception as e:
			# Log but don't fail - email was already sent
			frappe.log_error("Mark original email", f"Failed to mark original email: {e!s}")

		# The draft it was written in, gone with it (a sent message left in Drafts was sent twice by mistake)
		if draft_uid and draft_folder:
			try:
				with imap_session(account) as client:
					_delete_draft(client, draft_folder, draft_uid)
			except Exception as e:
				frappe.log_error("Delete sent draft", f"Failed to delete the draft of a sent email: {e!s}")

		# Create Communication link if reference document is provided
		communication_created = False
		if reference_doctype and reference_name:
			try:
				result = create_communication_link(
					account_name=account.email,
					to=to,
					subject=subject,
					html_content=html_content,
					reference_doctype=reference_doctype,
					reference_name=reference_name,
				)
				communication_created = result.get("created", False)
			except Exception as e:
				# Log but don't fail - email was already sent
				frappe.log_error("Communication link", f"Failed to create communication link: {e!s}")

		return {
			"success": True,
			"message": _("Email sent successfully"),
			"communication_created": communication_created,
		}

	except Exception as e:
		frappe.log_error("Email send error", f"{e!s}")
		frappe.throw(_("Failed to send email: {0}").format(e))


def _references(account, message_id, uid, folder):
	"""The References of an answer: the whole chain of the message answered (conversations.references_for), read on
	the server; the message answered alone when its place is not given or cannot be read."""
	if not (uid and folder and IMAPClient):
		return message_id
	try:
		with imap_session(account) as client:
			return references_for(client, folder, uid, message_id) or message_id
	except Exception:
		return message_id


def _attach(msg, filename, content_type, data):
	"""A file joined to a message, of its own type (application/octet-stream when unknown), its name encoded for a
	name with accents (RFC 2231): the name used to go raw into the header, every file as octet-stream."""
	maintype, _sep, subtype = (content_type or "application/octet-stream").partition("/")
	part = MIMEBase(maintype or "application", subtype or "octet-stream")
	part.set_payload(data)
	encoders.encode_base64(part)
	part.add_header("Content-Disposition", "attachment", filename=filename)
	msg.attach(part)


def _forwarded_attachments(account, folder, uid, ids):
	"""(file name, content type, bytes) of the attachments of a forwarded message the person kept, read once from the
	IMAP server (EXAMINE and BODY.PEEK: forwarding never marks the message read)."""
	wanted = {str(i) for i in ids or []}
	if not wanted:
		return []
	uid = int(uid)
	with imap_session(account) as client:
		client.select_folder(folder, readonly=True)
		data = client.fetch([uid], ["BODY.PEEK[]"])
	if uid not in data:
		frappe.throw(_("Email not found"))
	msg = email.message_from_bytes(data[uid][b"BODY[]"])
	return [
		(attachment_filename(a), a.part.get_content_type(), attachment_bytes(a.part))
		for a in iter_attachments(msg)
		if a.id in wanted
	]


def _copy_to_sent_folder(account, msg):
	"""Copy sent message to the Sent folder via IMAP"""
	if not IMAPClient:
		return

	# Common sent folder names
	sent_folder_names = ["Sent", "Sent Items", "Sent Mail", "INBOX.Sent", "Envoyés"]

	with imap_session(account) as client:
		# Find the Sent folder
		folders = client.list_folders()
		sent_folder = None

		for flags, _delimiter, name in folders:
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


def _mark_original_email(account, reply_to_uid, reply_to_folder, forward_uid, forward_folder):
	"""Mark the original email as answered or forwarded"""
	if not IMAPClient:
		return

	# Mark as answered if this is a reply
	if reply_to_uid and reply_to_folder:
		with imap_session(account) as client:
			client.select_folder(reply_to_folder)
			client.add_flags([int(reply_to_uid)], [b"\\Answered"])

	# Mark as forwarded if this is a forward
	if forward_uid and forward_folder:
		with imap_session(account) as client:
			client.select_folder(forward_folder)
			# $Forwarded is a common keyword, not a standard flag
			client.add_flags([int(forward_uid)], [b"$Forwarded"])


@frappe.whitelist()
def save_draft_imap(
	account_name,
	to=None,
	cc=None,
	subject=None,
	html_content=None,
	draft_uid=None,
	draft_folder=None,
	bcc=None,
	reply_to_message_id=None,
	attachments=None,
	forward_uid=None,
	forward_folder=None,
	forward_attachments=None,
):
	"""Save a draft to the IMAP Drafts folder, again and again while the person writes (both screens save on their own).

	It keeps what the message will carry: Cc, Bcc, the message it answers, the files joined and the forwarded
	message's attachments kept. The new copy is appended before the old one (`draft_uid` in `draft_folder`) is
	deleted, so a failure never loses the text. Returns the new copy's place, for the next save and for sending."""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	# Build draft message
	msg = MIMEMultipart("mixed")
	msg["From"] = f'"{account.sender_name}" <{account.email}>' if account.sender_name else account.email
	if to:
		msg["To"] = to
	if cc:
		msg["Cc"] = cc
	if bcc:
		msg["Bcc"] = bcc
	if subject:
		msg["Subject"] = subject
	# When it was last written, shown in « Brouillons »
	msg["Date"] = formatdate(localtime=True)
	if reply_to_message_id:
		msg["In-Reply-To"] = reply_to_message_id
		msg["References"] = reply_to_message_id
	# A Message-ID of its own: the draft is found again by it where the server gives no APPENDUID
	message_id = make_msgid(domain=(account.email or "webmail.local").split("@")[-1])
	msg["Message-ID"] = message_id

	# Images written in the text are kept as parts of the draft, as they will leave (taken back, they show again)
	html_content, inline_parts = to_parts(html_content, (account.email or "webmail.local").split("@")[-1])

	# Body
	body = MIMEMultipart("alternative")
	if html_content:
		body.attach(MIMEText(plain_text(html_content), "plain", "utf-8"))
		body.attach(MIMEText(html_content, "html", "utf-8"))
	msg.attach(body_with(body, inline_parts))

	# The files joined, then the forwarded message's attachments kept: what send_email would carry
	if attachments:
		for att in frappe.parse_json(attachments):
			_attach(msg, att["filename"], att.get("content_type"), base64.b64decode(att["data"]))
	if forward_attachments and forward_uid and forward_folder:
		kept = frappe.parse_json(forward_attachments)
		for filename, content_type, data in _forwarded_attachments(
			account, forward_folder, forward_uid, kept
		):
			_attach(msg, filename, content_type, data)

	# Common drafts folder names
	drafts_folder_names = ["Drafts", "Draft", "INBOX.Drafts", "Brouillons"]

	with imap_session(account) as client:
		# Find the Drafts folder
		folders = client.list_folders()
		drafts_folder = None

		for flags, _delimiter, name in folders:
			# Check for \Drafts flag first
			if b"\\Drafts" in flags:
				drafts_folder = name
				break
			# Fallback to common names
			if name in drafts_folder_names:
				drafts_folder = name

		if not drafts_folder:
			frappe.throw(_("Drafts folder not found"))

		# Append the new copy first, with the \Draft flag
		import datetime

		response = client.append(
			drafts_folder, msg.as_bytes(), flags=[b"\\Draft", b"\\Seen"], msg_time=datetime.datetime.now()
		)
		uid = appended_uid(response)
		if uid is None:
			client.select_folder(drafts_folder, readonly=True)
			found = client.search(["HEADER", "Message-ID", message_id])
			uid = max(found) if found else None

		# Then the copy it replaces
		if (
			draft_uid
			and draft_folder
			and not (str(draft_folder) == str(drafts_folder) and str(draft_uid) == str(uid))
		):
			try:
				_delete_draft(client, draft_folder, draft_uid)
			except Exception:
				# The old copy stays: a duplicate draft rather than a lost one
				frappe.log_error("Replace draft", frappe.get_traceback())

	return {"success": True, "message": _("Draft saved"), "uid": uid, "folder": drafts_folder}


def _delete_draft(client, folder, uid):
	"""Delete one draft, and only it (_remove_from_folder)."""
	client.select_folder(folder)
	_remove_from_folder(client, [uid])


def _remove_from_folder(client, uids):
	"""Take these messages out of the selected folder, and only them: \\Deleted, then UID EXPUNGE (RFC 4315) where the
	server has UIDPLUS. A plain EXPUNGE also erases every other message of the folder marked deleted, by another mail
	client or another person of a shared mailbox (maintenance#1633); it stays the way of a server without UIDPLUS."""
	uids = [int(uid) for uid in uids]
	if not uids:
		return
	client.delete_messages(uids)
	if b"UIDPLUS" in (client.capabilities() or ()):
		client.uid_expunge(uids)
	else:
		client.expunge()


def _move_messages(client, uids, to_folder):
	"""Move these messages of the selected folder to `to_folder`: MOVE (RFC 6851) where the server has it, else a copy,
	then _remove_from_folder (which touches no other message unless the server has neither MOVE nor UIDPLUS)."""
	uids = [int(uid) for uid in uids]
	if not uids:
		return
	if b"MOVE" in (client.capabilities() or ()):
		client.move(uids, to_folder)
	else:
		client.copy(uids, to_folder)
		_remove_from_folder(client, uids)


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

	with imap_session(account) as client:
		client.select_folder(folder)

		if add_flags:
			flags = [f.encode() if isinstance(f, str) else f for f in frappe.parse_json(add_flags)]
			client.add_flags(uids, flags)

		if remove_flags:
			flags = [f.encode() if isinstance(f, str) else f for f in frappe.parse_json(remove_flags)]
			client.remove_flags(uids, flags)

		return {"success": True}


@frappe.whitelist()
def move_emails(account_name, uids, from_folder, to_folder):
	"""Move emails to another folder"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uids = frappe.parse_json(uids) if isinstance(uids, str) else uids

	with imap_session(account) as client:
		client.select_folder(from_folder)
		_move_messages(client, uids, to_folder)

		return {"success": True}


@frappe.whitelist()
def copy_emails(account_name, uids, from_folder, to_folder):
	"""Copy emails to another folder (without deleting from source)"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uids = frappe.parse_json(uids) if isinstance(uids, str) else uids

	with imap_session(account) as client:
		client.select_folder(from_folder)

		# Copy only, don't delete
		client.copy(uids, to_folder)

		return {"success": True, "copied": len(uids)}


@frappe.whitelist()
def rename_folder(account_name, old_name, new_name):
	"""Rename an IMAP folder"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	# Protected folders that cannot be renamed
	protected_folders = ["inbox", "sent", "drafts", "trash", "spam", "junk", "archive"]

	old_name_lower = old_name.lower()
	if old_name_lower in protected_folders or old_name_lower.split("/")[-1] in protected_folders:
		frappe.throw(_("Cannot rename this folder"))

	account = get_account(account_name)

	with imap_session(account) as client:
		# Check if source folder exists
		folders = [f[2] for f in client.list_folders()]
		if old_name not in folders:
			frappe.throw(_("Folder not found"))

		# Check if target folder already exists
		if new_name in folders:
			frappe.throw(_("A folder with this name already exists"))

		client.rename_folder(old_name, new_name)

		return {"success": True, "old_name": old_name, "new_name": new_name}


@frappe.whitelist()
def mark_folder_read(account_name, folder):
	"""Mark all emails in a folder as read"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	with imap_session(account) as client:
		client.select_folder(folder)

		# Search for unread messages
		uids = client.search(["UNSEEN"])

		if uids:
			# Mark all as read
			client.add_flags(uids, [b"\\Seen"])

		return {"success": True, "marked_count": len(uids)}


@frappe.whitelist()
def empty_folder(account_name, folder):
	"""Empty a folder (delete all emails permanently). Only allowed for Trash/Spam folders."""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)

	# Only allow emptying Trash or Spam folders for safety
	folder_lower = folder.lower()
	is_trash = "trash" in folder_lower or "deleted" in folder_lower or "corbeille" in folder_lower
	is_spam = "spam" in folder_lower or "junk" in folder_lower

	if not is_trash and not is_spam:
		frappe.throw(_("Only Trash and Spam folders can be emptied"))

	with imap_session(account) as client:
		client.select_folder(folder)

		# Search for all messages
		uids = client.search(["ALL"])

		if uids:
			# Mark all as deleted and expunge
			client.add_flags(uids, [b"\\Deleted"])
			client.expunge()

		return {"success": True, "deleted_count": len(uids)}


@frappe.whitelist()
def delete_folder(account_name, folder_name):
	"""Delete an IMAP folder"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	# Protected folders that cannot be deleted
	protected_folders = ["inbox", "sent", "drafts", "trash", "spam", "junk", "archive"]

	folder_lower = folder_name.lower()
	if folder_lower in protected_folders or folder_lower.split("/")[-1] in protected_folders:
		frappe.throw(_("Cannot delete this folder"))

	account = get_account(account_name)

	with imap_session(account) as client:
		# Check if folder exists
		folders = [f[2] for f in client.list_folders()]
		if folder_name not in folders:
			frappe.throw(_("Folder not found"))

		# Check if folder has subfolders
		has_children = any(f.startswith(folder_name + "/") for f in folders)
		if has_children:
			frappe.throw(_("Cannot delete folder with subfolders"))

		client.delete_folder(folder_name)

		return {"success": True, "deleted": folder_name}


@frappe.whitelist()
def delete_emails(account_name, uids, folder, permanent=False):
	"""Delete emails (move to trash or permanent)"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	uids = frappe.parse_json(uids) if isinstance(uids, str) else uids
	permanent = to_bool(permanent)

	with imap_session(account) as client:
		client.select_folder(folder)

		if permanent:
			_remove_from_folder(client, uids)
			return {"success": True, "action": "permanent_delete"}
		else:
			# Try to find trash folder
			folders = client.list_folders()
			trash_folder = None

			# Common trash folder names
			trash_names = [
				"trash",
				"corbeille",
				"deleted",
				"deleted items",
				"deleted messages",
				"bin",
				"papierkorb",
				"cestino",
			]

			for flags, _delimiter, name in folders:
				# Normalize folder name to string
				folder_name = name if isinstance(name, str) else name.decode()
				folder_name_lower = folder_name.lower()
				# Normalize flags to strings for comparison
				flags_str = [f.decode() if isinstance(f, bytes) else f for f in flags]

				# Check for \Trash flag (handle both bytes and string)
				has_trash_flag = b"\\Trash" in flags or "\\Trash" in flags_str
				if has_trash_flag and not trash_folder:
					trash_folder = folder_name
				# Check folder name as fallback
				if not trash_folder and (
					folder_name_lower in trash_names
					or folder_name_lower.endswith("/trash")
					or folder_name_lower.endswith("/corbeille")
				):
					trash_folder = folder_name

			# Normalize current folder for comparison
			current_folder = (
				folder
				if isinstance(folder, str)
				else folder.decode()
				if isinstance(folder, bytes)
				else str(folder)
			)

			if trash_folder and current_folder.lower() != trash_folder.lower():
				_move_messages(client, uids, trash_folder)
				return {"success": True, "action": "moved_to_trash", "trash_folder": trash_folder}
			else:
				# No trash folder found or already in trash: deleted for good
				_remove_from_folder(client, uids)
				return {
					"success": True,
					"action": "deleted",
					"reason": "no_trash_folder" if not trash_folder else "already_in_trash",
				}


@frappe.whitelist()
def get_attachment(account_name, uid, folder, attachment_id):
	"""Download an attachment, in base64 (the composer's forward, the viewer's download button).

	The attachment is found with the same rule as the list of get_email_content (`mime_parts`): an attachment the list
	shows can always be downloaded. A preview or a file to save goes through `attachments.download_attachment`, which
	streams the bytes instead of wrapping them in JSON.
	"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	filename, content_type, payload = read_attachment(account, folder, uid, attachment_id)
	return {
		"filename": filename,
		"content_type": content_type,
		"data": base64.b64encode(payload).decode(),
		"size": len(payload),
	}


def read_attachment(account, folder, uid, attachment_id):
	"""(file name, content type, bytes) of one attachment of a message, read again from the IMAP server.

	A read-only EXAMINE and BODY.PEEK: reading an attachment never marks its message as read. Every action on an
	attachment (attachments.py) reads it here, on the server, so its bytes never travel through the browser.
	"""
	uid = int(uid)
	with imap_session(account) as client:
		client.select_folder(folder, readonly=True)
		data = client.fetch([uid], ["BODY.PEEK[]"])

	if uid not in data:
		frappe.throw(_("Email not found"))

	msg = email.message_from_bytes(data[uid][b"BODY[]"])
	for attachment in iter_attachments(msg):
		if attachment.id == str(attachment_id):
			return (
				attachment_filename(attachment),
				attachment.part.get_content_type(),
				attachment_bytes(attachment.part),
			)

	frappe.throw(_("Attachment not found"))


# How an attached message (message/rfc822, message/global, a delivery report, a read receipt…) is written back: with
# CRLF line ends and its headers as they were folded, which is how the message carries it. Python's own defaults end
# lines with LF and fold long headers again: the file saved was not the one the message carried, nor of its size
# (which neomail_attachments.find compares with NeoMail's). What Python's generator cannot keep, it still normalises:
# a header without a space after its colon gets one, an empty header gets a space, lines ended by LF alone get CRLF, a
# report's last block gets the blank line that ends it.
_AS_CARRIED = email.policy.compat32.clone(linesep="\r\n", max_line_length=0)


def attachment_bytes(part):
	"""The bytes of an attachment. An attached message (any message/*) has no payload to decode: its bytes are the
	message it carries, written back as it carries it (_AS_CARRIED), which saves as a .eml file. Before, only
	message/rfc822 was: a delivery report or a read receipt came out as no bytes at all."""
	payload = part.get_payload(decode=True)
	if payload is None and part.get_content_maintype() == "message":
		# The part written again by its own generator (which knows each kind: an e-mail, a report's blocks), its own
		# headers taken off; one without headers of its own starts with the blank line
		written = part.as_bytes(policy=_AS_CARRIED)
		if written.startswith(b"\r\n"):
			return written[2:]
		_headers, blank, body = written.partition(b"\r\n\r\n")
		return body if blank else b""
	return payload or b""


def attachment_filename(attachment):
	"""The decoded file name of an attachment; one without a name is called after its rank."""
	filename = attachment.part.get_filename()
	if filename:
		return decode_mime_header(filename)
	suffix = ".eml" if attachment.part.get_content_type() == "message/rfc822" else ""
	return f"attachment_{attachment.rank}{suffix}"


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
	is_nora_seen=None,
	limit=50,
	offset=0,
):
	"""Advanced email search with multiple criteria"""
	if not IMAPClient:
		frappe.throw(_("imapclient package is not installed"))

	account = get_account(account_name)
	limit = min(int(limit), 100)
	offset = int(offset)

	# Convert boolean parameters (handles string "true"/"false" from JS)
	has_attachment = to_bool(has_attachment) if has_attachment is not None else None
	is_unread = to_bool(is_unread) if is_unread is not None else None
	is_flagged = to_bool(is_flagged) if is_flagged is not None else None
	is_nora_seen = to_bool(is_nora_seen) if is_nora_seen is not None else None

	with imap_session(account) as client:
		client.select_folder(folder)

		# Build search criteria
		criteria = []

		# Simple text search across common fields, word by word (flat on purpose: see _search_charset)
		if _text_criteria(query):
			criteria.append(_text_criteria(query))

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

		if is_nora_seen is True:
			criteria.append(["KEYWORD", "$NoraSeen"])
		elif is_nora_seen is False:
			criteria.append(["NOT", "KEYWORD", "$NoraSeen"])

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

		messages = client.search(search_criteria, charset=_search_charset(search_criteria))
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
						decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else ""
					),
					"to": format_address(env.to[0]) if env.to else "",
					"date": env.date.isoformat() if env.date else None,
					"seen": b"\\Seen" in flags,
					"flagged": b"\\Flagged" in flags,
					"answered": b"\\Answered" in flags,
					"forwarded": b"$Forwarded" in flags,
					"nora_seen": b"$NoraSeen" in flags,
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


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=120, seconds=60)
def clean_signature(html=None):
	"""A signature pasted as HTML as it will be kept and sent (email_html.clean_signature_html), for the signature
	manager's preview: what goes, goes before the person saves, not after. The desk's people only (the webmail is
	theirs), and so many a minute: up to a megabyte of HTML read twice is work for the server."""
	from frappe_webmail.email_html import MAX_SIGNATURE_SOURCE, clean_signature_html

	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	html = html if isinstance(html, str) else ""
	if len(html) > MAX_SIGNATURE_SOURCE:
		frappe.throw(_("This signature is too large."))
	return {"html": clean_signature_html(html)}


@frappe.whitelist()
def get_default_signature(account_name=None):
	"""Get default signature content: the company's, written for the person, when an Email Signature Template applies
	to them and does not leave them their own (never to a portal account: signatures.template_for); else the signature
	they have set as their default one. Empty when there is none.

	For a mailbox (`account_name`, one the person owns or is shared, get_account refusing any other), the signature a
	message written from it starts with: the mailbox's own, and a mailbox shared with them signs as the mailbox, never
	with their numbers (signatures.signature_for)."""
	from frappe_webmail.signatures import signature_for

	account = None
	if account_name:
		mailbox = get_account(account_name)
		account = {
			"user": mailbox.user,
			"email": mailbox.email,
			"sender_name": mailbox.sender_name,
			"default_signature": mailbox.default_signature,
		}
	return (signature_for(frappe.session.user, account) or {}).get("html") or ""


# ============================================
# CONTACTS (ERPNext Integration)
# ============================================


def _may_read_contacts():
	"""Whether the person may read any contact. The lists below go through frappe.get_list, which applies their rights
	and user permissions, and refuses outright someone with no right at all: a portal client gets nothing, not an
	error, for the composer's suggestions."""
	return bool(frappe.has_permission("Contact", "read"))


def _existing_contact(email):
	"""Whether a contact the person may read already has this address, and its name. A contact they may not read is as
	if it did not exist: saying « it is there » would tell them which addresses the company keeps (maintenance#1541)."""
	# A row whose contact is gone is skipped (has_permission would raise on it); read by the database layer, below the
	# rights it checks itself.
	for name in frappe.db.get_values("Contact Email", {"email_id": email}, "parent", pluck=True, limit=20):
		if frappe.db.exists("Contact", name) and frappe.has_permission("Contact", "read", doc=name):
			return True, name
	return False, None


def _readable_record(doctype, name):
	"""Whether `name` is a record of `doctype` (a DocType of records, not a table or a single) that the person may read:
	one answer for a record that is not there and one that is not theirs to read."""
	if not isinstance(doctype, str) or not isinstance(name, str) or not doctype or not name:
		return False
	if not frappe.db.exists("DocType", {"name": doctype, "istable": 0, "issingle": 0}):
		return False
	return bool(frappe.db.exists(doctype, name) and frappe.has_permission(doctype, "read", doc=name))


def _require_desk_user():
	"""The webmail is the desk's: a portal client (Website User) keeps no mailbox here, and has no contacts to add or
	documents to pick through it (maintenance#1541)."""
	user = frappe.session.user
	if user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def search_contacts(query, limit=10):
	"""Search contacts by name or email for autocomplete: the contacts the person may read. It used to read every
	contact for anyone signed in, a portal client included (maintenance#1541)."""
	if not query or len(query) < 2 or not _may_read_contacts():
		return []

	limit = min(int(limit), 50)

	# Search in Contact DocType (ERPNext standard)
	contacts = []
	fields = ["name", "first_name", "last_name", "full_name", "email_id", "image"]

	# Search by name
	name_results = frappe.get_list(
		"Contact",
		filters=[
			["Contact", "full_name", "like", f"%{query}%"],
		],
		fields=fields,
		limit=limit,
	)

	# Search by email in Contact Email child table
	email_results = frappe.get_list(
		"Contact",
		filters=[["Contact Email", "email_id", "like", f"%{query}%"]],
		fields=fields,
		distinct=True,
		limit=limit,
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
					"full_name": contact.full_name
					or f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
					"email": contact.email_id or (emails[0].email_id if emails else ""),
					"emails": [e.email_id for e in emails],
					"image": contact.image,
				}
			)

	return contacts[:limit]


@frappe.whitelist()
def get_contact_by_email(email):
	"""Get contact details by email address: a contact the person may read, or None. It answered anyone signed in,
	a portal client included, with any contact's phones, company and links (the class of #1531)."""
	if not email or not _may_read_contacts():
		return None

	# A contact the person may read among all those that have the address: the first row alone said None when it was
	# one they may not read, though they may read another.
	found, name = _existing_contact(email)
	if not found:
		return None

	contact = frappe.get_doc("Contact", name)

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


# What a sender can be in Neoffice, in that order: the record their contact is linked to, and its documents counted
# for the year (canvas « Neodesk », boards 2 and 7: « Supplier X · 3 invoices this year »)
SENDER_KINDS = (
	("Supplier", "Purchase Invoice", "supplier"),
	("Customer", "Sales Invoice", "customer"),
)


@frappe.whitelist()
def get_sender_card(email):
	"""Who wrote, in Neoffice: the supplier or the customer the sender's contact is linked to, with its invoices of
	the year, for the card under a message's sender (the desk's mail and Neodesk read the same answer). Only what the
	person may read: None for a contact or a record they may not see, no count without the right to read invoices."""
	contact = get_contact_by_email(email)
	if not contact:
		return None
	links = {link["link_doctype"]: link for link in contact["links"]}
	for doctype, invoice_doctype, field in SENDER_KINDS:
		link = links.get(doctype)
		if not link or not frappe.has_permission(doctype, "read", doc=link["link_name"]):
			continue
		invoices = None
		if frappe.db.exists("DocType", invoice_doctype) and frappe.has_permission(invoice_doctype, "read"):
			year_start = frappe.utils.getdate(frappe.utils.nowdate()).replace(month=1, day=1)
			invoices = len(
				frappe.get_list(
					invoice_doctype,
					filters={field: link["link_name"], "docstatus": 1, "posting_date": [">=", year_start]},
					pluck="name",
					limit_page_length=1000,
				)
			)
		return {
			"doctype": doctype,
			"name": link["link_name"],
			"title": link.get("link_title") or link["link_name"],
			"kind": _(doctype),
			"url": frappe.utils.get_url_to_form(doctype, link["link_name"]),
			"invoices": invoices,
		}
	return None


@frappe.whitelist()
def create_contact_from_email(email, name=None):
	"""Create a new contact from an email address, with the person's right to create contacts. It used to insert with
	ignore_permissions for anyone signed in (maintenance#1541)."""
	if not email:
		frappe.throw(_("Email address is required"))
	_require_desk_user()
	frappe.has_permission("Contact", "create", throw=True)

	# Check if contact with this email already exists
	known, named = _existing_contact(email)
	if known:
		return {"success": False, "message": _("Contact with this email already exists"), "contact": named}

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

	contact.insert()
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

	with imap_session(account) as client:
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

		# Check which contacts already exist (named only to whoever may read them)
		for contact in contacts:
			contact["exists"], contact["contact_name"] = _existing_contact(contact["email"])

		return contacts


@frappe.whitelist()
def bulk_create_contacts(contacts_json):
	"""Create multiple contacts from a list, with the person's right to create contacts (create_contact_from_email)."""
	_require_desk_user()
	frappe.has_permission("Contact", "create", throw=True)
	contacts = frappe.parse_json(contacts_json)

	created = []
	skipped = []

	for contact_data in contacts:
		email = contact_data.get("email")
		name = contact_data.get("name")

		if not email:
			continue

		# Check if already exists
		known, named = _existing_contact(email)
		if known:
			skipped.append({"email": email, "contact": named})
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
	"""Get recently used contacts for quick access: those the person may read (maintenance#1541)."""
	if not _may_read_contacts():
		return []
	limit = min(int(limit), 50)

	# Get contacts ordered by modification date
	contacts = frappe.get_list(
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
	"""Link a contact to a document (Customer, Supplier, etc.), with the person's own rights: writing the contact and
	reading the document. It used to save with ignore_permissions, so anyone signed in could relink any contact."""
	_require_desk_user()
	# A record the person may not read is answered as one that does not exist: « no permission » would tell them which
	# contacts and documents the company keeps.
	if not _readable_record("Contact", contact_name):
		frappe.throw(_("Contact not found"), frappe.DoesNotExistError)
	frappe.has_permission("Contact", "write", doc=contact_name, throw=True)
	if not _readable_record(link_doctype, link_name):
		frappe.throw(_("{0} {1} not found").format(_(link_doctype), link_name), frappe.DoesNotExistError)

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

	contact.save()

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

	# Convert boolean parameters (handles string "true"/"false" from JS)
	has_attachment = to_bool(has_attachment)
	mark_as_read = to_bool(mark_as_read)
	mark_as_starred = to_bool(mark_as_starred)

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

	# Boolean fields that need conversion from JS strings
	bool_fields = ["enabled", "has_attachment", "mark_as_read", "mark_as_starred"]

	for field in allowed_fields:
		if field in kwargs:
			value = kwargs[field]
			if field in bool_fields:
				value = to_bool(value)
			setattr(filter_doc, field, value)

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
	with imap_session(account) as client:
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
			_move_messages(client, [uid], filter_doc.target_folder)
			return True

	elif filter_doc.action_type == "delete":
		_remove_from_folder(client, [uid])
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

	with imap_session(account) as client:
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
# TRUSTED SOURCES
# ============================================


@frappe.whitelist()
def add_trusted_source(account_name, value, source_type):
	"""
	Add a trusted sender or domain to the account.

	Args:
		account_name: The account email
		value: Email address (for Sender) or domain (for Domain)
		source_type: "Sender" or "Domain"
	"""
	account = get_account(account_name)

	# Check if trusted_sources field exists on the account
	if not hasattr(account, "trusted_sources"):
		frappe.throw(
			_("Trusted sources feature is not available. Please update the Webmail Account DocType.")
		)

	# Validate source_type
	if source_type not in ("Sender", "Domain"):
		frappe.throw(_("Invalid source type. Must be 'Sender' or 'Domain'"))

	# Normalize value
	value = value.strip().lower()

	# Check if already exists
	for row in account.trusted_sources or []:
		if row.source_type == source_type and row.value.lower() == value:
			return {"exists": True, "message": _("Already in trusted list")}

	account.append("trusted_sources", {"source_type": source_type, "value": value})
	account.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def remove_trusted_source(account_name, value, source_type):
	"""
	Remove a trusted sender or domain from the account.

	Args:
		account_name: The account email
		value: Email address (for Sender) or domain (for Domain)
		source_type: "Sender" or "Domain"
	"""
	account = get_account(account_name)

	# Check if trusted_sources field exists on the account
	if not hasattr(account, "trusted_sources") or not account.trusted_sources:
		return {"success": False, "message": _("Not found in trusted list")}

	# Normalize value
	value = value.strip().lower()

	# Find and remove
	to_remove = None
	for row in account.trusted_sources:
		if row.source_type == source_type and row.value.lower() == value:
			to_remove = row
			break

	if to_remove:
		account.remove(to_remove)
		account.save(ignore_permissions=True)
		frappe.db.commit()
		return {"success": True}

	return {"success": False, "message": _("Not found in trusted list")}


@frappe.whitelist()
def is_sender_trusted(account_name, from_email):
	"""
	Check if a sender or their domain is trusted.

	Args:
		account_name: The account email
		from_email: The sender's email address

	Returns:
		bool: True if the sender or their domain is trusted
	"""
	account = get_account(account_name)

	if not from_email:
		return False

	# Check if trusted_sources field exists on the account
	if not hasattr(account, "trusted_sources") or not account.trusted_sources:
		return False

	from_email = from_email.strip().lower()
	domain = from_email.split("@")[1] if "@" in from_email else ""

	for row in account.trusted_sources:
		row_value = row.value.lower()
		if row.source_type == "Sender" and row_value == from_email:
			return True
		if row.source_type == "Domain" and domain and row_value == domain:
			return True

	return False


@frappe.whitelist()
def get_trusted_sources(account_name):
	"""
	Get all trusted sources for an account.

	Args:
		account_name: The account email

	Returns:
		list: List of trusted sources with type and value
	"""
	account = get_account(account_name)

	# Check if trusted_sources field exists on the account
	if not hasattr(account, "trusted_sources") or not account.trusted_sources:
		return []

	return [{"source_type": row.source_type, "value": row.value} for row in account.trusted_sources]


# ============================================
# CAPABILITIES
# ============================================


@frappe.whitelist()
def get_capabilities():
	"""Optional companions installed on this site. The UI only shows what can run:
	a bare Frappe site without `nora` gets a plain webmail, not buttons that 404."""
	installed = set(frappe.get_installed_apps())
	return {"nora": "nora" in installed}


# ============================================
# UI PREFERENCES
# ============================================


@frappe.whitelist()
def get_ui_preferences(account_name):
	"""Get UI preferences (column widths, collapsed folders) for an account"""
	account = get_account(account_name)

	# Parse collapsed_folders JSON
	collapsed_folders = []
	if account.collapsed_folders:
		import json

		try:
			collapsed_folders = json.loads(account.collapsed_folders)
		except (json.JSONDecodeError, TypeError):
			collapsed_folders = []

	# .get(): the column arrives with the DocType sync — a worker serving requests
	# between `git pull` and `bench migrate` must not 500 on a missing attribute.
	collapsed = account.get("sidebar_collapsed")
	return {
		"sidebar_width": account.sidebar_width or 220,
		"email_list_width": account.email_list_width or 350,
		"collapsed_folders": collapsed_folders,
		# None = the user never chose → the client picks a default from the viewport
		"sidebar_collapsed": None if collapsed is None else bool(collapsed),
	}


@frappe.whitelist()
def save_ui_preferences(
	account_name, sidebar_width=None, email_list_width=None, collapsed_folders=None, sidebar_collapsed=None
):
	"""Save UI preferences (column widths, collapsed folders, folder rail) for an account"""
	import json

	account = get_account(account_name)

	if sidebar_collapsed is not None:
		account.sidebar_collapsed = 1 if to_bool(sidebar_collapsed) else 0

	# Validate and constrain values
	if sidebar_width is not None:
		sidebar_width = int(sidebar_width)
		# Enforce min/max limits
		sidebar_width = max(150, min(400, sidebar_width))
		account.sidebar_width = sidebar_width

	if email_list_width is not None:
		email_list_width = int(email_list_width)
		# Enforce min/max limits
		email_list_width = max(250, min(600, email_list_width))
		account.email_list_width = email_list_width

	if collapsed_folders is not None:
		# Handle both string (from JS) and list
		if isinstance(collapsed_folders, str):
			try:
				collapsed_folders = json.loads(collapsed_folders)
			except (json.JSONDecodeError, TypeError):
				collapsed_folders = []
		# Store as JSON string
		account.collapsed_folders = json.dumps(collapsed_folders)

	account.save(ignore_permissions=True)
	frappe.db.commit()

	# Parse collapsed_folders for response
	response_collapsed = []
	if account.collapsed_folders:
		try:
			response_collapsed = json.loads(account.collapsed_folders)
		except (json.JSONDecodeError, TypeError):
			response_collapsed = []

	return {
		"success": True,
		"sidebar_width": account.sidebar_width,
		"email_list_width": account.email_list_width,
		"collapsed_folders": response_collapsed,
	}


# ============================================
# FOLDER MAPPING
# ============================================


@frappe.whitelist()
def get_folder_mapping(account_name):
	"""Get folder mapping for an account (configured or auto-detected)"""
	account = get_account(account_name)

	# Get configured folders (manual override)
	configured = {
		"inbox": account.inbox_folder or "",
		"sent": account.sent_folder or "",
		"drafts": account.drafts_folder or "",
		"trash": account.trash_folder or "",
		"spam": account.spam_folder or "",
		"archive": account.archive_folder or "",
	}

	# Get auto-detected folders from IMAP
	auto_detected = {}
	try:
		with imap_session(account) as client:
			folders = client.list_folders()

			for flags, delimiter, name in folders:
				# Decode folder name
				if isinstance(name, bytes):
					name = name.decode("utf-8")
				if isinstance(delimiter, bytes):
					delimiter = delimiter.decode("utf-8")

				# Convert flags to strings
				flags_str = [f.decode("utf-8") if isinstance(f, bytes) else f for f in flags]
				name_lower = name.lower()

				# Auto-detect based on IMAP flags first
				if "\\Inbox" in flags_str or name_lower == "inbox":
					if not auto_detected.get("inbox"):
						auto_detected["inbox"] = name
				if "\\Sent" in flags_str:
					if not auto_detected.get("sent"):
						auto_detected["sent"] = name
				if "\\Drafts" in flags_str:
					if not auto_detected.get("drafts"):
						auto_detected["drafts"] = name
				if "\\Trash" in flags_str:
					if not auto_detected.get("trash"):
						auto_detected["trash"] = name
				if "\\Junk" in flags_str or "\\Spam" in flags_str:
					if not auto_detected.get("spam"):
						auto_detected["spam"] = name
				if "\\Archive" in flags_str:
					if not auto_detected.get("archive"):
						auto_detected["archive"] = name

				# Fallback to name-based detection
				if not auto_detected.get("inbox") and name_lower == "inbox":
					auto_detected["inbox"] = name
				if not auto_detected.get("sent") and name_lower in [
					"sent",
					"sent items",
					"sent mail",
					"envoyés",
				]:
					auto_detected["sent"] = name
				if not auto_detected.get("drafts") and name_lower in ["drafts", "brouillons"]:
					auto_detected["drafts"] = name
				if not auto_detected.get("trash") and name_lower in ["trash", "deleted items", "corbeille"]:
					auto_detected["trash"] = name
				if not auto_detected.get("spam") and name_lower in [
					"spam",
					"junk",
					"junk e-mail",
					"courrier indésirable",
				]:
					auto_detected["spam"] = name
				if not auto_detected.get("archive") and name_lower in ["archive", "archives"]:
					auto_detected["archive"] = name

	except Exception as e:
		frappe.log_error("Folder auto-detection failed", str(e))

	# Merge: configured takes precedence over auto-detected
	effective = {
		"inbox": configured["inbox"] or auto_detected.get("inbox", "INBOX"),
		"sent": configured["sent"] or auto_detected.get("sent", ""),
		"drafts": configured["drafts"] or auto_detected.get("drafts", ""),
		"trash": configured["trash"] or auto_detected.get("trash", ""),
		"spam": configured["spam"] or auto_detected.get("spam", ""),
		"archive": configured["archive"] or auto_detected.get("archive", ""),
	}

	return {
		"configured": configured,
		"auto_detected": auto_detected,
		"effective": effective,
	}


@frappe.whitelist()
def save_folder_mapping(
	account_name,
	inbox_folder=None,
	sent_folder=None,
	drafts_folder=None,
	trash_folder=None,
	spam_folder=None,
	archive_folder=None,
):
	"""Save folder mapping for an account"""
	account = _owned_account(account_name)

	# Update only non-None values
	if inbox_folder is not None:
		account.inbox_folder = inbox_folder.strip() if inbox_folder else ""
	if sent_folder is not None:
		account.sent_folder = sent_folder.strip() if sent_folder else ""
	if drafts_folder is not None:
		account.drafts_folder = drafts_folder.strip() if drafts_folder else ""
	if trash_folder is not None:
		account.trash_folder = trash_folder.strip() if trash_folder else ""
	if spam_folder is not None:
		account.spam_folder = spam_folder.strip() if spam_folder else ""
	if archive_folder is not None:
		account.archive_folder = archive_folder.strip() if archive_folder else ""

	account.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


# ============================================
# HELPERS
# ============================================


def get_account(account_name):
	"""Get and validate email account (owner or shared user). A mailbox that is not the person's is answered as one that
	does not exist: « access denied » told which addresses have a mailbox here (maintenance#1541)."""
	if not isinstance(account_name, str) or not frappe.db.exists("Webmail Account", account_name):
		frappe.throw(_("Account not found"))

	account = frappe.get_doc("Webmail Account", account_name)
	user = frappe.session.user

	# Check if user is owner
	is_owner = account.user == user

	# Check if user has shared access
	is_shared_user = False
	if not is_owner:
		is_shared_user = frappe.db.exists(
			"Webmail Account User", {"parent": account_name, "user": user, "parenttype": "Webmail Account"}
		)

	if not is_owner and not is_shared_user:
		frappe.throw(_("Account not found"))

	if not account.enabled:
		frappe.throw(_("Account is disabled"))

	return account


def _owned_account(account_name):
	"""The account, for its owner only: its settings are theirs to change, not those of the people it is shared with,
	whose change would hold for everyone (maintenance#1654)."""
	account = get_account(account_name)
	if account.user != frappe.session.user:
		frappe.throw(_("Only the owner of this mailbox can change its settings."), frappe.PermissionError)
	return account


# A header a mailer wrote over several lines (RFC 5322 §2.2.3, « folding »: a line break before a space or a tab) is one
# line: the break goes, the space stays. A long attachment name read back from the server said « …de notre\r\n
# rendez-vous… » in the webmail's list (Python writes a long quoted name over two lines, and so do other mailers).
_FOLDED = re.compile(r"\r?\n(?=[ \t])")


def decode_mime_header(header):
	"""Decode MIME encoded header, unfolded first (one line, as it was before a mailer folded it)."""
	if not header:
		return ""
	if isinstance(header, bytes):
		header = header.decode("utf-8", errors="replace")
	header = _FOLDED.sub("", str(header))

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

	def normalize(val):
		"""Convert bytes to lowercase string"""
		if isinstance(val, bytes):
			return val.decode("utf-8", errors="ignore").lower()
		if isinstance(val, str):
			return val.lower()
		return ""

	def is_attachment_type(main_type, sub_type):
		"""Check if MIME type indicates an attachment"""
		main_type = normalize(main_type)
		sub_type = normalize(sub_type)
		# Skip text/plain and text/html (body content)
		if main_type == "text":
			return False
		# Skip multipart types
		if main_type == "multipart":
			return False
		# Common attachment types - application/*, audio/*, video/*, image/*
		attachment_types = ("application", "audio", "video", "image")
		return main_type in attachment_types

	def check_part(part):
		"""Recursively check parts for attachments"""
		if not isinstance(part, tuple | list) or len(part) < 2:
			return False

		first = part[0]

		# Multipart: first element is a tuple/list (nested part)
		if isinstance(first, tuple | list):
			for item in part:
				if isinstance(item, tuple | list):
					if check_part(item):
						return True
			return False

		# Single part: [type, subtype, params, id, desc, encoding, size, ...]
		# Check if this is a MIME type we recognize as attachment
		if is_attachment_type(first, part[1] if len(part) > 1 else ""):
			return True

		return False

	return check_part(bodystructure)


# ============================================
# ATTACHMENT SOURCES
# ============================================


@frappe.whitelist()
def get_file_manager_files(folder="Home", start=0, page_length=20, search=None):
	"""
	Get files from Frappe File Manager.

	Args:
		folder: Folder name to browse (default: "Home")
		start: Pagination offset
		page_length: Number of files per page
		search: Search text to filter files

	Returns:
		dict: List of files and folders
	"""
	_require_desk_user()
	start = max(0, int(start))
	page_length = max(1, min(int(page_length), 50))
	folder = folder or "Home"
	# A folder is browsed only by who may read it: any folder id used to list its subfolders, « Users » the private
	# Drive folder of every person, named after their e-mail address.
	# One answer for a folder that is not there and one the person may not read.
	if folder != "Home" and not _readable_record("File", folder):
		frappe.throw(_("Access denied"), frappe.PermissionError)

	filters = {"is_private": 0}  # Only public files for now

	if folder and folder != "Home":
		filters["folder"] = folder

	if search:
		filters["file_name"] = ["like", f"%{search}%"]

	# Get folders first: those the person may read
	folders = [
		f
		for f in frappe.get_all(
			"File",
			filters={"is_folder": 1, "folder": folder},
			fields=["name", "file_name", "folder", "is_folder", "modified"],
			order_by="file_name asc",
		)
		if frappe.has_permission("File", "read", doc=f.name)
	]

	# Get files: those the person's rights list (frappe.get_list; get_all listed every public file to anyone signed in)
	files = frappe.get_list(
		"File",
		filters={**filters, "is_folder": 0},
		fields=["name", "file_name", "file_url", "file_size", "file_type", "folder", "is_folder", "modified"],
		order_by="modified desc",
		limit_start=start,
		limit_page_length=page_length,
	)

	# Count total files for pagination, under the same rights
	counted = frappe.get_list(
		"File", filters={**filters, "is_folder": 0}, fields=["count(`tabFile`.name) as total"]
	)
	total_files = cint(counted[0].get("total")) if counted else 0

	return {
		"folders": folders,
		"files": files,
		"total": total_files,
		"has_more": start + page_length < total_files,
	}


@frappe.whitelist()
def get_file_content(file_url):
	"""
	Get content of a file from File Manager.

	Args:
		file_url: The file URL (e.g., "/files/example.pdf")

	Returns:
		dict: filename, content (base64), content_type
	"""
	if not file_url:
		frappe.throw(_("File URL is required"))
	_require_desk_user()

	# The File records of this address (several documents may share one file): a public one, as the web serves it, or
	# a private one the person's rights open. Any other is answered as not there: « access denied » said it existed,
	# and the first record alone refused a file another record let the person read.
	rows = frappe.get_all(
		"File", filters={"file_url": file_url, "is_folder": 0}, fields=["name", "is_private"], limit=20
	)
	name = next(
		(r.name for r in rows if not r.is_private or frappe.has_permission("File", "read", doc=r.name)), None
	)
	if not name:
		frappe.throw(_("File not found"), frappe.DoesNotExistError)

	# Load full doc to get content
	file = frappe.get_doc("File", name)

	try:
		content = file.get_content()
	except Exception as e:
		frappe.log_error("File content error", f"Failed to read file {file_url}: {e!s}")
		frappe.throw(_("Could not read file content"))
	# A text file comes back as text (File.get_content decodes it): it is sent as its bytes.
	if isinstance(content, str):
		content = content.encode()

	return {
		"filename": file.file_name,
		"content": base64.b64encode(content).decode(),
		"content_type": file.file_type or "application/octet-stream",
		"size": len(content),
	}


@frappe.whitelist()
def get_drive_files(folder=None, search=None, limit=20):
	"""Files and folders of the Neoffice Drive (the `suite` app) for the composer's « From the Drive » tab: the person's
	own Drive, a folder's content, or a search across what they may read (frappe_webmail.drive).

	It used to read the old Drive app's `Drive Entity`, which no instance has any more: the tab said « not installed ».
	"""
	from frappe_webmail import drive

	if not drive.available():
		return {
			"files": [],
			"folders": [],
			"installed": False,
			"message": _("The Drive is not installed on this instance"),
		}
	return {"installed": True, **drive.listing(folder, search, min(int(limit), 50))}


@frappe.whitelist()
def get_drive_file_content(entity_name):
	"""A Drive file, in base64, to attach to a message (the Drive's own rules of access decide)."""
	from frappe_webmail import drive

	if not drive.available():
		frappe.throw(_("The Drive is not installed on this instance"))
	if not entity_name:
		frappe.throw(_("Entity name is required"))
	filename, content_type, content = drive.read(entity_name)
	return {
		"filename": filename,
		"content": base64.b64encode(content).decode(),
		"content_type": content_type,
		"size": len(content),
	}


@frappe.whitelist()
def get_printable_doctypes():
	"""
	Get list of DocTypes that have print formats.

	Returns:
		list: DocTypes with print support
	"""
	# Common DocTypes with print formats
	common_doctypes = [
		"Sales Invoice",
		"Sales Order",
		"Quotation",
		"Purchase Invoice",
		"Purchase Order",
		"Delivery Note",
		"Purchase Receipt",
		"Stock Entry",
		"Payment Entry",
		"Journal Entry",
		"Material Request",
		"Request for Quotation",
		"Supplier Quotation",
		"Lead",
		"Opportunity",
	]

	result = []
	for doctype in common_doctypes:
		if frappe.db.exists("DocType", doctype):
			# Check if user has read permission
			if frappe.has_permission(doctype, "read"):
				result.append(
					{
						"doctype": doctype,
						"label": _(doctype),
					}
				)

	return result


@frappe.whitelist()
def search_documents(doctype, search_text, limit=10):
	"""
	Search for documents of a specific DocType.

	Args:
		doctype: DocType to search
		search_text: Search query
		limit: Max results

	Returns:
		list: Matching documents
	"""
	if not doctype:
		frappe.throw(_("DocType is required"))

	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("No permission to read {0}").format(doctype))

	limit = min(int(limit), 20)

	# Use Frappe's search_link method
	return frappe.call(
		"frappe.desk.search.search_link",
		doctype=doctype,
		txt=search_text or "",
		page_length=limit,
	)


@frappe.whitelist()
def get_recent_documents(doctype, limit=10):
	"""
	Get recent documents of a specific DocType.

	Args:
		doctype: DocType to fetch
		limit: Max results (default 10)

	Returns:
		list: Recent documents with value and description
	"""
	if not doctype:
		frappe.throw(_("DocType is required"))
	_require_desk_user()

	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("No permission to read {0}").format(doctype))

	limit = min(int(limit), 20)

	# Get the title field for the doctype
	meta = frappe.get_meta(doctype)
	title_field = meta.title_field or "name"

	# Get recent documents ordered by modified date: those the person may read (their user permissions, the records of
	# their own when that is all their role gives). get_all listed any (maintenance#1541).
	docs = frappe.get_list(
		doctype,
		fields=["name", title_field] if title_field != "name" else ["name"],
		order_by="modified desc",
		limit=limit,
	)

	# Format results like search_link
	results = []
	for doc in docs:
		results.append(
			{
				"value": doc.name,
				"description": doc.get(title_field, "") if title_field != "name" else "",
			}
		)

	return results


@frappe.whitelist()
def get_print_formats(doctype):
	"""
	Get available print formats for a DocType.

	Args:
		doctype: DocType name

	Returns:
		list: Available print formats
	"""
	if not doctype or not frappe.db.exists("DocType", doctype):
		return []
	_require_desk_user()
	if not frappe.has_permission(doctype, "read"):
		return []

	formats = frappe.get_all(
		"Print Format",
		filters={"doc_type": doctype, "disabled": 0},
		fields=["name", "default_print_language"],
		order_by="name asc",
	)

	# Add "Standard" format
	result = [{"name": "Standard", "label": _("Standard")}]
	result.extend([{"name": f.name, "label": f.name} for f in formats])

	return result


@frappe.whitelist()
def generate_document_pdf(doctype, docname, print_format=None, language=None):
	"""
	Generate a PDF for a Frappe document.

	Args:
		doctype: DocType of the document
		docname: Name of the document
		print_format: Print format to use (default: Standard)
		language: The language it is printed in (the person's when absent), as the desk's « Print » offers

	Returns:
		dict: filename (the document's name), content (base64), content_type
	"""
	if not doctype or not docname:
		frappe.throw(_("DocType and document name are required"))

	_require_desk_user()
	# A document the person may not read is answered as one that does not exist (« access denied » told them it was).
	if not _readable_record(doctype, docname):
		frappe.throw(_("Document not found"), frappe.DoesNotExistError)

	try:
		# Generate PDF using Frappe's built-in method
		from frappe.translate import print_language
		from frappe.utils.pdf import get_pdf

		# Get HTML content, in the language asked for
		with print_language(language or None):
			html = frappe.get_print(
				doctype,
				docname,
				print_format=print_format or "Standard",
				as_pdf=False,
			)

		# Convert to PDF
		pdf_content = get_pdf(html)

		# The file is named after the document, as the person knows it (« FA-2026-0121.pdf »)
		filename = "".join(c if c.isalnum() or c in "-_." else "-" for c in str(docname)) + ".pdf"

		return {
			"filename": filename,
			"content": base64.b64encode(pdf_content).decode(),
			"content_type": "application/pdf",
			"size": len(pdf_content),
			"doctype": doctype,
			"docname": docname,
		}

	except Exception as e:
		frappe.log_error("PDF generation error", f"Failed to generate PDF for {doctype}/{docname}: {e!s}")
		frappe.throw(_("Failed to generate PDF: {0}").format(str(e)))


def create_communication_link(
	account_name,
	to,
	subject,
	html_content,
	reference_doctype=None,
	reference_name=None,
):
	"""
	Create a Communication record to link an email to a document's timeline.

	Args:
		account_name: Sender's email account
		to: Recipients
		subject: Email subject
		html_content: Email HTML content
		reference_doctype: DocType to link to
		reference_name: Document name to link to

	Returns:
		dict: Communication name if created
	"""
	if not reference_doctype or not reference_name:
		return {"created": False, "reason": "No reference document specified"}

	if not frappe.db.exists(reference_doctype, reference_name):
		return {"created": False, "reason": "Reference document not found"}

	# Called by send_email only (no longer whitelisted: anyone signed in could write an e-mail into any document's
	# timeline). The sent mail lands on a timeline the sender may read, no other.
	if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
		return {"created": False, "reason": "No permission on the reference document"}

	try:
		comm = frappe.new_doc("Communication")
		comm.communication_type = "Communication"
		comm.communication_medium = "Email"
		comm.sent_or_received = "Sent"
		comm.subject = subject
		comm.content = html_content
		comm.sender = account_name
		comm.recipients = to
		comm.reference_doctype = reference_doctype
		comm.reference_name = reference_name
		comm.status = "Linked"

		comm.insert(ignore_permissions=True)
		frappe.db.commit()

		return {"created": True, "communication": comm.name}

	except Exception as e:
		frappe.log_error("Communication link error", f"Failed to create communication link: {e!s}")
		return {"created": False, "reason": str(e)}
