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

	// Prevent scroll on page - apply to html and body
	document.documentElement.style.overflow = 'hidden';
	document.body.style.overflow = 'hidden';

	// Get the navbar height dynamically
	const navbar = document.querySelector('.navbar');
	const navbarHeight = navbar ? navbar.offsetHeight : 48;

	// Reduce padding on page body container and prevent scroll
	const pageBody = document.querySelector('.container.page-body');
	if (pageBody) {
		pageBody.style.padding = '15px';
		pageBody.style.overflow = 'hidden';
		pageBody.style.height = `calc(100vh - ${navbarHeight}px)`;
	}

	// Calculate available height: viewport - navbar - padding (top + bottom)
	const paddingTotal = 30; // 15px top + 15px bottom
	const availableHeight = `calc(100vh - ${navbarHeight}px - ${paddingTotal}px)`;

	// Create container for Vue app
	const container = document.createElement('div');
	container.id = 'webmail-app';
	container.className = 'webmail-container';
	container.style.cssText = `height: ${availableHeight}; overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--border-radius-lg);`;

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
	// Restore scroll on page when leaving
	document.documentElement.style.overflow = '';
	document.body.style.overflow = '';

	const pageBody = document.querySelector('.container.page-body');
	if (pageBody) {
		pageBody.style.overflow = '';
		pageBody.style.height = '';
	}

	// Clean up when navigating away
	if (frappe.webmail) {
		frappe.webmail.destroy();
	}
};
