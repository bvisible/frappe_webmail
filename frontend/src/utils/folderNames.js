/**
 * The names of a mailbox's special folders, in the mail's own words.
 *
 * The bare words (« Inbox », « Sent », « Archive ») are translated by other apps of the site too, and the catalog
 * that loads last wins: the archive folder showed as « Archiver », a verb, in the list of folders and the cockpit's.
 * With their context (« Mail folder ») they are the mail's, and the same as Neodesk's (Réception, Envoyés,
 * Brouillons, Archives, Indésirables, Corbeille).
 */

// Frappe's __, read when a name is asked (the page may load before it); the extractor sees the calls below.
function __(message, replace, context) {
	return typeof window !== "undefined" && window.__
		? window.__(message, replace, context)
		: message;
}

/** The name of a special folder by its role (inbox, sent, drafts, trash, spam, archive), or null. */
export function folderName(role) {
	switch (role) {
		case "inbox":
			return __("Inbox", null, "Mail folder");
		case "sent":
			return __("Sent", null, "Mail folder");
		case "drafts":
			return __("Drafts", null, "Mail folder");
		case "trash":
			return __("Trash", null, "Mail folder");
		case "spam":
			return __("Spam", null, "Mail folder");
		case "archive":
			return __("Archive", null, "Mail folder");
		default:
			return null;
	}
}
