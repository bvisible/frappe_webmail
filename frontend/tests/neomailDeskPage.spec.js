// The desk's page /app/neomail (frappe_webmail/frappe_webmail/page/neomail/neomail.js), run against a made-up desk:
// its page wrapper, its jQuery events, its menu (NeoCockpit's setPageNav) and a frame NeoMail would be in.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(HERE, "../../frappe_webmail", path), "utf8");
const HOST = read("public/js/neomail_host.js");
const PAGE = read("frappe_webmail/page/neomail/neomail.js");

// Just enough of jQuery for the page: html(), append(), and events with their namespace and target, bubbling.
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
		trigger(full) {
			const [type, ...namespace] = full.split(".");
			el.dispatchEvent(new CustomEvent("jq-" + type, { bubbles: true, detail: namespace.join(".") }));
			return this;
		},
	};
}

// The markup Frappe's make_app_page gives a single-column page (frappe/public/js/frappe/ui/page.html, page.js).
function make_app_page({ parent }) {
	parent.innerHTML = `<div class="page-head"></div><div class="container page-body"><div class="page-wrapper">
		<div class="page-content"><div class="row layout-main"><div class="col-md-12 layout-main-section-wrapper">
		<div class="layout-main-section"></div></div></div></div></div></div>`;
	return { main: $(parent.querySelector(".layout-main-section")) };
}

const HANDOVER = {
	build_url: "about:blank",
	host: { accounts: [{ email: "ada@example.org", secret: "token-1" }], language: "fr", chrome: "menu" },
	no_mailbox: false,
};
const STATE = {
	type: "mailcraft:state",
	module: "mail",
	account: "ada@example.org",
	folder: "F-inbox",
	favorites: [],
	accounts: [
		{
			email: "ada@example.org",
			folders: [{ id: "F-inbox", name: "Inbox", role: "inbox", parent: null, unread: 2, selectable: true }],
		},
	],
};

let desk;

// Frappe's __ (frappe/public/js/frappe/translate.js): the translation in the context, else the word's without
// context, else the word.
function translator(messages) {
	return (text, replace, context) =>
		(context && messages[`${text}:${context}`]) || messages[text] || text;
}

// The desk with the page loaded and shown, its frame there: what the page heard, what it lent, what it posted.
// `features`: what the cockpit says it draws of a page's navigation (none: an older cockpit).
// `answer`: the handover's answer, a promise the test settles itself (the page may be hidden by then).
// `key`: what the server answers the page's message_key (a message the address names), or a failure (null).
// `synk`: Raven installed for a person who holds its role (unless `role: false`): what Raven answers for the unread
// messages (`unread`: the rows, or a refusal's status) and the person's channels (`channels`), and the desk's socket
// (`realtime`).
async function open({ cockpit = true, features = null, boot = {}, messages = {}, answer = null, key, synk = null } = {}) {
	const heard = [];
	const listen = window.addEventListener.bind(window);
	vi.spyOn(window, "addEventListener").mockImplementation((type, fn, options) => {
		if (type === "message") heard.push(fn);
		return listen(type, fn, options);
	});
	const setPageNav = vi.fn();
	if (cockpit) window.NeoCockpit = features ? { setPageNav, pageNavFeatures: features } : { setPageNav };
	else delete window.NeoCockpit;
	const wrapper = document.createElement("div");
	wrapper.className = "content page-container";
	wrapper.setAttribute("data-page-route", "neomail");
	document.body.append(wrapper);
	const frappe = {
		csrf_token: "csrf-1",
		boot,
		_messages: messages,
		pages: { neomail: wrapper },
		router: { make_url: (parts) => "/app/" + parts.join("/") },
		ui: { make_app_page },
		utils: { debounce: (fn) => fn },
	};
	if (synk) {
		// The desk's dialogs and alerts, as the share uses them: each dialog made is kept, with what it was shown
		synk.dialogs = [];
		synk.said = [];
		frappe.ui.Dialog = class {
			constructor(options) {
				this.options = options;
				this.shown = false;
				this.disabled = false;
				synk.dialogs.push(this);
			}
			show() {
				this.shown = true;
			}
			hide() {
				this.shown = false;
			}
			disable_primary_action() {
				this.disabled = true;
			}
			enable_primary_action() {
				this.disabled = false;
			}
		};
		frappe.msgprint = (text) => synk.said.push(["msgprint", text]);
		frappe.show_alert = (alert) => synk.said.push(["alert", alert.message]);
		frappe.utils.get_random = () => "client-1";
		frappe.boot = { ...boot, versions: { raven: "3.0.0" } };
		frappe.user = { has_role: (role) => role === "Raven User" && synk.role !== false };
		frappe.session = { user: "ada@example.org" };
		if (synk.realtime) frappe.realtime = synk.realtime;
	}
	const fetch = vi.fn(async (url) => {
		if (String(url).includes("raven.api.raven_message.get_unread_count_for_channels")) {
			const unread = synk && synk.unread;
			return typeof unread === "number"
				? new Response("{}", { status: unread })
				: new Response(JSON.stringify({ message: unread || [] }));
		}
		if (String(url).includes("raven.api.raven_channel.get_all_channels")) {
			return new Response(JSON.stringify({ message: (synk && synk.channels) || { channels: [], dm_channels: [] } }));
		}
		if (String(url).includes("neomail_share.destinations")) {
			return new Response(JSON.stringify({ message: (synk && synk.destinations) || { channels: [], people: [] } }));
		}
		if (String(url).includes("neomail_share.share")) {
			const shared = synk && synk.shared;
			return typeof shared === "number"
				? new Response(JSON.stringify({ _server_messages: JSON.stringify([JSON.stringify({ message: "Refused <b>here</b>" })]) }), {
						status: shared,
				  })
				: new Response(JSON.stringify({ message: shared || {} }));
		}
		if (String(url).includes("message_key")) {
			return key ? new Response(JSON.stringify({ message: key })) : new Response("{}", { status: 417 });
		}
		return answer || new Response(JSON.stringify({ message: structuredClone(HANDOVER) }));
	});
	new Function("window", HOST)(window);
	new Function("frappe", "$", "__", "fetch", PAGE)(frappe, $, translator(messages), fetch);
	frappe.pages.neomail.on_page_load(wrapper);
	frappe.pages.neomail.on_page_show(wrapper);
	if (answer) {
		desk = { wrapper, frappe, setPageNav, fetch, heard };
		return desk;
	}
	await vi.waitFor(() => expect(wrapper.querySelector("iframe")).toBeTruthy());
	const frame = wrapper.querySelector("iframe");
	const posted = [];
	Object.defineProperty(frame, "contentWindow", {
		value: { postMessage: (message, origin) => posted.push([message, origin]) },
	});
	const hear = (event) => heard.forEach((fn) => fn(event));
	const tell = (data) => hear({ source: frame.contentWindow, origin: window.location.origin, data });
	desk = { wrapper, frappe, frame, posted, tell, hear, setPageNav, fetch };
	return desk;
}

beforeEach(() => {
	// The desk's chrome is NeoCockpit (frappe's desk.js puts the class on the body)
	document.body.className = "neoffice-cockpit";
});

// The address the page is at (happy-dom's history does not move its location: its URL is set instead)
const at = (address) => window.happyDOM.setURL("http://localhost:3000" + address);
// What the page left in the address, from its last history.replaceState
const left = (replaced) => replaced.mock.lastCall && replaced.mock.lastCall[2];

afterEach(() => {
	at("/app/neomail");
	vi.restoreAllMocks();
	if (desk) desk.wrapper.remove();
	desk = null;
	delete window.NeoCockpit;
	delete window.mailcraftJmap;
});

describe("the desk's page", () => {
	it("has the panel draw nothing around it while it is in front, and gives the panel back when hidden", async () => {
		const { wrapper, frappe } = await open();
		expect(document.body.classList.contains("neomail-desk-full")).toBe(true);
		// A dialog's own hide, bubbling from inside the page, is not the page being hidden
		$(wrapper.querySelector(".layout-main-section")).trigger("hide.bs.modal");
		expect(document.body.classList.contains("neomail-desk-full")).toBe(true);
		$(wrapper).trigger("hide");
		expect(document.body.classList.contains("neomail-desk-full")).toBe(false);
		frappe.pages.neomail.on_page_show(wrapper);
		expect(document.body.classList.contains("neomail-desk-full")).toBe(true);
	});

	it("keeps the handover on the window only while the page is in front, and the frame's functions always", async () => {
		const { wrapper, frappe } = await open();
		expect(window.mailcraftJmap.accounts[0].secret).toBe("token-1");
		$(wrapper).trigger("hide");
		expect("mailcraftJmap" in window).toBe(false);
		// The frame goes on under the hidden page: a renewal it asks for then still has the page's function
		expect(typeof window.mailcraftJmapRenew).toBe("function");
		expect(typeof window.mailcraftFetchUrl).toBe("function");
		// The frame keeps what it read as it started; a reload of it once the page is back finds it again
		frappe.pages.neomail.on_page_show(wrapper);
		expect(window.mailcraftJmap.accounts[0].secret).toBe("token-1");
	});

	it("starts NeoMail only once the page is in front, when the handover came while it was hidden", async () => {
		let settle;
		const answer = new Promise((resolve) => (settle = resolve));
		delete window.mailcraftJmapRenew;
		delete window.mailcraftFetchUrl;
		const { wrapper, frappe } = await open({ answer });
		$(wrapper).trigger("hide");
		settle(new Response(JSON.stringify({ message: structuredClone(HANDOVER) })));
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(wrapper.querySelector("iframe")).toBeNull();
		expect("mailcraftJmap" in window).toBe(false);
		expect("mailcraftJmapRenew" in window).toBe(false);
		frappe.pages.neomail.on_page_show(wrapper);
		expect(wrapper.querySelector("iframe")).toBeTruthy();
		expect(window.mailcraftJmap.accounts[0].secret).toBe("token-1");
	});

	it("lends the menu NeoMail's navigation as NeoMail says it is, and a click there asks NeoMail", async () => {
		const { tell, setPageNav, posted } = await open();
		expect(setPageNav).not.toHaveBeenCalled();
		tell(STATE);
		expect(setPageNav).toHaveBeenCalledTimes(1);
		const lent = setPageNav.mock.calls[0][0];
		expect(lent.app).toEqual({ name: "mail", title: "Mail" });
		expect(lent.route).toBe("/app/neomail");
		expect(lent.nav.map((section) => section.label)).toEqual(["ada@example.org", undefined]);
		expect(lent.nav[0].items[0]).toMatchObject({ label: "Inbox", badge: 2, badgeTone: "accent", active: true });
		lent.nav[0].items[0].onClick();
		lent.nav[1].items[1].onClick();
		expect(posted).toEqual([
			[
				{
					type: "mailcraft:command",
					id: 1,
					name: "folder.select",
					params: { account: "ada@example.org", folder: "F-inbox" },
				},
				window.location.origin,
			],
			[{ type: "mailcraft:command", id: 2, name: "view.calendar", params: {} }, window.location.origin],
		]);
	});

	it("gives the menu back when the page is hidden, and lends it again, as last said, when it comes back", async () => {
		const { wrapper, frappe, tell, setPageNav } = await open();
		tell(STATE);
		$(wrapper).trigger("hide");
		expect(setPageNav).toHaveBeenLastCalledWith(null);
		// NeoMail goes on from under the hidden page: the menu is another page's now
		tell({ ...STATE, folder: null });
		expect(setPageNav).toHaveBeenCalledTimes(2);
		frappe.pages.neomail.on_page_show(wrapper);
		expect(setPageNav).toHaveBeenCalledTimes(3);
		expect(setPageNav.mock.calls[2][0].nav[0].items[0].active).toBe(false);
	});

	it("hears only its frame, and keeps a refused command in the console", async () => {
		const { tell, hear, setPageNav, frame } = await open();
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		tell({ type: "mailcraft:command-done", id: 4, ok: false, error: "Notes are not offered" });
		tell({ type: "mailcraft:command-done", id: 5, ok: true });
		expect(warn).toHaveBeenCalledTimes(1);
		expect(warn.mock.calls[0]).toContain("Notes are not offered");
		// The page's own origin, but not its frame's window (another frame's, or none)
		hear({ source: {}, origin: window.location.origin, data: STATE });
		hear({ source: null, origin: window.location.origin, data: STATE });
		// Its frame's window, but another origin
		hear({ source: frame.contentWindow, origin: "https://elsewhere.example", data: STATE });
		expect(setPageNav).not.toHaveBeenCalled();
	});

	it("asks NeoMail to leave its navigation to the menu only where the menu can draw it", async () => {
		await open();
		expect(window.mailcraftJmap.chrome).toBe("menu");
		desk.wrapper.remove();
		// No NeoCockpit
		await open({ cockpit: false });
		expect("chrome" in window.mailcraftJmap).toBe(false);
		desk.wrapper.remove();
		// NeoCockpit loaded, but not the desk's chrome
		document.body.className = "";
		await open();
		expect("chrome" in window.mailcraftJmap).toBe(false);
		desk.wrapper.remove();
		// The site switched NeoCockpit off
		document.body.className = "neoffice-cockpit";
		await open({ boot: { neoffice_cockpit_disable: 1 } });
		expect("chrome" in window.mailcraftJmap).toBe(false);
	});

	it("puts the views in the cockpit's dock and lends it the search box, where the cockpit offers them", async () => {
		const { tell, setPageNav, posted } = await open({ features: ["dock", "search"] });
		tell({ ...STATE, views: ["mail", "calendar", "people"] });
		const lent = setPageNav.mock.calls[0][0];
		expect(lent.nav.map((section) => section.label)).toEqual(["ada@example.org"]);
		expect(lent.dock.map((view) => [view.id, view.icon, view.active])).toEqual([
			["mail", "mail", true],
			["calendar", "calendar", false],
			["people", "users", false],
		]);
		expect(lent.search.placeholder).toBe("Search mail");
		lent.search.onQuery("devis 2026");
		lent.search.onQuery("");
		lent.dock[1].onClick();
		expect(posted.map(([message]) => [message.name, message.params])).toEqual([
			["search", { query: "devis 2026" }],
			["search", { query: "" }],
			["view.calendar", {}],
		]);
	});

	it("keeps the views at the end of the navigation, and the desk's search, with an older cockpit", async () => {
		const { tell, setPageNav } = await open();
		tell(STATE);
		const lent = setPageNav.mock.calls[0][0];
		expect(lent.dock).toBeUndefined();
		expect(lent.search).toBeUndefined();
		expect(lent.nav.at(-1).items.map((item) => item.icon)).toEqual([
			"lucide-mail",
			"lucide-calendar",
			"lucide-users",
			"lucide-sticky-note",
		]);
	});

	it("names the views in NeoMail's words, never in another app's", async () => {
		// What other apps made of the same English words, and NeoMail's own in their context
		const messages = {
			Mail: "Messagerie",
			People: "Personnes",
			Notes: "Remarques",
			Favourites: "Favoris d'ailleurs",
			"Mail:NeoMail view": "Courrier",
			"Calendar:NeoMail view": "Calendrier",
			"People:NeoMail view": "Contacts",
			"Favourites:NeoMail pane": "Favoris",
		};
		const { tell, setPageNav } = await open({ features: ["dock"], messages });
		const favorites = [{ account: "ada@example.org", folder: "F-inbox", name: "Inbox - ada", unread: 2 }];
		tell({ ...STATE, favorites });
		const lent = setPageNav.mock.calls[0][0];
		expect(lent.dock.map((view) => view.title)).toEqual(["Courrier", "Calendrier", "Contacts", "Notes"]);
		expect(lent.nav[0].label).toBe("Favoris");
		// The module card too: « Courrier », not what another app made of « Mail »
		expect(lent.app).toEqual({ name: "mail", title: "Courrier" });
	});

	it("lights a folder once, in the list it was chosen from", async () => {
		const { tell, setPageNav } = await open();
		const favorites = [{ account: "ada@example.org", folder: "F-inbox", name: "Inbox - ada", unread: 2 }];
		tell({ ...STATE, favorites, folder: null });
		setPageNav.mock.calls[0][0].nav[0].items[0].onClick();
		tell({ ...STATE, favorites });
		const lit = setPageNav.mock.lastCall[0].nav.map(
			(section) => section.items.filter((item) => item.active).length
		);
		// Favoris, the mailbox, the views (Mail in front)
		expect(lit).toEqual([1, 0, 1]);
	});

	it("forgets the list a folder was chosen from once NeoMail goes elsewhere by itself", async () => {
		const { tell, setPageNav } = await open();
		const favorites = [{ account: "ada@example.org", folder: "F-inbox", name: "Inbox - ada", unread: 2 }];
		const sent = { id: "F-sent", name: "Sent", role: "sent", parent: null, unread: 0, selectable: true };
		const accounts = [{ ...STATE.accounts[0], folders: [...STATE.accounts[0].folders, sent] }];
		const lit = () =>
			setPageNav.mock.lastCall[0].nav.map((section) => section.items.filter((item) => item.active).length);
		tell({ ...STATE, accounts, favorites, folder: null });
		setPageNav.mock.lastCall[0].nav[0].items[0].onClick();
		tell({ ...STATE, accounts, favorites });
		expect(lit()).toEqual([1, 0, 1]);
		// NeoMail goes to Sent by itself (the keyboard), then back to the inbox by itself: its mailbox's section
		tell({ ...STATE, accounts, favorites, folder: "F-sent" });
		tell({ ...STATE, accounts, favorites });
		expect(lit()).toEqual([0, 1, 1]);
	});

	it("forgets a choice NeoMail refused", async () => {
		const { tell, setPageNav, posted } = await open();
		vi.spyOn(console, "warn").mockImplementation(() => {});
		const favorites = [{ account: "ada@example.org", folder: "F-inbox", name: "Inbox - ada", unread: 2 }];
		tell({ ...STATE, favorites, folder: null });
		setPageNav.mock.lastCall[0].nav[0].items[0].onClick();
		const id = posted.at(-1)[0].id;
		tell({ type: "mailcraft:command-done", id, ok: false, error: "No such folder" });
		// Later NeoMail shows the inbox by itself: lit in its mailbox's section, not in Favoris
		tell({ ...STATE, favorites });
		const lit = setPageNav.mock.lastCall[0].nav.map((section) => section.items.filter((item) => item.active).length);
		expect(lit).toEqual([0, 1, 1]);
	});

	it("draws the menu again at once when the favourite of the folder already shown is chosen", async () => {
		const { tell, setPageNav } = await open();
		const favorites = [{ account: "ada@example.org", folder: "F-inbox", name: "Inbox - ada", unread: 2 }];
		tell({ ...STATE, favorites });
		const lit = (call) =>
			setPageNav.mock.calls[call][0].nav.map((section) => section.items.filter((item) => item.active).length);
		expect(lit(0)).toEqual([0, 1, 1]);
		// NeoMail says nothing new (the folder does not change): the menu moves the light by itself
		setPageNav.mock.calls[0][0].nav[0].items[0].onClick();
		expect(setPageNav).toHaveBeenCalledTimes(2);
		expect(lit(1)).toEqual([1, 0, 1]);
	});

	// A message an address names ---------------------------------------------------------------------------------

	it("opens the message a webmail's link names, once NeoMail said where it is, and takes it off the address", async () => {
		at("/app/neomail?build=ucs&account=ada%40example.org&folder=Archive&uid=31");
		const replaced = vi.spyOn(window.history, "replaceState");
		const key = { account: "ada@example.org", mailbox: "MQXJjaGl2ZQ", email: "E7V31ZQXJjaGl2ZQ" };
		const { tell, posted, fetch } = await open({ key });
		expect(left(replaced)).toBe("/app/neomail?build=ucs");
		const asked = fetch.mock.calls.find(([url]) => String(url).includes("message_key"));
		expect(asked[0]).toContain("account=ada%40example.org&folder=Archive&uid=31");
		expect(asked[1].method).toBe("GET");
		expect(asked[1].headers["X-Frappe-CSRF-Token"]).toBe("csrf-1");
		expect(posted).toEqual([], "nothing before NeoMail said where it is");
		tell(STATE);
		expect(posted.map(([message]) => [message.name, message.params])).toEqual([
			["message.open", { account: "ada@example.org", id: "E7V31ZQXJjaGl2ZQ" }],
		]);
		// Once only
		tell({ ...STATE, folder: null });
		expect(posted.length).toBe(1);
	});

	it("shows the message's folder where NeoMail does not open a message by its id", async () => {
		at("/app/neomail?account=ada%40example.org&folder=Archive&uid=31");
		const key = { account: "ada@example.org", mailbox: "MQXJjaGl2ZQ", email: "E7V31ZQXJjaGl2ZQ" };
		const { tell, posted } = await open({ key });
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		tell(STATE);
		const id = posted[0][0].id;
		tell({ type: "mailcraft:command-done", id, ok: false, error: "Unknown command" });
		expect(posted.map(([message]) => [message.name, message.params])).toEqual([
			["message.open", { account: "ada@example.org", id: "E7V31ZQXJjaGl2ZQ" }],
			["folder.select", { account: "ada@example.org", folder: "MQXJjaGl2ZQ" }],
		]);
		expect(warn).not.toHaveBeenCalled();
	});

	it("opens a message named by its JMAP id, and a new message, without asking the server", async () => {
		at("/app/neomail?account=ada%40example.org&email=E7V31ZQXJjaGl2ZQ");
		const replaced = vi.spyOn(window.history, "replaceState");
		let desk_ = await open();
		desk_.tell(STATE);
		expect(desk_.posted[0][0]).toMatchObject({ name: "message.open", params: { id: "E7V31ZQXJjaGl2ZQ" } });
		expect(desk_.fetch.mock.calls.some(([url]) => String(url).includes("message_key"))).toBe(false);
		expect(left(replaced)).toBe("/app/neomail");
		desk_.wrapper.remove();
		at("/app/neomail?compose=1");
		desk_ = await open();
		desk_.tell(STATE);
		expect(desk_.posted.map(([message]) => message.name)).toEqual(["mail.new"]);
	});

	it("opens NeoMail as it is when the server does not find the message (another's mailbox)", async () => {
		at("/app/neomail?account=someone%40example.org&uid=4");
		const replaced = vi.spyOn(window.history, "replaceState");
		const { tell, posted } = await open({ key: null });
		tell(STATE);
		expect(posted).toEqual([]);
		expect(left(replaced)).toBe("/app/neomail");
	});

	it("opens what a link followed later asks, from the address or from the desk's route options, and clears both", async () => {
		const key = { account: "ada@example.org", mailbox: "MQXJjaGl2ZQ", email: "E7V31ZQXJjaGl2ZQ" };
		const { tell, posted, frappe, wrapper, fetch } = await open({ key });
		tell(STATE);
		expect(posted).toEqual([]);
		// A link of the desk (<a>) followed while the page is open: its query is in frappe.route_options
		frappe.route_options = { account: "ada@example.org", folder: "Archive", uid: "31", other: "kept" };
		frappe.pages.neomail.on_page_show(wrapper);
		await vi.waitFor(() => expect(posted.length).toBe(1));
		expect(posted[0][0]).toMatchObject({ name: "message.open", params: { id: "E7V31ZQXJjaGl2ZQ" } });
		expect(frappe.route_options).toEqual({ other: "kept" });
		const asked = fetch.mock.calls.filter(([url]) => String(url).includes("message_key"));
		expect(asked.length).toBe(1);
		expect(asked[0][0]).toContain("folder=Archive&uid=31");
		// The address of a later show, its query taken off
		at("/app/neomail?account=ada%40example.org&email=E7V9ZQXJjaGl2ZQ");
		const replaced = vi.spyOn(window.history, "replaceState");
		frappe.pages.neomail.on_page_show(wrapper);
		await vi.waitFor(() => expect(posted.length).toBe(2));
		expect(posted[1][0].params).toEqual({ account: "ada@example.org", id: "E7V9ZQXJjaGl2ZQ" });
		expect(left(replaced)).toBe("/app/neomail");
		// Shown again with nothing asked (the address as the browser left it): nothing sent again
		at(left(replaced));
		frappe.pages.neomail.on_page_show(wrapper);
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(posted.length).toBe(2);
	});

	it("gives the webmail back in this tab when NeoMail was switched off since the desk started", async () => {
		const answer = Promise.resolve(new Response("{}", { status: 404 }));
		const { wrapper, frappe } = await open({ answer, boot: { neomail_in_desk: 1 } });
		await vi.waitFor(() => expect(wrapper.querySelector(".neomail-desk-note")).toBeTruthy());
		expect(frappe.boot.neomail_in_desk).toBe(0);
		expect(wrapper.querySelector(".neomail-desk-note a").getAttribute("href")).toBe("/app/webmail");
	});
});

// The desk's socket as the page uses it (frappe/public/js/frappe/socketio_client.js): on, doctype_subscribe; `emit`
// plays an event the server would send.
function socket() {
	const handlers = {};
	return {
		on: (event, fn) => (handlers[event] = handlers[event] || []).push(fn),
		doctype_subscribe: vi.fn(),
		emit: (event, data) => (handlers[event] || []).forEach((fn) => fn(data)),
	};
}

// Whether a frame is behind the other one: kept at its size, out of sight, out of reach (never `display: none`).
const away = (frame) => {
	const behind = frame.classList.contains("neomail-desk-away");
	expect(frame.inert).toBe(behind);
	expect(frame.hidden).toBe(false);
	return behind;
};

// What the page asked Raven for the unread messages, so far.
const unreadAsked = (fetch) => fetch.mock.calls.filter(([url]) => String(url).includes("get_unread_count_for_channels")).length;

// The dock the menu was last lent, once it shows Synk.
async function synkDock(setPageNav) {
	await vi.waitFor(() => expect(setPageNav.mock.lastCall[0].dock.map((view) => view.id)).toContain("synk"));
	return setPageNav.mock.lastCall[0].dock;
}

describe("Synk, a view of the desk's page after NeoMail's", () => {
	// Raven's frame stays empty here: happy-dom would try to load /raven itself
	beforeEach(() => {
		window.happyDOM.settings.disableIframePageLoading = true;
	});
	afterEach(() => {
		window.happyDOM.settings.disableIframePageLoading = false;
	});

	const UNREAD = [
		{ name: "general", is_direct_message: 0, unread_count: 2 },
		{ name: "ada-bruno", is_direct_message: 1, unread_count: 1 },
	];

	it("comes after NeoMail's views once Raven answers the person, its unread messages as its badge", async () => {
		const { tell, setPageNav } = await open({ features: ["dock"], synk: { unread: UNREAD } });
		tell(STATE);
		const dock = await synkDock(setPageNav);
		expect(dock.map(({ id, title, icon, active, badge }) => [id, title, icon, active, badge])).toEqual([
			["mail", "Mail", "mail", true, undefined],
			["calendar", "Calendar", "calendar", false, undefined],
			["people", "People", "users", false, undefined],
			["notes", "Notes", "sticky-note", false, undefined],
			["synk", "Synk", "message-circle", false, 3],
		]);
	});

	it("shows Raven in a frame of its own in place of NeoMail, and NeoMail again from any of its views", async () => {
		const { wrapper, frame, tell, setPageNav, posted, fetch } = await open({ features: ["dock"], synk: { unread: UNREAD } });
		tell(STATE);
		(await synkDock(setPageNav)).at(-1).onClick();
		const frames = wrapper.querySelectorAll("iframe");
		expect(frames.length).toBe(2);
		const raven = frames[1];
		expect(raven.getAttribute("src")).toBe("/raven?embed=desk");
		expect(raven.title).toBe("Synk");
		expect(away(raven)).toBe(false);
		expect(away(frame)).toBe(true);
		// The menu shows Synk in front: its icon lit, no folder lit, NeoMail asked nothing
		let lent = setPageNav.mock.lastCall[0];
		expect(lent.dock.map((view) => view.active)).toEqual([false, false, false, false, true]);
		expect(lent.nav.flatMap((section) => section.items).some((item) => item.active)).toBe(false);
		expect(posted).toEqual([]);
		// NeoMail's Mail icon: NeoMail back in front, Raven alive under it, the count asked again
		const before = unreadAsked(fetch);
		lent.dock[0].onClick();
		expect(away(frame)).toBe(false);
		expect(away(raven)).toBe(true);
		expect(raven.isConnected).toBe(true);
		expect(posted.map(([message]) => message.name)).toEqual(["view.mail"]);
		await vi.waitFor(() => expect(unreadAsked(fetch)).toBe(before + 1));
		// Synk again: the same frame, not a new one
		setPageNav.mock.lastCall[0].dock.at(-1).onClick();
		expect(wrapper.querySelectorAll("iframe").length).toBe(2);
		expect(away(raven)).toBe(false);
		// A folder of the menu puts NeoMail back in front too, and asks it
		lent = setPageNav.mock.lastCall[0];
		lent.nav[0].items[0].onClick();
		expect(away(frame)).toBe(false);
		expect(away(raven)).toBe(true);
		expect(posted.at(-1)[0]).toMatchObject({ name: "folder.select", params: { folder: "F-inbox" } });
	});

	it("puts NeoMail back in front for what the menu's search box asks", async () => {
		const { frame, tell, setPageNav, posted } = await open({ features: ["dock", "search"], synk: { unread: UNREAD } });
		tell(STATE);
		(await synkDock(setPageNav)).at(-1).onClick();
		expect(away(frame)).toBe(true);
		setPageNav.mock.lastCall[0].search.onQuery("devis");
		expect(away(frame)).toBe(false);
		expect(posted.at(-1)[0]).toMatchObject({ name: "search", params: { query: "devis" } });
	});

	it("offers no Synk to someone Raven refuses, and asks Raven nothing without its role", async () => {
		const refused = await open({ features: ["dock"], synk: { unread: 417 } });
		refused.tell(STATE);
		await vi.waitFor(() => expect(unreadAsked(refused.fetch)).toBe(1));
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(refused.setPageNav.mock.lastCall[0].dock.map((view) => view.id)).not.toContain("synk");
		desk.wrapper.remove();
		const without = await open({ features: ["dock"], synk: { unread: UNREAD, role: false } });
		without.tell(STATE);
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(unreadAsked(without.fetch)).toBe(0);
		expect(without.setPageNav.mock.lastCall[0].dock.map((view) => view.id)).not.toContain("synk");
		expect(without.wrapper.querySelectorAll("iframe").length).toBe(1);
	});

	it("asks Raven again only for what can change the count, and only while the page is in front", async () => {
		const realtime = socket();
		const channels = { channels: [{ name: "general" }], dm_channels: [{ name: "ada-bruno" }] };
		const { wrapper, frappe, tell, setPageNav, fetch } = await open({
			features: ["dock"],
			synk: { unread: UNREAD, channels, realtime },
		});
		tell(STATE);
		await synkDock(setPageNav);
		// The room of everyone holding the role, where a channel's messages come
		expect(realtime.doctype_subscribe).toHaveBeenCalledWith("Raven User");
		await vi.waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).includes("get_all_channels"))).toBe(true));
		await new Promise((resolve) => setTimeout(resolve, 0));
		const asked = () => unreadAsked(fetch);
		const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
		const event = (data) => realtime.emit("raven:unread_channel_count_updated", data);
		let count = asked();
		// Someone else's message in a channel of the person's: asked
		event({ channel_id: "general", sent_by: "bruno@example.org", is_dm_channel: false });
		count += 1;
		await vi.waitFor(() => expect(asked()).toBe(count));
		// A channel the person is not in, and the person's own message: not asked
		event({ channel_id: "elsewhere", sent_by: "bruno@example.org", is_dm_channel: false });
		event({ channel_id: "general", sent_by: "ada@example.org", is_dm_channel: false });
		await settle();
		expect(asked()).toBe(count);
		// A direct message, a read on another screen: asked
		event({ channel_id: "ada-carla", sent_by: "carla@example.org", is_dm_channel: true });
		count += 1;
		await vi.waitFor(() => expect(asked()).toBe(count));
		event({ channel_id: "general", sent_by: "ada@example.org", event_type: "track_visit" });
		count += 1;
		await vi.waitFor(() => expect(asked()).toBe(count));
		// The page hidden: nothing asked; shown again: asked once
		$(wrapper).trigger("hide");
		event({ channel_id: "general", sent_by: "bruno@example.org", is_dm_channel: false });
		await settle();
		expect(asked()).toBe(count);
		frappe.pages.neomail.on_page_show(wrapper);
		count += 1;
		await vi.waitFor(() => expect(asked()).toBe(count));
		// The socket back after a break: the room joined again, the count asked again
		realtime.emit("connect");
		expect(realtime.doctype_subscribe).toHaveBeenCalledTimes(2);
		count += 1;
		await vi.waitFor(() => expect(asked()).toBe(count));
	});

	it("takes Synk away when Raven later refuses the person, NeoMail back in front", async () => {
		const realtime = socket();
		const synk = { unread: UNREAD, realtime };
		const { frame, tell, setPageNav } = await open({ features: ["dock"], synk });
		tell(STATE);
		(await synkDock(setPageNav)).at(-1).onClick();
		expect(away(frame)).toBe(true);
		// The role taken away meanwhile: Raven's next answer is a refusal
		synk.unread = 403;
		realtime.emit("raven:unread_channel_count_updated", { channel_id: "x", sent_by: "bruno@example.org", is_dm_channel: true });
		await vi.waitFor(() => expect(away(frame)).toBe(false));
		expect(setPageNav.mock.lastCall[0].dock.map((view) => view.id)).not.toContain("synk");
	});
});

describe("Share in Synk, from NeoMail's button", () => {
	beforeEach(() => {
		window.happyDOM.settings.disableIframePageLoading = true;
	});
	afterEach(() => {
		window.happyDOM.settings.disableIframePageLoading = false;
	});

	const DESTINATIONS = {
		channels: [{ id: "synk-atelier", label: "atelier", private: true }],
		people: [{ id: "bruno@example.org", label: "Bruno Keller" }],
	};
	const ASKED = { type: "mailcraft:share", account: "ada@example.org", email: "E7V31ZSU5CT1g" };

	// The share's request to the server, as the page made it: its address, its method and what it sent.
	const shareSent = (fetch) =>
		fetch.mock.calls
			.filter(([url]) => String(url).includes("neomail_share.share"))
			.map(([, init]) => ({ method: init.method, csrf: init.headers["X-Frappe-CSRF-Token"], body: JSON.parse(init.body) }));

	it("asks where, shares as asked, and shows the post in Synk", async () => {
		const synk = { unread: [], destinations: DESTINATIONS, shared: { channel: "synk-atelier", message: "m-42", files: 1, left_out: 0 } };
		const { wrapper, frame, tell, fetch } = await open({ features: ["dock"], synk });
		tell(STATE);
		tell(ASKED);
		await vi.waitFor(() => expect(synk.dialogs.length).toBe(1));
		const dialog = synk.dialogs[0];
		expect(dialog.shown).toBe(true);
		expect(dialog.options.fields.find((f) => f.fieldname === "to").options).toEqual([
			{ value: "channel:synk-atelier", label: "# atelier" },
			{ value: "user:bruno@example.org", label: "Bruno Keller" },
		]);
		await dialog.options.primary_action({ to: "channel:synk-atelier", note: "Pour info", attachments: 1 });
		expect(shareSent(fetch)).toEqual([
			{
				method: "POST",
				csrf: "csrf-1",
				body: {
					account: "ada@example.org",
					email: "E7V31ZSU5CT1g",
					to: "channel:synk-atelier",
					note: "Pour info",
					attachments: 1,
					client_id: "client-1",
				},
			},
		]);
		expect(dialog.shown).toBe(false);
		expect(synk.said).toContainEqual(["alert", "Shared in Synk"]);
		// Synk in front, on the post
		const raven = wrapper.querySelectorAll("iframe")[1];
		expect(raven.getAttribute("src")).toBe("/raven/message/m-42?embed=desk");
		expect(away(raven)).toBe(false);
		expect(away(frame)).toBe(true);
	});

	it("says what the server refused, and lets the person try again", async () => {
		const synk = { unread: [], destinations: DESTINATIONS, shared: 417 };
		const { tell, wrapper } = await open({ features: ["dock"], synk });
		tell(STATE);
		tell(ASKED);
		await vi.waitFor(() => expect(synk.dialogs.length).toBe(1));
		const dialog = synk.dialogs[0];
		await dialog.options.primary_action({ to: "user:bruno@example.org" });
		expect(dialog.shown).toBe(true);
		expect(dialog.disabled).toBe(false);
		expect(synk.said).toEqual([["msgprint", "Refused <b>here</b>"]]);
		expect(wrapper.querySelectorAll("iframe").length).toBe(1);
	});

	it("takes nothing but a mailbox and an email id from NeoMail", async () => {
		const synk = { unread: [], destinations: DESTINATIONS };
		const { tell, fetch } = await open({ features: ["dock"], synk });
		tell(STATE);
		tell({ type: "mailcraft:share", account: "ada@example.org", email: "../../etc" });
		tell({ type: "mailcraft:share", account: "nobody", email: "E7V31ZSU5CT1g" });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(synk.dialogs.length).toBe(0);
		expect(fetch.mock.calls.some(([url]) => String(url).includes("neomail_share"))).toBe(false);
	});

	it("says so when there is nowhere to share", async () => {
		const synk = { unread: [], destinations: { channels: [], people: [] } };
		const { tell } = await open({ features: ["dock"], synk });
		tell(STATE);
		tell(ASKED);
		await vi.waitFor(() => expect(synk.said.length).toBe(1));
		expect(synk.said[0]).toEqual(["msgprint", "You have no channel in Synk and nobody to write to yet."]);
		expect(synk.dialogs.length).toBe(0);
	});
});
