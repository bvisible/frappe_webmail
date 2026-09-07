<template>
	<div class="email-list-container">
		<!-- List header: serif folder title + unread count + actions
		     (no search input — the topbar cmd-search is the single entry point) -->
		<div class="list-header">
			<h2 class="list-title">{{ folderLabel }}</h2>
			<span class="list-count" v-if="unreadFilterCount > 0">
				{{ __("{0} unread", [unreadFilterCount]) }}
			</span>
			<div class="list-header-right">
				<div
					class="polling-status"
					v-if="pollingEnabled"
					:data-tip="__('Auto-refresh on')"
				>
					<span class="polling-indicator"></span>
				</div>
				<button
					@click="refresh"
					:disabled="loading"
					class="header-icon-btn"
					:data-tip="__('Refresh')"
					:aria-label="__('Refresh')"
				>
					<RefreshCw :size="14" :class="{ rotating: loading }" />
				</button>
				<label
					v-if="emails.length > 0"
					class="header-checkbox"
					:data-tip="allSelected ? __('Deselect all') : __('Select all')"
				>
					<input
						type="checkbox"
						:checked="allSelected"
						:indeterminate="someSelected"
						@change="selectAll"
					/>
				</label>
			</div>
		</div>

		<!-- Quick filter chips (Tous / Non lus / Avec PJ / Suivis) -->
		<div class="filter-chips" v-if="emails.length > 0">
			<button
				class="chip-filter"
				:class="{ on: activeFilter === 'all' }"
				@click="activeFilter = 'all'"
			>
				{{ __("All") }}
				<span class="ct">{{ emails.length }}</span>
			</button>
			<button
				class="chip-filter"
				:class="{ on: activeFilter === 'unread' }"
				@click="activeFilter = 'unread'"
			>
				{{ __("Unread") }}
				<span class="ct" v-if="unreadFilterCount">{{ unreadFilterCount }}</span>
			</button>
			<button
				class="chip-filter"
				:class="{ on: activeFilter === 'attachments' }"
				@click="activeFilter = 'attachments'"
			>
				{{ __("Attachments") }}
			</button>
			<button
				class="chip-filter"
				:class="{ on: activeFilter === 'starred' }"
				@click="activeFilter = 'starred'"
			>
				{{ __("Starred") }}
			</button>
		</div>

		<!-- List -->
		<RecycleScroller
			v-if="displayedEmails.length"
			class="email-list"
			:items="displayedEmails"
			:item-size="64"
			key-field="uid"
			v-slot="{ item }"
			@scroll-end="loadMore"
		>
			<div
				class="email-row"
				:class="{
					unread: !item.seen,
					active: item.uid === selectedUid,
					selected: isSelected(item.uid),
					flagged: item.flagged,
					dragging: draggingUid === item.uid,
				}"
				draggable="true"
				@click="$emit('select', item)"
				@contextmenu.prevent="showContextMenu($event, item)"
				@dragstart="onDragStart($event, item)"
				@dragend="onDragEnd"
			>
				<!-- Checkbox + star stacked vertically (compact left column) -->
				<div class="row-controls">
					<div class="checkbox-cell" @click.stop="toggleSelection(item, $event)">
						<input
							type="checkbox"
							:checked="isSelected(item.uid)"
							@click.stop
							@change="toggleSelection(item, $event)"
						/>
					</div>
					<div class="star" @click.stop="toggleStar(item)">
						<Star :size="14" :fill="item.flagged ? 'currentColor' : 'none'" />
					</div>
				</div>
				<!-- Sender avatar with deterministic gradient color from email -->
				<div
					class="email-avatar"
					:class="getAvatarColor(item.from_email)"
					:title="item.from_name || item.from_email"
				>
					{{ getAvatarInitials(item.from_name, item.from_email) }}
				</div>
				<div class="email-content">
					<div class="email-top-line">
						<span class="from">{{ item.from_name || item.from_email }}</span>
						<span class="date">{{ formatDate(item.date) }}</span>
					</div>
					<div class="email-bottom-line">
						<span class="subject-text">{{ item.subject || __("(No subject)") }}</span>
						<Reply
							v-if="item.answered"
							:size="14"
							class="status-icon replied"
							:title="__('Replied')"
						/>
						<Forward
							v-if="item.forwarded"
							:size="14"
							class="status-icon forwarded"
							:title="__('Forwarded')"
						/>
						<Paperclip
							v-if="item.has_attachments"
							:size="14"
							class="attachment-icon"
						/>
					</div>
				</div>
			</div>
		</RecycleScroller>

		<!-- Empty state -->
		<div v-else-if="!loading" class="empty-state">
			<p>{{ __("No emails in this folder") }}</p>
		</div>

		<!-- Loading -->
		<div v-if="loading" class="loading-indicator">{{ __("Loading...") }}</div>

		<!-- Context Menu -->
		<ContextMenu
			:visible="contextMenuVisible"
			:position="contextMenuPosition"
			:items="contextMenuItems"
			:selected-count="contextMenuSelectedCount"
			@select="onContextMenuSelect"
			@close="contextMenuVisible = false"
		/>
	</div>
</template>

<script>
import { RecycleScroller } from "vue-virtual-scroller";
import "vue-virtual-scroller/dist/vue-virtual-scroller.css";
import {
	Star,
	Reply,
	Forward,
	Paperclip,
	RefreshCw,
	Search,
	ReplyAll,
	Mail,
	MailOpen,
	FolderInput,
	Copy,
	Trash2,
	AlertTriangle,
} from "lucide-vue-next";
import ContextMenu from "./ContextMenu.vue";

export default {
	name: "EmailList",
	components: {
		RecycleScroller,
		Star,
		Reply,
		Forward,
		Paperclip,
		RefreshCw,
		Search,
		ReplyAll,
		Mail,
		MailOpen,
		FolderInput,
		Copy,
		Trash2,
		AlertTriangle,
		ContextMenu,
	},

	props: {
		account: { type: String, required: true },
		folder: { type: String, default: "INBOX" },
		selectedUid: { type: Number, default: null },
		pollingEnabled: { type: Boolean, default: true },
		pollingInterval: { type: Number, default: 60000 }, // 60 seconds
		folders: { type: Array, default: () => [] },
		folderMapping: {
			type: Object,
			default: () => ({
				inbox: "",
				sent: "",
				drafts: "",
				trash: "",
				spam: "",
				archive: "",
			}),
		},
	},

	emits: ["select", "update:total", "new-emails", "context-action", "selection-change"],

	data() {
		return {
			emails: [],
			total: 0,
			loading: false,
			hasMore: true,
			searchQuery: "",
			pollingTimer: null,
			lastCheckTime: null,
			newEmailCount: 0,
			draggingUid: null,
			// Context menu
			contextMenuVisible: false,
			contextMenuPosition: { x: 0, y: 0 },
			contextMenuEmail: null,
			// Multi-selection
			selectedUids: new Set(),
			lastSelectedIndex: -1,
			// Quick filter chip state ("all" | "unread" | "attachments" | "starred").
			activeFilter: "all",
		};
	},

	computed: {
		// Human-readable label for the current folder, shown as the serif
		// list header. Uses folderMapping to recognise the standard buckets
		// (Inbox/Sent/Drafts/Trash/Spam/Archive); falls back to the last
		// path segment for nested IMAP folders.
		folderLabel() {
			const folder = this.folder || "";
			const m = this.folderMapping || {};
			if (folder === "INBOX" || folder === m.inbox) return this.__("Inbox");
			if (folder === m.sent) return this.__("Sent");
			if (folder === m.drafts) return this.__("Drafts");
			if (folder === m.trash) return this.__("Trash");
			if (folder === m.spam) return this.__("Spam");
			if (folder === m.archive) return this.__("Archive");
			return folder.split("/").pop() || folder;
		},

		// Emails filtered by the active quick-filter chip. The RecycleScroller
		// uses this so filtering doesn't require an extra round-trip to IMAP.
		displayedEmails() {
			switch (this.activeFilter) {
				case "unread":
					return this.emails.filter((e) => !e.seen);
				case "attachments":
					return this.emails.filter((e) => e.has_attachments);
				case "starred":
					return this.emails.filter((e) => e.flagged);
				default:
					return this.emails;
			}
		},

		// Count of unread emails — shown next to the "Unread" chip when > 0.
		unreadFilterCount() {
			return this.emails.filter((e) => !e.seen).length;
		},

		contextMenuItems() {
			if (!this.contextMenuEmail) return [];

			const email = this.contextMenuEmail;
			const isTrash = this.isTrashFolder(this.folder);
			const isSpam = this.isSpamFolder(this.folder);

			const items = [
				{
					id: "reply",
					label: this.__("Reply"),
					icon: Reply,
					action: "reply",
				},
				{
					id: "reply-all",
					label: this.__("Reply All"),
					icon: ReplyAll,
					action: "reply-all",
				},
				{
					id: "forward",
					label: this.__("Forward"),
					icon: Forward,
					action: "forward",
				},
				{ separator: true },
				{
					id: "mark-read",
					label: email.seen ? this.__("Mark as unread") : this.__("Mark as read"),
					icon: email.seen ? Mail : MailOpen,
					action: email.seen ? "mark-unread" : "mark-read",
				},
				{
					id: "toggle-star",
					label: email.flagged ? this.__("Remove star") : this.__("Add star"),
					icon: Star,
					action: "toggle-star",
				},
				{ separator: true },
				{
					id: "move-to",
					label: this.__("Move to"),
					icon: FolderInput,
					action: "move-to",
					submenu: this.getMoveToFolders(),
				},
				{
					id: "copy-to",
					label: this.__("Copy to"),
					icon: Copy,
					action: "copy-to",
					submenu: this.getCopyToFolders(),
				},
				{ separator: true },
			];

			// Add trash/spam actions based on current folder
			if (!isTrash) {
				items.push({
					id: "trash",
					label: this.__("Move to Trash"),
					icon: Trash2,
					action: "trash",
				});
			}

			if (!isSpam) {
				items.push({
					id: "spam",
					label: this.__("Mark as Spam"),
					icon: AlertTriangle,
					action: "spam",
				});
			}

			items.push({ separator: true });

			items.push({
				id: "delete-permanent",
				label: this.__("Delete permanently"),
				icon: Trash2,
				action: "delete-permanent",
				danger: true,
			});

			return items;
		},

		// Multi-selection computed
		selectedCount() {
			return this.selectedUids.size;
		},

		selectedEmails() {
			return this.emails.filter((e) => this.selectedUids.has(e.uid));
		},

		allSelected() {
			return (
				this.emails.length > 0 && this.emails.every((e) => this.selectedUids.has(e.uid))
			);
		},

		someSelected() {
			return this.selectedUids.size > 0 && !this.allSelected;
		},

		contextMenuSelectedCount() {
			// If the right-clicked email is part of the selection, show selection count
			if (this.contextMenuEmail && this.selectedUids.has(this.contextMenuEmail.uid)) {
				return this.selectedUids.size;
			}
			// Otherwise, it's a single email context menu
			return 1;
		},
	},

	watch: {
		account: "onAccountOrFolderChange",
		folder: "onAccountOrFolderChange",
		pollingEnabled(enabled) {
			if (enabled) {
				this.startPolling();
			} else {
				this.stopPolling();
			}
		},
	},

	mounted() {
		this.loadEmails();
		if (this.pollingEnabled) {
			this.startPolling();
		}
		// Add keyboard event listeners
		document.addEventListener("keydown", this.onKeydown);
	},

	beforeUnmount() {
		this.stopPolling();
		document.removeEventListener("keydown", this.onKeydown);
	},

	methods: {
		// Deterministic gradient color class (c1-c6) for the sender avatar.
		// Same email always renders with the same color across sessions.
		getAvatarColor(email) {
			const src = (email || "").toLowerCase();
			let hash = 0;
			for (let i = 0; i < src.length; i++) {
				hash = (hash << 5) - hash + src.charCodeAt(i);
				hash |= 0; // keep 32-bit
			}
			return "c" + ((Math.abs(hash) % 6) + 1);
		},

		// 1-2 letter initials drawn from the sender name (falling back to email).
		getAvatarInitials(name, email) {
			const raw = (name || email || "?").trim();
			const parts = raw.split(/[\s@._-]+/).filter(Boolean);
			if (parts.length >= 2 && parts[0] && parts[1]) {
				return (parts[0][0] + parts[1][0]).toUpperCase();
			}
			return ((parts[0] || raw)[0] || "?").toUpperCase();
		},

		async loadEmails(append = false) {
			if (this.loading) return;
			if (append && !this.hasMore) return;

			this.loading = true;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_emails",
					args: {
						account_name: this.account,
						folder: this.folder,
						limit: 50,
						offset: append ? this.emails.length : 0,
						search: this.searchQuery || null,
					},
				});

				const data = response.message || {};
				// A short or malformed answer must never leave `emails` undefined: every
				// computed filter below runs `.filter()` on it.
				const rows = Array.isArray(data.emails) ? data.emails : [];

				if (append) {
					this.emails.push(...rows);
				} else {
					this.emails = rows;
				}

				this.total = Number(data.total) || 0;
				this.hasMore = Boolean(data.has_more);
				this.$emit("update:total", this.total);
			} catch (error) {
				frappe.toast({ message: this.__("Loading error"), indicator: "red" });
			} finally {
				this.loading = false;
			}
		},

		refresh() {
			this.emails = [];
			this.hasMore = true;
			this.loadEmails();
		},

		search() {
			this.refresh();
		},

		loadMore() {
			if (this.hasMore && !this.loading) {
				this.loadEmails(true);
			}
		},

		async toggleStar(email) {
			const action = email.flagged ? "remove_flags" : "add_flags";

			try {
				await frappe.call({
					method: "frappe_webmail.api.set_flags",
					args: {
						account_name: this.account,
						uids: JSON.stringify([email.uid]),
						folder: this.folder,
						[action]: JSON.stringify(["\\Flagged"]),
					},
				});

				email.flagged = !email.flagged;
			} catch (error) {
				frappe.toast({ message: this.__("Error"), indicator: "red" });
			}
		},

		formatDate(dateStr) {
			if (!dateStr) return "";
			const date = new Date(dateStr);
			const now = new Date();
			const isToday = date.toDateString() === now.toDateString();

			if (isToday) {
				return date.toLocaleTimeString("fr-FR", {
					hour: "2-digit",
					minute: "2-digit",
				});
			}

			const isThisYear = date.getFullYear() === now.getFullYear();
			if (isThisYear) {
				return date.toLocaleDateString("fr-FR", {
					day: "numeric",
					month: "short",
				});
			}

			return date.toLocaleDateString("fr-FR", {
				day: "numeric",
				month: "short",
				year: "2-digit",
			});
		},

		markAsRead(uid) {
			const email = this.emails.find((e) => e.uid === uid);
			if (email) email.seen = true;
		},

		onAccountOrFolderChange() {
			this.stopPolling();
			this.refresh();
			if (this.pollingEnabled) {
				this.startPolling();
			}
		},

		startPolling() {
			this.stopPolling(); // Clear any existing timer
			this.pollingTimer = setInterval(() => {
				this.checkForNewEmails();
			}, this.pollingInterval);
		},

		stopPolling() {
			if (this.pollingTimer) {
				clearInterval(this.pollingTimer);
				this.pollingTimer = null;
			}
		},

		async checkForNewEmails() {
			// Don't check while loading or if no emails loaded yet
			if (this.loading || this.emails.length === 0) return;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_emails",
					args: {
						account_name: this.account,
						folder: this.folder,
						limit: 10,
						offset: 0,
						search: null,
					},
				});

				const data = response.message;
				const newTotal = data.total;

				// Check if there are new emails
				if (newTotal > this.total) {
					const newCount = newTotal - this.total;
					this.newEmailCount = newCount;

					// Find truly new emails (UIDs we don't have)
					const existingUids = new Set(this.emails.map((e) => e.uid));
					const newEmails = data.emails.filter((e) => !existingUids.has(e.uid));

					if (newEmails.length > 0) {
						// Prepend new emails to the list
						this.emails.unshift(...newEmails);
						this.total = newTotal;

						this.$emit("update:total", this.total);
						this.$emit("new-emails", {
							count: newEmails.length,
							emails: newEmails,
						});

						// Show notification
						this.showNewEmailNotification(newEmails);
					}
				} else if (newTotal < this.total) {
					// Emails were deleted, refresh the list
					this.total = newTotal;
					this.$emit("update:total", this.total);
				}
			} catch (error) {
				console.error("Polling error:", error);
			}
		},

		showNewEmailNotification(newEmails) {
			if (newEmails.length === 1) {
				const email = newEmails[0];
				frappe.toast({
					message: __("New message from {0}", [email.from_name || email.from_email]),
					indicator: "blue",
				});
			} else {
				frappe.toast({
					message: __("{0} new messages", [newEmails.length]),
					indicator: "blue",
				});
			}

			// Play notification sound if available
			this.playNotificationSound();
		},

		playNotificationSound() {
			try {
				// Create a simple notification sound using Web Audio API
				const audioContext = new (window.AudioContext || window.webkitAudioContext)();
				const oscillator = audioContext.createOscillator();
				const gainNode = audioContext.createGain();

				oscillator.connect(gainNode);
				gainNode.connect(audioContext.destination);

				oscillator.frequency.value = 800;
				oscillator.type = "sine";
				gainNode.gain.value = 0.1;

				oscillator.start();
				oscillator.stop(audioContext.currentTime + 0.1);
			} catch (e) {
				// Audio not supported or blocked
			}
		},

		// Drag and drop methods
		onDragStart(event, email) {
			this.draggingUid = email.uid;
			event.dataTransfer.setData(
				"application/json",
				JSON.stringify({
					uid: email.uid,
					subject: email.subject,
					folder: this.folder,
				})
			);
			event.dataTransfer.effectAllowed = "move";

			// Set a custom drag image (optional)
			const dragImage = document.createElement("div");
			dragImage.textContent = email.subject || this.__("(No subject)");
			dragImage.style.cssText = `
				position: absolute;
				top: -1000px;
				padding: 8px 12px;
				background: var(--card-bg, white);
				border: 1px solid var(--border-color, #e5e5e5);
				border-radius: 4px;
				font-size: 13px;
				max-width: 200px;
				overflow: hidden;
				text-overflow: ellipsis;
				white-space: nowrap;
				box-shadow: 0 2px 8px rgba(0,0,0,0.15);
			`;
			document.body.appendChild(dragImage);
			event.dataTransfer.setDragImage(dragImage, 10, 10);

			// Remove drag image after a short delay
			setTimeout(() => {
				document.body.removeChild(dragImage);
			}, 0);
		},

		onDragEnd() {
			this.draggingUid = null;
		},

		// Context menu methods
		showContextMenu(event, email) {
			this.contextMenuEmail = email;
			this.contextMenuPosition = { x: event.clientX, y: event.clientY };
			this.contextMenuVisible = true;
		},

		onContextMenuSelect({ item, parentItem, action }) {
			const email = this.contextMenuEmail;
			if (!email) return;

			// Check if this is a bulk action (email is part of selection)
			const isBulk = this.selectedUids.has(email.uid) && this.selectedUids.size > 1;
			const uids = isBulk ? Array.from(this.selectedUids) : [email.uid];

			// Handle submenu selections (move-to, copy-to)
			if (parentItem) {
				this.$emit("context-action", {
					action: parentItem.action,
					email,
					targetFolder: item.id,
					uids,
					isBulk,
				});
				return;
			}

			// Handle main actions
			this.$emit("context-action", { action, email, uids, isBulk });
		},

		getMoveToFolders() {
			return this.folders
				.filter((f) => f.name !== this.folder && f.selectable)
				.map((f) => ({
					id: f.name,
					label: this.getFolderDisplayName(f.name),
				}));
		},

		getCopyToFolders() {
			return this.folders
				.filter((f) => f.name !== this.folder && f.selectable)
				.map((f) => ({
					id: f.name,
					label: this.getFolderDisplayName(f.name),
				}));
		},

		getFolderDisplayName(folderName) {
			// Check folder mapping first
			if (this.folderMapping.inbox && folderName === this.folderMapping.inbox)
				return this.__("Inbox");
			if (this.folderMapping.sent && folderName === this.folderMapping.sent)
				return this.__("Sent");
			if (this.folderMapping.drafts && folderName === this.folderMapping.drafts)
				return this.__("Drafts");
			if (this.folderMapping.trash && folderName === this.folderMapping.trash)
				return this.__("Trash");
			if (this.folderMapping.spam && folderName === this.folderMapping.spam)
				return this.__("Spam");
			if (this.folderMapping.archive && folderName === this.folderMapping.archive)
				return this.__("Archive");

			// Return last part of folder name
			const parts = folderName.split("/");
			return parts[parts.length - 1];
		},

		isTrashFolder(folderName) {
			if (this.folderMapping.trash && folderName === this.folderMapping.trash) return true;
			const name = folderName.toLowerCase();
			return (
				name === "trash" ||
				name.includes("trash") ||
				name.includes("deleted") ||
				name.includes("corbeille")
			);
		},

		isSpamFolder(folderName) {
			if (this.folderMapping.spam && folderName === this.folderMapping.spam) return true;
			const name = folderName.toLowerCase();
			return (
				name === "spam" ||
				name === "junk" ||
				name.includes("spam") ||
				name.includes("junk")
			);
		},

		// Methods to update email state from parent component
		updateEmailFlag(uid, flag, value) {
			const email = this.emails.find((e) => e.uid === uid);
			if (email) {
				email[flag] = value;
			}
		},

		removeEmail(uid) {
			const index = this.emails.findIndex((e) => e.uid === uid);
			if (index !== -1) {
				this.emails.splice(index, 1);
				this.total--;
				this.$emit("update:total", this.total);
			}
		},

		// Multi-selection methods
		toggleSelection(email, event) {
			const index = this.emails.findIndex((e) => e.uid === email.uid);

			// Shift+Click for range selection
			if (event?.shiftKey && this.lastSelectedIndex !== -1) {
				const start = Math.min(this.lastSelectedIndex, index);
				const end = Math.max(this.lastSelectedIndex, index);

				for (let i = start; i <= end; i++) {
					this.selectedUids.add(this.emails[i].uid);
				}
				// Force reactivity
				this.selectedUids = new Set(this.selectedUids);
			} else {
				// Toggle normal
				if (this.selectedUids.has(email.uid)) {
					this.selectedUids.delete(email.uid);
				} else {
					this.selectedUids.add(email.uid);
				}
				// Force reactivity
				this.selectedUids = new Set(this.selectedUids);
			}

			this.lastSelectedIndex = index;
			this.$emit("selection-change", {
				count: this.selectedUids.size,
				uids: Array.from(this.selectedUids),
			});
		},

		isSelected(uid) {
			return this.selectedUids.has(uid);
		},

		selectAll() {
			if (this.allSelected) {
				this.selectedUids.clear();
			} else {
				this.emails.forEach((e) => this.selectedUids.add(e.uid));
			}
			// Force reactivity
			this.selectedUids = new Set(this.selectedUids);
			this.$emit("selection-change", {
				count: this.selectedUids.size,
				uids: Array.from(this.selectedUids),
			});
		},

		clearSelection() {
			this.selectedUids.clear();
			this.selectedUids = new Set(this.selectedUids);
			this.lastSelectedIndex = -1;
			this.$emit("selection-change", { count: 0, uids: [] });
		},

		removeFromSelection(uids) {
			uids.forEach((uid) => this.selectedUids.delete(uid));
			this.selectedUids = new Set(this.selectedUids);
			this.$emit("selection-change", {
				count: this.selectedUids.size,
				uids: Array.from(this.selectedUids),
			});
		},

		getSelectedUids() {
			return Array.from(this.selectedUids);
		},

		// Keyboard shortcuts
		onKeydown(event) {
			// Don't handle shortcuts when typing in an input
			if (
				event.target.tagName === "INPUT" ||
				event.target.tagName === "TEXTAREA" ||
				event.target.isContentEditable
			) {
				return;
			}

			// Cmd/Ctrl+A - Select all
			if ((event.metaKey || event.ctrlKey) && event.key === "a") {
				event.preventDefault();
				this.selectAll();
				return;
			}

			// Escape - Clear selection
			if (event.key === "Escape") {
				if (this.selectedUids.size > 0) {
					event.preventDefault();
					this.clearSelection();
				}
				return;
			}

			// Only handle these shortcuts if emails are selected
			if (this.selectedUids.size === 0) return;

			// Delete - Move to trash
			if (event.key === "Delete" || event.key === "Backspace") {
				event.preventDefault();
				if (event.shiftKey) {
					// Shift+Delete - Delete permanently
					this.$emit("context-action", {
						action: "delete-permanent",
						uids: Array.from(this.selectedUids),
						isBulk: this.selectedUids.size > 1,
					});
				} else {
					// Delete - Move to trash
					this.$emit("context-action", {
						action: "trash",
						uids: Array.from(this.selectedUids),
						isBulk: this.selectedUids.size > 1,
					});
				}
				return;
			}

			// e - Archive
			if (event.key === "e" && !event.metaKey && !event.ctrlKey) {
				event.preventDefault();
				this.$emit("context-action", {
					action: "archive",
					uids: Array.from(this.selectedUids),
					isBulk: this.selectedUids.size > 1,
				});
				return;
			}

			// s - Toggle star
			if (event.key === "s" && !event.metaKey && !event.ctrlKey) {
				event.preventDefault();
				this.$emit("context-action", {
					action: "toggle-star",
					uids: Array.from(this.selectedUids),
					isBulk: this.selectedUids.size > 1,
				});
				return;
			}

			// Shift+u - Toggle read/unread
			if (event.key === "u" && event.shiftKey && !event.metaKey && !event.ctrlKey) {
				event.preventDefault();
				// Get first selected email to check current state
				const firstUid = Array.from(this.selectedUids)[0];
				const firstEmail = this.emails.find((e) => e.uid === firstUid);
				const action = firstEmail?.seen ? "mark-unread" : "mark-read";
				this.$emit("context-action", {
					action,
					uids: Array.from(this.selectedUids),
					isBulk: this.selectedUids.size > 1,
				});
				return;
			}
		},
	},
};
</script>

<style scoped>
.email-list-container {
	display: flex;
	flex-direction: column;
	height: 100%;
	background: var(--card-bg, white);
}

/* =====================================================================
   Quick filter chip bar — sits between toolbar and the scrollable list.
   Active chip uses --wm-ink so the contrast pops on the soft bg.
   ===================================================================== */
.filter-chips {
	display: flex;
	gap: 4px;
	padding: 4px 10px 8px;
	font-size: 12px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
}

.chip-filter {
	height: 24px;
	padding: 0 10px;
	border: 0;
	border-radius: 999px;
	background: transparent;
	color: var(--wm-ink-mute, #8d99a6);
	cursor: pointer;
	display: inline-flex;
	align-items: center;
	gap: 5px;
	font-size: 12px;
	font-family: inherit;
	transition: background 0.15s, color 0.15s;
}

.chip-filter:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
	color: var(--wm-ink, #333);
}

.chip-filter.on {
	background: var(--wm-ink, #1a1a1a);
	color: var(--wm-bg-raised, white);
	font-weight: 500;
}

/* In dark mode the active chip would be a bright slab on dark — switch
   it to the brand accent so it reads as "selected" without dazzling. */
:global([data-theme="dark"]) .chip-filter.on {
	background: var(--wm-accent, var(--wm-accent));
	color: #ffffff;
}

.chip-filter .ct {
	font-size: 10.5px;
	background: rgba(0, 0, 0, 0.08);
	padding: 1px 5px;
	border-radius: 999px;
	font-variant-numeric: tabular-nums;
}

.chip-filter.on .ct {
	background: rgba(255, 255, 255, 0.22);
	color: inherit;
}

:global([data-theme="dark"]) .chip-filter .ct {
	background: rgba(255, 255, 255, 0.08);
}

/* =====================================================================
   Sender avatar — 32px circle with a deterministic gradient color
   driven by getAvatarColor(email) in the script. c1..c6 cover the
   palette from the design (indigo / amber / sage / rose / cyan / purple).
   ===================================================================== */
.email-avatar {
	flex-shrink: 0;
	width: 32px;
	height: 32px;
	border-radius: 50%;
	display: grid;
	place-items: center;
	color: white;
	font-size: 12px;
	font-weight: 600;
	letter-spacing: 0.01em;
	align-self: center;
}

.email-avatar.c1 {
	background: linear-gradient(135deg, var(--wm-accent), var(--wm-nora-2));
}
.email-avatar.c2 {
	background: linear-gradient(135deg, #b45309, #f59e0b);
}
.email-avatar.c3 {
	background: linear-gradient(135deg, #047857, #34d399);
}
.email-avatar.c4 {
	background: linear-gradient(135deg, #be185d, #ec4899);
}
.email-avatar.c5 {
	background: linear-gradient(135deg, #0e7490, #06b6d4);
}
.email-avatar.c6 {
	background: linear-gradient(135deg, #6d28d9, #c084fc);
}

/* ========================================================================
   New list header — serif folder title + unread count + minimal icons.
   Replaces the old toolbar that combined search + select-all + refresh.
   ======================================================================== */
.list-header {
	display: flex;
	align-items: baseline;
	gap: 10px;
	padding: 12px 14px 8px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
}

.list-title {
	margin: 0;
	font-family: Forum, Georgia, "Times New Roman", serif;
	font-size: 19px;
	font-weight: 400;
	color: var(--wm-ink, #1a1a1a);
	letter-spacing: -0.005em;
	flex-shrink: 0;
}

.list-count {
	font-size: 11.5px;
	color: var(--wm-ink-mute, #8d99a6);
	font-variant-numeric: tabular-nums;
}

.list-header-right {
	margin-left: auto;
	display: flex;
	align-items: center;
	gap: 4px;
}

.header-icon-btn {
	width: 26px;
	height: 26px;
	display: grid;
	place-items: center;
	border: 0;
	background: transparent;
	border-radius: 6px;
	color: var(--wm-ink-soft, #555);
	cursor: pointer;
	transition: background 0.15s, color 0.15s;
}

.header-icon-btn:hover:not(:disabled) {
	background: var(--wm-bg-sunken, #f5f5f5);
	color: var(--wm-ink, #1a1a1a);
}

.header-icon-btn:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}

.header-icon-btn .rotating {
	animation: rotate 1s linear infinite;
}

.header-checkbox {
	width: 26px;
	height: 26px;
	display: grid;
	place-items: center;
	border-radius: 6px;
	cursor: pointer;
	margin: 0 !important;
}

.header-checkbox:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
}

.header-checkbox input[type="checkbox"] {
	width: 14px;
	height: 14px;
	margin: 0 !important;
	cursor: pointer;
	accent-color: var(--wm-accent, var(--wm-accent));
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
	padding: 10px 5px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	cursor: pointer;
	gap: 6px;
}

.email-row:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.email-row.unread {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.08));
}

.email-row.unread .from {
	font-weight: 600;
}

.email-row.unread .subject-text {
	font-weight: 500;
	color: var(--text-color, #333);
}

/* Active row = the email currently open in the reader.
   Soft horizontal gradient (strong accent on the left fading to transparent)
   + a 4px "guardian" bar on the left (box-shadow inset so it stays visible
   even with the column-resizer's negative margin). */
.email-row.active {
	background: linear-gradient(
		90deg,
		var(--subtle-accent, rgba(36, 144, 239, 0.22)) 0%,
		var(--subtle-accent, rgba(36, 144, 239, 0.1)) 35%,
		transparent 90%
	);
	box-shadow: inset 4px 0 0 0 var(--primary-color, #2490ef);
}

/* Selected rows = multi-selection checkbox state (different from "active"). */
.email-row.selected {
	background: linear-gradient(
		90deg,
		rgba(214, 138, 89, 0.18),
		rgba(214, 138, 89, 0.06) 50%,
		transparent 90%
	);
	box-shadow: inset 4px 0 0 0 var(--primary-color, #2490ef);
}

.email-row.selected.active {
	background: linear-gradient(
		90deg,
		rgba(214, 138, 89, 0.28),
		rgba(214, 138, 89, 0.1) 50%,
		transparent 90%
	);
}

.email-row.dragging {
	opacity: 0.5;
	background: var(--bg-light-gray, #f5f5f5);
}

/* Vertical wrapper that stacks the row checkbox above the star, so the
   horizontal footprint of these two controls is one column instead of two. */
.row-controls {
	flex-shrink: 0;
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 4px;
	padding-top: 3px;
	width: 20px;
}

.checkbox-cell {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 100%;
	height: 14px;
}

.checkbox-cell input[type="checkbox"] {
	width: 14px;
	height: 14px;
	cursor: pointer;
	accent-color: var(--primary-color, #2490ef);
	/* Frappe Desk ships a global "input { margin: 0 5px 0 0 }" rule that
	   shifts the checkbox 2-3 px off-center inside its flex cell. Force it back. */
	margin: 0 !important;
}

.star {
	cursor: pointer;
	width: 100%;
	height: 14px;
	color: var(--text-muted, #999);
	display: flex;
	align-items: center;
	justify-content: center;
	transition: color 0.15s ease;
}

.star:hover {
	color: var(--yellow-500, #eab308);
}

.email-row.flagged .star {
	color: var(--yellow-500, #eab308);
}

.email-content {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.email-top-line {
	display: flex;
	justify-content: space-between;
	align-items: center;
	gap: 12px;
}

.from {
	flex: 1;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	font-size: 14px;
}

.date {
	flex-shrink: 0;
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	white-space: nowrap;
}

.email-bottom-line {
	display: flex;
	align-items: center;
	gap: 8px;
}

.subject-text {
	flex: 1;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	font-size: 13px;
	color: var(--text-muted, #8d99a6);
}

.attachment-icon {
	flex-shrink: 0;
	color: var(--text-muted, #8d99a6);
}

.status-icon {
	flex-shrink: 0;
	margin-left: 4px;
}

.status-icon.replied {
	color: var(--primary-color, #2490ef);
}

.status-icon.forwarded {
	color: var(--text-muted, #8d99a6);
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
	background: var(--success-color, #28a745);
	animation: pulse 2s infinite;
}

@keyframes pulse {
	0%,
	100% {
		opacity: 1;
	}
	50% {
		opacity: 0.4;
	}
}

/* Responsive Design */
@media (max-width: 768px) {
	.email-row {
		padding: 8px 12px;
		gap: 8px;
	}

	.from {
		font-size: 13px;
	}

	.subject-text {
		font-size: 12px;
	}

	.date {
		font-size: 11px;
	}

	.checkbox-cell {
		width: 28px;
	}

	.checkbox-cell input[type="checkbox"] {
		width: 20px;
		height: 20px;
	}
}

@media (max-width: 480px) {
	.email-row {
		padding: 8px 10px;
		gap: 6px;
	}

	.star {
		font-size: 14px;
	}

	.from {
		font-size: 13px;
	}

	.subject-text {
		font-size: 12px;
	}

	.date {
		font-size: 10px;
	}

	.checkbox-cell {
		width: 24px;
	}

	.checkbox-cell input[type="checkbox"] {
		width: 18px;
		height: 18px;
	}
}
</style>
