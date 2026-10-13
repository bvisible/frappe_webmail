# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The line of text under a message's subject in the list (frappe_webmail/previews.py): which part it comes from,
how a body cut anywhere is read, what the list asks the server.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_previews
"""

import base64
import unittest

from imapclient.response_parser import parse_fetch_response

from frappe_webmail.previews import fetch_previews, preview_text, text_part


def structure(bodystructure):
	"""A BODYSTRUCTURE as imapclient hands it to the list, from the server's own words."""
	return parse_fetch_response([f"1 (UID 1 BODYSTRUCTURE {bodystructure})".encode()], uid_is_key=True)[1][
		b"BODYSTRUCTURE"
	]


PLAIN = '"text" "plain" ("charset" "utf-8") NIL NIL "quoted-printable" 120 3 NIL NIL NIL NIL'
HTML = '"text" "html" ("charset" "utf-8") NIL NIL "base64" 400 6 NIL NIL NIL NIL'
PDF = '"application" "pdf" ("name" "f.pdf") NIL NIL "base64" 1000 NIL ("attachment" ("filename" "f.pdf")) NIL NIL'


class TestTextPart(unittest.TestCase):
	def test_a_message_of_one_part_is_part_one(self):
		self.assertEqual(text_part(structure(f"({PLAIN})")), ("1", "plain", "quoted-printable", "utf-8"))

	def test_plain_text_wins_over_html_in_an_alternative(self):
		self.assertEqual(text_part(structure(f'(({HTML})({PLAIN}) "alternative" NIL NIL NIL NIL)'))[0], "2")

	def test_a_nested_part_has_a_dotted_path(self):
		found = text_part(
			structure(f'((({PLAIN})({HTML}) "alternative" NIL NIL NIL NIL)({PDF}) "mixed" NIL NIL NIL NIL)')
		)
		self.assertEqual(found, ("1.1", "plain", "quoted-printable", "utf-8"))

	def test_html_alone_is_taken(self):
		found = text_part(structure(f'(({HTML})({PDF}) "related" NIL NIL NIL NIL)'))
		self.assertEqual(found, ("1", "html", "base64", "utf-8"))

	def test_a_text_file_attached_is_not_the_message(self):
		attached = '"text" "plain" ("charset" "utf-8" "name" "notes.txt") NIL NIL "7bit" 50 2 NIL ("attachment" ("filename" "notes.txt")) NIL NIL'
		self.assertIsNone(text_part(structure(f'(({attached})({PDF}) "mixed" NIL NIL NIL NIL)')))

	def test_nothing_to_read(self):
		self.assertIsNone(text_part(None))
		self.assertIsNone(text_part(structure(f"({PDF})")))


class TestPreviewText(unittest.TestCase):
	def test_base64_cut_anywhere(self):
		body = base64.b64encode(b"Bonjour, veuillez trouver ci-joint notre facture.")
		self.assertEqual(
			preview_text(body[:-7], "plain", "base64", "utf-8"),
			"Bonjour, veuillez trouver ci-joint notre fact",
		)

	def test_quoted_printable_cut_in_an_escape_or_a_character(self):
		self.assertEqual(
			preview_text(b"Merci pour le caf=C3=A9 =C", "plain", "quoted-printable", "utf-8"),
			"Merci pour le café",
		)
		self.assertEqual(preview_text(b"Un d=C3=A9but =C3", "plain", "quoted-printable", "utf-8"), "Un début")

	def test_html_reads_as_its_words(self):
		html = b"<html><head><style>p{color:red}</style></head><body><p>Bonjour&nbsp;Marc,</p><p>Voici le <b>devis</b>.</p>"
		self.assertEqual(preview_text(html, "html", "7bit", "utf-8"), "Bonjour Marc, Voici le devis.")

	def test_an_unclosed_style_hides_nothing_but_itself(self):
		self.assertEqual(preview_text(b"<p>Salut</p><style>.a{", "html", "7bit", "utf-8"), "Salut")

	def test_the_quoted_lines_of_a_reply_are_left_out(self):
		text = b"Merci, c'est parfait.\r\n\r\n> Le devis est joint.\r\n> Bonne journ\xc3\xa9e"
		self.assertEqual(preview_text(text, "plain", "8bit", "utf-8"), "Merci, c'est parfait.")

	def test_a_long_text_is_cut_on_a_word(self):
		text = ("mot " * 60).encode()
		cut = preview_text(text, "plain", "7bit", "utf-8", length=30)
		self.assertTrue(cut.endswith("…"))
		self.assertLessEqual(len(cut), 31)
		self.assertNotIn("mo…", cut)

	def test_an_unknown_charset_reads_as_utf8(self):
		self.assertEqual(preview_text("Été".encode(), "plain", "8bit", "x-unknown"), "Été")


class FakeClient:
	def __init__(self, bodies):
		self.bodies = bodies
		self.fetches = []

	def fetch(self, uids, items):
		self.fetches.append((list(uids), items))
		(item,) = items
		path = item[item.index("[") + 1 : item.index("]")]
		return {uid: {f"BODY[{path}]<0>".encode(): self.bodies[uid]} for uid in uids}


class TestFetchPreviews(unittest.TestCase):
	def test_one_fetch_for_each_part_path_and_peek_only(self):
		client = FakeClient({1: b"Premier", 2: b"Deuxi=C3=A8me", 3: b"Troisi\xc3\xa8me"})
		structures = {
			1: structure('("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 7 1 NIL NIL NIL NIL)'),
			2: structure(f"({PLAIN})"),
			3: structure(
				f'((({PLAIN.replace("quoted-printable", "8bit")})({HTML}) "alternative" NIL NIL NIL NIL)({PDF}) "mixed" NIL NIL NIL NIL)'
			),
			4: structure(f"({PDF})"),
		}
		previews = fetch_previews(client, structures)
		self.assertEqual(previews, {1: "Premier", 2: "Deuxième", 3: "Troisième"})
		asked = {items[0]: uids for uids, items in client.fetches}
		self.assertEqual(asked, {"BODY.PEEK[1]<0.800>": [1, 2], "BODY.PEEK[1.1]<0.800>": [3]})
