# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
IMAP Client Wrapper

Provides a high-level interface for IMAP operations with connection pooling
and error handling.
"""

import frappe
from frappe import _

try:
	from imapclient import IMAPClient
except ImportError:
	IMAPClient = None


class WebmailIMAPClient:
	"""
	Wrapper class for IMAP operations with automatic connection management.

	Usage:
		with WebmailIMAPClient(account) as client:
			folders = client.list_folders()
	"""

	def __init__(self, account):
		"""
		Initialize IMAP client with account settings.

		Args:
			account: Webmail Account document or dict with connection settings
		"""
		if not IMAPClient:
			frappe.throw(_("imapclient package is not installed. Run: pip install imapclient"))

		self.account = account
		self.client = None
		self._connected = False

	def __enter__(self):
		"""Context manager entry - establish connection"""
		self.connect()
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		"""Context manager exit - close connection"""
		self.disconnect()
		return False

	def connect(self):
		"""Establish IMAP connection"""
		if self._connected:
			return

		try:
			self.client = IMAPClient(
				host=self.account.imap_host,
				port=self.account.imap_port,
				ssl=self.account.imap_ssl,
			)
			self.client.login(self.account.email, self.account.get_password("imap_password"))
			self._connected = True
		except Exception as e:
			frappe.log_error(f"IMAP connection error: {e!s}", "Frappe Webmail")
			frappe.throw(_("Failed to connect to IMAP server: {0}").format(e))

	def disconnect(self):
		"""Close IMAP connection"""
		if self.client and self._connected:
			try:
				self.client.logout()
			except Exception:
				pass
			finally:
				self._connected = False
				self.client = None

	def list_folders(self):
		"""
		List all IMAP folders.

		Returns:
			list: List of folder dictionaries with name, delimiter, flags, and selectable
		"""
		self._ensure_connected()
		folders = self.client.list_folders()

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

	def select_folder(self, folder="INBOX", readonly=False):
		"""
		Select a folder for operations.

		Args:
			folder: Folder name to select
			readonly: Whether to open in readonly mode

		Returns:
			dict: Folder status information
		"""
		self._ensure_connected()
		return self.client.select_folder(folder, readonly=readonly)

	def search(self, criteria=None):
		"""
		Search for messages matching criteria.

		Args:
			criteria: IMAP search criteria (default: NOT DELETED)

		Returns:
			list: List of message UIDs
		"""
		self._ensure_connected()
		if criteria is None:
			criteria = ["NOT", "DELETED"]
		return self.client.search(criteria)

	def fetch(self, uids, data):
		"""
		Fetch message data.

		Args:
			uids: List of message UIDs to fetch
			data: List of data items to fetch (e.g., ['ENVELOPE', 'FLAGS'])

		Returns:
			dict: Message data keyed by UID
		"""
		self._ensure_connected()
		return self.client.fetch(uids, data)

	def add_flags(self, uids, flags):
		"""
		Add flags to messages.

		Args:
			uids: List of message UIDs
			flags: List of flags to add (e.g., ['\\Seen', '\\Flagged'])
		"""
		self._ensure_connected()
		self.client.add_flags(uids, flags)

	def remove_flags(self, uids, flags):
		"""
		Remove flags from messages.

		Args:
			uids: List of message UIDs
			flags: List of flags to remove
		"""
		self._ensure_connected()
		self.client.remove_flags(uids, flags)

	def copy(self, uids, destination):
		"""
		Copy messages to another folder.

		Args:
			uids: List of message UIDs
			destination: Destination folder name
		"""
		self._ensure_connected()
		self.client.copy(uids, destination)

	def expunge(self):
		"""Permanently remove messages marked for deletion"""
		self._ensure_connected()
		self.client.expunge()

	def _ensure_connected(self):
		"""Ensure client is connected, raise error if not"""
		if not self._connected or not self.client:
			frappe.throw(_("IMAP client is not connected"))


class IMAPConnectionPool:
	"""
	Connection pool for IMAP clients (future implementation).

	This class can be used to manage a pool of IMAP connections
	for better performance with concurrent requests.
	"""

	def __init__(self, max_connections=5):
		self.max_connections = max_connections
		self._pool = {}

	def get_connection(self, account_name):
		"""Get or create a connection for an account"""
		# TODO: Implement connection pooling
		pass

	def release_connection(self, account_name):
		"""Release a connection back to the pool"""
		# TODO: Implement connection pooling
		pass

	def close_all(self):
		"""Close all connections in the pool"""
		for client in self._pool.values():
			try:
				client.disconnect()
			except Exception:
				pass
		self._pool.clear()
