# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The icon of a sender's domain, for the round of NeoMail's rows (neomail_icons, 16.11.2026): asked of the domain's own site
at its two fixed places only, kept a week for the whole instance, never for a free mail service's domain. No site is reached:
`pictures.fetch` is a fake that notes the addresses it is asked.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_neomail_icons
"""

import base64
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_webmail import neomail_icons, pictures
from frappe_webmail.mailcraft_jmap import JmapError, _more_methods

DOMAIN = "icons-test-atelier.example"
SUB = "news.icons-test-atelier.example"
ICO = b"\x00\x00\x01\x00\x01\x00" + b"\x10" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
TOUCHED = (
	DOMAIN,
	"icons-test-nothing.example",
	"icons-test-large.example",
	"icons-test-busy.example",
	"gmail.com",
)


class FakeSites:
	"""`pictures.fetch`: the answers of the sites by address (bytes, or the kind of failure), and the addresses asked."""

	def __init__(self, answers):
		self.answers = answers
		self.asked = []
		self.patience = []
		self.max_bytes = []

	def __call__(self, url, look_up=None, patience=None, kind_of=None, max_bytes=None):
		self.asked.append(url)
		self.patience.append(patience)
		self.max_bytes.append(max_bytes)
		answer = self.answers.get(url, "status")
		if isinstance(answer, str):
			raise pictures.PictureError(answer, 404 if answer == "status" else None)
		if max_bytes is not None and len(answer) > max_bytes:
			raise pictures.PictureError("too_large")
		kind = (kind_of or pictures.picture_kind)(answer)
		if kind is None:
			raise pictures.PictureError("not_picture")
		return answer, kind


class TestNeomailIcons(FrappeTestCase):
	def setUp(self):
		self._forget()
		# The mailbox is the person's: what `_account` checks is mailcraft_jmap's, tested there.
		self.enterContext(patch.object(neomail_icons, "_account", lambda account_id: None))

	def tearDown(self):
		self._forget()

	def _forget(self):
		for domain in TOUCHED:
			frappe.cache().delete_value(neomail_icons._key(domain))

	def _ask(self, domain, sites):
		with patch.object(pictures, "fetch", sites):
			return neomail_icons.icon_get({"accountId": "A1", "domain": domain})

	def test_the_method_and_its_capability_are_offered(self):
		self.assertIn("NeomailSenderIcon/get", _more_methods())
		capabilities, account = neomail_icons.session_parts(None)
		self.assertIn(neomail_icons.ICONS, capabilities)
		self.assertEqual(account[neomail_icons.ICONS]["maxBytes"], neomail_icons.MAX_BYTES)

	def test_a_free_mail_services_domain_is_never_asked(self):
		for domain in (
			"gmail.com",
			"yahoo.fr",
			"yahoo.co.uk",
			"bluewin.ch",
			"outlook.com",
			"gmx.ch",
			"proton.me",
		):
			sites = FakeSites({})
			answer = self._ask(domain, sites)
			self.assertIsNone(answer["data"], domain)
			self.assertEqual(sites.asked, [], domain)
		for company in (DOMAIN, "mail.company.example", "gmail.company.example"):
			self.assertFalse(neomail_icons.free_mail(company), company)

	def test_what_is_no_domain_is_refused(self):
		for junk in (
			None,
			"",
			"localhost",
			"127.0.0.1",
			"a..b.example",
			"x" * 250 + ".example",
			"exa mple.example",
			"https://icons-test-atelier.example/x",
			"ada@icons-test-atelier.example",
			5,
			["x.example"],
		):
			with self.assertRaises(JmapError, msg=repr(junk)) as said:
				self._ask(junk, FakeSites({}))
			self.assertEqual(said.exception.type, "invalidArguments")

	def test_the_icon_is_asked_at_the_two_places_of_the_domains_site_and_kept_for_everyone(self):
		sites = FakeSites({f"https://{DOMAIN}/favicon.ico": ICO})
		answer = self._ask(DOMAIN.upper() + ".", sites)
		self.assertEqual(answer["domain"], DOMAIN)
		self.assertEqual(answer["type"], "image/x-icon")
		self.assertEqual(base64.b64decode(answer["data"]), ICO)
		self.assertEqual(
			sites.asked, [f"https://{DOMAIN}/apple-touch-icon.png", f"https://{DOMAIN}/favicon.ico"]
		)
		self.assertTrue(all(p is not None and p <= neomail_icons.TRY_PATIENCE for p in sites.patience))
		self.assertEqual(sites.max_bytes, [neomail_icons.MAX_BYTES] * 2, "no more taken than an icon")
		# Kept: asked again, nobody is.
		again = FakeSites({})
		self.assertEqual(self._ask(DOMAIN, again)["data"], answer["data"])
		self.assertEqual(again.asked, [])

	def test_a_name_under_a_site_is_asked_as_the_site_and_shares_its_icon(self):
		sites = FakeSites({f"https://{DOMAIN}/apple-touch-icon.png": PNG})
		answer = self._ask(SUB, sites)
		self.assertEqual((answer["domain"], answer["type"]), (SUB, "image/png"))
		self.assertEqual(sites.asked, [f"https://{DOMAIN}/apple-touch-icon.png"], "never the name under it")
		again = FakeSites({})
		self.assertEqual(self._ask(DOMAIN, again)["data"], answer["data"])
		self.assertEqual(again.asked, [], "the site's icon, kept once")
		self.assertEqual(neomail_icons.site_of("a.b.example.co.uk"), "example.co.uk")
		self.assertEqual(neomail_icons.site_of("mail.gmail.com"), "gmail.com")
		self.assertIsNone(self._ask("mail.gmail.com", FakeSites({}))["data"])

	def test_no_icon_is_kept_too_and_what_is_too_large_or_no_picture_is_none(self):
		nothing = "icons-test-nothing.example"
		sites = FakeSites({f"https://{nothing}/apple-touch-icon.png": b"<html>not found</html>"})
		self.assertIsNone(self._ask(nothing, sites)["data"])
		self.assertEqual(len(sites.asked), 2)
		again = FakeSites({f"https://{nothing}/favicon.ico": ICO})
		self.assertIsNone(self._ask(nothing, again)["data"], "a day before it is asked again")
		self.assertEqual(again.asked, [])
		large = "icons-test-large.example"
		big = PNG + b"\x00" * neomail_icons.MAX_BYTES
		sites = FakeSites({f"https://{large}/apple-touch-icon.png": big, f"https://{large}/favicon.ico": ICO})
		self.assertEqual(base64.b64decode(self._ask(large, sites)["data"]), ICO, "the large one passed over")

	def test_a_busy_bench_and_a_person_over_their_share_ask_nothing(self):
		busy = "icons-test-busy.example"
		sites = FakeSites({f"https://{busy}/favicon.ico": ICO})
		with (
			patch.object(pictures, "_take_turn", lambda: None),
			patch.object(neomail_icons, "WAIT_TURN", 0.3),
		):
			with self.assertRaises(JmapError) as said:
				self._ask(busy, sites)
		self.assertEqual(said.exception.type, "serverUnavailable")
		with patch.object(pictures, "_may_fetch", lambda user: False):
			with self.assertRaises(JmapError) as said:
				self._ask(busy, sites)
		self.assertEqual(
			said.exception.type, "serverUnavailable", "asked again later, not told there is none"
		)
		self.assertEqual(sites.asked, [])
		self.assertIsNone(neomail_icons._found(busy), "nothing learnt, nothing kept")

	def test_an_ico_is_an_icon_and_text_is_none(self):
		self.assertEqual(neomail_icons.icon_kind(ICO), "image/x-icon")
		self.assertEqual(neomail_icons.icon_kind(PNG), "image/png")
		self.assertIsNone(neomail_icons.icon_kind(b"<svg/>"))
		self.assertIsNone(neomail_icons.icon_kind(b"\x00\x00\x01\x00"))

	def test_a_body_is_taken_no_further_than_its_limit(self):
		class Answer:
			chunked = False

			def __init__(self, body, length=None):
				self.body, self.length = body, length

			def getheader(self, name):
				return self.length

			def read(self, size):
				taken, self.body = self.body[:size], self.body[size:]
				return taken

		far = time.monotonic() + 5
		self.assertEqual(pictures._read(Answer(b"x" * 10), far, limit=10), b"x" * 10)
		for answer in (Answer(b"x" * 11), Answer(b"x" * 5, length="11")):
			with self.assertRaises(pictures.PictureError) as said:
				pictures._read(answer, far, limit=10)
			self.assertEqual(said.exception.kind, "too_large")
		self.assertEqual(len(pictures._read(Answer(b"x" * 11), far)), 11, "the pictures' own limit otherwise")
