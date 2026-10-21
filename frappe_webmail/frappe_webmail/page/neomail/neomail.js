// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/*
 * The desk's page /app/neomail (neomail.py): NeoMail's browser build in one frame, given what /neomail gives it, and
 * the desk's menu lent to NeoMail's navigation. Offered only where the site says so (`neomail_in_desk`); elsewhere the
 * page says NeoMail is not offered here. The contract: neoffice-apps, docs/neomail-desk-menu-contract.md.
 *
 * - The handover holds tokens: it is asked for each time the page opens (neomail.hand_over), never written into this
 *   script, which the desk keeps in the browser's storage. NeoMail starts only once the page is in front, and its
 *   handover (`mailcraftJmap`, the mailboxes and their tokens) is on the window only while the page is in front; the
 *   functions the frame calls (the tokens' renewal, the pictures' fetching) stay while it works under the hidden page,
 *   since a renewal it would ask for then, without them, would leave the mailbox asking for a reload. It asks NeoMail
 *   to leave its navigation to the desk's menu (`chrome: "menu"`) where the menu can draw it (NeoCockpit on, with its
 *   setPageNav); elsewhere NeoMail keeps its own.
 * - NeoMail says where it is (`mailcraft:state`): its favourites, its mailboxes and their folders go into the menu
 *   (neomailHost.navSections), its views into the menu's dock (a row of icons always in sight; at the end of the
 *   navigation with a cockpit that has none), and the menu's search box searches in NeoMail where the cockpit lends it.
 *   A click there asks NeoMail (`mailcraft:command`).
 * - An address may ask NeoMail to open something (the webmail's links, which lead here: a message by its account,
 *   folder and UID, a folder, a new message; or a message by its JMAP id): the page takes it off the address, asks
 *   the server the message's JMAP id (neomail.message_key), and once NeoMail said where it is, sends `message.open`,
 *   or `folder.select` of its folder when this NeoMail does not open a message by its id.
 * - All the space: while the page is in front, the desk's panel draws no border, rounding or padding around it
 *   (`neomail-desk-full` on the body, neomail.css), and the frame fills the panel.
 * - Leaving the page for another of the desk keeps the frame under the hidden page, as the webmail's page keeps its
 *   app: nothing is lost, and coming back is instant. Closing the tab or reloading it would lose what the frame holds:
 *   while NeoMail says it holds such work (`mailcraft:dirty`), the browser asks first.
 * - Synk, the instance's Raven, is a fifth view after NeoMail's own (neoffice-apps, docs/raven-in-neomail-study.md,
 *   section 8): its icon in the dock carries the person's unread messages, and shows Raven's own app in a second
 *   frame, made at the first click (`/raven?embed=desk`, which Raven draws without the desk's menu), in place of
 *   NeoMail's, which stays alive under it; anything asked of NeoMail from the menu (a view, a folder, a search, an
 *   address) puts NeoMail back in front. Only for someone Raven answers: the icon waits for Raven's own count, and a
 *   refusal (no Raven role) leaves the page as it was, without a word.
 */

// The functions /neomail gives the build, shared with it (window.neomailHost): Frappe puts the file in place of the
// next line when it serves this script (render_include). The line stays a comment for linters; the file's own first
// line is a comment too, so the line Frappe leaves behind is one.
// {% include "frappe_webmail/public/js/neomail_host.js" %}

(function () {
	const HANDOVER = "/api/method/frappe_webmail.frappe_webmail.page.neomail.neomail.hand_over";
	const MESSAGE_KEY = "/api/method/frappe_webmail.frappe_webmail.page.neomail.neomail.message_key";
	const PAGE = "neomail";
	// On the body while the page is in front: the desk's panel draws nothing around it (neomail.css).
	const FULL = "neomail-desk-full";
	// On the frame of the view that is not in front, NeoMail's or Synk's: in place and at its size, out of sight and out
	// of reach (neomail.css).
	const AWAY = "neomail-desk-away";
	// Raven's methods Synk's view reads (raven/api of bvisible/Raven): the unread messages, the person's channels.
	const UNREAD = "/api/method/raven.api.raven_message.get_unread_count_for_channels";
	const CHANNELS = "/api/method/raven.api.raven_channel.get_all_channels?hide_archived=1";

	// One page for the desk's tab: its box, the banner, whether NeoMail said it holds work, whether the page is in
	// front, what NeoMail last said of where it is, and what asks it.
	const state = {
		box: null,
		banner: null,
		link: null,
		dirty: false,
		shown: false,
		where: null,
		send: null,
		lent: false,
		// The handover, put back on the window when the page comes to the front again
		host: null,
		// The handover answered while the page was hidden: NeoMail starts when the page comes to the front
		pending: null,
		// The menu's last folder click: {account, folder, from, id, seen} (neomailHost.followChoice)
		chosen: null,
		// What the address asked (neomailHost.intentOf), as NeoMail takes it: {compose}, {account, email, mailbox} or
		// {account, mailbox}; sent once (`delivered`); the message.open waiting for its answer (`opening`)
		intent: null,
		key: null,
		delivered: false,
		opening: null,
		// NeoMail's frame, once it is made
		frame: null,
		// Synk's view: whether Raven answered the person (its icon shows only then), its frame once made, whether it is
		// in front, the badge, the person's channels (a Set, null while unknown), the count being asked and whether to
		// ask it once more when it is back, whether Raven's events are listened to
		synk: {
			offered: false,
			frame: null,
			front: false,
			badge: undefined,
			mine: null,
			asking: null,
			again: false,
			listening: false,
		},
	};

	// The desk's menu, where it can draw a page's navigation: NeoCockpit is the desk's chrome (it can be switched off
	// for a site, `neoffice_cockpit_disable`, and then draws nothing) and lends its navigation to pages.
	const cockpit = () =>
		window.NeoCockpit &&
		typeof window.NeoCockpit.setPageNav === "function" &&
		document.body.classList.contains("neoffice-cockpit") &&
		!(frappe.boot && frappe.boot.neoffice_cockpit_disable)
			? window.NeoCockpit
			: null;

	// What this cockpit draws of a page's navigation beyond its sections: `dock`, `search` (an older one says nothing).
	const offers = (menu, feature) =>
		Array.isArray(menu.pageNavFeatures) && menu.pageNavFeatures.includes(feature);

	// The names of NeoMail's views and of its Favourites, in NeoMail's words: their translation in a context of their
	// own, or else the English word itself. Never what other apps made of the same English word, which is what Frappe
	// gives when a context has no translation (« Mail » read « Messagerie », « People » « Personnes », « Notes »
	// « Remarques »). French « Notes » is the English word: it has no entry (no msgstr may repeat its msgid) and shows
	// as it is.
	const own = (translated, text, context) =>
		frappe._messages && frappe._messages[text + ":" + context] ? translated : text;
	const texts = () => ({
		favorites: own(__("Favourites", null, "NeoMail pane"), "Favourites", "NeoMail pane"),
		mail: own(__("Mail", null, "NeoMail view"), "Mail", "NeoMail view"),
		calendar: own(__("Calendar", null, "NeoMail view"), "Calendar", "NeoMail view"),
		people: own(__("People", null, "NeoMail view"), "People", "NeoMail view"),
		notes: own(__("Notes", null, "NeoMail view"), "Notes", "NeoMail view"),
		// The product's name, as the desk's menu and Raven's own app show it
		synk: "Synk",
	});

	// Asks NeoMail, putting it back in front if Synk was; a folder chosen in the menu is remembered with the list it was
	// chosen from, and the menu is drawn again at once: NeoMail never says the same state twice, so a favourite of the
	// folder already shown (lit in its mailbox's section) would otherwise stay unlit.
	function ask(name, params, from) {
		if (!state.send) return null;
		show_synk(false);
		const id = state.send(name, params);
		if (name === "folder.select") {
			state.chosen = window.neomailHost.followChoice({ ...params, from, id }, state.where);
			lend();
		}
		return id;
	}

	// The address the navigation belongs to: the menu draws it only there (its pageNav.ts compares whole paths).
	const page_route = () =>
		frappe.router && typeof frappe.router.make_url === "function"
			? frappe.router.make_url([PAGE])
			: "/app/" + PAGE;

	// The menu lent NeoMail's navigation, as NeoMail last said it is, while the page is in front.
	function lend() {
		const menu = cockpit();
		if (!menu || !state.shown || !state.where || !state.send) return;
		const words = texts();
		const dock = offers(menu, "dock");
		const page = page_views(words);
		const lent = {
			app: { name: "mail", title: words.mail },
			route: page_route(),
			nav: window.neomailHost.navSections(state.where, ask, words, { dock, chosen: state.chosen, page }),
		};
		if (dock) lent.dock = window.neomailHost.viewDock(state.where, ask, words, page);
		if (offers(menu, "search")) {
			lent.search = {
				placeholder: __("Search mail"),
				onQuery: (query) => ask("search", { query: String(query || "") }),
			};
		}
		menu.setPageNav(lent);
		state.lent = true;
	}

	// The menu draws its own navigation again.
	function give_back() {
		const menu = cockpit();
		if (menu && state.lent) menu.setPageNav(null);
		state.lent = false;
	}

	// The page's own views after NeoMail's, as neomailHost.viewsOf takes them: Synk, once Raven answered the person.
	function page_views(words) {
		const synk = state.synk;
		const host = window.neomailHost;
		const views = synk.offered
			? [{ view: host.synk.view, title: words.synk, icon: host.synk.icon, badge: synk.badge, onClick: () => show_synk(true) }]
			: [];
		return { front: synk.front ? host.synk.view : null, views };
	}

	// A frame in front (`away` false), or behind the other: kept at its size, never `display: none`, which gives an egui
	// app a zero size and has it lay its panes out again (NeoMail's message list came back narrower); `inert` keeps the
	// clicks and the keyboard off it.
	function put_away(frame, away) {
		if (!frame) return;
		frame.classList.toggle(AWAY, away);
		frame.inert = away;
	}

	// Synk in front (`on`), in its own frame, made the first time; or NeoMail back in front. The frame left behind stays
	// alive under the other, as both stay under the page when the person leaves it.
	function show_synk(on) {
		const synk = state.synk;
		if (on === synk.front || (on && (!synk.offered || !state.box))) return;
		if (on && !synk.frame) {
			synk.frame = document.createElement("iframe");
			synk.frame.className = "neomail-desk-frame neomail-desk-synk";
			synk.frame.title = texts().synk;
			synk.frame.src = window.neomailHost.synk.address;
			state.box.append(synk.frame);
		}
		synk.front = on;
		put_away(synk.frame, !on);
		put_away(state.frame, on);
		const shown = on ? synk.frame : state.frame;
		if (shown && typeof shown.focus === "function") shown.focus();
		// What the person read there: the badge follows at once, without waiting for Raven's event
		if (!on) count_synk();
		lend();
	}

	// Whether Raven is here for the person at all, before asking it anything: installed, and the person holding its role.
	// Raven itself decides after that (count_synk).
	const synk_may = () =>
		Boolean(
			frappe.boot &&
				frappe.boot.versions &&
				frappe.boot.versions.raven &&
				frappe.user &&
				typeof frappe.user.has_role === "function" &&
				frappe.user.has_role("Raven User")
		);

	// One of Raven's methods, as the person (the desk's cookie, its CSRF token): its `message`, or the refusal's status.
	async function from_raven(address) {
		try {
			const answer = await fetch(address, {
				method: "GET",
				credentials: "same-origin",
				cache: "no-store",
				headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token || "" },
			});
			if (!answer.ok) return { refused: answer.status };
			return { message: (await answer.json()).message };
		} catch (e) {
			return { refused: 0 };
		}
	}

	// The person's unread messages in Raven, as Synk's badge. One question at a time: asked again while one is out, it
	// asks once more when that one is back. A refusal for the person (no Raven role: 403, 417; Raven gone: 404) takes the
	// icon away, and NeoMail comes back in front if Synk was; a network failure leaves things as they were.
	async function count_synk() {
		const synk = state.synk;
		if (!synk_may()) return;
		if (synk.asking) {
			synk.again = true;
			return;
		}
		synk.asking = from_raven(UNREAD);
		const answer = await synk.asking;
		synk.asking = null;
		if ("message" in answer) {
			const badge = window.neomailHost.synkBadge(answer.message);
			const first = !synk.offered;
			if (first || badge !== synk.badge) {
				synk.offered = true;
				synk.badge = badge;
				lend();
			}
			if (first) listen_synk();
		} else if ([401, 403, 404, 417].includes(answer.refused)) {
			if (synk.front) show_synk(false);
			synk.offered = false;
			synk.badge = undefined;
			lend();
			return;
		}
		if (synk.again) {
			synk.again = false;
			count_synk();
		}
	}

	// The person's channels and direct messages: a channel's message, broadcast to every Raven user, counts only there.
	async function know_synk_channels() {
		const answer = await from_raven(CHANNELS);
		state.synk.mine = "message" in answer ? window.neomailHost.synkChannels(answer.message) : null;
	}

	// Raven's events on the desk's own socket, once Raven answered the person. Neodesk's lessons: a channel's message is
	// broadcast to the room of everyone holding the role, which a client joins by subscribing to the « Raven User »
	// doctype (direct messages and reads come to the person's own room); `frappe.realtime.off` is never called without
	// its listener (that would take away every listener of the event, the docked chat's too); after a reconnection the
	// room is joined again and the count asked again; a tab coming back into sight asks it again too (the desk's socket
	// gives up after three tries). While the page is hidden nothing is asked: the page asks once as it comes back.
	function listen_synk() {
		const synk = state.synk;
		if (synk.listening) return;
		synk.listening = true;
		know_synk_channels();
		const recount = () => {
			if (state.shown) count_synk();
		};
		const realtime = frappe.realtime;
		if (realtime && typeof realtime.on === "function") {
			const join = () => {
				if (typeof realtime.doctype_subscribe === "function") realtime.doctype_subscribe("Raven User");
			};
			join();
			realtime.on("raven:unread_channel_count_updated", (event) => {
				const me = frappe.session && frappe.session.user;
				if (window.neomailHost.synkCountMoved(event, me, synk.mine)) recount();
			});
			realtime.on("channel_list_updated", () => {
				know_synk_channels();
				recount();
			});
			realtime.on("connect", () => {
				join();
				recount();
			});
		}
		document.addEventListener("visibilitychange", () => {
			if (document.visibilityState === "visible") recount();
		});
	}

	// Closing the tab or reloading it loses what the frame holds, whether the page is in front or not.
	function ask_before_unload() {
		window.addEventListener("beforeunload", (event) => {
			if (!state.dirty) return;
			event.preventDefault();
			event.returnValue = "";
		});
	}

	const pixels = (element, property) =>
		element ? parseFloat(getComputedStyle(element)[property]) || 0 : 0;

	// The frame fills the page down to the bottom of what shows: the inside of the desk's panel (`.main-section`, or
	// a surface's `.nc-panel`), or the window (neomailHost.frameHeight). What the page's own layout adds below the box
	// (a margin the measure does not know) would make the panel scroll: the box gives that back.
	function fit() {
		const box = state.box;
		if (!box || !box.isConnected || !state.shown) return;
		const panel = box.closest(".nc-panel, .main-section");
		const height = window.neomailHost.frameHeight({
			boxTop: box.getBoundingClientRect().top,
			panel: panel && {
				bottom: panel.getBoundingClientRect().bottom,
				borderBottom: pixels(panel, "borderBottomWidth"),
				paddingBottom: pixels(panel, "paddingBottom"),
			},
			bodyPaddingBottom: pixels(box.closest(".page-body"), "paddingBottom"),
			windowHeight: window.innerHeight,
		});
		box.style.setProperty("height", `${height}px`, "important");
		const beyond = panel ? panel.scrollHeight - panel.clientHeight : 0;
		if (beyond > 0) {
			box.style.setProperty("height", `${Math.max(300, height - beyond)}px`, "important");
		}
	}

	// A sentence in place of the frame, with a link when there is somewhere to go.
	function say(text, link, label) {
		const note = document.createElement("div");
		note.className = "neomail-desk-note";
		const words = document.createElement("p");
		words.textContent = text;
		note.append(words);
		if (link) {
			const line = document.createElement("p");
			const go = document.createElement("a");
			go.href = link;
			go.textContent = label;
			line.append(go);
			note.append(line);
		}
		state.box.append(note);
	}

	// Back to this very page after signing in, with what its address carries.
	function point_sign_in() {
		if (state.link) {
			state.link.href =
				"/login?redirect-to=" +
				encodeURIComponent(window.location.pathname + window.location.search);
		}
	}

	// The banner that says the desk session ended, with a way to sign in again.
	function make_banner() {
		const banner = document.createElement("div");
		banner.className = "neomail-desk-signin";
		banner.setAttribute("role", "alert");
		banner.hidden = true;
		banner.append(document.createTextNode(__("Your Neoffice session has ended.") + " "));
		state.link = document.createElement("a");
		state.link.textContent = __("Sign in again");
		banner.append(state.link);
		point_sign_in();
		state.box.append(banner);
		return banner;
	}

	async function ask_handover() {
		const asked = new URLSearchParams(window.location.search);
		try {
			return await fetch(HANDOVER, {
				method: "POST",
				credentials: "same-origin",
				cache: "no-store",
				headers: {
					Accept: "application/json",
					"Content-Type": "application/json",
					"X-Frappe-CSRF-Token": frappe.csrf_token || "",
				},
				body: JSON.stringify({
					sample: asked.has("sample") ? 1 : 0,
					build: asked.get("build") || "",
				}),
			});
		} catch (e) {
			return null;
		}
	}

	// What the address asks NeoMail to open, each time the page comes to the front (a link of the desk followed while
	// it is open included): from the address, and from frappe.route_options, where the desk puts the query of a link
	// it follows itself (router.js); taken off both once read (the address keeps its `build` and `sample`). True when
	// there is something to open.
	function take_intent() {
		const keys = window.neomailHost.intentKeys;
		const asked = new URLSearchParams(window.location.search);
		const options = frappe.route_options || {};
		for (const key of keys) {
			if (options[key] != null && !asked.has(key)) asked.set(key, String(options[key]));
		}
		const intent = window.neomailHost.intentOf("?" + asked.toString());
		if (frappe.route_options) {
			keys.forEach((key) => delete frappe.route_options[key]);
			if (!Object.keys(frappe.route_options).length) frappe.route_options = null;
		}
		const rest = window.neomailHost.withoutIntent(window.location.search);
		if (rest !== window.location.search) {
			window.history.replaceState(
				window.history.state,
				"",
				window.location.pathname + rest + window.location.hash
			);
		}
		if (!intent) return false;
		state.intent = intent;
		state.key = null;
		state.delivered = false;
		state.opening = null;
		return true;
	}

	// The intent as NeoMail takes it: a message by its JMAP id (the server makes it from the webmail's account, folder
	// and UID), a folder by its mailbox's id, a new message. One the server does not find (another's mailbox, a message
	// gone) is left: NeoMail opens as it would without it.
	async function resolve_intent() {
		const intent = state.intent;
		if (!intent) return;
		if (intent.compose) {
			state.key = { compose: true };
		} else if (intent.email) {
			state.key = {
				account: intent.account,
				email: intent.email,
				mailbox: window.neomailHost.mailboxOfEmail(intent.email),
			};
		} else {
			const asked = new URLSearchParams({ account: intent.account, folder: intent.folder });
			if (intent.uid) asked.set("uid", intent.uid);
			try {
				const answer = await fetch(MESSAGE_KEY + "?" + asked.toString(), {
					method: "GET",
					credentials: "same-origin",
					cache: "no-store",
					headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token || "" },
				});
				const found = answer.ok ? (await answer.json()).message : null;
				if (found && found.account && found.mailbox) state.key = found;
			} catch (e) {
				state.key = null;
			}
		}
		deliver();
	}

	// The address's intent, sent once NeoMail said where it is (it has started and read its mailboxes)
	function deliver() {
		const key = state.key;
		if (!key || state.delivered || !state.where || !state.send) return;
		state.delivered = true;
		// What the address asks is NeoMail's: it comes back in front if Synk was
		show_synk(false);
		if (key.compose) {
			ask("mail.new", {});
		} else if (key.email) {
			const id = state.send("message.open", { account: key.account, id: key.email });
			state.opening = { id, account: key.account, mailbox: key.mailbox };
		} else if (key.mailbox) {
			ask("folder.select", { account: key.account, folder: key.mailbox }, "mailbox");
		}
	}

	async function open() {
		state.banner = make_banner();
		take_intent();
		const [answer] = await Promise.all([ask_handover(), resolve_intent()]);
		if (answer && answer.status === 404) {
			// NeoMail was switched off since the desk started: its boot still says the webmail leads here, which would
			// send the link below straight back. In this tab, the webmail is the webmail again.
			if (frappe.boot) frappe.boot.neomail_in_desk = 0;
			say(__("NeoMail is not offered on this site."), "/app/webmail", __("Open the webmail"));
			return;
		}
		// The desk session ended, or this page's CSRF token is a session's that another sign-in replaced.
		if (
			answer &&
			(answer.status === 401 ||
				answer.status === 403 ||
				(await window.neomailHost.refusedAsStale(answer)))
		) {
			state.banner.hidden = false;
			return;
		}
		let given = null;
		try {
			given = answer && answer.ok ? (await answer.json()).message : null;
		} catch (e) {
			given = null;
		}
		if (!given || !given.host || !given.build_url) {
			say(__("NeoMail could not be opened. Reload the page to try again."));
			return;
		}
		// Made-up mail would pass for theirs: without a mailbox the page says so, and frames nothing. A mailbox is added
		// by its form: the webmail, where it used to be added, leads here now.
		if (given.no_mailbox) {
			say(
				__("You have no mailbox in Neoffice yet."),
				"/app/webmail-account/new",
				__("Add a mailbox")
			);
			return;
		}
		state.pending = given;
		if (state.shown) start();
	}

	// NeoMail in its frame, from the handover the page was given, once the page is in front.
	function start() {
		const given = state.pending;
		state.pending = null;
		// A desk whose menu cannot draw NeoMail's navigation (NeoCockpit off or missing): NeoMail keeps its own.
		if (!cockpit()) delete given.host.chrome;
		// What the build reads from the page that frames it, there before the frame starts.
		state.host = given.host;
		window.neomailHost.install(window, given.host, {
			sessionEnded: __("Your Neoffice session has ended."),
			onSession: (alive) => (state.banner.hidden = alive),
		});
		const frame = document.createElement("iframe");
		frame.className = "neomail-desk-frame";
		frame.title = "NeoMail";
		frame.src = given.build_url;
		state.frame = frame;
		// Synk was put in front before NeoMail was made: NeoMail stays under it
		put_away(frame, state.synk.front);
		state.send = window.neomailHost.commander(window, frame);
		window.neomailHost.listen(window, frame, {
			// Whether closing it would lose work: said as it starts, then at each change
			"mailcraft:dirty": (data) => (state.dirty = data.dirty === true),
			// Where it is, once it started and at each change: the desk's menu follows
			"mailcraft:state": (data) => {
				state.where = data;
				state.chosen = window.neomailHost.followChoice(state.chosen, data);
				lend();
				deliver();
			},
			// A command it refused: the menu reflects what NeoMail says next, the console keeps why
			"mailcraft:command-done": (data) => {
				const opening = state.opening;
				if (opening && opening.id === data.id) {
					state.opening = null;
					// A NeoMail that does not open a message by its id (older than the command): its folder, quietly
					if (data.ok === false && opening.mailbox) {
						ask("folder.select", { account: opening.account, folder: opening.mailbox }, "mailbox");
					}
					return;
				}
				if (data.ok === false) {
					console.warn("NeoMail refused a command from the desk's menu", data.id, data.error);
					if (state.chosen && state.chosen.id === data.id) state.chosen = null;
				}
			},
		});
		state.box.append(frame);
	}

	function front(on) {
		state.shown = on;
		document.body.classList.toggle(FULL, on);
		// The handover (the mailboxes and their tokens) is on the window only while the page is in front: NeoMail reads
		// it as it starts, and a frame that starts again (a reload) finds it there. The functions the frame calls stay
		// (see above).
		if (on && state.host) window.mailcraftJmap = state.host;
		else if (!on) delete window.mailcraftJmap;
		// The frame scrolls, the desk does not
		document.documentElement.style.overflow = on ? "hidden" : "";
		document.body.style.overflow = on ? "hidden" : "";
	}

	frappe.pages[PAGE].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("NeoMail"),
			single_column: true,
		});
		wrapper.page = page;
		// NeoMail has its own ribbon: no page header above it.
		const head = wrapper.querySelector(".page-head");
		if (head) head.style.display = "none";

		state.box = document.createElement("div");
		state.box.className = "neomail-desk";
		page.main.html("").append(state.box);

		window.addEventListener("resize", frappe.utils.debounce(fit, 150));
		// The desk hides the page itself; a dialog's or a dropdown's own `hide.bs.*`, bubbling from inside it, is not that.
		$(wrapper).on("hide", (event) => {
			if (event.namespace || event.target !== wrapper) return;
			front(false);
			give_back();
		});
		ask_before_unload();
		open();
		// Synk's icon, once Raven answers the person
		count_synk();
	};

	// Each time the page comes to the front, its first time included.
	frappe.pages[PAGE].on_page_show = function () {
		front(true);
		if (state.pending) start();
		// A link followed while the page was open (or hidden) asks NeoMail something too
		if (take_intent()) resolve_intent();
		point_sign_in();
		lend();
		// What was read elsewhere in the desk meanwhile (its docked chat, another tab)
		if (state.synk.listening) count_synk();
		requestAnimationFrame(fit);
		setTimeout(fit, 400);
	};
})();
