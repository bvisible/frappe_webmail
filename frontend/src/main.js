/**
 * Frappe Webmail Frontend Entry Point
 *
 * This module initializes the webmail application within Frappe Desk.
 */

import { createApp, h } from 'vue'
import Webmail from './pages/Webmail.vue'

// Store app instance for cleanup
let app = null

/**
 * Initialize the webmail application
 * @param {HTMLElement} container - The container element to mount the app
 */
function initWebmail(container) {
  if (app) {
    app.unmount()
  }

  app = createApp({
    render() {
      return h(Webmail)
    }
  })

  // Add global error handler
  app.config.errorHandler = (err, instance, info) => {
    console.error('Webmail Error:', err)
    console.error('Component:', instance)
    console.error('Info:', info)
    if (window.frappe) {
      frappe.toast({
        message: err.message || 'An error occurred',
        indicator: 'red'
      })
    }
  }

  app.mount(container)
}

/**
 * Destroy the webmail application
 */
function destroyWebmail() {
  if (app) {
    app.unmount()
    app = null
  }
}

// Export for Frappe integration
window.FrappeWebmail = {
  init: initWebmail,
  destroy: destroyWebmail
}

// Auto-initialize if container exists
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('webmail-app')
  if (container) {
    initWebmail(container)
  }
})

// Frappe page integration
if (typeof frappe !== 'undefined') {
  frappe.provide('frappe.webmail')

  frappe.webmail = {
    init: initWebmail,
    destroy: destroyWebmail
  }

  // Register the webmail page
  frappe.pages['webmail'] = {
    refresh: function(wrapper) {
      const container = wrapper.querySelector('#webmail-app') || wrapper
      initWebmail(container)
    }
  }
}

export { initWebmail, destroyWebmail }
