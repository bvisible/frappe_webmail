import { describe, expect, it } from "vitest";
import { onWebmailPage, webmailRoute } from "../src/utils/pageRoute.js";

describe("webmailRoute", () => {
	it("is the desk's own address for the page when the router can say it", () => {
		const win = { frappe: { router: { make_url: (parts) => `/desk/${parts.join("/")}` } } };
		expect(webmailRoute(win)).toBe("/desk/webmail");
	});

	it("is /app/webmail without a router (a harness, a bare page)", () => {
		expect(webmailRoute({})).toBe("/app/webmail");
		expect(webmailRoute({ frappe: {} })).toBe("/app/webmail");
		expect(webmailRoute({ frappe: { router: {} } })).toBe("/app/webmail");
	});
});

describe("onWebmailPage", () => {
	const at = (pathname) => ({ location: { pathname } });

	it("is the webmail's desk page, and what is below it", () => {
		expect(onWebmailPage(at("/app/webmail"))).toBe(true);
		expect(onWebmailPage(at("/app/webmail/"))).toBe(true);
		expect(onWebmailPage(at("/app/webmail/INBOX"))).toBe(true);
	});

	it("is not another page, NeoMail's included, nor a page whose name starts the same", () => {
		expect(onWebmailPage(at("/app/neomail"))).toBe(false);
		expect(onWebmailPage(at("/app/home"))).toBe(false);
		expect(onWebmailPage(at("/app/webmail-settings"))).toBe(false);
		expect(onWebmailPage({})).toBe(false);
	});
});
