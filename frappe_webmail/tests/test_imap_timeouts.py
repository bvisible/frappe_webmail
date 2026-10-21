# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Every IMAP connection the app opens is bounded (maintenance#1786): a mail server whose IPv6 addresses could not be
reached held a connection for about two minutes, and gunicorn killed the worker at 120 s. Each IMAPClient is the
app's bounded one (utils/imap_client.py), built with imap_timeout: with TLS too, its connect timeout bounds the
connection, the handshake and the greeting (imapclient 3.1 alone does not); a connection that failed is never used
again; a failure reaches NeoMail as WebmailConnectionError (a 503, which it tries again); and a web request keeps to
IMAP_REQUEST_BUDGET. The servers here are real sockets on this machine, which say nothing, or answer only some
commands; each case prints how long it took (« imap-timeouts: »).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_imap_timeouts
"""

import ast
import datetime
import ipaddress
import os
import socket
import ssl
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from imapclient import IMAPClient as StockIMAPClient
from imapclient import SocketTimeout

from frappe_webmail import webmail_api
from frappe_webmail.utils import imap_client

BOUNDED = SocketTimeout(connect=imap_client.IMAP_CONNECT_TIMEOUT, read=imap_client.IMAP_READ_TIMEOUT)
# gunicorn's -t on the fleet's benches (config/supervisor.conf)
GUNICORN_TIMEOUT = 120
# The limits the cases with real servers use, short so that the suite stays quick
SHORT = 1
# The most a bounded case may take beyond its limit
SLACK = 1.5


class _Server:
	"""A server on this machine. Silent (no `greeting`): it accepts a connection and says nothing, no IMAP greeting
	and no TLS handshake. Else it greets (over TLS with `tls`, a server context), answers CAPABILITY and the commands
	in `answers`, and at the first other command, as `then` says: says nothing more ("silent"), closes the connection
	("close"), or says BYE and closes it ("bye")."""

	def __init__(self, greeting=None, answers=(), then="silent", tls=None):
		self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.listener.bind(("127.0.0.1", 0))
		self.listener.listen(8)
		self.port = self.listener.getsockname()[1]
		self.greeting = greeting
		self.answers = {command.upper().encode() for command in answers}
		self.then = then
		self.tls = tls
		self.connections = []
		self.accepted = 0
		threading.Thread(target=self._serve, daemon=True).start()

	def _serve(self):
		while True:
			try:
				connection, _address = self.listener.accept()
			except OSError:
				return
			self.accepted += 1
			self.connections.append(connection)
			threading.Thread(target=self._talk, args=(connection,), daemon=True).start()

	def _talk(self, connection):
		if self.greeting is None:
			return
		try:
			if self.tls is not None:
				connection = self.tls.wrap_socket(connection, server_side=True)
				self.connections.append(connection)
			connection.sendall(self.greeting)
			pending = b""
			while True:
				data = connection.recv(4096)
				if not data:
					return
				pending += data
				while b"\r\n" in pending:
					line, pending = pending.split(b"\r\n", 1)
					tag, _sep, rest = line.partition(b" ")
					command = rest.split(b" ", 1)[0].upper()
					if command == b"CAPABILITY":
						connection.sendall(b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n")
					elif command == b"LOGOUT" and command in self.answers:
						connection.sendall(b"* BYE logging out\r\n" + tag + b" OK done\r\n")
					elif command in self.answers:
						connection.sendall(tag + b" OK done\r\n")
					else:
						if self.then == "bye":
							connection.sendall(b"* BYE going away\r\n")
						if self.then in ("bye", "close"):
							connection.shutdown(socket.SHUT_RDWR)
							connection.close()
						return
		except OSError:
			return

	def close(self):
		for sock in (self.listener, *self.connections):
			try:
				sock.shutdown(socket.SHUT_RDWR)
			except OSError:
				pass
			try:
				sock.close()
			except OSError:
				pass


def _in_thread(open_connection, wait):
	"""Run `open_connection` in a thread for at most `wait` seconds: {finished, seconds, error}. A connection that
	never ends keeps its thread (a daemon) until its server closes."""
	outcome = {"finished": False, "seconds": None, "error": None}

	def run():
		start = time.monotonic()
		try:
			open_connection()
		except Exception as e:
			outcome["error"] = e
		outcome["seconds"] = time.monotonic() - start
		outcome["finished"] = True

	thread = threading.Thread(target=run, daemon=True)
	thread.start()
	thread.join(wait)
	return outcome


def _certificate(folder):
	"""A certificate for 127.0.0.1 and its key, made for the test, as PEM files in `folder`: (certificate, key)."""
	from cryptography import x509
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import ec
	from cryptography.x509.oid import NameOID

	key = ec.generate_private_key(ec.SECP256R1())
	name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
	now = datetime.datetime.now(datetime.timezone.utc)
	certificate = (
		x509.CertificateBuilder()
		.subject_name(name)
		.issuer_name(name)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(now - datetime.timedelta(minutes=5))
		.not_valid_after(now + datetime.timedelta(hours=1))
		.add_extension(
			x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False
		)
		.add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
		.sign(key, hashes.SHA256())
	)
	paths = (os.path.join(folder, "certificate.pem"), os.path.join(folder, "key.pem"))
	with open(paths[0], "wb") as handle:
		handle.write(certificate.public_bytes(serialization.Encoding.PEM))
	with open(paths[1], "wb") as handle:
		handle.write(
			key.private_bytes(
				serialization.Encoding.PEM,
				serialization.PrivateFormat.PKCS8,
				serialization.NoEncryption(),
			)
		)
	return paths


class _Unanswering:
	"""A socket whose connect waits its whole timeout, as an address that does not answer; `tried` keeps each address
	and the timeout it was given."""

	tried: ClassVar[list] = []

	def __init__(self, *args):
		self.timeout = None

	def settimeout(self, timeout):
		self.timeout = timeout

	def connect(self, address):
		_Unanswering.tried.append((address[0], self.timeout))
		time.sleep(self.timeout)
		raise TimeoutError(f"timed out: {address[0]}")

	def close(self):
		pass


# A name with six addresses (documentation addresses, RFC 5737)
SIX_ADDRESSES = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (f"192.0.2.{n}", 993)) for n in range(1, 7)]


def _measured(label, seconds):
	print(f"imap-timeouts: {label}: {seconds:.2f} s")


def _account(port=993, ssl=1):
	return frappe._dict(
		name="webmail_timeouts_box@example.com",
		email="webmail_timeouts_box@example.com",
		auth_type="Password",
		imap_host="127.0.0.1",
		imap_port=port,
		imap_ssl=ssl,
		smtp_host="smtp.test.local",
		smtp_port=465,
		smtp_ssl=1,
		smtp_starttls=0,
	)


def _sign_in(client, account):
	client.login("user", "secret")


class TestImapTimeouts(FrappeTestCase):
	def setUp(self):
		self.servers = []

	def tearDown(self):
		entry = webmail_api._IMAP_POOL.pop(_account().name, None)
		if entry is not None:
			webmail_api._imap_discard(entry)
		for server in self.servers:
			server.close()

	def _server(self, **kwargs):
		server = _Server(**kwargs)
		self.servers.append(server)
		return server

	# The limits ------------------------------------------------------------------------------------------------

	def test_the_limits_are_short_to_connect_and_under_gunicorn_s_to_read(self):
		self.assertEqual(imap_client.imap_timeout(), BOUNDED)
		self.assertLessEqual(imap_client.IMAP_CONNECT_TIMEOUT, 10)
		# A connection given up on two unreachable addresses, then one read, still ends before gunicorn's limit
		self.assertLess(
			2 * imap_client.IMAP_CONNECT_TIMEOUT + imap_client.IMAP_READ_TIMEOUT, GUNICORN_TIMEOUT
		)
		self.assertLess(imap_client.IMAP_PROBE_TIMEOUT, imap_client.IMAP_READ_TIMEOUT)
		self.assertLess(imap_client.IMAP_REQUEST_BUDGET + imap_client.IMAP_CONNECT_TIMEOUT, GUNICORN_TIMEOUT)

	def test_every_imapclient_of_the_app_is_the_bounded_one_built_with_the_limits(self):
		"""Read from the app's own source, so that an IMAPClient added later without them fails here."""
		root = frappe.get_app_path("frappe_webmail")
		built, unbounded = [], []
		for folder, dirs, files in os.walk(root):
			dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "__pycache__")]
			for name in files:
				if not name.endswith(".py"):
					continue
				path = os.path.join(folder, name)
				with open(path, encoding="utf-8") as handle:
					tree = ast.parse(handle.read(), path)
				for node in ast.walk(tree):
					if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "IMAPClient":
						where = f"{os.path.relpath(path, root)}:{node.lineno}"
						built.append(where)
						timeout = next((k.value for k in node.keywords if k.arg == "timeout"), None)
						if not (
							isinstance(timeout, ast.Call)
							and getattr(timeout.func, "id", None) == "imap_timeout"
						):
							unbounded.append(where)
		self.assertGreaterEqual(len(built), 4, built)
		self.assertEqual(unbounded, [], "built without imap_timeout()")
		# The name they call is the bounded class, in both modules that build one
		self.assertIs(webmail_api.IMAPClient, imap_client.BoundedIMAPClient)
		self.assertIs(imap_client.IMAPClient, imap_client.BoundedIMAPClient)

	def test_each_construction_passes_the_limits(self):
		with patch.object(webmail_api, "IMAPClient") as imap, patch.object(webmail_api, "imap_login"):
			webmail_api._imap_connect(_account())
		self.assertEqual(imap.call_args.kwargs["timeout"], BOUNDED, "the pool's")
		with patch.object(webmail_api, "IMAPClient") as imap, patch.object(webmail_api, "imap_login"):
			with webmail_api.imap_session(_account()):
				pass
		self.assertEqual(imap.call_args.kwargs["timeout"], BOUNDED, "the session's under test")
		with (
			patch.object(webmail_api, "IMAPClient") as imap,
			patch.object(webmail_api, "_imap_login_raw"),
			patch.object(webmail_api, "_smtp_login_raw"),
			patch.object(webmail_api.smtplib, "SMTP_SSL"),
		):
			result = webmail_api._test_connection_internal(_account())
		self.assertTrue(result["success"], result)
		self.assertEqual(imap.call_args.kwargs["timeout"], BOUNDED, "the connection test's")
		account = MagicMock(imap_host="imap.test.local", imap_port=993, imap_ssl=True, email="a@example.com")
		with patch.object(imap_client, "IMAPClient") as imap:
			imap_client.WebmailIMAPClient(account).connect()
		self.assertEqual(imap.call_args.kwargs["timeout"], BOUNDED, "the utility client's")

	# Real servers that say nothing ----------------------------------------------------------------------------

	def test_a_server_that_says_nothing_is_given_up_within_the_connect_timeout_with_tls_and_without(self):
		for tls in (True, False):
			server = self._server()
			with patch.object(imap_client, "IMAP_CONNECT_TIMEOUT", SHORT):
				outcome = _in_thread(
					lambda server=server, tls=tls: imap_client.IMAPClient(
						host="127.0.0.1", port=server.port, ssl=tls, timeout=imap_client.imap_timeout()
					),
					wait=SHORT + 10,
				)
			label = "no TLS handshake" if tls else "no greeting"
			self.assertTrue(outcome["finished"], f"{label}: still waiting after {SHORT + 10} s")
			_measured(f"bounded client, {label}, connect limit {SHORT} s", outcome["seconds"])
			self.assertIsInstance(outcome["error"], OSError, label)
			self.assertLess(outcome["seconds"], SHORT + SLACK, label)

	def test_imapclient_alone_still_waits_without_end_with_tls(self):
		"""Why the app has its own TLS connection class (_IMAP4TLSWithTimeout): imapclient 3.1 opens the socket without
		the connect timeout it was given. When this test fails, imapclient bounds it itself: remove that class."""
		server = self._server()
		outcome = _in_thread(
			lambda: StockIMAPClient(
				host="127.0.0.1", port=server.port, ssl=True, timeout=SocketTimeout(connect=SHORT, read=SHORT)
			),
			wait=SHORT + 3,
		)
		if outcome["finished"]:
			# A sign, not a failure: where the stock client ends by itself (a newer imapclient bounds TLS, or the runner's
			# network ends the silent connection), the app's class is harmless; this is the moment to check whether
			# _IMAP4TLSWithTimeout can be removed. The app's own bound is proved by the tests around this one.
			self.skipTest(f"the stock imapclient ended by itself here ({outcome.get('error')!r}): check its TLS bound")
		_measured(f"imapclient alone, no TLS handshake, connect limit {SHORT} s: still waiting at", SHORT + 3)

	def test_a_server_out_of_reach_is_a_connection_error_for_the_webmail(self):
		"""Not a raw socket error, which NeoMail's facade answered with a 500 and an Error Log line each time."""
		server = self._server()
		start = time.monotonic()
		with (
			patch.object(imap_client, "IMAP_CONNECT_TIMEOUT", SHORT),
			self.assertRaises(webmail_api.WebmailConnectionError),
		):
			webmail_api._imap_connect(_account(port=server.port, ssl=1))
		_measured("the pool's connection to a silent TLS server", time.monotonic() - start)
		self.assertLess(time.monotonic() - start, SHORT + SLACK)
		refused = socket.socket()
		refused.bind(("127.0.0.1", 0))
		port = refused.getsockname()[1]
		refused.close()
		with self.assertRaises(webmail_api.WebmailConnectionError, msg="refused"):
			webmail_api._imap_connect(_account(port=port, ssl=0))

	# A read that timed out -------------------------------------------------------------------------------------

	def test_a_read_that_timed_out_is_a_connection_error_and_its_connection_is_dropped(self):
		server = self._server(greeting=b"* OK ready\r\n", answers=("LOGIN", "LOGOUT"))
		start = time.monotonic()
		with (
			patch.dict(frappe.local.flags, {"in_test": False}),
			patch.object(imap_client, "IMAP_READ_TIMEOUT", SHORT),
			patch.object(webmail_api, "imap_login", side_effect=_sign_in),
			self.assertRaises(webmail_api.WebmailConnectionError),
		):
			with webmail_api.imap_session(_account(port=server.port, ssl=0)) as client:
				client.select_folder("INBOX")
		_measured(
			f"a read that timed out (read limit {SHORT} s), its connection dropped", time.monotonic() - start
		)
		self.assertLess(time.monotonic() - start, SHORT + SLACK, "dropping it waits for nothing more")
		self.assertNotIn(_account().name, webmail_api._IMAP_POOL)
		self.assertTrue(client.socket_failed)

	def test_a_connection_that_failed_is_never_used_again_even_when_the_caller_went_on(self):
		"""As _move and save_draft_imap do: they catch the error and carry on, and the connection went back to the pool,
		where the next request within 20 s skipped the NOOP and failed (« cannot read from timed out object »)."""
		server = self._server(greeting=b"* OK ready\r\n", answers=("LOGIN", "LOGOUT"))
		account = _account(port=server.port, ssl=0)
		with (
			patch.dict(frappe.local.flags, {"in_test": False}),
			patch.object(imap_client, "IMAP_READ_TIMEOUT", SHORT),
			patch.object(webmail_api, "imap_login", side_effect=_sign_in),
		):
			with webmail_api.imap_session(account) as client:
				try:
					client.select_folder("INBOX")
				except Exception:
					pass
			self.assertNotIn(account.name, webmail_api._IMAP_POOL)
			before = server.accepted
			with webmail_api.imap_session(account) as fresh:
				self.assertIsNot(fresh, client)
			self.assertEqual(server.accepted, before + 1, "a new connection")

	def test_an_idle_pooled_connection_is_checked_briefly(self):
		client = MagicMock()
		entry = webmail_api._PooledIMAP(client)
		entry.last_used = time.monotonic() - (webmail_api._IMAP_IDLE_RECHECK + 5)
		self.assertTrue(webmail_api._imap_is_alive(entry))
		self.assertEqual(
			[c.args[0] for c in client.set_read_timeout.call_args_list],
			[imap_client.IMAP_PROBE_TIMEOUT, imap_client.IMAP_READ_TIMEOUT],
			"a short check, then the read's limit again",
		)
		silent = MagicMock()
		silent.noop.side_effect = TimeoutError("timed out")
		entry = webmail_api._PooledIMAP(silent)
		entry.last_used = time.monotonic() - (webmail_api._IMAP_IDLE_RECHECK + 5)
		self.assertFalse(webmail_api._imap_is_alive(entry), "a connection that does not answer is replaced")
		failed = MagicMock(socket_failed=True)
		entry = webmail_api._PooledIMAP(failed)
		self.assertFalse(webmail_api._imap_is_alive(entry), "nor is one that failed, however recent")
		failed.noop.assert_not_called()

	# A web request's budget ------------------------------------------------------------------------------------

	def test_a_web_request_keeps_to_its_budget_whatever_its_reads(self):
		"""Many calls in one request (NeoMail sends up to 16), each with its own reads: past IMAP_REQUEST_BUDGET from
		the first, every IMAP operation of the request fails at once, without connecting again."""
		server = self._server(greeting=b"* OK ready\r\n", answers=("LOGIN", "LOGOUT"))
		account = _account(port=server.port, ssl=0)
		budget = 1.5
		with (
			patch.object(frappe.local, "request", SimpleNamespace(), create=True),
			patch.dict(frappe.local.flags, {"in_test": False}),
			patch.object(imap_client, "IMAP_REQUEST_BUDGET", budget),
			patch.object(webmail_api, "imap_login", side_effect=_sign_in),
		):
			start = time.monotonic()
			with self.assertRaises(webmail_api.WebmailConnectionError):
				with webmail_api.imap_session(account) as client:
					# A read whose own limit is 60 s, cut at what the request has left
					client.select_folder("INBOX")
			spent = time.monotonic() - start
			_measured(f"a read with 60 s of its own, in a request with {budget} s", spent)
			self.assertLess(spent, budget + SLACK)
			before = server.accepted
			start = time.monotonic()
			with self.assertRaises(webmail_api.WebmailConnectionError):
				with webmail_api.imap_session(account):
					pass
			_measured("the request's next session, its budget spent", time.monotonic() - start)
			self.assertLess(time.monotonic() - start, 0.5)
			self.assertEqual(server.accepted, before, "no new connection")

	def test_a_background_job_has_the_limits_of_each_operation_only(self):
		self.assertIsNone(getattr(frappe.local, "request", None))
		self.assertIsNone(imap_client._time_left())
		self.assertEqual(imap_client._within_budget(7), 7)

	def test_the_budget_belongs_to_its_request(self):
		"""Kept on the request itself: a request that never reached Frappe's release of its locals (a callback that
		failed first) can't pass a spent budget on to the next one, which would fail every IMAP operation of the
		worker."""
		first, second = SimpleNamespace(), SimpleNamespace()
		with (
			patch.object(frappe.local, "request", first, create=True),
			patch.object(imap_client, "IMAP_REQUEST_BUDGET", 0.2),
		):
			imap_client._time_left()
			time.sleep(0.3)
			with self.assertRaises(imap_client.MailServerTooSlow) as caught:
				imap_client._within_budget(8)
			self.assertEqual(
				str(caught.exception), frappe._("The mail server is not answering quickly enough.")
			)
			# The next request, frappe.local left as it was
			frappe.local.request = second
			self.assertGreater(imap_client._within_budget(8), 0.1)

	# The addresses of a name ------------------------------------------------------------------------------------

	def test_each_address_has_the_connect_timeout_in_turn_outside_a_request(self):
		_Unanswering.tried = []
		start = time.monotonic()
		with (
			patch.object(imap_client.socket, "getaddrinfo", return_value=SIX_ADDRESSES),
			patch.object(imap_client.socket, "socket", _Unanswering),
			self.assertRaises(TimeoutError) as caught,
		):
			imap_client._connect("mail.example.org", 993, 0.1)
		_measured("six addresses that do not answer, 0.1 s each, no request", time.monotonic() - start)
		self.assertEqual(_Unanswering.tried, [(f"192.0.2.{n}", 0.1) for n in range(1, 7)], "in their order")
		self.assertEqual(str(caught.exception), "timed out: 192.0.2.6", "the last address's error")

	def test_a_name_with_many_addresses_stays_within_the_request_s_budget(self):
		"""socket.create_connection gives each address the whole timeout: six that do not answer took six times
		min(8 s, what was left), past gunicorn's 120 s when opened late in a request."""
		_Unanswering.tried = []
		with (
			patch.object(frappe.local, "request", SimpleNamespace(), create=True),
			patch.object(imap_client, "IMAP_REQUEST_BUDGET", 0.4),
			patch.object(imap_client.socket, "getaddrinfo", return_value=SIX_ADDRESSES),
			patch.object(imap_client.socket, "socket", _Unanswering),
		):
			start = time.monotonic()
			with self.assertRaises(TimeoutError):
				imap_client._connect("mail.example.org", 993, 8)
			spent = time.monotonic() - start
		_measured("six addresses that do not answer, 8 s each, in a request with 0.4 s", spent)
		self.assertLess(spent, 0.4 + 0.3)
		self.assertLess(len(_Unanswering.tried), 6)

	# How a connection ends --------------------------------------------------------------------------------------

	def test_a_server_that_closes_or_says_bye_leaves_a_connection_never_used_again(self):
		"""imaplib says « socket error: EOF » or BYE outside the socket's reads: the connection is marked all the
		same, and a caller that went on (as _delete_draft in save_draft_imap does) leaves it out of the pool."""
		for then in ("close", "bye"):
			server = self._server(greeting=b"* OK ready\r\n", answers=("LOGIN", "LOGOUT"), then=then)
			account = _account(port=server.port, ssl=0)
			with (
				patch.dict(frappe.local.flags, {"in_test": False}),
				patch.object(webmail_api, "imap_login", side_effect=_sign_in),
			):
				with webmail_api.imap_session(account) as client:
					try:
						client.select_folder("INBOX")
					except Exception:
						pass
			self.assertTrue(client.socket_failed, then)
			self.assertNotIn(account.name, webmail_api._IMAP_POOL, then)

	def test_a_connection_lost_after_a_change_was_sent_says_the_change_may_have_been_made(self):
		"""An APPEND whose answer never came may have filed the message: NeoMail's facade must not say « nothing
		done, ask again » (it would be filed twice). A read cut off the same way changed nothing."""
		server = self._server(greeting=b"* OK ready\r\n", answers=("LOGIN", "LOGOUT"))
		account = _account(port=server.port, ssl=0)
		with (
			patch.dict(frappe.local.flags, {"in_test": False}),
			patch.object(imap_client, "IMAP_READ_TIMEOUT", SHORT),
			patch.object(webmail_api, "imap_login", side_effect=_sign_in),
		):
			with self.assertRaises(webmail_api.WebmailConnectionLost):
				with webmail_api.imap_session(account) as client:
					client.append("INBOX", b"Subject: kept\r\n\r\nKept.\r\n")
			with self.assertRaises(webmail_api.WebmailConnectionError) as caught:
				with webmail_api.imap_session(account) as client:
					client.select_folder("INBOX")
			self.assertNotIsInstance(caught.exception, webmail_api.WebmailConnectionLost)

	def test_the_commands_that_change_something_are_told_from_the_others(self):
		writes = imap_client._writes
		for line in (
			b"A1 APPEND INBOX {5}\r\n",
			b"A2 UID STORE 7 +FLAGS (\\Seen)\r\n",
			b"A3 uid move 7 Archive\r\n",
		):
			self.assertTrue(writes(line), line)
		for line in (b"A4 SELECT INBOX\r\n", b"A5 UID FETCH 7 (FLAGS)\r\n", b"A6 NOOP\r\n", b"x"):
			self.assertFalse(writes(line), line)

	def test_a_tls_connection_that_answers_signs_in_and_goes_on_and_one_not_trusted_is_refused(self):
		with tempfile.TemporaryDirectory() as folder:
			certificate, key = _certificate(folder)
			served = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
			served.load_cert_chain(certificate, key)
			trusted = ssl.create_default_context(cafile=certificate)
			server = self._server(greeting=b"* OK ready\r\n", answers=("LOGIN", "NOOP", "LOGOUT"), tls=served)
			start = time.monotonic()
			client = imap_client.IMAPClient(
				host="127.0.0.1",
				port=server.port,
				ssl=True,
				ssl_context=trusted,
				timeout=imap_client.imap_timeout(),
			)
			client.login("user", "secret")
			client.noop()
			_measured("a TLS connection, signed in, then NOOP", time.monotonic() - start)
			self.assertFalse(client.socket_failed)
			self.assertEqual(client.socket().gettimeout(), imap_client.IMAP_READ_TIMEOUT)
			client.logout()
			# The certificate is still checked: a context that does not trust it refuses the connection
			with self.assertRaises(ssl.SSLCertVerificationError):
				imap_client.IMAPClient(
					host="127.0.0.1",
					port=server.port,
					ssl=True,
					ssl_context=ssl.create_default_context(),
					timeout=imap_client.imap_timeout(),
				)
