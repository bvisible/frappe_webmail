// An attachment in NeoMail, as the desk's page /app/neomail files it (frappe_webmail/frappe_webmail/page/neomail/
// neomail.js, with the helpers of frappe_webmail/public/js/neomail_host.js): the Drive, an editor, the scanned
// documents. Run against a made-up desk: its page wrapper, its dialogs and toasts, a frame NeoMail would be in, and a
// server that answers the page's calls (neomail_attachments.py, attachments.py).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(HERE, "../../frappe_webmail", path), "utf8");
const HOST = read("public/js/neomail_host.js");
const PAGE = read("frappe_webmail/page/neomail/neomail.js");

// The helpers alone, on a made-up window.
function helpers() {
	const win = { location: { origin: "https://erp.example.org" } };
	new Function("window", HOST)(win);
	return win.neomailHost;
}

// Just enough of jQuery for the page: html(), append(), and events with their namespace and target.
function $(el) {
	return {
		html(text) {
			el.innerHTML = text;
			return this;
		},
		append(node) {
			el.append(node);
			return this;
		},
		on(type, fn) {
			el.addEventListener("jq-" + type, (e) => fn({ namespace: e.detail, target: e.target }));
			return this;
		},
	};
}

// The markup Frappe's make_app_page gives a single-column page.
function make_app_page({ parent }) {
	parent.innerHTML = `<div class="page-head"></div><div class="container page-body"><div class="page-wrapper">
		<div class="page-content"><div class="layout-main-section"></div></div></div></div>`;
	return { main: $(parent.querySelector(".layout-main-section")) };
}

// Frappe's __: the word, then `replace` in its {0}, {1}…
const translate = (text, replace) =>
	Array.isArray(replace) ? text.replace(/\{(\d+)\}/g, (all, n) => (n in replace ? String(replace[n]) : all)) : text;

const HANDOVER = {
	build_url: "about:blank",
	host: {
		accounts: [{ email: "ada@example.org", secret: "token-1" }],
		language: "fr",
		attachments: ["drive", "scan", "edit"],
	},
	editors: ["docx", "pdf"],
	no_mailbox: false,
};
const MESSAGE = { account: "ada@example.org", email: "E7V31ZSU5CT1g" };
const INVOICE = { index: 1, count: 3, name: "Facture 118.pdf", size: 12_700, mime: "application/pdf", cid: "" };
const ROOTS = [
	{ name: "home-ada", title: "My Drive", kind: "home", can_write: true, has_children: true },
	{ name: "drive-root", title: "Shared Drive", kind: "shared_drive", can_write: false, has_children: true },
];
const LAST = { name: "folder-invoices", title: "Invoices", kind: "folder", can_write: true, has_children: false, path: "My Drive / Invoices" };
const CHILDREN = { "home-ada": [{ name: "folder-clients", title: "Clients", kind: "folder", can_write: true, has_children: false }] };
const SAVED = { name: "a1B2c3", file_name: "Facture 118.pdf", url: "/drive/f/a1B2c3", message: "Saved in the Drive: My Drive / Invoices" };

const json = (message, status = 200) =>
	status === 200
		? new Response(JSON.stringify({ message }))
		: new Response(JSON.stringify({ _server_messages: JSON.stringify([JSON.stringify({ message })]) }), { status });

let desk;

// The desk with the page loaded and shown and NeoMail's frame there. `server`: what the server answers the page's
// calls, by the method's name (an answer, a status for a refusal with `refused` as its words, or a function of what
// was sent); `handover`: what the page is handed.
async function open({ server = {}, handover = HANDOVER } = {}) {
	const heard = [];
	const listen = window.addEventListener.bind(window);
	vi.spyOn(window, "addEventListener").mockImplementation((type, fn, options) => {
		if (type === "message") heard.push(fn);
		return listen(type, fn, options);
	});
	const wrapper = document.createElement("div");
	wrapper.className = "content page-container";
	document.body.append(wrapper);
	const dialogs = [];
	const said = [];
	// The desk's dialog, as the page uses it: its HTML field a real element, its primary button's state kept
	class Dialog {
		constructor(options) {
			this.options = options;
			this.shown = false;
			this.disabled = false;
			this.fields_dict = {};
			for (const field of options.fields) {
				const element = document.createElement("div");
				document.body.append(element);
				this.fields_dict[field.fieldname] = { wrapper: element, $wrapper: { get: () => element } };
			}
			dialogs.push(this);
		}
		show() {
			this.shown = true;
		}
		hide() {
			this.shown = false;
			if (this.onhide) this.onhide();
		}
		disable_primary_action() {
			this.disabled = true;
		}
		get $wrapper() {
			const dialog = this;
			return { remove: () => (dialog.removed = true) };
		}
		enable_primary_action() {
			this.disabled = false;
		}
		picker() {
			return this.fields_dict.picker.wrapper;
		}
	}
	const frappe = {
		csrf_token: "csrf-1",
		boot: {},
		_messages: {},
		pages: { neomail: wrapper },
		router: { make_url: (parts) => "/app/" + parts.join("/") },
		ui: { make_app_page, Dialog },
		utils: {
			debounce: (fn) => fn,
			escape_html: (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
		},
		msgprint: (text) => said.push(["msgprint", text]),
		show_alert: (alert) => said.push(["alert", alert.message]),
	};
	const fetch = vi.fn(async (url, init) => {
		const address = String(url);
		const method = Object.keys(server).find((name) => address.includes(name));
		if (method) {
			const given = server[method];
			const body = init && init.body ? JSON.parse(init.body) : Object.fromEntries(new URL(address, "http://x").searchParams);
			const answer = typeof given === "function" ? await given(body) : given;
			return typeof answer === "number" ? json(server.refused || "Refused <b>here</b>", answer) : json(answer);
		}
		if (address.includes("hand_over")) return json(structuredClone(handover));
		return new Response("{}", { status: 404 });
	});
	new Function("window", HOST)(window);
	new Function("frappe", "$", "__", "fetch", PAGE)(frappe, $, translate, fetch);
	frappe.pages.neomail.on_page_load(wrapper);
	frappe.pages.neomail.on_page_show(wrapper);
	await vi.waitFor(() => expect(wrapper.querySelector("iframe")).toBeTruthy());
	const frame = wrapper.querySelector("iframe");
	Object.defineProperty(frame, "contentWindow", { value: { postMessage: () => {} } });
	const tell = (data) => heard.forEach((fn) => fn({ source: frame.contentWindow, origin: window.location.origin, data }));
	desk = { wrapper, frappe, fetch, tell, dialogs, said };
	return desk;
}

// What the page sent to one of the server's methods: its method, its CSRF token and its body.
const sent = (fetch, name) =>
	fetch.mock.calls
		.filter(([url]) => String(url).includes(name))
		.map(([, init]) => ({ method: init.method, csrf: init.headers["X-Frappe-CSRF-Token"], body: init.body && JSON.parse(init.body) }));
const rows = (dialog) => [...dialog.picker().querySelectorAll(".neomail-picker-row")];
const row = (dialog, title) => rows(dialog).find((r) => r.textContent.includes(title));
const settle = () => new Promise((go) => setTimeout(go, 20));

beforeEach(() => {
	window.happyDOM.settings.disableIframePageLoading = true;
});

afterEach(() => {
	window.happyDOM.settings.disableIframePageLoading = false;
	vi.restoreAllMocks();
	if (desk) desk.wrapper.remove();
	desk = null;
	delete window.mailcraftJmap;
	document.body.replaceChildren();
});

describe("what NeoMail asks of an attachment", () => {
	it("takes an action it offers, a message and a described file, and nothing else", () => {
		const { attachmentOf } = helpers();
		const asked = { type: "mailcraft:attachment", action: "drive", ...MESSAGE, attachment: { ...INVOICE, extra: "x" } };
		expect(attachmentOf(asked)).toEqual({ ...MESSAGE, action: "drive", attachment: INVOICE });
		// What is not of its kind is left out, a name too long is cut
		expect(attachmentOf({ ...asked, attachment: { index: 0, name: "a".repeat(5000), size: -3, mime: 7, count: "3" } }).attachment).toEqual({
			index: 0,
			count: null,
			name: "a".repeat(1024),
			size: null,
			mime: "",
			cid: "",
		});
		for (const wrong of [
			null,
			{ ...asked, action: "delete" },
			{ ...asked, action: undefined },
			{ ...asked, email: "M7" },
			{ ...asked, account: "nobody" },
			{ ...asked, attachment: null },
			{ ...asked, attachment: "Facture.pdf" },
			{ ...asked, attachment: { ...INVOICE, index: 1.5 } },
			{ ...asked, attachment: { ...INVOICE, index: "1" } },
			{ ...asked, attachment: { ...INVOICE, name: "  " } },
		]) {
			expect(attachmentOf(wrong)).toBeNull();
		}
	});

	it("shows a name without what would make it read otherwise", () => {
		const { fileLabel } = helpers();
		expect(fileLabel("Facture\u202egpj.exe")).toBe("Facturegpj.exe");
		expect(fileLabel("../../etc/passwd")).toBe("passwd");
		expect(fileLabel("C:\\temp\\a\u0007b\r\n.pdf")).toBe("ab.pdf");
		expect(fileLabel("")).toBe("attachment");
		expect(fileLabel("x".repeat(300)).length).toBe(140);
	});

	it("knows the Drive's editors by the extension, as products named in no language", () => {
		const { editorOf } = helpers();
		expect(editorOf("Lettre.DOCX")).toEqual({ extension: "docx", product: "NeoDoc" });
		expect(editorOf("Budget 2026.xlsx")).toEqual({ extension: "xlsx", product: "NeoGrille" });
		expect(editorOf("Pitch.pptx")).toEqual({ extension: "pptx", product: "NeoPrés" });
		expect(editorOf("Facture.pdf")).toEqual({ extension: "pdf", product: "NeoPDF" });
		for (const name of ["Lettre.doc", "pdf", "Facture.pdf\u202e.exe", "a.constructor", "a.__proto__"]) {
			expect(editorOf(name)).toBeNull();
		}
	});

	it("opens only a file or a folder of the Drive, and a scanned document by its name", () => {
		const { driveUrl, scanUrl, sizeLabel } = helpers();
		expect(driveUrl("/drive/f/a1B2c3_d-4")).toBe("/drive/f/a1B2c3_d-4");
		expect(driveUrl("/drive/d/folder-1")).toBe("/drive/d/folder-1");
		for (const wrong of [
			null,
			"",
			"/drive/f/",
			"/drive/f/../app",
			"/drive/f/a?b",
			"/drive/x/a",
			"//evil.example/drive/f/a",
			"https://evil.example/drive/f/a",
			"javascript:alert(1)",
		]) {
			expect(driveUrl(wrong)).toBeNull();
		}
		expect(scanUrl("SCAN-2026 <1>")).toBe("/app/document-scan/SCAN-2026%20%3C1%3E");
		expect(scanUrl("")).toBeNull();
		expect(scanUrl(7)).toBeNull();
		expect(sizeLabel(12_700)).toBe("12.4 KB");
		expect(sizeLabel(null)).toBe("");
	});
});

describe("Save to Drive…, from an attachment's menu", () => {
	const ASKED = { type: "mailcraft:attachment", action: "drive", ...MESSAGE, attachment: INVOICE };

	it("asks for a folder, starting at the one used last, and saves the file there", async () => {
		const server = {
			// A server that lists a folder inside itself draws it once
			get_drive_folders: (asked) => (asked.parent ? { folders: ROOTS } : { folders: ROOTS, last: LAST }),
			save_to_drive: SAVED,
		};
		const { tell, dialogs, fetch, said } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		const dialog = dialogs[0];
		expect(dialog.shown).toBe(true);
		expect(dialog.options.title).toBe("Save to the Drive");
		expect(dialog.options.primary_action_label).toBe("Save here");
		// The file, its size, the folder used last chosen already
		expect(dialog.picker().querySelector(".neomail-picker-file-name").textContent).toBe("Facture 118.pdf");
		expect(dialog.picker().querySelector(".neomail-picker-file-size").textContent).toBe("12.4 KB");
		const last = dialog.picker().querySelector(".neomail-picker-last");
		expect(last.hidden).toBe(false);
		expect(last.textContent).toContain("My Drive / Invoices");
		expect(last.classList.contains("is-chosen")).toBe(true);
		expect(dialog.disabled).toBe(false);
		// A folder the person may not file into is not chosen; it opens
		row(dialog, "Shared Drive").click();
		expect(last.classList.contains("is-chosen")).toBe(true);
		await vi.waitFor(() => expect(row(dialog, "Shared Drive").getAttribute("aria-expanded")).toBe("true"));
		expect(rows(dialog).map((r) => r.textContent)).toEqual(["▸My Drive", "▾Shared Drive", "▸My Drive"]);
		await dialog.options.primary_action();
		expect(sent(fetch, "save_to_drive")).toEqual([
			{
				method: "POST",
				csrf: "csrf-1",
				body: { ...MESSAGE, attachment: INVOICE, drive_folder: "folder-invoices", edit: 0 },
			},
		]);
		expect(dialog.shown).toBe(false);
		expect(said).toEqual([
			[
				"alert",
				'Saved in the Drive: My Drive / Invoices <a href="/drive/f/a1B2c3" target="_blank" rel="noopener">Open it</a>',
			],
		]);
	});

	it("opens a folder's subfolders, finds one by its name, and makes a new one", async () => {
		const server = {
			get_drive_folders: (asked) =>
				asked.parent
					? { folders: CHILDREN[asked.parent] || [] }
					: asked.search
					? { folders: [{ ...LAST, path: "My Drive / <b>Invoices</b>" }] }
					: { folders: ROOTS, last: null },
			create_drive_folder: (asked) => ({ name: "folder-new", title: asked.title, can_write: true, has_children: false }),
			save_to_drive: SAVED,
		};
		const { tell, dialogs, fetch } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		const dialog = dialogs[0];
		// Nothing chosen yet: nothing to save to
		expect(dialog.disabled).toBe(true);
		expect(dialog.picker().querySelector(".neomail-picker-last").hidden).toBe(true);
		row(dialog, "My Drive").click();
		await vi.waitFor(() => expect(row(dialog, "Clients")).toBeTruthy());
		expect(dialog.disabled).toBe(false);
		expect(row(dialog, "Clients").style.paddingLeft).toBe("26px");
		// A search: the folder with where it is, its words never markup
		const search = dialog.picker().querySelector(".neomail-picker-search");
		search.value = "Invo";
		search.dispatchEvent(new Event("input"));
		await vi.waitFor(() => expect(row(dialog, "Invoices")).toBeTruthy());
		expect(row(dialog, "Invoices").querySelector("small").textContent).toBe("My Drive / <b>Invoices</b>");
		expect(row(dialog, "Invoices").querySelector("b")).toBeNull();
		row(dialog, "Invoices").click();
		search.value = "";
		search.dispatchEvent(new Event("input"));
		// A new folder in the folder chosen, chosen in its turn
		const making = dialog.picker().querySelector(".neomail-picker-new");
		making.querySelector("button").click();
		const name = making.querySelector("input");
		expect(name.hidden).toBe(false);
		name.value = "Fournisseurs";
		name.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
		await vi.waitFor(() => expect(sent(fetch, "create_drive_folder").length).toBe(1));
		expect(sent(fetch, "create_drive_folder")[0].body).toEqual({ parent: "folder-invoices", title: "Fournisseurs" });
		await settle();
		await dialog.options.primary_action();
		expect(sent(fetch, "save_to_drive")[0].body.drive_folder).toBe("folder-new");
	});

	it("says what the server refused, and lets the person try again", async () => {
		const server = { get_drive_folders: { folders: ROOTS, last: LAST }, save_to_drive: 417 };
		const { tell, dialogs, said } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		const dialog = dialogs[0];
		await dialog.options.primary_action();
		expect(dialog.shown).toBe(true);
		expect(dialog.disabled).toBe(false);
		// The server's words, never its markup (msgprint shows HTML)
		expect(said).toEqual([["msgprint", "Refused &lt;b&gt;here&lt;/b&gt;"]]);
	});

	it("saves once while the server works, however many clicks", async () => {
		let finish;
		const server = {
			get_drive_folders: { folders: ROOTS, last: LAST },
			save_to_drive: () => new Promise((go) => (finish = () => go(SAVED))),
		};
		const { tell, dialogs, fetch } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		const dialog = dialogs[0];
		const first = dialog.options.primary_action();
		await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
		expect(dialog.disabled).toBe(true);
		dialog.options.primary_action();
		finish();
		await first;
		expect(sent(fetch, "save_to_drive").length).toBe(1);
	});

	it("opens one picker at a time, and none is left once it is closed", async () => {
		const { tell, dialogs } = await open({ server: { get_drive_folders: { folders: ROOTS, last: LAST } } });
		tell(ASKED);
		tell(ASKED);
		tell({ ...ASKED, action: "edit", attachment: { ...INVOICE, name: "Lettre.docx" } });
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		await settle();
		expect(dialogs.length).toBe(1);
		dialogs[0].hide();
		expect(dialogs[0].removed).toBe(true);
		tell(ASKED);
		await vi.waitFor(() => expect(dialogs.length).toBe(2));
	});

	it("hears only what the handover offered", async () => {
		const handover = { ...HANDOVER, host: { ...HANDOVER.host, attachments: ["scan"] } };
		const { tell, dialogs, fetch } = await open({ handover, server: { get_drive_folders: { folders: ROOTS } } });
		tell(ASKED);
		tell({ ...ASKED, action: "edit", attachment: { ...INVOICE, name: "Lettre.docx" } });
		await settle();
		expect(dialogs.length).toBe(0);
		expect(fetch.mock.calls.some(([url]) => String(url).includes("attachments"))).toBe(false);
		// Nothing offered at all: nothing heard
		const none = await open({ handover: { ...HANDOVER, host: { accounts: HANDOVER.host.accounts } } });
		none.tell({ ...ASKED, action: "scan" });
		await settle();
		expect(none.fetch.mock.calls.some(([url]) => String(url).includes("to_scans"))).toBe(false);
	});

	it("takes nothing but an offered action, a message and a described file from NeoMail", async () => {
		const { tell, dialogs, fetch } = await open({ server: { get_drive_folders: { folders: ROOTS } } });
		tell({ ...ASKED, action: "delete" });
		tell({ ...ASKED, email: "../../etc" });
		tell({ ...ASKED, attachment: { name: "Facture.pdf" } });
		await settle();
		expect(dialogs.length).toBe(0);
		expect(fetch.mock.calls.some(([url]) => String(url).includes("attachments"))).toBe(false);
	});
});

describe("Open in NeoDoc…, from an attachment's menu", () => {
	const ASKED = {
		type: "mailcraft:attachment",
		action: "edit",
		...MESSAGE,
		attachment: { index: 2, name: "Lettre.docx", size: 20_000, mime: "", cid: "" },
	};

	it("saves a copy in the Drive, then opens it in a tab opened on the click itself", async () => {
		const tab = { opener: "page", location: { replace: vi.fn() }, close: vi.fn() };
		const opened = vi.spyOn(window, "open").mockReturnValue(tab);
		const server = {
			get_drive_folders: { folders: ROOTS, last: LAST },
			save_to_drive: { ...SAVED, url: "/drive/f/lettre-1" },
		};
		const { tell, dialogs, fetch, said } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		const dialog = dialogs[0];
		expect(dialog.options.title).toBe("Open in NeoDoc");
		expect(dialog.options.primary_action_label).toBe("Save and open");
		await dialog.options.primary_action();
		expect(opened).toHaveBeenCalledWith("", "_blank");
		expect(tab.opener).toBeNull();
		expect(sent(fetch, "save_to_drive")[0].body.edit).toBe(1);
		expect(tab.location.replace).toHaveBeenCalledWith(window.location.origin + "/drive/f/lettre-1");
		expect(tab.close).not.toHaveBeenCalled();
		expect(said[0][1]).toContain('href="/drive/f/lettre-1"');
	});

	it("says the editor is not installed, without making a copy nothing opens", async () => {
		const { tell, dialogs, fetch, said } = await open();
		tell({ ...ASKED, attachment: { ...ASKED.attachment, name: "Budget.xlsx" } });
		await settle();
		expect(said).toEqual([["msgprint", "NeoGrille is not installed on this site."]]);
		expect(dialogs.length).toBe(0);
		// A type no editor opens: nothing at all
		tell({ ...ASKED, attachment: { ...ASKED.attachment, name: "plan.png" } });
		await settle();
		expect(dialogs.length).toBe(0);
		expect(fetch.mock.calls.some(([url]) => String(url).includes("attachments"))).toBe(false);
	});

	it("opens nothing but a file of the Drive, and closes its tab when nothing was saved", async () => {
		const tab = { opener: "page", location: { replace: vi.fn() }, close: vi.fn() };
		vi.spyOn(window, "open").mockReturnValue(tab);
		const server = {
			get_drive_folders: { folders: ROOTS, last: LAST },
			save_to_drive: { ...SAVED, url: "https://evil.example/drive/f/x" },
		};
		const { tell, dialogs } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(rows(dialogs[0]).length).toBe(2));
		await dialogs[0].options.primary_action();
		expect(tab.location.replace).not.toHaveBeenCalled();
		expect(tab.close).toHaveBeenCalled();
		// Refused: the tab goes too
		const refused = { opener: "page", location: { replace: vi.fn() }, close: vi.fn() };
		window.open.mockReturnValue(refused);
		const again = await open({ server: { ...server, save_to_drive: 417 } });
		again.tell(ASKED);
		await vi.waitFor(() => expect(rows(again.dialogs[0]).length).toBe(2));
		await again.dialogs[0].options.primary_action();
		expect(refused.close).toHaveBeenCalled();
		expect(refused.location.replace).not.toHaveBeenCalled();
	});
});

describe("Send to Scanned Documents, from an attachment's menu", () => {
	const ASKED = { type: "mailcraft:attachment", action: "scan", ...MESSAGE, attachment: INVOICE };

	it("sends it at once, once however many clicks, and links to the scanned document", async () => {
		let finish;
		const server = {
			to_scans: () => new Promise((go) => (finish = () => go({ name: "SCAN-118", duplicate: false, message: "Sent <b>now</b>" }))),
		};
		const { tell, dialogs, fetch, said } = await open({ server });
		tell(ASKED);
		tell(ASKED);
		await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
		tell(ASKED);
		finish();
		await vi.waitFor(() => expect(said.length).toBe(1));
		expect(sent(fetch, "to_scans")).toEqual([{ method: "POST", csrf: "csrf-1", body: { ...MESSAGE, attachment: INVOICE } }]);
		expect(dialogs.length).toBe(0);
		expect(said[0]).toEqual(["alert", 'Sent &lt;b&gt;now&lt;/b&gt; <a href="/app/document-scan/SCAN-118">Open it</a>']);
		// Done: a new click sends it again (the server says it is there already)
		tell(ASKED);
		await vi.waitFor(() => expect(sent(fetch, "to_scans").length).toBe(2));
	});

	it("says what the server refused", async () => {
		const server = { to_scans: 403, refused: "You are not allowed to create a scanned document" };
		const { tell, said } = await open({ server });
		tell(ASKED);
		await vi.waitFor(() => expect(said.length).toBe(1));
		expect(said[0]).toEqual(["msgprint", "You are not allowed to create a scanned document"]);
	});
});
