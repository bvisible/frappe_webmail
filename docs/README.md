# Frappe Webmail Documentation

Bienvenue dans la documentation de Frappe Webmail. Cette documentation couvre l'architecture, l'API, et le guide de développement.

## Table des matières

1. [Architecture](./architecture.md) - Vue d'ensemble de l'architecture
2. [API Reference](./api-reference.md) - Documentation complète de l'API Python
3. [Frontend](./frontend.md) - Guide des composants Vue.js
4. [Security](./security.md) - Mesures de sécurité implémentées
5. [Development Guide](./development.md) - Guide pour les développeurs
6. [Testing](./testing.md) - Guide des tests

## Quick Start

### Installation

```bash
# Cloner et installer
bench get-app frappe_webmail
bench --site your-site install-app frappe_webmail

# Dépendances Python
cd apps/frappe_webmail
pip install -r requirements.txt

# Build frontend
cd frontend
npm install
npm run build

# Migration
bench --site your-site migrate
```

### Configuration

1. Aller dans **Webmail Account** dans Frappe Desk
2. Créer un nouveau compte avec les paramètres IMAP/SMTP
3. Accéder à `/app/webmail`

## Structure du projet

```
frappe_webmail/
├── docs/                    # Documentation
├── frappe_webmail/
│   ├── api.py              # API endpoints
│   ├── hooks.py            # Frappe hooks
│   ├── tests/              # Tests Python
│   ├── utils/              # Utilitaires
│   ├── frappe_webmail/
│   │   ├── doctype/        # DocTypes
│   │   └── page/           # Pages Desk
│   ├── public/             # Assets statiques
│   └── www/                # Pages web
├── frontend/
│   ├── src/                # Code source Vue.js
│   └── tests/              # Tests frontend
└── requirements.txt
```
