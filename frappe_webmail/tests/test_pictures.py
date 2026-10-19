# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The pictures on the web a message links to, fetched for NeoMail in the browser (pictures.py, mailcraft_jmap.picture):
where an address may lead, what is taken from there, how many at a time, and who may ask.

The picture server is a fake on this machine's loopback, which the rules refuse: the tests let it through by name
(`pictures.example` stands for it) and keep the rules for every other address.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_pictures
"""

import gzip
import http.server
import ipaddress
import json
import threading
import time
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import mailcraft_jmap as jmap
from frappe_webmail import pictures

DESK = "neomail_pictures_desk@example.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + b"\0" * 32
LOOPBACK = ipaddress.ip_address("127.0.0.1")
INSIDE = ipaddress.ip_address("10.9.9.9")
NAMES = {
	"pictures.example": [LOOPBACK],
	"inside.example": [INSIDE],
	"mixed.example": [LOOPBACK, INSIDE],
}


# The rules themselves, before the tests let the fake server through.
RULES = pictures.is_public


def look_up(host, patience):
	return list(NAMES.get(host, []))


def allowed(ip):
	"""The rules, but for the fake server."""
	return ip == LOOPBACK or RULES(ip)


class Pictures(http.server.BaseHTTPRequestHandler):
	"""The fake picture server: each path answers one way, and every request it gets is kept."""

	seen: ClassVar[list] = []
	busy: ClassVar[set] = set()

	def log_message(self, *args):
		pass

	def answer(self, status, body=b"", kind="image/png", **headers):
		self.send_response(status)
		self.send_header("Content-Type", kind)
		self.send_header("Content-Length", str(headers.pop("length", len(body))))
		for name, value in headers.items():
			self.send_header(name.replace("_", "-"), value)
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self):
		Pictures.seen.append({"path": self.path, "headers": dict(self.headers)})
		path, port = self.path, self.server.server_address[1]
		if path == "/logo.png":
			return self.answer(200, PNG)
		if path.startswith("/hop/"):
			left = int(path.rsplit("/", 1)[1])
			return self.answer(302, Location=f"/hop/{left - 1}") if left else self.answer(200, PNG)
		if path == "/inside":
			return self.answer(302, Location=f"http://inside.example:{port}/logo.png")
		if path == "/relative/a/b.png":
			return self.answer(301, Location="../logo.png")
		if path == "/relative/logo.png":
			return self.answer(200, PNG)
		if path == "/page.html":
			return self.answer(200, b"<html><body>Not a picture</body></html>", kind="text/html")
		if path == "/announced":
			return self.answer(200, b"", length=pictures.MAX_BYTES + 1)
		if path == "/streamed":
			return self.answer(200, PNG + b"\0" * (pictures.MAX_BYTES + 10))
		if path == "/busy-once":
			if path not in Pictures.busy:
				Pictures.busy.add(path)
				return self.answer(429, b"", kind="text/plain", Retry_After="0")
			return self.answer(200, PNG)
		if path == "/packed":
			return self.answer(200, gzip.compress(PNG), Content_Encoding="gzip")
		if path == "/bomb":
			return self.answer(
				200, gzip.compress(PNG + b"\0" * (pictures.MAX_BYTES * 2)), Content_Encoding="gzip"
			)
		if path == "/members":
			# The picture in two members of one gzip stream, as a few servers send it.
			return self.answer(
				200, gzip.compress(PNG[:20]) + gzip.compress(PNG[20:]), Content_Encoding="gzip"
			)
		if path == "/many-members":
			# One member more than a stream may hold (all empty: before the cap, this read as no picture at all).
			return self.answer(
				200, gzip.compress(b"", mtime=0) * (pictures.MAX_MEMBERS + 1), Content_Encoding="gzip"
			)
		if path == "/packed-twice":
			# A great many empty members packed once more: a few bytes on the wire that cost minutes to read back.
			empty = gzip.compress(b"", mtime=0) * (pictures.MAX_BYTES // 20)
			return self.answer(200, gzip.compress(empty), Content_Encoding="gzip, gzip")
		if path == "/chunked":
			# In chunks, with a length beside them that counts for nothing (RFC 9112).
			self.protocol_version = "HTTP/1.1"
			self.send_response(200)
			self.send_header("Content-Type", "image/png")
			self.send_header("Transfer-Encoding", "chunked")
			self.send_header("Content-Length", "5")
			self.send_header("Connection", "close")
			self.end_headers()
			for piece in (PNG[:10], PNG[10:]):
				self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
			self.wfile.write(b"0\r\n\r\n")
			self.close_connection = True
			return None
		if path == "/cut":
			# Less than the length it says, then the connection ends.
			self.send_response(200)
			self.send_header("Content-Type", "image/png")
			self.send_header("Content-Length", str(len(PNG) + 5000))
			self.end_headers()
			self.wfile.write(PNG)
			self.wfile.flush()
			self.close_connection = True
			return None
		if path == "/slow":
			self.send_response(200)
			self.send_header("Content-Type", "image/png")
			self.end_headers()
			self.wfile.write(PNG[:4])
			self.wfile.flush()
			time.sleep(3)
			return None
		return self.answer(404, b"", kind="text/plain")


class TestPictures(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pictures)
		cls.server.daemon_threads = True
		# A picture left half sent (too large, too slow) is no failure of the fake server's.
		cls.server.handle_error = lambda request, client: None
		cls.port = cls.server.server_address[1]
		threading.Thread(target=cls.server.serve_forever, daemon=True).start()
		if not frappe.db.exists("User", DESK):
			user = frappe.get_doc(
				{"doctype": "User", "email": DESK, "first_name": "Pictures", "send_welcome_email": 0}
			)
			user.append("roles", {"role": "Blogger"})
			user.insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		cls.server.shutdown()
		cls.server.server_close()
		super().tearDownClass()

	def setUp(self):
		Pictures.seen.clear()
		Pictures.busy.clear()
		# The fake server stands for a server on the web, on the usual port; a bench of its own for the turns.
		self.patches = [
			patch.dict(pictures.PORTS, {"http": self.port}),
			patch.object(pictures, "is_public", allowed),
			patch.object(
				pictures, "FLYING", "neomail-pictures-flying-test-" + frappe.generate_hash(length=8)
			),
			patch.dict(frappe.local.conf, {"neomail_disabled": 0}),
		]
		for p in self.patches:
			p.start()

	def tearDown(self):
		frappe.cache().delete(pictures.FLYING)
		for key in pictures._spent_keys(DESK):
			frappe.cache().delete(key)
		for p in reversed(self.patches):
			p.stop()
		frappe.local.flags.mailcraft_jmap_user = None
		frappe.set_user("Administrator")

	def url(self, path, host="pictures.example"):
		return f"http://{host}:{self.port}{path}"

	def fetch(self, path, host="pictures.example"):
		return pictures.fetch(self.url(path, host), look_up=look_up)

	def refused(self, path, host="pictures.example"):
		with self.assertRaises(pictures.PictureError) as caught:
			self.fetch(path, host)
		return caught.exception.kind, caught.exception.status

	# Where an address may lead ----------------------------------------------------------------------------------

	def test_only_the_public_internet(self):
		for text, public in (
			("8.8.8.8", True),
			("1.1.1.1", True),
			("127.0.0.1", False),
			("10.0.0.1", False),
			("100.64.0.1", False),
			("169.254.169.254", False),
			("172.16.0.1", False),
			("192.168.1.1", False),
			("192.0.2.1", False),
			("198.18.0.1", False),
			("0.0.0.0", False),
			("224.0.0.1", False),
			("255.255.255.255", False),
			("2606:4700:4700::1111", True),
			("::1", False),
			("fe80::1", False),
			("fc00::1", False),
			("2001:db8::1", False),
			("2002:7f00:1::", False),
			("::ffff:127.0.0.1", False),
			("::ffff:8.8.8.8", True),
			("64:ff9b::7f00:1", False),
			("64:ff9b::808:808", True),
		):
			self.assertEqual(RULES(ipaddress.ip_address(text)), public, text)

	def test_an_address_is_read_the_way_a_browser_reads_it(self):
		place = pictures.address(' HTTPS://Pictures.Example/a/./b/../c d\u00e9.png?x="1"#top ')
		self.assertEqual(
			(place.scheme, place.host, place.target),
			("https", "pictures.example", "/a/c%20d%C3%A9.png?x=%221%22"),
		)
		self.assertEqual(pictures.address("http://pictures.example").target, "/")
		self.assertEqual(pictures.address("http://pictures.example?q=1").target, "/?q=1")
		self.assertEqual(pictures.address("https://[2606:4700::1]/x.png").authority, "[2606:4700::1]")
		self.assertEqual(pictures.address("https://b\u00fccher.example/x.png").host, "xn--bcher-kva.example")
		self.assertEqual(pictures.address("http://8.8.8.8/x.png").host, "8.8.8.8")
		self.assertEqual(pictures.address("https://pictures.example/apiary/x.png").target, "/apiary/x.png")
		# Only Frappe's methods are refused under /api: an avatar drawn from a name is a picture.
		self.assertEqual(pictures.address("https://avatars.example/api/?name=Ann").target, "/api/?name=Ann")
		for text in (
			# A number a browser reads as an address, other than the four usual ones.
			"http://2130706433/x.png",
			"http://127.1/x.png",
			"http://017700000001/x.png",
			"http://0x7f.0.0.1/x.png",
			"http://1.2.3.04/x.png",
			"http://pictures.123/x.png",
			# A method of a Frappe site, by its path or its query, whatever the case or the escapes.
			"https://pictures.example/api/method/frappe.auth.get_logged_user",
			"https://pictures.example//API/resource/User",
			"https://pictures.example/api/v2/method/frappe.ping",
			# The same, written so that only the server's decoding reads it as such.
			"https://pictures.example/%61pi/method/frappe.ping",
			"https://pictures.example/api%2Fmethod%2Ffrappe.ping",
			"https://pictures.example/%2Fapi/method/frappe.ping",
			"https://pictures.example/a/%2e%2e/api/resource/User",
			"https://pictures.example/api%5Cmethod/frappe.ping",
			"https://pictures.example/?cmd=frappe.ping",
			"https://pictures.example/logo.png?size=2&c%6Dd=frappe.ping",
			"https://pictures.example/logo.png?a=1;cmd=frappe.ping",
			"ftp://pictures.example/x.png",
			"javascript:alert(1)",
			"data:image/png;base64,AAAA",
			"//pictures.example/x.png",
			"http://user:secret@pictures.example/x.png",
			"http://pictures.example@inside.example/x.png",
			"http://pictures.example:8080/x.png",
			"https://pictures.example:80/x.png",
			"http://pictures.example\\@inside.example/",
			"http://%31%32%37.0.0.1/x.png",
			"http:///x.png",
			"http://pictures.example/a\nb.png",
			"http://[::1/x.png",
			"http://pictures.example:/x.png",
			"http://" + "a" * 8000 + ".example/",
			None,
		):
			with self.assertRaises(pictures.PictureError, msg=repr(text)):
				pictures.address(text)

	def test_a_redirect_leads_on_from_where_it_was(self):
		start = pictures.address("https://pictures.example/news/2026/logo.png?size=2")
		for location, expected in (
			("https://other.example/x.png", ("https", "other.example", "/x.png")),
			("//other.example/y.png", ("https", "other.example", "/y.png")),
			("/z.png", ("https", "pictures.example", "/z.png")),
			("small.png", ("https", "pictures.example", "/news/2026/small.png")),
			("../older/a.png", ("https", "pictures.example", "/news/older/a.png")),
			("http://other.example/", ("http", "other.example", "/")),
		):
			place = pictures.follow(start, location)
			self.assertEqual((place.scheme, place.host, place.target), expected, location)
		for location in (
			"",
			"javascript:alert(1)",
			"ftp://other.example/x",
			"c:/x.png",
			"/api/method/frappe.ping",
			"/%61pi/method/frappe.ping",
			"?cmd=frappe.ping",
			"https://2130706433/x.png",
		):
			with self.assertRaises(pictures.PictureError, msg=location):
				pictures.follow(start, location)

	def test_a_number_that_names_this_machine_is_refused_by_the_rules_too(self):
		"""Were the reading of a number ever to let one through, the lookup's answer is checked all the same."""
		deadline = time.monotonic() + 5
		with patch.object(pictures, "is_public", RULES):
			for host in ("2130706433", "127.1", "017700000001"):
				with self.assertRaises(pictures.PictureError, msg=host):
					pictures._addresses(host, deadline, pictures._look_up)

	def test_a_name_that_leads_inside_is_refused_and_nothing_is_asked(self):
		self.assertEqual(self.refused("/logo.png", "inside.example"), ("not_public", None))
		self.assertEqual(
			self.refused("/logo.png", "mixed.example"), ("not_public", None), "one address inside refuses all"
		)
		self.assertEqual(self.refused("/logo.png", "localhost"), ("not_public", None))
		self.assertEqual(self.refused("/logo.png", "nowhere.example"), ("lookup", None))
		self.assertEqual(Pictures.seen, [])
		# A redirect is checked the same way.
		self.assertEqual(self.refused("/inside"), ("not_public", None))
		self.assertEqual([s["path"] for s in Pictures.seen], ["/inside"])

	# What is taken ------------------------------------------------------------------------------------------------

	def test_a_picture_comes_with_nothing_of_the_person(self):
		body, kind = self.fetch("/logo.png")
		self.assertEqual((body, kind), (PNG, "image/png"))
		headers = {k.lower(): v for k, v in Pictures.seen[0]["headers"].items()}
		# Connected to the address checked, named as the message names it.
		self.assertEqual(headers["host"], f"pictures.example:{self.port}")
		self.assertEqual(headers["user-agent"], pictures.USER_AGENT)
		self.assertEqual(headers["accept-encoding"], "identity")
		for absent in ("cookie", "referer", "authorization", "origin"):
			self.assertNotIn(absent, headers)

	def test_redirects_are_followed_five_times(self):
		self.assertEqual(self.fetch("/hop/5"), (PNG, "image/png"))
		self.assertEqual(self.refused("/hop/6"), ("redirects", None))
		self.assertEqual(self.fetch("/relative/a/b.png"), (PNG, "image/png"))

	def test_what_comes_must_be_a_picture_of_a_bounded_size(self):
		self.assertEqual(self.refused("/page.html"), ("not_picture", None))
		self.assertEqual(self.refused("/announced"), ("too_large", None))
		self.assertEqual(self.refused("/streamed"), ("too_large", None))
		self.assertEqual(self.refused("/missing.png"), ("status", 404))
		# Cut before the length it said: not taken for the whole picture.
		self.assertEqual(self.refused("/cut"), ("broken", None))
		# Sent in chunks with a length beside them: whole all the same.
		self.assertEqual(self.fetch("/chunked"), (PNG, "image/png"))
		self.assertEqual(pictures.picture_kind(b"GIF89a..."), "image/gif")
		self.assertEqual(pictures.picture_kind(b"RIFF\0\0\0\0WEBPVP8 "), "image/webp")
		self.assertEqual(pictures.picture_kind(b"\xff\xd8\xff\xe0"), "image/jpeg")
		self.assertIsNone(pictures.picture_kind(b"<svg xmlns='http://www.w3.org/2000/svg'/>"))

	def test_a_packed_body_is_unpacked_within_the_same_limit(self):
		self.assertEqual(self.fetch("/packed"), (PNG, "image/png"))
		self.assertEqual(self.refused("/bomb"), ("too_large", None))
		with self.assertRaises(pictures.PictureError):
			pictures.unpack(b"\x1f\x8b not gzip at all", "gzip")
		self.assertEqual(pictures.unpack(PNG, "gzip"), PNG, "said of a body sent as it is")
		with self.assertRaises(pictures.PictureError):
			pictures.unpack(PNG, "br")
		self.assertEqual(self.fetch("/members"), (PNG, "image/png"), "two members of one stream")

	def test_a_body_that_costs_more_to_unpack_than_a_picture_is_left_at_once(self):
		"""A great many empty gzip members, on their own or packed once more: refused in a moment, not after minutes of
		a worker's time."""
		for path in ("/many-members", "/packed-twice"):
			started = time.monotonic()
			self.assertEqual(self.refused(path), ("packed", None), path)
			self.assertLess(time.monotonic() - started, 3, path)
		# And whatever is left of the picture's time bounds the unpacking.
		with self.assertRaises(pictures.PictureError) as caught:
			pictures.unpack(gzip.compress(PNG), "gzip", deadline=time.monotonic() - 1)
		self.assertEqual(caught.exception.kind, "timeout")
		# Packed three times over is no answer of a picture's server.
		with self.assertRaises(pictures.PictureError) as caught:
			pictures.unpack(gzip.compress(gzip.compress(gzip.compress(PNG))), "gzip, gzip, gzip")
		self.assertEqual(caught.exception.kind, "packed")

	def test_a_server_that_says_not_now_is_asked_once_more(self):
		with patch.object(pictures, "RETRY_WAIT", 0.01), patch.object(pictures, "MAX_RETRY_WAIT", 0.05):
			self.assertEqual(self.fetch("/busy-once"), (PNG, "image/png"))
		self.assertEqual([s["path"] for s in Pictures.seen], ["/busy-once", "/busy-once"])

	def test_a_slow_server_is_left_when_the_time_is_up(self):
		with patch.object(pictures, "PATIENCE", 0.6):
			started = time.monotonic()
			self.assertEqual(self.refused("/slow"), ("timeout", None))
			self.assertLess(time.monotonic() - started, 2.5)

	# How many at a time, and who may ask --------------------------------------------------------------------------

	def test_the_bench_fetches_a_few_at_a_time(self):
		with patch.dict(frappe.local.conf, {"neomail_picture_slots": 1}):
			first = pictures._take_turn()
			self.assertIsNotNone(first)
			self.assertIsNone(pictures._take_turn(), "all turns taken")
			pictures._give_back(first)
			second = pictures._take_turn()
			self.assertIsNotNone(second)
			# A turn its worker never gave back stops counting after a while.
			frappe.cache().zadd(pictures.FLYING, {second: time.time() - 2 * pictures.FLYING_STALE})
			self.assertIsNotNone(pictures._take_turn())
		with patch.dict(frappe.local.conf, {"neomail_picture_slots": 0, "gunicorn_workers": 9}):
			self.assertEqual(pictures._slots(), 3)
		with patch.dict(frappe.local.conf, {"neomail_picture_slots": 0, "gunicorn_workers": 2}):
			self.assertEqual(pictures._slots(), 1)

	def test_the_relay_answers_a_picture_or_why_not(self):
		with patch.object(pictures, "fetch", return_value=(PNG, "image/png")):
			answer = pictures.relay("http://pictures.example/logo.png", DESK)
		self.assertEqual(
			(answer.status_code, answer.content_type, answer.get_data()), (200, "image/png", PNG)
		)
		self.assertEqual(answer.headers["X-Content-Type-Options"], "nosniff")
		for error, status in (
			(pictures.PictureError("not_public"), 400),
			(pictures.PictureError("too_large"), 413),
			(pictures.PictureError("not_picture"), 415),
			(pictures.PictureError("timeout"), 504),
			(pictures.PictureError("status", 403), 502),
			(pictures.PictureError("status", 404), 502),
		):
			with patch.object(pictures, "fetch", side_effect=error):
				answer = pictures.relay("http://pictures.example/logo.png", DESK)
			self.assertEqual(answer.status_code, status, error.kind)
			self.assertTrue(json.loads(answer.get_data())["detail"], error.kind)
		# Every turn was given back.
		self.assertEqual(frappe.cache().zcard(pictures.FLYING), 0)
		with patch.dict(frappe.local.conf, {"neomail_picture_slots": 1}):
			held = pictures._take_turn()
			answer = pictures.relay("http://pictures.example/logo.png", DESK)
			pictures._give_back(held)
		self.assertEqual((answer.status_code, answer.headers.get("Retry-After")), (503, "1"))

	def test_a_person_fetches_so_many_in_ten_minutes(self):
		with (
			patch.object(pictures, "MAX_PICTURES", 2),
			patch.object(pictures, "fetch", return_value=(PNG, "image/png")),
		):
			statuses = [
				pictures.relay("http://pictures.example/logo.png", DESK).status_code for _i in range(3)
			]
		self.assertEqual(statuses, [200, 200, 429])
		with (
			patch.object(pictures, "MAX_WINDOW_BYTES", len(PNG)),
			patch.object(pictures, "fetch", return_value=(PNG, "image/png")),
		):
			for key in pictures._spent_keys(DESK):
				frappe.cache().delete(key)
			statuses = [
				pictures.relay("http://pictures.example/logo.png", DESK).status_code for _i in range(3)
			]
		self.assertEqual(statuses, [200, 200, 429], "the bytes of the window count too")
		# A request answered "busy" counts for nothing: the page asks again, and nothing was fetched.
		for key in pictures._spent_keys(DESK):
			frappe.cache().delete(key)
		with patch.dict(frappe.local.conf, {"neomail_picture_slots": 1}):
			held = pictures._take_turn()
			for _i in range(3):
				self.assertEqual(pictures.relay("http://pictures.example/logo.png", DESK).status_code, 503)
			pictures._give_back(held)
		self.assertEqual(frappe.cache().mget(pictures._spent_keys(DESK)), [None, None])

	def test_only_the_facade_s_token_asks_for_a_picture(self):
		path = "/api/method/frappe_webmail.mailcraft_jmap.picture"
		token = jmap.give_token(DESK)
		frappe.set_user("Guest")
		with (
			patch.object(frappe.local, "request", SimpleNamespace(path=path), create=True),
			patch.object(
				frappe.local, "form_dict", frappe._dict({"url": "http://pictures.example/logo.png"})
			),
			patch("frappe.get_request_header", return_value=f"Bearer {token}"),
			patch.object(jmap, "_session_alive", return_value=True),
		):
			jmap.authenticate()
		self.assertEqual((frappe.session.user, frappe.local.flags.mailcraft_jmap_user), (DESK, DESK))
		with patch.object(pictures, "fetch", return_value=(PNG, "image/png")):
			self.assertEqual(jmap.picture("http://pictures.example/logo.png").status_code, 200)
			# A desk session's cookie alone: refused, so that another site can't make a browser fetch through here.
			frappe.local.flags.mailcraft_jmap_user = None
			self.assertEqual(jmap.picture("http://pictures.example/logo.png").status_code, 403)
			with patch.dict(frappe.local.conf, {"neomail_disabled": 1}):
				frappe.local.flags.mailcraft_jmap_user = DESK
				self.assertEqual(jmap.picture("http://pictures.example/logo.png").status_code, 404)
			# Whatever goes wrong is answered here, never left to Frappe (which would log the request's form).
			with patch.object(jmap, "_gate", side_effect=RuntimeError("down")):
				self.assertEqual(jmap.picture("http://pictures.example/logo.png").status_code, 500)

	def test_a_token_that_cant_be_checked_is_no_token_and_leaves_nothing_in_the_log(self):
		"""The cache or the database failing while a token is checked: the request goes on as a visitor's (refused by
		the gate), and the log says what failed, not the request's form nor the session the token is bound to."""
		path = "/api/method/frappe_webmail.mailcraft_jmap.picture"
		address = "http://pictures.example/for-ann-at-example-org.png"
		frappe.set_user("Guest")
		frappe.local.flags.mailcraft_jmap_user = None
		with (
			patch.object(frappe.local, "request", SimpleNamespace(path=path), create=True),
			patch.object(frappe.local, "form_dict", frappe._dict({"url": address})),
			patch("frappe.get_request_header", return_value="Bearer some-token"),
			patch.object(jmap, "_person_of_token", side_effect=RuntimeError("cache down for " + address)),
		):
			jmap.authenticate()
		self.assertEqual(frappe.session.user, "Guest")
		self.assertIsNone(frappe.local.flags.mailcraft_jmap_user)
		logged = frappe.get_all(
			"Error Log",
			filters={"method": "MailCraft JMAP: a token could not be checked"},
			fields=["name", "error"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(logged)
		self.assertNotIn("for-ann-at-example-org", logged[0].error)
		frappe.delete_doc("Error Log", logged[0].name, ignore_permissions=True, force=True)

	def test_an_unforeseen_error_is_answered_and_logged_without_the_address(self):
		address = "http://pictures.example/for-ann-at-example-org.png"
		title = "NeoMail: a picture could not be fetched"
		with patch.object(pictures, "_take_turn", side_effect=RuntimeError(f"turn lost for {address}")):
			answer = pictures.relay(address, DESK)
		self.assertEqual(answer.status_code, 502)
		logged = frappe.get_all(
			"Error Log",
			filters={"method": title},
			fields=["name", "error"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(logged)
		self.assertIn("RuntimeError", logged[0].error)
		self.assertNotIn("for-ann-at-example-org", logged[0].error)
		frappe.delete_doc("Error Log", logged[0].name, ignore_permissions=True, force=True)
