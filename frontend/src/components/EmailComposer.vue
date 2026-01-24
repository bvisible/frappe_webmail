<template>
  <div class="email-composer">
    <!-- Recipients -->
    <div class="composer-field">
      <label>A:</label>
      <input
        v-model="emailData.to"
        type="text"
        placeholder="destinataire@example.com"
      />
    </div>
    <div class="composer-field">
      <label>Cc:</label>
      <input v-model="emailData.cc" type="text" placeholder="Copie carbone" />
    </div>
    <div class="composer-field">
      <label>Objet:</label>
      <input
        v-model="emailData.subject"
        type="text"
        placeholder="Objet du message"
      />
    </div>

    <!-- Toolbar -->
    <div class="editor-toolbar" v-if="editor">
      <button
        @click="editor.chain().focus().toggleBold().run()"
        :class="{ active: editor.isActive('bold') }"
        title="Gras"
      >
        <strong>B</strong>
      </button>
      <button
        @click="editor.chain().focus().toggleItalic().run()"
        :class="{ active: editor.isActive('italic') }"
        title="Italique"
      >
        <em>I</em>
      </button>
      <button
        @click="editor.chain().focus().toggleUnderline().run()"
        :class="{ active: editor.isActive('underline') }"
        title="Souligne"
      >
        <u>U</u>
      </button>
      <span class="separator"></span>
      <button
        @click="editor.chain().focus().toggleBulletList().run()"
        :class="{ active: editor.isActive('bulletList') }"
        title="Liste a puces"
      >
        •
      </button>
      <button
        @click="editor.chain().focus().toggleOrderedList().run()"
        :class="{ active: editor.isActive('orderedList') }"
        title="Liste numerotee"
      >
        1.
      </button>
      <span class="separator"></span>
      <button @click="insertLink" title="Lien">🔗</button>
      <button @click="insertImage" title="Image">🖼️</button>
      <span class="separator"></span>
      <button @click="insertSignature" title="Signature">✍️</button>
    </div>

    <!-- Editor -->
    <div class="editor-container">
      <editor-content :editor="editor" />
    </div>

    <!-- Attachments -->
    <div class="attachments-section" v-if="attachments.length">
      <div
        v-for="(file, idx) in attachments"
        :key="idx"
        class="attachment-chip"
      >
        <span>{{ file.name }}</span>
        <span class="size">({{ formatSize(file.size) }})</span>
        <button @click="removeAttachment(idx)" class="remove">x</button>
      </div>
    </div>

    <!-- Actions -->
    <div class="composer-actions">
      <div class="draft-status" v-if="lastSaved || isSavingDraft">
        <span v-if="isSavingDraft" class="saving">Sauvegarde...</span>
        <span v-else-if="lastSaved" class="saved">
          Sauvegarde a {{ formatLastSaved() }}
        </span>
      </div>
      <div class="action-buttons">
        <input
          type="file"
          ref="fileInput"
          multiple
          @change="handleFiles"
          style="display: none"
        />
        <button class="btn btn-secondary" @click="$refs.fileInput.click()">
          📎 Joindre
        </button>
        <button class="btn btn-secondary" @click="saveDraft" :disabled="isSavingDraft">
          💾 Brouillon
        </button>
        <button class="btn btn-primary" @click="send" :disabled="sending">
          {{ sending ? 'Envoi...' : '📤 Envoyer' }}
        </button>
        <button class="btn btn-danger-light" @click="discardDraft" v-if="currentDraftId">
          🗑️ Supprimer
        </button>
        <button class="btn btn-light" @click="$emit('close')">Annuler</button>
      </div>
    </div>
  </div>
</template>

<script>
import { Editor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'

export default {
  name: 'EmailComposer',
  components: { EditorContent },

  props: {
    account: { type: String, required: true },
    replyTo: { type: Object, default: null },
    forwardEmail: { type: Object, default: null },
    signature: { type: String, default: '' },
    draftId: { type: String, default: null },
    folder: { type: String, default: 'INBOX' }
  },

  emits: ['sent', 'close', 'draft-saved'],

  data() {
    return {
      editor: null,
      emailData: {
        to: '',
        cc: '',
        bcc: '',
        subject: ''
      },
      attachments: [],
      sending: false,
      currentDraftId: null,
      lastSaved: null,
      autoSaveTimer: null,
      autoSaveDelay: 3000, // 3 seconds debounce
      isDirty: false,
      isSavingDraft: false
    }
  },

  mounted() {
    this.currentDraftId = this.draftId
    this.initEditor()

    if (this.draftId) {
      this.loadDraft()
    } else if (this.replyTo) {
      this.setupReply()
    } else if (this.forwardEmail) {
      this.setupForward()
    }
  },

  beforeUnmount() {
    // Clear auto-save timer
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer)
    }

    // Save draft before closing if dirty
    if (this.isDirty && !this.sending) {
      this.saveDraftNow()
    }

    if (this.editor) {
      this.editor.destroy()
    }
  },

  watch: {
    'emailData.to'() {
      this.scheduleAutoSave()
    },
    'emailData.cc'() {
      this.scheduleAutoSave()
    },
    'emailData.bcc'() {
      this.scheduleAutoSave()
    },
    'emailData.subject'() {
      this.scheduleAutoSave()
    }
  },

  methods: {
    initEditor() {
      let initialContent = ''

      if (this.signature) {
        initialContent = `<p></p><br><p>--</p>${this.signature}`
      }

      this.editor = new Editor({
        content: initialContent,
        extensions: [
          StarterKit,
          Underline,
          Link.configure({ openOnClick: false }),
          Image.configure({ inline: true }),
          Placeholder.configure({
            placeholder: 'Ecrivez votre message...'
          })
        ],
        onUpdate: () => {
          this.scheduleAutoSave()
        }
      })
    },

    async loadDraft() {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_draft',
          args: { draft_id: this.draftId }
        })

        const draft = response.message
        this.emailData.to = draft.to || ''
        this.emailData.cc = draft.cc || ''
        this.emailData.bcc = draft.bcc || ''
        this.emailData.subject = draft.subject || ''

        if (draft.html_content) {
          this.editor.commands.setContent(draft.html_content)
        }

        if (draft.attachments_json) {
          // Note: We can't restore File objects, but we store metadata
          // User will need to re-attach files
        }

        this.lastSaved = draft.last_saved
        this.isDirty = false
      } catch (error) {
        console.error('Failed to load draft:', error)
      }
    },

    scheduleAutoSave() {
      this.isDirty = true

      // Clear existing timer
      if (this.autoSaveTimer) {
        clearTimeout(this.autoSaveTimer)
      }

      // Schedule new save
      this.autoSaveTimer = setTimeout(() => {
        this.saveDraftNow()
      }, this.autoSaveDelay)
    },

    async saveDraftNow() {
      if (this.isSavingDraft || this.sending) return

      // Don't save empty drafts
      const hasContent =
        this.emailData.to ||
        this.emailData.subject ||
        (this.editor && this.editor.getText().trim())

      if (!hasContent) return

      this.isSavingDraft = true

      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.save_draft',
          args: {
            account_name: this.account,
            to: this.emailData.to,
            cc: this.emailData.cc,
            bcc: this.emailData.bcc,
            subject: this.emailData.subject,
            html_content: this.editor ? this.editor.getHTML() : '',
            reply_to_message_id: this.replyTo?.message_id || null,
            reply_to_uid: this.replyTo?.uid || null,
            reply_to_folder: this.replyTo ? this.folder : null,
            forward_uid: this.forwardEmail?.uid || null,
            forward_folder: this.forwardEmail ? this.folder : null,
            draft_id: this.currentDraftId
          }
        })

        this.currentDraftId = response.message.draft_id
        this.lastSaved = response.message.last_saved
        this.isDirty = false
        this.$emit('draft-saved', this.currentDraftId)
      } catch (error) {
        console.error('Auto-save failed:', error)
      } finally {
        this.isSavingDraft = false
      }
    },

    setupReply() {
      const reply = this.replyTo
      this.emailData.to = reply.from_email
      this.emailData.subject = reply.subject.startsWith('Re:')
        ? reply.subject
        : `Re: ${reply.subject}`

      const date = new Date(reply.date).toLocaleString('fr-FR')
      const quoteContent = `
        <br><br>
        <p>Le ${date}, ${reply.from_name || reply.from_email} a ecrit :</p>
        <blockquote style="border-left: 2px solid #ccc; padding-left: 10px; margin-left: 0; color: #666;">
          ${reply.html || reply.text || ''}
        </blockquote>
      `

      let content = '<p></p>'
      if (this.signature) {
        content += `<br><p>--</p>${this.signature}`
      }
      content += quoteContent

      this.editor.commands.setContent(content)
      this.editor.commands.focus('start')
    },

    setupForward() {
      const fwd = this.forwardEmail
      this.emailData.subject = fwd.subject.startsWith('Fwd:')
        ? fwd.subject
        : `Fwd: ${fwd.subject}`

      const date = new Date(fwd.date).toLocaleString('fr-FR')
      const forwardContent = `
        <br><br>
        <p>---------- Message transfere ----------</p>
        <p>De: ${fwd.from_name || fwd.from_email} &lt;${fwd.from_email}&gt;</p>
        <p>Date: ${date}</p>
        <p>Objet: ${fwd.subject}</p>
        <p>A: ${fwd.to}</p>
        <br>
        ${fwd.html || fwd.text || ''}
      `

      let content = '<p></p>'
      if (this.signature) {
        content += `<br><p>--</p>${this.signature}`
      }
      content += forwardContent

      this.editor.commands.setContent(content)
      this.editor.commands.focus('start')
    },

    insertSignature() {
      if (this.signature) {
        this.editor
          .chain()
          .focus()
          .insertContent(`<br><p>--</p>${this.signature}`)
          .run()
      }
    },

    insertLink() {
      const url = prompt('URL du lien:')
      if (url) {
        this.editor.chain().focus().setLink({ href: url }).run()
      }
    },

    insertImage() {
      const url = prompt("URL de l'image:")
      if (url) {
        this.editor.chain().focus().setImage({ src: url }).run()
      }
    },

    handleFiles(event) {
      const files = Array.from(event.target.files)
      this.attachments.push(...files)
    },

    removeAttachment(index) {
      this.attachments.splice(index, 1)
    },

    formatSize(bytes) {
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    },

    async prepareAttachments() {
      const result = []
      for (const file of this.attachments) {
        const data = await this.fileToBase64(file)
        result.push({
          filename: file.name,
          content_type: file.type,
          data: data
        })
      }
      return result
    },

    fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => {
          const base64 = reader.result.split(',')[1]
          resolve(base64)
        }
        reader.onerror = reject
        reader.readAsDataURL(file)
      })
    },

    async send() {
      if (!this.emailData.to) {
        frappe.toast({
          message: 'Veuillez saisir un destinataire',
          indicator: 'red'
        })
        return
      }

      this.sending = true

      try {
        const attachments = await this.prepareAttachments()

        await frappe.call({
          method: 'frappe_webmail.api.send_email',
          args: {
            account_name: this.account,
            to: this.emailData.to,
            cc: this.emailData.cc || null,
            subject: this.emailData.subject,
            html_content: this.editor.getHTML(),
            reply_to_message_id: this.replyTo?.message_id || null,
            attachments: attachments.length ? JSON.stringify(attachments) : null
          }
        })

        // Delete draft after successful send
        if (this.currentDraftId) {
          try {
            await frappe.call({
              method: 'frappe_webmail.api.delete_draft',
              args: { draft_id: this.currentDraftId }
            })
          } catch (e) {
            console.warn('Failed to delete draft:', e)
          }
        }

        frappe.toast({ message: 'Email envoye !', indicator: 'green' })
        this.isDirty = false // Prevent save on unmount
        this.$emit('sent')
        this.$emit('close')
      } catch (error) {
        frappe.toast({
          message: error.message || "Erreur d'envoi",
          indicator: 'red'
        })
      } finally {
        this.sending = false
      }
    },

    async saveDraft() {
      await this.saveDraftNow()
      if (this.lastSaved) {
        const time = new Date(this.lastSaved).toLocaleTimeString('fr-FR')
        frappe.toast({
          message: `Brouillon sauvegarde a ${time}`,
          indicator: 'blue'
        })
      }
    },

    async discardDraft() {
      if (this.currentDraftId) {
        try {
          await frappe.call({
            method: 'frappe_webmail.api.delete_draft',
            args: { draft_id: this.currentDraftId }
          })
          frappe.toast({ message: 'Brouillon supprime', indicator: 'gray' })
        } catch (error) {
          console.error('Failed to delete draft:', error)
        }
      }
      this.isDirty = false
      this.$emit('close')
    },

    formatLastSaved() {
      if (!this.lastSaved) return ''
      return new Date(this.lastSaved).toLocaleTimeString('fr-FR')
    }
  }
}
</script>

<style scoped>
.email-composer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  border-radius: 8px;
}

.composer-field {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.composer-field label {
  width: 50px;
  color: var(--text-muted, #8d99a6);
  font-size: 13px;
}

.composer-field input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 14px;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  gap: 4px;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
  background: var(--bg-light-gray, #f5f5f5);
}

.editor-toolbar button {
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
}

.editor-toolbar button:hover {
  background: var(--bg-gray, #eee);
}

.editor-toolbar button.active {
  background: var(--primary-light, #e3f2fd);
  border-color: var(--primary-color, #2490ef);
}

.editor-toolbar .separator {
  width: 1px;
  height: 20px;
  background: var(--border-color, #e5e5e5);
  margin: 0 8px;
}

.editor-container {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}

.editor-container :deep(.ProseMirror) {
  min-height: 200px;
  outline: none;
}

.editor-container :deep(.ProseMirror p.is-editor-empty:first-child::before) {
  color: var(--text-muted, #8d99a6);
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}

.attachments-section {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #e5e5e5);
}

.attachment-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-light-gray, #f5f5f5);
  border-radius: 4px;
  font-size: 12px;
}

.attachment-chip .size {
  color: var(--text-muted, #8d99a6);
}

.attachment-chip .remove {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-muted, #8d99a6);
  font-size: 16px;
  padding: 0 4px;
}

.attachment-chip .remove:hover {
  color: #e74c3c;
}

.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #e5e5e5);
}

.draft-status {
  font-size: 12px;
  color: var(--text-muted, #8d99a6);
}

.draft-status .saving {
  color: var(--primary-color, #2490ef);
}

.draft-status .saved {
  color: var(--success-color, #28a745);
}

.action-buttons {
  display: flex;
  gap: 8px;
}

.composer-actions .btn {
  padding: 8px 16px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}

.composer-actions .btn-primary {
  background: var(--primary-color, #2490ef);
  color: white;
  border-color: var(--primary-color, #2490ef);
}

.composer-actions .btn-primary:hover {
  background: #1a7fd4;
}

.composer-actions .btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.composer-actions .btn-secondary {
  background: white;
}

.composer-actions .btn-secondary:hover {
  background: var(--bg-light-gray, #f5f5f5);
}

.composer-actions .btn-light {
  background: white;
  color: var(--text-muted, #8d99a6);
}

.composer-actions .btn-light:hover {
  background: var(--bg-light-gray, #f5f5f5);
}

.composer-actions .btn-danger-light {
  background: white;
  color: #dc3545;
  border-color: #dc3545;
}

.composer-actions .btn-danger-light:hover {
  background: #dc3545;
  color: white;
}
</style>
