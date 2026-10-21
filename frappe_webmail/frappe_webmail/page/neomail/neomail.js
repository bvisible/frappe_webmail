// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/*
 * The desk's page /app/neomail (neomail.py): NeoMail's browser build in one frame, the full height under the desk's
 * header, given what /neomail gives it. Offered only where the site says so (`neomail_in_desk`); elsewhere the page
 * says NeoMail is not offered here.
 *
 * The handover holds tokens: it is asked for each time the page opens (neomail.hand_over), never written into this
 * script, which the desk keeps in the browser's storage. Leaving the page keeps the frame under the hidden page, as the
 * webmail's page keeps its app (coming back is instant); while NeoMail says it holds work that closing it would lose
 * (`mailcraft:dirty`), the page asks before the desk's router leaves it, and the browser asks before the tab goes.
 */

// The functions /neomail gives the build, shared with it (window.neomailHost): Frappe puts the file in place of the
// next line when it serves this script (render_include). The line stays a comment for linters; the file's own first
// line is a comment too, so the line Frappe leaves behind is one.
// {% include "frappe_webmail/public/js/neomail_host.js" %}

(function () {
	const HANDOVER = "/api/method/frappe_webmail.frappe_webmail.page.neomail.neomail.hand_over";
	const PAGE = "neomail";

	// One page for the desk's tab: its box, the banner, whether NeoMail said it holds work, whether the page is in
	// front, and its address there.
	const state = { box: null, banner: null, link: null, dirty: false, shown: false, here: "" };

	const page_of = (path) => (frappe.router.get_sub_path(path) || "").split("/")[0];

	// The page's address while leaving it for `path` should be asked about: NeoMail holds work and the page is left.
	const holding = (path) => (state.dirty && state.shown && page_of(path) !== PAGE ? state.here : null);

	function guard() {
		window.neomailHost.guardLeaving(window, frappe.router, holding, (leave) =>
			frappe.confirm(
				__("NeoMail still holds work that is not sent or saved. Leave this page anyway?"),
				leave
			)
		);
		// Closing the tab or reloading it loses what the frame holds, whether the page is in front or not.
		window.addEventListener("beforeunload", (event) => {
			if (!state.dirty) return;
			event.preventDefault();
			event.returnValue = "";
		});
	}

	// The frame fills the page, from where it starts down to the bottom of the desk's panel (the legacy navbar or
	// NeoCockpit's framed panel: measured, not guessed).
	function fit() {
		const box = state.box;
		if (!box || !box.isConnected || !state.shown) return;
		const panel = box.closest(".nc-panel, .content.page-container") || document.body;
		const bottom = Math.min(panel.getBoundingClientRect().bottom, window.innerHeight);
		const top = box.getBoundingClientRect().top;
		box.style.setProperty("height", `${Math.max(300, Math.round(bottom - top))}px`, "important");
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
		// What the build reads from the page that frames it, there before the frame starts.
		window.neomailHost.install(window, given.host, {
			sessionEnded: __("Your Neoffice session has ended."),
			onSession: (alive) => (state.banner.hidden = alive),
		});
		const frame = document.createElement("iframe");
		frame.className = "neomail-desk-frame";
		frame.title = "NeoMail";
		frame.src = given.build_url;
		// The frame says as it starts, then at each change, whether closing it would lose work.
		window.neomailHost.listen(window, frame, {
			"mailcraft:dirty": (data) => (state.dirty = data.dirty === true),
		});
		state.box.append(frame);
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
		const body = wrapper.querySelector(".container.page-body");
		if (body) body.classList.add("neomail-desk-body");

		state.box = document.createElement("div");
		state.box.className = "neomail-desk";
		page.main.html("").append(state.box);

		window.addEventListener("resize", frappe.utils.debounce(fit, 150));
		$(wrapper).on("hide", () => {
			state.shown = false;
			document.documentElement.style.overflow = "";
			document.body.style.overflow = "";
		});
		guard();
		open();
	};

	// Each time the page comes to the front, its first time included.
	frappe.pages[PAGE].on_page_show = function () {
		state.shown = true;
		state.here = window.location.pathname + window.location.search;
		point_sign_in();
		// The frame scrolls, the desk does not.
		document.documentElement.style.overflow = "hidden";
		document.body.style.overflow = "hidden";
		requestAnimationFrame(fit);
		setTimeout(fit, 400);
	};
})();
