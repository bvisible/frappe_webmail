// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/*
 * The desk's page /app/neomail (neomail.py): NeoMail's browser build in one frame, given what /neomail gives it, and
 * the desk's menu lent to NeoMail's navigation. Offered only where the site says so (`neomail_in_desk`); elsewhere the
 * page says NeoMail is not offered here. The contract: neoffice-apps, docs/neomail-desk-menu-contract.md.
 *
 * - The handover holds tokens: it is asked for each time the page opens (neomail.hand_over), never written into this
 *   script, which the desk keeps in the browser's storage. It asks NeoMail to leave its navigation to the desk's menu
 *   (`chrome: "menu"`), where the menu can draw it (NeoCockpit's setPageNav); elsewhere NeoMail keeps its own.
 * - NeoMail says where it is (`mailcraft:state`): its favourites, its mailboxes and their folders, its views go into
 *   the menu (neomailHost.navSections), and a click there asks NeoMail (`mailcraft:command`).
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
	};

	// The desk's menu, where it can draw a page's navigation.
	const cockpit = () =>
		window.NeoCockpit && typeof window.NeoCockpit.setPageNav === "function"
			? window.NeoCockpit
			: null;

	// The address the navigation belongs to: the menu draws it only there (its pageNav.ts compares whole paths).
	const page_route = () =>
		frappe.router && typeof frappe.router.make_url === "function"
			? frappe.router.make_url([PAGE])
			: "/app/" + PAGE;

	// The menu lent NeoMail's navigation, as NeoMail last said it is, while the page is in front.
	function lend() {
		const menu = cockpit();
		if (!menu || !state.shown || !state.where || !state.send) return;
		menu.setPageNav({
			app: { name: "mail", title: __("Mail") },
			route: page_route(),
			nav: window.neomailHost.navSections(state.where, state.send, {
				favorites: __("Favorites"),
				mail: __("Mail"),
				calendar: __("Calendar"),
				people: __("People"),
				notes: __("Notes"),
			}),
		});
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
		// A desk whose menu cannot draw NeoMail's navigation (no NeoCockpit): NeoMail keeps its own.
		if (!cockpit()) delete given.host.chrome;
		// What the build reads from the page that frames it, there before the frame starts.
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
				lend();
			},
			// A command it refused: the menu reflects what NeoMail says next, the console keeps why
			"mailcraft:command-done": (data) => {
				if (data.ok === false) {
					console.warn("NeoMail refused a command from the desk's menu", data.id, data.error);
				}
			},
		});
		state.box.append(frame);
	}

	function front(on) {
		state.shown = on;
		document.body.classList.toggle(FULL, on);
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
		point_sign_in();
		lend();
		requestAnimationFrame(fit);
		setTimeout(fit, 400);
	};
})();
