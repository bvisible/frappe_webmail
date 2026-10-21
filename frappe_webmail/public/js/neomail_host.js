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
	// NeoMail's views, in its order, and their icons (lucide names, without the prefix the menu's items take).
	const VIEW_ICONS = { mail: "mail", calendar: "calendar", people: "users", notes: "sticky-note" };
	const VIEWS = Object.keys(VIEW_ICONS);
	// Synk, the instance's Raven, a view the desk's page adds after NeoMail's own (neoffice-apps,
	// docs/raven-in-neomail-study.md, section 8): Raven's app in a frame of its own, which it draws without the desk's
	// menu because it is framed by this page and asked to (`embed=desk`, Raven's apps/web/src/utils/embeddedInDesk.ts).
	const SYNK = { view: "synk", icon: "message-circle", address: "/raven?embed=desk" };
	// The deepest a folder is drawn under its parents.
	const MAX_DEPTH = 8;

	/*
	 * The number NeoMail's own pane shows beside a folder, as the menu's badge: its `count` (a total in brackets, `[4]`;
	 * nothing when the pane shows none), or, from a NeoMail that does not say it, its unread messages.
	 */
	function badgeOf(folder) {
		if (!folder) return undefined;
		if (Object.prototype.hasOwnProperty.call(folder, "count")) {
			const count = folder.count;
			if (!count || typeof count.value !== "number") return undefined;
			return count.kind === "total" ? "[" + count.value + "]" : count.value;
		}
		return typeof folder.unread === "number" && folder.unread > 0 ? folder.unread : undefined;
	}

	/*
	 * NeoMail's views as the menu shows them: those it offers here (`views`, in its order; the four from a NeoMail
	 * that does not say), each with its name (`texts[view]`), its icon, whether it is in front, and its click; then the
	 * page's own (`page.views`: {view, title, icon, badge, onClick}, Synk). While one of the page's is in front
	 * (`page.front`, its `view`), it is the one lit, and none of NeoMail's.
	 */
	function viewsOf(state, send, texts, page) {
		const now = state || {};
		const own = page || {};
		const offered = Array.isArray(now.views) ? now.views.filter((view) => VIEW_ICONS[view]) : VIEWS;
		const views = offered.map((view) => ({
			view,
			title: texts[view],
			icon: VIEW_ICONS[view],
			active: !own.front && now.module === view,
			onClick: () => send("view." + view, {}),
		}));
		for (const extra of Array.isArray(own.views) ? own.views : []) {
			views.push({ ...extra, active: own.front === extra.view });
		}
		return views;
	}

	/*
	 * The views as the menu's dock draws them: a row of icons always in sight, their names as tooltips, a view's
	 * number (Synk's unread messages) as its badge.
	 */
	function viewDock(state, send, texts, page) {
		return viewsOf(state, send, texts, page).map((view) => {
			const item = { id: view.view, title: view.title, icon: view.icon, active: view.active, onClick: view.onClick };
			if (view.badge !== undefined) item.badge = view.badge;
			return item;
		});
	}

	/* Raven's unread messages as Synk's badge: the sum of `get_unread_count_for_channels`, none at 0, « 99+ » above 99. */
	function synkBadge(counts) {
		const count = (row) => (row && Number.isFinite(row.unread_count) && row.unread_count > 0 ? row.unread_count : 0);
		const total = (Array.isArray(counts) ? counts : []).reduce((sum, row) => sum + count(row), 0);
		if (!total) return undefined;
		return total > 99 ? "99+" : total;
	}

	/*
	 * Whether one of Raven's `raven:unread_channel_count_updated` events may change the person's unread messages, so that
	 * the page asks for them again; the rules Neodesk follows (neoffice-mobile, apps/mobile/hooks/useDesktopChat.ts):
	 * - a read on another screen (`track_visit`) does;
	 * - one's own message never does (Raven counts only the others');
	 * - a direct message does: Raven sends it to its two people's rooms only;
	 * - a channel's message is broadcast to everyone holding the Raven role, its text left out: it does only in a channel
	 *   the person is a member of (`mine`, a Set of channel names; while the page does not know them, it does).
	 */
	function synkCountMoved(event, me, mine) {
		if (!event || typeof event !== "object") return false;
		if (event.event_type === "track_visit") return true;
		if (me && event.sent_by === me) return false;
		if (event.is_dm_channel) return true;
		if (!(mine instanceof Set)) return true;
		return mine.has(event.channel_id);
	}

	/* The names of the person's channels and direct messages, from `get_all_channels` (its `channels`, `dm_channels`). */
	function synkChannels(answer) {
		const names = new Set();
		for (const list of [answer && answer.channels, answer && answer.dm_channels]) {
			for (const channel of Array.isArray(list) ? list : []) {
				if (channel && typeof channel.name === "string") names.add(channel.name);
			}
		}
		return names;
	}

	// Raven's own pages the menu opens while Synk is in front, before the conversations: their path in Raven's app and
	// their icon (lucide names, with the prefix the menu's items take; only those the cockpit draws, its lucideIconMap:
	// it has no « # », lock, person, bot nor bookmark, a name it lacks draws an empty circle).
	const SYNK_PAGES = [
		{ key: "activity", path: "/raven/notifications", icon: "lucide-bell" },
		{ key: "threads", path: "/raven/threads", icon: "lucide-message-square" },
		{ key: "later", path: "/raven/later", icon: "lucide-clock" },
	];
	// The icons of Synk's conversations in the menu, among those the cockpit draws (see above).
	const SYNK_ICONS = {
		channel: "lucide-message-circle",
		privateChannel: "lucide-key-round",
		person: "lucide-contact",
		bot: "lucide-sparkles",
		whole: "lucide-layout-grid",
		settings: "lucide-settings",
	};
	// The direct messages the menu lists, the latest first; those with unread messages come too, however old.
	const SYNK_DIRECT = 15;

	/*
	 * The address Synk's frame loads: `route` (a path of Raven's app; Raven's own start without one), asked to draw
	 * itself for the desk (`embed=desk`) and, where the desk's menu shows its lists (`menu`), to draw none of its own
	 * (`chrome=menu`).
	 */
	function synkAddress(route, menu) {
		const path = route || "/raven";
		return path + (path.includes("?") ? "&" : "?") + "embed=desk" + (menu ? "&chrome=menu" : "");
	}

	/* A path of Raven's app as the menu compares it: decoded, without its query nor a trailing slash. */
	function synkPath(path) {
		let decoded = String(path || "").split("?")[0];
		try {
			decoded = decodeURIComponent(decoded);
		} catch (e) {
			// A path that does not decode stays as it is
		}
		return decoded.length > 1 ? decoded.replace(/\/+$/, "") : decoded;
	}

	/*
	 * Synk's lists as the desk menu's sections, while Synk is in front (Raven, asked to, draws no list of its own then:
	 * `chrome=menu`, Raven's apps/web/src/utils/embeddedInDesk.ts). Raven's own pages first (Activity, Threads, Later);
	 * then, for each workspace, the channels the person is a member of (`lists`, get_all_channels: those with a
	 * `member_id`), by name, a private one with a key, and last the workspace's whole list in Raven (`?all`, where Raven
	 * browses, joins and makes channels); then their direct messages, the latest first (SYNK_DIRECT of them, and any
	 * other with unread messages), each by the other person's name (`users`, Raven's raven_users.get_list; one whose
	 * account is disabled is left out, as Raven does), and last all of them in Raven; then Synk's settings, which
	 * Raven's rail opens and the menu takes the place of. A conversation's unread messages (`unread`,
	 * get_unread_count_for_channels) are its badge, in the accent for a direct message; a muted channel shows none.
	 * Lit: the page Raven last said it shows (`here`, its path), or a conversation under it (a thread of it). A click is
	 * `act.open(path)`, a path of Raven's app, or `act.settings()`; the words are `texts`.
	 */
	function synkSections(lists, unread, users, here, act, texts) {
		const open = (path) => act.open(path);
		const at = synkPath(here);
		const lit = (path) => {
			const own = synkPath(path);
			return Boolean(at) && (at === own || at.startsWith(own + "/"));
		};
		const counts = new Map();
		for (const row of Array.isArray(unread) ? unread : []) {
			if (row && typeof row.name === "string" && Number.isFinite(row.unread_count) && row.unread_count > 0) {
				counts.set(row.name, row.unread_count);
			}
		}
		const badge = (name) => {
			const count = counts.get(name);
			if (!count) return undefined;
			return count > 99 ? "99+" : count;
		};
		const item = (label, icon, path, extra) => ({ label, icon, active: lit(path), onClick: () => open(path), ...extra });
		// A whole list in Raven: lit only on it, not on a conversation it holds
		const whole = (label, path) => item(label, SYNK_ICONS.whole, path + "?all", { active: at === synkPath(path) });
		const nav = [{ items: SYNK_PAGES.map((page) => item(texts[page.key], page.icon, page.path)) }];
		const known = lists && typeof lists === "object" ? lists : {};
		const named = (channel) => channel && typeof channel.name === "string" && channel.name;
		// Every workspace Raven lists a channel of (the person's, joined or not: its open and public ones come too), so
		// that its whole list stays within reach; under it, the channels the person is a member of
		const workspaces = new Map();
		for (const channel of Array.isArray(known.channels) ? known.channels : []) {
			const workspace = named(channel) && typeof channel.workspace === "string" ? channel.workspace : "";
			if (!workspace) continue;
			if (!workspaces.has(workspace)) workspaces.set(workspace, []);
			if (channel.member_id && !channel.is_archived) workspaces.get(workspace).push(channel);
		}
		const byName = (a, b) => String(a.channel_name || a.name).localeCompare(String(b.channel_name || b.name));
		for (const [workspace, list] of [...workspaces].sort(([a], [b]) => a.localeCompare(b))) {
			const home = "/raven/" + encodeURIComponent(workspace);
			const items = list.sort(byName).map((channel) =>
				item(
					channel.channel_name || channel.name,
					channel.type === "Private" ? SYNK_ICONS.privateChannel : SYNK_ICONS.channel,
					home + "/" + encodeURIComponent(channel.name),
					{ badge: channel.muted ? undefined : badge(channel.name) }
				)
			);
			items.push(whole(texts.allChannels, home));
			nav.push({ label: workspace, items });
		}
		const people = new Map();
		for (const user of Array.isArray(users) ? users : []) {
			if (user && typeof user.name === "string") people.set(user.name, user);
		}
		// Once the people are known, a direct message with someone gone from them, or disabled, is left out (DMSidebar)
		const reachable = (channel) => {
			if (!people.size || channel.is_self_message) return true;
			const peer = people.get(channel.peer_user_id);
			return Boolean(peer) && peer.enabled !== 0;
		};
		const direct = (Array.isArray(known.dm_channels) ? known.dm_channels : []).filter(
			(channel) => named(channel) && reachable(channel)
		);
		const latest = (channel) => String(channel.last_message_timestamp || channel.creation || "");
		direct.sort((a, b) => latest(b).localeCompare(latest(a)));
		const shown = direct.filter((channel, index) => index < SYNK_DIRECT || counts.has(channel.name));
		const directItems = shown.map((channel) => {
			const peer = people.get(channel.peer_user_id);
			const name = (peer && (peer.full_name || peer.first_name)) || channel.peer_user_id || channel.channel_name;
			const label = channel.is_self_message ? texts.self.replace("{0}", name) : name;
			return item(label, peer && peer.type === "Bot" ? SYNK_ICONS.bot : SYNK_ICONS.person, "/raven/dm-channel/" + encodeURIComponent(channel.name), {
				badge: badge(channel.name),
				badgeTone: "accent",
			});
		});
		directItems.push(whole(texts.allDirect, "/raven/dm-channel"));
		nav.push({ label: texts.direct, items: directItems });
		nav.push({ items: [{ label: texts.settings, icon: SYNK_ICONS.settings, onClick: () => act.settings() }] });
		return nav;
	}

	/*
	 * The desk menu's sections for what NeoMail said of itself (`mailcraft:state`): its own pane, in its order.
	 * Favourites first (`texts.favorites`), when it has any; then one section per mailbox, titled with its address, with
	 * every folder of it in NeoMail's order, under its parent (`depth`); then, unless the menu draws them in its dock
	 * (`options.dock`), the views as small items at the end. A folder's badge is the number NeoMail's pane shows
	 * (badgeOf), an inbox's in the accent. A click asks NeoMail through `send(name, params, from)`: `folder.select`
	 * for a folder, `from` saying the list it was chosen from ("favorites" or "mailbox"; a folder NeoMail cannot open
	 * has no click), `view.*` for a view.
	 *
	 * The folder shown is marked once, while Mail is in front: in the list it was chosen from (`options.chosen`, the
	 * page's last click: {account, folder, from}), else, when NeoMail changed folder by itself, in its mailbox's
	 * section; never while one of the page's own views is in front (`options.page`, as viewsOf takes it). The cockpit's
	 * sections cannot be folded.
	 */
	function navSections(state, send, texts, options) {
		const now = state || {};
		const opts = options || {};
		const page = opts.page || {};
		const accounts = Array.isArray(now.accounts) ? now.accounts : [];
		const favorites = Array.isArray(now.favorites) ? now.favorites : [];
		const shown = (account, folder) =>
			!page.front && now.module === "mail" && folder != null && account === now.account && folder === now.folder;
		const chosen = opts.chosen;
		const fromFavorites =
			Boolean(chosen) &&
			chosen.from === "favorites" &&
			favorites.some((favorite) => shown(favorite.account, favorite.folder)) &&
			shown(chosen.account, chosen.folder);
		const tone = (role) => (role === "inbox" ? "accent" : undefined);
		const icon = (role) => ROLE_ICONS[role] || "lucide-folder";
		const select = (account, folder, from) => () => send("folder.select", { account, folder }, from);
		const key = (account, folder) => JSON.stringify([account, folder]);
		const known = new Map();
		for (const box of accounts) {
			for (const folder of box.folders || []) known.set(key(box.email, folder.id), folder);
		}
		const nav = [];
		if (favorites.length) {
			nav.push({
				label: texts.favorites,
				items: favorites.map((favorite) => {
					const folder = known.get(key(favorite.account, favorite.folder));
					const role = (folder && folder.role) || null;
					return {
						label: favorite.name,
						icon: icon(role),
						badge: badgeOf(folder || favorite),
						badgeTone: tone(role),
						active: fromFavorites && shown(favorite.account, favorite.folder),
						onClick: select(favorite.account, favorite.folder, "favorites"),
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
					badge: badgeOf(folder),
					badgeTone: tone(folder.role),
					active: !fromFavorites && shown(box.email, folder.id),
					onClick:
						folder.selectable === false ? undefined : select(box.email, folder.id, "mailbox"),
				})),
			});
		}
		if (!opts.dock) {
			nav.push({
				items: viewsOf(now, send, texts, page).map((view) => {
					const item = { label: view.title, icon: "lucide-" + view.icon, active: view.active, onClick: view.onClick };
					if (view.badge !== undefined) item.badge = view.badge;
					return item;
				}),
			});
		}
		return nav;
	}

	/*
	 * What the page remembers of the menu's last folder click ({account, folder, from, id}) as NeoMail's states come:
	 * kept until NeoMail shows that folder (`seen`), then forgotten as soon as it shows another one, or another view,
	 * having gone there by itself. Coming back to the folder by itself, NeoMail has it lit in its mailbox's section.
	 */
	function followChoice(chosen, state) {
		if (!chosen) return null;
		const now = state || {};
		const showing = now.module === "mail" && now.account === chosen.account && now.folder === chosen.folder;
		if (showing) return chosen.seen ? chosen : { ...chosen, seen: true };
		return chosen.seen ? null : chosen;
	}

	// The keys of an address that ask the desk's NeoMail page to open something (intentOf): the webmail's own links
	// (Webmail.vue, applyUrlIntent: `account`, `folder`, `uid`, `compose`) and NeoMail's (`account`, `email`).
	const INTENT_KEYS = ["account", "folder", "uid", "email", "compose"];

	/*
	 * What an address's query asks the desk's NeoMail page to open: a new message ({compose: true}); a message by its
	 * JMAP id ({account, email}); a message as the webmail's links name it ({account, folder, uid}: the page asks the
	 * server its id); a folder ({account, folder}); null for nothing. A folder left out is the inbox's.
	 */
	function intentOf(search) {
		const query = new URLSearchParams(search || "");
		if (query.has("compose")) return { compose: true };
		const account = (query.get("account") || "").trim();
		if (!account) return null;
		const email = (query.get("email") || "").trim();
		if (/^E[0-9]+V[0-9]+Z[A-Za-z0-9_-]+$/.test(email)) return { account, email };
		const uid = (query.get("uid") || "").trim();
		const folder = (query.get("folder") || "").trim();
		if (/^[1-9][0-9]*$/.test(uid)) return { account, folder: folder || "INBOX", uid };
		if (folder) return { account, folder };
		return null;
	}

	/* An address's query without the keys of its intent (what else it carries stays: `build`, `sample`). */
	function withoutIntent(search) {
		const query = new URLSearchParams(search || "");
		INTENT_KEYS.forEach((key) => query.delete(key));
		const rest = query.toString();
		return rest ? "?" + rest : "";
	}

	/*
	 * What NeoMail's Share in Synk asks the page to share (`mailcraft:share`, where the handover says `share: true`):
	 * {account, email}, a mailbox's address and an email id of the facade (`E<validity>V<uid>Z<folder>`); null for
	 * anything else. The server still says whether the mailbox is the person's (neomail_share.py).
	 */
	function shareOf(data) {
		const given = data || {};
		const account = typeof given.account === "string" ? given.account.trim() : "";
		const email = typeof given.email === "string" ? given.email.trim() : "";
		if (!account || account.length > 320 || !account.includes("@")) return null;
		if (email.length > 320 || !/^E[0-9]+V[0-9]+Z[A-Za-z0-9_-]+$/.test(email)) return null;
		return { account, email };
	}

	/*
	 * What NeoMail asks with `mailcraft:chat` (Chat in Synk): a message as `shareOf` takes one, and with whom,
	 * "sender" or "all"; null when it is not that.
	 */
	function chatOf(data) {
		const message = shareOf(data);
		const who = data && data.who;
		return message && (who === "sender" || who === "all") ? { ...message, who } : null;
	}

	/*
	 * A conversation's address in Synk as neomail_share.chat answers it (`/raven/dm-channel/<id>`,
	 * `/raven/<workspace>/<id>`, each part URL-encoded): a path of Raven's app, nothing else; null otherwise.
	 */
	function synkRoute(route) {
		return typeof route === "string" && /^\/raven(\/[A-Za-z0-9%._~-]+){2}$/.test(route) ? route : null;
	}

	/*
	 * Where the person may share a message, as the share dialog lists them (neomail_share.destinations: {channels:
	 * [{id, label, private}], people: [{id, label}]}): the channels first, « # name », then the people by name, each
	 * with what `share` takes (`channel:<id>`, `user:<id>`).
	 */
	function shareChoices(found) {
		const lists = found || {};
		const channels = Array.isArray(lists.channels) ? lists.channels : [];
		const people = Array.isArray(lists.people) ? lists.people : [];
		const named = (entry) => entry && typeof entry.id === "string" && entry.id && typeof entry.label === "string";
		return [
			...channels.filter(named).map((c) => ({ value: "channel:" + c.id, label: "# " + c.label })),
			...people.filter(named).map((p) => ({ value: "user:" + p.id, label: p.label })),
		];
	}

	/* The JMAP id of the mailbox an email id of the facade names (`E<validity>V<uid>Z<folder>`, `M<folder>`). */
	function mailboxOfEmail(id) {
		const found = /^E[0-9]+V[0-9]+Z([A-Za-z0-9_-]+)$/.exec(String(id || ""));
		return found ? "M" + found[1] : null;
	}

	// What the webmail's address opens that NeoMail has no equivalent of yet: its signatures, filters and automations
	// (page/neomail/neomail.py, WEBMAIL_ONLY).
	const WEBMAIL_ONLY = ["signatures", "filters", "automations"];

	/*
	 * Where an address of the webmail's desk page leads where NeoMail is in the desk: /app/neomail with what the address
	 * asked (a message, a folder, a new message); null for what only the webmail does (WEBMAIL_ONLY). Kept the same as
	 * the server's own (page/neomail/neomail.py, neomail_address).
	 */
	function deskAddress(search) {
		const query = new URLSearchParams(search || "");
		if (WEBMAIL_ONLY.some((key) => query.has(key))) return null;
		const kept = new URLSearchParams();
		if (query.has("compose")) {
			kept.set("compose", "1");
		} else {
			for (const key of ["account", "folder", "uid", "email"]) {
				const value = (query.get(key) || "").trim();
				if (value) kept.set(key, value);
			}
		}
		const rest = kept.toString();
		return "/app/neomail" + (rest ? "?" + rest : "");
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

	return {
		install,
		listen,
		frameHeight,
		navSections,
		viewDock,
		badgeOf,
		synk: SYNK,
		synkBadge,
		synkCountMoved,
		synkChannels,
		shareOf,
		shareChoices,
		chatOf,
		synkRoute,
		synkAddress,
		synkSections,
		followChoice,
		intentKeys: INTENT_KEYS,
		intentOf,
		withoutIntent,
		mailboxOfEmail,
		deskAddress,
		commander,
		refusedAsStale,
	};
})();
