# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

# OAuth2 provider settings
OAUTH_PROVIDERS = {
	"Gmail": {
		"imap_host": "imap.gmail.com",
		"imap_port": 993,
		"imap_ssl": 1,
		"smtp_host": "smtp.gmail.com",
		"smtp_port": 587,
		"smtp_ssl": 0,
		"smtp_starttls": 1,
		"auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
		"token_url": "https://oauth2.googleapis.com/token",
		"scope": "https://mail.google.com/",
	},
	"Outlook": {
		"imap_host": "outlook.office365.com",
		"imap_port": 993,
		"imap_ssl": 1,
		"smtp_host": "smtp.office365.com",
		"smtp_port": 587,
		"smtp_ssl": 0,
		"smtp_starttls": 1,
		"auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
		"token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
		"scope": "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access",
	},
}


class WebmailAccount(Document):
	def validate(self):
		"""Validate the account settings"""
		self.validate_email()
		self.validate_ports()
		self.validate_auth()
		self.apply_oauth_provider_settings()

	def validate_email(self):
		"""Validate email format"""
		if self.email and not frappe.utils.validate_email_address(self.email):
			frappe.throw(_("Invalid email address: {0}").format(self.email))

	def validate_ports(self):
		"""Validate port numbers"""
		if self.imap_port and (self.imap_port < 1 or self.imap_port > 65535):
			frappe.throw(_("Invalid IMAP port number"))
		if self.smtp_port and (self.smtp_port < 1 or self.smtp_port > 65535):
			frappe.throw(_("Invalid SMTP port number"))

	def validate_auth(self):
		"""Validate authentication settings"""
		if self.auth_type == "Password":
			if not self.imap_password:
				frappe.throw(_("IMAP Password is required for Password authentication"))
			if not self.smtp_password:
				frappe.throw(_("SMTP Password is required for Password authentication"))
		elif self.auth_type == "OAuth2":
			if not self.oauth_provider:
				frappe.throw(_("OAuth Provider is required for OAuth2 authentication"))

	def apply_oauth_provider_settings(self):
		"""Auto-fill IMAP/SMTP settings based on OAuth provider"""
		if self.auth_type == "OAuth2" and self.oauth_provider:
			provider = OAUTH_PROVIDERS.get(self.oauth_provider)
			if provider:
				self.imap_host = provider["imap_host"]
				self.imap_port = provider["imap_port"]
				self.imap_ssl = provider["imap_ssl"]
				self.smtp_host = provider["smtp_host"]
				self.smtp_port = provider["smtp_port"]
				self.smtp_ssl = provider["smtp_ssl"]
				self.smtp_starttls = provider["smtp_starttls"]

	def before_insert(self):
		"""Set default values before insert"""
		if not self.user:
			self.user = frappe.session.user

	def has_permission(self, permtype="read", doc=None):
		"""Check if user has permission to access this account"""
		if frappe.session.user == "Administrator":
			return True
		if self.user == frappe.session.user:
			return True
		return False

	def is_oauth_token_valid(self):
		"""Check if OAuth token is still valid"""
		if not self.oauth_access_token or not self.oauth_token_expiry:
			return False

		expiry = get_datetime(self.oauth_token_expiry)
		# Consider token invalid if it expires in less than 5 minutes
		buffer_time = frappe.utils.add_to_date(now_datetime(), minutes=5)

		return expiry > buffer_time

	def get_oauth_access_token(self):
		"""Get valid OAuth access token, refreshing if necessary"""
		if self.auth_type != "OAuth2":
			return None

		if self.is_oauth_token_valid():
			return self.get_password("oauth_access_token")

		# Token expired or about to expire, refresh it
		if self.oauth_refresh_token:
			return self.refresh_oauth_token()

		frappe.throw(_("OAuth token expired. Please reconnect your account."))

	def refresh_oauth_token(self):
		"""Refresh the OAuth access token using refresh token"""
		import requests

		provider = OAUTH_PROVIDERS.get(self.oauth_provider)
		if not provider:
			frappe.throw(_("Unknown OAuth provider"))

		# Get OAuth credentials from site config
		oauth_config = get_oauth_config(self.oauth_provider)
		if not oauth_config:
			frappe.throw(_("OAuth credentials not configured for {0}").format(self.oauth_provider))

		try:
			response = requests.post(
				provider["token_url"],
				data={
					"client_id": oauth_config["client_id"],
					"client_secret": oauth_config["client_secret"],
					"refresh_token": self.get_password("oauth_refresh_token"),
					"grant_type": "refresh_token",
				},
				timeout=30,
			)

			if response.status_code != 200:
				frappe.log_error(f"OAuth refresh failed: {response.text}", "Webmail OAuth Error")
				frappe.throw(_("Failed to refresh OAuth token"))

			data = response.json()

			# Update tokens
			self.oauth_access_token = data["access_token"]
			if "refresh_token" in data:
				self.oauth_refresh_token = data["refresh_token"]

			# Calculate expiry
			expires_in = data.get("expires_in", 3600)
			self.oauth_token_expiry = frappe.utils.add_to_date(now_datetime(), seconds=expires_in)

			self.save(ignore_permissions=True)
			frappe.db.commit()

			return data["access_token"]

		except requests.RequestException as e:
			frappe.log_error(f"OAuth refresh error: {e!s}", "Webmail OAuth Error")
			frappe.throw(_("Failed to refresh OAuth token: {0}").format(e))


def get_oauth_config(provider):
	"""Get OAuth credentials from site config"""
	config_key = f"webmail_oauth_{provider.lower()}"
	config = frappe.conf.get(config_key, {})

	if not config.get("client_id") or not config.get("client_secret"):
		return None

	return config


def get_permission_query_conditions(user):
	"""Only show user's own accounts"""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return ""

	return f"(`tabWebmail Account`.user = {frappe.db.escape(user)})"


def has_permission(doc, ptype="read", user=None):
	"""Check if user can access this account"""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return True

	return doc.user == user
