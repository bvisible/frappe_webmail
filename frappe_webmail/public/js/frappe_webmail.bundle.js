/**
 * Frappe Webmail Bundle
 *
 * This file integrates the webmail Vue.js application with Frappe Desk.
 * The actual Vue components are built separately and included here.
 *
 * For development:
 *   cd frontend && npm install && npm run build
 *
 * This will compile the Vue components and output them here.
 */

(function() {
  'use strict';

  // Provide frappe.webmail namespace
  frappe.provide('frappe.webmail');

  /**
   * Initialize the webmail application
   * @param {HTMLElement|string} container - Container element or selector
   */
  frappe.webmail.init = function(container) {
    if (typeof container === 'string') {
      container = document.querySelector(container);
    }

    if (!container) {
      console.error('Webmail: Container not found');
      return;
    }

    // Check if Vue is available
    if (typeof Vue === 'undefined' && typeof window.Vue === 'undefined') {
      console.warn('Webmail: Vue.js not loaded. Loading from CDN...');
      // For production, Vue should be bundled with the app
    }

    // Initialize the app when FrappeWebmail is available
    if (window.FrappeWebmail) {
      window.FrappeWebmail.init(container);
    } else {
      console.warn('Webmail: Application not loaded. Run "npm run build" in frontend folder.');
      container.innerHTML = `
        <div style="padding: 40px; text-align: center; color: #8d99a6;">
          <h3>Webmail</h3>
          <p>L'application webmail n'est pas encore compilee.</p>
          <p>Executez les commandes suivantes:</p>
          <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; display: inline-block; text-align: left;">
cd apps/frappe_webmail/frontend
npm install
npm run build</pre>
          <p style="margin-top: 20px;">
            <a href="/app/webmail-account" class="btn btn-primary">
              Configurer un compte email
            </a>
          </p>
        </div>
      `;
    }
  };

  /**
   * Destroy the webmail application
   */
  frappe.webmail.destroy = function() {
    if (window.FrappeWebmail) {
      window.FrappeWebmail.destroy();
    }
  };

  /**
   * Register the webmail page with Frappe
   */
  frappe.pages['webmail'] = {
    onload: function(wrapper) {
      // Create page structure
      frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Webmail',
        single_column: true
      });

      this.wrapper = wrapper;
      this.page = wrapper.page;

      // Create container for Vue app
      const container = document.createElement('div');
      container.id = 'webmail-app';
      container.className = 'webmail-container';
      container.style.cssText = 'height: calc(100vh - 100px); overflow: hidden;';

      this.page.main.html('').append(container);

      // Initialize webmail
      frappe.webmail.init(container);
    },

    onhide: function() {
      // Clean up when navigating away
      frappe.webmail.destroy();
    }
  };

  // Also register for direct route access
  frappe.router.register_page('/webmail', frappe.pages['webmail']);

})();

// Add webmail to sidebar
frappe.after_ajax(function() {
  // Add to Module view if not already present
  if (frappe.boot && frappe.boot.user) {
    // Webmail is accessible to all logged-in users
  }
});
