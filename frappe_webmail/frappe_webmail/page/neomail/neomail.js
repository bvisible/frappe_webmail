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
 * - All the space: while the page is in front, the desk's panel draws no border, rounding or padding around it
 *   (`neomail-desk-full` on the body, neomail.css), and the frame fills the panel.
 * - Leaving the page for another of the desk keeps the frame under the hidden page, as the webmail's page keeps its
 *   app: nothing is lost, and coming back is instant. Closing the tab or reloading it would lose what the frame holds:
 *   while NeoMail says it holds such work (`mailcraft:dirty`), the browser asks first.
 */

// The functions /neomail gives the build, shared with it (window.neomailHost): Frappe puts the file in place of the
// next line when it serves this script (render_include). The line stays a comment for linters; the file's own first
// line is a comment too, so the line Frappe leaves behind is one.
// {% include "frappe_webmail/public/js/neomail_host.js" %}

(function () {
	const HANDOVER = "/api/method/frappe_webmail.frappe_webmail.page.neomail.neomail.hand_over";
	const PAGE = "neomail";
	// On the body while the page is in front: the desk's panel draws nothing around it (neomail.css).
	const FULL = "neomail-desk-full";

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
	});

	// Asks NeoMail; a folder chosen in the menu is remembered with the list it was chosen from, and the menu is drawn
	// again at once: NeoMail never says the same state twice, so a favourite of the folder already shown (lit in its
	// mailbox's section) would otherwise stay unlit.
	function ask(name, params, from) {
		if (!state.send) return null;
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
		const lent = {
			app: { name: "mail", title: words.mail },
			route: page_route(),
			nav: window.neomailHost.navSections(state.where, ask, words, { dock, chosen: state.chosen }),
		};
		if (dock) lent.dock = window.neomailHost.viewDock(state.where, ask, words);
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

	async function open() {
		state.banner = make_banner();
		const answer = await ask_handover();
		if (answer && answer.status === 404) {
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
		// Made-up mail would pass for theirs: without a mailbox the page says so, and frames nothing.
		if (given.no_mailbox) {
			say(
				__("You have no mailbox in Neoffice yet."),
				"/app/webmail",
				__("Open the webmail to add one")
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
		state.send = window.neomailHost.commander(window, frame);
		window.neomailHost.listen(window, frame, {
			// Whether closing it would lose work: said as it starts, then at each change
			"mailcraft:dirty": (data) => (state.dirty = data.dirty === true),
			// Where it is, once it started and at each change: the desk's menu follows
			"mailcraft:state": (data) => {
				state.where = data;
				state.chosen = window.neomailHost.followChoice(state.chosen, data);
				lend();
			},
			// A command it refused: the menu reflects what NeoMail says next, the console keeps why
			"mailcraft:command-done": (data) => {
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
	};

	// Each time the page comes to the front, its first time included.
	frappe.pages[PAGE].on_page_show = function () {
		front(true);
		if (state.pending) start();
		point_sign_in();
		lend();
		requestAnimationFrame(fit);
		setTimeout(fit, 400);
	};
})();
