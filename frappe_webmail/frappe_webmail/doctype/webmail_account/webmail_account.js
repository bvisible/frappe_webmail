// Copyright (c) 2024, Neoservice and contributors
// For license information, please see license.txt

frappe.ui.form.on('Webmail Account', {
	refresh: function(frm) {
		// Update OAuth status display
		if (frm.doc.auth_type === 'OAuth2') {
			update_oauth_status(frm);
		}

		// Add test connection button
		frm.add_custom_button(__('Test Connection'), function() {
			test_connection(frm);
		});
	},

	auth_type: function(frm) {
		// Auto-fill provider settings when changing to OAuth2
		if (frm.doc.auth_type === 'OAuth2' && frm.doc.oauth_provider) {
			apply_provider_defaults(frm);
		}
	},

	oauth_provider: function(frm) {
		// Auto-fill settings when provider is selected
		if (frm.doc.oauth_provider) {
			apply_provider_defaults(frm);
		}
	},

	oauth_connect_btn: function(frm) {
		// Handle OAuth connect button click
		if (!frm.doc.name) {
			frappe.msgprint(__('Please save the document first.'));
			return;
		}

		if (!frm.doc.oauth_provider) {
			frappe.msgprint(__('Please select an OAuth provider.'));
			return;
		}

		// Get authorization URL and redirect
		frappe.call({
			method: 'frappe_webmail.api.get_oauth_authorization_url',
			args: {
				account_name: frm.doc.name
			},
			callback: function(r) {
				if (r.message && r.message.authorization_url) {
					// Open in new window/redirect
					window.open(r.message.authorization_url, '_self');
				}
			}
		});
	}
});

function apply_provider_defaults(frm) {
	const providers = {
		'Gmail': {
			imap_host: 'imap.gmail.com',
			imap_port: 993,
			imap_ssl: 1,
			smtp_host: 'smtp.gmail.com',
			smtp_port: 587,
			smtp_ssl: 0,
			smtp_starttls: 1
		},
		'Outlook': {
			imap_host: 'outlook.office365.com',
			imap_port: 993,
			imap_ssl: 1,
			smtp_host: 'smtp.office365.com',
			smtp_port: 587,
			smtp_ssl: 0,
			smtp_starttls: 1
		}
	};

	const settings = providers[frm.doc.oauth_provider];
	if (settings) {
		frm.set_value('imap_host', settings.imap_host);
		frm.set_value('imap_port', settings.imap_port);
		frm.set_value('imap_ssl', settings.imap_ssl);
		frm.set_value('smtp_host', settings.smtp_host);
		frm.set_value('smtp_port', settings.smtp_port);
		frm.set_value('smtp_ssl', settings.smtp_ssl);
		frm.set_value('smtp_starttls', settings.smtp_starttls);
	}
}

function update_oauth_status(frm) {
	if (frm.doc.oauth_access_token && frm.doc.oauth_token_expiry) {
		const expiry = frappe.datetime.str_to_obj(frm.doc.oauth_token_expiry);
		const now = new Date();

		if (expiry > now) {
			frm.set_value('oauth_status', 'Connected');
			// Add disconnect button
			frm.add_custom_button(__('Disconnect OAuth'), function() {
				disconnect_oauth(frm);
			}, __('OAuth'));
		} else {
			frm.set_value('oauth_status', 'Token Expired - Please Reconnect');
		}
	} else if (frm.doc.oauth_provider) {
		frm.set_value('oauth_status', 'Not Connected');
	}
}

function test_connection(frm) {
	if (!frm.doc.name) {
		frappe.msgprint(__('Please save the document first.'));
		return;
	}

	frappe.call({
		method: 'frappe_webmail.api.test_connection',
		args: {
			account_name: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				if (r.message.success) {
					frappe.msgprint({
						title: __('Success'),
						indicator: 'green',
						message: __('Connection successful!')
					});
				} else {
					frappe.msgprint({
						title: __('Connection Failed'),
						indicator: 'red',
						message: r.message.errors.join('<br>')
					});
				}
			}
		}
	});
}

function disconnect_oauth(frm) {
	frappe.confirm(
		__('Are you sure you want to disconnect OAuth? You will need to reconnect to use this account.'),
		function() {
			frappe.call({
				method: 'frappe_webmail.api.disconnect_oauth',
				args: {
					account_name: frm.doc.name
				},
				callback: function(r) {
					if (r.message && r.message.success) {
						frappe.msgprint(__('OAuth disconnected successfully.'));
						frm.reload_doc();
					}
				}
			});
		}
	);
}
