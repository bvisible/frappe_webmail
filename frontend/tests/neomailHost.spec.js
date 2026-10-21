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
	function lent(state = STATE, options) {
		const sent = [];
		const nav = page().host.navSections(
			state,
			(name, params, from) => sent.push(from ? { name, params, from } : { name, params }),
			TEXTS,
			options
		);
		return { nav, sent };
	}
	const active = (nav) =>
		nav.flatMap((section) =>
			section.items.filter((item) => item.active).map((item) => (section.label || "") + " › " + item.label)
		);

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

	it("draws a folder under its parents, with its unread mail from a NeoMail that gives no count", () => {
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

	it("shows the number NeoMail's pane shows: its count, a total in brackets, nothing when it shows none", () => {
		const counted = structuredClone(STATE);
		const [inbox, clients, projects, sent] = counted.accounts[0].folders;
		inbox.count = { value: 3, kind: "unread" };
		clients.count = null;
		projects.count = { value: 5, kind: "total" };
		sent.count = { value: 0, kind: "unread" };
		counted.accounts[1].folders[1].count = { value: 2, kind: "total" };
		const [favorites, ada] = lent(counted).nav;
		// `count` decides, not `unread`: the projects' 2 unread give way to its total, the inbox's tone stays
		expect(ada.items.map((item) => item.badge)).toEqual([3, undefined, "[5]", 0, undefined]);
		expect(ada.items[0].badgeTone).toBe("accent");
		// A favourite shows its folder's count: the team's Sent its total, though the favourite says 0 unread
		expect(favorites.items.map((item) => item.badge)).toEqual([3, "[2]"]);
	});

	it("marks the folder shown once, while Mail is in front: in its mailbox when NeoMail chose it", () => {
		expect(active(lent().nav)).toEqual(["ada@example.org › Projets", " › Courrier"]);
		// An inbox that is a favourite too: lit in its mailbox only, when nobody chose it from the menu
		expect(active(lent({ ...STATE, folder: "F-inbox" }).nav)).toEqual([
			"ada@example.org › Boîte de réception",
			" › Courrier",
		]);
		// The same folder's id in another mailbox is another folder
		expect(active(lent({ ...STATE, account: "team@example.org", folder: "F-inbox" }).nav)).toEqual([" › Courrier"]);
		// Several folders, a search: none
		expect(active(lent({ ...STATE, folder: null }).nav)).toEqual([" › Courrier"]);
		// Another view in front: the folders stay, that view is marked
		const calendar = lent({ ...STATE, module: "calendar" }).nav;
		expect(calendar.length).toBe(4);
		expect(active(calendar)).toEqual([" › Calendrier"]);
	});

	it("marks the folder in the list it was chosen from, until NeoMail goes elsewhere by itself", () => {
		const inbox = { ...STATE, folder: "F-inbox" };
		const fromFavorites = { account: "ada@example.org", folder: "F-inbox", from: "favorites" };
		expect(active(lent(inbox, { chosen: fromFavorites }).nav)).toEqual([
			"Favoris › Boîte de réception - ada@example.org",
			" › Courrier",
		]);
		const fromMailbox = { ...fromFavorites, from: "mailbox" };
		expect(active(lent(inbox, { chosen: fromMailbox }).nav)).toEqual([
			"ada@example.org › Boîte de réception",
			" › Courrier",
		]);
		// Chosen from Favoris, then NeoMail went to Projets by itself (the keyboard): its mailbox's section
		expect(active(lent(STATE, { chosen: fromFavorites }).nav)).toEqual([
			"ada@example.org › Projets",
			" › Courrier",
		]);
	});

	it("asks NeoMail for the folder or the view clicked, saying the list, and nothing for a folder it cannot open", () => {
		const { nav, sent } = lent();
		nav[0].items[1].onClick();
		nav[1].items[2].onClick();
		nav[2].items[0].onClick();
		expect(nav[1].items[4].onClick).toBeUndefined();
		nav[3].items.forEach((item) => item.onClick());
		expect(sent).toEqual([
			{ name: "folder.select", params: { account: "team@example.org", folder: "T-sent" }, from: "favorites" },
			{ name: "folder.select", params: { account: "ada@example.org", folder: "F-projects" }, from: "mailbox" },
			{ name: "folder.select", params: { account: "team@example.org", folder: "T-inbox" }, from: "mailbox" },
			{ name: "view.mail", params: {} },
			{ name: "view.calendar", params: {} },
			{ name: "view.people", params: {} },
			{ name: "view.notes", params: {} },
		]);
	});

	it("draws the views NeoMail offers as small items at the end, with a cockpit that has no dock", () => {
		const views = lent().nav.at(-1);
		expect(views.label).toBeUndefined();
		expect(views.items.map((item) => [item.label, item.icon])).toEqual([
			["Courrier", "lucide-mail"],
			["Calendrier", "lucide-calendar"],
			["Contacts", "lucide-users"],
			["Notes", "lucide-sticky-note"],
		]);
		const noNotes = lent({ ...STATE, views: ["mail", "calendar", "people", "tasks"] }).nav.at(-1);
		expect(noNotes.items.map((item) => item.label)).toEqual(["Courrier", "Calendrier", "Contacts"]);
	});

	it("leaves the views to the cockpit's dock when it has one", () => {
		const { nav } = lent(STATE, { dock: true });
		expect(nav.map((section) => section.label)).toEqual(["Favoris", "ada@example.org", "team@example.org"]);
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

describe("viewDock", () => {
	it("gives the cockpit's dock the views NeoMail offers, in its order, the one in front marked", () => {
		const sent = [];
		const host = page().host;
		const dock = host.viewDock({ ...STATE, module: "people" }, (name, params) => sent.push(name), TEXTS);
		expect(dock.map(({ id, title, icon, active }) => ({ id, title, icon, active }))).toEqual([
			{ id: "mail", title: "Courrier", icon: "mail", active: false },
			{ id: "calendar", title: "Calendrier", icon: "calendar", active: false },
			{ id: "people", title: "Contacts", icon: "users", active: true },
			{ id: "notes", title: "Notes", icon: "sticky-note", active: false },
		]);
		dock[3].onClick();
		expect(sent).toEqual(["view.notes"]);
		const offered = host.viewDock({ ...STATE, views: ["calendar", "mail"] }, () => {}, TEXTS);
		expect(offered.map((view) => view.id)).toEqual(["calendar", "mail"]);
	});
});

describe("followChoice", () => {
	const { followChoice } = page().host;
	const inbox = { type: "mailcraft:state", module: "mail", account: "ada@example.org", folder: "F-inbox" };
	const chosen = { account: "ada@example.org", folder: "F-inbox", from: "favorites", id: 3 };

	it("keeps a choice until NeoMail shows its folder, and while it does", () => {
		expect(followChoice(chosen, { ...inbox, folder: "F-sent" })).toBe(chosen);
		const seen = followChoice(chosen, inbox);
		expect(seen).toEqual({ ...chosen, seen: true });
		expect(followChoice(seen, inbox)).toBe(seen);
	});

	it("forgets it once NeoMail shows another folder or another view, having gone there by itself", () => {
		const seen = followChoice(chosen, inbox);
		expect(followChoice(seen, { ...inbox, folder: "F-sent" })).toBeNull();
		expect(followChoice(seen, { ...inbox, module: "calendar" })).toBeNull();
		expect(followChoice(seen, { ...inbox, folder: null })).toBeNull();
		expect(followChoice(null, inbox)).toBeNull();
	});
});

describe("what an address asks NeoMail's page", () => {
	const host = page().host;

	it("reads a message, a folder or a new message from the webmail's links and NeoMail's", () => {
		expect(host.intentOf("?compose=1&uid=4")).toEqual({ compose: true });
		expect(host.intentOf("?account=ada%40example.org&folder=Archive&uid=31")).toEqual({
			account: "ada@example.org",
			folder: "Archive",
			uid: "31",
		});
		// The webmail's links that name no folder mean the inbox
		expect(host.intentOf("?account=ada@example.org&uid=31")).toEqual({
			account: "ada@example.org",
			folder: "INBOX",
			uid: "31",
		});
		expect(host.intentOf("?account=ada@example.org&email=E7V31ZSU5CT1g")).toEqual({
			account: "ada@example.org",
			email: "E7V31ZSU5CT1g",
		});
		expect(host.intentOf("?account=ada@example.org&folder=Sent")).toEqual({
			account: "ada@example.org",
			folder: "Sent",
		});
	});

	it("asks nothing of an address without a mailbox, or with what is not a message", () => {
		for (const search of ["", "?build=ucs", "?uid=31", "?account=a@b.c", "?account=a@b.c&uid=x", "?account=a@b.c&email=nope"]) {
			expect(host.intentOf(search)).toBeNull();
		}
	});

	it("takes the intent off the address, and leaves the rest", () => {
		expect(host.withoutIntent("?build=ucs&account=a%40b.c&folder=INBOX&uid=3&sample")).toBe("?build=ucs&sample=");
		expect(host.withoutIntent("?account=a%40b.c&email=E1V2ZSU5CT1g")).toBe("");
		expect(host.withoutIntent("")).toBe("");
	});

	it("knows the folder of a message by its JMAP id", () => {
		expect(host.mailboxOfEmail("E7V31ZSU5CT1g")).toBe("MSU5CT1g");
		expect(host.mailboxOfEmail("MSU5CT1g")).toBeNull();
		expect(host.mailboxOfEmail(undefined)).toBeNull();
	});

	it("leads the webmail's addresses to NeoMail's, its signatures aside, as the server does", () => {
		expect(host.deskAddress("")).toBe("/app/neomail");
		expect(host.deskAddress("?compose=1&uid=4")).toBe("/app/neomail?compose=1");
		expect(host.deskAddress("?account=a%40example.org&uid=9&other=x")).toBe(
			"/app/neomail?account=a%40example.org&uid=9"
		);
		expect(host.deskAddress("?account=a%40example.org&email=E7V9ZSU5CT1g")).toBe(
			"/app/neomail?account=a%40example.org&email=E7V9ZSU5CT1g"
		);
		expect(host.deskAddress("?signatures=1&uid=4")).toBeNull();
	});
});

describe("badgeOf", () => {
	it("reads a folder's count as NeoMail's pane shows it, else its unread mail", () => {
		const { badgeOf } = page().host;
		expect(badgeOf({ count: { value: 4, kind: "unread" }, unread: 9 })).toBe(4);
		expect(badgeOf({ count: { value: 4, kind: "total" }, unread: 0 })).toBe("[4]");
		expect(badgeOf({ count: null, unread: 9 })).toBeUndefined();
		expect(badgeOf({ unread: 2 })).toBe(2);
		expect(badgeOf({ unread: 0 })).toBeUndefined();
		expect(badgeOf(undefined)).toBeUndefined();
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
