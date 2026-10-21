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

/**
 * Whether the reader is on the webmail's desk page (or below it): the only place where its folders belong in the
 * cockpit. The app stays mounted under the hidden page and refreshes from the background (the mailboxes' unread mail,
 * every 60 s); lending from there replaced the navigation of the page in front, NeoMail's at /app/neomail (21.10.2026).
 */
export function onWebmailPage(win = window) {
	const route = webmailRoute(win);
	const path = ((win.location && win.location.pathname) || "").replace(/\/+$/, "");
	return path === route || path.startsWith(route + "/");
}
