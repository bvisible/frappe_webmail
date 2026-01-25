# CLAUDE.md - Development Guide for Claude Code

Ce fichier fournit le contexte et les instructions pour Claude Code (ou tout autre assistant IA) travaillant sur ce projet.

## Vue d'ensemble du projet

**Frappe Webmail** est un client webmail natif pour Frappe Framework avec support IMAP/SMTP complet.

### Stack technique

- **Backend**: Python 3.10+, Frappe Framework
- **Frontend**: Vue.js 3, TipTap (éditeur), DOMPurify (sécurité)
- **Protocoles**: IMAP (imapclient), SMTP (smtplib natif)

## Structure du projet

```
frappe_webmail/
├── CLAUDE.md                    # Ce fichier
├── README.md                    # Documentation utilisateur
├── docs/                        # Documentation détaillée
│   ├── README.md
│   ├── architecture.md
│   ├── api-reference.md
│   ├── frontend.md
│   ├── security.md
│   ├── development.md
│   └── testing.md
├── frappe_webmail/
│   ├── api.py                   # API Python principale
│   ├── hooks.py                 # Configuration Frappe
│   ├── api/
│   │   └── permission.py        # Permissions
│   ├── utils/
│   │   ├── imap_client.py       # Client IMAP wrapper
│   │   └── email_parser.py      # Parsing emails
│   ├── frappe_webmail/
│   │   ├── doctype/
│   │   │   ├── webmail_account/ # DocType compte email
│   │   │   └── email_signature/ # DocType signatures
│   │   └── page/
│   │       └── webmail/         # Page Desk
│   ├── tests/
│   │   ├── test_api.py
│   │   ├── test_doctypes.py
│   │   └── test_utils.py
│   ├── public/
│   │   ├── js/
│   │   └── css/
│   └── www/
│       └── webmail.html
├── frontend/
│   ├── src/
│   │   ├── main.js
│   │   ├── pages/
│   │   │   └── Webmail.vue
│   │   └── components/
│   │       ├── EmailList.vue
│   │       ├── EmailViewer.vue
│   │       ├── EmailComposer.vue
│   │       ├── FolderTree.vue
│   │       └── SignatureEditor.vue
│   ├── tests/
│   │   ├── setup.js
│   │   └── components/
│   ├── package.json
│   └── vite.config.js
├── requirements.txt
└── pyproject.toml
```

## Commandes de développement

### Backend

```bash
# Lancer les tests
bench --site dev.local run-tests --app frappe_webmail

# Test d'un module spécifique
bench --site dev.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_api

# Migration
bench --site dev.local migrate

# Console
bench --site dev.local console
```

### Frontend

```bash
cd frontend

# Installation
npm install

# Développement (hot reload)
npm run dev

# Build production
npm run build

# Tests
npm test
npm test:run
npm test:coverage
```

## Git Workflow - Règles de Commit

### Workflow obligatoire

1. **EXPLORER** le code localement
2. **MODIFIER** les fichiers localement
3. **TESTER** sur l'instance cible via SSH (osiris)
4. **VÉRIFIER** que le fix fonctionne à 100%
5. **DEMANDER** la permission à l'utilisateur avant de commit/push

### Règles strictes

- **JAMAIS** commit du code non testé
- **JAMAIS** modifier les fichiers directement sur les serveurs distants
- **TOUJOURS** tester via SSH avant de commit
- **TOUJOURS** demander confirmation avant push

### Déploiement après fix

```bash
# Sur l'instance cible (osiris)
cd /home/neoffice/frappe-bench/apps/frappe_webmail && git pull upstream develop
cd /home/neoffice/frappe-bench && bench restart
```

### Serveur de test

| Instance | URL | Serveur SSH |
|----------|-----|-------------|
| Osiris | `https://osiris.neoffice.me` | `osiris` |

---

## Tâches courantes

### Ajouter une nouvelle méthode API

1. Ajouter la fonction dans `frappe_webmail/api.py`:
```python
@frappe.whitelist()
def ma_nouvelle_methode(param1, param2=None):
    """Description"""
    account = get_account(param1)  # Validation
    # Logique...
    return {"success": True}
```

2. Ajouter les tests dans `tests/test_api.py`

3. Documenter dans `docs/api-reference.md`

### Modifier un DocType

1. Modifier le JSON ou via l'interface Frappe
2. Mettre à jour le controller Python si nécessaire
3. Lancer `bench migrate`
4. Mettre à jour les tests

### Ajouter un composant Vue

1. Créer `frontend/src/components/MonComposant.vue`
2. L'importer dans le composant parent
3. Ajouter les tests dans `frontend/tests/components/`
4. Documenter dans `docs/frontend.md`

## Conventions de code

### Python

- PEP 8 (formater avec `ruff`)
- Docstrings pour fonctions publiques
- Type hints recommandés
- Utiliser `frappe.throw()` pour les erreurs

```python
def ma_fonction(param: str) -> dict:
    """
    Description.

    Args:
        param: Description

    Returns:
        dict: Description
    """
    if not param:
        frappe.throw(_("param is required"))
    return {"result": param}
```

### JavaScript/Vue

- ESLint + Prettier
- Props typées avec defaults
- Documenter les events émis

```vue
<script>
export default {
  props: {
    email: { type: Object, default: null }
  },
  emits: ['select', 'delete']
}
</script>
```

## Sécurité - Points critiques

1. **Sanitisation HTML**: Toujours utiliser DOMPurify (client) ET bleach (serveur)
2. **Accès aux comptes**: Vérifier `account.user == frappe.session.user`
3. **Mots de passe**: Utiliser le fieldtype `Password` de Frappe
4. **XSS**: Bloquer les event handlers (`onerror`, `onclick`, etc.)
5. **Tracking**: Bloquer les images externes par défaut

## Tests - Ce qu'il faut tester

### Backend

- Permissions (accès aux comptes d'autres utilisateurs)
- Validation des entrées
- Gestion des erreurs IMAP/SMTP (avec mocks)
- Sanitisation HTML

### Frontend

- Rendu des composants
- Events émis
- Sanitisation HTML dans EmailViewer
- États de chargement et erreurs

## Améliorations à faire

Voir `docs/testing.md` et le README pour la roadmap complète.

### Priorité haute

1. **Draft auto-save**: Sauvegarder les brouillons automatiquement
2. **IMAP IDLE**: Notifications temps réel (ou polling)
3. **Recherche avancée**: Recherche full-text

### Priorité moyenne

4. **OAuth2**: Support Gmail/Outlook OAuth
5. **Filtres email**: Règles automatiques
6. **Contacts**: Gestion des contacts

### Priorité basse

7. **CalDAV**: Intégration calendrier
8. **Mobile**: Améliorer le responsive

## Dépendances externes

### Python (requirements.txt)

```
imapclient>=2.3.0    # Client IMAP
bleach>=6.0.0        # Sanitisation HTML
```

### JavaScript (package.json)

```
@tiptap/*            # Éditeur rich text
dompurify            # Sanitisation HTML
vue-virtual-scroller # Virtual scrolling
```

## Debugging

### Backend

```python
# Log
frappe.log_error("message", "Webmail Debug")

# Breakpoint
import pdb; pdb.set_trace()

# Console
bench --site dev.local console
>>> doc = frappe.get_doc("Webmail Account", "email@example.com")
```

### Frontend

```javascript
// Console
console.log('Debug:', data)

// Vue DevTools (extension navigateur)
```

## Questions fréquentes

### Comment tester sans serveur IMAP ?

Utiliser les mocks dans les tests:
```python
from unittest.mock import patch, MagicMock

@patch('frappe_webmail.api.IMAPClient')
def test_get_folders(self, mock_imap):
    mock_client = MagicMock()
    mock_client.list_folders.return_value = [...]
    mock_imap.return_value.__enter__ = MagicMock(return_value=mock_client)
    # ...
```

### Comment ajouter un provider email (Gmail, Outlook) ?

1. Les paramètres IMAP/SMTP sont configurables par l'utilisateur
2. Pour OAuth2, il faudra:
   - Ajouter les credentials dans Site Config
   - Implémenter le flow OAuth dans l'API
   - Stocker les tokens refresh

### Où sont stockés les mots de passe ?

Dans la table Frappe, chiffrés avec la clé du site (`site_config.json`).
Utiliser `doc.get_password("field_name")` pour déchiffrer.

## Contact

Pour toute question sur le projet, consulter:
- `docs/` pour la documentation détaillée
- Les tests pour des exemples de code
- Le README pour l'installation et l'usage
