# Plan : Actions Groupées pour Webmail

## Objectif
Implémenter un système d'actions groupées (bulk actions) permettant de sélectionner plusieurs emails et d'effectuer des opérations en masse avec une UX moderne et intuitive.

---

## 1. Mode de Sélection

### 1.1 Checkbox visible sur chaque email
- Checkbox à gauche de l'étoile (toujours visible, pas au hover)
- Taille minimum : 24x24px desktop, 44x44px mobile
- Animation de coche au clic

### 1.2 Méthodes de sélection
| Méthode | Action |
|---------|--------|
| **Click checkbox** | Toggle sélection de l'email |
| **Shift+Click** | Sélectionner une plage (du dernier sélectionné au cliqué) |
| **Cmd/Ctrl+Click** | Ajouter/retirer un email sans désélectionner les autres |
| **Click sur email** | Sélectionne ET ouvre l'email (comportement actuel) |

### 1.3 "Select All" dans le header
- Checkbox dans le toolbar de la liste
- États : vide / indéterminé (certains) / coché (tous)
- Quand tout sélectionné : afficher "Sélectionner tous les X emails du dossier"

---

## 2. Composant BulkActionBar.vue

### 2.1 Structure
```vue
<template>
  <Transition name="slide-down">
    <div v-if="selectedCount > 0" class="bulk-action-bar">
      <div class="selection-info">
        <button @click="clearSelection" class="btn-clear">
          <X :size="16" />
        </button>
        <span>{{ selectedCount }} sélectionné(s)</span>
      </div>

      <div class="bulk-actions">
        <!-- Actions principales -->
        <button @click="$emit('archive')" :title="__('Archive')">
          <Archive :size="18" />
        </button>
        <button @click="$emit('delete')" :title="__('Delete')">
          <Trash2 :size="18" />
        </button>
        <button @click="$emit('mark-read')" :title="__('Mark as read')">
          <MailOpen :size="18" />
        </button>
        <button @click="$emit('mark-unread')" :title="__('Mark as unread')">
          <Mail :size="18" />
        </button>

        <!-- Dropdown Déplacer vers -->
        <div class="dropdown">
          <button @click="showMoveMenu = !showMoveMenu">
            <FolderInput :size="18" />
            <span>{{ __('Move to') }}</span>
            <ChevronDown :size="14" />
          </button>
          <div v-if="showMoveMenu" class="dropdown-menu">
            <div v-for="folder in folders" :key="folder.name"
                 @click="$emit('move', folder.name)">
              {{ folder.displayName }}
            </div>
          </div>
        </div>

        <!-- Menu More -->
        <div class="dropdown">
          <button @click="showMoreMenu = !showMoreMenu">
            <MoreHorizontal :size="18" />
          </button>
          <div v-if="showMoreMenu" class="dropdown-menu">
            <div @click="$emit('toggle-star')">
              <Star :size="16" /> {{ __('Toggle star') }}
            </div>
            <div @click="$emit('spam')">
              <AlertTriangle :size="16" /> {{ __('Mark as spam') }}
            </div>
            <div @click="$emit('copy')" class="has-submenu">
              <Copy :size="16" /> {{ __('Copy to') }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>
```

### 2.2 Props & Events
```javascript
props: {
  selectedCount: { type: Number, required: true },
  folders: { type: Array, default: () => [] }
}

emits: [
  'clear',
  'archive',
  'delete',
  'mark-read',
  'mark-unread',
  'move',
  'copy',
  'toggle-star',
  'spam',
  'delete-permanent'
]
```

### 2.3 Styles
```css
.bulk-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: var(--primary-color, #2490ef);
  color: white;
  border-radius: 8px 8px 0 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.2s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
```

---

## 3. Modifications EmailList.vue

### 3.1 Template - Ajouter checkbox
```vue
<div class="email-row" ...>
  <!-- Checkbox pour sélection -->
  <div class="checkbox-cell" @click.stop="toggleSelection(item)">
    <input
      type="checkbox"
      :checked="isSelected(item.uid)"
      @click.stop
      @change="toggleSelection(item)"
    />
  </div>

  <div class="star" @click.stop="toggleStar(item)">
    <!-- ... existant ... -->
  </div>
  <!-- ... reste du contenu ... -->
</div>
```

### 3.2 Data & Computed
```javascript
data() {
  return {
    // ... existant ...
    selectedUids: new Set(),
    lastSelectedIndex: -1,
  }
},

computed: {
  selectedCount() {
    return this.selectedUids.size;
  },

  selectedEmails() {
    return this.emails.filter(e => this.selectedUids.has(e.uid));
  },

  allSelected() {
    return this.emails.length > 0 &&
           this.emails.every(e => this.selectedUids.has(e.uid));
  },

  someSelected() {
    return this.selectedUids.size > 0 && !this.allSelected;
  }
}
```

### 3.3 Methods
```javascript
methods: {
  toggleSelection(email, event) {
    const index = this.emails.findIndex(e => e.uid === email.uid);

    // Shift+Click pour sélection de plage
    if (event?.shiftKey && this.lastSelectedIndex !== -1) {
      const start = Math.min(this.lastSelectedIndex, index);
      const end = Math.max(this.lastSelectedIndex, index);

      for (let i = start; i <= end; i++) {
        this.selectedUids.add(this.emails[i].uid);
      }
    } else {
      // Toggle normal
      if (this.selectedUids.has(email.uid)) {
        this.selectedUids.delete(email.uid);
      } else {
        this.selectedUids.add(email.uid);
      }
    }

    this.lastSelectedIndex = index;
  },

  isSelected(uid) {
    return this.selectedUids.has(uid);
  },

  selectAll() {
    if (this.allSelected) {
      this.selectedUids.clear();
    } else {
      this.emails.forEach(e => this.selectedUids.add(e.uid));
    }
  },

  clearSelection() {
    this.selectedUids.clear();
    this.lastSelectedIndex = -1;
  },

  removeFromSelection(uids) {
    uids.forEach(uid => this.selectedUids.delete(uid));
  }
}
```

### 3.4 Styles checkbox
```css
.checkbox-cell {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  padding-top: 2px;
}

.checkbox-cell input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--primary-color, #2490ef);
}

.email-row.selected {
  background: rgba(36, 144, 239, 0.12);
  border-left: 3px solid var(--primary-color, #2490ef);
}
```

---

## 4. Adaptation ContextMenu pour Multi-sélection

### 4.1 Header informatif
Quand plusieurs emails sont sélectionnés, le menu affiche un header :
```vue
<div v-if="selectedCount > 1" class="context-menu-header">
  {{ selectedCount }} emails sélectionnés
</div>
```

### 4.2 Items adaptés
- Retirer "Répondre" / "Répondre à tous" / "Transférer" (pas de sens en bulk)
- Garder : Marquer lu/non lu, Étoile, Déplacer, Copier, Corbeille, Spam, Supprimer

### 4.3 Logique
```javascript
computed: {
  contextMenuItems() {
    // Si multi-sélection, menu simplifié
    if (this.selectedCount > 1) {
      return this.getBulkContextMenuItems();
    }
    // Sinon menu normal (existant)
    return this.getSingleEmailContextMenuItems();
  }
}
```

---

## 5. Toast avec Undo

### 5.1 Composant Toast (utiliser frappe.toast amélioré)
```javascript
// Après une action bulk
showUndoToast(message, undoCallback) {
  const toast = frappe.toast({
    message: `${message} <a href="#" class="undo-link">Annuler</a>`,
    indicator: 'green',
  });

  // Ajouter handler pour Undo
  toast.querySelector('.undo-link')?.addEventListener('click', (e) => {
    e.preventDefault();
    undoCallback();
    toast.remove();
  });

  // Auto-remove après 8 secondes
  setTimeout(() => toast.remove(), 8000);
}
```

### 5.2 Implémentation Undo
Pour l'undo, on stocke temporairement les UIDs et le dossier source :
```javascript
data() {
  return {
    lastBulkAction: null // { type: 'move', uids: [...], fromFolder: '...', toFolder: '...' }
  }
},

methods: {
  async undoLastAction() {
    if (!this.lastBulkAction) return;

    const { type, uids, fromFolder, toFolder } = this.lastBulkAction;

    if (type === 'move') {
      // Remettre les emails dans le dossier d'origine
      await this.moveEmails(uids, toFolder, fromFolder);
    }
    // ... autres types d'actions

    this.lastBulkAction = null;
    this.refresh();
  }
}
```

---

## 6. Webmail.vue - Handlers Bulk

### 6.1 Nouveaux handlers
```javascript
methods: {
  async handleBulkArchive() {
    const uids = this.$refs.emailList.selectedUids;
    const archiveFolder = this.folderMapping.archive || 'Archive';
    await this.bulkMoveEmails(Array.from(uids), archiveFolder);
  },

  async handleBulkDelete() {
    const uids = Array.from(this.$refs.emailList.selectedUids);
    const trashFolder = this.folderMapping.trash || 'Trash';
    await this.bulkMoveEmails(uids, trashFolder);
  },

  async handleBulkMarkRead() {
    const uids = Array.from(this.$refs.emailList.selectedUids);
    await this.bulkSetFlags(uids, ['\\Seen'], 'add');
  },

  async handleBulkMarkUnread() {
    const uids = Array.from(this.$refs.emailList.selectedUids);
    await this.bulkSetFlags(uids, ['\\Seen'], 'remove');
  },

  async handleBulkMove(targetFolder) {
    const uids = Array.from(this.$refs.emailList.selectedUids);
    await this.bulkMoveEmails(uids, targetFolder);
  },

  async handleBulkSpam() {
    const uids = Array.from(this.$refs.emailList.selectedUids);
    const spamFolder = this.folderMapping.spam || 'Spam';
    await this.bulkMoveEmails(uids, spamFolder);
  },

  async handleBulkDeletePermanent() {
    const uids = Array.from(this.$refs.emailList.selectedUids);

    frappe.confirm(
      this.__('Supprimer définitivement {0} emails ? Cette action est irréversible.', [uids.length]),
      async () => {
        await frappe.call({
          method: 'frappe_webmail.api.delete_emails',
          args: {
            account_name: this.currentAccount,
            uids: JSON.stringify(uids),
            folder: this.currentFolder,
            permanent: true
          }
        });

        this.$refs.emailList.removeFromSelection(uids);
        this.$refs.emailList.refresh();

        frappe.toast({
          message: this.__("{0} emails supprimés", [uids.length]),
          indicator: 'green'
        });
      }
    );
  },

  async bulkMoveEmails(uids, targetFolder) {
    const fromFolder = this.currentFolder;

    await frappe.call({
      method: 'frappe_webmail.webmail_api.move_emails',
      args: {
        account_name: this.currentAccount,
        uids: JSON.stringify(uids),
        from_folder: fromFolder,
        to_folder: targetFolder
      }
    });

    // Stocker pour Undo
    this.lastBulkAction = { type: 'move', uids, fromFolder, toFolder: targetFolder };

    // Retirer de la sélection et rafraîchir
    this.$refs.emailList.removeFromSelection(uids);
    this.$refs.emailList.refresh();

    // Toast avec Undo
    frappe.toast({
      message: this.__("{0} emails déplacés", [uids.length]),
      indicator: 'green'
    });
  },

  async bulkSetFlags(uids, flags, action) {
    const args = {
      account_name: this.currentAccount,
      uids: JSON.stringify(uids),
      folder: this.currentFolder
    };

    if (action === 'add') {
      args.add_flags = JSON.stringify(flags);
    } else {
      args.remove_flags = JSON.stringify(flags);
    }

    await frappe.call({
      method: 'frappe_webmail.api.set_flags',
      args
    });

    // Mettre à jour l'affichage
    uids.forEach(uid => {
      const email = this.$refs.emailList.emails.find(e => e.uid === uid);
      if (email && flags.includes('\\Seen')) {
        email.seen = action === 'add';
      }
      if (email && flags.includes('\\Flagged')) {
        email.flagged = action === 'add';
      }
    });

    frappe.toast({
      message: this.__("{0} emails mis à jour", [uids.length]),
      indicator: 'green'
    });
  }
}
```

---

## 7. Raccourcis Clavier

| Raccourci | Action |
|-----------|--------|
| `Cmd/Ctrl+A` | Sélectionner tous les emails visibles |
| `Escape` | Désélectionner tout |
| `Delete` | Supprimer (corbeille) |
| `Shift+Delete` | Supprimer définitivement |
| `E` | Archiver |
| `V` | Ouvrir menu "Déplacer vers" |
| `Shift+U` | Toggle lu/non lu |
| `S` | Toggle étoile |

---

## 8. Fichiers à Créer/Modifier

| Fichier | Action | Description |
|---------|--------|-------------|
| `BulkActionBar.vue` | **Créer** | Barre d'actions contextuelle |
| `EmailList.vue` | Modifier | Checkboxes, sélection multiple, shift+click |
| `ContextMenu.vue` | Modifier | Support multi-sélection |
| `Webmail.vue` | Modifier | Handlers bulk, state management |
| Styles | Modifier | Classes .selected, animations |

---

## 9. Séquence d'Implémentation

### Étape 1 : Sélection Multiple
- [ ] Ajouter checkboxes visibles dans EmailList.vue
- [ ] Implémenter selectedUids (Set)
- [ ] Shift+Click pour sélection de plage
- [ ] Style .selected sur les lignes

### Étape 2 : BulkActionBar
- [ ] Créer composant BulkActionBar.vue
- [ ] Intégrer dans Webmail.vue
- [ ] Actions : Archive, Delete, Mark Read/Unread
- [ ] Dropdown "Move to" avec liste dossiers

### Étape 3 : Handlers & API
- [ ] handleBulkArchive, handleBulkDelete, etc.
- [ ] bulkMoveEmails, bulkSetFlags
- [ ] Toast notifications

### Étape 4 : Menu Contextuel Multi-sélection
- [ ] Adapter ContextMenu.vue pour mode bulk
- [ ] Header "X emails sélectionnés"
- [ ] Items adaptés (sans Reply/Forward)

### Étape 5 : Select All & Raccourcis
- [ ] Checkbox "Select All" dans toolbar
- [ ] Raccourcis clavier (Cmd+A, Escape, Delete, E, V)

### Étape 6 : Build & Test
- [ ] npm run build
- [ ] Déployer sur osiris
- [ ] Tester toutes les fonctionnalités

---

## 10. Critères de Validation

### Fonctionnel
- [ ] Checkbox cliquable sur chaque email
- [ ] Shift+Click sélectionne une plage
- [ ] Barre d'actions apparaît avec animation
- [ ] Toutes les actions bulk fonctionnent
- [ ] Menu contextuel adapté en mode bulk
- [ ] Toast après chaque action

### UX
- [ ] Feedback visuel immédiat (couleur sélection)
- [ ] Compteur animé dans la barre
- [ ] Actions clairement identifiables
- [ ] Confirmations pour actions destructives
- [ ] Responsive (mobile friendly)

### Performance
- [ ] Pas de lag avec 50+ emails sélectionnés
- [ ] Appels API groupés (pas 1 par email)
