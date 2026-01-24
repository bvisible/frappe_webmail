# API Reference

Documentation complète de l'API Python de Frappe Webmail.

## Authentification

Toutes les méthodes API nécessitent une session Frappe authentifiée. Elles sont accessibles via `frappe.call()`.

## Méthodes

### get_accounts

Récupère tous les comptes email de l'utilisateur connecté.

```python
@frappe.whitelist()
def get_accounts() -> list
```

**Retour:**
```json
[
    {
        "name": "user@example.com",
        "email": "user@example.com",
        "sender_name": "John Doe",
        "default_signature": "signature-001"
    }
]
```

**Exemple JavaScript:**
```javascript
const accounts = await frappe.call({
    method: 'frappe_webmail.api.get_accounts'
});
console.log(accounts.message);
```

---

### test_connection

Teste la connexion IMAP et SMTP d'un compte.

```python
@frappe.whitelist()
def test_connection(account_name: str) -> dict
```

**Paramètres:**
| Nom | Type | Description |
|-----|------|-------------|
| account_name | str | Nom du compte (email) |

**Retour succès:**
```json
{
    "success": true,
    "message": "Connection successful"
}
```

**Retour erreur:**
```json
{
    "success": false,
    "errors": ["IMAP: Connection refused", "SMTP: Authentication failed"]
}
```

---

### get_folders

Liste les dossiers IMAP d'un compte.

```python
@frappe.whitelist()
def get_folders(account_name: str) -> list
```

**Paramètres:**
| Nom | Type | Description |
|-----|------|-------------|
| account_name | str | Nom du compte |

**Retour:**
```json
[
    {
        "name": "INBOX",
        "delimiter": "/",
        "flags": ["\\HasNoChildren"],
        "selectable": true
    },
    {
        "name": "Sent",
        "delimiter": "/",
        "flags": ["\\Sent", "\\HasNoChildren"],
        "selectable": true
    }
]
```

---

### get_emails

Récupère les emails d'un dossier avec pagination.

```python
@frappe.whitelist()
def get_emails(
    account_name: str,
    folder: str = "INBOX",
    limit: int = 50,
    offset: int = 0,
    search: str = None
) -> dict
```

**Paramètres:**
| Nom | Type | Défaut | Description |
|-----|------|--------|-------------|
| account_name | str | - | Nom du compte |
| folder | str | "INBOX" | Dossier IMAP |
| limit | int | 50 | Nombre d'emails (max 100) |
| offset | int | 0 | Position de départ |
| search | str | None | Terme de recherche |

**Retour:**
```json
{
    "emails": [
        {
            "uid": 12345,
            "subject": "Hello World",
            "from_email": "sender@example.com",
            "from_name": "Sender Name",
            "to": "recipient@example.com",
            "date": "2024-01-15T10:30:00",
            "seen": false,
            "flagged": true,
            "answered": false,
            "has_attachments": true,
            "size": 15234
        }
    ],
    "total": 1523,
    "has_more": true
}
```

---

### get_email_content

Récupère le contenu complet d'un email.

```python
@frappe.whitelist()
def get_email_content(
    account_name: str,
    uid: int,
    folder: str = "INBOX",
    mark_read: bool = True
) -> dict
```

**Paramètres:**
| Nom | Type | Défaut | Description |
|-----|------|--------|-------------|
| account_name | str | - | Nom du compte |
| uid | int | - | UID de l'email |
| folder | str | "INBOX" | Dossier IMAP |
| mark_read | bool | True | Marquer comme lu |

**Retour:**
```json
{
    "uid": 12345,
    "message_id": "<abc123@example.com>",
    "subject": "Hello World",
    "from_email": "sender@example.com",
    "from_name": "Sender Name",
    "to": "recipient@example.com",
    "cc": "cc@example.com",
    "reply_to": "reply@example.com",
    "date": "2024-01-15T10:30:00",
    "html": "<html>...</html>",
    "text": "Plain text version...",
    "attachments": [
        {
            "id": "0",
            "filename": "document.pdf",
            "content_type": "application/pdf",
            "size": 102400
        }
    ],
    "seen": true,
    "flagged": false
}
```

---

### send_email

Envoie un email via SMTP.

```python
@frappe.whitelist()
def send_email(
    account_name: str,
    to: str,
    subject: str,
    html_content: str,
    cc: str = None,
    bcc: str = None,
    reply_to_message_id: str = None,
    attachments: str = None
) -> dict
```

**Paramètres:**
| Nom | Type | Description |
|-----|------|-------------|
| account_name | str | Nom du compte |
| to | str | Destinataires (virgule séparés) |
| subject | str | Sujet |
| html_content | str | Corps HTML |
| cc | str | Copie carbone |
| bcc | str | Copie cachée |
| reply_to_message_id | str | Message-ID pour réponse |
| attachments | str | JSON array de pièces jointes |

**Format des pièces jointes:**
```json
[
    {
        "filename": "document.pdf",
        "content_type": "application/pdf",
        "data": "base64_encoded_content"
    }
]
```

**Retour:**
```json
{
    "success": true,
    "message": "Email sent successfully"
}
```

---

### set_flags

Modifie les flags d'un ou plusieurs emails.

```python
@frappe.whitelist()
def set_flags(
    account_name: str,
    uids: str,
    folder: str,
    add_flags: str = None,
    remove_flags: str = None
) -> dict
```

**Paramètres:**
| Nom | Type | Description |
|-----|------|-------------|
| account_name | str | Nom du compte |
| uids | str | JSON array des UIDs |
| folder | str | Dossier IMAP |
| add_flags | str | JSON array des flags à ajouter |
| remove_flags | str | JSON array des flags à retirer |

**Flags IMAP standards:**
- `\Seen` - Lu
- `\Flagged` - Suivi/Étoile
- `\Answered` - Répondu
- `\Deleted` - Supprimé

**Exemple:**
```javascript
await frappe.call({
    method: 'frappe_webmail.api.set_flags',
    args: {
        account_name: 'user@example.com',
        uids: JSON.stringify([12345, 12346]),
        folder: 'INBOX',
        add_flags: JSON.stringify(['\\Seen', '\\Flagged'])
    }
});
```

---

### move_emails

Déplace des emails vers un autre dossier.

```python
@frappe.whitelist()
def move_emails(
    account_name: str,
    uids: str,
    from_folder: str,
    to_folder: str
) -> dict
```

**Paramètres:**
| Nom | Type | Description |
|-----|------|-------------|
| account_name | str | Nom du compte |
| uids | str | JSON array des UIDs |
| from_folder | str | Dossier source |
| to_folder | str | Dossier destination |

---

### delete_emails

Supprime des emails.

```python
@frappe.whitelist()
def delete_emails(
    account_name: str,
    uids: str,
    folder: str,
    permanent: bool = False
) -> dict
```

**Paramètres:**
| Nom | Type | Défaut | Description |
|-----|------|--------|-------------|
| account_name | str | - | Nom du compte |
| uids | str | - | JSON array des UIDs |
| folder | str | - | Dossier IMAP |
| permanent | bool | False | Suppression définitive |

**Comportement:**
- `permanent=False`: Déplace vers la corbeille
- `permanent=True`: Supprime définitivement

---

### get_attachment

Télécharge une pièce jointe.

```python
@frappe.whitelist()
def get_attachment(
    account_name: str,
    uid: int,
    folder: str,
    attachment_id: str
) -> dict
```

**Retour:**
```json
{
    "filename": "document.pdf",
    "content_type": "application/pdf",
    "data": "base64_encoded_content",
    "size": 102400
}
```

---

### get_signatures

Liste les signatures de l'utilisateur.

```python
@frappe.whitelist()
def get_signatures() -> list
```

**Retour:**
```json
[
    {
        "name": "user@example.com-Professional",
        "signature_name": "Professional",
        "content": "<p>Best regards,<br>John Doe</p>",
        "is_default": true
    }
]
```

---

### get_default_signature

Récupère le contenu de la signature par défaut.

```python
@frappe.whitelist()
def get_default_signature() -> str
```

**Retour:**
```html
"<p>Best regards,<br>John Doe</p>"
```

## Codes d'erreur

| Code | Description |
|------|-------------|
| `ValidationError` | Paramètres invalides |
| `PermissionError` | Accès non autorisé |
| `DoesNotExistError` | Ressource non trouvée |
| `AuthenticationError` | Échec authentification IMAP/SMTP |

## Limites

- Maximum 100 emails par requête
- Timeout IMAP: 30 secondes
- Timeout SMTP: 30 secondes
- Taille max pièce jointe: défini par le serveur email
