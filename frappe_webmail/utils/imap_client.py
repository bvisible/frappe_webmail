# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
IMAP Client Wrapper

Provides a high-level interface for IMAP operations with connection pooling
and error handling.
"""

import socket
import time

import frappe
from frappe import _

try:
	from imapclient import IMAPClient as _IMAPClient
	from imapclient import SocketTimeout
	from imapclient.imap4 import IMAP4WithTimeout
	from imapclient.tls import IMAP4_TLS, wrap_socket
except ImportError:
	_IMAPClient = SocketTimeout = IMAP4WithTimeout = IMAP4_TLS = wrap_socket = None

# How long a mail server may take, for every IMAP connection the app opens (imap_timeout). Without a limit, a server
# whose name gives IPv6 addresses, on a host with no working IPv6 route, held the connection for about two minutes
# before the IPv4 one was tried, and gunicorn killed the worker at 120 s (maintenance#1786). Each address that does not
# accept a connection is given up after IMAP_CONNECT_TIMEOUT for the next one, and the TLS handshake and the server's
# greeting have as long for each of their reads; once signed in, each read may take up to IMAP_READ_TIMEOUT.
IMAP_CONNECT_TIMEOUT = 8
IMAP_READ_TIMEOUT = 60
# How long a pooled connection that sat idle has to answer the NOOP that checks it is still there (webmail_api,
# _imap_is_alive): one the server dropped without a word answers nothing, and is replaced.
IMAP_PROBE_TIMEOUT = 10
# What one web request may spend waiting on mail servers, all its IMAP connections and reads together, from its first
# IMAP operation: gunicorn kills a worker at 120 s, and a request may hold many reads (NeoMail sends up to 16 calls at
# once, each with its own). Past it, every IMAP operation of the request fails at once, as a connection that failed.
# A background job has no such budget: the limits of each operation only.
IMAP_REQUEST_BUDGET = 90
# The IMAP commands that change something on the server (UID ones included): one sent on a connection that then fails
# may have been done (WebmailConnectionLost in webmail_api).
WRITES = frozenset(
	(
		b"APPEND",
		b"STORE",
		b"COPY",
		b"MOVE",
		b"EXPUNGE",
		b"CREATE",
		b"DELETE",
		b"RENAME",
		b"SETACL",
		b"DELETEACL",
	)
)


class MailServerTooSlow(TimeoutError):
	"""The web request's time for its mail servers is spent (IMAP_REQUEST_BUDGET): nothing more is asked of them."""


def imap_timeout():
	"""The `timeout` every IMAPClient of the app is built with: IMAP_CONNECT_TIMEOUT, then IMAP_READ_TIMEOUT."""
	return SocketTimeout(connect=IMAP_CONNECT_TIMEOUT, read=IMAP_READ_TIMEOUT)


def _time_left():
	"""The seconds the current web request has left for its mail servers (IMAP_REQUEST_BUDGET from its first IMAP
	operation), None outside a web request. The deadline is kept on the request itself: one that never reached its
	end (a callback that failed before Frappe released its locals) can't pass its own on to the next."""
	request = getattr(frappe.local, "request", None)
	if request is None:
		return None
	deadline = getattr(request, "neoffice_imap_deadline", None)
	if deadline is None:
		deadline = time.monotonic() + IMAP_REQUEST_BUDGET
		request.neoffice_imap_deadline = deadline
	return deadline - time.monotonic()


def _within_budget(limit):
	"""`limit` (seconds), or what the web request has left when that is less; MailServerTooSlow when it has nothing
	left."""
	left = _time_left()
	if left is None:
		return limit
	if left <= 0:
		raise MailServerTooSlow(_("The mail server is not answering quickly enough."))
	return left if limit is None else min(limit, left)


def _connect(host, port, limit):
	"""socket.create_connection, whose `timeout` bounds each address alone: here each address of the name has `limit`
	and never more than what the web request has left, so that a name with many addresses that do not answer stays
	within the request's budget. The addresses in getaddrinfo's order; when none answers, the last one's error."""
	error = None
	for family, kind, protocol, _name, address in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
		timeout = _within_budget(limit)
		sock = None
		try:
			sock = socket.socket(family, kind, protocol)
			sock.settimeout(timeout)
			sock.connect(address)
			return sock
		except OSError as e:
			error = e
			if sock is not None:
				sock.close()
	if error is not None:
		raise error
	raise OSError("getaddrinfo returns an empty list")


if _IMAPClient is not None:

	class _Watched:
		"""An IMAP connection that remembers its socket failed (`failed`: a read or a write timed out, the server
		closed it or said BYE, the connection broke), so that nobody uses it again, whoever caught the error; that
		notes when a command that changes something was sent (`wrote`); and whose every read and write waits at most
		its limit (`limit`: the connect timeout until imapclient sets the read timeout, then the read timeout), and
		never past what the web request has left (_within_budget)."""

		failed = False
		wrote = False
		limit = None

		def _bound(self):
			limit = self.limit if self.limit is not None else self._timeout
			self.sock.settimeout(_within_budget(limit))

		def _watch(self, operation, *args):
			try:
				self._bound()
				return operation(*args)
			except OSError:
				self.failed = True
				raise

		def read(self, size):
			data = self._watch(super().read, size)
			if size and not data:
				self.failed = True
			return data

		def readline(self):
			line = self._watch(super().readline)
			# The server closed the connection (imaplib then says « socket error: EOF »)
			if not line:
				self.failed = True
			return line

		def send(self, data):
			try:
				self._bound()
			except OSError:
				self.failed = True
				raise
			if _writes(data):
				self.wrote = True
			return self._watch(super().send, data)

		def _get_response(self):
			try:
				return super()._get_response()
			except self.abort:
				self.failed = True
				raise

		def _command(self, *args):
			try:
				return super()._command(*args)
			except self.abort:
				self.failed = True
				raise

		def _command_complete(self, *args):
			try:
				return super()._command_complete(*args)
			except self.abort:
				self.failed = True
				raise

	def _writes(data):
		"""Whether the line sent is a command that changes something on the server (`tag WRITE …`, `tag UID WRITE …`).
		A literal sent after its command (an APPENDed message) is no command, and may read as one: then it says yes."""
		words = bytes(data[:64]).split(b" ", 3)
		if len(words) < 2:
			return False
		command = words[1].upper()
		if command == b"UID" and len(words) > 2:
			command = words[2].upper()
		return command in WRITES

	class _IMAP4TLSWithTimeout(_Watched, IMAP4_TLS):
		"""imapclient's TLS connection, opened within its connect timeout. imapclient 3.1 keeps the timeout it is given
		(`self._timeout`) but lets imaplib open the socket with none (`_create_socket(None)`): the connection, the TLS
		handshake and the server's greeting waited without end, the read timeout being set only after them. To remove
		when imapclient passes its timeout to the socket itself (test_imap_timeouts says when: its check of the stock
		client then fails)."""

		def _create_socket(self, timeout=None):
			limit = timeout if timeout is not None else self._timeout
			try:
				sock = _connect(self.host, self.port, limit)
				sock.settimeout(_within_budget(limit))
				return wrap_socket(sock, self.ssl_context, self.host)
			except OSError:
				self.failed = True
				raise

	class _IMAP4WithTimeout(_Watched, IMAP4WithTimeout):
		"""imapclient's plain connection, opened as the TLS one is, and watched the same way."""

		def _create_socket(self, timeout=None):
			try:
				return _connect(self.host, self.port, timeout if timeout is not None else self._timeout)
			except OSError:
				self.failed = True
				raise

	class BoundedIMAPClient(_IMAPClient):
		"""The IMAPClient the app builds (as `IMAPClient`): with TLS too, its connect timeout bounds the connection, the
		handshake and the greeting; it says when its socket failed (`socket_failed`) and when it sent a command that
		changes something since its session began (`wrote`, begin_session); and its reads keep to the web request's
		budget."""

		def _create_IMAP4(self):
			if self.stream:
				return super()._create_IMAP4()
			connect = getattr(self._timeout, "connect", None)
			if self.ssl:
				return _IMAP4TLSWithTimeout(self.host, self.port, self.ssl_context, connect)
			return _IMAP4WithTimeout(self.host, self.port, connect)

		def _set_read_timeout(self):
			super()._set_read_timeout()
			self._imap.limit = getattr(self._timeout, "read", None)

		def set_read_timeout(self, seconds):
			"""Each read from now on waits at most `seconds` (and never past the web request's budget)."""
			self._imap.limit = seconds
			self.socket().settimeout(seconds)

		def begin_session(self):
			"""A session of the pool begins with this connection: nothing written yet."""
			self._imap.wrote = False

		@property
		def socket_failed(self):
			"""Whether a read or a write of this connection failed: it is not to be used again."""
			return bool(getattr(self._imap, "failed", False))

		@property
		def wrote(self):
			"""Whether a command that changes something was sent since the session began."""
			return bool(getattr(self._imap, "wrote", False))

	IMAPClient = BoundedIMAPClient
else:
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
				timeout=imap_timeout(),
			)
			self.client.login(self.account.email, self.account.get_password("imap_password"))
			self._connected = True
		except Exception as e:
			frappe.log_error("Webmail: IMAP connection failed", frappe.get_traceback())
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
