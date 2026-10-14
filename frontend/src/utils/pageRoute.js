/**
 * The address of the webmail's desk page, the one the folders it lends the cockpit belong to.
 *
 * The cockpit draws a lent navigation only while the reader is on the page that lent it: the page is never told it
 * was left (Frappe wires `on_page_show`, no `on_page_hide`) and its mounted app goes on running, so it goes on
 * publishing from the background. Without this address, the folders stayed in the sidebar under « Mon espace »
 * (14.10.2026).
 */
export function webmailRoute(win = window) {
	const router = win.frappe && win.frappe.router;
	return router && typeof router.make_url === "function"
		? router.make_url(["webmail"])
		: "/app/webmail";
}
