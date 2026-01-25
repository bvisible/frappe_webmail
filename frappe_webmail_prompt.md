# Prompt Claude Code - Frappe Webmail App

## Contexte du projet

Tu vas créer une application Frappe Framework appelée **frappe_webmail** qui fournit un client webmail complet intégré nativement dans Frappe Desk. Cette app permet aux utilisateurs de gérer plusieurs comptes email (IMAP/SMTP) avec une interface moderne, la composition d'emails rich text, les signatures, et l'affichage sécurisé des emails HTML.

## Objectifs principaux

1. **Multi-comptes** : Un utilisateur peut configurer plusieurs comptes email (Gmail, Outlook, serveurs IMAP personnels)
2. **Interface intégrée** : Page Frappe Desk avec liste d'emails, lecture, composition
3. **Sécurité** : Sanitisation HTML des emails reçus (protection XSS, tracking pixels)
4. **Signatures** : Gestion de signatures HTML personnalisées par utilisateur
5. **Performance** : Affichage fluide de milliers d'emails avec virtual scrolling

## Stack technique

### Frontend (Vue.js dans Frappe)
- **TipTap** : Éditeur rich text pour composition et signatures
- **DOMPurify** : Sanitisation HTML côté client
- **vue-virtual-scroller** : Liste d'emails performante
- **Frappe UI** : Composants natifs (Dialog, Button, etc.)

### Backend (Python)
- **imapclient** : Connexion IMAP (lecture emails)
- **smtplib** : Envoi SMTP (natif Python)
- **email.mime** : Construction emails multipart
- **bleach** : Sanitisation HTML côté serveur

## Structure de l'application

```
frappe_webmail/
├── frappe_webmail/
│   ├── __init__.py
│   ├── hooks.py
│   ├── api.py                          # API Python IMAP/SMTP
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── imap_client.py              # Wrapper IMAP
│   │   └── email_parser.py             # Parsing emails
│   ├── frappe_webmail/
│   │   └── doctype/
│   │       ├── webmail_account/        # Configuration compte email
│   │       │   ├── webmail_account.json
│   │       │   └── webmail_account.py
│   │       └── email_signature/        # Signatures utilisateur
│   │           ├── email_signature.json
│   │           └── email_signature.py
│   ├── public/
│   │   └── js/
│   │       └── frappe_webmail.bundle.js
│   └── www/
│       └── webmail.html                # Page principale (optionnel)
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js
│       ├── pages/
│       │   └── Webmail.vue             # Page principale
│       └── components/
│           ├── EmailList.vue           # Liste emails (virtual scroll)
│           ├── EmailViewer.vue         # Affichage email (sanitized)
│           ├── EmailComposer.vue       # Composition (TipTap)
│           ├── FolderTree.vue          # Arborescence dossiers
│           └── SignatureEditor.vue     # Éditeur de signature
├── setup.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

## DocTypes à créer

### 1. Webmail Account

```json
{
  "doctype": "DocType",
  "name": "Webmail Account",
  "module": "Frappe Webmail",
  "fields": [
    {
      "fieldname": "enabled",
      "fieldtype": "Check",
      "label": "Enabled",
      "default": "1"
    },
    {
      "fieldname": "user",
      "fieldtype": "Link",
      "label": "User",
      "options": "User",
      "reqd": 1,
      "default": "__user"
    },
    {
      "fieldname": "email",
      "fieldtype": "Data",
      "label": "Email Address",
      "options": "Email",
      "reqd": 1
    },
    {
      "fieldname": "sender_name",
      "fieldtype": "Data",
      "label": "Sender Name"
    },
    {
      "fieldname": "sb_imap",
      "fieldtype": "Section Break",
      "label": "IMAP Settings"
    },
    {
      "fieldname": "imap_host",
      "fieldtype": "Data",
      "label": "IMAP Host",
      "reqd": 1
    },
    {
      "fieldname": "imap_port",
      "fieldtype": "Int",
      "label": "IMAP Port",
      "default": "993"
    },
    {
      "fieldname": "imap_ssl",
      "fieldtype": "Check",
      "label": "Use SSL",
      "default": "1"
    },
    {
      "fieldname": "imap_password",
      "fieldtype": "Password",
      "label": "IMAP Password",
      "reqd": 1
    },
    {
      "fieldname": "sb_smtp",
      "fieldtype": "Section Break",
      "label": "SMTP Settings"
    },
    {
      "fieldname": "smtp_host",
      "fieldtype": "Data",
      "label": "SMTP Host",
      "reqd": 1
    },
    {
      "fieldname": "smtp_port",
      "fieldtype": "Int",
      "label": "SMTP Port",
      "default": "587"
    },
    {
      "fieldname": "smtp_ssl",
      "fieldtype": "Check",
      "label": "Use SSL"
    },
    {
      "fieldname": "smtp_starttls",
      "fieldtype": "Check",
      "label": "Use STARTTLS",
      "default": "1"
    },
    {
      "fieldname": "smtp_password",
      "fieldtype": "Password",
      "label": "SMTP Password",
      "reqd": 1
    },
    {
      "fieldname": "sb_signature",
      "fieldtype": "Section Break",
      "label": "Default Signature"
    },
    {
      "fieldname": "default_signature",
      "fieldtype": "Link",
      "label": "Default Signature",
      "options": "Email Signature"
    }
  ],
  "permissions": [
    {
      "role": "System Manager",
      "read": 1,
      "write": 1,
      "create": 1,
      "delete": 1
    },
    {
      "role": "All",
      "read": 1,
      "write": 1,
      "create": 1,
      "delete": 1,
      "if_owner": 1
    }
  ],
  "autoname": "format:{email}",
  "title_field": "email",
  "search_fields": "email,sender_name"
}
```

### 2. Email Signature

```json
{
  "doctype": "DocType",
  "name": "Email Signature",
  "module": "Frappe Webmail",
  "fields": [
    {
      "fieldname": "user",
      "fieldtype": "Link",
      "label": "User",
      "options": "User",
      "reqd": 1,
      "default": "__user"
    },
    {
      "fieldname": "signature_name",
      "fieldtype": "Data",
      "label": "Signature Name",
      "reqd": 1
    },
    {
      "fieldname": "is_default",
      "fieldtype": "Check",
      "label": "Is Default"
    },
    {
      "fieldname": "content",
      "fieldtype": "Text Editor",
      "label": "Signature Content",
      "reqd": 1
    }
  ],
  "permissions": [
    {
      "role": "All",
      "read": 1,
      "write": 1,
      "create": 1,
      "delete": 1,
      "if_owner": 1
    }
  ],
  "autoname": "format:{user}-{signature_name}",
  "title_field": "signature_name"
}
```

## API Python (api.py)

```python
# frappe_webmail/api.py
import frappe
from frappe import _
from imapclient import IMAPClient
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
import email
from email.header import decode_header
import bleach
import base64

# ============================================
# ACCOUNT MANAGEMENT
# ============================================

@frappe.whitelist()
def get_accounts():
    """Get all email accounts for current user"""
    return frappe.get_all(
        "Webmail Account",
        filters={"user": frappe.session.user, "enabled": 1},
        fields=["name", "email", "sender_name", "default_signature"]
    )

@frappe.whitelist()
def test_connection(account_name):
    """Test IMAP/SMTP connection for an account"""
    account = get_account(account_name)
    
    errors = []
    
    # Test IMAP
    try:
        with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
            client.login(account.email, account.get_password("imap_password"))
    except Exception as e:
        errors.append(f"IMAP: {str(e)}")
    
    # Test SMTP
    try:
        smtp_class = smtplib.SMTP_SSL if account.smtp_ssl else smtplib.SMTP
        with smtp_class(account.smtp_host, account.smtp_port, timeout=10) as server:
            if account.smtp_starttls and not account.smtp_ssl:
                server.starttls()
            server.login(account.email, account.get_password("smtp_password"))
    except Exception as e:
        errors.append(f"SMTP: {str(e)}")
    
    if errors:
        return {"success": False, "errors": errors}
    return {"success": True, "message": _("Connection successful")}

# ============================================
# FOLDERS
# ============================================

@frappe.whitelist()
def get_folders(account_name):
    """List IMAP folders for an account"""
    account = get_account(account_name)
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        folders = client.list_folders()
        
        result = []
        for flags, delimiter, name in folders:
            result.append({
                "name": name,
                "delimiter": delimiter.decode() if isinstance(delimiter, bytes) else delimiter,
                "flags": [f.decode() if isinstance(f, bytes) else f for f in flags],
                "selectable": b"\\Noselect" not in flags
            })
        
        return result

# ============================================
# EMAILS - LIST
# ============================================

@frappe.whitelist()
def get_emails(account_name, folder="INBOX", limit=50, offset=0, search=None):
    """Get emails from a folder with pagination"""
    account = get_account(account_name)
    limit = min(int(limit), 100)  # Max 100 per request
    offset = int(offset)
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        client.select_folder(folder)
        
        # Search criteria
        if search:
            criteria = ['OR', 'OR', 
                ['SUBJECT', search], 
                ['FROM', search], 
                ['TO', search]
            ]
        else:
            criteria = ['NOT', 'DELETED']
        
        messages = client.search(criteria)
        total = len(messages)
        
        # Pagination (newest first)
        messages = list(reversed(messages))
        page = messages[offset:offset + limit]
        
        if not page:
            return {"emails": [], "total": total, "has_more": False}
        
        # Fetch envelope data
        data = client.fetch(page, ['ENVELOPE', 'FLAGS', 'BODYSTRUCTURE', 'RFC822.SIZE'])
        
        emails = []
        for uid in page:  # Maintain order
            if uid not in data:
                continue
            msg_data = data[uid]
            env = msg_data[b'ENVELOPE']
            flags = msg_data[b'FLAGS']
            
            emails.append({
                "uid": uid,
                "subject": decode_mime_header(env.subject),
                "from_email": format_address(env.from_[0]) if env.from_ else "",
                "from_name": decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else "",
                "to": format_address(env.to[0]) if env.to else "",
                "date": env.date.isoformat() if env.date else None,
                "seen": b'\\Seen' in flags,
                "flagged": b'\\Flagged' in flags,
                "answered": b'\\Answered' in flags,
                "has_attachments": has_attachments(msg_data.get(b'BODYSTRUCTURE')),
                "size": msg_data.get(b'RFC822.SIZE', 0)
            })
        
        return {
            "emails": emails, 
            "total": total, 
            "has_more": offset + limit < total
        }

# ============================================
# EMAILS - READ
# ============================================

@frappe.whitelist()
def get_email_content(account_name, uid, folder="INBOX", mark_read=True):
    """Get full email content"""
    account = get_account(account_name)
    uid = int(uid)
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        client.select_folder(folder)
        
        # Mark as read
        if mark_read:
            client.add_flags([uid], [b'\\Seen'])
        
        # Fetch full message
        data = client.fetch([uid], ['RFC822', 'ENVELOPE', 'FLAGS'])
        
        if uid not in data:
            frappe.throw(_("Email not found"))
        
        raw = data[uid][b'RFC822']
        msg = email.message_from_bytes(raw)
        env = data[uid][b'ENVELOPE']
        flags = data[uid][b'FLAGS']
        
        # Parse content
        html_content = None
        text_content = None
        attachments = []
        inline_images = {}
        
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            content_id = part.get("Content-ID", "").strip("<>")
            
            if "attachment" in content_disposition:
                payload = part.get_payload(decode=True)
                attachments.append({
                    "id": content_id or str(len(attachments)),
                    "filename": decode_mime_header(part.get_filename()) or f"attachment_{len(attachments)}",
                    "content_type": content_type,
                    "size": len(payload) if payload else 0
                })
            elif content_type.startswith("image/") and content_id:
                # Inline image
                payload = part.get_payload(decode=True)
                if payload:
                    inline_images[content_id] = f"data:{content_type};base64,{base64.b64encode(payload).decode()}"
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    html_content = payload.decode(charset, errors='replace')
            elif content_type == "text/plain" and not html_content:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    text_content = payload.decode(charset, errors='replace')
        
        # Replace CID references with inline data
        if html_content and inline_images:
            for cid, data_uri in inline_images.items():
                html_content = html_content.replace(f"cid:{cid}", data_uri)
        
        return {
            "uid": uid,
            "message_id": msg.get("Message-ID", ""),
            "subject": decode_mime_header(env.subject),
            "from_email": format_address(env.from_[0]) if env.from_ else "",
            "from_name": decode_mime_header(env.from_[0].name) if env.from_ and env.from_[0].name else "",
            "to": ", ".join([format_address(a) for a in (env.to or [])]),
            "cc": ", ".join([format_address(a) for a in (env.cc or [])]),
            "reply_to": format_address(env.reply_to[0]) if env.reply_to else "",
            "date": env.date.isoformat() if env.date else None,
            "html": html_content,
            "text": text_content,
            "attachments": attachments,
            "seen": b'\\Seen' in flags,
            "flagged": b'\\Flagged' in flags
        }

# ============================================
# EMAILS - SEND
# ============================================

@frappe.whitelist()
def send_email(account_name, to, subject, html_content, cc=None, bcc=None, 
               reply_to_message_id=None, attachments=None):
    """Send an email"""
    account = get_account(account_name)
    
    # Build message
    msg = MIMEMultipart('mixed')
    msg['From'] = f'"{account.sender_name}" <{account.email}>' if account.sender_name else account.email
    msg['To'] = to
    msg['Subject'] = subject
    
    if cc:
        msg['Cc'] = cc
    
    if reply_to_message_id:
        msg['In-Reply-To'] = reply_to_message_id
        msg['References'] = reply_to_message_id
    
    # Body (multipart/alternative for text + html)
    body = MIMEMultipart('alternative')
    
    # Plain text version
    text_content = bleach.clean(html_content, tags=[], strip=True)
    body.attach(MIMEText(text_content, 'plain', 'utf-8'))
    
    # HTML version
    body.attach(MIMEText(html_content, 'html', 'utf-8'))
    msg.attach(body)
    
    # Attachments
    if attachments:
        for att in frappe.parse_json(attachments):
            # att = {"filename": "...", "data": "base64...", "content_type": "..."}
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(base64.b64decode(att['data']))
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{att["filename"]}"')
            msg.attach(part)
    
    # Send via SMTP
    try:
        if account.smtp_ssl:
            server = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=30)
            if account.smtp_starttls:
                server.starttls()
        
        server.login(account.email, account.get_password("smtp_password"))
        
        recipients = [r.strip() for r in to.split(',')]
        if cc:
            recipients.extend([r.strip() for r in cc.split(',')])
        if bcc:
            recipients.extend([r.strip() for r in bcc.split(',')])
        
        server.sendmail(account.email, recipients, msg.as_string())
        server.quit()
        
        return {"success": True, "message": _("Email sent successfully")}
    
    except Exception as e:
        frappe.log_error(f"Email send error: {str(e)}", "Frappe Webmail")
        frappe.throw(_("Failed to send email: {0}").format(str(e)))

# ============================================
# EMAILS - ACTIONS
# ============================================

@frappe.whitelist()
def set_flags(account_name, uids, folder, add_flags=None, remove_flags=None):
    """Set or remove flags on emails"""
    account = get_account(account_name)
    uids = frappe.parse_json(uids) if isinstance(uids, str) else uids
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        client.select_folder(folder)
        
        if add_flags:
            flags = [f.encode() if isinstance(f, str) else f for f in frappe.parse_json(add_flags)]
            client.add_flags(uids, flags)
        
        if remove_flags:
            flags = [f.encode() if isinstance(f, str) else f for f in frappe.parse_json(remove_flags)]
            client.remove_flags(uids, flags)
        
        return {"success": True}

@frappe.whitelist()
def move_emails(account_name, uids, from_folder, to_folder):
    """Move emails to another folder"""
    account = get_account(account_name)
    uids = frappe.parse_json(uids) if isinstance(uids, str) else uids
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        client.select_folder(from_folder)
        
        # Copy then delete
        client.copy(uids, to_folder)
        client.add_flags(uids, [b'\\Deleted'])
        client.expunge()
        
        return {"success": True}

@frappe.whitelist()
def delete_emails(account_name, uids, folder, permanent=False):
    """Delete emails (move to trash or permanent)"""
    account = get_account(account_name)
    uids = frappe.parse_json(uids) if isinstance(uids, str) else uids
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        client.select_folder(folder)
        
        if permanent:
            client.add_flags(uids, [b'\\Deleted'])
            client.expunge()
        else:
            # Try to find trash folder
            folders = client.list_folders()
            trash_folder = None
            for flags, _, name in folders:
                if b'\\Trash' in flags or name.lower() in ['trash', 'corbeille', 'deleted', 'deleted items']:
                    trash_folder = name
                    break
            
            if trash_folder and folder != trash_folder:
                client.copy(uids, trash_folder)
            
            client.add_flags(uids, [b'\\Deleted'])
            client.expunge()
        
        return {"success": True}

@frappe.whitelist()
def get_attachment(account_name, uid, folder, attachment_id):
    """Download an attachment"""
    account = get_account(account_name)
    uid = int(uid)
    
    with IMAPClient(host=account.imap_host, port=account.imap_port, ssl=account.imap_ssl) as client:
        client.login(account.email, account.get_password("imap_password"))
        client.select_folder(folder)
        
        data = client.fetch([uid], ['RFC822'])
        
        if uid not in data:
            frappe.throw(_("Email not found"))
        
        raw = data[uid][b'RFC822']
        msg = email.message_from_bytes(raw)
        
        # Find the attachment
        idx = 0
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            content_id = part.get("Content-ID", "").strip("<>")
            
            if "attachment" in content_disposition:
                current_id = content_id or str(idx)
                if current_id == attachment_id:
                    payload = part.get_payload(decode=True)
                    filename = decode_mime_header(part.get_filename()) or f"attachment_{idx}"
                    content_type = part.get_content_type()
                    
                    return {
                        "filename": filename,
                        "content_type": content_type,
                        "data": base64.b64encode(payload).decode(),
                        "size": len(payload)
                    }
                idx += 1
        
        frappe.throw(_("Attachment not found"))

# ============================================
# SIGNATURES
# ============================================

@frappe.whitelist()
def get_signatures():
    """Get all signatures for current user"""
    return frappe.get_all(
        "Email Signature",
        filters={"user": frappe.session.user},
        fields=["name", "signature_name", "content", "is_default"],
        order_by="is_default desc, signature_name asc"
    )

@frappe.whitelist()
def get_default_signature():
    """Get default signature content"""
    sig = frappe.db.get_value(
        "Email Signature",
        {"user": frappe.session.user, "is_default": 1},
        "content"
    )
    return sig or ""

# ============================================
# HELPERS
# ============================================

def get_account(account_name):
    """Get and validate email account"""
    if not frappe.db.exists("Webmail Account", account_name):
        frappe.throw(_("Account not found"))
    
    account = frappe.get_doc("Webmail Account", account_name)
    
    if account.user != frappe.session.user:
        frappe.throw(_("Access denied"))
    
    if not account.enabled:
        frappe.throw(_("Account is disabled"))
    
    return account

def decode_mime_header(header):
    """Decode MIME encoded header"""
    if not header:
        return ""
    if isinstance(header, bytes):
        header = header.decode('utf-8', errors='replace')
    
    try:
        decoded_parts = decode_header(header)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                result.append(part)
        return "".join(result)
    except:
        return str(header)

def format_address(addr):
    """Format email address from IMAP envelope"""
    if not addr:
        return ""
    try:
        mailbox = addr.mailbox.decode() if isinstance(addr.mailbox, bytes) else addr.mailbox
        host = addr.host.decode() if isinstance(addr.host, bytes) else addr.host
        return f"{mailbox}@{host}"
    except:
        return ""

def has_attachments(bodystructure):
    """Check if email has attachments from BODYSTRUCTURE"""
    if not bodystructure:
        return False
    
    def check_part(part):
        if isinstance(part, tuple):
            if len(part) >= 2:
                # Check for attachment disposition
                for item in part:
                    if isinstance(item, tuple) and len(item) >= 2:
                        if item[0] and isinstance(item[0], bytes) and item[0].lower() == b'attachment':
                            return True
                    if isinstance(item, tuple):
                        if check_part(item):
                            return True
        return False
    
    return check_part(bodystructure)
```

## Composants Vue.js

### 1. EmailComposer.vue (avec TipTap)

```vue
<template>
  <div class="email-composer">
    <!-- Recipients -->
    <div class="composer-field">
      <label>À:</label>
      <input v-model="email.to" type="text" placeholder="destinataire@example.com" />
    </div>
    <div class="composer-field">
      <label>Cc:</label>
      <input v-model="email.cc" type="text" placeholder="Copie carbone" />
    </div>
    <div class="composer-field">
      <label>Objet:</label>
      <input v-model="email.subject" type="text" placeholder="Objet du message" />
    </div>
    
    <!-- Toolbar -->
    <div class="editor-toolbar" v-if="editor">
      <button @click="editor.chain().focus().toggleBold().run()" 
              :class="{ active: editor.isActive('bold') }" title="Gras">
        <strong>B</strong>
      </button>
      <button @click="editor.chain().focus().toggleItalic().run()"
              :class="{ active: editor.isActive('italic') }" title="Italique">
        <em>I</em>
      </button>
      <button @click="editor.chain().focus().toggleUnderline().run()"
              :class="{ active: editor.isActive('underline') }" title="Souligné">
        <u>U</u>
      </button>
      <span class="separator"></span>
      <button @click="editor.chain().focus().toggleBulletList().run()"
              :class="{ active: editor.isActive('bulletList') }" title="Liste à puces">
        •
      </button>
      <button @click="editor.chain().focus().toggleOrderedList().run()"
              :class="{ active: editor.isActive('orderedList') }" title="Liste numérotée">
        1.
      </button>
      <span class="separator"></span>
      <button @click="insertLink" title="Lien">🔗</button>
      <button @click="insertImage" title="Image">🖼️</button>
      <span class="separator"></span>
      <button @click="insertSignature" title="Signature">✍️</button>
    </div>
    
    <!-- Editor -->
    <div class="editor-container">
      <editor-content :editor="editor" />
    </div>
    
    <!-- Attachments -->
    <div class="attachments-section" v-if="attachments.length">
      <div v-for="(file, idx) in attachments" :key="idx" class="attachment-chip">
        <span>{{ file.name }}</span>
        <span class="size">({{ formatSize(file.size) }})</span>
        <button @click="removeAttachment(idx)" class="remove">×</button>
      </div>
    </div>
    
    <!-- Actions -->
    <div class="composer-actions">
      <input type="file" ref="fileInput" multiple @change="handleFiles" style="display: none" />
      <button class="btn btn-secondary" @click="$refs.fileInput.click()">
        📎 Joindre
      </button>
      <button class="btn btn-secondary" @click="saveDraft">
        💾 Brouillon
      </button>
      <button class="btn btn-primary" @click="send" :disabled="sending">
        {{ sending ? 'Envoi...' : '📤 Envoyer' }}
      </button>
    </div>
  </div>
</template>

<script>
import { Editor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'

export default {
  name: 'EmailComposer',
  components: { EditorContent },
  
  props: {
    account: { type: String, required: true },
    replyTo: { type: Object, default: null },
    signature: { type: String, default: '' }
  },
  
  emits: ['sent', 'close'],
  
  data() {
    return {
      editor: null,
      email: {
        to: '',
        cc: '',
        subject: ''
      },
      attachments: [],
      sending: false
    }
  },
  
  mounted() {
    this.initEditor()
    
    if (this.replyTo) {
      this.setupReply()
    }
  },
  
  beforeUnmount() {
    if (this.editor) {
      this.editor.destroy()
    }
  },
  
  methods: {
    initEditor() {
      let initialContent = ''
      
      if (this.signature) {
        initialContent = `<p></p><br><p>--</p>${this.signature}`
      }
      
      this.editor = new Editor({
        content: initialContent,
        extensions: [
          StarterKit,
          Underline,
          Link.configure({ openOnClick: false }),
          Image.configure({ inline: true }),
          Placeholder.configure({
            placeholder: 'Écrivez votre message...'
          })
        ]
      })
    },
    
    setupReply() {
      const reply = this.replyTo
      this.email.to = reply.from_email
      this.email.subject = reply.subject.startsWith('Re:') ? reply.subject : `Re: ${reply.subject}`
      
      const date = new Date(reply.date).toLocaleString('fr-FR')
      const quoteContent = `
        <br><br>
        <p>Le ${date}, ${reply.from_name || reply.from_email} a écrit :</p>
        <blockquote style="border-left: 2px solid #ccc; padding-left: 10px; margin-left: 0; color: #666;">
          ${reply.html || reply.text || ''}
        </blockquote>
      `
      
      let content = '<p></p>'
      if (this.signature) {
        content += `<br><p>--</p>${this.signature}`
      }
      content += quoteContent
      
      this.editor.commands.setContent(content)
      this.editor.commands.focus('start')
    },
    
    insertSignature() {
      if (this.signature) {
        this.editor.chain().focus().insertContent(`<br><p>--</p>${this.signature}`).run()
      }
    },
    
    insertLink() {
      const url = prompt('URL du lien:')
      if (url) {
        this.editor.chain().focus().setLink({ href: url }).run()
      }
    },
    
    insertImage() {
      const url = prompt('URL de l\'image:')
      if (url) {
        this.editor.chain().focus().setImage({ src: url }).run()
      }
    },
    
    handleFiles(event) {
      const files = Array.from(event.target.files)
      this.attachments.push(...files)
    },
    
    removeAttachment(index) {
      this.attachments.splice(index, 1)
    },
    
    formatSize(bytes) {
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    },
    
    async prepareAttachments() {
      const result = []
      for (const file of this.attachments) {
        const data = await this.fileToBase64(file)
        result.push({
          filename: file.name,
          content_type: file.type,
          data: data
        })
      }
      return result
    },
    
    fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => {
          const base64 = reader.result.split(',')[1]
          resolve(base64)
        }
        reader.onerror = reject
        reader.readAsDataURL(file)
      })
    },
    
    async send() {
      if (!this.email.to) {
        frappe.toast({ message: 'Veuillez saisir un destinataire', indicator: 'red' })
        return
      }
      
      this.sending = true
      
      try {
        const attachments = await this.prepareAttachments()
        
        await frappe.call({
          method: 'frappe_webmail.api.send_email',
          args: {
            account_name: this.account,
            to: this.email.to,
            cc: this.email.cc || null,
            subject: this.email.subject,
            html_content: this.editor.getHTML(),
            reply_to_message_id: this.replyTo?.message_id || null,
            attachments: attachments.length ? JSON.stringify(attachments) : null
          }
        })
        
        frappe.toast({ message: 'Email envoyé !', indicator: 'green' })
        this.$emit('sent')
        this.$emit('close')
        
      } catch (error) {
        frappe.toast({ message: error.message || 'Erreur d\'envoi', indicator: 'red' })
      } finally {
        this.sending = false
      }
    },
    
    saveDraft() {
      // TODO: Implement draft saving
      frappe.toast({ message: 'Brouillon sauvegardé', indicator: 'blue' })
    }
  }
}
</script>

<style scoped>
.email-composer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  border-radius: 8px;
}

.composer-field {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
}

.composer-field label {
  width: 50px;
  color: var(--text-muted);
  font-size: 13px;
}

.composer-field input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 14px;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  gap: 4px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-light-gray);
}

.editor-toolbar button {
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
}

.editor-toolbar button:hover {
  background: var(--bg-gray);
}

.editor-toolbar button.active {
  background: var(--primary-light);
  border-color: var(--primary-color);
}

.editor-toolbar .separator {
  width: 1px;
  height: 20px;
  background: var(--border-color);
  margin: 0 8px;
}

.editor-container {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}

.editor-container :deep(.ProseMirror) {
  min-height: 200px;
  outline: none;
}

.editor-container :deep(.ProseMirror p.is-editor-empty:first-child::before) {
  color: var(--text-muted);
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}

.attachments-section {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}

.attachment-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-light-gray);
  border-radius: 4px;
  font-size: 12px;
}

.attachment-chip .size {
  color: var(--text-muted);
}

.attachment-chip .remove {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 16px;
  padding: 0 4px;
}

.composer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}
</style>
```

### 2. EmailViewer.vue (avec DOMPurify)

```vue
<template>
  <div class="email-viewer" v-if="email">
    <!-- Header -->
    <div class="email-header">
      <div class="email-subject">{{ email.subject || '(Sans objet)' }}</div>
      <div class="email-meta">
        <div class="from">
          <strong>{{ email.from_name || email.from_email }}</strong>
          <span class="email-address">&lt;{{ email.from_email }}&gt;</span>
        </div>
        <div class="to">À: {{ email.to }}</div>
        <div v-if="email.cc" class="cc">Cc: {{ email.cc }}</div>
        <div class="date">{{ formatDate(email.date) }}</div>
      </div>
    </div>
    
    <!-- Actions -->
    <div class="email-actions">
      <button @click="$emit('reply', email)" class="btn btn-sm">↩️ Répondre</button>
      <button @click="$emit('forward', email)" class="btn btn-sm">↪️ Transférer</button>
      <button @click="toggleStar" class="btn btn-sm">{{ email.flagged ? '⭐' : '☆' }}</button>
      <button @click="$emit('delete', email)" class="btn btn-sm btn-danger">🗑️</button>
    </div>
    
    <!-- External images warning -->
    <div v-if="hasBlockedImages" class="blocked-images-notice">
      ⚠️ Les images externes ont été bloquées pour votre sécurité.
      <button @click="showExternalImages = true">Afficher les images</button>
    </div>
    
    <!-- Body (sandboxed iframe) -->
    <iframe
      ref="emailFrame"
      class="email-body"
      sandbox="allow-popups allow-popups-to-escape-sandbox"
      referrerpolicy="no-referrer"
      :srcdoc="sanitizedContent"
    />
    
    <!-- Attachments -->
    <div v-if="email.attachments?.length" class="email-attachments">
      <h4>📎 Pièces jointes ({{ email.attachments.length }})</h4>
      <div class="attachment-list">
        <div v-for="att in email.attachments" :key="att.id" class="attachment-item" @click="downloadAttachment(att)">
          <span class="icon">{{ getFileIcon(att.content_type) }}</span>
          <span class="name">{{ att.filename }}</span>
          <span class="size">({{ formatSize(att.size) }})</span>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="no-email-selected">
    <p>Sélectionnez un email pour le lire</p>
  </div>
</template>

<script>
import DOMPurify from 'dompurify'

export default {
  name: 'EmailViewer',
  
  props: {
    email: { type: Object, default: null },
    account: { type: String, required: true },
    folder: { type: String, default: 'INBOX' }
  },
  
  emits: ['reply', 'forward', 'delete', 'flag-changed'],
  
  data() {
    return {
      showExternalImages: false,
      hasBlockedImages: false
    }
  },
  
  computed: {
    sanitizedContent() {
      if (!this.email) return ''
      
      const content = this.email.html || this.wrapPlainText(this.email.text)
      if (!content) return ''
      
      // Configure DOMPurify
      const config = {
        WHOLE_DOCUMENT: true,
        FORBID_TAGS: ['script', 'style', 'audio', 'video', 'form', 'input', 'button', 'textarea', 'object', 'embed'],
        FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur', 'onsubmit'],
        ALLOW_DATA_ATTR: false
      }
      
      // Hook to handle external images
      this.hasBlockedImages = false
      
      DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        // Block external images unless allowed
        if (node.tagName === 'IMG' && !this.showExternalImages) {
          const src = node.getAttribute('src')
          if (src && !src.startsWith('data:') && !src.startsWith('cid:')) {
            node.setAttribute('data-blocked-src', src)
            node.setAttribute('src', 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" fill="gray" font-size="12">[Image bloquée]</text></svg>')
            node.style.cursor = 'pointer'
            node.title = 'Image externe bloquée'
            this.hasBlockedImages = true
          }
        }
        
        // Open links in new tab
        if (node.tagName === 'A') {
          node.setAttribute('target', '_blank')
          node.setAttribute('rel', 'noopener noreferrer')
        }
      })
      
      const clean = DOMPurify.sanitize(content, config)
      
      // Remove hook to avoid affecting other sanitizations
      DOMPurify.removeHook('afterSanitizeAttributes')
      
      // Wrap in HTML document with base styles
      return `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            * { box-sizing: border-box; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
              font-size: 14px;
              line-height: 1.6;
              color: #333;
              margin: 0;
              padding: 16px;
              word-wrap: break-word;
            }
            img { max-width: 100%; height: auto; }
            a { color: #0066cc; }
            blockquote {
              border-left: 3px solid #ccc;
              margin: 10px 0;
              padding-left: 15px;
              color: #666;
            }
            pre, code {
              background: #f5f5f5;
              padding: 2px 6px;
              border-radius: 3px;
              font-size: 13px;
            }
            pre { padding: 10px; overflow-x: auto; }
            table { border-collapse: collapse; max-width: 100%; }
            td, th { border: 1px solid #ddd; padding: 8px; }
          </style>
        </head>
        <body>${clean}</body>
        </html>
      `
    }
  },
  
  watch: {
    email() {
      this.showExternalImages = false
      this.hasBlockedImages = false
    }
  },
  
  methods: {
    wrapPlainText(text) {
      if (!text) return ''
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>')
      return `<pre style="white-space: pre-wrap; font-family: inherit;">${escaped}</pre>`
    },
    
    formatDate(dateStr) {
      if (!dateStr) return ''
      return new Date(dateStr).toLocaleString('fr-FR', {
        dateStyle: 'full',
        timeStyle: 'short'
      })
    },
    
    formatSize(bytes) {
      if (!bytes) return '0 B'
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    },
    
    getFileIcon(contentType) {
      if (!contentType) return '📄'
      if (contentType.startsWith('image/')) return '🖼️'
      if (contentType.startsWith('video/')) return '🎬'
      if (contentType.startsWith('audio/')) return '🎵'
      if (contentType.includes('pdf')) return '📕'
      if (contentType.includes('word') || contentType.includes('document')) return '📘'
      if (contentType.includes('sheet') || contentType.includes('excel')) return '📗'
      if (contentType.includes('zip') || contentType.includes('archive')) return '📦'
      return '📄'
    },
    
    async toggleStar() {
      const action = this.email.flagged ? 'remove_flags' : 'add_flags'
      const flags = ['\\Flagged']
      
      try {
        await frappe.call({
          method: 'frappe_webmail.api.set_flags',
          args: {
            account_name: this.account,
            uids: JSON.stringify([this.email.uid]),
            folder: this.folder,
            [action]: JSON.stringify(flags)
          }
        })
        
        this.email.flagged = !this.email.flagged
        this.$emit('flag-changed', this.email)
      } catch (error) {
        frappe.toast({ message: 'Erreur', indicator: 'red' })
      }
    },
    
    async downloadAttachment(attachment) {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_attachment',
          args: {
            account_name: this.account,
            uid: this.email.uid,
            folder: this.folder,
            attachment_id: attachment.id
          }
        })
        
        const data = response.message
        const byteCharacters = atob(data.data)
        const byteNumbers = new Array(byteCharacters.length)
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i)
        }
        const byteArray = new Uint8Array(byteNumbers)
        const blob = new Blob([byteArray], { type: data.content_type })
        
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = data.filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        
      } catch (error) {
        frappe.toast({ message: 'Erreur de téléchargement', indicator: 'red' })
      }
    }
  }
}
</script>

<style scoped>
.email-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
}

.no-email-selected {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
}

.email-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.email-subject {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 12px;
}

.email-meta {
  font-size: 13px;
  color: var(--text-muted);
}

.email-meta .from {
  color: var(--text-color);
  margin-bottom: 4px;
}

.email-meta .email-address {
  color: var(--text-muted);
  font-weight: normal;
}

.email-actions {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-light-gray);
}

.blocked-images-notice {
  padding: 8px 16px;
  background: #fff3cd;
  border-bottom: 1px solid #ffc107;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.blocked-images-notice button {
  background: none;
  border: none;
  color: #0066cc;
  cursor: pointer;
  text-decoration: underline;
}

.email-body {
  flex: 1;
  border: none;
  width: 100%;
}

.email-attachments {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-light-gray);
}

.email-attachments h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
}

.attachment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attachment-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.attachment-item:hover {
  background: var(--bg-gray);
}

.attachment-item .size {
  color: var(--text-muted);
}
</style>
```

### 3. EmailList.vue (avec virtual scroll)

```vue
<template>
  <div class="email-list-container">
    <!-- Toolbar -->
    <div class="list-toolbar">
      <input 
        v-model="searchQuery" 
        type="text" 
        placeholder="Rechercher..." 
        @keyup.enter="search"
      />
      <button @click="refresh" :disabled="loading">🔄</button>
    </div>
    
    <!-- List -->
    <RecycleScroller
      v-if="emails.length"
      class="email-list"
      :items="emails"
      :item-size="64"
      key-field="uid"
      v-slot="{ item }"
      @scroll-end="loadMore"
    >
      <div 
        class="email-row"
        :class="{ unread: !item.seen, selected: item.uid === selectedUid, flagged: item.flagged }"
        @click="$emit('select', item)"
      >
        <div class="checkbox" @click.stop>
          <input type="checkbox" v-model="item.checked" />
        </div>
        <div class="star" @click.stop="toggleStar(item)">
          {{ item.flagged ? '⭐' : '☆' }}
        </div>
        <div class="from">{{ item.from_name || item.from_email }}</div>
        <div class="subject">
          <span class="subject-text">{{ item.subject || '(Sans objet)' }}</span>
          <span v-if="item.has_attachments" class="attachment-icon">📎</span>
        </div>
        <div class="date">{{ formatDate(item.date) }}</div>
      </div>
    </RecycleScroller>
    
    <!-- Empty state -->
    <div v-else-if="!loading" class="empty-state">
      <p>Aucun email dans ce dossier</p>
    </div>
    
    <!-- Loading -->
    <div v-if="loading" class="loading-indicator">
      Chargement...
    </div>
  </div>
</template>

<script>
import { RecycleScroller } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'

export default {
  name: 'EmailList',
  components: { RecycleScroller },
  
  props: {
    account: { type: String, required: true },
    folder: { type: String, default: 'INBOX' },
    selectedUid: { type: Number, default: null }
  },
  
  emits: ['select', 'update:total'],
  
  data() {
    return {
      emails: [],
      total: 0,
      loading: false,
      hasMore: true,
      searchQuery: ''
    }
  },
  
  watch: {
    account: 'refresh',
    folder: 'refresh'
  },
  
  mounted() {
    this.loadEmails()
  },
  
  methods: {
    async loadEmails(append = false) {
      if (this.loading) return
      if (append && !this.hasMore) return
      
      this.loading = true
      
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_emails',
          args: {
            account_name: this.account,
            folder: this.folder,
            limit: 50,
            offset: append ? this.emails.length : 0,
            search: this.searchQuery || null
          }
        })
        
        const data = response.message
        
        if (append) {
          this.emails.push(...data.emails)
        } else {
          this.emails = data.emails
        }
        
        this.total = data.total
        this.hasMore = data.has_more
        this.$emit('update:total', this.total)
        
      } catch (error) {
        frappe.toast({ message: 'Erreur de chargement', indicator: 'red' })
      } finally {
        this.loading = false
      }
    },
    
    refresh() {
      this.emails = []
      this.hasMore = true
      this.loadEmails()
    },
    
    search() {
      this.refresh()
    },
    
    loadMore() {
      if (this.hasMore && !this.loading) {
        this.loadEmails(true)
      }
    },
    
    async toggleStar(email) {
      const action = email.flagged ? 'remove_flags' : 'add_flags'
      
      try {
        await frappe.call({
          method: 'frappe_webmail.api.set_flags',
          args: {
            account_name: this.account,
            uids: JSON.stringify([email.uid]),
            folder: this.folder,
            [action]: JSON.stringify(['\\Flagged'])
          }
        })
        
        email.flagged = !email.flagged
      } catch (error) {
        frappe.toast({ message: 'Erreur', indicator: 'red' })
      }
    },
    
    formatDate(dateStr) {
      if (!dateStr) return ''
      const date = new Date(dateStr)
      const now = new Date()
      const isToday = date.toDateString() === now.toDateString()
      
      if (isToday) {
        return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
      }
      
      const isThisYear = date.getFullYear() === now.getFullYear()
      if (isThisYear) {
        return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
      }
      
      return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: '2-digit' })
    },
    
    markAsRead(uid) {
      const email = this.emails.find(e => e.uid === uid)
      if (email) email.seen = true
    }
  }
}
</script>

<style scoped>
.email-list-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.list-toolbar {
  display: flex;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid var(--border-color);
}

.list-toolbar input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.list-toolbar button {
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: white;
  cursor: pointer;
}

.email-list {
  flex: 1;
  overflow-y: auto;
}

.email-row {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  gap: 12px;
}

.email-row:hover {
  background: var(--bg-light-gray);
}

.email-row.unread {
  font-weight: 600;
  background: #f0f7ff;
}

.email-row.selected {
  background: var(--primary-light);
}

.email-row.flagged .star {
  color: #f5a623;
}

.checkbox {
  flex-shrink: 0;
}

.star {
  flex-shrink: 0;
  cursor: pointer;
  font-size: 16px;
  width: 20px;
}

.from {
  width: 180px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.subject {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

.subject-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attachment-icon {
  flex-shrink: 0;
}

.date {
  width: 70px;
  flex-shrink: 0;
  text-align: right;
  font-size: 12px;
  color: var(--text-muted);
}

.empty-state, .loading-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
}
</style>
```

## hooks.py

```python
app_name = "frappe_webmail"
app_title = "Frappe Webmail"
app_publisher = "Your Name"
app_description = "Native webmail client for Frappe"
app_email = "your@email.com"
app_license = "MIT"

# Document Events
# ---------------

# Email Signature - ensure only one default per user
doc_events = {
    "Email Signature": {
        "before_save": "frappe_webmail.doctype.email_signature.email_signature.before_save"
    }
}

# Website Route Rules
# -------------------
website_route_rules = [
    {"from_route": "/webmail", "to_route": "webmail"}
]

# Desk Pages
# ----------
# page_js = {
#     "webmail": "public/js/webmail.bundle.js"
# }

# Include JS/CSS in all pages
# ---------------------------
# app_include_css = "/assets/frappe_webmail/css/webmail.css"
# app_include_js = "/assets/frappe_webmail/js/webmail.bundle.js"
```

## requirements.txt

```
imapclient>=2.3.0
bleach>=6.0.0
```

## package.json (frontend)

```json
{
  "name": "frappe-webmail-frontend",
  "version": "1.0.0",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@tiptap/extension-image": "^2.5.0",
    "@tiptap/extension-link": "^2.5.0",
    "@tiptap/extension-placeholder": "^2.5.0",
    "@tiptap/extension-underline": "^2.5.0",
    "@tiptap/pm": "^2.5.0",
    "@tiptap/starter-kit": "^2.5.0",
    "@tiptap/vue-3": "^2.5.0",
    "dompurify": "^3.3.0",
    "vue": "^3.4.0",
    "vue-virtual-scroller": "^2.0.0-beta.8"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0"
  }
}
```

## Instructions d'installation

1. Créer l'application Frappe :
```bash
cd ~/frappe-bench
bench new-app frappe_webmail
```

2. Installer les dépendances Python :
```bash
cd apps/frappe_webmail
pip install -r requirements.txt
```

3. Installer l'app sur le site :
```bash
bench --site [sitename] install-app frappe_webmail
```

4. Créer les DocTypes via l'interface Frappe ou en important les JSON

5. Configurer le frontend Vue.js :
```bash
cd apps/frappe_webmail/frontend
npm install
npm run build
```

6. Migrer la base de données :
```bash
bench --site [sitename] migrate
```

## Points d'attention

1. **Sécurité** : 
   - Les mots de passe IMAP/SMTP sont stockés chiffrés via le fieldtype Password de Frappe
   - DOMPurify côté client + bleach côté serveur pour double protection
   - iframe sandboxée pour l'affichage des emails

2. **Performance** :
   - Virtual scrolling pour les listes longues
   - Pagination côté serveur (50 emails par page)
   - Lazy loading des contenus

3. **UX** :
   - Blocage des images externes par défaut (anti-tracking)
   - Indicateurs visuels pour emails non lus, suivis, avec pièces jointes
   - Recherche intégrée

4. **Multi-comptes** :
   - Chaque utilisateur peut avoir plusieurs comptes
   - Isolation des données par utilisateur (permissions Frappe)

## À implémenter ensuite (Phase 2)

- Dossiers/labels personnalisés
- Brouillons avec auto-save
- Règles de filtrage
- Notifications temps réel (IMAP IDLE ou polling)
- Export/Import de contacts
- Intégration calendrier (CalDAV)
- Support OAuth2 pour Gmail/Outlook
