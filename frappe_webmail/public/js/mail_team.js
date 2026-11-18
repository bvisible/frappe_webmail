// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/*
 * The team's mail, the windows (18.11.2026, the « Courrier » canvas, from the Neoffice design system):
 *
 * - « Add a mailbox » (add_mailbox): a wizard of the desk's window model (four steps: whose it is, where it is, how it
 *   signs in, who else reads it). The mailbox Neoservice provides comes first and chosen: its servers are found from the
 *   domain of the address (mail_team.detect, its MX records), whoever hosts it. Google and Microsoft 365 sign in at their
 *   own page, once, by the person; another provider gives its servers. A password is tried before anything is made.
 * - « My mail » (open_mine): for everyone, their own mailboxes and those shared with them, what waits for them (to
 *   connect at Google or Microsoft, a password), who else reads each, and their own signature (the builder's own view,
 *   signature_builder.mount).
 *
 * Their server side: mail_team.py. Loaded on demand by a <script> tag (Settings › Mail, the user menu's « My mail »).
 */

/* global frappe_webmail */

frappe.provide("frappe_webmail.mail_team");

(function () {
	const API = "frappe_webmail.mail_team.";
	// Versioned: a browser that keeps an older builder (without `mount`) would draw nothing
	const BUILDER_JS = "/assets/frappe_webmail/js/signature_builder.js?v=2";
	const BUILDER_CSS = "/assets/frappe_webmail/css/signature_builder.css?v=2";
	const STYLE = "/assets/frappe_webmail/css/mail_team.css?v=2";
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	// A file asked once, by a tag (frappe.require never runs an address that carries a version)
	const asked = {};
	function load(src, kind) {
		if (!asked[src]) {
			asked[src] = new Promise((resolve, reject) => {
				const el = document.createElement(kind === "css" ? "link" : "script");
				if (kind === "css") {
					el.rel = "stylesheet";
					el.href = src;
				} else {
					el.src = src;
				}
				el.onload = resolve;
				el.onerror = () => {
					delete asked[src];
					reject(new Error(src + " did not load"));
				};
				document.head.appendChild(el);
			});
		}
		return asked[src];
	}
	const styled = () => load(STYLE, "css");
	const builder = () =>
		Promise.all([
			load(BUILDER_CSS, "css"),
			frappe_webmail.signature_builder && frappe_webmail.signature_builder.mount
				? null
				: load(BUILDER_JS),
		]);

	// The five tones of a state (design system §6.3), as the pill draws them
	function pill(state) {
		const tone = { success: "ok", warn: "warn", danger: "bad", muted: "mute", info: "info" }[
			(state && state.tone) || "muted"
		];
		return `<span class="mlt-pill mlt-${tone}"><i></i>${esc(state && state.label)}</span>`;
	}

	const LETTERS = { neoservice: "N", google: "G", microsoft: "M", other: "…" };
	function providers() {
		return [
			{
				key: "neoservice",
				name: __("Neoservice e-mail"),
				how: __(
					"The mailbox Neoservice provides. Its address and its password: Neoffice finds the right settings itself."
				),
			},
			{
				key: "google",
				name: __("Google"),
				how: __(
					"Gmail or Google Workspace. The person signs in once at Google: no password here."
				),
			},
			{
				key: "microsoft",
				name: __("Microsoft 365"),
				how: __(
					"Outlook or Microsoft 365. The person signs in once at Microsoft: no password here."
				),
			},
			{
				key: "other",
				name: __("Another provider"),
				how: __(
					"The address, its password, and the IMAP and SMTP servers the provider gives."
				),
			},
		];
	}

	// ---- « Add a mailbox » ---------------------------------------------------------------------------------------------

	// « Who else reads it » is a list of the desk's people: its table's description must be known to the page first
	function add_mailbox(opts) {
		return frappe.model.with_doctype("Webmail Account User").then(() => make_wizard(opts));
	}

	function make_wizard(opts) {
		const options = opts || {};
		const S = {
			provider: "neoservice",
			detected: null,
			tried: null,
			oauth: options.oauth || {},
		};
		const d = new frappe.ui.Dialog({
			title: __("Whose mailbox is it?"),
			eyebrow: __("Add a mailbox"),
			size: "large",
			primary_action_label: __("Add the mailbox"),
			primary_action: (values) => make(values),
			steps: [
				{
					label: __("Whose", null, "Add a mailbox"),
					title: __("Whose mailbox is it?"),
					fields: [
						{
							fieldtype: "Link",
							fieldname: "user",
							options: "User",
							label: __("The person"),
							reqd: 1,
							default: options.user || "",
							get_query: () => ({
								filters: { enabled: 1, user_type: "System User" },
							}),
							description: __("They answer for it: it opens in their NeoMail."),
						},
						{
							fieldtype: "Data",
							fieldname: "email",
							options: "Email",
							label: __("The address"),
							reqd: 1,
						},
					],
					answer: (v) => v.email || "",
				},
				{
					label: __("Where", null, "Add a mailbox"),
					title: __("Where is this mailbox?"),
					fields: [{ fieldtype: "HTML", fieldname: "where" }],
					// Neoservice's mailbox only where the domain receives at our host; a provider this site cannot sign in at, never
					// Another provider's servers only for one's own mailbox (mail_team.add refuses them for someone else)
					validate: () =>
						(S.provider !== "neoservice" ||
							(S.detected && S.detected.provider === "neoservice")) &&
						(S.provider !== "other" || d.get_value("user") === frappe.session.user) &&
						S.oauth[S.provider] !== false,
					answer: () => (providers().find((p) => p.key === S.provider) || {}).name || "",
				},
				{
					label: __("Sign-in", null, "Add a mailbox"),
					title: __("How does it sign in?"),
					fields: [
						{ fieldtype: "HTML", fieldname: "how" },
						{
							fieldtype: "Password",
							fieldname: "password",
							label: __("The mailbox's password"),
						},
						{ fieldtype: "Data", fieldname: "imap_host", label: __("IMAP server") },
						{
							fieldtype: "Int",
							fieldname: "imap_port",
							label: __("IMAP port"),
							default: 993,
						},
						{ fieldtype: "Data", fieldname: "smtp_host", label: __("SMTP server") },
						{
							fieldtype: "Int",
							fieldname: "smtp_port",
							label: __("SMTP port"),
							default: 465,
						},
						{ fieldtype: "HTML", fieldname: "tried" },
					],
					validate: (v) => sign_in_ready(v),
				},
				{
					label: __("Who reads it", null, "Add a mailbox"),
					title: __("Who else reads this mailbox?"),
					fields: [
						{
							fieldtype: "Table MultiSelect",
							fieldname: "readers",
							options: "Webmail Account User",
							label: __("Read also by"),
							description: __(
								"Leave it empty for a mailbox of their own. Each person named here sees it in their NeoMail; its owner sees who reads it."
							),
						},
					],
				},
			],
		});
		d.on_step = (i) => {
			if (i === 1) draw_where();
			if (i === 2) draw_how();
		};
		d.show();
		styled();

		function draw_where() {
			const email = (d.get_value("email") || "").trim();
			const own = d.get_value("user") === frappe.session.user;
			if (!own && S.provider === "other") S.provider = "neoservice";
			const $w = d.fields_dict.where.$wrapper;
			const tiles = () =>
				providers()
					.filter((p) => own || p.key !== "other")
					.map(
						(p) => `<button type="button" class="mlt-tile${
							p.key === S.provider ? " is-on" : ""
						}" data-provider="${p.key}" aria-pressed="${p.key === S.provider}">
						<span class="mlt-mark mlt-mark-${p.key}">${LETTERS[p.key]}</span>
						<span class="mlt-tile-text"><span class="mlt-tile-name">${esc(
							p.name
						)}</span><span class="mlt-tile-how">${esc(p.how)}</span></span>
					</button>`
					)
					.join("");
			const paint = () => {
				$w.html(`<p class="mlt-lead">${esc(
					__("The address: {0}. Choose who serves it; Neoffice does the settings.", [
						email,
					])
				)}</p>
					<div class="mlt-tiles">${tiles()}</div><div class="mlt-note">${esc(note())}</div>`);
				$w.find(".mlt-tile").on("click", (e) => {
					S.provider = e.currentTarget.dataset.provider;
					S.tried = null;
					paint();
				});
			};
			const note = () => {
				const found = S.detected;
				if (!found)
					return __("Looking where {0} receives its mail…", [email.split("@")[1] || ""]);
				if (found.failed && S.provider === "neoservice")
					return __(
						"Neoffice could not look up where {0} receives its mail: try again in a moment.",
						[found.domain]
					);
				if (S.provider === "neoservice")
					return found.provider === "neoservice"
						? __(
								"The domain {0} receives its mail at our host: its servers are set.",
								[found.domain]
						  )
						: __(
								"The domain {0} does not receive its mail at Neoservice's: choose the provider that hosts it.",
								[found.domain]
						  );
				if (S.provider === "google" || S.provider === "microsoft")
					return S.oauth[S.provider] === false
						? __("This site cannot sign in at this provider yet: ask Neoservice.")
						: __(
								"Next: the person signs in once at their provider and says yes, from « My mail »."
						  );
				return __(
					"Next: the password and the two servers. Neoffice tries them before adding."
				);
			};
			paint();
			if (S.detected && S.detected.email === email) return;
			S.detected = null;
			frappe
				.call({ method: API + "detect", args: { email } })
				.then((r) => {
					S.detected = Object.assign({ email }, r.message || {});
					// Where the domain says, unless the person chose already; Neoservice's mailbox when it says nothing
					if (["google", "microsoft", "neoservice"].includes(S.detected.provider))
						S.provider = S.detected.provider;
					paint();
				})
				.catch(() => {
					S.detected = { email, provider: "", domain: email.split("@")[1] || "" };
					paint();
				});
		}

		function draw_how() {
			const oauth = S.provider === "google" || S.provider === "microsoft";
			const other = S.provider === "other";
			d.set_df_property("password", "hidden", oauth ? 1 : 0);
			d.set_df_property("password", "reqd", oauth ? 0 : 1);
			["imap_host", "imap_port", "smtp_host", "smtp_port"].forEach((f) => {
				d.set_df_property(f, "hidden", other ? 0 : 1);
				if (f.endsWith("host")) d.set_df_property(f, "reqd", other ? 1 : 0);
			});
			const name = (providers().find((p) => p.key === S.provider) || {}).name;
			const text = oauth
				? __(
						"{0} signs in at {1} once, from « My mail »: Neoffice never sees their password.",
						[d.get_value("user") || "", name]
				  )
				: __(
						"The mailbox's password, as {0} gave it. Neoffice tries it before adding the mailbox.",
						[name]
				  );
			d.fields_dict.how.$wrapper.html(`<p class="mlt-lead">${esc(text)}</p>`);
			paint_tried();
		}

		function paint_tried() {
			const t = S.tried;
			const $t = d.fields_dict.tried.$wrapper;
			if (!t) return $t.html("");
			if (t === "trying")
				return $t.html(
					`<div class="mlt-note">${esc(__("Trying the mailbox's servers…"))}</div>`
				);
			if (t.success)
				return $t.html(
					`<div class="mlt-note mlt-note-ok">${esc(__("✓ The mailbox signs in."))}</div>`
				);
			$t.html(
				`<div class="mlt-note mlt-note-bad">${esc(
					__("It does not sign in: {0}", [(t.errors || []).join(" · ")])
				)}</div>`
			);
		}

		// The password is tried before going on, for the values typed now; a step that fails stays, with why
		function sign_in_ready(values) {
			if (S.provider === "google" || S.provider === "microsoft") return true;
			const key = JSON.stringify([
				values.email,
				S.provider,
				values.password,
				values.imap_host,
				values.imap_port,
				values.smtp_host,
				values.smtp_port,
			]);
			if (S.tried && S.tried.success && S.tried_for === key) return true;
			if (S.tried === "trying") return false;
			S.tried = "trying";
			S.tried_for = key;
			paint_tried();
			frappe
				.call({
					method: API + "try_connection",
					type: "POST",
					args: {
						email: values.email,
						provider: S.provider,
						password: values.password,
						imap_host: values.imap_host,
						imap_port: values.imap_port,
						smtp_host: values.smtp_host,
						smtp_port: values.smtp_port,
					},
				})
				.then((r) => {
					S.tried = r.message || { success: false, errors: [] };
					paint_tried();
					if (S.tried.success) d.step_next();
				})
				.catch(() => {
					S.tried = null;
					paint_tried();
				});
			return false;
		}

		function make(values) {
			frappe
				.call({
					method: API + "add",
					type: "POST",
					freeze: true,
					args: {
						user: values.user,
						email: values.email,
						provider: S.provider,
						password: values.password,
						imap_host: values.imap_host,
						imap_port: values.imap_port,
						smtp_host: values.smtp_host,
						smtp_port: values.smtp_port,
						readers: JSON.stringify(
							(values.readers || []).map((r) => r.user).filter(Boolean)
						),
					},
				})
				.then((r) => {
					if (!r.message) return;
					d.hide();
					frappe.show_alert({
						message: r.message.waits_to_connect
							? __(
									"The mailbox {0} is added: its owner connects it once, from « My mail ».",
									[r.message.email]
							  )
							: __("The mailbox {0} is added: it opens in NeoMail.", [
									r.message.email,
							  ]),
						indicator: "green",
					});
					if (typeof options.on_added === "function") options.on_added(r.message);
				});
		}
		return d;
	}

	// ---- « My mail » ---------------------------------------------------------------------------------------------------

	function box_card(box) {
		const who = box.mine
			? box.readers.length
				? __("Read also by {0}", [box.readers.map((r) => r.full_name).join(", ")])
				: __("Yours alone")
			: __("Shared · {0} answers for it", [box.owner_name]);
		let act = "";
		if (box.may_connect)
			act = `<button type="button" class="btn btn-primary btn-sm mlt-connect" data-box="${esc(
				box.name
			)}">${esc(__("Connect at {0}", [box.provider]))}</button>`;
		else if (box.mine && box.state.code === "password")
			act = `<a class="mlt-link" href="/app/webmail-account/${encodeURIComponent(
				box.name
			)}">${esc(__("Type its password"))}</a>`;
		return `<article class="mlt-box${
			box.mine && box.state.tone !== "success" && box.state.tone !== "muted"
				? " is-waiting"
				: ""
		}">
			<div class="mlt-box-address">${esc(box.email)}</div>
			<div class="mlt-box-facts">${pill(box.state)}<span>${esc(box.provider)}</span></div>
			<div class="mlt-box-who">${esc(who)}</div>${
			box.mine && box.added_by
				? `<div class="mlt-box-who">${esc(__("Added by {0}", [box.added_by]))}</div>`
				: ""
		}${act}
		</article>`;
	}

	function open_mine() {
		const d = new frappe.ui.Dialog({
			title: __("My mail"),
			eyebrow: __("Settings"),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
		});
		const $body = d.fields_dict.body.$wrapper;
		$body.html(
			`<div class="mlt-mine"><div class="mlt-col mlt-boxes"><span class="mlt-label">${esc(
				__("My mailboxes")
			)}</span><div class="mlt-list">${esc(
				__("Loading…")
			)}</div></div><div class="mlt-col mlt-signature"></div></div>`
		);
		d.show();
		styled();
		const draw = () =>
			frappe.call({ method: API + "mine" }).then((r) => {
				const m = r.message || { boxes: [] };
				const $list = $body.find(".mlt-list");
				const more = m.may_manage
					? `<button type="button" class="mlt-link mlt-add">+ ${esc(
							__("Add a mailbox")
					  )}</button>`
					: `<p class="mlt-small">${esc(
							__("Another mailbox? Your administrator adds it in Settings › Mail.")
					  )}</p>`;
				$list.html(
					(m.boxes.length
						? m.boxes.map(box_card).join("")
						: `<p class="mlt-small">${esc(__("No mailbox yet."))}</p>`) + more
				);
				$list
					.find(".mlt-connect")
					.on("click", (e) =>
						connect(m.boxes.find((b) => b.name === e.currentTarget.dataset.box))
					);
				$list.find(".mlt-add").on("click", () => {
					d.hide();
					add_mailbox({ user: frappe.session.user });
				});
			});
		draw();
		builder()
			.then(() =>
				frappe_webmail.signature_builder.mount($body.find(".mlt-signature"), {
					tab: "mine",
					only_mine: true,
					small_head: true,
				})
			)
			.catch(() => $body.find(".mlt-signature").html(""));
		return d;
	}

	// Signing in at Google or Microsoft: the provider's own page, then back to the desk (webmail_api.oauth_callback).
	// Who else will read the mailbox is said before, since connecting it opens it to them too.
	function connect(box) {
		if (!box) return;
		const go = () =>
			frappe
				.call({
					method: "frappe_webmail.api.get_oauth_authorization_url",
					args: { account_name: box.name },
				})
				.then((r) => {
					const url = r.message && r.message.authorization_url;
					if (url) window.location.href = url;
				});
		if (!box.readers.length) return go();
		frappe.confirm(
			__("Once connected, {0} will read this mailbox too. Connect it?", [
				box.readers.map((r) => r.full_name).join(", "),
			]),
			go
		);
	}

	// The builder drawn in a block of a page (Settings › Mail › Signatures), loaded first when it is not yet
	function mount_builder($el, opts) {
		return builder().then(() => frappe_webmail.signature_builder.mount($el, opts || {}));
	}

	Object.assign(frappe_webmail.mail_team, { add_mailbox, open_mine, mount_builder, pill, load });
})();
