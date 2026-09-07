<template>
	<div class="folder-tree" :class="{ compact }">
		<!-- Header with create button -->
		<div class="folder-header" v-if="!compact">
			<span class="header-title">{{ __("Dossiers") }}</span>
			<button
				@click="showCreateDialog = true"
				class="btn-create-folder"
				:title="__('Create folder')"
			>
				<Plus :size="16" />
			</button>
		</div>

		<div v-if="loading" class="loading">{{ __("Loading...") }}</div>

		<div v-else class="folder-list">
			<div
				v-for="folder in visibleFolders"
				:key="folder.name"
				class="folder-item"
				:class="{
					selected: folder.name === selectedFolder,
					disabled: !folder.selectable,
					'drag-over': dragOverFolder === folder.name,
				}"
				:style="{ paddingLeft: (compact ? 0 : getFolderIndent(folder)) + 'px' }"
				:title="
					compact
						? getDisplayName(folder) +
						  (folder.unread ? ' (' + folder.unread + ')' : '')
						: null
				"
				@click="selectFolder(folder)"
				@contextmenu.prevent="showContextMenu($event, folder)"
				@dragover.prevent="onDragOver($event, folder)"
				@dragleave="onDragLeave"
				@drop="onDrop($event, folder.name)"
			>
				<component
					:is="getFolderIcon(folder)"
					:size="15"
					:stroke-width="1.5"
					class="folder-icon"
				/>
				<span v-if="!compact" class="folder-name">{{ getDisplayName(folder) }}</span>
				<span v-if="folder.unread && !compact" class="unread-count">{{
					folder.unread
				}}</span>
				<span v-else-if="folder.unread" class="unread-dot"></span>
				<!-- Expand/Collapse chevron on the right (only for parent folders).
				     Kept last so it lives on the trailing edge and the name can use
				     the full remaining width. -->
				<button
					v-if="hasChildren(folder) && !compact"
					@click.stop="toggleFolder(folder)"
					class="expand-btn"
					:title="isCollapsed(folder) ? __('Expand') : __('Collapse')"
				>
					<ChevronRight :size="14" :class="{ rotated: !isCollapsed(folder) }" />
				</button>
			</div>
		</div>

		<!-- Context Menu -->
		<ContextMenu
			:visible="contextMenuVisible"
			:position="contextMenuPosition"
			:items="contextMenuItems"
			@select="onContextMenuSelect"
			@close="contextMenuVisible = false"
		/>

		<!-- Rename folder dialog -->
		<div
			v-if="showRenameDialog"
			class="create-folder-overlay"
			@click.self="showRenameDialog = false"
		>
			<div class="create-folder-dialog">
				<div class="dialog-header">
					<h4>{{ __("Rename folder") }}</h4>
					<button @click="showRenameDialog = false" class="close-btn">
						<X :size="18" />
					</button>
				</div>
				<div class="dialog-body">
					<div class="form-group">
						<label>{{ __("New name") }}</label>
						<input
							v-model="renameFolderName"
							type="text"
							class="form-control"
							:placeholder="__('Enter new name')"
							@keyup.enter="renameFolder"
							ref="renameFolderInput"
						/>
					</div>
				</div>
				<div class="dialog-footer">
					<button @click="showRenameDialog = false" class="btn btn-secondary">
						{{ __("Cancel") }}
					</button>
					<button
						@click="renameFolder"
						class="btn btn-primary"
						:disabled="!renameFolderName.trim() || renamingFolder"
					>
						<span v-if="renamingFolder">{{ __("Renaming...") }}</span>
						<span v-else>{{ __("Rename") }}</span>
					</button>
				</div>
			</div>
		</div>

		<!-- Create folder dialog -->
		<div
			v-if="showCreateDialog"
			class="create-folder-overlay"
			@click.self="showCreateDialog = false"
		>
			<div class="create-folder-dialog">
				<div class="dialog-header">
					<h4>{{ __("Create folder") }}</h4>
					<button @click="showCreateDialog = false" class="close-btn">
						<X :size="18" />
					</button>
				</div>
				<div class="dialog-body">
					<div class="form-group">
						<label>{{ __("Location") }}</label>
						<select v-model="newFolderParent" class="form-control">
							<option value="">{{ __("Root level") }}</option>
							<option v-for="f in selectableFolders" :key="f.name" :value="f.name">
								{{ f.name }}
							</option>
						</select>
					</div>
					<div class="form-group">
						<label>{{ __("Folder name") }}</label>
						<input
							v-model="newFolderName"
							type="text"
							class="form-control"
							:placeholder="__('Enter folder name')"
							@keyup.enter="createFolder"
							ref="folderNameInput"
						/>
					</div>
				</div>
				<div class="dialog-footer">
					<button @click="showCreateDialog = false" class="btn btn-secondary">
						{{ __("Cancel") }}
					</button>
					<button
						@click="createFolder"
						class="btn btn-primary"
						:disabled="!newFolderName.trim() || creatingFolder"
					>
						<span v-if="creatingFolder">{{ __("Creating...") }}</span>
						<span v-else>{{ __("Create") }}</span>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<script>
import {
	Inbox,
	Send,
	FileEdit,
	Trash2,
	AlertTriangle,
	Archive,
	Star,
	AlertCircle,
	Folder,
	FolderOpen,
	Plus,
	X,
	ChevronRight,
	FolderPlus,
	Pencil,
	MailCheck,
	FolderX,
} from "lucide-vue-next";
import ContextMenu from "./ContextMenu.vue";

export default {
	name: "FolderTree",

	components: {
		Inbox,
		Send,
		FileEdit,
		Trash2,
		AlertTriangle,
		Archive,
		Star,
		AlertCircle,
		Folder,
		FolderOpen,
		Plus,
		X,
		ChevronRight,
		FolderPlus,
		Pencil,
		MailCheck,
		FolderX,
		ContextMenu,
	},

	props: {
		account: { type: String, required: true },
		accountEmail: { type: String, default: "" },
		selectedFolder: { type: String, default: "INBOX" },
		// Icon-rail mode (folder column collapsed): icons + tooltips, no labels,
		// no nesting chevrons — the whole tree stays reachable at 56px wide.
		compact: { type: Boolean, default: false },
	},

	emits: ["select", "drop-email", "folder-mapping-loaded"],

	data() {
		return {
			folders: [],
			collapsedFolders: [],
			folderMapping: {
				inbox: "",
				sent: "",
				drafts: "",
				trash: "",
				spam: "",
				archive: "",
			},
			loading: false,
			showCreateDialog: false,
			newFolderName: "",
			newFolderParent: "",
			creatingFolder: false,
			dragOverFolder: null,
			// Context menu
			contextMenuVisible: false,
			contextMenuPosition: { x: 0, y: 0 },
			contextMenuFolder: null,
			// Rename dialog
			showRenameDialog: false,
			renameFolderName: "",
			renamingFolder: false,
		};
	},

	computed: {
		protectedFolders() {
			return ["inbox", "sent", "drafts", "trash", "spam", "junk", "archive"];
		},

		contextMenuItems() {
			if (!this.contextMenuFolder) return [];

			const folder = this.contextMenuFolder;
			const folderName = folder.name.toLowerCase();
			const isProtected = this.isProtectedFolder(folder.name);
			const isTrashOrSpam =
				this.isTrashFolder(folder.name) || this.isSpamFolder(folder.name);

			const items = [
				{
					id: "create-subfolder",
					label: this.__("Create subfolder"),
					icon: FolderPlus,
					action: "create-subfolder",
				},
				{
					id: "rename",
					label: this.__("Rename"),
					icon: Pencil,
					action: "rename",
					disabled: isProtected,
				},
				{ separator: true },
				{
					id: "mark-all-read",
					label: this.__("Mark all as read"),
					icon: MailCheck,
					action: "mark-all-read",
				},
				{ separator: true },
			];

			// Only show "Empty folder" for Trash/Spam
			if (isTrashOrSpam) {
				items.push({
					id: "empty-folder",
					label: this.__("Empty folder"),
					icon: Trash2,
					action: "empty-folder",
					danger: true,
				});
			}

			// Only show "Delete folder" for non-protected folders
			if (!isProtected) {
				items.push({
					id: "delete-folder",
					label: this.__("Delete folder"),
					icon: FolderX,
					action: "delete-folder",
					danger: true,
				});
			}

			return items;
		},

		sortedFolders() {
			// Sort folders: INBOX first, then special folders, then alphabetically
			const specialOrder = ["INBOX", "Sent", "Drafts", "Trash", "Spam", "Junk", "Archive"];

			return [...this.folders].sort((a, b) => {
				const aName = a.name.toUpperCase();
				const bName = b.name.toUpperCase();

				const aIndex = specialOrder.findIndex(
					(s) => aName === s.toUpperCase() || aName.endsWith("/" + s.toUpperCase())
				);
				const bIndex = specialOrder.findIndex(
					(s) => bName === s.toUpperCase() || bName.endsWith("/" + s.toUpperCase())
				);

				if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex;
				if (aIndex !== -1) return -1;
				if (bIndex !== -1) return 1;
				return a.name.localeCompare(b.name);
			});
		},

		visibleFolders() {
			// Filter out folders whose parent is collapsed
			return this.sortedFolders.filter((folder) => {
				const delimiter = folder.delimiter || "/";
				const parts = folder.name.split(delimiter);

				// Check if any parent folder is collapsed
				for (let i = 1; i < parts.length; i++) {
					const parentPath = parts.slice(0, i).join(delimiter);
					if (this.collapsedFolders.includes(parentPath)) {
						return false;
					}
				}
				return true;
			});
		},

		selectableFolders() {
			// Filter folders that can have subfolders (exclude special flags like \Noselect)
			return this.folders.filter((f) => f.selectable);
		},
	},

	watch: {
		account: {
			immediate: true,
			async handler() {
				await Promise.all([this.loadPreferences(), this.loadFolderMapping()]);
				this.loadFolders();
			},
		},
		showCreateDialog(val) {
			if (val) {
				// Focus input when dialog opens
				this.$nextTick(() => {
					if (this.$refs.folderNameInput) {
						this.$refs.folderNameInput.focus();
					}
				});
			} else {
				// Reset form when dialog closes
				this.newFolderName = "";
				this.newFolderParent = "";
			}
		},
		showRenameDialog(val) {
			if (!val) {
				// Reset form when dialog closes
				this.renameFolderName = "";
			}
		},
	},

	methods: {
		async loadPreferences() {
			if (!this.account) return;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_ui_preferences",
					args: { account_name: this.account },
				});

				if (response.message?.collapsed_folders) {
					this.collapsedFolders = response.message.collapsed_folders;
				}
			} catch (error) {
				// Silently fail - use default empty array
				this.collapsedFolders = [];
			}
		},

		async loadFolderMapping() {
			if (!this.account) return;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_folder_mapping",
					args: { account_name: this.account },
				});

				if (response.message?.effective) {
					this.folderMapping = response.message.effective;
					// Emit mapping to parent component for use in email operations
					this.$emit("folder-mapping-loaded", this.folderMapping);
				}
			} catch (error) {
				// Silently fail - use default empty mapping
				console.warn("Failed to load folder mapping:", error);
			}
		},

		async saveCollapsedFolders() {
			if (!this.account) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.save_ui_preferences",
					args: {
						account_name: this.account,
						collapsed_folders: JSON.stringify(this.collapsedFolders),
					},
				});
			} catch (error) {
				// Silently fail
			}
		},

		hasChildren(folder) {
			const delimiter = folder.delimiter || "/";
			const prefix = folder.name + delimiter;
			return this.folders.some((f) => f.name.startsWith(prefix));
		},

		isCollapsed(folder) {
			return this.collapsedFolders.includes(folder.name);
		},

		toggleFolder(folder) {
			const index = this.collapsedFolders.indexOf(folder.name);
			if (index === -1) {
				// Collapse
				this.collapsedFolders.push(folder.name);
			} else {
				// Expand
				this.collapsedFolders.splice(index, 1);
			}
			// Save to account preferences
			this.saveCollapsedFolders();
		},

		async loadFolders() {
			if (!this.account) return;

			this.loading = true;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_folders",
					args: {
						account_name: this.account,
					},
				});

				this.folders = response.message || [];
			} catch (error) {
				frappe.toast({ message: this.__("Error loading folders"), indicator: "red" });
			} finally {
				this.loading = false;
			}
		},

		selectFolder(folder) {
			if (folder.selectable) {
				this.$emit("select", folder.name);
			}
		},

		async createFolder() {
			if (!this.newFolderName.trim() || this.creatingFolder) return;

			this.creatingFolder = true;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.create_folder",
					args: {
						account_name: this.account,
						folder_name: this.newFolderName.trim(),
						parent_folder: this.newFolderParent || null,
					},
				});

				frappe.toast({
					message: this.__("Folder created"),
					indicator: "green",
				});

				this.showCreateDialog = false;
				this.loadFolders();
			} catch (error) {
				frappe.toast({
					message: error.message || this.__("Error creating folder"),
					indicator: "red",
				});
			} finally {
				this.creatingFolder = false;
			}
		},

		// Drag and drop handlers
		onDragOver(event, folder) {
			if (!folder.selectable) return;
			event.dataTransfer.dropEffect = "move";
			this.dragOverFolder = folder.name;
		},

		onDragLeave() {
			this.dragOverFolder = null;
		},

		onDrop(event, folderName) {
			this.dragOverFolder = null;

			const data = event.dataTransfer.getData("application/json");
			if (data) {
				try {
					const emailData = JSON.parse(data);
					this.$emit("drop-email", { targetFolder: folderName, email: emailData });
				} catch (e) {
					console.error("Invalid drop data:", e);
				}
			}
		},

		getFolderIcon(folder) {
			const name = folder.name;
			const nameLower = name.toLowerCase();
			const flags = folder.flags || [];

			// Check folder mapping first (configured or auto-detected)
			if (this.folderMapping.inbox && name === this.folderMapping.inbox) return Inbox;
			if (this.folderMapping.sent && name === this.folderMapping.sent) return Send;
			if (this.folderMapping.drafts && name === this.folderMapping.drafts) return FileEdit;
			if (this.folderMapping.trash && name === this.folderMapping.trash) return Trash2;
			if (this.folderMapping.spam && name === this.folderMapping.spam) return AlertTriangle;
			if (this.folderMapping.archive && name === this.folderMapping.archive) return Archive;

			// Check IMAP special-use flags
			if (flags.includes("\\Inbox") || nameLower === "inbox") return Inbox;
			if (flags.includes("\\Sent")) return Send;
			if (flags.includes("\\Drafts")) return FileEdit;
			if (flags.includes("\\Trash")) return Trash2;
			if (flags.includes("\\Junk") || flags.includes("\\Spam")) return AlertTriangle;
			if (flags.includes("\\Archive")) return Archive;
			if (flags.includes("\\Flagged") || flags.includes("\\Starred")) return Star;
			if (flags.includes("\\Important")) return AlertCircle;
			if (flags.includes("\\All")) return Folder;

			// Fallback to name-based detection
			if (nameLower === "inbox") return Inbox;
			if (nameLower.includes("sent")) return Send;
			if (nameLower.includes("draft")) return FileEdit;
			if (
				nameLower.includes("trash") ||
				nameLower.includes("deleted") ||
				nameLower.includes("corbeille")
			)
				return Trash2;
			if (nameLower.includes("spam") || nameLower.includes("junk")) return AlertTriangle;
			if (nameLower.includes("archive")) return Archive;
			if (nameLower.includes("starred") || nameLower.includes("important")) return Star;

			return Folder;
		},

		getDisplayName(folder) {
			const fullName = folder.name;

			// Check folder mapping first - return translated name for mapped folders
			if (this.folderMapping.inbox && fullName === this.folderMapping.inbox)
				return this.__("Inbox");
			if (this.folderMapping.sent && fullName === this.folderMapping.sent)
				return this.__("Sent");
			if (this.folderMapping.drafts && fullName === this.folderMapping.drafts)
				return this.__("Drafts");
			if (this.folderMapping.trash && fullName === this.folderMapping.trash)
				return this.__("Trash");
			if (this.folderMapping.spam && fullName === this.folderMapping.spam)
				return this.__("Spam");
			if (this.folderMapping.archive && fullName === this.folderMapping.archive)
				return this.__("Archive");

			// Remove prefix path and show just the folder name
			const parts = fullName.split(folder.delimiter || "/");
			const name = parts[parts.length - 1];

			// Translate common folder names
			const translations = {
				INBOX: this.__("Inbox"),
				Sent: this.__("Sent"),
				"Sent Items": this.__("Sent"),
				"Sent Mail": this.__("Sent"),
				Drafts: this.__("Drafts"),
				Trash: this.__("Trash"),
				"Deleted Items": this.__("Trash"),
				Spam: this.__("Spam"),
				Junk: this.__("Spam"),
				"Junk E-mail": this.__("Spam"),
				Archive: this.__("Archive"),
				Starred: this.__("Starred"),
				Important: this.__("Important"),
			};

			return translations[name] || name;
		},

		getFolderIndent(folder) {
			// Calculate indentation based on folder depth.
			// Small base padding so the icon sits close to the left edge - we want
			// to give the folder name as much horizontal room as possible.
			const depth = (folder.name.match(/\//g) || []).length;
			return 8 + depth * 20;
		},

		// Context menu methods
		showContextMenu(event, folder) {
			this.contextMenuFolder = folder;
			this.contextMenuPosition = { x: event.clientX, y: event.clientY };
			this.contextMenuVisible = true;
		},

		onContextMenuSelect({ item, action }) {
			const folder = this.contextMenuFolder;
			if (!folder) return;

			switch (action) {
				case "create-subfolder":
					this.newFolderParent = folder.name;
					this.showCreateDialog = true;
					break;

				case "rename":
					this.startRenameFolder(folder);
					break;

				case "mark-all-read":
					this.markFolderAsRead(folder);
					break;

				case "empty-folder":
					this.emptyFolder(folder);
					break;

				case "delete-folder":
					this.deleteFolder(folder);
					break;
			}
		},

		isProtectedFolder(folderName) {
			const name = folderName.toLowerCase();
			const lastPart = name.split("/").pop();

			// Check folder mapping
			if (this.folderMapping.inbox && folderName === this.folderMapping.inbox) return true;
			if (this.folderMapping.sent && folderName === this.folderMapping.sent) return true;
			if (this.folderMapping.drafts && folderName === this.folderMapping.drafts) return true;
			if (this.folderMapping.trash && folderName === this.folderMapping.trash) return true;
			if (this.folderMapping.spam && folderName === this.folderMapping.spam) return true;
			if (this.folderMapping.archive && folderName === this.folderMapping.archive)
				return true;

			// Check common names
			return (
				this.protectedFolders.includes(name) || this.protectedFolders.includes(lastPart)
			);
		},

		isTrashFolder(folderName) {
			if (this.folderMapping.trash && folderName === this.folderMapping.trash) return true;
			const name = folderName.toLowerCase();
			return (
				name.includes("trash") || name.includes("deleted") || name.includes("corbeille")
			);
		},

		isSpamFolder(folderName) {
			if (this.folderMapping.spam && folderName === this.folderMapping.spam) return true;
			const name = folderName.toLowerCase();
			return name.includes("spam") || name.includes("junk");
		},

		startRenameFolder(folder) {
			// Get just the folder name (last part of path)
			const parts = folder.name.split("/");
			this.renameFolderName = parts[parts.length - 1];
			this.showRenameDialog = true;

			this.$nextTick(() => {
				if (this.$refs.renameFolderInput) {
					this.$refs.renameFolderInput.focus();
					this.$refs.renameFolderInput.select();
				}
			});
		},

		async renameFolder() {
			if (!this.renameFolderName.trim() || this.renamingFolder) return;

			const folder = this.contextMenuFolder;
			if (!folder) return;

			this.renamingFolder = true;

			try {
				// Build new folder name preserving path
				const parts = folder.name.split("/");
				parts[parts.length - 1] = this.renameFolderName.trim();
				const newName = parts.join("/");

				await frappe.call({
					method: "frappe_webmail.webmail_api.rename_folder",
					args: {
						account_name: this.account,
						old_name: folder.name,
						new_name: newName,
					},
				});

				frappe.toast({
					message: this.__("Folder renamed"),
					indicator: "green",
				});

				this.showRenameDialog = false;
				this.renameFolderName = "";
				this.loadFolders();
			} catch (error) {
				frappe.toast({
					message: error.message || this.__("Error renaming folder"),
					indicator: "red",
				});
			} finally {
				this.renamingFolder = false;
			}
		},

		async markFolderAsRead(folder) {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.mark_folder_read",
					args: {
						account_name: this.account,
						folder: folder.name,
					},
				});

				const count = response.message?.marked_count || 0;
				frappe.toast({
					message: this.__("{0} emails marked as read", [count]),
					indicator: "green",
				});

				// Refresh folders to update unread count
				this.loadFolders();
			} catch (error) {
				frappe.toast({
					message: error.message || this.__("Error"),
					indicator: "red",
				});
			}
		},

		async emptyFolder(folder) {
			frappe.confirm(
				this.__(
					"Are you sure you want to permanently delete all emails in this folder? This action cannot be undone."
				),
				async () => {
					try {
						const response = await frappe.call({
							method: "frappe_webmail.webmail_api.empty_folder",
							args: {
								account_name: this.account,
								folder: folder.name,
							},
						});

						const count = response.message?.deleted_count || 0;
						frappe.toast({
							message: this.__("{0} emails deleted", [count]),
							indicator: "green",
						});

						// Refresh folders
						this.loadFolders();
					} catch (error) {
						frappe.toast({
							message: error.message || this.__("Error"),
							indicator: "red",
						});
					}
				}
			);
		},

		async deleteFolder(folder) {
			frappe.confirm(
				this.__(
					"Are you sure you want to delete the folder '{0}'? This action cannot be undone.",
					[folder.name]
				),
				async () => {
					try {
						await frappe.call({
							method: "frappe_webmail.webmail_api.delete_folder",
							args: {
								account_name: this.account,
								folder_name: folder.name,
							},
						});

						frappe.toast({
							message: this.__("Folder deleted"),
							indicator: "green",
						});

						// Refresh folders
						this.loadFolders();

						// If deleted folder was selected, switch to INBOX
						if (this.selectedFolder === folder.name) {
							this.$emit("select", "INBOX");
						}
					} catch (error) {
						frappe.toast({
							message: error.message || this.__("Error deleting folder"),
							indicator: "red",
						});
					}
				}
			);
		},
	},
};
</script>

<style scoped>
.folder-tree {
	display: flex;
	flex-direction: column;
	height: 100%;
	/* Transparent so the FolderTree inherits the surrounding sidebar
	   surface (no white card behind the folders list). */
	background: transparent;
	padding: 0;
}

/* Harmonized with .sb-section style in Webmail.vue: no border-bottom,
   compact padding, small uppercase muted label — and a "+" add button. */
.folder-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 14px 14px 6px;
}

.header-title {
	font-size: 10.5px;
	font-weight: 600;
	text-transform: uppercase;
	color: var(--text-muted, #8d99a6);
	letter-spacing: 0.08em;
}

.btn-create-folder {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 28px;
	height: 28px;
	border: none;
	border-radius: 6px;
	background: transparent;
	color: var(--text-muted, #8d99a6);
	cursor: pointer;
	transition: all 0.15s ease;
}

.btn-create-folder:hover {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	color: var(--primary-color, #2490ef);
}

.loading {
	padding: 16px;
	color: var(--text-muted, #8d99a6);
	text-align: center;
}

.folder-list {
	display: flex;
	flex-direction: column;
	padding: 8px 0;
}

.folder-item {
	display: flex;
	align-items: center;
	padding: 7px 12px;
	cursor: pointer;
	gap: 10px;
	transition: background 0.15s ease;
	margin: 0 6px;
	border-radius: 7px;
}

.folder-item:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.folder-item.selected {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	color: var(--primary-color, #2490ef);
	font-weight: 600;
}

.folder-item.selected .folder-icon,
.folder-item.selected .folder-name {
	color: var(--primary-color, #2490ef);
}

.folder-item.disabled {
	opacity: 0.5;
	cursor: not-allowed;
}

.folder-item.drag-over {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.25));
	border-left-color: var(--primary-color, #2490ef);
}

.expand-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 18px;
	height: 18px;
	border: none;
	border-radius: 4px;
	background: transparent;
	color: var(--text-muted, #8d99a6);
	cursor: pointer;
	padding: 0;
	flex-shrink: 0;
	transition: all 0.15s ease;
}

.expand-btn:hover {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	color: var(--primary-color, #2490ef);
}

.expand-btn svg {
	transition: transform 0.2s ease;
}

.expand-btn svg.rotated {
	transform: rotate(90deg);
}

.folder-icon {
	flex-shrink: 0;
	color: var(--text-muted, #8d99a6);
}

.folder-name {
	flex: 1;
	font-size: 12.5px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	color: var(--text-color, #333);
}

.unread-count {
	background: var(--primary-color, #2490ef);
	color: white;
	font-size: 10.5px;
	padding: 1px 7px;
	border-radius: 999px;
	min-width: 18px;
	text-align: center;
	font-weight: 600;
	font-variant-numeric: tabular-nums;
}

/* Create folder dialog */
.create-folder-overlay {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	background: rgba(0, 0, 0, 0.5);
	display: flex;
	align-items: center;
	justify-content: center;
	z-index: 1100;
}

.create-folder-dialog {
	background: var(--card-bg, white);
	border-radius: 8px;
	width: 400px;
	max-width: 90vw;
	box-shadow: var(--shadow-lg, 0 4px 20px rgba(0, 0, 0, 0.2));
}

.dialog-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 16px 20px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.dialog-header h4 {
	margin: 0;
	font-size: 16px;
	font-weight: 600;
	color: var(--text-color, #333);
}

.close-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 32px;
	height: 32px;
	border: none;
	border-radius: 6px;
	background: transparent;
	color: var(--text-muted, #8d99a6);
	cursor: pointer;
	transition: all 0.15s ease;
}

.close-btn:hover {
	background: var(--bg-light-gray, #f5f5f5);
	color: var(--text-color, #333);
}

.dialog-body {
	padding: 20px;
}

.form-group {
	margin-bottom: 16px;
}

.form-group:last-child {
	margin-bottom: 0;
}

.form-group label {
	display: block;
	margin-bottom: 6px;
	font-size: 13px;
	font-weight: 500;
	color: var(--text-color, #333);
}

.form-control {
	width: 100%;
	padding: 10px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	font-size: 14px;
	background: var(--card-bg, white);
	color: var(--text-color, #333);
	transition: border-color 0.15s ease;
}

select.form-control {
	appearance: auto;
	-webkit-appearance: menulist;
	-moz-appearance: menulist;
	background-color: white !important;
	color: #333 !important;
	-webkit-text-fill-color: #333 !important;
	opacity: 1 !important;
	height: auto !important;
	min-height: 42px !important;
}

select.form-control option {
	background-color: white !important;
	color: #333 !important;
	-webkit-text-fill-color: #333 !important;
}

.create-folder-dialog select {
	color: #333 !important;
	-webkit-text-fill-color: #333 !important;
}

.form-control:focus {
	outline: none;
	border-color: var(--primary-color, #2490ef);
}

.dialog-footer {
	display: flex;
	justify-content: flex-end;
	gap: 10px;
	padding: 16px 20px;
	border-top: 1px solid var(--border-color, #e5e5e5);
	background: var(--bg-light-gray, #fafafa);
	border-radius: 0 0 8px 8px;
}

.btn {
	padding: 10px 18px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	font-size: 14px;
	font-weight: 500;
	cursor: pointer;
	transition: all 0.15s ease;
}

.btn-secondary {
	background: var(--card-bg, white);
	color: var(--text-color, #333);
}

.btn-secondary:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.btn-primary {
	background: var(--primary-color, #2490ef);
	color: white;
	border-color: var(--primary-color, #2490ef);
}

.btn-primary:hover:not(:disabled) {
	background: var(--primary-dark, #1a7fd4);
}

.btn-primary:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}

/* ===== Compact icon rail (folder column collapsed) ===== */
.folder-tree.compact .folder-list {
	padding: 10px 0;
	align-items: center;
	gap: 2px;
}

.folder-tree.compact .folder-item {
	width: 36px;
	height: 36px;
	padding: 0;
	margin: 0;
	gap: 0;
	justify-content: center;
	position: relative;
}

.folder-tree.compact .folder-icon {
	color: var(--text-color, #333);
}

.folder-tree.compact .folder-item.selected .folder-icon {
	color: var(--primary-color, #2490ef);
}

/* Unread marker when there is no room for a count */
.folder-tree.compact .unread-dot {
	position: absolute;
	top: 6px;
	right: 6px;
	width: 7px;
	height: 7px;
	border-radius: 50%;
	background: var(--primary-color, #2490ef);
	box-shadow: 0 0 0 2px var(--card-bg, #fff);
}
</style>
