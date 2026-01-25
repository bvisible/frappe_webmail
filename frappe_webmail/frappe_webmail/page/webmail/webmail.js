/**
 * Webmail Desk Page
 *
 * This page provides the webmail interface within Frappe Desk.
 */

frappe.pages['webmail'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Webmail',
		single_column: true
	});

	// Store references
	wrapper.page = page;

	// Hide the page header for full-screen webmail experience
	const pageHead = wrapper.querySelector('.page-head');
	if (pageHead) {
		pageHead.style.display = 'none';
	}

	// Reduce padding on page body container
	const pageBody = wrapper.closest('.container.page-body');
	if (pageBody) {
		pageBody.style.padding = '15px';
	}

	// Create container for Vue app
	const container = document.createElement('div');
	container.id = 'webmail-app';
	container.className = 'webmail-container';
	container.style.cssText = 'height: calc(100vh - 60px); overflow: hidden;';

	page.main.html('').append(container);

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
		setTimeout(function() {
			if (frappe.webmail) {
				frappe.webmail.init(container);
			}
		}, 1000);
	}
};

frappe.pages['webmail'].on_page_hide = function(wrapper) {
	// Clean up when navigating away
	if (frappe.webmail) {
		frappe.webmail.destroy();
	}
};
