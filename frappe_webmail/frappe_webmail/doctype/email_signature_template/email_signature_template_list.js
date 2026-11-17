// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/* global frappe_webmail */

// The list of the company's signatures: the builder (public/js/signature_builder.js) shows them side by side, whom each
// reaches, and each as a person sends it.
frappe.listview_settings["Email Signature Template"] = {
	onload: function (listview) {
		listview.page.add_inner_button(__("Open the signature builder"), function () {
			frappe.require("/assets/frappe_webmail/js/signature_builder.js", function () {
				frappe_webmail.signature_builder.load_and_open({});
			});
		});
	},
};
