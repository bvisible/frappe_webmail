<template>
	<div class="webmail-container">
		<!-- Header -->
		<div class="webmail-header">
			<div class="header-left">
				<h1>📧 Webmail</h1>
				<select
					v-model="currentAccount"
					class="account-selector"
					@change="onAccountChange"
				>
					<option v-for="acc in accounts" :key="acc.name" :value="acc.name">
						{{ acc.email }}
					</option>
				</select>
			</div>
			<div class="header-right">
				<button @click="showSearch = true" class="btn btn-secondary">
					🔍 {{ __("Search") }}
				</button>
				<button @click="compose" class="btn btn-primary">
					✉️ {{ __("New Message") }}
				</button>
				<button @click="showFilters = true" class="btn btn-secondary">
					🗂️ {{ __("Filters") }}
				</button>
				<button @click="showSignatures = true" class="btn btn-secondary">
					✍️ {{ __("Signatures") }}
				</button>
				<button @click="openSettings" class="btn btn-secondary">
					⚙️ {{ __("Settings") }}
				</button>
			</div>
		</div>

		<!-- Main Content -->
		<div class="webmail-main" v-if="accounts.length" :class="{ 'is-resizing': isResizing }">
			<!-- Folder Sidebar -->
			<div class="sidebar" :style="{ width: sidebarWidth + 'px' }">
				<FolderTree
					:account="currentAccount"
					:account-email="currentAccountEmail"
					:selected-folder="currentFolder"
					@select="onFolderSelect"
				/>
			</div>

			<!-- Resizer 1: Sidebar / Email List -->
			<div class="column-resizer" @mousedown="startResize('sidebar', $event)">
				<div class="resizer-handle"></div>
			</div>

			<!-- Email List -->
			<div class="email-list-panel" :style="{ width: emailListWidth + 'px' }">
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

			<!-- Resizer 2: Email List / Email Viewer -->
			<div class="column-resizer" @mousedown="startResize('emailList', $event)">
				<div class="resizer-handle"></div>
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
					:edit-draft="editingDraft"
					:signature="defaultSignature"
					:folder="currentFolder"
					@sent="onEmailSent"
					@close="closeComposer"
					@draft-deleted="onDraftDeleted"
				/>
			</div>
		</div>

		<!-- No Accounts State -->
		<div class="no-accounts" v-else-if="!loading">
			<div class="no-accounts-content">
				<h2>{{ __("Welcome to Webmail") }}</h2>
				<p>{{ __("You haven't configured any email account yet.") }}</p>
				<button @click="openSettings" class="btn btn-primary">
					{{ __("Configure an account") }}
				</button>
			</div>
		</div>

		<!-- Loading -->
		<div class="loading-overlay" v-if="loading">
			<div class="spinner"></div>
			<p>{{ __("Loading...") }}</p>
		</div>

		<!-- Signature Editor Modal -->
		<div class="modal-overlay" v-if="showSignatures" @click.self="showSignatures = false">
			<div class="modal-content signature-modal">
				<SignatureEditor @close="showSignatures = false" @updated="loadDefaultSignature" />
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
import FolderTree from "../components/FolderTree.vue";
import EmailList from "../components/EmailList.vue";
import EmailViewer from "../components/EmailViewer.vue";
import EmailComposer from "../components/EmailComposer.vue";
import SignatureEditor from "../components/SignatureEditor.vue";
import AdvancedSearch from "../components/AdvancedSearch.vue";
import FilterManager from "../components/FilterManager.vue";

export default {
	name: "Webmail",

	components: {
		FolderTree,
		EmailList,
		EmailViewer,
		EmailComposer,
		SignatureEditor,
		AdvancedSearch,
		FilterManager,
	},

	data() {
		return {
			loading: true,
			accounts: [],
			currentAccount: "",
			currentFolder: "INBOX",
			selectedEmail: null,
			selectedEmailContent: null,
			totalEmails: 0,
			showComposer: false,
			replyToEmail: null,
			forwardingEmail: null,
			editingDraft: null,
			defaultSignature: "",
			showSignatures: false,
			pollingEnabled: true,
			pollingInterval: 60000, // 60 seconds
			unreadCount: 0,
			showSearch: false,
			showFilters: false,
			folders: [],
			// Column resize state
			sidebarWidth: 220,
			emailListWidth: 350,
			isResizing: false,
			resizeTarget: null,
			resizeStartX: 0,
			resizeStartWidth: 0,
			savePreferencesTimeout: null,
		};
	},

	computed: {
		currentAccountEmail() {
			const acc = this.accounts.find((a) => a.name === this.currentAccount);
			return acc?.email || "";
		},
	},

	mounted() {
		this.initialize();
	},

	methods: {
		async initialize() {
			this.loading = true;

			try {
				await this.loadAccounts();
				await this.loadDefaultSignature();
				await this.loadUIPreferences();
			} catch (error) {
				console.error("Initialization error:", error);
			} finally {
				this.loading = false;
			}
		},

		async loadAccounts() {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_accounts",
				});

				this.accounts = response.message || [];

				if (this.accounts.length && !this.currentAccount) {
					this.currentAccount = this.accounts[0].name;
					// Load folders for search
					this.loadFolders();
				}
			} catch (error) {
				frappe.toast({ message: __("Error loading accounts"), indicator: "red" });
			}
		},

		async loadFolders() {
			if (!this.currentAccount) return;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_folders",
					args: { account_name: this.currentAccount },
				});
				this.folders = (response.message || []).filter((f) => f.selectable);
			} catch (error) {
				console.error("Error loading folders:", error);
			}
		},

		async loadDefaultSignature() {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_default_signature",
				});
				this.defaultSignature = response.message || "";
			} catch (error) {
				console.error("Error loading signature:", error);
			}
		},

		onAccountChange() {
			this.currentFolder = "INBOX";
			this.selectedEmail = null;
			this.selectedEmailContent = null;
			this.loadFolders();
			this.loadUIPreferences();
		},

		onFolderSelect(folder) {
			this.currentFolder = folder;
			this.selectedEmail = null;
			this.selectedEmailContent = null;
		},

		async onEmailSelect(email) {
			this.selectedEmail = email;

			// Load full content
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_email_content",
					args: {
						account_name: this.currentAccount,
						uid: email.uid,
						folder: this.currentFolder,
						mark_read: true,
					},
				});

				const emailContent = response.message;

				// Check if this is a Drafts folder - open in composer mode
				if (this.isDraftsFolder(this.currentFolder)) {
					this.editingDraft = { ...emailContent, folder: this.currentFolder };
					this.replyToEmail = null;
					this.forwardingEmail = null;
					this.showComposer = true;
					this.selectedEmailContent = null;
				} else {
					// Normal email - open in viewer mode
					this.showComposer = false;
					this.selectedEmailContent = emailContent;

					// Mark as read in list
					if (this.$refs.emailList) {
						this.$refs.emailList.markAsRead(email.uid);
					}
				}
			} catch (error) {
				frappe.toast({ message: __("Error loading email"), indicator: "red" });
			}
		},

		isDraftsFolder(folderName) {
			const name = folderName.toLowerCase();
			return (
				name === "drafts" ||
				name === "draft" ||
				name === "brouillons" ||
				name.endsWith("/drafts") ||
				name.endsWith("/draft") ||
				name.includes("drafts") ||
				name === "inbox.drafts"
			);
		},

		compose() {
			this.showComposer = true;
			this.replyToEmail = null;
			this.forwardingEmail = null;
			this.editingDraft = null;
		},

		replyTo(email) {
			this.showComposer = true;
			this.replyToEmail = email;
			this.forwardingEmail = null;
			this.editingDraft = null;
		},

		forwardEmail(email) {
			this.showComposer = true;
			this.forwardingEmail = email;
			this.replyToEmail = null;
			this.editingDraft = null;
		},

		closeComposer() {
			this.showComposer = false;
			this.replyToEmail = null;
			this.forwardingEmail = null;
			this.editingDraft = null;
		},

		onEmailSent() {
			this.closeComposer();
			// Optionally refresh sent folder
		},

		onDraftDeleted() {
			// Refresh the email list to remove the deleted draft
			if (this.$refs.emailList) {
				this.$refs.emailList.refresh();
			}
		},

		deleteEmail(email) {
			frappe.confirm(__("Are you sure you want to delete this email?"), async () => {
				try {
					const response = await frappe.call({
						method: "frappe_webmail.api.delete_emails",
						args: {
							account_name: this.currentAccount,
							uids: JSON.stringify([email.uid]),
							folder: this.currentFolder,
							permanent: false,
						},
					});

					console.log("Delete response:", response);
					frappe.toast({ message: __("Email deleted"), indicator: "green" });

					// Refresh list
					if (this.$refs.emailList) {
						this.$refs.emailList.refresh();
					}

					this.selectedEmail = null;
					this.selectedEmailContent = null;
				} catch (error) {
					console.error("Delete error:", error);
					frappe.toast({ message: __("Delete error"), indicator: "red" });
				}
			});
		},

		onFlagChanged(email) {
			// Update in list if needed
			if (this.$refs.emailList) {
				const listEmail = this.$refs.emailList.emails.find((e) => e.uid === email.uid);
				if (listEmail) {
					listEmail.flagged = email.flagged;
				}
			}
		},

		onMarkUnread(email) {
			// Update in list to show as unread
			if (this.$refs.emailList) {
				const listEmail = this.$refs.emailList.emails.find((e) => e.uid === email.uid);
				if (listEmail) {
					listEmail.seen = false;
				}
			}
		},

		openSettings() {
			// Open Webmail Account list
			frappe.set_route("List", "Webmail Account");
		},

		onNewEmails({ count, emails }) {
			// Update document title with unread count
			this.unreadCount += count;
			this.updateDocumentTitle();

			// Could also trigger browser notification if permission granted
			this.requestNotificationPermission();
		},

		updateDocumentTitle() {
			const baseTitle = "Webmail";
			if (this.unreadCount > 0) {
				document.title = `(${this.unreadCount}) ${baseTitle}`;
			} else {
				document.title = baseTitle;
			}
		},

		async requestNotificationPermission() {
			if (!("Notification" in window)) return;

			if (Notification.permission === "default") {
				await Notification.requestPermission();
			}
		},

		togglePolling() {
			this.pollingEnabled = !this.pollingEnabled;
		},

		// Column resize methods
		async loadUIPreferences() {
			if (!this.currentAccount) return;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_ui_preferences",
					args: { account_name: this.currentAccount },
				});

				if (response.message) {
					this.sidebarWidth = response.message.sidebar_width || 220;
					this.emailListWidth = response.message.email_list_width || 350;
				}
			} catch (error) {
				console.error("Error loading UI preferences:", error);
			}
		},

		saveUIPreferences() {
			// Debounce the save to avoid too many API calls
			if (this.savePreferencesTimeout) {
				clearTimeout(this.savePreferencesTimeout);
			}

			this.savePreferencesTimeout = setTimeout(async () => {
				if (!this.currentAccount) return;

				try {
					await frappe.call({
						method: "frappe_webmail.webmail_api.save_ui_preferences",
						args: {
							account_name: this.currentAccount,
							sidebar_width: this.sidebarWidth,
							email_list_width: this.emailListWidth,
						},
					});
				} catch (error) {
					console.error("Error saving UI preferences:", error);
				}
			}, 500);
		},

		startResize(target, event) {
			event.preventDefault();
			this.isResizing = true;
			this.resizeTarget = target;
			this.resizeStartX = event.clientX;

			if (target === "sidebar") {
				this.resizeStartWidth = this.sidebarWidth;
			} else if (target === "emailList") {
				this.resizeStartWidth = this.emailListWidth;
			}

			document.addEventListener("mousemove", this.onResize);
			document.addEventListener("mouseup", this.stopResize);
			document.body.style.cursor = "col-resize";
			document.body.style.userSelect = "none";
		},

		onResize(event) {
			if (!this.isResizing) return;

			const deltaX = event.clientX - this.resizeStartX;
			let newWidth = this.resizeStartWidth + deltaX;

			if (this.resizeTarget === "sidebar") {
				// Sidebar: min 150px, max 400px
				newWidth = Math.max(150, Math.min(400, newWidth));
				this.sidebarWidth = newWidth;
			} else if (this.resizeTarget === "emailList") {
				// Email list: min 250px, max 600px
				newWidth = Math.max(250, Math.min(600, newWidth));
				this.emailListWidth = newWidth;
			}
		},

		stopResize() {
			if (!this.isResizing) return;

			this.isResizing = false;
			this.resizeTarget = null;

			document.removeEventListener("mousemove", this.onResize);
			document.removeEventListener("mouseup", this.stopResize);
			document.body.style.cursor = "";
			document.body.style.userSelect = "";

			// Save preferences after resize
			this.saveUIPreferences();
		},

		async onSearchSelect({ email, folder }) {
			// Switch to the folder if different
			if (folder !== this.currentFolder) {
				this.currentFolder = folder;
			}

			// Close search modal
			this.showSearch = false;

			// Load the email content
			this.selectedEmail = email;
			this.showComposer = false;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_email_content",
					args: {
						account_name: this.currentAccount,
						uid: email.uid,
						folder: folder,
						mark_read: true,
					},
				});

				this.selectedEmailContent = response.message;
			} catch (error) {
				frappe.toast({ message: __("Loading error"), indicator: "red" });
			}
		},
	},
};
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

.webmail-main.is-resizing {
	cursor: col-resize;
}

.webmail-main.is-resizing * {
	pointer-events: none;
}

.sidebar {
	flex-shrink: 0;
	background: white;
	overflow-y: auto;
	border-top: 1px solid var(--border-color, #e5e5e5);
	min-width: 150px;
	max-width: 400px;
}

.column-resizer {
	width: 6px;
	flex-shrink: 0;
	cursor: col-resize;
	background: transparent;
	position: relative;
	z-index: 10;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: background 0.15s ease;
}

.column-resizer:hover {
	background: rgba(36, 144, 239, 0.1);
}

.column-resizer:active,
.webmail-main.is-resizing .column-resizer {
	background: rgba(36, 144, 239, 0.2);
}

.resizer-handle {
	width: 2px;
	height: 40px;
	background: var(--border-color, #e5e5e5);
	border-radius: 2px;
	transition: background 0.15s ease, height 0.15s ease;
}

.column-resizer:hover .resizer-handle {
	background: var(--primary-color, #2490ef);
	height: 60px;
}

.column-resizer:active .resizer-handle,
.webmail-main.is-resizing .column-resizer .resizer-handle {
	background: var(--primary-color, #2490ef);
	height: 80px;
}

.email-list-panel {
	flex-shrink: 0;
	border-right: 1px solid var(--border-color, #e5e5e5);
	border-top: 1px solid var(--border-color, #e5e5e5);
	border-radius: 0 var(--border-radius-lg) 0 0;
	overflow: hidden;
	min-width: 250px;
	max-width: 600px;
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
