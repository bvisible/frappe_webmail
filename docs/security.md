# Security

Documentation des mesures de sécurité implémentées dans Frappe Webmail.

## Vue d'ensemble

Frappe Webmail implémente plusieurs couches de sécurité pour protéger contre:
- Injection XSS via emails HTML
- Tracking pixels et images externes
- Vol de credentials
- Accès non autorisé aux comptes

## Sanitisation HTML

### Côté serveur (Python)

Utilisation de **bleach** pour la sanitisation:

```python
import bleach

SAFE_TAGS = [
    'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'div', 'em',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li',
    'ol', 'p', 'pre', 'span', 'strong', 'table', 'tbody', 'td',
    'th', 'thead', 'tr', 'u', 'ul'
]

SAFE_ATTRIBUTES = {
    '*': ['class', 'style'],
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'width', 'height'],
    'table': ['border', 'cellpadding', 'cellspacing', 'width'],
    'td': ['colspan', 'rowspan', 'width', 'valign', 'align'],
    'th': ['colspan', 'rowspan', 'width', 'valign', 'align']
}

clean_html = bleach.clean(html, tags=SAFE_TAGS, attributes=SAFE_ATTRIBUTES)
```

### Côté client (JavaScript)

Utilisation de **DOMPurify** pour une deuxième couche:

```javascript
import DOMPurify from 'dompurify'

const config = {
    WHOLE_DOCUMENT: true,
    FORBID_TAGS: [
        'script', 'style', 'audio', 'video', 'form',
        'input', 'button', 'textarea', 'object', 'embed'
    ],
    FORBID_ATTR: [
        'onerror', 'onload', 'onclick', 'onmouseover',
        'onfocus', 'onblur', 'onsubmit'
    ],
    ALLOW_DATA_ATTR: false
}

const clean = DOMPurify.sanitize(content, config)
```

## Iframe sandboxée

Les emails sont affichés dans une iframe avec restrictions:

```html
<iframe
    sandbox="allow-popups allow-popups-to-escape-sandbox"
    referrerpolicy="no-referrer"
    :srcdoc="sanitizedContent"
/>
```

**Permissions bloquées:**
- `allow-scripts` - Pas d'exécution JavaScript
- `allow-forms` - Pas de soumission de formulaires
- `allow-same-origin` - Isolation du contexte
- `allow-top-navigation` - Pas de redirection de la page

**Permissions accordées:**
- `allow-popups` - Ouverture de liens (nouvelle fenêtre)
- `allow-popups-to-escape-sandbox` - Liens fonctionnels

## Blocage des images externes

Par défaut, les images externes sont bloquées pour prévenir le tracking:

```javascript
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'IMG' && !showExternalImages) {
        const src = node.getAttribute('src')
        if (src && !src.startsWith('data:') && !src.startsWith('cid:')) {
            // Remplace par placeholder
            node.setAttribute('data-blocked-src', src)
            node.setAttribute('src', 'data:image/svg+xml,...')
        }
    }
})
```

**Images autorisées:**
- `data:` URLs (inline base64)
- `cid:` URLs (images embarquées dans l'email)

**Images bloquées:**
- `http://` URLs
- `https://` URLs
- Toute URL externe

## Stockage des mots de passe

Les mots de passe IMAP/SMTP utilisent le fieldtype `Password` de Frappe:

```python
# Dans le DocType
{
    "fieldname": "imap_password",
    "fieldtype": "Password",
    "label": "IMAP Password"
}

# Récupération (déchiffrement automatique)
password = account.get_password("imap_password")
```

**Caractéristiques:**
- Chiffrement AES en base de données
- Clé de chiffrement dans `site_config.json`
- Jamais exposé via l'API (champ masqué)

## Contrôle d'accès

### Permissions DocType

```json
{
    "permissions": [
        {
            "role": "System Manager",
            "read": 1, "write": 1, "create": 1, "delete": 1
        },
        {
            "role": "All",
            "read": 1, "write": 1, "create": 1, "delete": 1,
            "if_owner": 1
        }
    ]
}
```

### Validation API

```python
def get_account(account_name):
    """Valide l'accès au compte"""
    account = frappe.get_doc("Webmail Account", account_name)

    # Vérifie que le compte appartient à l'utilisateur
    if account.user != frappe.session.user:
        frappe.throw(_("Access denied"))

    if not account.enabled:
        frappe.throw(_("Account is disabled"))

    return account
```

## Protection CSRF

Toutes les requêtes API passent par `frappe.call()` qui inclut automatiquement le token CSRF.

## Headers de sécurité

Recommandations pour le serveur web:

```nginx
# Content Security Policy
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self' blob:;";

# Autres headers
add_header X-Content-Type-Options "nosniff";
add_header X-Frame-Options "SAMEORIGIN";
add_header X-XSS-Protection "1; mode=block";
add_header Referrer-Policy "strict-origin-when-cross-origin";
```

## Logging et audit

Les erreurs sont loguées pour audit:

```python
frappe.log_error(f"Email send error: {str(e)}", "Frappe Webmail")
```

## Recommandations

### Pour les utilisateurs

1. Utiliser des **App Passwords** pour Gmail/Outlook
2. Ne pas cliquer sur "Afficher les images" pour les emails suspects
3. Vérifier l'expéditeur avant de répondre

### Pour les administrateurs

1. Activer HTTPS obligatoire
2. Configurer les headers de sécurité
3. Mettre à jour régulièrement les dépendances
4. Surveiller les logs d'erreur
5. Limiter l'accès au rôle approprié

## Vulnérabilités connues

Aucune vulnérabilité connue à ce jour.

Pour signaler une vulnérabilité, contacter: security@example.com
