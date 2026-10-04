// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

// The Select formatter Frappe uses for a list column translates the raw value
// WITHOUT a context, so "move" (the default filter action) came out as another
// app's word for the bare key. The form control already passes the DocType name
// as context; the list column does the same here.
frappe.listview_settings["Email Filter"] = {
	formatters: {
		action_type(value) {
			return frappe.utils.escape_html(__(value, null, "Email Filter"));
		},
	},
};
