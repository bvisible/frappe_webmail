/**
 * Webmail Desk Page
 *
 * This page provides the webmail interface within Frappe Desk.
 */

frappe.pages["webmail"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Webmail",
		single_column: true,
	});

	// Store references
	wrapper.page = page;

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
			`${Math.max(300, Math.round(bottom - top - 15))}px`,
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

frappe.pages["webmail"].on_page_hide = function (wrapper) {
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
