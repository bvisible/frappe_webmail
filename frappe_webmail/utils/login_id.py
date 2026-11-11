# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""What the mail servers sign a mailbox in as."""

from frappe.utils import cint


def login_id_of(account):
	"""What the servers sign a password mailbox in as: its login ID when it says it differs from its address (some servers
	want a username or an account number), else its address. The same one for IMAP and SMTP; the address stays the one
	mail is sent from. A mailbox made before the field existed has neither attribute, hence the defaults.

	OAuth2 mailboxes do not come here: the provider knows them by their address."""
	if cint(getattr(account, "login_id_is_different", 0)):
		login_id = (getattr(account, "login_id", None) or "").strip()
		if login_id:
			return login_id
	return account.email
