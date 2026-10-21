// What a page that frames NeoMail gives the build (frappe_webmail/public/js/neomail_host.js), shared by /neomail and
// the desk's page /app/neomail. The file is a plain browser script, included by the pages where they are rendered: it
// runs here against a made-up window.
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE = readFileSync(
	resolve(dirname(fileURLToPath(import.meta.url)), "../../frappe_webmail/public/js/neomail_host.js"),
	"utf8"
);

const ORIGIN = "https://erp.example.org";

// A page: its window as the script sees it, the answers its fetch gives in turn, and what it asked.
function page(answers = []) {
	const asked = [];
	const heard = [];
	const win = {
		frappe: { csrf_token: "csrf-1" },
		location: { origin: ORIGIN, pathname: "/app/neomail", search: "", hash: "" },
		fetch: vi.fn(async (url, init) => {
			asked.push({ url, init });
			const next = answers.shift();
			return typeof next === "function" ? next(url, init) : next;
		}),
		setTimeout: (go) => go(),
		addEventListener: (type, fn) => type === "message" && heard.push(fn),
		removeEventListener: (type, fn) => heard.splice(heard.indexOf(fn), 1),
	};
	new Function("window", SOURCE)(win);
	return { win, host: win.neomailHost, asked, heard };
}

const json = (body, status = 200) =>
	new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const picture = (bytes) => new Response(new Uint8Array(bytes), { headers: { "Content-Type": "image/png" } });
const handed = (secret = "token-1") => ({
	accounts: [{ email: "ada@example.org", secret, scheme: "bearer" }],
	language: "fr",
	product: "NeoMail",
});

describe("install", () => {
	it("hands the build what the page gives it", () => {
		const { win, host } = page();
		const given = handed();
		host.install(win, given);
		expect(win.mailcraftJmap).toBe(given);
		expect(typeof win.mailcraftJmapRenew).toBe("function");
		expect(typeof win.mailcraftFetchUrl).toBe("function");
	});

	it("renews with the page's session and its CSRF token, and says the session is alive", async () => {
		const { win, host, asked } = page([json({ message: { accounts: [{ secret: "token-2" }] } })]);
		const told = [];
		host.install(win, handed(), { onSession: (alive) => told.push(alive) });
		const answer = await win.mailcraftJmapRenew();
		expect(answer).toEqual({ accounts: [{ secret: "token-2" }] });
		expect(asked[0].url).toBe("/api/method/frappe_webmail.mailcraft_jmap.renew");
		expect(asked[0].init.method).toBe("POST");
		expect(asked[0].init.credentials).toBe("same-origin");
		expect(asked[0].init.headers["X-Frappe-CSRF-Token"]).toBe("csrf-1");
		expect(told).toEqual([true]);
	});

	it("says the session ended when the renewal is refused, or the page's token is stale", async () => {
		for (const refusal of [
			json({}, 401),
			json({}, 403),
			json({ exc_type: "CSRFTokenError" }, 400),
		]) {
			const { win, host } = page([refusal]);
			const told = [];
			host.install(win, handed(), { onSession: (alive) => told.push(alive) });
			expect(await win.mailcraftJmapRenew()).toBeNull();
			expect(told).toEqual([false]);
		}
	});

	it("says nothing of the session for another failure", async () => {
		for (const failure of [json({}, 500), json({ exc_type: "ValidationError" }, 400)]) {
			const { win, host } = page([failure]);
			const told = [];
			host.install(win, handed(), { onSession: (alive) => told.push(alive) });
			expect(await win.mailcraftJmapRenew()).toBeNull();
			expect(told).toEqual([]);
		}
	});

	it("fetches no picture without a mailbox's token", () => {
		const { win, host } = page();
		win.mailcraftFetchUrl = () => "left from before";
		host.install(win, { accounts: [] });
		expect(win.mailcraftFetchUrl).toBeUndefined();
		expect(typeof win.mailcraftJmapRenew).toBe("function");
	});
});

describe("mailcraftFetchUrl", () => {
	it("asks the server for the picture with the facade's token, never the page's cookie", async () => {
		const { win, host, asked } = page([picture([1, 2, 3])]);
		host.install(win, handed("token-1"));
		const got = await win.mailcraftFetchUrl("https://pictures.example.net/a.png");
		expect(got.status).toBe(200);
		expect(got.contentType).toBe("image/png");
		expect(Array.from(got.bytes)).toEqual([1, 2, 3]);
		expect(asked[0].url).toBe("/api/method/frappe_webmail.mailcraft_jmap.picture");
		expect(asked[0].init.credentials).toBe("omit");
		expect(asked[0].init.referrerPolicy).toBe("no-referrer");
		expect(asked[0].init.headers.Authorization).toBe("Bearer token-1");
		expect(JSON.parse(asked[0].init.body)).toEqual({ url: "https://pictures.example.net/a.png" });
	});

	it("renews a refused token once, then asks again with the new one", async () => {
		const { win, host, asked } = page([
			json({}, 401),
			json({ message: { accounts: [{ secret: "token-2" }] } }),
			picture([9]),
		]);
		host.install(win, handed("token-1"));
		const got = await win.mailcraftFetchUrl("https://pictures.example.net/b.png");
		expect(Array.from(got.bytes)).toEqual([9]);
		expect(asked.map((a) => a.url.split(".").pop())).toEqual(["picture", "renew", "picture"]);
		expect(asked[2].init.headers.Authorization).toBe("Bearer token-2");
	});

	it("says the session ended when the new token is refused too", async () => {
		const { win, host } = page([json({}, 403), json({}, 403), json({}, 403)]);
		host.install(win, handed(), { sessionEnded: "Session ended." });
		await expect(win.mailcraftFetchUrl("https://pictures.example.net/c.png")).rejects.toThrow(
			"Session ended."
		);
	});

	it("waits while the server is busy, and tells what it said of a picture it would not fetch", async () => {
		const busy = page([json({}, 503), picture([7])]);
		busy.host.install(busy.win, handed());
		expect(Array.from((await busy.win.mailcraftFetchUrl("https://x.example/1.png")).bytes)).toEqual([7]);
		const refused = page([json({ detail: "Not a picture" }, 422), json({}, 500)]);
		refused.host.install(refused.win, handed());
		await expect(refused.win.mailcraftFetchUrl("https://x.example/2.png")).rejects.toThrow("Not a picture");
		await expect(refused.win.mailcraftFetchUrl("https://x.example/3.png")).rejects.toThrow("HTTP 500");
	});

	it("asks for two pictures at a time", async () => {
		const pending = [];
		const { win, host, asked } = page(
			Array.from({ length: 3 }, () => () => new Promise((give) => pending.push(give)))
		);
		host.install(win, handed());
		const all = [1, 2, 3].map((n) => win.mailcraftFetchUrl(`https://x.example/${n}.png`));
		await new Promise((go) => setTimeout(go, 0));
		expect(asked.length).toBe(2);
		pending[0](picture([1]));
		await vi.waitFor(() => expect(asked.length).toBe(3));
		pending[1](picture([2]));
		pending[2](picture([3]));
		expect((await Promise.all(all)).map((got) => got.bytes[0])).toEqual([1, 2, 3]);
	});
});

describe("listen", () => {
	it("hears only its frame, on the page's own origin, and only the messages it names", () => {
		const { win, host, heard } = page();
		const frame = { contentWindow: { name: "neomail" } };
		const other = { contentWindow: { name: "another frame" } };
		const dirty = [];
		const stop = host.listen(win, frame, { "mailcraft:dirty": (data) => dirty.push(data.dirty) });
		const send = (event) => heard.forEach((fn) => fn(event));
		send({ source: frame.contentWindow, origin: ORIGIN, data: { type: "mailcraft:dirty", dirty: true } });
		send({ source: other.contentWindow, origin: ORIGIN, data: { type: "mailcraft:dirty", dirty: false } });
		send({
			source: frame.contentWindow,
			origin: "https://elsewhere.example",
			data: { type: "mailcraft:dirty", dirty: false },
		});
		send({ source: frame.contentWindow, origin: ORIGIN, data: "mailcraft:dirty" });
		send({ source: frame.contentWindow, origin: ORIGIN, data: { type: "toString" } });
		send({ source: frame.contentWindow, origin: ORIGIN, data: { type: "mailcraft:other" } });
		expect(dirty).toEqual([true]);
		stop();
		expect(heard.length).toBe(0);
	});

	it("hears nothing before the frame has a window", () => {
		const { win, host, heard } = page();
		const frame = { contentWindow: null };
		const said = [];
		host.listen(win, frame, { "mailcraft:dirty": (data) => said.push(data) });
		heard.forEach((fn) => fn({ source: null, origin: ORIGIN, data: { type: "mailcraft:dirty" } }));
		expect(said).toEqual([]);
	});
});

describe("guardLeaving", () => {
	// A desk's router as Frappe's: push_state changes the address, then routes; the back button routes alone.
	function desk(holding) {
		const { win, host } = page();
		const history = [];
		win.location.href = "https://erp.example.org/app/neomail";
		win.history = {
			pushState: (state, title, url) => {
				history.push(url);
				const at = new URL(url, win.location.href);
				win.location.pathname = at.pathname;
				win.location.search = at.search;
			},
		};
		const routed = [];
		const router = {
			route() {
				routed.push(win.location.pathname + win.location.search);
				return "routed";
			},
			push_state(url) {
				win.history.pushState(null, null, url);
				return this.route();
			},
		};
		const asks = [];
		const unguard = host.guardLeaving(win, router, holding, (leave) => asks.push(leave));
		return { win, router, history, routed, asks, unguard };
	}

	it("lets the router go where the page does not hold work", () => {
		const { router, routed, asks, history } = desk(() => null);
		expect(router.push_state("/app/todo")).toBe("routed");
		expect(routed).toEqual(["/app/todo"]);
		expect(asks).toEqual([]);
		expect(history).toEqual(["/app/todo"]);
	});

	it("asks before a link leaves, and goes on only when the person says so", () => {
		const paths = [];
		const { router, routed, asks, history } = desk((path) => {
			paths.push(path);
			return path === "/app/neomail" ? null : "/app/neomail?build=ucs";
		});
		router.push_state("/app/todo?status=Open");
		expect(paths).toEqual(["/app/todo"]);
		expect(history).toEqual([], "the address did not change while the person decides");
		expect(routed).toEqual([]);
		expect(asks.length).toBe(1);
		asks[0]();
		expect(history).toEqual(["/app/todo?status=Open"]);
		expect(routed).toEqual(["/app/todo?status=Open"], "asked once, not again by the route that follows");
	});

	it("puts the page's address back after the back button, and leaves for the one asked when told to", async () => {
		const { win, router, routed, asks, history } = desk((path) =>
			path === "/app/neomail" ? null : "/app/neomail?build=ucs"
		);
		// The browser went back already: the address is the previous page's
		win.location.pathname = "/app/todo";
		win.location.search = "?status=Open";
		await router.route();
		expect(history).toEqual(["/app/neomail?build=ucs"], "pushed, so the previous page stays behind it");
		expect(routed).toEqual([]);
		asks[0]();
		expect(history[1]).toEqual("/app/todo?status=Open");
		expect(routed).toEqual(["/app/todo?status=Open"]);
	});

	it("takes the guard off", () => {
		const { router, unguard, asks, routed } = desk(() => "/app/neomail");
		unguard();
		expect(router.push_state("/app/todo")).toBe("routed");
		expect(routed).toEqual(["/app/todo"]);
		expect(asks).toEqual([]);
	});
});
