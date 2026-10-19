// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

// The preview is drawn by the server (frappe_webmail.signatures.preview), from the form as it stands, saved or not:
// what the form shows is what people get, never a second drawing made in the browser.
frappe.ui.form.on("Email Signature Template", {
	setup: function (frm) {
		// One drawing once the changes stop, not one per key stroke
		frm.refresh_preview = frappe.utils.debounce(function () {
			draw_preview(frm);
		}, 500);

		// Any field of the template, and of its social links, draws the preview again
		frappe.model.on(frm.doctype, "*", function (fieldname, value, doc) {
			if (doc.name === frm.docname) frm.refresh_preview();
		});
		frappe.model.on("Email Signature Social Link", "*", function (fieldname, value, doc) {
			if (doc.parent === frm.docname) frm.refresh_preview();
		});
	},

	refresh: function (frm) {
		// The preview is written with the details of the person who is editing, until another is chosen. Set without
		// making the form unsaved: opening a template changes nothing in it.
		frm.set_value("preview_user", frappe.session.user, true, true);
		frm.trigger("enabled");
		frm.refresh_preview();
		show_font_names(frm);
	},

	enabled: function (frm) {
		frm.set_intro("");
		if (!frm.doc.enabled) {
			frm.set_intro(__("This template is not enabled: nobody gets it."), "orange");
		}
	},

	social_links_add: function (frm) {
		frm.refresh_preview();
	},

	social_links_remove: function (frm) {
		frm.refresh_preview();
	},
});

// A font's name is a name: shown as it is written. Frappe passes the options of a Select through the site's
// translations, where another app's « Georgia » is the country (« Géorgie »).
function show_font_names(frm) {
	const field = frm.get_field("font");
	if (!field || !field.$input) return;
	field.$input.find("option").each(function () {
		if (this.value) this.textContent = this.value;
	});
}

function draw_preview(frm) {
	const field = frm.get_field("preview_html");
	if (!field || !field.$wrapper) return;

	// Only the latest drawing is shown, whichever answer comes back first
	frm.preview_ticket = (frm.preview_ticket || 0) + 1;
	const ticket = frm.preview_ticket;

	frappe.call({
		method: "frappe_webmail.signatures.preview",
		args: { doc: frm.doc, user: frm.doc.preview_user || frappe.session.user },
		silent: true,
		callback: function (r) {
			if (ticket === frm.preview_ticket) show_preview(field.$wrapper, r.message);
		},
		error: function () {
			if (ticket === frm.preview_ticket) {
				show_preview_message(field.$wrapper, __("The preview could not be drawn."));
			}
		},
	});
}

function show_preview(wrapper, signature) {
	if (!signature || !signature.html) {
		show_preview_message(
			wrapper,
			__("This template says nothing for this person: everything it shows is empty or off.")
		);
		return;
	}

	// The signature is drawn in a frame of its own, so that the desk's styles do not reach it. Nothing runs in it,
	// whatever it holds (no allow-scripts); allow-same-origin only lets this page read its height, and lets a logo
	// that is a private file of the instance load with the person's session. A click on a link does nothing.
	const frame = document.createElement("iframe");
	frame.setAttribute("sandbox", "allow-same-origin");
	frame.setAttribute("title", __("Signature preview"));
	frame.style.cssText =
		"width: 100%; min-height: 140px; border: 1px solid var(--border-color);" +
		" border-radius: var(--border-radius); background: #fff;";
	frame.srcdoc =
		'<!doctype html><html><head><meta charset="utf-8"><base target="_blank">' +
		"<style>body { margin: 16px; background: #fff; }</style></head><body>" +
		signature.html +
		"</body></html>";
	frame.addEventListener("load", function () {
		try {
			frame.style.height = frame.contentDocument.documentElement.scrollHeight + "px";
		} catch (e) {
			// The height stays what it was
		}
	});

	const caption = document.createElement("div");
	caption.className = "text-muted small";
	caption.style.margin = "var(--margin-md) 0 var(--margin-xs)";
	caption.textContent = __("Plain text version");

	const text = document.createElement("pre");
	text.style.cssText = "white-space: pre-wrap; margin: 0; font-family: inherit;";
	text.textContent = signature.text || "";

	wrapper.empty().append(frame, caption, text);
}

function show_preview_message(wrapper, message) {
	const note = document.createElement("div");
	note.className = "text-muted";
	note.textContent = message;
	wrapper.empty().append(note);
}
