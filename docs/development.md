# Development Guide

Guide complet pour le développement de Frappe Webmail.

## Prérequis

- Python 3.10+
- Node.js 18+
- Frappe Framework v14 ou v15
- Git

## Setup de développement

### 1. Cloner le repository

```bash
cd ~/frappe-bench/apps
git clone https://github.com/your-org/frappe_webmail.git
```

### 2. Installer les dépendances Python

```bash
cd frappe_webmail
pip install -r requirements.txt

# Pour le développement
pip install pytest pytest-frappe
```

### 3. Installer les dépendances frontend

```bash
cd frontend
npm install
```

### 4. Installer l'app sur un site de dev

```bash
cd ~/frappe-bench
bench --site dev.local install-app frappe_webmail
bench --site dev.local migrate
```

## Structure du code

### Backend

```
frappe_webmail/
├── api.py                          # API principale
├── hooks.py                        # Configuration Frappe
├── api/
│   ├── __init__.py
│   └── permission.py               # Permissions app
├── utils/
│   ├── __init__.py
│   ├── imap_client.py              # Client IMAP
│   └── email_parser.py             # Parsing emails
├── frappe_webmail/
│   ├── doctype/
│   │   ├── webmail_account/
│   │   │   ├── webmail_account.json
│   │   │   └── webmail_account.py
│   │   └── email_signature/
│   │       ├── email_signature.json
│   │       └── email_signature.py
│   └── page/
│       └── webmail/
│           ├── webmail.json
│           ├── webmail.html
│           └── webmail.js
├── tests/
│   ├── __init__.py
│   ├── test_api.py
│   └── test_doctypes.py
├── public/
│   ├── js/
│   └── css/
└── www/
    ├── webmail.html
    └── webmail.py
```

### Frontend

```
frontend/
├── src/
│   ├── main.js
│   ├── pages/
│   │   └── Webmail.vue
│   └── components/
│       ├── EmailList.vue
│       ├── EmailViewer.vue
│       ├── EmailComposer.vue
│       ├── FolderTree.vue
│       └── SignatureEditor.vue
├── tests/
│   ├── setup.js
│   └── components/
│       ├── EmailList.spec.js
│       └── EmailViewer.spec.js
├── package.json
└── vite.config.js
```

## Développement Backend

### Ajouter une nouvelle méthode API

1. Ajouter la fonction dans `api.py`:

```python
@frappe.whitelist()
def my_new_method(param1, param2=None):
    """Description de la méthode"""
    # Validation
    if not param1:
        frappe.throw(_("param1 is required"))

    # Logique
    result = do_something(param1, param2)

    return {"success": True, "data": result}
```

2. Ajouter les tests dans `tests/test_api.py`:

```python
def test_my_new_method():
    result = frappe.call(
        "frappe_webmail.api.my_new_method",
        param1="value"
    )
    assert result["success"] == True
```

### Modifier un DocType

1. Modifier le fichier JSON ou utiliser l'interface Frappe
2. Mettre à jour le controller Python si nécessaire
3. Lancer la migration:

```bash
bench --site dev.local migrate
```

### Ajouter un utilitaire

1. Créer le fichier dans `utils/`:

```python
# utils/my_utility.py
class MyUtility:
    def __init__(self):
        pass

    def do_something(self):
        pass
```

2. L'exporter dans `utils/__init__.py`:

```python
from frappe_webmail.utils.my_utility import MyUtility
```

## Développement Frontend

### Mode développement

```bash
cd frontend
npm run dev
```

Le serveur Vite démarre sur `localhost:5173` avec hot reload.

### Ajouter un composant

1. Créer le fichier `.vue`:

```vue
<!-- components/MyComponent.vue -->
<template>
  <div class="my-component">
    {{ message }}
  </div>
</template>

<script>
export default {
  name: 'MyComponent',
  props: {
    message: { type: String, default: '' }
  }
}
</script>

<style scoped>
.my-component {
  padding: 16px;
}
</style>
```

2. L'importer dans le composant parent:

```vue
<script>
import MyComponent from './MyComponent.vue'

export default {
  components: { MyComponent }
}
</script>
```

### Appeler l'API Frappe

```javascript
// Utiliser frappe.call (disponible globalement)
const response = await frappe.call({
    method: 'frappe_webmail.api.my_method',
    args: {
        param1: 'value'
    }
});

if (response.message.success) {
    // Succès
}
```

### Build production

```bash
npm run build
```

Les fichiers sont générés dans `frappe_webmail/public/js/`.

## Tests

### Tests Python

```bash
cd ~/frappe-bench
bench --site dev.local run-tests --app frappe_webmail
```

Ou un test spécifique:

```bash
bench --site dev.local run-tests --app frappe_webmail --module frappe_webmail.tests.test_api
```

### Tests Frontend

```bash
cd frontend
npm test
```

## Debugging

### Backend

```python
# Logs
frappe.log_error("Debug message", "Webmail Debug")

# Console (bench console)
frappe.get_doc("Webmail Account", "user@example.com")

# Breakpoint
import pdb; pdb.set_trace()
```

### Frontend

```javascript
// Console browser
console.log('Debug:', data)

// Vue DevTools
// Installer l'extension Chrome/Firefox
```

## Conventions de code

### Python

- Suivre PEP 8
- Docstrings pour toutes les fonctions publiques
- Type hints recommandés
- Formater avec `ruff`

```python
def my_function(param: str) -> dict:
    """
    Description courte.

    Args:
        param: Description du paramètre

    Returns:
        dict: Description du retour
    """
    pass
```

### JavaScript/Vue

- ESLint + Prettier
- Composition API ou Options API (cohérent)
- Props avec types et defaults
- Events documentés

```javascript
export default {
    props: {
        email: {
            type: Object,
            default: null
        }
    },
    emits: ['select', 'delete']
}
```

## Git Workflow

### Branches

- `main` - Production stable
- `develop` - Développement
- `feature/*` - Nouvelles fonctionnalités
- `fix/*` - Corrections de bugs

### Commits

Format: `type: description`

Types:
- `feat` - Nouvelle fonctionnalité
- `fix` - Correction de bug
- `docs` - Documentation
- `style` - Formatage
- `refactor` - Refactoring
- `test` - Tests
- `chore` - Maintenance

Exemple:
```
feat: add email draft auto-save
fix: correct attachment download on Safari
docs: update API reference
```

### Pull Request

1. Créer une branche feature
2. Développer et tester
3. Pousser et créer la PR
4. Review et merge

## Release

1. Mettre à jour la version dans `pyproject.toml`
2. Mettre à jour le CHANGELOG
3. Créer un tag Git
4. Pousser sur le repository

```bash
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```
