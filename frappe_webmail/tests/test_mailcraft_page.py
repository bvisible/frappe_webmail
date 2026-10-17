# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""The /neomail address (NeoMail, the trial of our MailCraft fork with Nora, maintenance#1629, #1630): off unless the
site says so, and for the desk's people only; the former /mailcraft address redirects to it.

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_mailcraft_page
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

PORTAL = "webmail_mailcraft_portal@example.com"
STAFF = "webmail_mailcraft_staff@example.com"


def _make_user(email, desk):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	if desk:
		# A desk role makes the account a System User.
		user.append("roles", {"role": "Blogger"})
	else:
		user.user_type = "Website User"
	user.insert(ignore_permissions=True)


class TestMailCraftPage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_make_user(PORTAL, desk=False)
		_make_user(STAFF, desk=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _context(self, trial=1):
		from frappe_webmail.www import neomail

		context = frappe._dict()
		with patch.dict(frappe.local.conf, {"mailcraft_trial": trial}):
			neomail.get_context(context)
		return context

	def test_the_address_does_not_exist_unless_the_site_says_so(self):
		frappe.set_user(STAFF)
		with self.assertRaises(frappe.PageDoesNotExistError):
			self._context(trial=0)

	def test_a_visitor_signs_in_first(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			self._context()
		self.assertEqual(frappe.local.flags.redirect_location, "/login?redirect-to=/neomail")

	def test_a_portal_account_is_refused(self):
		frappe.set_user(PORTAL)
		with self.assertRaises(frappe.PermissionError):
			self._context()

	def test_the_former_address_leads_here_and_no_browser_keeps_it(self):
		from frappe.website.path_resolver import resolve_redirect

		frappe.cache.hdel("website_redirects", "default:mailcraft")
		with self.assertRaises(frappe.Redirect) as raised:
			resolve_redirect("mailcraft")
		self.assertEqual(frappe.local.flags.redirect_location, "/neomail")
		self.assertEqual(raised.exception.http_status_code, 302)

	def test_the_desk_gets_the_sample_mailbox_with_nora(self):
		from frappe_webmail.www import neomail

		frappe.set_user(STAFF)
		with patch.object(neomail, "nora_installed", return_value=False):
			self.assertEqual(
				self._context().build_url,
				"/assets/suite/craft/mailcraft/index.html?sample",
				"no Nora where the instance has none",
			)
		with patch.object(neomail, "nora_installed", return_value=True):
			context = self._context()
		self.assertEqual(context.build_url, "/assets/suite/craft/mailcraft/index.html?sample&nora")
		self.assertTrue(
			frappe.local.session.data.csrf_token, "the framed build's calls need the session's token"
		)
