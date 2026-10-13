// The menu of an attachment, as the server describes it (frappe_webmail.attachments.get_attachment_actions): the
// desk and the desktop app draw the same entries, with the same words, and an action the server adds in a kind the
// screens already play (client, now, pick_folder, pick_document) appears here without a line of screen code.

import { CloudUpload, Download, Eye, File, Forward, Link, ScanLine } from "lucide-vue-next";

export const ACTIONS_METHOD = "frappe_webmail.attachments.get_attachment_actions";
export const DOWNLOAD_METHOD = "frappe_webmail.attachments.download_attachment";

// The server names a Lucide icon; the desk draws Lucide
const ICONS = {
	eye: Eye,
	download: Download,
	"cloud-upload": CloudUpload,
	"scan-line": ScanLine,
	link: Link,
	forward: Forward,
};

let pending = null;

/** The actions of this person on this site, asked once per page. */
export function loadAttachmentActions(call = (opts) => frappe.call(opts)) {
	if (!pending) {
		pending = call({ method: ACTIONS_METHOD })
			.then((r) => (Array.isArray(r?.message) ? r.message : []))
			.catch(() => {
				pending = null;
				return [];
			});
	}
	return pending;
}

/** For the tests: forget what was asked. */
export function resetAttachmentActions() {
	pending = null;
}

/** ContextMenu items: one per action, a separator between the groups the server named. */
export function menuItems(actions) {
	const items = [];
	let group = null;
	for (const action of actions || []) {
		if (group !== null && action.group !== group) {
			items.push({ separator: true, id: `sep-${items.length}` });
		}
		group = action.group;
		items.push({
			id: action.key,
			label: action.label,
			icon: ICONS[action.icon] || File,
			action,
		});
	}
	return items;
}

/** The URL that streams one attachment: shown in the browser (inline) or saved. */
export function downloadUrl({ account, folder, uid, attachmentId, inline = false }) {
	const query = new URLSearchParams({
		account_name: account,
		folder,
		uid: String(uid),
		attachment_id: String(attachmentId),
		inline: inline ? "1" : "0",
	});
	return `/api/method/${DOWNLOAD_METHOD}?${query.toString()}`;
}

/** What a browser can show by itself; anything else is saved (the server forces it anyway). */
export function previewable(contentType) {
	return /^(application\/pdf|image\/(png|jpe?g|gif|webp)|text\/plain)$/i.test(contentType || "");
}
