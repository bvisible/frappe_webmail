// Invented mailboxes, people, messages and Drive folders for the bench (harness.js). No real person, company or
// address: example.com and example.ch only. The shapes are those of the server methods they stand for.

const today = new Date();
const at = (daysAgo, h, m) => {
	const d = new Date(today);
	d.setDate(d.getDate() - daysAgo);
	d.setHours(h, m, 0, 0);
	return d.toISOString();
};

const ME = "camille.favre@example.ch";

export const ACCOUNTS = [
	{
		name: ME,
		email: ME,
		sender_name: "Camille Favre",
		auth_type: "Password",
		user: ME,
		shared_with: ["luc.bernard@example.ch"],
	},
	{
		name: "info@example.ch",
		email: "info@example.ch",
		sender_name: "Info",
		auth_type: "Password",
		user: "admin@example.ch",
		is_shared: true,
	},
	{
		name: "compta@example.ch",
		email: "compta@example.ch",
		sender_name: "Comptabilité",
		auth_type: "Password",
		user: "admin@example.ch",
		is_shared: true,
	},
];

const FOLDER_NAMES = [
	"INBOX",
	"Sent",
	"Drafts",
	"Archive",
	"Trash",
	"Junk",
	"Clients",
	"Fournisseurs",
	"Fournisseurs/2026",
];
export const FOLDERS = FOLDER_NAMES.map((name) => ({
	name,
	delimiter: "/",
	flags:
		name === "Sent"
			? ["\\Sent"]
			: name === "Drafts"
			? ["\\Drafts"]
			: name === "Trash"
			? ["\\Trash"]
			: name === "Junk"
			? ["\\Junk"]
			: name === "Archive"
			? ["\\Archive"]
			: [],
	selectable: true,
}));

export const COUNTS = {
	INBOX: { unseen: 12, messages: 240 },
	Sent: { unseen: 0, messages: 518 },
	Drafts: { unseen: 1, messages: 1 },
	Archive: { unseen: 0, messages: 1290 },
	Trash: { unseen: 0, messages: 8 },
	Junk: { unseen: 2, messages: 2 },
	Clients: { unseen: 0, messages: 64 },
	Fournisseurs: { unseen: 3, messages: 120 },
	"Fournisseurs/2026": { unseen: 0, messages: 41 },
};

const message = (
	uid,
	from_name,
	from_email,
	subject,
	date,
	seen,
	has_attachments,
	flagged = false
) => ({
	uid,
	subject,
	from_name,
	from_email,
	to: ME,
	date,
	seen,
	flagged,
	answered: false,
	forwarded: false,
	nora_seen: false,
	has_attachments,
	size: 20480,
});

export const EMAILS = [
	message(
		118,
		"Exemple Sanitaire SA",
		"compta@sanitaire.example.ch",
		"Facture 2026-118 — chaudière 24 kW",
		at(0, 10, 42),
		false,
		true
	),
	message(
		117,
		"Marc Rey",
		"marc.rey@example.ch",
		"Re: Devis chaudière",
		at(0, 9, 15),
		false,
		false
	),
	message(
		116,
		"Atelier Démo",
		"contact@atelier.example.ch",
		"Plans de la cuisine — version 3",
		at(1, 16, 5),
		true,
		true
	),
	message(
		115,
		"Banque Exemple",
		"noreply@banque.example.ch",
		"Votre relevé de septembre",
		at(1, 8, 30),
		true,
		true
	),
	message(
		114,
		"Luc Bernard",
		"luc.bernard@example.ch",
		"Planning de la semaine prochaine",
		at(3, 17, 48),
		true,
		false,
		true
	),
	message(
		113,
		"Nora",
		"nora@example.ch",
		"Résumé de la boîte compta@ — lundi",
		at(4, 7, 0),
		true,
		false
	),
];

const BODIES = {
	118: "<p>Bonjour,</p><p>Veuillez trouver ci-joint notre facture n° 2026-118 pour la livraison de la chaudière à condensation 24 kW (chantier de la rue des Pins).</p><p>Paiement à 30 jours. Meilleures salutations,<br>Exemple Sanitaire SA</p>",
	117: "<p>Bonjour,</p><p>Merci pour le devis, on part sur la condensation 24 kW. Pour la pose, est-ce que la semaine du 26 octobre vous irait ?</p><p>Meilleures salutations,<br>Marc Rey</p>",
	116: "<p>Bonjour,</p><p>Voici les plans mis à jour avec le nouvel évier.</p><p>Bonne journée,<br>Atelier Démo</p>",
	115: "<p>Votre relevé est disponible dans votre e-banking.</p>",
	114: "<p>Je serai sur le chantier de Pully mardi et mercredi, puis au dépôt jeudi.</p><p>Luc</p>",
	113: "<p>Trois factures fournisseurs sont arrivées dans compta@ ce week-end. Elles sont dans les documents scannés.</p>",
};

const ATTACHMENTS = {
	118: [
		{
			id: "0",
			filename: "Facture-2026-118.pdf",
			content_type: "application/pdf",
			size: 188416,
		},
		{ id: "1", filename: "Bon-de-livraison.jpg", content_type: "image/jpeg", size: 1258291 },
	],
	116: [
		{
			id: "0",
			filename: "Plans-cuisine-v3.pdf",
			content_type: "application/pdf",
			size: 2411724,
		},
	],
	115: [
		{ id: "0", filename: "Releve-2026-09.pdf", content_type: "application/pdf", size: 96256 },
	],
};

export function content(uid) {
	const head = EMAILS.find((e) => e.uid === Number(uid)) || EMAILS[0];
	return {
		...head,
		message_id: `<${head.uid}@example.ch>`,
		cc: "",
		reply_to: "",
		html: BODIES[head.uid] || "<p>…</p>",
		text: null,
		attachments: ATTACHMENTS[head.uid] || [],
	};
}

export const ATTACHMENT_ACTIONS = [
	{ key: "preview", label: "Aperçu", icon: "eye", kind: "client", group: "view", method: null },
	{
		key: "download",
		label: "Enregistrer sous…",
		icon: "download",
		kind: "client",
		group: "view",
		method: null,
	},
	{
		key: "save_to_drive",
		label: "Enregistrer dans le Drive…",
		icon: "cloud-upload",
		kind: "pick_folder",
		group: "neoffice",
		method: "frappe_webmail.attachments.save_attachment_to_drive",
	},
	{
		key: "document_scan",
		label: "Créer un document scanné",
		icon: "scan-line",
		kind: "now",
		group: "neoffice",
		method: "frappe_webmail.attachments.create_document_scan_from_attachment",
	},
	{
		key: "attach_to_document",
		label: "Joindre à un document Neoffice…",
		icon: "link",
		kind: "pick_document",
		group: "neoffice",
		method: "frappe_webmail.attachments.attach_to_document",
	},
	{
		key: "forward",
		label: "Transférer",
		icon: "forward",
		kind: "client",
		group: "share",
		method: null,
	},
];

const folder = (name, title, kind = "folder", children = true, path = null) => ({
	name,
	title,
	kind,
	can_write: kind !== "shared_with_me",
	has_children: children,
	path,
});

export const DRIVE = {
	roots: [
		folder("home", "Mon Drive", "home"),
		folder("drive", "Drive partagé", "shared_drive"),
		folder("__shared_with_me__", "Partagé avec moi", "shared_with_me"),
	],
	children: {
		home: [folder("admin", "Administratif", "folder", false), folder("clients", "Clients")],
		drive: [folder("compta", "Comptabilité"), folder("projets", "Projets", "folder", false)],
		__shared_with_me__: [folder("factures", "Factures fournisseurs 2026", "folder", false)],
		clients: [folder("pins", "Rue des Pins", "folder", false)],
		compta: [folder("factures", "Factures fournisseurs 2026", "folder", false)],
	},
	last: folder(
		"factures",
		"Factures fournisseurs 2026",
		"folder",
		false,
		"Drive partagé / Comptabilité / Factures fournisseurs 2026"
	),
};
