/**
 * Webmail Desk Page
 *
 * This page provides the webmail interface within Frappe Desk. Where NeoMail is in the desk for the person
 * (`frappe.boot.neomail_in_desk`, page/neomail/neomail.py), it gives way to it: the page leads to /app/neomail with what
 * its address asked (a message, a folder, a new message), in place of itself in the history, and builds nothing; only
 * its signatures (?signatures=1) stay here, where they are written. A load of the address is led there by the server
 * already (neomail.lead_to_neomail); this is the desk's own navigation (its menu, its links).
 */

// The rule of where the webmail's addresses lead, shared with NeoMail's page (window.neomailHost.deskAddress): Frappe
// puts the file in place of the next line when it serves this script (render_include). The line stays a comment for
// linters; the file's own first line is a comment too, so the line Frappe leaves behind is one.
// {% include "frappe_webmail/public/js/neomail_host.js" %}

// Auto-collapse the NeoCockpit menu while the webmail is open: the mailbox needs
// the width far more than the module tree does (folders + list + reader + soon an
// agent panel). The cockpit exposes no API for this — only its own toggle button —
// and it persists the choice to localStorage. So we click the button, put the
// user's real preference back in storage right after (other pages keep their
// layout on reload), and re-expand on the way out only if WE collapsed it.
const webmail_cockpit = {
	collapsed_by_us: false,
	side() {
		return document.querySelector(".nc-side");
	},
	toggle_button() {
		return document.querySelector(".nc-side .nc-collapse");
	},
	restore_preference(saved) {
		try {
			if (saved === null) localStorage.removeItem("neocockpit-pinned");
			else localStorage.setItem("neocockpit-pinned", saved);
		} catch (e) {
			/* storage unavailable — nothing to restore */
		}
	},
	collapse(attempt = 0) {
		const side = this.side();
		const btn = this.toggle_button();
		if (!side || !btn) {
			// Direct load of /app/webmail: the cockpit may mount after the page.
			if (attempt < 10) setTimeout(() => this.collapse(attempt + 1), 300);
			return;
		}
		if (!side.classList.contains("expanded")) return;
		let saved = null;
		try {
			saved = localStorage.getItem("neocockpit-pinned");
		} catch (e) {
			saved = null;
		}
		btn.click();
		this.collapsed_by_us = true;
		// The cockpit's effect writes "false" on the next render — undo that write
		// so the forced collapse never becomes the user's stored preference.
		setTimeout(() => this.restore_preference(saved), 60);
		setTimeout(() => this.restore_preference(saved), 400);
	},
	restore() {
		if (!this.collapsed_by_us) return;
		this.collapsed_by_us = false;
		const side = this.side();
		const btn = this.toggle_button();
		// The user may have re-expanded it themselves meanwhile: then leave it.
		if (!side || !btn || !side.classList.contains("collapsed")) return;
		btn.click();
	},
};

// A cockpit that draws a page's navigation (window.NeoCockpit.setPageNav, Neodesk plan W1) gets the webmail's
// folders (Webmail.vue lends them): it is not folded any more, there is no second sidebar to make room for.
const webmail_lends_nav = () => Boolean(window.NeoCockpit && window.NeoCockpit.setPageNav);

// Where NeoMail is in the desk for the person, the webmail leads there: true when it does (the page then builds
// nothing). Done once the desk has finished showing this page, so that NeoMail's takes its place, its address
// replacing this one in the history (the back button goes to the page before).
// Once for both the page's load and its show, which the desk calls one after the other.
let webmail_leading = false;
const webmail_leads_to_neomail = () => {
	if (!(frappe.boot && frappe.boot.neomail_in_desk && window.neomailHost)) return false;
	const target = window.neomailHost.deskAddress(window.location.search);
	if (!target) return false;
	if (!webmail_leading) {
		webmail_leading = true;
		setTimeout(() => {
			webmail_leading = false;
			if ((frappe.get_route() || [])[0] !== "webmail") return;
			frappe.route_flags.replace_route = true;
			frappe.router.push_state(target);
			frappe.route_flags.replace_route = false;
		}, 0);
	}
	return true;
};

frappe.pages["webmail"].on_page_load = function (wrapper) {
	if (webmail_leads_to_neomail()) return;
	webmail_build(wrapper);
};

function webmail_build(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Webmail"),
		single_column: true,
	});

	// Store references
	wrapper.page = page;

	if (!webmail_lends_nav()) webmail_cockpit.collapse();

	// Hide the page header for full-screen webmail experience
	const pageHead = wrapper.querySelector(".page-head");
	if (pageHead) {
		pageHead.style.display = "none";
	}

	// Prevent scroll on page - apply to html and body
	document.documentElement.style.overflow = "hidden";
	document.body.style.overflow = "hidden";

	// Reduce padding on page body container and prevent scroll.
	// NB: no navbar-based 100vh math here — under the NeoCockpit chrome the
	// navbar is gone and the content lives inside a framed panel, so the
	// only robust height is measured from the container's real position.
	const pageBody = document.querySelector(".container.page-body");
	if (pageBody) {
		pageBody.style.padding = "15px";
		pageBody.style.overflow = "hidden";
	}

	// Create container for Vue app
	const container = document.createElement("div");
	container.id = "webmail-app";
	container.className = "webmail-container";
	container.style.cssText = `overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--border-radius-lg);`;

	page.main.html("").append(container);

	// Size from the measured geometry — works with both the legacy navbar
	// and the cockpit chrome (framed panel). The Vue bundle pins heights
	// with !important rules tuned for the legacy 60px navbar, so we must
	// answer with inline !important (which outranks stylesheet !important).
	const size_container = () => {
		const panel = container.closest(".nc-panel, .content.page-container") || document.body;
		const bottom = Math.min(panel.getBoundingClientRect().bottom, window.innerHeight);
		if (pageBody) {
			const pb_top = pageBody.getBoundingClientRect().top;
			pageBody.style.setProperty(
				"height",
				`${Math.max(300, Math.round(bottom - pb_top))}px`,
				"important"
			);
		}
		const top = container.getBoundingClientRect().top;
		container.style.setProperty(
			"height",
			`${Math.max(300, Math.round(bottom - top))}px`,
			"important"
		);
	};
	requestAnimationFrame(size_container);
	setTimeout(size_container, 400);
	window.addEventListener("resize", frappe.utils.debounce(size_container, 150));

	// Initialize webmail when ready
	if (frappe.webmail) {
		frappe.webmail.init(container);
	} else {
		// Show placeholder
		container.innerHTML = `
			<div style="padding: 40px; text-align: center; color: #8d99a6;">
				<h3>📧 Webmail</h3>
				<p>Chargement de l'application...</p>
			</div>
		`;

		// Retry initialization
		setTimeout(function () {
			if (frappe.webmail) {
				frappe.webmail.init(container);
			}
		}, 1000);
	}
}

// Re-entering the page (route change back to /app/webmail) does not call
// on_page_load again — collapse the cockpit on every show.
frappe.pages["webmail"].on_page_show = function (wrapper) {
	if (webmail_leads_to_neomail()) return;
	// First reached for what stays the webmail's (its signatures), after a visit that led to NeoMail: built now
	if (!wrapper.page) webmail_build(wrapper);
	// An app that something unmounted (frappe.webmail.destroy) is mounted again on the way back: it stayed blank
	const container = wrapper && wrapper.querySelector("#webmail-app");
	if (container && frappe.webmail && frappe.webmail.mounted && !frappe.webmail.mounted()) {
		frappe.webmail.init(container);
	}
	if (webmail_lends_nav()) window.dispatchEvent(new Event("frappe_webmail:lend-nav"));
	else webmail_cockpit.collapse();
};

// NB: Frappe's page view wires on_page_load, on_page_show and refresh, never on_page_hide: nothing calls this when the
// desk leaves the page, and the app stays mounted under the hidden page (coming back is instant, the open message is
// where it was). What must not outlive the page is the folders it lends the cockpit: they carry this page's address
// (Webmail.vue, webmailRoute) and the cockpit draws them on that address only (pageNav.ts), 14.10.2026.
frappe.pages["webmail"].on_page_hide = function (wrapper) {
	webmail_cockpit.restore();
	// The cockpit draws its own navigation again
	if (webmail_lends_nav()) window.NeoCockpit.setPageNav(null);

	// Restore scroll on page when leaving
	document.documentElement.style.overflow = "";
	document.body.style.overflow = "";

	const pageBody = document.querySelector(".container.page-body");
	if (pageBody) {
		pageBody.style.overflow = "";
		pageBody.style.height = "";
	}

	// Clean up when navigating away
	if (frappe.webmail) {
		frappe.webmail.destroy();
	}
};
