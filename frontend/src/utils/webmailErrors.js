/**
 * Webmail error handling
 *
 * Turns backend WebmailAuthenticationError / WebmailConnectionError responses
 * into friendly dialogs instead of Frappe's raw "Server Error" traceback popup.
 *
 * The backend raises these as frappe.ValidationError subclasses (HTTP 417) with
 * a recognizable `exc_type`. Frappe's request layer (frappe.request.cleanup)
 * invokes handlers registered through `frappe.request.on_error(exc_type, fn)`
 * and skips its own automatic msgprint whenever a handler is registered.
 */

// Translation helper - falls back to the identity function if not yet available.
const __ = (typeof window !== "undefined" && window.__) || ((s) => s);

const AUTH_EXC = "WebmailAuthenticationError";
const CONN_EXC = "WebmailConnectionError";

let registered = false;
// Reference to the currently open re-auth dialog, so we never stack two.
let activeDialog = null;

/**
 * Register the global webmail error handlers.
 * Safe to call multiple times - only the first call takes effect.
 */
export function registerWebmailErrorHandlers() {
	if (registered) return;
	if (
		typeof frappe === "undefined" ||
		!frappe.request ||
		typeof frappe.request.on_error !== "function"
	) {
		return;
	}
	frappe.request.on_error(AUTH_EXC, handleAuthError);
	frappe.request.on_error(CONN_EXC, handleConnectionError);
	registered = true;
}

/**
 * Read the structured webmail_error payload sent by the backend, falling back
 * to the account currently open in the webmail UI.
 */
function extractWebmailError(r) {
	const info = {};
	if (r && r.webmail_error && typeof r.webmail_error === "object") {
		Object.assign(info, r.webmail_error);
	}
	const getActive = window.frappe && frappe.webmail && frappe.webmail.getActiveAccount;
	if (typeof getActive === "function") {
		const active = getActive();
		if (active) {
			if (!info.account) info.account = active.name;
			if (!info.email) info.email = active.email;
			if (!info.auth_type) info.auth_type = active.auth_type;
		}
	}
	return info;
}

/** Extract the human-readable message the backend put in _server_messages. */
function getServerMessage(r, fallback) {
	if (r && r._server_messages) {
		try {
			const list = JSON.parse(r._server_messages);
			if (list && list.length) {
				const first = list[0];
				const parsed = typeof first === "string" ? JSON.parse(first) : first;
				if (parsed && parsed.message) return parsed.message;
			}
		} catch (e) {
			/* malformed payload - fall through to the default */
		}
	}
	return fallback;
}

/** Handler for WebmailAuthenticationError (bad credentials / expired OAuth). */
function handleAuthError(r) {
	if (activeDialog) return; // never stack re-auth dialogs
	const info = extractWebmailError(r);
	const message = getServerMessage(r, __("The email address or password is incorrect."));
	if (info.auth_type === "OAuth2") {
		openOAuthReconnectDialog(info, message);
	} else {
		openPasswordReauthDialog(info, message);
	}
}

/** Handler for WebmailConnectionError (server unreachable, SSL, timeout...). */
function handleConnectionError(r) {
	const message = getServerMessage(
		r,
		__("Could not connect to the email server. Check the account settings.")
	);
	frappe.msgprint({
		title: __("Email Connection Failed"),
		message: message,
		indicator: "red",
	});
}

/** Dialog to re-enter the password for a Password-auth account. */
function openPasswordReauthDialog(info, message) {
	const emailLabel = info.email || __("your email account");

	const dialog = new frappe.ui.Dialog({
		title: __("Incorrect password"),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: introHtml(
					message,
					__("Enter the current password for this account to reconnect.")
				),
			},
			{
				fieldtype: "Password",
				fieldname: "password",
				label: __("Password for {0}", [emailLabel]),
				reqd: 1,
			},
		],
		primary_action_label: __("Save and retry"),
		primary_action(values) {
			if (!values || !values.password) return;
			if (!info.account) {
				frappe.msgprint(__("Unable to determine which account to update."));
				return;
			}
			const btn = dialog.get_primary_btn();
			btn.prop("disabled", true).text(__("Saving..."));
			frappe.call({
				method: "frappe_webmail.api.update_account_password",
				args: {
					account_name: info.account,
					imap_password: values.password,
					smtp_password: values.password,
				},
				callback() {
					dialog.hide();
					frappe.show_alert({ message: __("Password updated"), indicator: "green" }, 5);
					retryWebmail();
				},
				error() {
					btn.prop("disabled", false).text(__("Save and retry"));
				},
			});
		},
	});

	trackDialog(dialog);
	dialog.show();
}

/** Dialog to restart the OAuth flow for an OAuth2 account. */
function openOAuthReconnectDialog(info, message) {
	const dialog = new frappe.ui.Dialog({
		title: __("Reconnect your account"),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: introHtml(
					message,
					__("Reconnect the account to refresh its authorization.")
				),
			},
		],
		primary_action_label: __("Reconnect"),
		primary_action() {
			if (!info.account) {
				dialog.hide();
				return;
			}
			const btn = dialog.get_primary_btn();
			btn.prop("disabled", true).text(__("Redirecting..."));
			frappe.call({
				method: "frappe_webmail.api.get_oauth_authorization_url",
				args: { account_name: info.account },
				callback(res) {
					const url =
						res.message &&
						(res.message.url || res.message.authorization_url || res.message);
					if (typeof url === "string" && url) {
						window.location.href = url;
					} else {
						dialog.hide();
					}
				},
				error() {
					btn.prop("disabled", false).text(__("Reconnect"));
				},
			});
		},
	});

	trackDialog(dialog);
	dialog.show();
}

/** Build the intro HTML block shown at the top of a re-auth dialog. */
function introHtml(message, hint) {
	const esc = (frappe.utils && frappe.utils.escape_html) || ((s) => s);
	return `<div style="margin-bottom:12px;line-height:1.6">
		<div>${esc(message)}</div>
		<div class="text-muted" style="margin-top:6px">${esc(hint)}</div>
	</div>`;
}

/** Keep a single dialog reference so we never stack two of them. */
function trackDialog(dialog) {
	activeDialog = dialog;
	dialog.$wrapper.on("hidden.bs.modal", () => {
		activeDialog = null;
	});
}

/** Reload the webmail so every panel picks up the new credentials. */
function retryWebmail() {
	setTimeout(() => window.location.reload(), 400);
}
