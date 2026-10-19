# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
The pictures a message links to on the web, fetched here for NeoMail in the browser (maintenance#1630). A page may not
read the bytes of another site's picture, so MailCraft's browser build asks the page that hosts it
(`window.mailcraftFetchUrl`), and /neomail asks this server (mailcraft_jmap.picture). MailCraft asks only once the
person said so (Download pictures for a message, a sender or a domain they chose, or the switch in its options, off by
default), and only while the message is on screen: that choice is MailCraft's, and nothing here fetches by itself.

The rules are the ones MailCraft keeps on the desktop (mailcraft_net::pictures there, its only way out):
- `http` or `https`, a host, no user name or password; here the usual port only (80, 443), since a service on another
  port of a server may trust this server's address; a host written as a number other than the four usual ones
  (`2130706433`, `127.1`, `0x7f.0.0.1`: a browser reads them as addresses) is no address;
- every address the host's name gives is of the public internet (`is_public`): never this machine, nor a private,
  carrier, link-local or set-aside network, nor `localhost`; one that isn't refuses them all; and the connection goes
  to the very address checked, so that a name can't answer the check with one address and the connection with another;
- here also, never a method of a Frappe site (`/api/method/…`, `/api/resource/…`, `/api/v1/…`, `/api/v2/…`, read as
  the server reads them, decoded; or a `cmd` in the query, which Frappe runs whatever the path): the request leaves
  from this instance's address, which other servers of its fleet may trust, and a picture is never one of their
  answers;
- at most five redirects, each new address checked the same way;
- at most 8 MB, all of it within 15 seconds from the lookup to the last byte, its unpacking included (the desktop waits
  30: here a worker of the desk waits with it);
- nothing of the person goes with the request: no cookie, no referrer, no credentials, a plain user agent; the plain
  kinds of picture accepted and nothing packed asked for (what comes packed all the same is unpacked within the 8 MB);
- a server that says "not now" (429, 503) is asked once more after a moment (what it says, 1 to 3 seconds);
- what comes is whole (as long as the server said) and a PNG, a JPEG, a GIF or a WebP by its own bytes, and is
  answered as that kind.

The bench fetches a few at a time (`_slots`: a third of its web workers, which its sites share), so that the desk stays
free for everything else: one more is answered 503 at once, and the page asks again a moment later. A person fetches
so many pictures and so many bytes in ten minutes at most. The address of a picture is never logged: it may say who
the message went to.
"""

import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
import zlib
from urllib.parse import parse_qsl, unquote

import frappe
from frappe import _
from frappe.translate import get_user_lang
from frappe.utils import cint
from werkzeug.wrappers import Response

MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 5
# Seconds: the whole of one picture, redirects included; a connection; one read.
PATIENCE = 15.0
CONNECT = 5.0
IO = 8.0
# The most addresses of a name tried, and the most looked at.
MAX_ADDRESSES = 4
MAX_LOOKED_UP = 16
# The longest address read (longer, it is no address).
MAX_URL = 8000
# The most codings a body may say it was packed with, and the most gzip members one may hold (a server sends one; a
# great many empty ones would cost far more time than the picture's).
MAX_CODINGS = 2
MAX_MEMBERS = 16
USER_AGENT = "Mozilla/5.0 (compatible; MailCraft)"
# The plain kinds first: a server that can send a newer one (WebP, AVIF) sends it only to those who name it.
ACCEPT = "image/png, image/jpeg, image/gif, image/*;q=0.5, */*;q=0.1"
# How long a server that says "not now" is left alone before it is asked again: what it says, within these.
RETRY_WAIT = 1.0
MAX_RETRY_WAIT = 3.0
# The only ports asked: the usual one of each scheme.
PORTS = {"http": 80, "https": 443}
REDIRECTS = (301, 302, 303, 307, 308)
CHUNK = 64 * 1024

# What one person fetches in ten minutes at most.
WINDOW = 600
MAX_PICTURES = 600
MAX_WINDOW_BYTES = 400 * 1024 * 1024

# The bench's pictures on their way: a sorted set of who holds a turn, by when they took it. The key is the bench's
# and not a site's, since the bench's sites share its web workers. A turn older than FLYING_STALE seconds no longer
# counts: no picture takes longer than PATIENCE, so its worker was stopped before it gave it back.
FLYING = "neomail-pictures-flying"
FLYING_STALE = 25

_NAME = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+)*\.?$")
# A part of a host that a browser reads as a number (decimal, octal or hexadecimal).
_NUMBER = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")
# Where a Frappe site answers its methods, with whatever slashes and case.
_METHODS = re.compile(r"^/+api/+(?:method|resource|v1|v2)(?:/|$)", re.IGNORECASE)
_TLS = None


class PictureError(Exception):
	"""Why a picture was not fetched: `kind` says it (`_reason`), with the status the server answered when that is
	why."""

	def __init__(self, kind, status=None):
		super().__init__(kind)
		self.kind = kind
		self.status = status


# ---------------------------------------------------------------------------------------------------------------
# Where an address leads
# ---------------------------------------------------------------------------------------------------------------


def is_public(ip):
	"""Whether an address is one of the public internet's: not this machine, not a private, carrier, link-local or
	site-local network, not multicast or broadcast, and not one of the ranges set aside for documentation, benchmarks,
	relays and protocols. An IPv6 address that carries an IPv4 one (mapped, or through NAT64) is judged by the one it
	carries."""
	if ip.version == 6:
		carried = ip.ipv4_mapped or _nat64(ip)
		if carried is None:
			return _public_v6(ip)
		ip = carried
	a, b, c, _d = ip.packed
	set_aside = (
		a == 0  # "this network"; 0.0.0.0 is this machine on some systems
		or a == 10  # private
		or (a == 100 and 64 <= b < 128)  # shared by a carrier's customers
		or a == 127  # this machine
		or (a == 169 and b == 254)  # link-local, and where clouds keep their metadata
		or (a == 172 and 16 <= b < 32)  # private
		or (a == 192 and b == 0 and c in (0, 2))  # protocol assignments; documentation
		or (a == 192 and b == 88 and c == 99)  # relays to IPv6
		or (a == 192 and b == 168)  # private
		or (a == 198 and 18 <= b < 20)  # benchmarks
		or (a == 198 and b == 51 and c == 100)  # documentation
		or (a == 203 and b == 0 and c == 113)  # documentation
		or a >= 224  # multicast, reserved, broadcast
	)
	return not set_aside


def _nat64(ip):
	"""The IPv4 address `64:ff9b::a.b.c.d` (NAT64) stands for."""
	return (
		ipaddress.IPv4Address(ip.packed[12:])
		if ip.packed[:12] == bytes.fromhex("0064ff9b" + "00" * 8)
		else None
	)


def _public_v6(ip):
	a, b = int.from_bytes(ip.packed[0:2], "big"), int.from_bytes(ip.packed[2:4], "big")
	# What is handed out to the internet at large is 2000::/3 (so not ::1, fc00::/7, fe80::/10, ff00::/8), less what
	# is set aside inside it.
	handed_out = a & 0xE000 == 0x2000
	set_aside = (
		(a == 0x2001 and b < 0x0200)  # Teredo, benchmarks and other protocol assignments
		or (a == 0x2001 and b == 0x0DB8)  # documentation
		or a == 0x2002  # 6to4: an IPv4 address in disguise
		or (a == 0x3FFF and b < 0x1000)  # documentation
	)
	return handed_out and not set_aside


class Place:
	"""Where a picture is asked for: the scheme, the host as the request names it, and the path with its query."""

	__slots__ = ("host", "secure", "target")

	def __init__(self, secure, host, target):
		self.secure, self.host, self.target = secure, host, target

	@property
	def scheme(self):
		return "https" if self.secure else "http"

	@property
	def port(self):
		return PORTS[self.scheme]

	@property
	def authority(self):
		return f"[{self.host}]" if ":" in self.host else self.host

	def __repr__(self):
		# Never the address itself: it may say who the message went to.
		return f"Place({self.scheme})"


def address(text):
	"""Read `text` as the address of a picture: `http://` or `https://`, a host, the usual port, a path. What follows a
	`#` is dropped (it is never sent); a space, a quote or a letter that isn't ASCII in the path or the query becomes
	`%XX` of its UTF-8, as a browser has it; `.` and `..` steps are taken."""
	if not isinstance(text, str):
		raise PictureError("address")
	text = text.strip().split("#", 1)[0]
	if not text or len(text) > MAX_URL:
		raise PictureError("address")
	scheme, sep, rest = text.partition("://")
	scheme = scheme.lower()
	if not sep or scheme not in PORTS:
		raise PictureError("address")
	cut = min((at for at in (rest.find("/"), rest.find("?")) if at >= 0), default=len(rest))
	authority, tail = rest[:cut], rest[cut:]
	if any(ord(c) < 32 or ord(c) == 127 for c in tail):
		raise PictureError("address")
	host, port = _host_and_port(authority)
	if port is not None and port != PORTS[scheme]:
		raise PictureError("address")
	tail = _escaped(tail)
	target = without_dots(tail if tail.startswith("/") else "/" + tail)
	path, _mark, query = target.partition("?")
	# A method of a Frappe site, by its path or by a `cmd` in the query (whatever its case or its escapes): never a
	# picture, and asked from this instance's address, which servers of its fleet may trust. The path as the server
	# reads it: decoded (`/%61pi/method/…`, `/api%2Fmethod…` are the same address to it), its steps taken again.
	if _METHODS.match(without_dots(unquote(path).replace("\\", "/"))) or any(
		key.strip().lower() == "cmd"
		for key, _value in parse_qsl(query.replace(";", "&"), keep_blank_values=True)
	):
		raise PictureError("address")
	return Place(scheme == "https", host, target)


def _host_and_port(authority):
	"""The host (lower case, a name in its ASCII form, or an address) and the port (None: none said)."""
	if (
		not authority
		or "@" in authority
		or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in authority)
	):
		raise PictureError("address")
	if authority.startswith("["):
		literal, bracket, rest = authority[1:].partition("]")
		if not bracket or (rest and not rest.startswith(":")):
			raise PictureError("address")
		try:
			host = ipaddress.IPv6Address(literal).compressed
		except ValueError:
			raise PictureError("address") from None
		port = rest[1:] if rest else None
	else:
		name, colon, port = authority.partition(":")
		port = port if colon else None
		host = _name(name)
	if port is None:
		return host, None
	if not (port.isascii() and port.isdigit() and len(port) <= 5 and 0 < int(port) <= 65535):
		raise PictureError("address")
	return host, int(port)


def _name(text):
	try:
		name = text.encode("idna").decode("ascii").lower() if not text.isascii() else text.lower()
	except UnicodeError:
		raise PictureError("address") from None
	if not _NAME.match(name) or len(name) > 253:
		raise PictureError("address")
	# A browser reads a host whose last part is a number as an address, whatever way it is written: only the four
	# usual numbers are one here.
	if _NUMBER.match(name.rstrip(".").rsplit(".", 1)[-1]):
		try:
			return str(ipaddress.IPv4Address(name.rstrip(".")))
		except ValueError:
			raise PictureError("address") from None
	return name


def _escaped(tail):
	out = []
	for c in tail:
		if c == " " or c in '"<>`' or not c.isascii():
			out.extend(f"%{b:02X}" for b in c.encode("utf-8"))
		else:
			out.append(c)
	return "".join(out)


def without_dots(path):
	"""A path (and its query) with its `.` and `..` steps taken, the way a browser takes them before it asks:
	`/a/b/../c.png` is `/a/c.png`, and no step climbs above the top."""
	steps, mark, query = path.partition("?")
	parts = steps.split("/")
	if not any(step in (".", "..") for step in parts):
		return path
	kept, folder = [], False
	for step in parts[1:]:
		folder = step in (".", "..")
		if step == "..":
			if kept:
				kept.pop()
		elif step != ".":
			kept.append(step)
	# A path that ends in a step up or a step in place ends at a folder.
	return "/" + "/".join(kept) + ("/" if folder and kept else "") + mark + query


def follow(start, location):
	"""The place a redirect from `start` leads to: a whole address, or one written from where `start` is."""
	location = (location or "").strip()
	if not location or len(location) > MAX_URL:
		raise PictureError("address")
	before, sep, _rest = location.partition("://")
	if sep and before and all(c.isascii() and (c.isalnum() or c in "+-.") for c in before):
		return address(location)
	if location.startswith("//"):
		return address(f"{start.scheme}:{location}")
	if location.startswith("/"):
		return address(f"{start.scheme}://{start.authority}{location}")
	# Beside where `start` is. A first step with a colon in it would be a scheme, not a path.
	if ":" in re.split(r"[/?]", location, maxsplit=1)[0]:
		raise PictureError("address")
	folder = start.target.split("?", 1)[0].rsplit("/", 1)[0]
	return address(f"{start.scheme}://{start.authority}{folder}/{location}")


def _look_up(host, patience):
	"""The system's answer to "where is `host`", waited for `patience` seconds at most: the system takes its own time
	over a name whose servers don't answer, so it is asked on a thread that can be left behind."""
	found = []
	done = threading.Event()

	def look():
		try:
			for *_kind, where in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)[:MAX_LOOKED_UP]:
				found.append(ipaddress.ip_address(where[0].split("%", 1)[0]))
		except (OSError, UnicodeError, ValueError):
			pass
		finally:
			done.set()

	threading.Thread(target=look, name="picture lookup", daemon=True).start()
	return list(found) if done.wait(max(patience, 0.0)) else None


def _addresses(host, deadline, look_up):
	"""The addresses of `host` to connect to, every one of them checked, IPv6 and IPv4 taking turns."""
	if host.rstrip(".") == "localhost" or host.rstrip(".").endswith(".localhost"):
		raise PictureError("not_public")
	try:
		# An address needs no looking up, and no resolver gets to read it its own way.
		found = [ipaddress.ip_address(host)]
	except ValueError:
		found = look_up(host, deadline - time.monotonic())
		if found is None:
			raise PictureError("timeout") from None
	unique = list(dict.fromkeys(found))
	if not unique:
		raise PictureError("lookup")
	# One address that isn't public refuses them all: a name that points both at the internet and into a private
	# network is up to no good.
	if not all(is_public(ip) for ip in unique):
		raise PictureError("not_public")
	same = [ip for ip in unique if ip.version == unique[0].version]
	other = [ip for ip in unique if ip.version != unique[0].version]
	turns = [ip for pair in zip(same, other, strict=False) for ip in pair]
	longer = same if len(same) > len(other) else other
	turns += longer[min(len(same), len(other)) :]
	return turns[:MAX_ADDRESSES]


# ---------------------------------------------------------------------------------------------------------------
# Asking for it
# ---------------------------------------------------------------------------------------------------------------


def _tls():
	global _TLS
	if _TLS is None:
		context = ssl.create_default_context()
		context.minimum_version = ssl.TLSVersion.TLSv1_2
		_TLS = context
	return _TLS


class _Plain(http.client.HTTPConnection):
	"""A connection to `ip`, the address that was checked, whose requests name `host`."""

	def __init__(self, host, ip, port, timeout):
		super().__init__(host, port, timeout=timeout)
		self.ip = ip

	def connect(self):
		self.sock = socket.create_connection((str(self.ip), self.port), self.timeout)


class _Secure(http.client.HTTPSConnection):
	"""The same over TLS: the certificate is checked against `host`, whatever address was connected to. The handshake
	comes after the socket is kept, so that the picture's timer can end a handshake that drags on too."""

	def __init__(self, host, ip, port, timeout):
		super().__init__(host, port, timeout=timeout, context=_tls())
		self.ip = ip

	def connect(self):
		raw = socket.create_connection((str(self.ip), self.port), self.timeout)
		try:
			self.sock = self._context.wrap_socket(
				raw, server_hostname=self.host, do_handshake_on_connect=False
			)
		except BaseException:
			raw.close()
			raise
		self.sock.do_handshake()


def _cut_at(deadline, connection):
	"""A timer that ends `connection` when the picture's time is up, whatever it waits for then (a handshake, a
	header, a byte): every read is bounded by IO, and this bounds them all together."""

	def cut():
		sock = connection.sock
		if sock is not None:
			try:
				# The socket's own shutdown, under TLS too: the reads waiting on it end at once.
				socket.socket.shutdown(sock, socket.SHUT_RDWR)
			except OSError:
				pass

	timer = threading.Timer(max(deadline - time.monotonic(), 0.0), cut)
	timer.daemon = True
	timer.start()
	return timer


def _connect(place, deadline, look_up):
	"""A connection to the first address of `place`'s host that takes one, its timer running."""
	failure = PictureError("connect")
	for ip in _addresses(place.host, deadline, look_up):
		left = deadline - time.monotonic()
		if left <= 0:
			raise PictureError("timeout")
		kind = _Secure if place.secure else _Plain
		connection = kind(place.host, ip, place.port, min(CONNECT, left))
		timer = _cut_at(deadline, connection)
		try:
			connection.connect()
		except ssl.SSLCertVerificationError:
			timer.cancel()
			connection.close()
			raise PictureError("certificate") from None
		except (OSError, ValueError):
			timer.cancel()
			connection.close()
			if time.monotonic() >= deadline:
				raise PictureError("timeout") from None
			continue
		return connection, timer
	raise failure


def _ask(place, deadline, look_up):
	"""The answer of `place`'s server to a GET of it: (connection, response, timer); the body is still to be read."""
	connection, timer = _connect(place, deadline, look_up)
	try:
		connection.sock.settimeout(min(IO, max(deadline - time.monotonic(), 0.1)))
		connection.request(
			"GET",
			place.target,
			headers={
				"User-Agent": USER_AGENT,
				"Accept": ACCEPT,
				"Accept-Encoding": "identity",
				"Connection": "close",
			},
		)
		return connection, connection.getresponse(), timer
	except (http.client.HTTPException, OSError, ValueError):
		timer.cancel()
		connection.close()
		raise PictureError("timeout" if time.monotonic() >= deadline else "broken") from None


def _read(response, deadline):
	"""The body of `response`, MAX_BYTES at most, and all of what the server said it would send."""
	length = (response.getheader("Content-Length") or "").strip()
	# A body sent in chunks has no length of its own: what it says beside them doesn't count (RFC 9112).
	length = int(length) if length.isascii() and length.isdigit() and not response.chunked else None
	if length is not None and length > MAX_BYTES:
		raise PictureError("too_large")
	body = bytearray()
	while True:
		if time.monotonic() >= deadline:
			raise PictureError("timeout")
		chunk = response.read(min(CHUNK, MAX_BYTES + 1 - len(body)))
		if not chunk:
			# An end that the picture's timer made is not the end of the picture.
			if time.monotonic() >= deadline:
				raise PictureError("timeout")
			# Nor one that comes before what was said: http.client lets a cut connection end a body short.
			if length is not None and len(body) < length:
				raise PictureError("broken")
			return bytes(body)
		body += chunk
		if len(body) > MAX_BYTES:
			raise PictureError("too_large")


def _retry_after(value):
	value = (value or "").strip()
	wait = float(value) if value.isascii() and value.isdigit() else RETRY_WAIT
	return min(max(wait, RETRY_WAIT), MAX_RETRY_WAIT)


def fetch(url, look_up=_look_up):
	"""The picture at `url`, an address a message gave: (its bytes, its kind), or PictureError. It blocks for PATIENCE
	at most."""
	deadline = time.monotonic() + PATIENCE
	place = address(url)
	redirects, asked_again, pause = 0, False, 0.0
	while True:
		if pause:
			time.sleep(pause)
			pause = 0.0
		connection, response, timer = _ask(place, deadline, look_up)
		try:
			status = response.status
			if status in REDIRECTS:
				redirects += 1
				if redirects > MAX_REDIRECTS:
					raise PictureError("redirects")
				location = response.getheader("Location")
				if not location:
					raise PictureError("status", status)
				place = follow(place, location)
				continue
			if status in (429, 503) and not asked_again:
				asked_again, pause = True, _retry_after(response.getheader("Retry-After"))
				if time.monotonic() + pause >= deadline:
					raise PictureError("status", status)
				continue
			if not 200 <= status < 300:
				raise PictureError("status", status)
			body = _read(response, deadline)
			codings = response.headers.get_all("Content-Encoding") or []
		except (http.client.HTTPException, OSError, ValueError):
			raise PictureError("timeout" if time.monotonic() >= deadline else "broken") from None
		finally:
			timer.cancel()
			connection.close()
		body = unpack(body, ",".join(codings), deadline)
		kind = picture_kind(body)
		if kind is None:
			raise PictureError("not_picture")
		return body, kind


def unpack(body, coding, deadline=None):
	"""A body as it was before it was packed (`coding`: what its Content-Encoding says), MAX_BYTES at most however
	little went in, and no later than `deadline` (the picture's time: unpacking is part of it)."""
	deadline = time.monotonic() + PATIENCE if deadline is None else deadline
	# Applied in the order they are written, so undone from the last.
	codings = [c.strip().lower() for c in coding.split(",") if c.strip() and c.strip().lower() != "identity"]
	if len(codings) > MAX_CODINGS:
		raise PictureError("packed")
	for c in reversed(codings):
		if c in ("gzip", "x-gzip"):
			# Some servers say so of a body they send as it is.
			if body.startswith(b"\x1f\x8b"):
				body = _inflate(body, 31, deadline)
		elif c == "deflate":
			# zlib's wrapping by the book, and bare deflate from servers that took the name at its word.
			try:
				body = _inflate(body, 15, deadline)
			except PictureError as e:
				if e.kind != "packed":
					raise
				body = _inflate(body, -15, deadline)
		else:
			raise PictureError("packed")
	return body


def _inflate(data, wbits, deadline):
	"""Everything `data` unpacks to (each member of a gzip stream in turn, MAX_MEMBERS of them at most), when that is
	no more than MAX_BYTES and done before `deadline`."""
	out = bytearray()
	members = 0
	while data:
		members += 1
		if members > MAX_MEMBERS:
			raise PictureError("packed")
		if time.monotonic() >= deadline:
			raise PictureError("timeout")
		unpacker = zlib.decompressobj(wbits)
		try:
			out += unpacker.decompress(data, MAX_BYTES + 1 - len(out))
		except zlib.error:
			raise PictureError("packed") from None
		# A few bytes can unpack to a great many: no more than the limit is ever taken out.
		if len(out) > MAX_BYTES or unpacker.unconsumed_tail:
			raise PictureError("too_large")
		if not unpacker.eof:
			raise PictureError("packed")
		data = unpacker.unused_data if wbits == 31 else b""
	return bytes(out)


def picture_kind(data):
	"""The kind of picture `data` is by its own bytes (image/png, image/jpeg, image/gif, image/webp), or None."""
	if data.startswith(b"\x89PNG\r\n\x1a\n"):
		return "image/png"
	if data.startswith(b"\xff\xd8\xff"):
		return "image/jpeg"
	if data[:6] in (b"GIF87a", b"GIF89a"):
		return "image/gif"
	if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
		return "image/webp"
	return None


# ---------------------------------------------------------------------------------------------------------------
# The relay
# ---------------------------------------------------------------------------------------------------------------


def _reason(error):
	"""The relay's status for `error`, and what the person reads: MailCraft shows it where the picture would have been.
	Never a 401 or a 403, which the page takes for its token refused."""
	kind, status = error.kind, error.status
	if kind == "address":
		return 400, _("it is not the address of a picture on the web")
	if kind == "not_public":
		return 400, _("its address does not lead to the public internet")
	if kind == "lookup":
		return 502, _("its server could not be found")
	if kind == "connect":
		return 502, _("its server could not be reached")
	if kind == "certificate":
		return 502, _("its server's certificate is not valid")
	if kind == "broken":
		return 502, _("the connection broke before it was all there")
	if kind == "timeout":
		return 504, _("it took too long")
	if kind == "redirects":
		return 502, _("it was sent on too many times")
	if kind == "too_large":
		return 413, _("it is larger than 8 MB")
	if kind == "packed":
		return 502, _("it came packed in a way that can't be read")
	if kind == "not_picture":
		return 415, _("what came is not a picture")
	if status in (401, 403):
		return 502, _("the server won't hand it out ({0})").format(status)
	if status in (404, 410):
		return 502, _("it is no longer there ({0})").format(status)
	if status == 429:
		return 502, _("the server is being asked too often just now ({0})").format(status)
	if status and 500 <= status <= 599:
		return 502, _("the server has trouble of its own ({0})").format(status)
	if status:
		return 502, _("the server answered {0} instead of a picture").format(status)
	return 502, _("the download failed")


def _problem(status, detail, retry=False):
	"""A failure, as the JMAP facade says one (RFC 7807): MailCraft reads its `detail`."""
	response = Response(
		json.dumps({"type": "about:blank", "status": status, "detail": detail}, separators=(",", ":")),
		status=status,
		content_type="application/json",
	)
	if retry:
		response.headers["Retry-After"] = "1"
	return response


def _slots():
	"""How many pictures the bench fetches at once: what the site's configuration says (`neomail_picture_slots`), else a
	third of the web workers (a worker waits with each one), one at least."""
	configured = cint(frappe.conf.get("neomail_picture_slots"))
	if configured > 0:
		return configured
	return max(1, (cint(frappe.conf.get("gunicorn_workers")) or 3) // 3)


def _take_turn():
	"""A turn among the bench's pictures on their way, or None while they are all taken."""
	cache = frappe.cache()
	holder = secrets.token_hex(8)
	now = time.time()
	pipe = cache.pipeline()
	pipe.zremrangebyscore(FLYING, "-inf", now - FLYING_STALE)
	pipe.zadd(FLYING, {holder: now})
	pipe.expire(FLYING, 2 * FLYING_STALE)
	pipe.zrank(FLYING, holder)
	rank = pipe.execute()[-1]
	if rank is not None and rank < _slots():
		return holder
	cache.zrem(FLYING, holder)
	return None


def _give_back(holder):
	frappe.cache().zrem(FLYING, holder)


def _spent_keys(user):
	cache = frappe.cache()
	return cache.make_key(f"neomail-pictures:{user}:count"), cache.make_key(f"neomail-pictures:{user}:bytes")


def _may_fetch(user):
	"""Whether `user` may fetch one more picture in this window: fewer than MAX_PICTURES fetched, and no more than
	MAX_WINDOW_BYTES taken."""
	count, taken = frappe.cache().mget(_spent_keys(user))
	return int(count or 0) < MAX_PICTURES and int(taken or 0) <= MAX_WINDOW_BYTES


def _count(user, pictures=0, size=0):
	"""What `user` fetched counts in this window: a picture once it has its turn (a request answered "busy" doesn't),
	its bytes once they came."""
	count_key, bytes_key = _spent_keys(user)
	pipe = frappe.cache().pipeline()
	for key, more in ((count_key, pictures), (bytes_key, size)):
		if more:
			pipe.set(key, 0, ex=WINDOW, nx=True)
			pipe.incrby(key, more)
	pipe.execute()


def relay(url, user):
	"""What mailcraft_jmap.picture answers `user`, who asked for the picture at `url`: its bytes as their own kind,
	or a failure whose `detail` the person reads (in their language). Nothing escapes it: an error Frappe caught would
	be logged with the request's form, the address with it."""
	try:
		return _relay(url, user)
	except Exception as e:
		failed(e)
		return _problem(502, _("the download failed"))


def failed(error):
	"""Log an error of the relay by its kind and where it happened: not its words, which may quote the address
	(mailcraft_jmap.log_quietly)."""
	from frappe_webmail.mailcraft_jmap import log_quietly

	log_quietly("NeoMail: a picture could not be fetched", error)


def _relay(url, user):
	# The request was signed in by its token after Frappe chose a language for a visitor: the person's own.
	frappe.local.lang = get_user_lang(user)
	if not _may_fetch(user):
		return _problem(
			429, _("so many pictures were downloaded in the last minutes that the next ones must wait")
		)
	holder = _take_turn()
	if holder is None:
		return _problem(503, _("too many pictures are being downloaded just now"), retry=True)
	try:
		_count(user, pictures=1)
		body, kind = fetch(url)
	except PictureError as e:
		return _problem(*_reason(e))
	finally:
		_give_back(holder)
	_count(user, size=len(body))
	response = Response(body, status=200, content_type=kind)
	# A stranger's bytes: nothing reads them as anything but the picture they are.
	response.headers["X-Content-Type-Options"] = "nosniff"
	response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
	return response
