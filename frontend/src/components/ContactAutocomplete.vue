<template>
  <div class="contact-autocomplete">
    <div class="input-wrapper">
      <div class="tags">
        <span
          v-for="(recipient, idx) in recipients"
          :key="idx"
          class="tag"
          :class="{ invalid: !isValidEmail(recipient.email) }"
        >
          <img
            v-if="recipient.image"
            :src="recipient.image"
            class="tag-avatar"
          />
          <span class="tag-name">{{ recipient.display }}</span>
          <button @click="removeRecipient(idx)" class="tag-remove">&times;</button>
        </span>
        <input
          ref="input"
          v-model="inputValue"
          type="text"
          :placeholder="recipients.length ? '' : placeholder"
          @input="onInput"
          @keydown.enter.prevent="onEnter"
          @keydown.backspace="onBackspace"
          @keydown.down.prevent="navigateDown"
          @keydown.up.prevent="navigateUp"
          @keydown.escape="closeSuggestions"
          @focus="onFocus"
          @blur="onBlur"
        />
      </div>
    </div>

    <!-- Suggestions dropdown -->
    <div
      v-if="showSuggestions && (suggestions.length || recentContacts.length)"
      class="suggestions-dropdown"
    >
      <!-- Search results -->
      <div v-if="inputValue && suggestions.length" class="suggestions-section">
        <div class="section-header">Resultats</div>
        <div
          v-for="(contact, idx) in suggestions"
          :key="'s-' + contact.name"
          class="suggestion-item"
          :class="{ active: highlightedIndex === idx }"
          @mousedown.prevent="selectContact(contact)"
          @mouseenter="highlightedIndex = idx"
        >
          <img
            v-if="contact.image"
            :src="contact.image"
            class="contact-avatar"
          />
          <div v-else class="contact-avatar-placeholder">
            {{ getInitials(contact.full_name) }}
          </div>
          <div class="contact-info">
            <div class="contact-name">{{ contact.full_name }}</div>
            <div class="contact-email">{{ contact.email }}</div>
          </div>
        </div>
      </div>

      <!-- Recent contacts -->
      <div v-if="!inputValue && recentContacts.length" class="suggestions-section">
        <div class="section-header">Contacts recents</div>
        <div
          v-for="(contact, idx) in recentContacts"
          :key="'r-' + contact.name"
          class="suggestion-item"
          :class="{ active: highlightedIndex === idx }"
          @mousedown.prevent="selectContact(contact)"
          @mouseenter="highlightedIndex = idx"
        >
          <img
            v-if="contact.image"
            :src="contact.image"
            class="contact-avatar"
          />
          <div v-else class="contact-avatar-placeholder">
            {{ getInitials(contact.full_name) }}
          </div>
          <div class="contact-info">
            <div class="contact-name">{{ contact.full_name }}</div>
            <div class="contact-email">{{ contact.email }}</div>
          </div>
        </div>
      </div>

      <!-- No results -->
      <div v-if="inputValue && !suggestions.length && !loading" class="no-results">
        Aucun contact trouve. Appuyez sur Entree pour ajouter.
      </div>

      <!-- Loading -->
      <div v-if="loading" class="loading">
        Recherche...
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ContactAutocomplete',

  props: {
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: 'Ajouter des destinataires...' }
  },

  emits: ['update:modelValue'],

  data() {
    return {
      inputValue: '',
      recipients: [],
      suggestions: [],
      recentContacts: [],
      showSuggestions: false,
      highlightedIndex: -1,
      loading: false,
      searchTimeout: null
    }
  },

  watch: {
    modelValue: {
      immediate: true,
      handler(val) {
        this.parseModelValue(val)
      }
    }
  },

  mounted() {
    this.loadRecentContacts()
  },

  methods: {
    parseModelValue(val) {
      if (!val) {
        this.recipients = []
        return
      }

      // Parse comma-separated emails
      const emails = val.split(',').map(e => e.trim()).filter(e => e)
      this.recipients = emails.map(email => ({
        email,
        display: email,
        image: null
      }))
    },

    emitValue() {
      const value = this.recipients.map(r => r.email).join(', ')
      this.$emit('update:modelValue', value)
    },

    async loadRecentContacts() {
      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.get_recent_contacts',
          args: { limit: 10 }
        })
        this.recentContacts = response.message || []
      } catch (error) {
        console.error('Error loading recent contacts:', error)
      }
    },

    onInput() {
      this.highlightedIndex = -1

      // Clear previous timeout
      if (this.searchTimeout) {
        clearTimeout(this.searchTimeout)
      }

      // Debounce search
      if (this.inputValue.length >= 2) {
        this.searchTimeout = setTimeout(() => {
          this.searchContacts()
        }, 300)
      } else {
        this.suggestions = []
      }
    },

    async searchContacts() {
      if (!this.inputValue || this.inputValue.length < 2) {
        this.suggestions = []
        return
      }

      this.loading = true

      try {
        const response = await frappe.call({
          method: 'frappe_webmail.api.search_contacts',
          args: {
            query: this.inputValue,
            limit: 10
          }
        })
        this.suggestions = response.message || []
      } catch (error) {
        console.error('Error searching contacts:', error)
        this.suggestions = []
      } finally {
        this.loading = false
      }
    },

    selectContact(contact) {
      this.addRecipient({
        email: contact.email,
        display: contact.full_name ? `${contact.full_name} <${contact.email}>` : contact.email,
        image: contact.image
      })
      this.inputValue = ''
      this.suggestions = []
      this.highlightedIndex = -1
      this.$refs.input.focus()
    },

    addRecipient(recipient) {
      // Check for duplicates
      if (this.recipients.some(r => r.email === recipient.email)) {
        return
      }
      this.recipients.push(recipient)
      this.emitValue()
    },

    removeRecipient(index) {
      this.recipients.splice(index, 1)
      this.emitValue()
    },

    onEnter() {
      if (this.highlightedIndex >= 0) {
        const items = this.inputValue ? this.suggestions : this.recentContacts
        if (items[this.highlightedIndex]) {
          this.selectContact(items[this.highlightedIndex])
          return
        }
      }

      // Add raw email
      const email = this.inputValue.trim()
      if (email) {
        this.addRecipient({
          email,
          display: email,
          image: null
        })
        this.inputValue = ''
        this.suggestions = []
      }
    },

    onBackspace() {
      if (!this.inputValue && this.recipients.length) {
        this.removeRecipient(this.recipients.length - 1)
      }
    },

    onFocus() {
      this.showSuggestions = true
    },

    onBlur() {
      // Delay to allow click on suggestion
      setTimeout(() => {
        this.showSuggestions = false

        // Add remaining input as email
        const email = this.inputValue.trim()
        if (email) {
          this.addRecipient({
            email,
            display: email,
            image: null
          })
          this.inputValue = ''
        }
      }, 200)
    },

    navigateDown() {
      const items = this.inputValue ? this.suggestions : this.recentContacts
      if (this.highlightedIndex < items.length - 1) {
        this.highlightedIndex++
      }
    },

    navigateUp() {
      if (this.highlightedIndex > 0) {
        this.highlightedIndex--
      }
    },

    closeSuggestions() {
      this.showSuggestions = false
      this.highlightedIndex = -1
    },

    isValidEmail(email) {
      const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      return re.test(email)
    },

    getInitials(name) {
      if (!name) return '?'
      const parts = name.split(' ')
      if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase()
      }
      return name.substring(0, 2).toUpperCase()
    }
  }
}
</script>

<style scoped>
.contact-autocomplete {
  position: relative;
}

.input-wrapper {
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  padding: 4px 8px;
  min-height: 36px;
  background: white;
}

.input-wrapper:focus-within {
  border-color: var(--primary-color, #2490ef);
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.tag {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  background: var(--bg-light-gray, #f5f5f5);
  border-radius: 4px;
  font-size: 13px;
  max-width: 200px;
}

.tag.invalid {
  background: #fee;
  border: 1px solid #fcc;
}

.tag-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
}

.tag-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tag-remove {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  color: var(--text-muted, #8d99a6);
  font-size: 16px;
  line-height: 1;
}

.tag-remove:hover {
  color: #dc3545;
}

.tags input {
  flex: 1;
  min-width: 100px;
  border: none;
  outline: none;
  font-size: 14px;
  padding: 4px 0;
}

.suggestions-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: white;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  z-index: 100;
  max-height: 300px;
  overflow-y: auto;
  margin-top: 4px;
}

.suggestions-section {
  padding: 8px 0;
}

.section-header {
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted, #8d99a6);
  text-transform: uppercase;
}

.suggestion-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
}

.suggestion-item:hover,
.suggestion-item.active {
  background: var(--bg-light-gray, #f5f5f5);
}

.contact-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
}

.contact-avatar-placeholder {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--primary-color, #2490ef);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.contact-info {
  flex: 1;
  min-width: 0;
}

.contact-name {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.contact-email {
  font-size: 12px;
  color: var(--text-muted, #8d99a6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.no-results,
.loading {
  padding: 12px;
  text-align: center;
  color: var(--text-muted, #8d99a6);
  font-size: 13px;
}
</style>
