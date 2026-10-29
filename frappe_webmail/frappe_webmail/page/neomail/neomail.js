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
 * - Share in Synk: where the handover says `share: true` (neomail.py, for someone who may share in Synk), NeoMail's
 *   button names a message by its mailbox and its id (`mailcraft:share`); the page asks where (a channel of the
 *   person's or a person, a word of their own, the attachments or not), the server posts it as the person
 *   (neomail_share.py), and the Synk view shows the post.
 * - An attachment, as the old webmail's menu has it: where the handover's `attachments` offers them (neomail.py, from
 *   what the person may do here), NeoMail's menu of an attachment names it to the page (`mailcraft:attachment`, its
 *   message and what NeoMail knows of the file). « Save to Drive… » asks for a folder of the Drive (its roots, a
 *   folder's subfolders, a search, the folder used last, a new folder) and the server saves the file there, read from
 *   the message on its server (neomail_attachments.py); « Open in NeoDoc » and its kin do the same, then open the copy
 *   in its editor in a new tab; « Send to Scanned Documents » sends a PDF or a picture to the scanned documents at
 *   once. A toast says where it went, with a link.
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
	// Raven's methods Synk's icon reads (raven/api of bvisible/Raven): the unread messages, the person's channels.
	const UNREAD = "/api/method/raven.api.raven_message.get_unread_count_for_channels";
	const CHANNELS = "/api/method/raven.api.raven_channel.get_all_channels?hide_archived=1";
	// Share in Synk (neomail_share.py): where the person may share a message, and the share itself.
	const DESTINATIONS = "/api/method/frappe_webmail.neomail_share.destinations";
	const SHARE = "/api/method/frappe_webmail.neomail_share.share";
	const CHAT = "/api/method/frappe_webmail.neomail_share.chat";
	// An attachment (neomail_attachments.py), and the Drive's folders as the old webmail's picker reads them
	// (attachments.py).
	const TO_DRIVE = "/api/method/frappe_webmail.neomail_attachments.save_to_drive";
	const TO_SCANS = "/api/method/frappe_webmail.neomail_attachments.to_scans";
	const FOLDERS = "/api/method/frappe_webmail.attachments.get_drive_folders";
	const NEW_FOLDER = "/api/method/frappe_webmail.attachments.create_drive_folder";

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
		// A folder's right-click menu while it is open: {menu, away, escape}
		folderMenu: null,
		// The extensions the Drive's editors open here (the handover's `editors`), and the attachments being sent to
		// the scanned documents (one call each, however many clicks)
		editors: [],
		filing: new Set(),
		// The Drive's folder picker while it is open
		picking: null,
		// Synk's icon (Synk on the web is Raven's own app, opened in a tab of its own): whether Raven answered the person
		// (the icon shows only then), the badge, the person's channels (a Set, null while unknown), the count being
		// asked and whether to ask it once more when it is back, whether Raven's events are listened to
		synk: {
			offered: false,
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

	// The words of a folder's right-click, as NeoMail's own menu says them.
	const folder_words = () => ({
		newFolder: __("New Folder…"),
		renameFolder: __("Rename Folder…"),
		deleteFolder: __("Delete Folder"),
		markAllRead: __("Mark All as Read"),
		emptyFolder: __("Empty Folder"),
	});

	// A folder's right-click in the desk's menu (neomailHost.folderActions, 29.10): a small menu where the click was,
	// each entry done on the mailbox's server (neomail_folders.act), NeoMail itself making no folder of a JMAP mailbox
	// yet; then NeoMail reads its folders again.
	function folder_menu(event, account, folder) {
		const address = String(account || "").toLowerCase();
		const shared = ((state.host && state.host.accounts) || []).some(
			(box) => String(box.email || "").toLowerCase() === address && box.shared === true
		);
		const entries = window.neomailHost.folderActions(folder, shared, folder_words());
		close_folder_menu();
		if (!entries.length) return;
		const menu = document.createElement("div");
		menu.className = "neomail-folder-menu";
		menu.setAttribute("role", "menu");
		for (const entry of entries) {
			const item = document.createElement("button");
			item.type = "button";
			item.className = "neomail-folder-menu-item";
			item.setAttribute("role", "menuitem");
			item.textContent = entry.label;
			item.disabled = entry.disabled;
			item.addEventListener("click", () => {
				close_folder_menu();
				folder_action(entry.action, account, folder);
			});
			menu.append(item);
		}
		document.body.append(menu);
		// Where the click was, inside the window
		const x = Math.min((event && event.clientX) || 0, window.innerWidth - menu.offsetWidth - 8);
		const y = Math.min((event && event.clientY) || 0, window.innerHeight - menu.offsetHeight - 8);
		menu.style.left = Math.max(8, x) + "px";
		menu.style.top = Math.max(8, y) + "px";
		const away = (e) => {
			if (!menu.contains(e.target)) close_folder_menu();
		};
		const escape = (e) => {
			if (e.key === "Escape") close_folder_menu();
		};
		document.addEventListener("pointerdown", away, true);
		document.addEventListener("keydown", escape, true);
		window.addEventListener("blur", close_folder_menu);
		state.folderMenu = { menu, away, escape };
	}

	function close_folder_menu() {
		const open = state.folderMenu;
		if (!open) return;
		state.folderMenu = null;
		open.menu.remove();
		document.removeEventListener("pointerdown", open.away, true);
		document.removeEventListener("keydown", open.escape, true);
		window.removeEventListener("blur", close_folder_menu);
	}

	// What an entry asks first (a name, or a yes), then the server does it and NeoMail reads its folders again. A
	// refusal (a name already there, a folder that holds others) is said by the call itself.
	function folder_action(action, account, folder) {
		const done = (name) =>
			frappe
				.call({
					method: "frappe_webmail.neomail_folders.act",
					args: { account, mailbox: folder.id, action, name },
					freeze: true,
				})
				.then(() => reread());
		const named = (title, primary, value) =>
			frappe.prompt(
				[{ fieldname: "name", fieldtype: "Data", label: __("Folder name"), reqd: 1, default: value || "" }],
				(values) => done(values.name),
				title,
				primary
			);
		if (action === "create") named(__("New folder in {0}", [folder.name]), __("Create"));
		else if (action === "rename") named(__("Rename the folder {0}", [folder.name]), __("Rename"), folder.name);
		else if (action === "delete") frappe.confirm(__("Delete the folder {0}?", [folder.name]), () => done());
		else if (action === "empty")
			frappe.confirm(__("Delete all the mail in {0} for good?", [folder.name]), () => done());
		else done();
	}

	// NeoMail reads its folders again: its frame starts again, unless it holds work it has not sent (a message being
	// written), when it shows the change at its next Send/Receive.
	function reread() {
		if (state.dirty || !state.frame || !state.frame.contentWindow) {
			frappe.show_alert({ message: __("Done: NeoMail shows it at its next Send/Receive."), indicator: "green" });
			return;
		}
		frappe.show_alert({ message: __("Done."), indicator: "green" }, 3);
		if (state.host) window.mailcraftJmap = state.host;
		state.frame.contentWindow.location.reload();
	}

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
		const page = page_views(words);
		const lent = {
			app: { name: "mail", title: words.mail },
			route: page_route(),
			nav: window.neomailHost.navSections(state.where, ask, words, {
				dock,
				chosen: state.chosen,
				page,
				folderMenu: folder_menu,
			}),
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

	// The page's own views after NeoMail's, as neomailHost.viewsOf takes them: Synk, once Raven answered the person. On
	// the web, Synk is Raven's own app: its icon opens it in a tab of its own, and is never the view in front.
	function page_views(words) {
		const synk = state.synk;
		const host = window.neomailHost;
		const views = synk.offered
			? [{ view: host.synk.view, title: words.synk, icon: host.synk.icon, badge: synk.badge, onClick: () => open_synk() }]
			: [];
		return { front: null, views };
	}

	// A page of Raven's app (`path`, `/raven/...`; Raven's own start without one) in a tab of its own: `tab`, opened
	// at the click when an answer had to be awaited first (a browser lets a page open a tab on a click only), or a new
	// one. A tab the browser refused leaves the person a link.
	function open_synk(path, tab) {
		const address = (path && window.neomailHost.synkRoute(path)) || window.neomailHost.synk.address;
		let opened = tab || null;
		if (opened) {
			opened.location.href = address;
		} else {
			opened = window.open(address, "_blank");
			if (opened) opened.opener = null;
		}
		if (!opened) {
			const link = `<a href="${frappe.utils.escape_html(address)}" target="_blank" rel="noopener">${__("Open in Synk")}</a>`;
			frappe.msgprint(link);
		}
	}

	// A tab opened at once on a click, still empty, for a page of Raven's app the answer to come will name (open_synk).
	function blank_tab() {
		const tab = window.open("", "_blank");
		if (tab) tab.opener = null;
		return tab;
	}

	// What the server said went wrong, in the person's language: its message, else `fallback`. As words, never markup:
	// msgprint shows HTML, and a server's message may carry what an e-mail wrote (a sender, a file's name).
	async function refusal(answer, fallback) {
		try {
			const body = await answer.json();
			const said = JSON.parse(body._server_messages || "[]")
				.map((m) => JSON.parse(m).message)
				.filter(Boolean);
			// The desk's own strip_html (frappe/public/js/frappe/utils/common.js): the words without their markup, then
			// escaped, so that whatever is left of one is shown and not run
			if (said.length) return frappe.utils.escape_html((window.strip_html || ((text) => text))(said.join(" ")));
		} catch (e) {
			// The fallback says it
		}
		return fallback;
	}

	// Share in Synk (`mailcraft:share`): the person chooses a channel or a person, adds a word, takes the attachments
	// or not; the server posts it as the person (neomail_share.share), and the person stays in their mail, the post a
	// click away in Synk. NeoMail named the message by its mailbox and its id alone.
	async function share_message(data) {
		const asked = window.neomailHost.shareOf(data);
		if (!asked) return;
		const headers = { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token || "" };
		let found = null;
		try {
			const answer = await fetch(DESTINATIONS, { method: "GET", credentials: "same-origin", cache: "no-store", headers });
			found = answer.ok ? (await answer.json()).message : null;
		} catch (e) {
			found = null;
		}
		const choices = window.neomailHost.shareChoices(found);
		if (!found) {
			frappe.msgprint(__("Synk could not be reached. Try again in a moment."));
			return;
		}
		if (!choices.length) {
			frappe.msgprint(__("You have no channel in Synk and nobody to write to yet."));
			return;
		}
		// One send, however many times the button is pressed (Raven's idempotency key)
		const client_id = frappe.utils.get_random(20);
		const dialog = new frappe.ui.Dialog({
			title: __("Share in Synk"),
			fields: [
				{
					fieldtype: "Autocomplete",
					fieldname: "to",
					label: __("Share with"),
					description: __("A channel, or a person"),
					options: choices,
					reqd: 1,
				},
				{ fieldtype: "Small Text", fieldname: "note", label: __("Your message") },
				{ fieldtype: "Check", fieldname: "attachments", label: __("Share the attachments too") },
			],
			primary_action_label: __("Share"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				let answer = null;
				try {
					answer = await fetch(SHARE, {
						method: "POST",
						credentials: "same-origin",
						cache: "no-store",
						headers: { ...headers, "Content-Type": "application/json" },
						body: JSON.stringify({
							account: asked.account,
							email: asked.email,
							to: values.to,
							note: values.note || "",
							attachments: values.attachments ? 1 : 0,
							client_id,
						}),
					});
				} catch (e) {
					answer = null;
				}
				if (!answer || !answer.ok) {
					dialog.enable_primary_action();
					const fallback = __("The message could not be shared.");
					frappe.msgprint(answer ? await refusal(answer, fallback) : fallback);
					return;
				}
				const done = (await answer.json()).message || {};
				dialog.hide();
				// The person stays in their mail; the post is a click away, in Synk's own tab
				const post = done.message ? "/raven/message/" + encodeURIComponent(done.message) : null;
				const seen = post
					? ` <a href="${frappe.utils.escape_html(post)}" target="_blank" rel="noopener">${__("Open in Synk")}</a>`
					: "";
				frappe.show_alert({ message: __("Shared in Synk") + seen, indicator: "green" });
				if (done.left_out > 0) {
					frappe.show_alert({
						message: __("{0} attachment(s) could not be shared.", [done.left_out]),
						indicator: "orange",
					});
				}
				// Raven answered the person: Synk is theirs
				state.synk.offered = true;
				count_synk();
			},
		});
		dialog.show();
	}

	// Chat in Synk about a message (`mailcraft:chat`): with its sender, or with everyone on it. The server finds or makes
	// the conversation (neomail_share.chat) and asks first when it would make a channel or add people to one (Raven
	// tells them); Synk then opens on it, in a tab of its own. Nothing is posted in the person's name: they write in
	// Synk.
	async function chat_in_synk(data) {
		const asked = window.neomailHost.chatOf(data);
		if (!asked) return;
		const ask = async (confirmed) => {
			let answer = null;
			try {
				answer = await fetch(CHAT, {
					method: "POST",
					credentials: "same-origin",
					cache: "no-store",
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": frappe.csrf_token || "",
					},
					body: JSON.stringify({ ...asked, confirmed: confirmed ? 1 : 0 }),
				});
			} catch (e) {
				answer = null;
			}
			if (!answer || !answer.ok) {
				const fallback = __("The conversation could not be opened in Synk.");
				frappe.msgprint(answer ? await refusal(answer, fallback) : fallback);
				return null;
			}
			return (await answer.json()).message || {};
		};
		let done = await ask(false);
		// After the question, the tab is opened on the person's « yes », while the browser lets the page open one
		let tab = null;
		if (done && done.ask) {
			const people = (Array.isArray(done.with) ? done.with : []).map((name) => frappe.utils.escape_html(String(name)));
			const names = frappe.utils.comma_and ? frappe.utils.comma_and(people) : people.join(", ");
			const question = done.adds
				? __("Add {0} to this message's channel in Synk?", [names])
				: __("Make a private channel in Synk with {0} about this message?", [names]);
			const yes = await new Promise((resolve) =>
				frappe.confirm(
					question,
					() => {
						tab = blank_tab();
						resolve(true);
					},
					() => resolve(false)
				)
			);
			if (!yes) return;
			done = await ask(true);
		}
		const route = done && window.neomailHost.synkRoute(done.route);
		if (!route) {
			if (tab) tab.close();
			return;
		}
		if (done.left_out > 0) {
			frappe.show_alert({
				message: __("{0} person(s) on this message could not join: they are not in your Synk workspace.", [done.left_out]),
				indicator: "orange",
			});
		}
		// Raven answered the person: Synk is theirs, and shows the conversation in its own tab
		state.synk.offered = true;
		open_synk(route, tab);
	}

	// One of the server's methods, as the person (the desk's cookie, its CSRF token): GET without `body`, else a POST
	// of it. The answer, or null when the server could not be reached.
	async function to_server(address, body) {
		const headers = { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token || "" };
		const init =
			body === undefined
				? { method: "GET", credentials: "same-origin", cache: "no-store", headers }
				: {
						method: "POST",
						credentials: "same-origin",
						cache: "no-store",
						headers: { ...headers, "Content-Type": "application/json" },
						body: JSON.stringify(body),
				  };
		try {
			return await fetch(address, init);
		} catch (e) {
			return null;
		}
	}

	// What the server answered (its `message`), or null once the person was told why not (its refusal, else
	// `fallback`).
	async function taken(answer, fallback) {
		if (!answer || !answer.ok) {
			frappe.msgprint(answer ? await refusal(answer, fallback) : fallback);
			return null;
		}
		try {
			return (await answer.json()).message || {};
		} catch (e) {
			frappe.msgprint(fallback);
			return null;
		}
	}

	// A toast that says where a file went, with a link to it: every word escaped, the link one the page checked.
	// `away`: the link opens a new tab (the Drive is not a page of the desk). « Open it », not the bare « Open », which
	// other apps translate as a state (« Ouvert »).
	function filed(message, link, away) {
		const escape = frappe.utils.escape_html;
		const open = link
			? ` <a href="${escape(link)}"${away ? ' target="_blank" rel="noopener"' : ""}>${escape(__("Open it"))}</a>`
			: "";
		frappe.show_alert({ message: escape(String(message || "")) + open, indicator: "green" }, 8);
	}

	// What NeoMail asks of an attachment (`mailcraft:attachment`): the Drive, the scanned documents, an editor. An
	// editor this site has no build of is said at once, before a copy is made that nothing opens.
	function attachment_action(data) {
		const asked = window.neomailHost.attachmentOf(data);
		if (!asked) return;
		// Only what the handover offered: a NeoMail asking for more is not heard
		const offered = state.host && Array.isArray(state.host.attachments) ? state.host.attachments : [];
		if (!offered.includes(asked.action)) return;
		if (asked.action === "scan") {
			send_to_scans(asked);
			return;
		}
		let editor = null;
		if (asked.action === "edit") {
			editor = window.neomailHost.editorOf(asked.attachment.name);
			if (!editor) return;
			if (!state.editors.includes(editor.extension)) {
				frappe.msgprint(__("{0} is not installed on this site.", [editor.product]));
				return;
			}
		}
		// One folder picker at a time: a second click while one is open brings nothing more
		if (state.picking) return;
		pick_drive_folder(asked, editor);
	}

	// « Send to Scanned Documents »: at once, as the old webmail did (neomail_attachments.to_scans), then a toast with
	// the scanned document's link. One call for an attachment while it runs, however many clicks.
	async function send_to_scans(asked) {
		const key = [asked.account, asked.email, asked.attachment.index].join("\n");
		if (state.filing.has(key)) return;
		state.filing.add(key);
		try {
			const answer = await to_server(TO_SCANS, {
				account: asked.account,
				email: asked.email,
				attachment: asked.attachment,
			});
			const done = await taken(answer, __("The attachment could not be sent to the scanned documents."));
			if (done) filed(done.message, window.neomailHost.scanUrl(done.name), false);
		} finally {
			state.filing.delete(key);
		}
	}

	// An element of the picker, with its class and its words (never markup).
	function element(tag, className, text) {
		const made = document.createElement(tag);
		if (className) made.className = className;
		if (text !== undefined) made.textContent = text;
		return made;
	}

	// « Save to Drive… » and « Open in NeoDoc » (`editor`): the person picks a folder of the Drive, as in the old
	// webmail's picker (attachments.get_drive_folders: the roots, a folder's subfolders, a search, the folder used last;
	// create_drive_folder), then the server saves the file there (neomail_attachments.save_to_drive). With an editor,
	// the copy then opens in it, in a new tab opened on the click itself (a browser blocks one opened after a wait).
	function pick_drive_folder(asked, editor) {
		const host = window.neomailHost;
		const view = {
			roots: [],
			children: {},
			open: {},
			selected: null,
			last: null,
			query: "",
			results: [],
			loading: true,
			failed: false,
			timer: null,
			busy: false,
		};
		const dialog = new frappe.ui.Dialog({
			title: editor ? __("Open in {0}", [editor.product]) : __("Save to the Drive"),
			fields: [{ fieldtype: "HTML", fieldname: "picker" }],
			primary_action_label: editor ? __("Save and open") : __("Save here"),
			primary_action: () => save(),
		});
		const field = dialog.fields_dict.picker;
		const box = field.wrapper || (field.$wrapper && field.$wrapper.get(0));
		const picker = element("div", "neomail-picker");
		const file = element("div", "neomail-picker-file");
		file.append(
			element("span", "neomail-picker-file-name", host.fileLabel(asked.attachment.name)),
			element("span", "neomail-picker-file-size", host.sizeLabel(asked.attachment.size))
		);
		const search = element("input", "form-control neomail-picker-search");
		search.type = "search";
		search.placeholder = __("Search for a folder");
		search.setAttribute("aria-label", __("Search for a folder"));
		const last = element("button", "btn neomail-picker-last");
		last.type = "button";
		const tree = element("div", "neomail-picker-tree");
		tree.setAttribute("role", "tree");
		const making = element("div", "neomail-picker-new");
		const start_new = element("button", "btn btn-default btn-sm", __("New folder"));
		start_new.type = "button";
		const new_name = element("input", "form-control input-sm");
		new_name.placeholder = __("Name of the folder");
		new_name.hidden = true;
		const create = element("button", "btn btn-default btn-sm", __("Create"));
		create.type = "button";
		create.hidden = true;
		making.append(start_new, new_name, create);
		picker.append(
			file,
			search,
			last,
			tree,
			making,
			element(
				"p",
				"neomail-picker-hint",
				__("The file is copied by the server, straight from the e-mail: nothing is downloaded.")
			)
		);
		box.append(picker);

		const writable = () => Boolean(view.selected && view.selected.can_write);
		function enable() {
			if (writable() && !view.busy) dialog.enable_primary_action();
			else dialog.disable_primary_action();
			start_new.disabled = !writable() || view.busy;
		}

		function choose(folder) {
			view.selected = folder;
			draw();
		}

		// One row of the tree: its chevron opens it, a click chooses it (when the person may file into it) and opens it.
		function row(folder, depth) {
			const line = element("button", "neomail-picker-row");
			line.type = "button";
			line.setAttribute("role", "treeitem");
			line.style.paddingLeft = 8 + depth * 18 + "px";
			const chosen = Boolean(view.selected && view.selected.name === folder.name);
			line.classList.toggle("is-chosen", chosen);
			line.setAttribute("aria-selected", String(chosen));
			line.classList.toggle("is-muted", !folder.can_write);
			if (folder.has_children) line.setAttribute("aria-expanded", String(Boolean(view.open[folder.name])));
			const chevron = element("span", "neomail-picker-chevron", folder.has_children ? (view.open[folder.name] ? "▾" : "▸") : "");
			chevron.addEventListener("click", (event) => {
				event.stopPropagation();
				toggle(folder);
			});
			const words = element("span", "neomail-picker-row-text");
			words.append(element("span", "", String(folder.title || folder.name || "")));
			if (folder.path && view.query) words.append(element("small", "", String(folder.path)));
			line.append(chevron, words);
			line.addEventListener("click", () => {
				if (folder.can_write) choose(folder);
				if (folder.has_children && !view.open[folder.name]) toggle(folder);
			});
			return line;
		}

		function draw() {
			tree.replaceChildren();
			const say = (text) => tree.append(element("div", "neomail-picker-empty", text));
			if (view.loading) say(__("Loading…"));
			else if (view.failed) say(__("The Drive could not be reached. Try again in a moment."));
			else if (view.query) {
				if (!view.results.length) say(__("No folder found"));
				view.results.forEach((folder) => tree.append(row(folder, 0)));
			} else {
				// A folder is never drawn inside itself, whatever the server answered
				const walk = (folders, depth, above) =>
					(folders || []).forEach((folder) => {
						if (above.includes(folder.name)) return;
						tree.append(row(folder, depth));
						if (view.open[folder.name]) walk(view.children[folder.name], depth + 1, [...above, folder.name]);
					});
				walk(view.roots, 0, []);
			}
			last.hidden = !view.last || Boolean(view.query);
			if (view.last) {
				last.replaceChildren(
					element("span", "neomail-picker-last-label", __("Last used")),
					element("span", "neomail-picker-last-path", String(view.last.path || view.last.title || ""))
				);
				last.classList.toggle("is-chosen", Boolean(view.selected && view.selected.name === view.last.name));
			}
			enable();
		}

		async function folders(query) {
			const answer = await to_server(FOLDERS + "?" + new URLSearchParams(query).toString());
			if (!answer || !answer.ok) return null;
			try {
				return (await answer.json()).message || null;
			} catch (e) {
				return null;
			}
		}

		async function toggle(folder) {
			if (!folder.has_children) return;
			if (view.open[folder.name]) {
				view.open[folder.name] = false;
				draw();
				return;
			}
			if (!view.children[folder.name]) {
				const found = await folders({ parent: folder.name });
				view.children[folder.name] = (found && found.folders) || [];
			}
			view.open[folder.name] = true;
			draw();
		}

		search.addEventListener("input", () => {
			clearTimeout(view.timer);
			const text = search.value.trim();
			view.query = text;
			if (!text) {
				view.results = [];
				draw();
				return;
			}
			view.timer = setTimeout(async () => {
				const found = await folders({ search: text });
				if (view.query !== text) return;
				view.results = (found && found.folders) || [];
				draw();
			}, 250);
		});
		last.addEventListener("click", () => view.last && choose(view.last));
		start_new.addEventListener("click", () => {
			start_new.hidden = true;
			new_name.hidden = false;
			create.hidden = false;
			new_name.value = "";
			new_name.focus();
		});
		async function make_folder() {
			const parent = view.selected;
			const title = new_name.value.trim();
			if (!title || !parent || !parent.can_write || view.busy) return;
			create.disabled = true;
			const made = await taken(
				await to_server(NEW_FOLDER, { parent: parent.name, title }),
				__("The folder could not be made.")
			);
			create.disabled = false;
			if (!made || !made.name) return;
			view.children[parent.name] = [...(view.children[parent.name] || []), made];
			view.open[parent.name] = true;
			parent.has_children = true;
			start_new.hidden = false;
			new_name.hidden = true;
			create.hidden = true;
			choose(made);
		}
		create.addEventListener("click", make_folder);
		new_name.addEventListener("keydown", (event) => {
			if (event.key === "Enter") {
				event.preventDefault();
				make_folder();
			}
		});

		async function save() {
			const folder = view.selected;
			if (!folder || !folder.can_write || view.busy) return;
			view.busy = true;
			enable();
			// The editor's tab, opened on the click itself, and cut from this page
			const tab = editor ? window.open("", "_blank") : null;
			if (tab) tab.opener = null;
			const done = await taken(
				await to_server(TO_DRIVE, {
					account: asked.account,
					email: asked.email,
					attachment: asked.attachment,
					drive_folder: folder.name,
					edit: editor ? 1 : 0,
				}),
				editor ? __("The file could not be opened.") : __("The file could not be saved in the Drive.")
			);
			if (!done) {
				if (tab) tab.close();
				view.busy = false;
				enable();
				return;
			}
			dialog.hide();
			const url = host.driveUrl(done.url);
			if (editor && url) {
				if (tab) tab.location.replace(window.location.origin + url);
				else window.open(url, "_blank", "noopener");
			} else if (tab) {
				tab.close();
			}
			filed(done.message, url, true);
		}

		// Closed, it is gone: from the page and from the desk's markup
		dialog.onhide = () => {
			clearTimeout(view.timer);
			state.picking = null;
			if (dialog.$wrapper && typeof dialog.$wrapper.remove === "function") dialog.$wrapper.remove();
		};
		state.picking = dialog;
		dialog.show();
		draw();
		folders({}).then((found) => {
			view.loading = false;
			view.failed = !found;
			view.roots = (found && found.folders) || [];
			view.last = (found && found.last) || null;
			if (view.last && view.last.can_write) view.selected = view.last;
			draw();
		});
		setTimeout(() => search.focus(), 0);
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
		const synk = state.synk;
		const answer = await from_raven(CHANNELS);
		synk.mine = "message" in answer ? window.neomailHost.synkChannels(answer.message) : null;
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
		// The extensions the Drive's editors open here, for the page itself (NeoMail is not told)
		state.editors = Array.isArray(given.editors) ? given.editors.filter((e) => typeof e === "string") : [];
		window.neomailHost.install(window, given.host, {
			sessionEnded: __("Your Neoffice session has ended."),
			onSession: (alive) => (state.banner.hidden = alive),
		});
		const frame = document.createElement("iframe");
		frame.className = "neomail-desk-frame";
		frame.title = "NeoMail";
		frame.src = given.build_url;
		// NeoMail in the desk's light or dark, not the computer's (neomail_host.js, followDeskTheme)
		window.neomailHost.followDeskTheme(document, frame, window.MutationObserver);
		state.frame = frame;
		state.send = window.neomailHost.commander(window, frame);
		window.neomailHost.listen(window, frame, {
			// Whether closing it would lose work: said as it starts, then at each change
			"mailcraft:dirty": (data) => (state.dirty = data.dirty === true),
			// Share in Synk, on the person's click: the dialog that asks where
			"mailcraft:share": (data) => share_message(data),
			"mailcraft:chat": (data) => chat_in_synk(data),
			// An attachment to file, on the person's click: the Drive, the scanned documents, an editor
			"mailcraft:attachment": (data) => attachment_action(data),
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
		if (!on) close_folder_menu();
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
