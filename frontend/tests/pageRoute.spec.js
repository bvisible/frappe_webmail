import { describe, expect, it } from "vitest";
import { webmailRoute } from "../src/utils/pageRoute.js";

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
