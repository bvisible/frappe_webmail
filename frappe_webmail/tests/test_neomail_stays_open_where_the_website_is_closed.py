# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""NeoMail is an application of the desk, not a page of the showcase: where the website is closed it stays open.

The website closes on an instance in maintenance (no showcase site) and on an entry offer without a website (Neoffice Go,
neoffice_theme's offer_gate). Both ask frappe's website_route_stays_open (Neoffice's fork, frappe/website/path_resolver.py)
which routes stay open, and every app declares its own in `website_maintenance_open_routes`. NeoMail was not declared:
on every Go the menu's « E-mail » led to /neomail, which answered 404 (neoffice-maintenance#3300). /neomail itself still
signs a visitor in and refuses a portal account (test_mailcraft_page).

Run with:
    bench --site prodclone.local run-tests --app frappe_webmail \
        --module frappe_webmail.tests.test_neomail_stays_open_where_the_website_is_closed
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestNeoMailStaysOpenWhereTheWebsiteIsClosed(FrappeTestCase):
	def setUp(self):
		super().setUp()
		try:
			from frappe.website.path_resolver import website_route_stays_open
		except ImportError:
			self.skipTest("a frappe without the maintenance veil of Neoffice's fork")
		self.stays_open = website_route_stays_open

	def test_neomail_and_its_former_address_stay_open(self):
		for route in ("neomail", "/neomail", "mailcraft"):
			self.assertTrue(self.stays_open(route), route)

	def test_the_webmail_stays_open_as_an_application_mounted_by_its_route_rule(self):
		self.assertTrue(self.stays_open("webmail"))
		self.assertTrue(self.stays_open("webmail/inbox"))

	def test_a_neighbour_of_neomail_is_not_opened_with_it(self):
		# A route opens itself and what follows it, never a longer word that starts like it.
		self.assertFalse(self.stays_open("neomailx"))
		self.assertFalse(self.stays_open("mailcraft-news"))
