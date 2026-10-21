// The webmail's desk page (frappe_webmail/frappe_webmail/page/webmail/webmail.js) where NeoMail is in the desk for the
// person (frappe.boot.neomail_in_desk): it leads to /app/neomail with what its address asked, in place of itself in
// the history, and builds nothing; its signatures stay its own. Run against a made-up desk.
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(HERE, "../../frappe_webmail", path), "utf8");
const HOST = read("public/js/neomail_host.js");
const PAGE = read("frappe_webmail/page/webmail/webmail.js");

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
	};
}

// The webmail's page loaded and shown at `address`, NeoMail in the desk or not: what the desk was asked.
function open(address, { neomail = true } = {}) {
	window.happyDOM.setURL("http://localhost:3000" + address);
	const wrapper = document.createElement("div");
	document.body.append(wrapper);
	const pushed = [];
	const frappe = {
		boot: { neomail_in_desk: neomail ? 1 : 0 },
		pages: { webmail: wrapper },
		route_flags: {},
		get_route: () => ["webmail"],
		router: {
			push_state(url) {
				pushed.push({ url, replace: frappe.route_flags.replace_route === true });
			},
		},
		ui: {
			make_app_page: vi.fn(({ parent }) => {
				parent.innerHTML = `<div class="page-head"></div><div class="container page-body"><div class="layout-main-section"></div></div>`;
				return { main: $(parent.querySelector(".layout-main-section")) };
			}),
		},
		utils: { debounce: (fn) => fn },
	};
	new Function("window", HOST)(window);
	new Function("frappe", "$", "__", PAGE)(frappe, $, (text) => text);
	frappe.pages.webmail.on_page_load(wrapper);
	frappe.pages.webmail.on_page_show(wrapper);
	vi.runAllTimers();
	return { frappe, pushed, wrapper };
}

afterEach(() => {
	vi.useRealTimers();
	window.happyDOM.setURL("http://localhost:3000/");
	document.body.innerHTML = "";
});

describe("the webmail's page, where NeoMail is in the desk", () => {
	it("leads to NeoMail with the message a link names, in place of itself in the history, and builds nothing", () => {
		vi.useFakeTimers();
		const { frappe, pushed } = open("/app/webmail?account=ada%40example.org&folder=INBOX&uid=31");
		expect(pushed).toEqual([
			{ url: "/app/neomail?account=ada%40example.org&folder=INBOX&uid=31", replace: true },
		]);
		expect(frappe.route_flags.replace_route).toBe(false);
		expect(frappe.ui.make_app_page).not.toHaveBeenCalled();
	});

	it("leads a new message and the plain address there too", () => {
		vi.useFakeTimers();
		expect(open("/app/webmail?compose=1").pushed.map((push) => push.url)).toEqual(["/app/neomail?compose=1"]);
		document.body.innerHTML = "";
		expect(open("/app/webmail").pushed.map((push) => push.url)).toEqual(["/app/neomail"]);
	});

	it("stays for its signatures, written there, and builds itself", () => {
		vi.useFakeTimers();
		const { frappe, pushed } = open("/app/webmail?signatures=1");
		expect(pushed).toEqual([]);
		expect(frappe.ui.make_app_page).toHaveBeenCalledTimes(1);
	});

	it("is the webmail as before where NeoMail is not in the desk", () => {
		vi.useFakeTimers();
		const { frappe, pushed } = open("/app/webmail?account=ada%40example.org&uid=31", { neomail: false });
		expect(pushed).toEqual([]);
		expect(frappe.ui.make_app_page).toHaveBeenCalledTimes(1);
	});
});
