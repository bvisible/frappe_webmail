<template>
  <div class="webmail-container">
    <!-- Header -->
    <div class="webmail-header">
      <div class="header-left">
        <h1>📧 Webmail</h1>
        <select v-model="currentAccount" class="account-selector" @change="onAccountChange">
          <option v-for="acc in accounts" :key="acc.name" :value="acc.name">
            {{ acc.email }}
          </option>
        </select>
      </div>
      <div class="header-right">
        <button @click="showSearch = true" class="btn btn-secondary">
          🔍 Recherche
        </button>
        <button @click="compose" class="btn btn-primary">
          ✉️ Nouveau message
        </button>
        <button @click="showFilters = true" class="btn btn-secondary">
          🗂️ Filtres
        </button>
        <button @click="showSignatures = true" class="btn btn-secondary">
          ✍️ Signatures
        </button>
        <button @click="openSettings" class="btn btn-secondary">
          ⚙️ Parametres
        </button>
      </div>
    </div>

    <!-- Main Content -->
    <div class="webmail-main" v-if="accounts.length">
      <!-- Folder Sidebar -->
      <div class="sidebar">
        <FolderTree
          :account="currentAccount"
          :account-email="currentAccountEmail"
          :selected-folder="currentFolder"
          @select="onFolderSelect"
        />
      </div>

      <!-- Email List -->
      <div class="email-list-panel">
        <EmailList
          ref="emailList"
          :account="currentAccount"
          :folder="currentFolder"
          :selected-uid="selectedEmail?.uid"
          :polling-enabled="pollingEnabled"
          :polling-interval="pollingInterval"
          @select="onEmailSelect"
          @update:total="totalEmails = $event"
          @new-emails="onNewEmails"
        />
      </div>

      <!-- Email Viewer -->
      <div class="email-viewer-panel">
        <EmailViewer
          v-if="!showComposer"
          :email="selectedEmailContent"
          :account="currentAccount"
          :folder="currentFolder"
          @reply="replyTo"
          @forward="forwardEmail"
          @delete="deleteEmail"
          @flag-changed="onFlagChanged"
          @mark-unread="onMarkUnread"
        />

        <EmailComposer
          v-else
          :account="currentAccount"
          :reply-to="replyToEmail"
          :forward-email="forwardingEmail"
          :signature="defaultSignature"
          :folder="currentFolder"
          @sent="onEmailSent"
          @close="closeComposer"
        />
      </div>
    </div>

    <!-- No Accounts State -->
    <div class="no-accounts" v-else-if="!loading">
      <div class="no-accounts-content">
        <h2>Bienvenue dans Webmail</h2>
        <p>Vous n'avez pas encore configure de compte email.</p>
        <button @click="openSettings" class="btn btn-primary">
          Configurer un compte
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div class="loading-overlay" v-if="loading">
      <div class="spinner"></div>
      <p>Chargement...</p>
    </div>

    <!-- Signature Editor Modal -->
    <div class="modal-overlay" v-if="showSignatures" @click.self="showSignatures = false">
      <div class="modal-content signature-modal">
        <SignatureEditor
          @close="showSignatures = false"
          @updated="loadDefaultSignature"
        />
      </div>
    </div>

    <!-- Advanced Search Modal -->
    <div class="modal-overlay" v-if="showSearch" @click.self="showSearch = false">
      <div class="modal-content search-modal">
        <AdvancedSearch
          :account="currentAccount"
          :folders="folders"
          :initial-folder="currentFolder"
          @close="showSearch = false"
          @select="onSearchSelect"
        />
      </div>
    </div>

    <!-- Filter Manager Modal -->
    <div class="modal-overlay" v-if="showFilters" @click.self="showFilters = false">
      <div class="modal-content filter-modal">
        <FilterManager
          :account="currentAccount"
          :folders="folders"
          @close="showFilters = false"
        />
      </div>
    </div>
  </div>
</template>

<script>
import FolderTree from '../components/FolderTree.vue'
import EmailList from '../components/EmailList.vue'
import EmailViewer from '../components/EmailViewer.vue'
import EmailComposer from '../components/EmailComposer.vue'
import SignatureEditor from '../components/SignatureEditor.vue'
import AdvancedSearch from '../components/AdvancedSearch.vue'
import FilterManager from '../components/FilterManager.vue'

export default {
  name: 'Webmail',

  components: {
    FolderTree,
    EmailList,
    EmailViewer,
    EmailComposer,
    SignatureEditor,
    AdvancedSearch,
    FilterManager
  },

  data() {
    return {
      loading: true,
      accounts: [],
      currentAccount: '',
      currentFolder: 'INBOX',
      selectedEmail: null,
      selectedEmailContent: null,
      totalEmails: 0,
      showComposer: false,
      replyToEmail: null,
      forwardingEmail: null,
      defaultSignature: '',
      showSignatures: false,
      pollingEnabled: true,
      pollingInterval: 60000, // 60 seconds
      unreadCount: 0,
      showSearch: false,
      showFilters: false,
      folders: []
    }
  },

  computed: {
    currentAccountEmail() {
      const acc = this.accounts.find((a) => a.name === this.currentAccount)
      return acc?.email || ''
    }
  },

  mounted() {
    this.initialize()
  },

  methods: {
    async initialize() {
      this.loading = true

      try {
        await this.loadAccounts()
        await this.loadDefaultSignature()
      } catch (error) {
        console.error('Initialization error:', error)
      } finally {
        this.loading = false
      }
    },

    async loadAccounts() {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_accounts'
        })

        this.accounts = response.message || []

        if (this.accounts.length && !this.currentAccount) {
          this.currentAccount = this.accounts[0].name
          // Load folders for search
          this.loadFolders()
        }
      } catch (error) {
        frappe.toast({ message: 'Erreur de chargement des comptes', indicator: 'red' })
      }
    },

    async loadFolders() {
      if (!this.currentAccount) return

      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_folders',
          args: { account_name: this.currentAccount }
        })
        this.folders = (response.message || []).filter(f => f.selectable)
      } catch (error) {
        console.error('Error loading folders:', error)
      }
    },

    async loadDefaultSignature() {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_default_signature'
        })
        this.defaultSignature = response.message || ''
      } catch (error) {
        console.error('Error loading signature:', error)
      }
    },

    onAccountChange() {
      this.currentFolder = 'INBOX'
      this.selectedEmail = null
      this.selectedEmailContent = null
      this.loadFolders()
    },

    onFolderSelect(folder) {
      this.currentFolder = folder
      this.selectedEmail = null
      this.selectedEmailContent = null
    },

    async onEmailSelect(email) {
      this.selectedEmail = email
      this.showComposer = false

      // Mark as read in list
      if (this.$refs.emailList) {
        this.$refs.emailList.markAsRead(email.uid)
      }

      // Load full content
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_email_content',
          args: {
            account_name: this.currentAccount,
            uid: email.uid,
            folder: this.currentFolder,
            mark_read: true
          }
        })

        this.selectedEmailContent = response.message
      } catch (error) {
        frappe.toast({ message: 'Erreur de chargement de l\'email', indicator: 'red' })
      }
    },

    compose() {
      this.showComposer = true
      this.replyToEmail = null
      this.forwardingEmail = null
    },

    replyTo(email) {
      this.showComposer = true
      this.replyToEmail = email
      this.forwardingEmail = null
    },

    forwardEmail(email) {
      this.showComposer = true
      this.forwardingEmail = email
      this.replyToEmail = null
    },

    closeComposer() {
      this.showComposer = false
      this.replyToEmail = null
      this.forwardingEmail = null
    },

    onEmailSent() {
      this.closeComposer()
      // Optionally refresh sent folder
    },

    async deleteEmail(email) {
      if (!confirm('Voulez-vous vraiment supprimer cet email ?')) return

      try {
        await frappe.call({
          method: 'frappe_webmail.api.delete_emails',
          args: {
            account_name: this.currentAccount,
            uids: JSON.stringify([email.uid]),
            folder: this.currentFolder,
            permanent: false
          }
        })

        frappe.toast({ message: 'Email supprime', indicator: 'green' })

        // Refresh list
        if (this.$refs.emailList) {
          this.$refs.emailList.refresh()
        }

        this.selectedEmail = null
        this.selectedEmailContent = null
      } catch (error) {
        frappe.toast({ message: 'Erreur de suppression', indicator: 'red' })
      }
    },

    onFlagChanged(email) {
      // Update in list if needed
      if (this.$refs.emailList) {
        const listEmail = this.$refs.emailList.emails.find((e) => e.uid === email.uid)
        if (listEmail) {
          listEmail.flagged = email.flagged
        }
      }
    },

    onMarkUnread(email) {
      // Update in list to show as unread
      if (this.$refs.emailList) {
        const listEmail = this.$refs.emailList.emails.find((e) => e.uid === email.uid)
        if (listEmail) {
          listEmail.seen = false
        }
      }
    },

    openSettings() {
      // Open Webmail Account list
      frappe.set_route('List', 'Webmail Account')
    },

    onNewEmails({ count, emails }) {
      // Update document title with unread count
      this.unreadCount += count
      this.updateDocumentTitle()

      // Could also trigger browser notification if permission granted
      this.requestNotificationPermission()
    },

    updateDocumentTitle() {
      const baseTitle = 'Webmail'
      if (this.unreadCount > 0) {
        document.title = `(${this.unreadCount}) ${baseTitle}`
      } else {
        document.title = baseTitle
      }
    },

    async requestNotificationPermission() {
      if (!('Notification' in window)) return

      if (Notification.permission === 'default') {
        await Notification.requestPermission()
      }
    },

    togglePolling() {
      this.pollingEnabled = !this.pollingEnabled
    },

    async onSearchSelect({ email, folder }) {
      // Switch to the folder if different
      if (folder !== this.currentFolder) {
        this.currentFolder = folder
      }

      // Close search modal
      this.showSearch = false

      // Load the email content
      this.selectedEmail = email
      this.showComposer = false

      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_email_content',
          args: {
            account_name: this.currentAccount,
            uid: email.uid,
            folder: folder,
            mark_read: true
          }
        })

        this.selectedEmailContent = response.message
      } catch (error) {
        frappe.toast({ message: 'Erreur de chargement', indicator: 'red' })
      }
    }
  }
}
</script>

<style scoped>
.webmail-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-color, #f5f5f5);
}

.webmail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: white;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-left h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.account-selector {
  padding: 6px 12px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  background: white;
  font-size: 14px;
  min-width: 200px;
}

.header-right {
  display: flex;
  gap: 8px;
}

.header-right .btn {
  padding: 8px 16px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  background: white;
}

.header-right .btn-primary {
  background: var(--primary-color, #2490ef);
  color: white;
  border-color: var(--primary-color, #2490ef);
}

.header-right .btn-primary:hover {
  background: #1a7fd4;
}

.header-right .btn-secondary:hover {
  background: var(--bg-light-gray, #f5f5f5);
}

.webmail-main {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: white;
  overflow-y: auto;
  border-top: 1px solid var(--border-color, #e5e5e5);
}

.email-list-panel {
  width: 350px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-color, #e5e5e5);
  border-top: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0 var(--border-radius-lg) 0 0;
  overflow: hidden;
}

.email-viewer-panel {
  flex: 1;
  overflow: hidden;
  background: white;
  border-radius: var(--border-radius-lg);
  border: 1px solid var(--border-color);
  margin: 0 10px;
}

.no-accounts {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.no-accounts-content {
  text-align: center;
  padding: 40px;
}

.no-accounts-content h2 {
  margin: 0 0 16px 0;
}

.no-accounts-content p {
  margin: 0 0 24px 0;
  color: var(--text-muted, #8d99a6);
}

.no-accounts-content .btn {
  padding: 12px 24px;
  background: var(--primary-color, #2490ef);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color, #e5e5e5);
  border-top-color: var(--primary-color, #2490ef);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.signature-modal {
  width: 800px;
  height: 600px;
  max-width: 90vw;
  max-height: 80vh;
}


.search-modal {
  width: 600px;
  height: 80vh;
  max-width: 90vw;
  max-height: 80vh;
  overflow: hidden;
}

.filter-modal {
  width: 550px;
  height: 70vh;
  max-width: 90vw;
  max-height: 80vh;
  overflow: hidden;
}
</style>
