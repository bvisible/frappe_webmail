// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/*
 * What a page that frames NeoMail's browser build gives it. The build reads these from the page that frames it (same
 * origin, apps/mailcraft-web/src/host.rs of bvisible/mailcraft):
 * - `window.mailcraftJmap`: the person's mailboxes, their language, the product's name, where signatures are written;
 * - `window.mailcraftJmapRenew()`: new facade tokens for the page's desk session, when the build's were refused;
 * - `window.mailcraftFetchUrl(url)`: a picture on the web that a message links to, fetched by the server.
 * And what the page and the build tell each other by `postMessage` on their common origin: the build says whether it
 * holds unsent work (`mailcraft:dirty`) and, with `chrome: "menu"`, where it is (`mailcraft:state`), which the desk's
 * page turns into the desk's menu (`navSections`); the page asks it to do things (`mailcraft:command`, `commander`).
 * The contract: neoffice-apps, docs/neomail-desk-menu-contract.md.
 *
 * /neomail (www/neomail.html) and the desk's page /app/neomail (page/neomail/neomail.js) both include this file where
 * they are rendered (Jinja's include, Frappe's render_include): it holds no template delimiter of Jinja.
 */
window.neomailHost = (function () {
	const RENEW = "/api/method/frappe_webmail.mailcraft_jmap.renew";
	const PICTURE = "/api/method/frappe_webmail.mailcraft_jmap.picture";
	// The pictures asked of the server at once, and how long one waits for its turn when the server is busy.
	const AT_ONCE = 2;
	const PATIENCE_MS = 50000;

	// Frappe's answer to a page whose CSRF token is no longer its session's.
	async function refusedAsStale(answer) {
		if (answer.status !== 400) return false;
		try {
			return (await answer.clone().json()).exc_type === "CSRFTokenError";
		} catch (e) {
			return false;
		}
	}

	/*
	 * Give the build on `win` (the page's window) what it reads there: `handover` as `mailcraftJmap`, the renewal and
	 * the pictures' fetching. `options.sessionEnded` is what a picture refused for an ended session says, in the
	 * person's language; `options.onSession(alive)` is told when a renewal finds the desk session ended, or this page's
	 * CSRF token a session's that another sign-in replaced (false: the page offers to sign in again and come back), and
	 * when a renewal went through (true).
	 */
	function install(win, handover, options) {
		const opts = options || {};
		const told = (alive) => opts.onSession && opts.onSession(alive);
		win.mailcraftJmap = handover;

		// New facade tokens for this page's session, when the build's were refused (MailCraft calls it, then retries).
		async function renew() {
			const answer = await win.fetch(RENEW, {
				method: "POST",
				credentials: "same-origin",
				headers: {
					Accept: "application/json",
					"X-Frappe-CSRF-Token": (win.frappe && win.frappe.csrf_token) || "",
				},
			});
			// The sign-in page sends someone signed in straight back, with a page that has the new session's token.
			if (answer.status === 401 || answer.status === 403 || (await refusedAsStale(answer))) told(false);
			if (!answer.ok) return null;
			told(true);
			return (await answer.json()).message || null;
		}
		win.mailcraftJmapRenew = renew;
		delete win.mailcraftFetchUrl;

		// The pictures on the web a message links to, once the person asked MailCraft to show them: a page can't read
		// another site's bytes, so the server fetches them (mailcraft_jmap.picture, under MailCraft's own rules), with
		// the facade's token and never this page's cookie. Two at a time; the server fetches only a few at once for the
		// whole instance and answers 503 to one more, asked again a moment later. A promise of { status, contentType,
		// bytes }, or a failure whose message MailCraft shows where the picture would have been.
		const first = ((handover && handover.accounts) || []).find((a) => a.secret);
		if (!first) return;
		let token = first.secret;
		// The framed build renews its tokens through the page: the pictures take the new one too.
		win.mailcraftJmapRenew = async function () {
			const answer = await renew();
			const fresh = ((answer && answer.accounts) || []).find((a) => a.secret);
			if (fresh) token = fresh.secret;
			return answer;
		};
		let flying = 0;
		const waiting = [];
		const turn = () => new Promise((go) => (flying < AT_ONCE ? (flying++, go()) : waiting.push(go)));
		const done = () => {
			const next = waiting.shift();
			if (next) next();
			else flying--;
		};
		const pause = (ms) => new Promise((go) => win.setTimeout(go, ms));
		const ask = (url) =>
			win.fetch(PICTURE, {
				method: "POST",
				credentials: "omit",
				cache: "no-store",
				referrerPolicy: "no-referrer",
				headers: {
					Authorization: "Bearer " + token,
					"Content-Type": "application/json",
					Accept: "image/*, application/json",
				},
				body: JSON.stringify({ url: String(url) }),
			});
		win.mailcraftFetchUrl = async function (url) {
			const since = Date.now();
			await turn();
			try {
				let renewed = false;
				for (;;) {
					const answer = await ask(url);
					if (answer.ok) {
						const bytes = new Uint8Array(await answer.arrayBuffer());
						return { status: answer.status, contentType: answer.headers.get("Content-Type") || "", bytes };
					}
					// The token was refused (it expired with the cache, or after twelve hours): a new one, once.
					if ((answer.status === 401 || answer.status === 403) && !renewed) {
						renewed = true;
						await win.mailcraftJmapRenew();
						continue;
					}
					if (answer.status === 503 && Date.now() - since < PATIENCE_MS) {
						await pause(400 + Math.random() * 600);
						continue;
					}
					// Refused again with a new token: the session itself ended (the page's banner says it too).
					if (answer.status === 401 || answer.status === 403) throw new Error(opts.sessionEnded || "");
					let detail = "";
					try {
						detail = (await answer.json()).detail || "";
					} catch (e) {
						// No detail: the status says it
					}
					throw new Error(detail || "HTTP " + answer.status);
				}
			} finally {
				done();
			}
		};
	}

	/*
	 * Hear what the build in `frame` tells the page: `handlers[type](data)` for each message whose `type` it names, taken
	 * only from that frame's window and from the page's own origin (another page's frame, another site, or anything
	 * that is not such a message is ignored). Returns what stops listening.
	 */
	function listen(win, frame, handlers) {
		function heard(event) {
			if (!frame.contentWindow || event.source !== frame.contentWindow) return;
			if (event.origin !== win.location.origin) return;
			const data = event.data;
			if (!data || typeof data !== "object" || typeof data.type !== "string") return;
			if (!Object.prototype.hasOwnProperty.call(handlers, data.type)) return;
			handlers[data.type](data);
		}
		win.addEventListener("message", heard);
		return () => win.removeEventListener("message", heard);
	}

	/*
	 * The height that makes a page's frame end at the bottom of what shows, from the box's top (`boxTop`): the inside
	 * of NeoCockpit's panel (`panel`: its bottom, less its bottom border and padding; null without NeoCockpit) or the
	 * window's bottom (`windowHeight`), whichever is higher, less the page body's bottom padding (`bodyPaddingBottom`).
	 * None of it changes with the box's own height, so fitting again gives the same height. 300 pixels at least.
	 */
	function frameHeight(measured) {
		const panel = measured.panel;
		const inside = panel ? panel.bottom - panel.borderBottom - panel.paddingBottom : Infinity;
		const bottom = Math.min(inside, measured.windowHeight);
		return Math.max(300, Math.round(bottom - measured.bodyPaddingBottom - measured.boxTop));
	}

	// The icons of NeoMail's special folders in the desk's menu, as the webmail's folders have them (FolderTree.vue).
	const ROLE_ICONS = {
		inbox: "lucide-inbox",
		sent: "lucide-send",
		drafts: "lucide-file-pen",
		archive: "lucide-archive",
		spam: "lucide-shield-alert",
		trash: "lucide-trash-2",
		outbox: "lucide-clock",
	};
	// NeoMail's four views, in its order, with their icons in the desk's menu.
	const VIEWS = [
		["mail", "lucide-mail"],
		["calendar", "lucide-calendar"],
		["people", "lucide-users"],
		["notes", "lucide-sticky-note"],
	];
	// The deepest a folder is drawn under its parents.
	const MAX_DEPTH = 8;

	/*
	 * The desk menu's sections for what NeoMail said of itself (`mailcraft:state`): its own pane, in its order.
	 * Favourites first (`texts.favorites`), when it has any; then one section per mailbox, titled with its address, with
	 * every folder of it in NeoMail's order, under its parent (`depth`); then the four views (`texts.mail`, `calendar`,
	 * `people`, `notes`), small items at the end, the one in front marked. A folder's count of unread mail is its badge,
	 * an inbox's in the accent; the folder shown is marked while Mail is in front. A click asks NeoMail through
	 * `send(name, params)`: `folder.select` for a folder (a folder NeoMail cannot open has no click), `view.*` for a view.
	 * The cockpit's sections cannot be folded and it has no row of icons: these are its own items.
	 */
	function navSections(state, send, texts) {
		const now = state || {};
		const accounts = Array.isArray(now.accounts) ? now.accounts : [];
		const favorites = Array.isArray(now.favorites) ? now.favorites : [];
		const inMail = now.module === "mail";
		const shown = (account, folder) =>
			inMail && folder != null && account === now.account && folder === now.folder;
		const unread = (count) => (typeof count === "number" && count > 0 ? count : undefined);
		const tone = (role) => (role === "inbox" ? "accent" : undefined);
		const icon = (role) => ROLE_ICONS[role] || "lucide-folder";
		const select = (account, folder) => () => send("folder.select", { account, folder });
		const key = (account, folder) => JSON.stringify([account, folder]);
		const roles = new Map();
		for (const box of accounts) {
			for (const folder of box.folders || []) roles.set(key(box.email, folder.id), folder.role);
		}
		const nav = [];
		if (favorites.length) {
			nav.push({
				label: texts.favorites,
				items: favorites.map((favorite) => {
					const role = roles.get(key(favorite.account, favorite.folder)) || null;
					return {
						label: favorite.name,
						icon: icon(role),
						badge: unread(favorite.unread),
						badgeTone: tone(role),
						active: shown(favorite.account, favorite.folder),
						onClick: select(favorite.account, favorite.folder),
					};
				}),
			});
		}
		for (const box of accounts) {
			const folders = Array.isArray(box.folders) ? box.folders : [];
			const parentOf = new Map(folders.map((folder) => [folder.id, folder.parent]));
			// The parents NeoMail listed above a folder, however its list is ordered (none twice, a loop ends there)
			const depth = (folder) => {
				const seen = new Set([folder.id]);
				let level = 0;
				for (let up = folder.parent; up != null && parentOf.has(up) && !seen.has(up); up = parentOf.get(up)) {
					seen.add(up);
					if (++level === MAX_DEPTH) break;
				}
				return level;
			};
			nav.push({
				label: box.email,
				items: folders.map((folder) => ({
					label: folder.name,
					icon: icon(folder.role),
					depth: depth(folder) || undefined,
					badge: unread(folder.unread),
					badgeTone: tone(folder.role),
					active: shown(box.email, folder.id),
					onClick: folder.selectable === false ? undefined : select(box.email, folder.id),
				})),
			});
		}
		nav.push({
			items: VIEWS.map(([view, viewIcon]) => ({
				label: texts[view],
				icon: viewIcon,
				active: now.module === view,
				onClick: () => send("view." + view, {}),
			})),
		});
		return nav;
	}

	/*
	 * What asks NeoMail in `frame` to do something (`mailcraft:command`): `send(name, params)` posts it to the frame's
	 * window on the page's own origin, each with the next id, and gives that id (null while the frame has no window).
	 */
	function commander(win, frame) {
		let last = 0;
		return function send(name, params) {
			if (!frame.contentWindow) return null;
			last += 1;
			frame.contentWindow.postMessage(
				{ type: "mailcraft:command", id: last, name, params: params || {} },
				win.location.origin
			);
			return last;
		};
	}

	return { install, listen, frameHeight, navSections, commander, refusedAsStale };
})();
