// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/*
 * What a page that frames NeoMail's browser build gives it. The build reads these from the page that frames it (same
 * origin, apps/mailcraft-web/src/host.rs of bvisible/mailcraft):
 * - `window.mailcraftJmap`: the person's mailboxes, their language, the product's name, where signatures are written;
 * - `window.mailcraftJmapRenew()`: new facade tokens for the page's desk session, when the build's were refused;
 * - `window.mailcraftFetchUrl(url)`: a picture on the web that a message links to, fetched by the server.
 * And what the build tells the page that frames it, by `postMessage` on their common origin (`mailcraft:dirty`).
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

	return { install, listen, frameHeight, refusedAsStale };
})();
