# Frontend Documentation

Guide des composants Vue.js de Frappe Webmail.

## Stack technique

- **Vue.js 3** - Framework frontend
- **TipTap 2** - Éditeur rich text
- **DOMPurify** - Sanitisation HTML
- **vue-virtual-scroller** - Virtual scrolling pour les listes

## Structure des fichiers

```
frontend/
├── src/
│   ├── main.js                 # Point d'entrée
│   ├── pages/
│   │   └── Webmail.vue         # Page principale
│   └── components/
│       ├── EmailList.vue       # Liste emails
│       ├── EmailViewer.vue     # Affichage email
│       ├── EmailComposer.vue   # Composition
│       ├── FolderTree.vue      # Dossiers
│       └── SignatureEditor.vue # Signatures
├── tests/
│   └── *.spec.js               # Tests unitaires
├── package.json
└── vite.config.js
```

## Composants

### Webmail.vue

Page principale orchestrant tous les composants.

**Props:** Aucune

**Data:**
```javascript
{
  accounts: [],           // Liste des comptes
  currentAccount: '',     // Compte actif
  currentFolder: 'INBOX', // Dossier actif
  selectedEmail: null,    // Email sélectionné (liste)
  selectedEmailContent: null, // Contenu complet
  showComposer: false,    // Afficher compositeur
  replyToEmail: null,     // Email pour réponse
  forwardingEmail: null,  // Email pour transfert
  defaultSignature: '',   // Signature par défaut
  showSignatures: false   // Modal signatures
}
```

**Méthodes principales:**
| Méthode | Description |
|---------|-------------|
| `initialize()` | Charge comptes et signature |
| `onEmailSelect(email)` | Sélectionne et charge un email |
| `compose()` | Ouvre le compositeur vide |
| `replyTo(email)` | Réponse à un email |
| `forwardEmail(email)` | Transfert d'un email |
| `deleteEmail(email)` | Supprime un email |

---

### EmailList.vue

Liste des emails avec virtual scrolling.

**Props:**
| Prop | Type | Défaut | Description |
|------|------|--------|-------------|
| account | String | required | Nom du compte |
| folder | String | 'INBOX' | Dossier IMAP |
| selectedUid | Number | null | UID sélectionné |

**Events:**
| Event | Payload | Description |
|-------|---------|-------------|
| select | email | Email sélectionné |
| update:total | number | Nombre total d'emails |

**Méthodes exposées:**
```javascript
// Accès via ref
this.$refs.emailList.refresh()    // Recharge la liste
this.$refs.emailList.markAsRead(uid) // Marque comme lu
```

**Exemple:**
```vue
<EmailList
  ref="emailList"
  :account="currentAccount"
  :folder="currentFolder"
  :selected-uid="selectedEmail?.uid"
  @select="onEmailSelect"
  @update:total="totalEmails = $event"
/>
```

---

### EmailViewer.vue

Affichage sécurisé du contenu email.

**Props:**
| Prop | Type | Défaut | Description |
|------|------|--------|-------------|
| email | Object | null | Contenu email complet |
| account | String | required | Nom du compte |
| folder | String | 'INBOX' | Dossier IMAP |

**Events:**
| Event | Payload | Description |
|-------|---------|-------------|
| reply | email | Demande réponse |
| forward | email | Demande transfert |
| delete | email | Demande suppression |
| flag-changed | email | Flag modifié |

**Sécurité:**
- HTML sanitisé via DOMPurify
- Rendu dans iframe sandboxée
- Images externes bloquées par défaut

**Computed - sanitizedContent:**
```javascript
// Génère un document HTML complet sanitisé
{
  WHOLE_DOCUMENT: true,
  FORBID_TAGS: ['script', 'style', 'form', ...],
  FORBID_ATTR: ['onerror', 'onload', 'onclick', ...],
  ALLOW_DATA_ATTR: false
}
```

---

### EmailComposer.vue

Éditeur rich text avec TipTap.

**Props:**
| Prop | Type | Défaut | Description |
|------|------|--------|-------------|
| account | String | required | Nom du compte |
| replyTo | Object | null | Email pour réponse |
| forwardEmail | Object | null | Email pour transfert |
| signature | String | '' | Signature HTML |

**Events:**
| Event | Payload | Description |
|-------|---------|-------------|
| sent | - | Email envoyé |
| close | - | Fermeture demandée |

**Extensions TipTap:**
- StarterKit (bold, italic, lists, etc.)
- Underline
- Link
- Image
- Placeholder

**Méthodes:**
| Méthode | Description |
|---------|-------------|
| `initEditor()` | Initialise TipTap |
| `setupReply()` | Configure pour réponse |
| `setupForward()` | Configure pour transfert |
| `insertSignature()` | Insère la signature |
| `send()` | Envoie l'email |

**Format pièces jointes:**
```javascript
{
  filename: 'document.pdf',
  content_type: 'application/pdf',
  data: 'base64...'
}
```

---

### FolderTree.vue

Navigation dans les dossiers IMAP.

**Props:**
| Prop | Type | Défaut | Description |
|------|------|--------|-------------|
| account | String | required | Nom du compte |
| accountEmail | String | '' | Email pour affichage |
| selectedFolder | String | 'INBOX' | Dossier sélectionné |

**Events:**
| Event | Payload | Description |
|-------|---------|-------------|
| select | folderName | Dossier sélectionné |

**Détection des dossiers spéciaux:**
```javascript
// Flags IMAP
'\\Inbox' → 📥
'\\Sent' → 📤
'\\Drafts' → 📝
'\\Trash' → 🗑️
'\\Junk' → ⚠️
'\\Archive' → 📦
```

---

### SignatureEditor.vue

Gestion des signatures email.

**Events:**
| Event | Payload | Description |
|-------|---------|-------------|
| close | - | Fermeture demandée |
| updated | - | Signature modifiée |

**Fonctionnalités:**
- Liste des signatures
- Création/édition/suppression
- Éditeur TipTap pour HTML
- Gestion du flag "par défaut"

## Intégration Frappe

### Appels API

```javascript
// Utiliser frappe.call pour les requêtes
const response = await frappe.call({
  method: 'frappe_webmail.api.get_emails',
  args: {
    account_name: 'user@example.com',
    folder: 'INBOX',
    limit: 50
  }
});

const emails = response.message.emails;
```

### Notifications

```javascript
// Toast notifications
frappe.toast({
  message: 'Email envoyé !',
  indicator: 'green' // green, red, blue, orange
});
```

### Navigation

```javascript
// Ouvrir une page Frappe
frappe.set_route('List', 'Webmail Account');

// Ouvrir un DocType
frappe.set_route('Form', 'Webmail Account', 'user@example.com');
```

## Build

### Développement

```bash
cd frontend
npm install
npm run dev
```

### Production

```bash
cd frontend
npm run build
```

Les fichiers sont générés dans `frappe_webmail/public/js/`.

## Tests

```bash
cd frontend
npm test
```

Voir [testing.md](./testing.md) pour plus de détails.
