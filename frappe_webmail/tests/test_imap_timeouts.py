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
import os
import socket
import threading
import time
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
	and no TLS handshake. Else it greets, answers CAPABILITY and the commands in `answers`, and from the first other
	command says nothing more."""

	def __init__(self, greeting=None, answers=()):
		self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.listener.bind(("127.0.0.1", 0))
		self.listener.listen(8)
		self.port = self.listener.getsockname()[1]
		self.greeting = greeting
		self.answers = {command.upper().encode() for command in answers}
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
					elif command in self.answers:
						connection.sendall(tag + b" OK done\r\n")
					else:
						return
		except OSError:
			return

	def close(self):
		self.listener.close()
		for connection in self.connections:
			try:
				connection.close()
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
		_measured(f"imapclient alone, no TLS handshake, connect limit {SHORT} s: still waiting at", SHORT + 3)
		self.assertFalse(outcome["finished"], "imapclient bounds its TLS connection itself now")

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
		try:
			with (
				patch.object(frappe.local, "request", object(), create=True),
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
		finally:
			if getattr(frappe.local, "imap_deadline", None) is not None:
				del frappe.local.imap_deadline

	def test_a_background_job_has_the_limits_of_each_operation_only(self):
		self.assertIsNone(getattr(frappe.local, "request", None))
		self.assertIsNone(imap_client._time_left())
		self.assertEqual(imap_client._within_budget(7), 7)
