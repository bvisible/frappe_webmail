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

// The desk with the page loaded and shown, its frame there: what the page heard, what it lent, what it posted.
async function open({ cockpit = true } = {}) {
	const heard = [];
	const listen = window.addEventListener.bind(window);
	vi.spyOn(window, "addEventListener").mockImplementation((type, fn, options) => {
		if (type === "message") heard.push(fn);
		return listen(type, fn, options);
	});
	const setPageNav = vi.fn();
	if (cockpit) window.NeoCockpit = { setPageNav };
	else delete window.NeoCockpit;
	const wrapper = document.createElement("div");
	wrapper.className = "content page-container";
	wrapper.setAttribute("data-page-route", "neomail");
	document.body.append(wrapper);
	const frappe = {
		csrf_token: "csrf-1",
		pages: { neomail: wrapper },
		router: { make_url: (parts) => "/app/" + parts.join("/") },
		ui: { make_app_page },
		utils: { debounce: (fn) => fn },
	};
	const fetch = vi.fn(async () => new Response(JSON.stringify({ message: structuredClone(HANDOVER) })));
	new Function("window", HOST)(window);
	new Function("frappe", "$", "__", "fetch", PAGE)(frappe, $, (text) => text, fetch);
	frappe.pages.neomail.on_page_load(wrapper);
	frappe.pages.neomail.on_page_show(wrapper);
	await vi.waitFor(() => expect(wrapper.querySelector("iframe")).toBeTruthy());
	const frame = wrapper.querySelector("iframe");
	const posted = [];
	Object.defineProperty(frame, "contentWindow", {
		value: { postMessage: (message, origin) => posted.push([message, origin]) },
	});
	const tell = (data) =>
		heard.forEach((fn) => fn({ source: frame.contentWindow, origin: window.location.origin, data }));
	desk = { wrapper, frappe, frame, posted, tell, setPageNav, fetch };
	return desk;
}

beforeEach(() => {
	document.body.className = "";
});

afterEach(() => {
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
		const { tell, setPageNav, frame } = await open();
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		tell({ type: "mailcraft:command-done", id: 4, ok: false, error: "Notes are not offered" });
		tell({ type: "mailcraft:command-done", id: 5, ok: true });
		expect(warn).toHaveBeenCalledTimes(1);
		expect(warn.mock.calls[0]).toContain("Notes are not offered");
		// Another frame, another origin
		window.dispatchEvent(new MessageEvent("message", { data: STATE, origin: window.location.origin }));
		expect(setPageNav).not.toHaveBeenCalled();
		expect(frame.contentWindow).toBeTruthy();
	});

	it("asks NeoMail to leave its navigation to the menu only where the menu can draw it", async () => {
		await open();
		expect(window.mailcraftJmap.chrome).toBe("menu");
		desk.wrapper.remove();
		await open({ cockpit: false });
		expect("chrome" in window.mailcraftJmap).toBe(false);
	});
});
