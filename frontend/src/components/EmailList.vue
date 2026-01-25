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
      <button @click="refresh" :disabled="loading" class="refresh-btn" title="Actualiser">
        <span :class="{ rotating: loading }">&#x21bb;</span>
      </button>
      <div class="polling-status" v-if="pollingEnabled" title="Actualisation automatique active">
        <span class="polling-indicator"></span>
      </div>
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
        :class="{
          unread: !item.seen,
          selected: item.uid === selectedUid,
          flagged: item.flagged
        }"
        @click="$emit('select', item)"
      >
        <div class="checkbox" @click.stop>
          <input type="checkbox" v-model="item.checked" />
        </div>
        <div class="star" @click.stop="toggleStar(item)">
          {{ item.flagged ? '★' : '☆' }}
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
    selectedUid: { type: Number, default: null },
    pollingEnabled: { type: Boolean, default: true },
    pollingInterval: { type: Number, default: 60000 } // 60 seconds
  },

  emits: ['select', 'update:total', 'new-emails'],

  data() {
    return {
      emails: [],
      total: 0,
      loading: false,
      hasMore: true,
      searchQuery: '',
      pollingTimer: null,
      lastCheckTime: null,
      newEmailCount: 0
    }
  },

  watch: {
    account: 'onAccountOrFolderChange',
    folder: 'onAccountOrFolderChange',
    pollingEnabled(enabled) {
      if (enabled) {
        this.startPolling()
      } else {
        this.stopPolling()
      }
    }
  },

  mounted() {
    this.loadEmails()
    if (this.pollingEnabled) {
      this.startPolling()
    }
  },

  beforeUnmount() {
    this.stopPolling()
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
        return date.toLocaleTimeString('fr-FR', {
          hour: '2-digit',
          minute: '2-digit'
        })
      }

      const isThisYear = date.getFullYear() === now.getFullYear()
      if (isThisYear) {
        return date.toLocaleDateString('fr-FR', {
          day: 'numeric',
          month: 'short'
        })
      }

      return date.toLocaleDateString('fr-FR', {
        day: 'numeric',
        month: 'short',
        year: '2-digit'
      })
    },

    markAsRead(uid) {
      const email = this.emails.find((e) => e.uid === uid)
      if (email) email.seen = true
    },

    onAccountOrFolderChange() {
      this.stopPolling()
      this.refresh()
      if (this.pollingEnabled) {
        this.startPolling()
      }
    },

    startPolling() {
      this.stopPolling() // Clear any existing timer
      this.pollingTimer = setInterval(() => {
        this.checkForNewEmails()
      }, this.pollingInterval)
    },

    stopPolling() {
      if (this.pollingTimer) {
        clearInterval(this.pollingTimer)
        this.pollingTimer = null
      }
    },

    async checkForNewEmails() {
      // Don't check while loading or if no emails loaded yet
      if (this.loading || this.emails.length === 0) return

      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_emails',
          args: {
            account_name: this.account,
            folder: this.folder,
            limit: 10,
            offset: 0,
            search: null
          }
        })

        const data = response.message
        const newTotal = data.total

        // Check if there are new emails
        if (newTotal > this.total) {
          const newCount = newTotal - this.total
          this.newEmailCount = newCount

          // Find truly new emails (UIDs we don't have)
          const existingUids = new Set(this.emails.map(e => e.uid))
          const newEmails = data.emails.filter(e => !existingUids.has(e.uid))

          if (newEmails.length > 0) {
            // Prepend new emails to the list
            this.emails.unshift(...newEmails)
            this.total = newTotal

            this.$emit('update:total', this.total)
            this.$emit('new-emails', {
              count: newEmails.length,
              emails: newEmails
            })

            // Show notification
            this.showNewEmailNotification(newEmails)
          }
        } else if (newTotal < this.total) {
          // Emails were deleted, refresh the list
          this.total = newTotal
          this.$emit('update:total', this.total)
        }
      } catch (error) {
        console.error('Polling error:', error)
      }
    },

    showNewEmailNotification(newEmails) {
      if (newEmails.length === 1) {
        const email = newEmails[0]
        frappe.toast({
          message: `Nouveau message de ${email.from_name || email.from_email}`,
          indicator: 'blue'
        })
      } else {
        frappe.toast({
          message: `${newEmails.length} nouveaux messages`,
          indicator: 'blue'
        })
      }

      // Play notification sound if available
      this.playNotificationSound()
    },

    playNotificationSound() {
      try {
        // Create a simple notification sound using Web Audio API
        const audioContext = new (window.AudioContext || window.webkitAudioContext)()
        const oscillator = audioContext.createOscillator()
        const gainNode = audioContext.createGain()

        oscillator.connect(gainNode)
        gainNode.connect(audioContext.destination)

        oscillator.frequency.value = 800
        oscillator.type = 'sine'
        gainNode.gain.value = 0.1

        oscillator.start()
        oscillator.stop(audioContext.currentTime + 0.1)
      } catch (e) {
        // Audio not supported or blocked
      }
    }
  }
}
</script>

<style scoped>
.email-list-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
}

.list-toolbar {
  display: flex;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.list-toolbar input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  outline: none;
}

.list-toolbar input:focus {
  border-color: var(--primary-color, #2490ef);
}

.refresh-btn {
  padding: 6px 10px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  background: white;
  cursor: pointer;
  font-size: 16px;
}

.refresh-btn:hover {
  background: var(--bg-light-gray, #f5f5f5);
}

.refresh-btn .rotating {
  display: inline-block;
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.email-list {
  flex: 1;
  overflow-y: auto;
}

.email-row {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
  cursor: pointer;
  gap: 12px;
}

.email-row:hover {
  background: var(--bg-light-gray, #f5f5f5);
}

.email-row.unread {
  font-weight: 600;
  background: #f0f7ff;
}

.email-row.selected {
  background: var(--primary-light, #e3f2fd);
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
  color: #999;
}

.star:hover {
  color: #f5a623;
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
  min-width: 55px;
  flex-shrink: 0;
  text-align: right;
  font-size: 12px;
  color: var(--text-muted, #8d99a6);
  white-space: nowrap;
}

.empty-state,
.loading-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted, #8d99a6);
}

.polling-status {
  display: flex;
  align-items: center;
  padding: 0 8px;
}

.polling-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #28a745;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

/* Responsive Design */
@media (max-width: 768px) {
  .email-row {
    padding: 10px 12px;
    gap: 8px;
  }

  .from {
    width: 120px;
    font-size: 13px;
  }

  .subject {
    font-size: 13px;
  }

  .date {
    font-size: 11px;
    min-width: 50px;
  }

  .checkbox {
    display: none;
  }
}

@media (max-width: 480px) {
  .email-row {
    flex-wrap: wrap;
    padding: 10px;
    gap: 4px;
  }

  .star {
    order: 1;
    font-size: 14px;
  }

  .from {
    order: 2;
    width: auto;
    flex: 1;
    font-size: 13px;
    font-weight: 600;
  }

  .date {
    order: 3;
    font-size: 11px;
    min-width: auto;
  }

  .subject {
    order: 4;
    width: 100%;
    flex-basis: 100%;
    font-size: 12px;
    color: var(--text-muted, #8d99a6);
    padding-left: 22px;
    margin-top: 2px;
  }

  .email-row.unread .subject {
    color: var(--text-color, #333);
  }

  .checkbox {
    display: none;
  }
}
</style>
