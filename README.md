# Frappe Webmail

A native webmail client for Frappe Framework with full IMAP/SMTP support, rich text composition, and secure email viewing.

## Features

- **Multi-Account Support**: Configure multiple email accounts (Gmail, Outlook, custom IMAP servers)
- **Secure Email Viewing**: HTML sanitization with DOMPurify, sandboxed iframes, blocked tracking pixels
- **Rich Text Composer**: TipTap-based editor with formatting, links, images, and attachments
- **Email Signatures**: Create and manage multiple HTML signatures per user
- **Virtual Scrolling**: Smooth performance with thousands of emails
- **Folder Navigation**: Full IMAP folder tree with special folder detection
- **Email Actions**: Reply, forward, star, delete, move between folders

## Installation

### Prerequisites

- Frappe Framework v14 or v15
- Node.js 18+
- Python 3.10+

### Install the App

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/your-org/frappe_webmail --branch main
bench --site your-site.local install-app frappe_webmail
```

### Install Python Dependencies

```bash
cd apps/frappe_webmail
pip install -r requirements.txt
```

### Build Frontend

```bash
cd apps/frappe_webmail/frontend
npm install
npm run build
```

### Migrate Database

```bash
bench --site your-site.local migrate
```

## Configuration

### Adding an Email Account

1. Go to **Webmail Account** in Frappe Desk
2. Click **New**
3. Enter your email settings:
   - **Email Address**: your@email.com
   - **IMAP Host**: imap.example.com (Port 993 for SSL)
   - **SMTP Host**: smtp.example.com (Port 587 for STARTTLS)
   - **Passwords**: Your email account password or app-specific password

### Gmail Configuration

For Gmail accounts:
- Enable "Less secure app access" or use an App Password
- IMAP Host: `imap.gmail.com`, Port: `993`, SSL: Yes
- SMTP Host: `smtp.gmail.com`, Port: `587`, STARTTLS: Yes

### Outlook/Office 365 Configuration

- IMAP Host: `outlook.office365.com`, Port: `993`, SSL: Yes
- SMTP Host: `smtp.office365.com`, Port: `587`, STARTTLS: Yes

## Usage

Access the webmail interface at `/app/webmail` in Frappe Desk.

### Keyboard Shortcuts (Coming Soon)

- `c` - Compose new email
- `r` - Reply to selected email
- `f` - Forward selected email
- `j/k` - Navigate up/down in email list
- `e` - Archive email
- `#` - Delete email

## Security

- HTML emails are sanitized using DOMPurify (client) and bleach (server)
- Emails are displayed in sandboxed iframes
- External images are blocked by default to prevent tracking
- IMAP/SMTP passwords are stored encrypted using Frappe's Password field type

## Development

### Frontend Development

```bash
cd apps/frappe_webmail/frontend
npm install
npm run dev  # Development server with hot reload
```

### Running Tests

```bash
cd apps/frappe_webmail
bench --site test-site run-tests --app frappe_webmail
```

### Code Formatting

This app uses `pre-commit` for code formatting:

```bash
cd apps/frappe_webmail
pre-commit install
```

Tools used:
- **Python**: ruff, pyupgrade
- **JavaScript**: eslint, prettier

## Project Structure

```
frappe_webmail/
├── frappe_webmail/
│   ├── api.py                          # IMAP/SMTP API endpoints
│   ├── hooks.py                        # Frappe hooks configuration
│   ├── utils/
│   │   ├── imap_client.py              # IMAP wrapper class
│   │   └── email_parser.py             # Email parsing utilities
│   ├── frappe_webmail/
│   │   ├── doctype/
│   │   │   ├── webmail_account/        # Email account DocType
│   │   │   └── email_signature/        # Signature DocType
│   │   └── page/
│   │       └── webmail/                # Desk page
│   └── public/
│       ├── js/
│       └── css/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   └── Webmail.vue             # Main application
│   │   └── components/
│   │       ├── EmailList.vue           # Virtual scrolling list
│   │       ├── EmailViewer.vue         # Secure email display
│   │       ├── EmailComposer.vue       # Rich text editor
│   │       ├── FolderTree.vue          # Folder navigation
│   │       └── SignatureEditor.vue     # Signature management
│   ├── package.json
│   └── vite.config.js
├── requirements.txt
└── pyproject.toml
```

## API Reference

### Python API

```python
# Get user's email accounts
frappe.call('frappe_webmail.api.get_accounts')

# List folders
frappe.call('frappe_webmail.api.get_folders', account_name='...')

# Get emails with pagination
frappe.call('frappe_webmail.api.get_emails',
    account_name='...',
    folder='INBOX',
    limit=50,
    offset=0,
    search='query'
)

# Get full email content
frappe.call('frappe_webmail.api.get_email_content',
    account_name='...',
    uid=123,
    folder='INBOX'
)

# Send email
frappe.call('frappe_webmail.api.send_email',
    account_name='...',
    to='recipient@example.com',
    subject='Hello',
    html_content='<p>Message body</p>'
)
```

## Roadmap

- [ ] Draft auto-save
- [ ] Email filters/rules
- [ ] IMAP IDLE for real-time updates
- [ ] Contact management
- [ ] CalDAV calendar integration
- [ ] OAuth2 authentication for Gmail/Outlook
- [ ] Email search with full-text indexing
- [ ] Mobile responsive improvements

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests.

## License

MIT License - see [license.txt](license.txt)

## Support

- [GitHub Issues](https://github.com/your-org/frappe_webmail/issues)
- [Frappe Forum](https://discuss.frappe.io)
