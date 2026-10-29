// Copyright (c) 2024, Neoservice and contributors
// For license information, please see license.txt

frappe.ui.form.on("Webmail Account", {
	refresh: function (frm) {
		// Update OAuth status display
		if (frm.doc.auth_type === "OAuth2") {
			update_oauth_status(frm);
		}

		// Add test connection button
		frm.add_custom_button(__("Test Connection"), function () {
			test_connection(frm);
		});

		show_nora(frm);
	},

	auth_type: function (frm) {
		// Auto-fill provider settings when changing to OAuth2
		if (frm.doc.auth_type === "OAuth2" && frm.doc.oauth_provider) {
			apply_provider_defaults(frm);
		}
	},

	provider_preset: function (frm) {
		// Password providers: fill the IMAP/SMTP servers (mirrors PASSWORD_PROVIDERS in the controller)
		const presets = {
			Infomaniak: {
				imap_host: "mail.infomaniak.com",
				imap_port: 993,
				imap_ssl: 1,
				smtp_host: "mail.infomaniak.com",
				smtp_port: 587,
				smtp_ssl: 0,
				smtp_starttls: 1,
			},
		};
		const settings = presets[frm.doc.provider_preset];
		if (settings) {
			Object.keys(settings).forEach((fieldname) =>
				frm.set_value(fieldname, settings[fieldname])
			);
		}
	},

	oauth_provider: function (frm) {
		// Auto-fill settings when provider is selected
		if (frm.doc.oauth_provider) {
			apply_provider_defaults(frm);
		}
	},

	oauth_connect_btn: function (frm) {
		// Handle OAuth connect button click
		if (!frm.doc.name) {
			frappe.msgprint(__("Please save the document first."));
			return;
		}

		if (!frm.doc.oauth_provider) {
			frappe.msgprint(__("Please select an OAuth provider."));
			return;
		}

		// Get authorization URL and redirect
		frappe.call({
			method: "frappe_webmail.api.get_oauth_authorization_url",
			args: {
				account_name: frm.doc.name,
			},
			callback: function (r) {
				if (r.message && r.message.authorization_url) {
					// Open in new window/redirect
					window.open(r.message.authorization_url, "_self");
				}
			},
		});
	},
});

function apply_provider_defaults(frm) {
	const providers = {
		Gmail: {
			imap_host: "imap.gmail.com",
			imap_port: 993,
			imap_ssl: 1,
			smtp_host: "smtp.gmail.com",
			smtp_port: 587,
			smtp_ssl: 0,
			smtp_starttls: 1,
		},
		Outlook: {
			imap_host: "outlook.office365.com",
			imap_port: 993,
			imap_ssl: 1,
			smtp_host: "smtp.office365.com",
			smtp_port: 587,
			smtp_ssl: 0,
			smtp_starttls: 1,
		},
	};

	const settings = providers[frm.doc.oauth_provider];
	if (settings) {
		frm.set_value("imap_host", settings.imap_host);
		frm.set_value("imap_port", settings.imap_port);
		frm.set_value("imap_ssl", settings.imap_ssl);
		frm.set_value("smtp_host", settings.smtp_host);
		frm.set_value("smtp_port", settings.smtp_port);
		frm.set_value("smtp_ssl", settings.smtp_ssl);
		frm.set_value("smtp_starttls", settings.smtp_starttls);
	}
}

function update_oauth_status(frm) {
	if (frm.doc.oauth_access_token && frm.doc.oauth_token_expiry) {
		const expiry = frappe.datetime.str_to_obj(frm.doc.oauth_token_expiry);
		const now = new Date();

		if (expiry > now) {
			frm.set_value("oauth_status", "Connected");
			// Add disconnect button
			frm.add_custom_button(
				__("Disconnect OAuth"),
				function () {
					disconnect_oauth(frm);
				},
				__("OAuth")
			);
		} else {
			frm.set_value("oauth_status", "Token Expired - Please Reconnect");
		}
	} else if (frm.doc.oauth_provider) {
		frm.set_value("oauth_status", "Not Connected");
	}
}

function test_connection(frm) {
	// Validate required fields
	if (!frm.doc.email) {
		frappe.msgprint(__("Please enter an email address."));
		return;
	}
	if (!frm.doc.imap_host) {
		frappe.msgprint(__("Please enter the IMAP server address."));
		return;
	}
	if (!frm.doc.smtp_host) {
		frappe.msgprint(__("Please enter the SMTP server address."));
		return;
	}

	// For password auth, check passwords
	if (frm.doc.auth_type === "Password") {
		// Get passwords from form fields (they may be unsaved)
		const imap_password = frm.doc.imap_password;
		const smtp_password = frm.doc.smtp_password;

		if (!imap_password) {
			frappe.msgprint(__("Please enter the IMAP password."));
			return;
		}
		if (!smtp_password) {
			frappe.msgprint(__("Please enter the SMTP password."));
			return;
		}
	}

	// Show loading indicator
	frappe.show_progress(__("Testing Connection"), 0, 100, __("Connecting to servers..."));

	// Use live test with form values
	frappe.call({
		method: "frappe_webmail.api.test_connection_live",
		args: {
			email: frm.doc.email,
			imap_host: frm.doc.imap_host,
			imap_port: frm.doc.imap_port || 993,
			imap_ssl: frm.doc.imap_ssl ? 1 : 0,
			smtp_host: frm.doc.smtp_host,
			smtp_port: frm.doc.smtp_port || 587,
			smtp_ssl: frm.doc.smtp_ssl ? 1 : 0,
			smtp_starttls: frm.doc.smtp_starttls ? 1 : 0,
			auth_type: frm.doc.auth_type || "Password",
			imap_password: frm.doc.imap_password || "",
			smtp_password: frm.doc.smtp_password || "",
			oauth_provider: frm.doc.oauth_provider || "",
			oauth_access_token: frm.doc.oauth_access_token || "",
		},
		callback: function (r) {
			frappe.hide_progress();

			if (r.message) {
				if (r.message.success) {
					frappe.msgprint({
						title: __("Success"),
						indicator: "green",
						message: __("Connection successful! Both IMAP and SMTP are working."),
					});
				} else {
					// Build detailed error message
					let message = "";

					// Show individual status
					if (r.message.imap_success) {
						message +=
							'<p><span class="text-success">✓</span> ' +
							__("IMAP: Connected successfully") +
							"</p>";
					}
					if (r.message.smtp_success) {
						message +=
							'<p><span class="text-success">✓</span> ' +
							__("SMTP: Connected successfully") +
							"</p>";
					}

					// Show errors
					if (r.message.errors && r.message.errors.length > 0) {
						message += "<hr><p><strong>" + __("Errors:") + "</strong></p>";
						message += "<ul>";
						r.message.errors.forEach(function (err) {
							message += '<li class="text-danger">' + err + "</li>";
						});
						message += "</ul>";
					}

					frappe.msgprint({
						title: __("Connection Test Results"),
						indicator: "red",
						message: message,
					});
				}
			}
		},
		error: function (r) {
			frappe.hide_progress();
			frappe.msgprint({
				title: __("Error"),
				indicator: "red",
				message: __("Failed to test connection. Please check your settings."),
			});
		},
	});
}

function disconnect_oauth(frm) {
	frappe.confirm(
		__(
			"Are you sure you want to disconnect OAuth? You will need to reconnect to use this account."
		),
		function () {
			frappe.call({
				method: "frappe_webmail.api.disconnect_oauth",
				args: {
					account_name: frm.doc.name,
				},
				callback: function (r) {
					if (r.message && r.message.success) {
						frappe.msgprint(__("OAuth disconnected successfully."));
						frm.reload_doc();
					}
				},
			});
		}
	);
}

// Nora's side of the person's own mailbox: whether she prepares replies to their e-mails, and what she keeps of their
// way of writing. The same switches as « My style » in NeoMail (nora.api.mail_ready.my_style), so that the page a
// mailbox is set up on has them too. Only where Nora is installed, and only on one's own mailbox: the style is the
// person's, learnt from a mailbox of theirs.
function show_nora(frm) {
	if (frm.is_new() || frm.doc.user !== frappe.session.user) return;
	if (!(frappe.boot.versions && frappe.boot.versions.nora)) return;
	frappe
		.call({ method: "nora.api.mail_ready.my_style", args: { action: "get" } })
		.then((r) => {
			const style = r && r.message;
			if (!style || !style.success) return;
			frm.dashboard.set_headline(nora_headline(style), style.ready_replies ? "green" : "blue");
			const group = __("Nora");
			if (style.ready_replies) {
				frm.add_custom_button(__("Stop ready replies"), () => nora_style(frm, "disable"), group);
			} else {
				frm.add_custom_button(
					__("Prepare ready replies"),
					() =>
						frappe.confirm(
							__(
								"Nora will prepare replies to your e-mails in your way of writing, learnt from your sent e-mails. She never sends anything: you choose, change and send."
							),
							() => nora_style(frm, "enable")
						),
					group
				);
			}
			if (style.own_mailbox) {
				frm.add_custom_button(__("Learn my style again"), () => nora_style(frm, "relearn"), group);
			}
			if (style.exists && (style.learnt_on || (style.points || []).length)) {
				frm.add_custom_button(
					__("Forget my style"),
					() =>
						frappe.confirm(
							__("Nora will forget what she learnt of your way of writing, and learn no more until you ask her to."),
							() => nora_style(frm, "forget")
						),
					group
				);
			}
		})
		// No Nora here, or no right to her: the page stays as it was.
		.catch(() => {});
}

function nora_headline(style) {
	const replies = style.ready_replies
		? __("Nora prepares replies to your e-mails in your way of writing.")
		: __("Nora does not prepare replies to your e-mails.");
	let learnt;
	if (style.style && style.style.learning) {
		learnt = __("She is learning your way of writing.");
	} else if (style.learnt_on) {
		learnt = __("Your way of writing was learnt on {0} from {1}.", [
			frappe.utils.escape_html(style.learnt_on),
			frappe.utils.escape_html(style.mailbox || ""),
		]);
	} else {
		learnt = __("She has not learnt your way of writing yet.");
	}
	return `${replies} ${learnt}`;
}

function nora_style(frm, action) {
	frappe
		.call({ method: "nora.api.mail_ready.my_style", args: { action }, freeze: true })
		.then(() => frm.refresh());
}
