/**
 * Frappe Webmail Frontend Entry Point
 *
 * This module provides the webmail Vue application.
 * The page routing is handled by frappe_webmail/page/webmail/webmail.js
 */

import { createApp, h } from "vue";
import Webmail from "./pages/Webmail.vue";
import { registerWebmailErrorHandlers } from "./utils/webmailErrors.js";

// Store app instance for cleanup
let app = null;

/**
 * Initialize the webmail application
 * @param {HTMLElement} container - The container element to mount the app
 */
function initWebmail(container) {
	// Register global handlers so IMAP/SMTP errors show friendly dialogs
	// instead of Frappe's raw "Server Error" traceback popup.
	registerWebmailErrorHandlers();

	if (app) {
		app.unmount();
	}

	app = createApp({
		render() {
			return h(Webmail);
		},
	});

	// Expose Frappe translation function to Vue components
	app.config.globalProperties.__ = window.__;

	// Add global error handler
	app.config.errorHandler = (err, instance, info) => {
		console.error("Webmail Error:", err);
		console.error("Component:", instance);
		console.error("Info:", info);
		if (window.frappe) {
			frappe.toast({
				message: err.message || "An error occurred",
				indicator: "red",
			});
		}
	};

	app.mount(container);
}

/**
 * Destroy the webmail application
 */
function destroyWebmail() {
	if (app) {
		app.unmount();
		app = null;
	}
}

// Register frappe.webmail namespace immediately when script loads
if (typeof frappe !== "undefined") {
	frappe.provide("frappe.webmail");
	frappe.webmail.init = initWebmail;
	frappe.webmail.destroy = destroyWebmail;
}

// Also expose on window for fallback
window.FrappeWebmail = {
	init: initWebmail,
	destroy: destroyWebmail,
};

// Export for module usage
export { initWebmail as init, destroyWebmail as destroy };
