# Architecture

## Vue d'ensemble

Frappe Webmail est une application client webmail intégrée à Frappe Framework. Elle utilise une architecture en trois couches:

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Vue.js)                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐│
│  │EmailList│ │ Viewer  │ │Composer │ │ Folders │ │Signature││
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘│
│       │           │           │           │           │      │
│       └───────────┴───────────┴───────────┴───────────┘      │
│                              │                                │
│                       frappe.call()                          │
└──────────────────────────────┼───────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────┐
│                      Backend (Python)                         │
│                              │                                │
│  ┌───────────────────────────┴───────────────────────────┐   │
│  │                      api.py                            │   │
│  │  get_emails() │ send_email() │ get_folders() │ etc.   │   │
│  └───────────────────────────┬───────────────────────────┘   │
│                              │                                │
│  ┌───────────────────────────┴───────────────────────────┐   │
│  │                      utils/                            │   │
│  │     imap_client.py      │      email_parser.py        │   │
│  └───────────────────────────┬───────────────────────────┘   │
└──────────────────────────────┼───────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────┐
│                    External Services                          │
│         ┌────────────────────┴────────────────────┐          │
│         │                    │                    │          │
│    ┌────┴────┐         ┌────┴────┐         ┌────┴────┐      │
│    │  IMAP   │         │  SMTP   │         │ Frappe  │      │
│    │ Server  │         │ Server  │         │   DB    │      │
│    └─────────┘         └─────────┘         └─────────┘      │
└──────────────────────────────────────────────────────────────┘
```

## Composants principaux

### 1. DocTypes

#### Webmail Account
Stocke la configuration des comptes email:
- Paramètres IMAP (host, port, SSL, password)
- Paramètres SMTP (host, port, SSL/STARTTLS, password)
- Signature par défaut
- Lié à un utilisateur Frappe

```python
# Champs principaux
{
    "email": "user@example.com",
    "imap_host": "imap.example.com",
    "imap_port": 993,
    "imap_ssl": 1,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_starttls": 1
}
```

#### Email Signature
Stocke les signatures HTML:
- Contenu HTML (via Text Editor)
- Flag "is_default" pour la signature par défaut
- Un seul défaut par utilisateur (géré automatiquement)

### 2. API Python (api.py)

L'API expose des méthodes whitelistées pour le frontend:

| Méthode | Description |
|---------|-------------|
| `get_accounts()` | Liste les comptes de l'utilisateur |
| `test_connection()` | Teste la connexion IMAP/SMTP |
| `get_folders()` | Liste les dossiers IMAP |
| `get_emails()` | Récupère les emails (paginé) |
| `get_email_content()` | Contenu complet d'un email |
| `send_email()` | Envoie un email |
| `set_flags()` | Modifie les flags (lu, suivi) |
| `move_emails()` | Déplace vers un dossier |
| `delete_emails()` | Supprime (corbeille ou permanent) |
| `get_attachment()` | Télécharge une pièce jointe |
| `get_signatures()` | Liste les signatures |

### 3. Utilitaires

#### WebmailIMAPClient (imap_client.py)
Wrapper pour les opérations IMAP:
- Gestion des connexions (context manager)
- Méthodes simplifiées (select, search, fetch)
- Gestion des erreurs

```python
with WebmailIMAPClient(account) as client:
    folders = client.list_folders()
    client.select_folder('INBOX')
    messages = client.search(['NOT', 'DELETED'])
```

#### EmailParser (email_parser.py)
Parsing et sanitisation des emails:
- Extraction HTML/texte
- Gestion des pièces jointes
- Images inline (CID)
- Sanitisation HTML (XSS protection)

### 4. Frontend Vue.js

#### Composants

| Composant | Responsabilité |
|-----------|----------------|
| `Webmail.vue` | Page principale, orchestration |
| `EmailList.vue` | Liste avec virtual scrolling |
| `EmailViewer.vue` | Affichage sécurisé |
| `EmailComposer.vue` | Éditeur TipTap |
| `FolderTree.vue` | Navigation dossiers |
| `SignatureEditor.vue` | Gestion signatures |

#### Flux de données

```
User Action → Component → frappe.call() → API → IMAP/SMTP
                                            ↓
            Component ← Response ← API ← Server Response
```

## Sécurité

Voir [security.md](./security.md) pour les détails sur:
- Sanitisation HTML (DOMPurify + bleach)
- Iframe sandboxée
- Blocage images externes
- Chiffrement des mots de passe

## Performance

- **Virtual scrolling**: Gestion de milliers d'emails
- **Pagination**: 50 emails par requête (max 100)
- **Lazy loading**: Contenu chargé à la demande
- **Cache**: Enveloppes IMAP mises en cache
