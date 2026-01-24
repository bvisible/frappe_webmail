<template>
  <div class="email-viewer" v-if="email">
    <!-- Header -->
    <div class="email-header">
      <div class="email-subject">{{ email.subject || '(Sans objet)' }}</div>
      <div class="email-meta">
        <div class="from">
          <div class="from-info">
            <strong>{{ email.from_name || email.from_email }}</strong>
            <span class="email-address">&lt;{{ email.from_email }}&gt;</span>
            <span
              v-if="senderContact"
              class="contact-badge"
              :title="'Contact: ' + senderContact.full_name"
            >
              👤
            </span>
            <button
              v-else
              @click="saveAsContact(email.from_email, email.from_name)"
              class="add-contact-btn"
              title="Ajouter aux contacts"
            >
              + 👤
            </button>
          </div>
        </div>
        <div class="to">A: {{ email.to }}</div>
        <div v-if="email.cc" class="cc">Cc: {{ email.cc }}</div>
        <div class="date">{{ formatDate(email.date) }}</div>
      </div>
    </div>

    <!-- Actions -->
    <div class="email-actions">
      <button @click="$emit('reply', email)" class="btn btn-sm">
        ↩️ Repondre
      </button>
      <button @click="$emit('forward', email)" class="btn btn-sm">
        ↪️ Transferer
      </button>
      <button @click="toggleStar" class="btn btn-sm">
        {{ email.flagged ? '★' : '☆' }}
      </button>
      <button @click="$emit('delete', email)" class="btn btn-sm btn-danger">
        🗑️
      </button>
    </div>

    <!-- External images warning -->
    <div v-if="hasBlockedImages" class="blocked-images-notice">
      ⚠️ Les images externes ont ete bloquees pour votre securite.
      <button @click="showExternalImages = true">Afficher les images</button>
    </div>

    <!-- Body (sandboxed iframe) -->
    <iframe
      ref="emailFrame"
      class="email-body"
      sandbox="allow-popups allow-popups-to-escape-sandbox"
      referrerpolicy="no-referrer"
      :srcdoc="sanitizedContent"
    />

    <!-- Attachments -->
    <div v-if="email.attachments?.length" class="email-attachments">
      <h4>📎 Pieces jointes ({{ email.attachments.length }})</h4>
      <div class="attachment-list">
        <div
          v-for="att in email.attachments"
          :key="att.id"
          class="attachment-item"
          @click="downloadAttachment(att)"
        >
          <span class="icon">{{ getFileIcon(att.content_type) }}</span>
          <span class="name">{{ att.filename }}</span>
          <span class="size">({{ formatSize(att.size) }})</span>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="no-email-selected">
    <p>Selectionnez un email pour le lire</p>
  </div>
</template>

<script>
import DOMPurify from 'dompurify'

export default {
  name: 'EmailViewer',

  props: {
    email: { type: Object, default: null },
    account: { type: String, required: true },
    folder: { type: String, default: 'INBOX' }
  },

  emits: ['reply', 'forward', 'delete', 'flag-changed'],

  data() {
    return {
      showExternalImages: false,
      hasBlockedImages: false,
      senderContact: null
    }
  },

  watch: {
    'email.from_email': {
      immediate: true,
      handler(email) {
        if (email) {
          this.loadSenderContact(email)
        } else {
          this.senderContact = null
        }
      }
    }
  },

  computed: {
    sanitizedContent() {
      if (!this.email) return ''

      const content =
        this.email.html || this.wrapPlainText(this.email.text)
      if (!content) return ''

      // Configure DOMPurify
      const config = {
        WHOLE_DOCUMENT: true,
        FORBID_TAGS: [
          'script',
          'style',
          'audio',
          'video',
          'form',
          'input',
          'button',
          'textarea',
          'object',
          'embed'
        ],
        FORBID_ATTR: [
          'onerror',
          'onload',
          'onclick',
          'onmouseover',
          'onfocus',
          'onblur',
          'onsubmit'
        ],
        ALLOW_DATA_ATTR: false
      }

      // Hook to handle external images
      this.hasBlockedImages = false
      const self = this

      DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        // Block external images unless allowed
        if (node.tagName === 'IMG' && !self.showExternalImages) {
          const src = node.getAttribute('src')
          if (src && !src.startsWith('data:') && !src.startsWith('cid:')) {
            node.setAttribute('data-blocked-src', src)
            node.setAttribute(
              'src',
              'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" fill="gray" font-size="12">[Image bloquee]</text></svg>'
            )
            node.style.cursor = 'pointer'
            node.title = 'Image externe bloquee'
            self.hasBlockedImages = true
          }
        }

        // Open links in new tab
        if (node.tagName === 'A') {
          node.setAttribute('target', '_blank')
          node.setAttribute('rel', 'noopener noreferrer')
        }
      })

      const clean = DOMPurify.sanitize(content, config)

      // Remove hook to avoid affecting other sanitizations
      DOMPurify.removeHook('afterSanitizeAttributes')

      // Wrap in HTML document with base styles
      return `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            * { box-sizing: border-box; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
              font-size: 14px;
              line-height: 1.6;
              color: #333;
              margin: 0;
              padding: 16px;
              word-wrap: break-word;
            }
            img { max-width: 100%; height: auto; }
            a { color: #0066cc; }
            blockquote {
              border-left: 3px solid #ccc;
              margin: 10px 0;
              padding-left: 15px;
              color: #666;
            }
            pre, code {
              background: #f5f5f5;
              padding: 2px 6px;
              border-radius: 3px;
              font-size: 13px;
            }
            pre { padding: 10px; overflow-x: auto; }
            table { border-collapse: collapse; max-width: 100%; }
            td, th { border: 1px solid #ddd; padding: 8px; }
          </style>
        </head>
        <body>${clean}</body>
        </html>
      `
    }
  },

  watch: {
    email() {
      this.showExternalImages = false
      this.hasBlockedImages = false
    }
  },

  methods: {
    wrapPlainText(text) {
      if (!text) return ''
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>')
      return `<pre style="white-space: pre-wrap; font-family: inherit;">${escaped}</pre>`
    },

    formatDate(dateStr) {
      if (!dateStr) return ''
      return new Date(dateStr).toLocaleString('fr-FR', {
        dateStyle: 'full',
        timeStyle: 'short'
      })
    },

    formatSize(bytes) {
      if (!bytes) return '0 B'
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    },

    getFileIcon(contentType) {
      if (!contentType) return '📄'
      if (contentType.startsWith('image/')) return '🖼️'
      if (contentType.startsWith('video/')) return '🎬'
      if (contentType.startsWith('audio/')) return '🎵'
      if (contentType.includes('pdf')) return '📕'
      if (contentType.includes('word') || contentType.includes('document'))
        return '📘'
      if (contentType.includes('sheet') || contentType.includes('excel'))
        return '📗'
      if (contentType.includes('zip') || contentType.includes('archive'))
        return '📦'
      return '📄'
    },

    async toggleStar() {
      const action = this.email.flagged ? 'remove_flags' : 'add_flags'
      const flags = ['\\Flagged']

      try {
        await frappe.call({
          method: 'frappe_webmail.api.set_flags',
          args: {
            account_name: this.account,
            uids: JSON.stringify([this.email.uid]),
            folder: this.folder,
            [action]: JSON.stringify(flags)
          }
        })

        this.email.flagged = !this.email.flagged
        this.$emit('flag-changed', this.email)
      } catch (error) {
        frappe.toast({ message: 'Erreur', indicator: 'red' })
      }
    },

    async downloadAttachment(attachment) {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_attachment',
          args: {
            account_name: this.account,
            uid: this.email.uid,
            folder: this.folder,
            attachment_id: attachment.id
          }
        })

        const data = response.message
        const byteCharacters = atob(data.data)
        const byteNumbers = new Array(byteCharacters.length)
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i)
        }
        const byteArray = new Uint8Array(byteNumbers)
        const blob = new Blob([byteArray], { type: data.content_type })

        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = data.filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      } catch (error) {
        frappe.toast({ message: 'Erreur de telechargement', indicator: 'red' })
      }
    },

    async loadSenderContact(email) {
      if (!email) {
        this.senderContact = null
        return
      }

      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_contact_by_email',
          args: { email }
        })
        this.senderContact = response.message
      } catch (error) {
        this.senderContact = null
      }
    },

    async saveAsContact(email, name) {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.create_contact_from_email',
          args: { email, name }
        })

        if (response.message.success) {
          frappe.toast({
            message: `Contact cree: ${response.message.full_name}`,
            indicator: 'green'
          })
          this.loadSenderContact(email)
        } else {
          frappe.toast({
            message: response.message.message,
            indicator: 'orange'
          })
          // Load existing contact
          this.loadSenderContact(email)
        }
      } catch (error) {
        frappe.toast({ message: 'Erreur lors de la creation du contact', indicator: 'red' })
      }
    }
  }
}
</script>

<style scoped>
.email-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
}

.no-email-selected {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted, #8d99a6);
}

.email-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.email-subject {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 12px;
}

.email-meta {
  font-size: 13px;
  color: var(--text-muted, #8d99a6);
}

.email-meta .from {
  color: var(--text-color, #333);
  margin-bottom: 4px;
}

.email-meta .email-address {
  color: var(--text-muted, #8d99a6);
  font-weight: normal;
}

.email-actions {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
  background: var(--bg-light-gray, #f5f5f5);
}

.email-actions .btn {
  padding: 4px 12px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  background: white;
  cursor: pointer;
  font-size: 13px;
}

.email-actions .btn:hover {
  background: var(--bg-gray, #eee);
}

.email-actions .btn-danger:hover {
  background: #fee;
  border-color: #fcc;
}

.blocked-images-notice {
  padding: 8px 16px;
  background: #fff3cd;
  border-bottom: 1px solid #ffc107;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.blocked-images-notice button {
  background: none;
  border: none;
  color: #0066cc;
  cursor: pointer;
  text-decoration: underline;
}

.email-body {
  flex: 1;
  border: none;
  width: 100%;
}

.email-attachments {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #e5e5e5);
  background: var(--bg-light-gray, #f5f5f5);
}

.email-attachments h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
}

.attachment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attachment-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: white;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.attachment-item:hover {
  background: var(--bg-gray, #eee);
}

.attachment-item .size {
  color: var(--text-muted, #8d99a6);
}

.from-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.contact-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: var(--primary-light, #e3f2fd);
  padding: 2px 6px;
  border-radius: 4px;
  cursor: help;
}

.add-contact-btn {
  background: none;
  border: 1px dashed var(--border-color, #ccc);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  cursor: pointer;
  color: var(--text-muted, #8d99a6);
  transition: all 0.2s;
}

.add-contact-btn:hover {
  background: var(--primary-light, #e3f2fd);
  border-color: var(--primary-color, #2490ef);
  color: var(--primary-color, #2490ef);
}
</style>
