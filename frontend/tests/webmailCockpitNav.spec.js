// The webmail page lends its folders to the desk's cockpit (publishNav): a mailbox is headed by its whole address, and
// the other mailboxes are listed by theirs. The domain tells mailboxes apart when a person has several (info@ of two
// domains); the heading used to stop after the @ (« DANIEL@ »), which read as a cut address and made two mailboxes
// that begin alike the same, where NeoMail's cockpit always showed the whole address (11.11.2026).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, shallowMount } from "@vue/test-utils";
import Webmail from "@/pages/Webmail.vue";

const ACCOUNTS = [
	{
		name: "daniel@neoservice.ai",
		email: "daniel@neoservice.ai",
		sender_name: "Daniel",
		user: "daniel",
	},
	{
		name: "info@neoservice.ai",
		email: "info@neoservice.ai",
		sender_name: "Info",
		user: "daniel",
	},
	{ name: "info@neoffice.io", email: "info@neoffice.io", sender_name: "Info", user: "daniel" },
];

async function lentNav(accounts) {
	window.happyDOM.setURL("http://localhost:3000/app/webmail");
	const setPageNav = vi.fn();
	window.NeoCockpit = { setPageNav };
	frappe.provide = vi.fn(() => {
		frappe.webmail = frappe.webmail || {};
	});
	const answers = { get_accounts: accounts, get_folders: [] };
	frappe.call.mockImplementation(async ({ method }) => {
		const name = method.split(".").pop();
		return { message: name in answers ? answers[name] : {} };
	});
	const wrapper = shallowMount(Webmail);
	await flushPromises();
	wrapper.vm.publishNav();
	return { wrapper, nav: setPageNav.mock.calls.at(-1)[0].nav };
}

beforeEach(() => {
	// A plain store: Node 25's own `localStorage` (experimental) shadows the one of the test DOM and has no `clear`
	const store = new Map();
	vi.stubGlobal("localStorage", {
		getItem: (key) => (store.has(key) ? store.get(key) : null),
		setItem: (key, value) => store.set(key, String(value)),
		removeItem: (key) => store.delete(key),
		clear: () => store.clear(),
	});
});

afterEach(() => {
	vi.unstubAllGlobals();
	delete window.NeoCockpit;
	window.happyDOM.setURL("http://localhost:3000/");
	document.body.innerHTML = "";
});

describe("the webmail page in the desk's cockpit", () => {
	it("heads the mailbox with its whole address, never cut after the @", async () => {
		const { nav } = await lentNav(ACCOUNTS);
		expect(nav.map((section) => section.label)).toContain("daniel@neoservice.ai");
		expect(nav.map((section) => section.label)).not.toContain("daniel@");
	});

	it("lists the other mailboxes by their whole address: two that begin alike stay apart", async () => {
		const { nav } = await lentNav(ACCOUNTS);
		const others = nav.find((section) => section.label === "Other mailboxes");
		expect(others.items.map((item) => item.label)).toEqual([
			"info@neoservice.ai",
			"info@neoffice.io",
		]);
	});

	it("heads a mailbox alone the same way", async () => {
		const { nav } = await lentNav(ACCOUNTS.slice(0, 1));
		expect(nav.map((section) => section.label)).toEqual(["daniel@neoservice.ai"]);
	});
});
