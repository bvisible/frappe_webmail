<template>
	<div class="webmail-container">
		<!-- Header -->
		<div class="webmail-header">
			<div class="header-left">
				<h1>
					<Mail :size="22" />
					<span>Webmail</span>
				</h1>
				<div class="account-selector-wrapper">
					<select
						v-model="currentAccount"
						class="account-selector"
						@change="onAccountChange"
					>
						<option v-for="acc in accounts" :key="acc.name" :value="acc.name">
							{{ acc.email }}{{ acc.is_shared ? ` (${__("shared")})` : "" }}
						</option>
					</select>
					<div
						v-if="currentAccountSharing"
						class="sharing-indicator"
						@mouseenter="showSharingTooltip = true"
						@mouseleave="showSharingTooltip = false"
					>
						<Users :size="16" />
						<div v-if="showSharingTooltip" class="sharing-tooltip">
							{{ currentAccountSharing }}
						</div>
					</div>
				</div>
			</div>
			<div class="header-right">
				<button @click="showSearch = true" class="btn btn-secondary">
					<Search :size="16" />
					<span>{{ __("Search") }}</span>
				</button>
				<button @click="compose" class="btn btn-primary">
					<SquarePen :size="16" />
					<span>{{ __("New Message") }}</span>
				</button>
				<button @click="showFilters = true" class="btn btn-secondary">
					<Filter :size="16" />
					<span>{{ __("Filters") }}</span>
				</button>
				<button @click="showSignatures = true" class="btn btn-secondary">
					<PenLine :size="16" />
					<span>{{ __("Signatures") }}</span>
				</button>
				<button @click="openSettings" class="btn btn-secondary">
					<Settings :size="16" />
					<span>{{ __("Settings") }}</span>
				</button>
			</div>
		</div>

		<!-- Main Content -->
		<div class="webmail-main" v-if="accounts.length" :class="{ 'is-resizing': isResizing }">
			<!-- Folder Sidebar -->
			<div class="sidebar" :style="{ width: sidebarWidth + 'px' }">
				<FolderTree
					ref="folderTree"
					:account="currentAccount"
					:account-email="currentAccountEmail"
					:selected-folder="currentFolder"
					@select="onFolderSelect"
					@drop-email="handleMoveEmail"
					@folder-mapping-loaded="onFolderMappingLoaded"
				/>
			</div>

			<!-- Resizer 1: Sidebar / Email List -->
			<div class="column-resizer" @mousedown="startResize('sidebar', $event)">
				<div class="resizer-handle"></div>
			</div>

			<!-- Email List -->
			<div class="email-list-panel" :style="{ width: emailListWidth + 'px' }">
				<!-- Bulk Action Bar -->
				<BulkActionBar
					:selected-count="selectedCount"
					:folders="folders"
					:current-folder="currentFolder"
					:folder-mapping="folderMapping"
					@clear="clearBulkSelection"
					@archive="handleBulkArchive"
					@delete="handleBulkDelete"
					@mark-read="handleBulkMarkRead"
					@mark-unread="handleBulkMarkUnread"
					@move="handleBulkMove"
					@toggle-star="handleBulkToggleStar"
					@spam="handleBulkSpam"
					@delete-permanent="handleBulkDeletePermanent"
				/>

				<EmailList
					ref="emailList"
					:account="currentAccount"
					:folder="currentFolder"
					:selected-uid="selectedEmail?.uid"
					:polling-enabled="pollingEnabled"
					:polling-interval="pollingInterval"
					:folders="folders"
					:folder-mapping="folderMapping"
					@select="onEmailSelect"
					@update:total="totalEmails = $event"
					@new-emails="onNewEmails"
					@context-action="handleEmailContextAction"
					@selection-change="onSelectionChange"
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
					@quick-reply="handleQuickReply"
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
import BulkActionBar from "../components/BulkActionBar.vue";
import { Mail, Search, SquarePen, Filter, PenLine, Settings, Users } from "lucide-vue-next";

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
		BulkActionBar,
		Mail,
		Search,
		SquarePen,
		Filter,
		PenLine,
		Settings,
		Users,
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
			showSharingTooltip: false,
			folders: [],
			// Folder mapping (from FolderTree)
			folderMapping: {
				inbox: "",
				sent: "",
				drafts: "",
				trash: "",
				spam: "",
				archive: "",
			},
			// Column resize state
			sidebarWidth: 220,
			emailListWidth: 350,
			isResizing: false,
			resizeTarget: null,
			resizeStartX: 0,
			resizeStartWidth: 0,
			savePreferencesTimeout: null,
			// Bulk actions
			selectedCount: 0,
			selectedUids: [],
			lastBulkAction: null,
		};
	},

	computed: {
		currentAccountEmail() {
			const acc = this.accounts.find((a) => a.name === this.currentAccount);
			return acc?.email || "";
		},

		currentAccountSharing() {
			const acc = this.accounts.find((a) => a.name === this.currentAccount);
			if (!acc) return null;

			// If this is a shared account (we are not the owner)
			if (acc.is_shared) {
				return this.__("Shared by {0}", [acc.user]);
			}

			// If we own this account and it's shared with others
			if (acc.shared_with && acc.shared_with.length > 0) {
				return this.__("Shared with {0}", [acc.shared_with.join(", ")]);
			}

			return null;
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
					// Try to restore last used account from localStorage
					const lastAccount = localStorage.getItem("webmail_last_account");
					const accountExists =
						lastAccount && this.accounts.some((a) => a.name === lastAccount);

					this.currentAccount = accountExists ? lastAccount : this.accounts[0].name;
					// Save the selected account
					localStorage.setItem("webmail_last_account", this.currentAccount);
					// Load folders for search
					this.loadFolders();
				}
			} catch (error) {
				frappe.toast({ message: this.__("Error loading accounts"), indicator: "red" });
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
			// Save last used account to localStorage
			localStorage.setItem("webmail_last_account", this.currentAccount);
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
				frappe.toast({ message: this.__("Error loading email"), indicator: "red" });
			}
		},

		isDraftsFolder(folderName) {
			// Check folder mapping first
			if (this.folderMapping.drafts && folderName === this.folderMapping.drafts) {
				return true;
			}

			// Fallback to name-based detection
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

		onFolderMappingLoaded(mapping) {
			this.folderMapping = mapping;
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

		handleQuickReply(data) {
			// Open composer in reply mode with Nora-generated draft content
			const email = data.original_email;
			this.showComposer = true;
			this.replyToEmail = {
				...email,
				noraDraftHtml: data.draft_html,
			};
			this.forwardingEmail = null;
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
			frappe.confirm(this.__("Are you sure you want to delete this email?"), async () => {
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
					frappe.toast({ message: this.__("Email deleted"), indicator: "green" });

					// Refresh list
					if (this.$refs.emailList) {
						this.$refs.emailList.refresh();
					}

					this.selectedEmail = null;
					this.selectedEmailContent = null;
				} catch (error) {
					console.error("Delete error:", error);
					frappe.toast({ message: this.__("Delete error"), indicator: "red" });
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
				frappe.toast({ message: this.__("Loading error"), indicator: "red" });
			}
		},

		async handleMoveEmail({ targetFolder, email }) {
			// Don't move if same folder
			if (email.folder === targetFolder) {
				return;
			}

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.move_emails",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify([email.uid]),
						from_folder: email.folder,
						to_folder: targetFolder,
					},
				});

				frappe.toast({
					message: this.__("Email moved to {0}", [targetFolder]),
					indicator: "green",
				});

				// Refresh email list to remove the moved email
				if (this.$refs.emailList) {
					this.$refs.emailList.refresh();
				}

				// Clear selection if the moved email was selected
				if (this.selectedEmail && this.selectedEmail.uid === email.uid) {
					this.selectedEmail = null;
					this.selectedEmailContent = null;
				}
			} catch (error) {
				frappe.toast({
					message: this.__("Error moving email"),
					indicator: "red",
				});
			}
		},

		async handleEmailContextAction({ action, email, targetFolder, uids, isBulk }) {
			// Handle bulk actions from context menu or keyboard shortcuts
			if (isBulk && uids && uids.length > 1) {
				this.selectedUids = uids;
				this.selectedCount = uids.length;

				switch (action) {
					case "mark-read":
						await this.handleBulkMarkRead();
						break;
					case "mark-unread":
						await this.handleBulkMarkUnread();
						break;
					case "toggle-star":
						await this.handleBulkToggleStar();
						break;
					case "move-to":
						await this.handleBulkMove(targetFolder);
						break;
					case "copy-to":
						await this.bulkCopyEmails(targetFolder);
						break;
					case "trash":
						await this.handleBulkDelete();
						break;
					case "spam":
						await this.handleBulkSpam();
						break;
					case "delete-permanent":
						await this.handleBulkDeletePermanent();
						break;
					case "archive":
						await this.handleBulkArchive();
						break;
				}
				return;
			}

			// Single email actions
			switch (action) {
				case "reply":
					await this.loadEmailAndReply(email, false);
					break;

				case "reply-all":
					await this.loadEmailAndReply(email, true);
					break;

				case "forward":
					await this.loadEmailAndForward(email);
					break;

				case "mark-read":
					await this.markEmailReadUnread(email, true);
					break;

				case "mark-unread":
					await this.markEmailReadUnread(email, false);
					break;

				case "toggle-star":
					await this.toggleEmailStar(email);
					break;

				case "move-to":
					await this.moveEmailToFolder(email, targetFolder);
					break;

				case "copy-to":
					await this.copyEmailToFolder(email, targetFolder);
					break;

				case "trash":
					await this.moveToTrash(email);
					break;

				case "spam":
					await this.moveToSpam(email);
					break;

				case "delete-permanent":
					await this.deleteEmailPermanently(email);
					break;

				case "archive":
					const archiveFolder = this.folderMapping.archive || "Archive";
					await this.moveEmailToFolder(email, archiveFolder);
					break;
			}
		},

		async loadEmailAndReply(email, replyAll) {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_email_content",
					args: {
						account_name: this.currentAccount,
						uid: email.uid,
						folder: this.currentFolder,
						mark_read: false,
					},
				});

				const emailContent = response.message;
				emailContent.reply_all = replyAll;
				this.replyTo(emailContent);
			} catch (error) {
				frappe.toast({ message: this.__("Error loading email"), indicator: "red" });
			}
		},

		async loadEmailAndForward(email) {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_email_content",
					args: {
						account_name: this.currentAccount,
						uid: email.uid,
						folder: this.currentFolder,
						mark_read: false,
					},
				});

				this.forwardEmail(response.message);
			} catch (error) {
				frappe.toast({ message: this.__("Error loading email"), indicator: "red" });
			}
		},

		async markEmailReadUnread(email, read) {
			try {
				const action = read ? "add_flags" : "remove_flags";
				await frappe.call({
					method: "frappe_webmail.api.set_flags",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify([email.uid]),
						folder: this.currentFolder,
						[action]: JSON.stringify(["\\Seen"]),
					},
				});

				// Update email in list
				if (this.$refs.emailList) {
					this.$refs.emailList.updateEmailFlag(email.uid, "seen", read);
				}
			} catch (error) {
				frappe.toast({ message: this.__("Error"), indicator: "red" });
			}
		},

		async toggleEmailStar(email) {
			try {
				const action = email.flagged ? "remove_flags" : "add_flags";
				await frappe.call({
					method: "frappe_webmail.api.set_flags",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify([email.uid]),
						folder: this.currentFolder,
						[action]: JSON.stringify(["\\Flagged"]),
					},
				});

				// Update email in list
				if (this.$refs.emailList) {
					this.$refs.emailList.updateEmailFlag(email.uid, "flagged", !email.flagged);
				}
			} catch (error) {
				frappe.toast({ message: this.__("Error"), indicator: "red" });
			}
		},

		async moveEmailToFolder(email, targetFolder) {
			if (!targetFolder || targetFolder === this.currentFolder) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.move_emails",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify([email.uid]),
						from_folder: this.currentFolder,
						to_folder: targetFolder,
					},
				});

				frappe.toast({
					message: this.__("Email moved"),
					indicator: "green",
				});

				// Remove from list
				if (this.$refs.emailList) {
					this.$refs.emailList.removeEmail(email.uid);
				}

				// Clear selection if moved email was selected
				if (this.selectedEmail?.uid === email.uid) {
					this.selectedEmail = null;
					this.selectedEmailContent = null;
				}
			} catch (error) {
				frappe.toast({ message: this.__("Error moving email"), indicator: "red" });
			}
		},

		async copyEmailToFolder(email, targetFolder) {
			if (!targetFolder || targetFolder === this.currentFolder) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.copy_emails",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify([email.uid]),
						from_folder: this.currentFolder,
						to_folder: targetFolder,
					},
				});

				frappe.toast({
					message: this.__("Email copied"),
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({ message: this.__("Error copying email"), indicator: "red" });
			}
		},

		async moveToTrash(email) {
			const trashFolder = this.folderMapping.trash || "Trash";
			await this.moveEmailToFolder(email, trashFolder);
		},

		async moveToSpam(email) {
			const spamFolder = this.folderMapping.spam || "Spam";
			await this.moveEmailToFolder(email, spamFolder);
		},

		async deleteEmailPermanently(email) {
			frappe.confirm(
				this.__(
					"Are you sure you want to permanently delete this email? This action cannot be undone."
				),
				async () => {
					try {
						await frappe.call({
							method: "frappe_webmail.api.delete_emails",
							args: {
								account_name: this.currentAccount,
								uids: JSON.stringify([email.uid]),
								folder: this.currentFolder,
								permanent: true,
							},
						});

						frappe.toast({
							message: this.__("Email deleted permanently"),
							indicator: "green",
						});

						// Remove from list
						if (this.$refs.emailList) {
							this.$refs.emailList.removeEmail(email.uid);
						}

						// Clear selection if deleted email was selected
						if (this.selectedEmail?.uid === email.uid) {
							this.selectedEmail = null;
							this.selectedEmailContent = null;
						}
					} catch (error) {
						frappe.toast({
							message: this.__("Error deleting email"),
							indicator: "red",
						});
					}
				}
			);
		},

		// Bulk actions
		onSelectionChange({ count, uids }) {
			this.selectedCount = count;
			this.selectedUids = uids;
		},

		clearBulkSelection() {
			if (this.$refs.emailList) {
				this.$refs.emailList.clearSelection();
			}
			this.selectedCount = 0;
			this.selectedUids = [];
		},

		async handleBulkArchive() {
			const archiveFolder = this.folderMapping.archive || "Archive";
			await this.bulkMoveEmails(archiveFolder);
		},

		async handleBulkDelete() {
			const trashFolder = this.folderMapping.trash || "Trash";
			await this.bulkMoveEmails(trashFolder);
		},

		async handleBulkMarkRead() {
			await this.bulkSetFlags(["\\Seen"], "add");
		},

		async handleBulkMarkUnread() {
			await this.bulkSetFlags(["\\Seen"], "remove");
		},

		async handleBulkMove(targetFolder) {
			await this.bulkMoveEmails(targetFolder);
		},

		async handleBulkToggleStar() {
			// For bulk toggle, we add the flag (star all selected)
			await this.bulkSetFlags(["\\Flagged"], "add");
		},

		async handleBulkSpam() {
			const spamFolder = this.folderMapping.spam || "Spam";
			await this.bulkMoveEmails(spamFolder);
		},

		async handleBulkDeletePermanent() {
			const uids = this.selectedUids;
			const count = uids.length;

			frappe.confirm(
				this.__("Permanently delete {0} emails? This action cannot be undone.", [count]),
				async () => {
					try {
						await frappe.call({
							method: "frappe_webmail.api.delete_emails",
							args: {
								account_name: this.currentAccount,
								uids: JSON.stringify(uids),
								folder: this.currentFolder,
								permanent: true,
							},
						});

						// Remove from list and selection
						if (this.$refs.emailList) {
							this.$refs.emailList.removeFromSelection(uids);
							this.$refs.emailList.refresh();
						}

						// Clear selected email if it was in the deleted list
						if (this.selectedEmail && uids.includes(this.selectedEmail.uid)) {
							this.selectedEmail = null;
							this.selectedEmailContent = null;
						}

						frappe.toast({
							message: this.__("{0} emails deleted", [count]),
							indicator: "green",
						});
					} catch (error) {
						frappe.toast({
							message: this.__("Error deleting emails"),
							indicator: "red",
						});
					}
				}
			);
		},

		async bulkMoveEmails(targetFolder) {
			const uids = this.selectedUids;
			const count = uids.length;
			const fromFolder = this.currentFolder;

			if (!targetFolder || targetFolder === fromFolder) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.move_emails",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify(uids),
						from_folder: fromFolder,
						to_folder: targetFolder,
					},
				});

				// Store for Undo
				this.lastBulkAction = { type: "move", uids, fromFolder, toFolder: targetFolder };

				// Remove from list and clear selection
				if (this.$refs.emailList) {
					this.$refs.emailList.removeFromSelection(uids);
					this.$refs.emailList.refresh();
				}

				// Clear selected email if it was moved
				if (this.selectedEmail && uids.includes(this.selectedEmail.uid)) {
					this.selectedEmail = null;
					this.selectedEmailContent = null;
				}

				frappe.toast({
					message: this.__("{0} emails moved", [count]),
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({ message: this.__("Error moving emails"), indicator: "red" });
			}
		},

		async bulkCopyEmails(targetFolder) {
			const uids = this.selectedUids;
			const count = uids.length;

			if (!targetFolder || targetFolder === this.currentFolder) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.copy_emails",
					args: {
						account_name: this.currentAccount,
						uids: JSON.stringify(uids),
						from_folder: this.currentFolder,
						to_folder: targetFolder,
					},
				});

				frappe.toast({
					message: this.__("{0} emails copied", [count]),
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({ message: this.__("Error copying emails"), indicator: "red" });
			}
		},

		async bulkSetFlags(flags, action) {
			const uids = this.selectedUids;
			const count = uids.length;

			const args = {
				account_name: this.currentAccount,
				uids: JSON.stringify(uids),
				folder: this.currentFolder,
			};

			if (action === "add") {
				args.add_flags = JSON.stringify(flags);
			} else {
				args.remove_flags = JSON.stringify(flags);
			}

			try {
				await frappe.call({
					method: "frappe_webmail.api.set_flags",
					args,
				});

				// Update emails in the list
				if (this.$refs.emailList) {
					uids.forEach((uid) => {
						if (flags.includes("\\Seen")) {
							this.$refs.emailList.updateEmailFlag(uid, "seen", action === "add");
						}
						if (flags.includes("\\Flagged")) {
							this.$refs.emailList.updateEmailFlag(uid, "flagged", action === "add");
						}
					});
				}

				frappe.toast({
					message: this.__("{0} emails updated", [count]),
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({ message: this.__("Error updating emails"), indicator: "red" });
			}
		},
	},
};
</script>

<style scoped>
:global(.webmail-container) {
	display: flex;
	flex-direction: column;
	height: 100vh;
	background: var(--bg-color, #f5f5f5);
	overflow: hidden;
}

/* Also target the nested Vue root container */
:global(#webmail-app) {
	display: flex;
	flex-direction: column;
	height: 100%;
	overflow: hidden;
}

.webmail-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 12px 20px;
	background: var(--card-bg, white);
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
	display: flex;
	align-items: center;
	gap: 8px;
	color: var(--text-color, #333);
}

.account-selector-wrapper {
	display: flex;
	align-items: center;
	gap: 8px;
}

.account-selector {
	padding: 6px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	background: var(--card-bg, white);
	color: var(--text-color, #333);
	font-size: 14px;
	min-width: 200px;
}

.sharing-indicator {
	position: relative;
	display: flex;
	align-items: center;
	justify-content: center;
	width: 28px;
	height: 28px;
	border-radius: 4px;
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	color: var(--primary-color, #2490ef);
	cursor: help;
}

.sharing-indicator:hover {
	background: var(--primary-color, #2490ef);
	color: var(--card-bg, white);
}

.sharing-tooltip {
	position: absolute;
	top: calc(100% + 8px);
	left: 50%;
	transform: translateX(-50%);
	padding: 8px 12px;
	background: var(--tooltip-bg, #333);
	color: var(--tooltip-text, white);
	font-size: 12px;
	border-radius: 6px;
	white-space: nowrap;
	z-index: 1000;
	box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
	pointer-events: none;
}

.sharing-tooltip::before {
	content: "";
	position: absolute;
	bottom: 100%;
	left: 50%;
	transform: translateX(-50%);
	border: 6px solid transparent;
	border-bottom-color: var(--tooltip-bg, #333);
}

.header-right {
	display: flex;
	gap: 8px;
}

.header-right .btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 8px 14px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	cursor: pointer;
	font-size: 13px;
	background: var(--card-bg, white);
	color: var(--text-color, #333);
	transition: all 0.15s ease;
}

.header-right .btn-primary {
	background: var(--primary-color, #2490ef);
	color: white;
	border-color: var(--primary-color, #2490ef);
}

.header-right .btn-primary:hover {
	background: var(--primary-dark, #1a7fd4);
}

.header-right .btn-secondary:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.webmail-main {
	display: flex;
	flex: 1;
	overflow: hidden;
	min-height: 0;
}

.webmail-main.is-resizing {
	cursor: col-resize;
}

.webmail-main.is-resizing * {
	pointer-events: none;
}

.sidebar {
	flex-shrink: 0;
	background: var(--card-bg, white);
	overflow-y: auto;
	border-top: 1px solid var(--border-color, #e5e5e5);
	border-right: 1px solid var(--border-color, #e5e5e5);
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
	margin-left: -3px;
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
	width: 4px;
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
	background: var(--card-bg, white);
	border-radius: var(--border-radius-lg);
	border: 1px solid var(--border-color, #e5e5e5);
	margin: 0 10px;
	min-height: 0;
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
	background: var(--modal-overlay-bg, rgba(255, 255, 255, 0.9));
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
	background: var(--card-bg, white);
	border-radius: 8px;
	overflow: hidden;
	box-shadow: var(--shadow-lg, 0 4px 20px rgba(0, 0, 0, 0.2));
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
	display: flex;
	flex-direction: column;
}

.filter-modal {
	width: 550px;
	height: 70vh;
	max-width: 90vw;
	max-height: 80vh;
	overflow: hidden;
}
</style>
