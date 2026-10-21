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

describe("frameHeight", () => {
	// NeoCockpit: a 100vh frame with 8px of padding around a panel with a 1px border, which scrolls; the desk's page
	// body has 15px of padding under the box.
	const cockpit = {
		boxTop: 70,
		panel: { bottom: 892, borderBottom: 1, paddingBottom: 0 },
		bodyPaddingBottom: 15,
		windowHeight: 900,
	};

	it("ends the box inside NeoCockpit's panel, above the page body's padding", () => {
		expect(window_host().frameHeight(cockpit)).toBe(892 - 1 - 15 - 70);
		const padded = { ...cockpit, panel: { ...cockpit.panel, paddingBottom: 6 } };
		expect(window_host().frameHeight(padded)).toBe(892 - 1 - 6 - 15 - 70);
	});

	it("reads nothing the box's own height changes: fitting again gives the same height", () => {
		const host = window_host();
		const first = host.frameHeight(cockpit);
		expect(host.frameHeight(cockpit)).toBe(first);
		expect(host.frameHeight({ ...cockpit })).toBe(first);
	});

	it("ends at the window's bottom without NeoCockpit, and never below it", () => {
		const host = window_host();
		expect(host.frameHeight({ ...cockpit, panel: null })).toBe(900 - 15 - 70);
		expect(host.frameHeight({ ...cockpit, panel: { bottom: 2000, borderBottom: 1, paddingBottom: 0 } })).toBe(
			900 - 15 - 70
		);
	});

	it("keeps the frame usable in a window too small for it", () => {
		expect(window_host().frameHeight({ ...cockpit, windowHeight: 200, panel: null })).toBe(300);
	});
});

function window_host() {
	return page().host;
}

// What NeoMail says of itself (docs/neomail-desk-menu-contract.md, section 2): two mailboxes, favourites, folders
// under folders, listed in NeoMail's order.
const STATE = {
	type: "mailcraft:state",
	module: "mail",
	account: "ada@example.org",
	folder: "F-projects",
	favorites: [
		{ account: "ada@example.org", folder: "F-inbox", name: "Boîte de réception - ada@example.org", unread: 3 },
		{ account: "team@example.org", folder: "T-sent", name: "Éléments envoyés - team@example.org", unread: 0 },
	],
	accounts: [
		{
			email: "ada@example.org",
			name: "Ada Marlow",
			unread: 3,
			folders: [
				{ id: "F-inbox", name: "Boîte de réception", role: "inbox", parent: null, unread: 3, selectable: true },
				{ id: "F-clients", name: "Clients", role: null, parent: "F-inbox", unread: 0, selectable: true },
				{ id: "F-projects", name: "Projets", role: null, parent: "F-clients", unread: 2, selectable: true },
				{ id: "F-sent", name: "Éléments envoyés", role: "sent", parent: null, unread: 0, selectable: true },
				{ id: "F-shelf", name: "Rayon", role: null, parent: null, unread: 0, selectable: false },
			],
		},
		{
			email: "team@example.org",
			name: "",
			unread: 1,
			folders: [
				{ id: "T-inbox", name: "Boîte de réception", role: "inbox", parent: null, unread: 1, selectable: true },
				{ id: "T-sent", name: "Éléments envoyés", role: "sent", parent: null, unread: 0, selectable: true },
				{ id: "T-trash", name: "Éléments supprimés", role: "trash", parent: null, unread: 0, selectable: true },
			],
		},
	],
};
const TEXTS = { favorites: "Favoris", mail: "Courrier", calendar: "Calendrier", people: "Contacts", notes: "Notes" };

describe("navSections", () => {
	function lent(state = STATE) {
		const sent = [];
		const nav = page().host.navSections(state, (name, params) => sent.push({ name, params }), TEXTS);
		return { nav, sent };
	}

	it("reproduces NeoMail's pane: favourites, then each mailbox with all its folders, then the views", () => {
		const { nav } = lent();
		expect(nav.map((section) => section.label)).toEqual([
			"Favoris",
			"ada@example.org",
			"team@example.org",
			undefined,
		]);
		expect(nav[0].items.map((item) => item.label)).toEqual([
			"Boîte de réception - ada@example.org",
			"Éléments envoyés - team@example.org",
		]);
		expect(nav[1].items.map((item) => item.label)).toEqual([
			"Boîte de réception",
			"Clients",
			"Projets",
			"Éléments envoyés",
			"Rayon",
		]);
		expect(nav[2].items.map((item) => item.label)).toEqual([
			"Boîte de réception",
			"Éléments envoyés",
			"Éléments supprimés",
		]);
	});

	it("draws a folder under its parents, with its unread mail, an inbox's in the accent", () => {
		const [favorites, ada, team] = lent().nav;
		expect(ada.items.map((item) => item.depth)).toEqual([undefined, 1, 2, undefined, undefined]);
		expect(ada.items.map((item) => item.badge)).toEqual([3, undefined, 2, undefined, undefined]);
		expect(ada.items.map((item) => item.badgeTone)).toEqual(["accent", undefined, undefined, undefined, undefined]);
		expect(ada.items.map((item) => item.icon)).toEqual([
			"lucide-inbox",
			"lucide-folder",
			"lucide-folder",
			"lucide-send",
			"lucide-folder",
		]);
		expect(team.items.map((item) => item.icon)).toEqual(["lucide-inbox", "lucide-send", "lucide-trash-2"]);
		// A favourite has its folder's look: an inbox's count in the accent, a sent folder's icon
		expect(favorites.items.map((item) => [item.icon, item.badge, item.badgeTone])).toEqual([
			["lucide-inbox", 3, "accent"],
			["lucide-send", undefined, undefined],
		]);
	});

	it("marks the folder shown, in its mailbox only, while Mail is in front", () => {
		const active = (nav) =>
			nav.flatMap((section) => section.items.filter((item) => item.active).map((item) => item.label));
		expect(active(lent().nav)).toEqual(["Projets", "Courrier"]);
		const inbox = { ...STATE, folder: "F-inbox" };
		expect(active(lent(inbox).nav)).toEqual([
			"Boîte de réception - ada@example.org",
			"Boîte de réception",
			"Courrier",
		]);
		// The same folder's id in another mailbox is another folder
		expect(active(lent({ ...STATE, account: "team@example.org", folder: "F-inbox" }).nav)).toEqual(["Courrier"]);
		// Several folders, a search: none
		expect(active(lent({ ...STATE, folder: null }).nav)).toEqual(["Courrier"]);
		// Another view in front: the folders stay, that view is marked
		const calendar = lent({ ...STATE, module: "calendar" }).nav;
		expect(calendar.length).toBe(4);
		expect(active(calendar)).toEqual(["Calendrier"]);
	});

	it("asks NeoMail for the folder or the view clicked, and nothing for a folder it cannot open", () => {
		const { nav, sent } = lent();
		nav[0].items[1].onClick();
		nav[1].items[2].onClick();
		nav[2].items[0].onClick();
		expect(nav[1].items[4].onClick).toBeUndefined();
		nav[3].items.forEach((item) => item.onClick());
		expect(sent).toEqual([
			{ name: "folder.select", params: { account: "team@example.org", folder: "T-sent" } },
			{ name: "folder.select", params: { account: "ada@example.org", folder: "F-projects" } },
			{ name: "folder.select", params: { account: "team@example.org", folder: "T-inbox" } },
			{ name: "view.mail", params: {} },
			{ name: "view.calendar", params: {} },
			{ name: "view.people", params: {} },
			{ name: "view.notes", params: {} },
		]);
	});

	it("draws the four views, small items with their icons, the last section", () => {
		const views = lent().nav.at(-1);
		expect(views.label).toBeUndefined();
		expect(views.items.map((item) => [item.label, item.icon])).toEqual([
			["Courrier", "lucide-mail"],
			["Calendrier", "lucide-calendar"],
			["Contacts", "lucide-users"],
			["Notes", "lucide-sticky-note"],
		]);
	});

	it("takes a state with nothing yet, folders listed before their parents, and a loop", () => {
		expect(lent({ type: "mailcraft:state", module: "mail" }).nav.length).toBe(1);
		const odd = {
			module: "mail",
			accounts: [
				{
					email: "ada@example.org",
					folders: [
						{ id: "c", name: "C", parent: "b" },
						{ id: "b", name: "B", parent: "a" },
						{ id: "a", name: "A", parent: null },
						{ id: "x", name: "X", parent: "y" },
						{ id: "y", name: "Y", parent: "x" },
						{ id: "lost", name: "Lost", parent: "gone" },
					],
				},
			],
		};
		expect(lent(odd).nav[0].items.map((item) => [item.label, item.depth])).toEqual([
			["C", 2],
			["B", 1],
			["A", undefined],
			["X", 1],
			["Y", 1],
			["Lost", undefined],
		]);
	});
});

describe("commander", () => {
	it("posts each command to the frame on the page's own origin, with the next id", () => {
		const { win, host } = page();
		const posted = [];
		const frame = { contentWindow: { postMessage: (message, origin) => posted.push([message, origin]) } };
		const send = host.commander(win, frame);
		expect(send("folder.select", { account: "ada@example.org", folder: "F-inbox" })).toBe(1);
		expect(send("view.calendar")).toBe(2);
		expect(posted).toEqual([
			[
				{
					type: "mailcraft:command",
					id: 1,
					name: "folder.select",
					params: { account: "ada@example.org", folder: "F-inbox" },
				},
				ORIGIN,
			],
			[{ type: "mailcraft:command", id: 2, name: "view.calendar", params: {} }, ORIGIN],
		]);
	});

	it("sends nothing while the frame has no window", () => {
		const { win, host } = page();
		expect(host.commander(win, { contentWindow: null })("view.mail")).toBeNull();
	});
});
