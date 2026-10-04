# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""
Static guard for the translation contexts that keep our wording apart from other apps.

Frappe merges every installed app's French catalogue into one dictionary and the app
loaded last wins. Two apps giving the same bare English key different senses therefore
collide. A call site that passes a context is looked up as "msg:context" first, so our
PO entry (msgctxt + msgid) cannot be overridden by another app's bare key.

No site and no database needed. Run with:
    python3 -m unittest frappe_webmail.tests.test_semantic_contexts -v
"""

import json
import re
import unittest
from pathlib import Path

from babel.messages.pofile import read_po

APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent
BUNDLE = APP_DIR / "public" / "js" / "frappe_webmail.bundle.iife.js"

# (msgid, context, expected French, Vue source, source call-site regex, bundle call-site text)
JS_CASES = [
	(
		"Empty folder",
		"Folder action",
		"Vider le dossier",
		"frontend/src/components/FolderTree.vue",
		r'__\(\s*"Empty folder"\s*,\s*null\s*,\s*"Folder action"\s*\)',
		'__("Empty folder",null,"Folder action")',
	),
	(
		"Tips",
		"Search help",
		"Astuces",
		"frontend/src/pages/Webmail.vue",
		r'__\(\s*"Tips"\s*,\s*null\s*,\s*"Search help"\s*\)',
		'__("Tips",null,"Search help")',
	),
	(
		"Resume",
		"Continue",
		"Reprendre",
		"frontend/src/components/AgentPanel.vue",
		r"__\(\s*'Resume'\s*,\s*null\s*,\s*'Continue'\s*\)",
		'__("Resume",null,"Continue")',
	),
	(
		"Resume",
		"Continue",
		"Reprendre",
		"frontend/src/components/AutomationsPanel.vue",
		r"__\(\s*'Resume'\s*,\s*null\s*,\s*'Continue'\s*\)",
		'__("Resume",null,"Continue")',
	),
]

# A Select option of the Email Filter DocType: the desk form looks it up as "move:Email Filter".
OPTION_CASE = ("move", "Email Filter", "déplacer")


def _catalog(name):
	with open(APP_DIR / "locale" / name, "rb") as handle:
		return read_po(handle)


class TestSemanticContexts(unittest.TestCase):
	def test_every_context_entry_is_translated_in_the_po(self):
		catalog = _catalog("fr.po")
		for msgid, context, expected, *_rest in [*JS_CASES, (*OPTION_CASE,)]:
			with self.subTest(msgid=msgid, context=context):
				message = catalog.get(msgid, context)
				self.assertIsNotNone(message, f"missing PO entry {msgid!r} / {context!r}")
				self.assertEqual(message.string, expected)
				self.assertNotIn("fuzzy", message.flags)

	def test_every_context_entry_is_kept_by_the_pot(self):
		# `bench update-po-files` drops (obsoletes) a PO entry the POT no longer carries.
		catalog = _catalog("main.pot")
		for msgid, context, *_rest in [*JS_CASES, (*OPTION_CASE,)]:
			with self.subTest(msgid=msgid, context=context):
				self.assertIsNotNone(catalog.get(msgid, context))

	def test_no_vue_call_site_is_left_on_the_bare_key(self):
		for msgid, _context, _expected, source, pattern, _bundled in JS_CASES:
			with self.subTest(source=source):
				text = (REPO_DIR / source).read_text(encoding="utf-8")
				self.assertRegex(text, pattern)
				bare = re.compile(r"""__\(\s*(["'])""" + re.escape(msgid) + r"""\1\s*\)""")
				self.assertIsNone(bare.search(text), f"bare __({msgid!r}) still in {source}")

	def test_built_bundle_carries_the_contexts(self):
		# The bundle is built by hand and committed (no CI builds it): a source change
		# without a rebuild would leave the shipped code on the bare key.
		bundle = BUNDLE.read_text(encoding="utf-8")
		for msgid, context, _expected, _source, _pattern, bundled in JS_CASES:
			with self.subTest(msgid=msgid, context=context):
				self.assertIn(bundled, bundle)
				self.assertNotIn(f'__("{msgid}")', bundle)

	def test_email_filter_move_option_has_its_context_anchor(self):
		msgid, context, _expected = OPTION_CASE
		doctype = json.loads(
			(APP_DIR / "frappe_webmail" / "doctype" / "email_filter" / "email_filter.json").read_text(
				encoding="utf-8"
			)
		)
		action = next(f for f in doctype["fields"] if f["fieldname"] == "action_type")
		self.assertIn(msgid, action["options"].split("\n"))
		# The DocType extractor gives no context, so an anchor keeps the entry in the POT.
		anchors = (APP_DIR / "i18n_anchors.py").read_text(encoding="utf-8")
		self.assertRegex(anchors, r'_\(\s*"move"\s*,\s*context\s*=\s*"Email Filter"\s*\)')

	def test_email_filter_list_column_uses_the_doctype_context(self):
		# Frappe's Select formatter translates the raw value without a context.
		listview = (
			APP_DIR / "frappe_webmail" / "doctype" / "email_filter" / "email_filter_list.js"
		).read_text(encoding="utf-8")
		self.assertIn('frappe.listview_settings["Email Filter"]', listview)
		self.assertRegex(listview, r'__\(\s*value\s*,\s*null\s*,\s*"Email Filter"\s*\)')


if __name__ == "__main__":
	unittest.main()
