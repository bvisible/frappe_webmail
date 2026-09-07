/**
 * Webmail Desk Page
 *
 * This page provides the webmail interface within Frappe Desk.
 */

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

frappe.pages["webmail"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Webmail",
		single_column: true,
	});

	// Store references
	wrapper.page = page;

	webmail_cockpit.collapse();

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
};

// Re-entering the page (route change back to /app/webmail) does not call
// on_page_load again — collapse the cockpit on every show.
frappe.pages["webmail"].on_page_show = function () {
	webmail_cockpit.collapse();
};

frappe.pages["webmail"].on_page_hide = function (wrapper) {
	webmail_cockpit.restore();

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
