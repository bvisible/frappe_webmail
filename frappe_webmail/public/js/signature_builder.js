// Copyright (c) 2026, Neoservice and contributors
// For license information, please see license.txt

/* global frappe_webmail */

/*
 * The signature builder: one window (the desk's dialog model, extra-large) where the company's signatures are made, one
 * model per group of people, and where each person sees theirs. Its server side: signature_builder.py. Its design: the
 * « Signatures NeoMail » canvas of Claude Design (17.11.2026), from the Neoffice design system.
 *
 * - « The team's signatures » (those who may write Email Signature Templates): the models on the left, each with whom it
 *   is given to; in the middle what the selected one is given to (everyone, a company, a department, a user group, roles),
 *   its layout and what each person may change; on the right the signature as a chosen person of the desk will send it,
 *   light, under a reader's dark mode or on a phone, and who sends it once saved.
 * - « My signature » (everyone): the model that applies to the person, as their messages carry it, and their own choices
 *   (their mobile, their photo).
 *
 * Opened by frappe_webmail.signature_builder.open() from NeoMail (File › Signatures, `?signatures=1` of /app/neomail),
 * from the list of Email Signature Templates and from the webmail. Loaded on demand (frappe.require).
 */

frappe.provide("frappe_webmail.signature_builder");

(function () {
	const API = "frappe_webmail.signature_builder.";
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	// The layouts in the order the builder offers them, the team's card first
	const LAYOUTS = [
		"Logo centre",
		"Logo above",
		"Logo left",
		"Compact",
		"Photo left",
		"Text only",
	];
	const KINDS = ["Everyone", "Company", "Department", "User Group", "Role"];
	// What a new model starts from when there is none to copy: the design system's e-mail rules
	const FRESH = {
		enabled: 1,
		applies_to: "Everyone",
		layout: "Logo centre",
		show_full_name: 1,
		show_job_title: 1,
		show_phone: 1,
		show_mobile: 1,
		show_email: 1,
		show_website: 1,
		show_logo: 1,
		show_contact_icons: 1,
		font: "Karla",
		accent_color: "#141414",
		font_size: 13,
		logo_width: 120,
	};
	// What a model copied from another keeps to itself
	const OWN = [
		"name",
		"template_name",
		"applies_to",
		"company",
		"department",
		"user_group",
		"roles",
	];

	function kind_label(kind) {
		return {
			Everyone: __("Everyone"),
			Company: __("Company"),
			Department: __("Department"),
			"User Group": __("User Group"),
			Role: __("Roles"),
		}[kind];
	}

	function layout_label(layout) {
		return layout === "Logo centre" ? __("Logo in the centre") : __(layout);
	}

	// A small drawing of a layout: bars for the words, clay for the contacts, a circle for a photo
	function thumb(layout) {
		const bar = (w, h, cls) =>
			`<i class="${cls || ""}" style="width:${w}px;height:${h}px"></i>`;
		const stack = (inner, end) => `<span class="st${end ? " end" : ""}">${inner}</span>`;
		const clay = bar(26, 4, "c") + bar(26, 4, "c") + bar(26, 4, "c");
		return {
			"Logo centre":
				stack(bar(26, 5) + bar(16, 4, "m"), true) +
				'<i class="r"></i>' +
				bar(22, 6) +
				'<i class="r"></i>' +
				stack(clay),
			"Logo above": stack(bar(24, 6) + bar(34, 5) + bar(28, 4, "c") + bar(28, 4, "c")),
			"Logo left":
				bar(22, 6) +
				'<i class="r"></i>' +
				stack(bar(34, 5) + bar(20, 4, "m") + bar(28, 4, "c")),
			Compact: stack(bar(60, 5) + bar(74, 4, "m")),
			"Photo left": '<i class="o"></i>' + stack(bar(34, 5) + bar(28, 4, "c") + bar(20, 5)),
			"Text only": stack(bar(34, 5) + bar(22, 4, "m") + bar(30, 4, "m")),
		}[layout];
	}

	function targets_of(model) {
		const k = model.applies_to;
		if (k === "Company") return model.company ? [model.company] : [];
		if (k === "Department") return model.department ? [model.department] : [];
		if (k === "User Group") return model.user_group ? [model.user_group] : [];
		if (k === "Role") return model.roles || [];
		return [];
	}

	function audience(model) {
		const targets = targets_of(model);
		const said =
			kind_label(model.applies_to) + (targets.length ? " : " + targets.join(", ") : "");
		return model.enabled ? said : said + " · " + __("off");
	}

	function open(opts) {
		const options = opts || {};
		const S = {
			data: null,
			tab: "team",
			models: [],
			at: 0,
			dirty: false,
			view: "light",
			person: frappe.session.user,
			reach: null,
			preview: null,
			ask: 0,
		};
		const d = new frappe.ui.Dialog({
			title: __("Signatures"),
			size: "extra-large",
			eyebrow: "NeoMail · " + __("Signatures"),
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
			primary_action_label: __("Save"),
			primary_action: () => save(),
		});
		d.neo_is_dirty = () => S.dirty;
		d.add_footer_link(__("All the settings: logo, font, small print, banner"), () => {
			const m = S.models[S.at];
			frappe.set_route(
				m && m.name
					? ["Form", "Email Signature Template", m.name]
					: ["List", "Email Signature Template"]
			);
			d.hide();
		});
		const $body = d.fields_dict.body.$wrapper;
		$body.html(`<div class="sigb"><div class="sigb-empty">${esc(__("Loading…"))}</div></div>`);
		d.show();

		frappe.call({ method: API + "state" }).then((r) => {
			S.data = r.message || {};
			S.models = (S.data.templates || []).map((t) => Object.assign({}, t));
			if (!S.data.can_edit || options.tab === "mine") S.tab = "mine";
			const wanted =
				options.template && S.models.findIndex((m) => m.name === options.template);
			if (wanted > 0) S.at = wanted;
			if (!S.models.length && S.data.can_edit) add_model();
			draw();
		});

		function current() {
			return S.models[S.at];
		}

		function changed() {
			S.dirty = true;
			draw_models();
			refresh();
		}

		function set_title() {
			d.set_title(S.tab === "team" ? __("The team's signatures") : __("My signature"));
			d.get_primary_btn().toggleClass("hide", S.tab !== "team");
		}

		function draw() {
			set_title();
			const tabs = S.data.can_edit
				? `<div class="sigb-tabs" role="tablist">
					<button type="button" class="sigb-tab" role="tab" data-tab="team" aria-selected="${
						S.tab === "team"
					}">${esc(__("The team's signatures"))}</button>
					<button type="button" class="sigb-tab" role="tab" data-tab="mine" aria-selected="${
						S.tab === "mine"
					}">${esc(__("My signature"))}</button>
				</div>`
				: "";
			const lead =
				S.tab === "team"
					? __(
							"One model for each group of people: give it to roles, a user group, a department or the whole company. Each person gets it filled from their own record."
					  )
					: __(
							"The signature your messages carry, from NeoMail, the webmail and the phone alike."
					  );
			$body.html(
				`<div class="sigb">${tabs}<p class="sigb-note" style="font-size:14px">${esc(
					lead
				)}</p><div class="sigb-main"></div></div>`
			);
			$body.find(".sigb-tab").on("click", (e) => {
				S.tab = $(e.currentTarget).data("tab");
				draw();
			});
			if (S.tab === "team") draw_team();
			else draw_mine();
		}

		// ---- the team's signatures --------------------------------------------------------------------------------------

		function draw_team() {
			const $main = $body.find(".sigb-main");
			$main.html(`<div class="sigb-cols">
				<div class="sigb-col">
					<span class="sigb-label">${esc(__("Models"))}</span>
					<div class="sigb-models"></div>
					<button type="button" class="sigb-link sigb-add">+ ${esc(__("New model"))}</button>
					<p class="sigb-note">${esc(
						__(
							"When several models fit a person, the most precise wins: their department, then their group, then their roles, then their company."
						)
					)}</p>
				</div>
				<div class="sigb-col sigb-editor"></div>
				<div class="sigb-col sigb-right"></div>
			</div>`);
			$main.find(".sigb-add").on("click", () => {
				add_model();
				changed();
				draw_editor();
			});
			draw_models();
			draw_editor();
			draw_right();
			refresh();
		}

		function draw_models() {
			const $list = $body.find(".sigb-models");
			$list.html(
				S.models
					.map(
						(
							m,
							i
						) => `<button type="button" class="sigb-model" data-i="${i}" aria-pressed="${
							i === S.at
						}">
					<b>${esc(m.template_name || __("New model"))}</b>
					<span>${esc(layout_label(m.layout))}</span>
					<span class="${m.enabled ? "" : "off"}">${esc(audience(m))}</span>
				</button>`
					)
					.join("")
			);
			$list.find(".sigb-model").on("click", (e) => {
				S.at = Number($(e.currentTarget).data("i"));
				S.reach = null;
				draw_models();
				draw_editor();
				refresh();
			});
		}

		function add_model() {
			const from = current() || null;
			const fresh = Object.assign({}, FRESH);
			if (from) {
				Object.keys(from).forEach((k) => {
					if (OWN.indexOf(k) === -1) fresh[k] = from[k];
				});
			}
			fresh.template_name = "";
			fresh.applies_to = "Role";
			fresh.roles = [];
			fresh.enabled = 1;
			S.models.push(fresh);
			S.at = S.models.length - 1;
			S.reach = null;
		}

		function options_html(list, chosen, placeholder) {
			return (
				`<option value="">${esc(placeholder)}</option>` +
				(list || [])
					.map(
						(v) =>
							`<option value="${esc(v)}"${v === chosen ? " selected" : ""}>${esc(
								v
							)}</option>`
					)
					.join("")
			);
		}

		function switch_html(field, label, checked) {
			return `<label class="sigb-switch"><input type="checkbox" data-field="${field}"${
				checked ? " checked" : ""
			}><span aria-hidden="true"></span>${esc(label)}</label>`;
		}

		function draw_editor() {
			const m = current();
			const $ed = $body.find(".sigb-editor");
			if (!m) {
				$ed.html("");
				return;
			}
			const c = S.data.choices || {};
			let target = "";
			if (m.applies_to === "Company")
				target = `<select class="sigb-select" data-field="company">${options_html(
					c.companies,
					m.company,
					__("Choose a company")
				)}</select>`;
			else if (m.applies_to === "Department")
				target = `<select class="sigb-select" data-field="department">${options_html(
					c.departments,
					m.department,
					__("Choose a department")
				)}</select>`;
			else if (m.applies_to === "User Group")
				target = (c.user_groups || []).length
					? `<select class="sigb-select" data-field="user_group">${options_html(
							c.user_groups,
							m.user_group,
							__("Choose a user group")
					  )}</select>`
					: `<p class="sigb-note">${esc(
							__("No user group yet: make one in User Group, then come back.")
					  )}</p>`;
			else if (m.applies_to === "Role") {
				const roles = m.roles || [];
				target = `<div class="sigb-chips">${roles
					.map(
						(r) =>
							`<span class="sigb-tag">${esc(
								r
							)}<button type="button" data-remove-role="${esc(r)}" aria-label="${esc(
								__("Remove {0}", [r])
							)}">×</button></span>`
					)
					.join("")}</div>
					<select class="sigb-select sigb-add-role">${options_html(
						(c.roles || []).filter((r) => roles.indexOf(r) === -1),
						"",
						__("+ Add a role")
					)}</select>`;
			}
			$ed.html(`
				<div class="sigb-section">
					<span class="sigb-label">${esc(__("Name of the model"))}</span>
					<input class="sigb-input" data-field="template_name" value="${esc(
						m.template_name || ""
					)}" placeholder="${esc(__("For example: Support"))}">
					${switch_html("enabled", __("In use"), !!m.enabled)}
				</div>
				<div class="sigb-section">
					<span class="sigb-label">${esc(__("Given to"))}</span>
					<div class="sigb-chips" role="group" aria-label="${esc(__("Given to"))}">${KINDS.map(
				(k) =>
					`<button type="button" class="sigb-chip" data-kind="${esc(k)}" aria-pressed="${
						m.applies_to === k
					}">${esc(kind_label(k))}</button>`
			).join("")}</div>
					${target}
				</div>
				<div class="sigb-section">
					<span class="sigb-label">${esc(__("Layout"))}</span>
					<div class="sigb-tiles">${LAYOUTS.map(
						(l) =>
							`<button type="button" class="sigb-tile" data-layout="${esc(
								l
							)}" aria-pressed="${
								m.layout === l
							}"><span class="sigb-thumb" aria-hidden="true">${thumb(
								l
							)}</span><b>${esc(layout_label(l))}</b></button>`
					).join("")}</div>
				</div>
				<div class="sigb-section">
					<span class="sigb-label">${esc(__("What it shows"))}</span>
					<div class="sigb-switches">
						${switch_html(
							"show_contact_icons",
							__("An icon before each number and address"),
							!!m.show_contact_icons
						)}
						${switch_html("show_mobile", __("The mobile number"), !!m.show_mobile)}
						${switch_html("show_disclaimer", __("The small print"), !!m.show_disclaimer)}
						${switch_html(
							"allow_personal",
							__("Each person may keep their own signature"),
							!!m.allow_personal
						)}
					</div>
				</div>`);
			$ed.find('[data-field="template_name"]').on("input", (e) => {
				m.template_name = e.target.value;
				S.dirty = true;
				draw_models();
			});
			$ed.find("input[type=checkbox][data-field]").on("change", (e) => {
				m[$(e.target).data("field")] = e.target.checked ? 1 : 0;
				changed();
			});
			$ed.find("select[data-field]").on("change", (e) => {
				m[$(e.target).data("field")] = e.target.value || null;
				changed();
			});
			$ed.find(".sigb-chip[data-kind]").on("click", (e) => {
				m.applies_to = $(e.currentTarget).data("kind");
				changed();
				draw_editor();
			});
			$ed.find(".sigb-tile").on("click", (e) => {
				m.layout = $(e.currentTarget).data("layout");
				changed();
				draw_editor();
			});
			$ed.find(".sigb-add-role").on("change", (e) => {
				if (!e.target.value) return;
				m.roles = (m.roles || []).concat([e.target.value]);
				changed();
				draw_editor();
			});
			$ed.find("[data-remove-role]").on("click", (e) => {
				const role = $(e.currentTarget).attr("data-remove-role");
				m.roles = (m.roles || []).filter((r) => r !== role);
				changed();
				draw_editor();
			});
		}

		function draw_right() {
			const people = S.data.people || [];
			// The person who asks when they are one the models reach, else the first of them (Administrator is none)
			if (people.length && !people.some((p) => p.user === S.person))
				S.person = people[0].user;
			$body.find(".sigb-right").html(`
				<div class="sigb-preview-bar">
					<label class="sigb-label" for="sigb-person">${esc(__("Preview for"))}</label>
					<select class="sigb-select" id="sigb-person" style="width:auto;flex:1;min-width:0">${people
						.map(
							(p) =>
								`<option value="${esc(p.user)}"${
									p.user === S.person ? " selected" : ""
								}>${esc(p.full_name)}</option>`
						)
						.join("")}</select>
					${views_html()}
				</div>
				<div class="sigb-stage"><iframe class="sigb-frame" title="${esc(
					__("Preview")
				)}" sandbox="allow-same-origin"></iframe></div>
				<span class="sigb-label sigb-reach-title">${esc(__("Who sends it"))}</span>
				<div class="sigb-people"></div>`);
			$body.find("#sigb-person").on("change", (e) => {
				S.person = e.target.value;
				refresh_preview();
			});
			bind_views();
		}

		function views_html() {
			return `<div class="sigb-seg" role="group" aria-label="${esc(
				__("How it is seen")
			)}">${[
				["light", __("Light")],
				["dark", __("Dark")],
				["phone", __("Phone")],
			]
				.map(
					([v, label]) =>
						`<button type="button" class="sigb-chip" data-view="${v}" aria-pressed="${
							S.view === v
						}">${esc(label)}</button>`
				)
				.join("")}</div>`;
		}

		function bind_views() {
			$body.find(".sigb-chip[data-view]").on("click", (e) => {
				S.view = $(e.currentTarget).data("view");
				$body
					.find(".sigb-chip[data-view]")
					.each((_, el) =>
						el.setAttribute("aria-pressed", String(el.dataset.view === S.view))
					);
				paint();
			});
		}

		// The model as the server reads it (its roles a list of names)
		function payload(m) {
			return Object.assign({}, m, { roles: (m.roles || []).slice() });
		}

		function refresh() {
			refresh_preview();
			refresh_reach();
		}

		function refresh_preview() {
			const m = current();
			if (S.tab !== "team" || !m) return;
			const asked = ++S.ask;
			frappe
				.call({
					method: API + "preview",
					args: { doc: payload(m), user: S.person },
					type: "POST",
				})
				.then((r) => {
					if (asked !== S.ask) return;
					S.preview = (r.message && r.message.html) || "";
					paint();
				});
		}

		function refresh_reach() {
			const m = current();
			if (S.tab !== "team" || !m) return;
			frappe
				.call({ method: API + "reach", args: { doc: payload(m) }, type: "POST" })
				.then((r) => {
					S.reach = r.message || null;
					draw_reach();
				});
		}

		function draw_reach() {
			const $p = $body.find(".sigb-people");
			if (!S.reach) return;
			const m = current();
			const names = {};
			S.models.forEach((t) => {
				if (t.name) names[t.name] = t.template_name;
			});
			const shown = S.reach.people.filter((p) => p.applies || p.today === (m && m.name));
			$body
				.find(".sigb-reach-title")
				.text(__("Who sends it") + " · " + __("{0} people", [S.reach.count]));
			if (!shown.length) {
				$p.html(
					`<div class="sigb-person"><small>${esc(
						__("Nobody yet: choose whom it is given to.")
					)}</small></div>`
				);
				return;
			}
			$p.html(
				shown
					.map((p) => {
						let pill = `<span class="sigb-pill yes">${esc(__("Sends it"))}</span>`;
						if (!p.sends) {
							const other = names[p.today] || p.today;
							pill = p.applies
								? `<span class="sigb-pill other">${esc(
										other ? __("Takes {0}", [other]) : __("Not in use")
								  )}</span>`
								: `<span class="sigb-pill">${esc(__("No longer"))}</span>`;
						}
						const lacks = p.missing.length
							? `<small>${esc(
									__("No {0} on their record", [p.missing.join(", ")])
							  )}</small>`
							: "";
						return `<div class="sigb-person"><span>${esc(
							p.full_name
						)}<br>${lacks}</span>${pill}</div>`;
					})
					.join("")
			);
		}

		// The signature in a message, as a reader's mail client draws it: a white page, its own pictures; « dark » as a
		// client that inverts everything but pictures, « phone » 343 px wide, scaled down to fit as a phone's client does
		function paint(html) {
			const frame = $body.find(".sigb-frame")[0];
			if (!frame) return;
			const signature = html != null ? html : S.preview || "";
			frame.classList.toggle("phone", S.view === "phone");
			const dark = S.view === "dark" ? "filter:invert(1) hue-rotate(180deg);" : "";
			const unflip = S.view === "dark" ? "img{filter:invert(1) hue-rotate(180deg)}" : "";
			frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><style>html{background:#fff;${dark}}body{margin:0;padding:18px 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:21px;color:#141414}${unflip}.msg{margin:0 0 18px}</style></head><body><div class="msg">${esc(
				__("Hello,")
			)}<br><br>${esc(__("Here is the document we spoke about."))}<br><br>${esc(
				__("Have a good day,")
			)}</div><div id="sig">${signature}</div></body></html>`;
			frame.onload = () => {
				const doc = frame.contentDocument;
				if (!doc || !doc.body) return;
				if (S.view === "phone") {
					const wide = doc.body.scrollWidth;
					const room = frame.clientWidth;
					if (wide > room) doc.body.style.zoom = String(room / wide);
				}
			};
		}

		function save() {
			const m = current();
			if (!m || S.tab !== "team") return;
			if (!(m.template_name || "").trim()) {
				frappe.show_alert({ message: __("Give the model a name."), indicator: "orange" });
				$body.find('[data-field="template_name"]').trigger("focus");
				return;
			}
			frappe
				.call({
					method: API + "save",
					args: { doc: payload(m) },
					type: "POST",
					freeze: true,
				})
				.then((r) => {
					if (!r.message) return;
					S.models[S.at] = Object.assign({}, r.message);
					S.dirty = false;
					draw_models();
					draw_editor();
					refresh();
					frappe.show_alert({
						message: __(
							"Saved. NeoMail, the webmail and the phone use it from the next message."
						),
						indicator: "green",
					});
					if (typeof options.on_saved === "function") options.on_saved(r.message);
				});
		}

		// ---- my signature ---------------------------------------------------------------------------------------------

		function draw_mine() {
			const mine = (S.data && S.data.mine) || {};
			const $main = $body.find(".sigb-main");
			const which = mine.template_name
				? __("You send the model « {0} ».", [mine.template_name])
				: __(
						"No model of the company applies to you: your messages carry your own signature, if you wrote one in the webmail."
				  );
			const choices = [];
			if (mine.mobile)
				choices.push(
					switch_html("hide_mobile", __("Hide my mobile number"), !!mine.hide_mobile)
				);
			if (mine.photo)
				choices.push(
					switch_html("photo_allowed", __("Show my photo"), !!mine.photo_allowed)
				);
			$main.html(`<div class="sigb-cols mine">
				<div class="sigb-col">
					<div class="sigb-section"><span class="sigb-label">${esc(
						__("Your model")
					)}</span><p class="sigb-note" style="font-size:14px;color:inherit">${esc(
				which
			)}</p></div>
					${
						choices.length
							? `<div class="sigb-section"><span class="sigb-label">${esc(
									__("Your choices")
							  )}</span><div class="sigb-switches">${choices.join("")}</div></div>`
							: ""
					}
					<a class="sigb-link" href="/app/webmail?signatures=1" target="_blank" rel="noopener">${esc(
						__("My own signatures")
					)}</a>
				</div>
				<div class="sigb-col">
					<div class="sigb-preview-bar"><span class="sigb-label">${esc(
						__("As your messages carry it")
					)}</span>${views_html()}</div>
					<div class="sigb-stage"><iframe class="sigb-frame" title="${esc(
						__("Preview")
					)}" sandbox="allow-same-origin"></iframe></div>
				</div>
			</div>`);
			bind_views();
			$main.find("input[type=checkbox][data-field]").on("change", (e) => {
				const args = {};
				args[$(e.target).data("field")] = e.target.checked ? 1 : 0;
				frappe
					.call({
						method: "frappe_webmail.signatures.save_my_choices",
						args,
						type: "POST",
					})
					.then((r) => {
						if (r.message) Object.assign(S.data.mine, r.message);
						load_mine();
					});
			});
			load_mine();
		}

		function load_mine() {
			frappe.call({ method: API + "my_preview" }).then((r) => {
				S.preview = (r.message && r.message.html) || "";
				paint();
			});
		}

		return d;
	}

	frappe_webmail.signature_builder.open = function (opts) {
		return open(opts);
	};

	// Loaded on demand, then opened: what the pages that offer it call
	frappe_webmail.signature_builder.load_and_open = function (opts) {
		return frappe
			.require(["/assets/frappe_webmail/css/signature_builder.css"])
			.then(() => open(opts));
	};
})();
