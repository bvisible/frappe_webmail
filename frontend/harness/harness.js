// The webmail mounted alone, for looking at it: frappe.call answers from fixtures.js after a short delay, __()
// translates with the app's own locale/fr.po, the theme comes from an instance (index.html). Every call is logged
// in the console as « [harness] method args », so a screen that asks for something the bench does not know says so.
//
//   ?theme=dark       the dark theme
//   ?lang=en          the English strings (the msgids)
//   ?slow=1500        each answer takes that long (ms), to see the loading states
//   ?cockpit=<url>    the desk's cockpit (its built neocockpit.global.js) beside the webmail, which lends it its folders
import poText from "../../frappe_webmail/locale/fr.po?raw";
import {
	ACCOUNTS,
	ATTACHMENT_ACTIONS,
	COUNTS,
	DRIVE,
	EMAILS,
	FOLDERS,
	content,
} from "./fixtures.js";

const params = new URLSearchParams(location.search);
document.documentElement.dataset.theme = params.get("theme") === "dark" ? "dark" : "light";
const customTheme = params.get("theme_css");
if (customTheme) document.getElementById("theme-css").href = customTheme;

// ---- __() with the app's French catalogue ----------------------------------------------------------------------
function parsePo(text) {
	const catalog = new Map();
	const unquote = (line) => JSON.parse(line.slice(line.indexOf('"')));
	let entry = {};
	let field = null;
	const flush = () => {
		if (entry.msgid && entry.msgstr) {
			catalog.set(
				entry.msgctxt ? `${entry.msgctxt}\u0004${entry.msgid}` : entry.msgid,
				entry.msgstr
			);
		}
		entry = {};
		field = null;
	};
	for (const raw of text.split("\n")) {
		const line = raw.trim();
		if (!line) {
			flush();
		} else if (line.startsWith("#")) {
			continue;
		} else if (/^msg(ctxt|id|str)\s/.test(line)) {
			field = line.split(/\s/)[0];
			if (field === "msgctxt" && entry.msgid !== undefined) flush();
			entry[field] = unquote(line);
		} else if (line.startsWith('"') && field) {
			entry[field] += unquote(line);
		}
	}
	flush();
	return catalog;
}

const catalog = parsePo(poText);
const english = params.get("lang") === "en";
window.__ = (text, args, context) => {
	let out = text;
	if (!english) {
		out = (context && catalog.get(`${context}\u0004${text}`)) || catalog.get(text) || text;
	}
	if (Array.isArray(args))
		out = out.replace(/\{(\d+)\}/g, (m, i) => (args[i] === undefined ? m : args[i]));
	return out;
};

// ---- the server ---------------------------------------------------------------------------------------------------
const answers = {
	get_accounts: () => ACCOUNTS,
	get_folders: () => FOLDERS,
	get_folder_counts: () => COUNTS,
	get_capabilities: () => ({ nora: true }),
	get_ui_preferences: () => ({
		sidebar_width: 220,
		email_list_width: 380,
		collapsed_folders: [],
		sidebar_collapsed: null,
	}),
	save_ui_preferences: () => ({ success: true }),
	get_quota: () => ({ usage_kb: 2_200_000, limit_kb: 10_485_760 }),
	get_default_signature: () => ({ content: "<p>Camille Favre</p>" }),
	get_signatures: () => [],
	get_filters: () => [],
	get_folder_mapping: () => ({}),
	is_sender_trusted: () => ({ trusted: false }),
	get_emails: ({ folder }) => {
		const emails = folder === "INBOX" || !folder ? EMAILS : [];
		return { emails, total: emails.length, has_more: false };
	},
	search_emails: () => ({ emails: EMAILS.slice(0, 2), total: 2, has_more: false }),
	get_email_content: ({ uid }) => content(uid),
	set_flags: () => ({ success: true }),
	get_attachment_actions: () => ATTACHMENT_ACTIONS,
	get_drive_folders: ({ parent, search }) => {
		if (search) return { folders: [DRIVE.last], last: DRIVE.last };
		return { folders: parent ? DRIVE.children[parent] || [] : DRIVE.roots, last: DRIVE.last };
	},
	save_attachment_to_drive: ({ drive_folder }) => ({
		name: "f-1",
		url: "/drive/f/f-1",
		folder: drive_folder,
		message: `Enregistré dans le Drive : ${DRIVE.last.path}`,
	}),
	create_document_scan_from_attachment: () => ({
		name: "SCAN-20261013104200-A1B2C3",
		duplicate: false,
		url: "/app/document-scan/SCAN-20261013104200-A1B2C3",
		message: "Envoyé aux documents scannés : la lecture prend environ une minute",
	}),
	get_attachable_doctypes: () => [
		{ doctype: "Purchase Invoice", label: "Facture d'achat" },
		{ doctype: "Project", label: "Projet" },
		{ doctype: "Supplier", label: "Fournisseur" },
	],
	get_recent_documents: () => [
		{ value: "ACC-PINV-2026-00118", description: "Exemple Sanitaire SA" },
		{ value: "ACC-PINV-2026-00117", description: "Atelier Démo" },
	],
	search_documents: () => [
		{ value: "ACC-PINV-2026-00118", description: "Exemple Sanitaire SA" },
	],
	attach_to_document: ({ doctype, docname }) => ({
		url: `/app/x/${docname}`,
		message: `Joint à ${doctype} ${docname}`,
	}),
	get_recent_contacts: () => [],
	search_contacts: () => [],
	get_contact_by_email: () => null,
	// The supplier who sent the invoice is known in Neoffice; the others are not (board 7)
	get_sender_card: ({ email }) =>
		email === "compta@sanitaire.example.ch"
			? {
					doctype: "Supplier",
					name: "SUP-0007",
					title: "Exemple Sanitaire SA",
					kind: "Fournisseur",
					url: "/app/supplier/SUP-0007",
					invoices: 3,
			  }
			: null,
	quick_reply: () => ({
		success: true,
		draft_text:
			"Bonjour Monsieur Rey,\n\nMerci pour votre retour. La semaine du 26 octobre nous convient.\n\nMeilleures salutations,",
		draft_html:
			"<p>Bonjour Monsieur Rey,</p><p>Merci pour votre retour. La semaine du 26 octobre nous convient.</p><p>Meilleures salutations,</p>",
	}),
	get_messages: () => ({ messages: [] }),
	start_or_resume_thread: () => ({ thread: "harness" }),
};

const delay = Number(params.get("slow")) || 120;

function call(opts) {
	const method = opts.method || "";
	const args = opts.args || {};
	const short = method.split(".").pop();
	console.info("[harness]", method, args);
	return new Promise((resolve, reject) => {
		setTimeout(() => {
			const answer = answers[short];
			if (!answer) {
				console.warn("[harness] no answer for", method);
				resolve({ message: null });
				return;
			}
			try {
				const result = { message: answer(args) };
				if (typeof opts.callback === "function") opts.callback(result);
				resolve(result);
			} catch (error) {
				reject(error);
			}
		}, delay);
	});
}

function toast(arg) {
	const message = typeof arg === "string" ? arg : arg?.message;
	const box = document.createElement("div");
	// frappe.show_alert renders HTML (the « Open » link of an action): so does the bench, its own strings only
	box.innerHTML = message;
	document.getElementById("harness-toasts").appendChild(box);
	setTimeout(() => box.remove(), 4000);
}

window.frappe = {
	session: { user: ACCOUNTS[0].user, user_fullname: "Camille Favre" },
	boot: {
		lang: english ? "en" : "fr",
		user: { name: ACCOUNTS[0].user, email: ACCOUNTS[0].user },
	},
	provide(namespace) {
		let node = window;
		for (const part of namespace.split(".")) node = node[part] = node[part] || {};
		return node;
	},
	call,
	toast,
	show_alert: toast,
	msgprint: (m) => toast(typeof m === "string" ? m : m?.message),
	confirm: (message, yes) => {
		console.info("[harness] confirm:", message);
		yes?.();
	},
	datetime: { prettyDate: (d) => new Date(d).toLocaleString(english ? "en" : "fr-CH") },
	utils: {
		escape_html: (s) =>
			String(s ?? "").replace(
				/[&<>"']/g,
				(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
			),
	},
	markdown: (s) => s,
	set_route: (...route) => console.info("[harness] set_route", route),
	request: { on_error: () => {}, cleanup: () => {} },
	ui: {
		Dialog: class {
			constructor(options) {
				this.options = options;
			}
			show() {
				console.info("[harness] Dialog", this.options?.title);
			}
			hide() {}
		},
	},
	client: { set_value: async () => ({}), insert: async () => ({}), delete: async () => ({}) },
	ValidationError: class extends Error {},
};

// ---- ?cockpit=<url of neocockpit.global.js>: the desk's cockpit beside the webmail, which lends it its folders
// (window.NeoCockpit.setPageNav, Neodesk plan W1). Mounted before the webmail, which looks for it when it starts.
const cockpitUrl = params.get("cockpit");
if (cockpitUrl) {
	window.frappe.boot = {
		sidebar_pages: { pages: [] },
		app_data: [],
		user: {
			name: ACCOUNTS[0].user,
			email: ACCOUNTS[0].email,
			full_name: ACCOUNTS[0].sender_name,
		},
		user_info: {},
		surface_apps: [
			{
				name: "mail",
				title: "Mail",
				route: "/app/webmail",
				logo: "https://osiris.neoffice.me/assets/neoffice_theme/icons/streamline/envelope.svg",
			},
		],
	};
	await new Promise((resolve, reject) => {
		const script = document.createElement("script");
		script.src = cockpitUrl;
		script.onload = resolve;
		script.onerror = reject;
		document.head.append(script);
	});
	document.body.classList.add("with-cockpit");
	window.NeoCockpit.mount(document.getElementById("cockpit"), {
		env: "desk",
		layout: "sidebar",
		onNavigate: (route) => console.info("[harness] navigate", route),
	});
}

const { init } = await import("../src/main.js");
init(document.getElementById("app"));
