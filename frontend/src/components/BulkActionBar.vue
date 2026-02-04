<template>
	<Transition name="slide-down">
		<div v-if="selectedCount > 0" class="bulk-action-bar">
			<div class="selection-info">
				<button @click="$emit('clear')" class="btn-clear" :title="__('Clear selection')">
					<X :size="16" />
				</button>
				<span class="selection-count">{{ selectedCount }}</span>
			</div>

			<div class="bulk-actions">
				<!-- Main actions -->
				<button @click="$emit('archive')" :title="__('Archive')" class="action-btn">
					<Archive :size="18" />
				</button>
				<button @click="$emit('delete')" :title="__('Move to Trash')" class="action-btn">
					<Trash2 :size="18" />
				</button>
				<button @click="$emit('mark-read')" :title="__('Mark as read')" class="action-btn">
					<MailOpen :size="18" />
				</button>
				<button
					@click="$emit('mark-unread')"
					:title="__('Mark as unread')"
					class="action-btn"
				>
					<Mail :size="18" />
				</button>

				<div class="separator"></div>

				<!-- Move to dropdown -->
				<div class="dropdown" ref="moveDropdown">
					<button
						@click="toggleMoveMenu"
						class="action-btn dropdown-trigger"
						:title="__('Move to')"
					>
						<FolderInput :size="18" />
						<ChevronDown :size="14" />
					</button>
					<div v-if="showMoveMenu" class="dropdown-menu">
						<div
							v-for="folder in availableFolders"
							:key="folder.name"
							class="dropdown-item"
							@click="selectMoveFolder(folder.name)"
						>
							<Folder :size="14" />
							<span>{{ folder.displayName }}</span>
						</div>
						<div v-if="!availableFolders.length" class="dropdown-empty">
							{{ __("No folders available") }}
						</div>
					</div>
				</div>

				<!-- More menu -->
				<div class="dropdown" ref="moreDropdown">
					<button @click="toggleMoreMenu" class="action-btn dropdown-trigger">
						<MoreHorizontal :size="18" />
					</button>
					<div v-if="showMoreMenu" class="dropdown-menu">
						<div class="dropdown-item" @click="handleAction('toggle-star')">
							<Star :size="16" />
							<span>{{ __("Toggle star") }}</span>
						</div>
						<div class="dropdown-item" @click="handleAction('spam')">
							<AlertTriangle :size="16" />
							<span>{{ __("Mark as spam") }}</span>
						</div>
						<div class="dropdown-separator"></div>
						<div
							class="dropdown-item danger"
							@click="handleAction('delete-permanent')"
						>
							<Trash2 :size="16" />
							<span>{{ __("Delete permanently") }}</span>
						</div>
					</div>
				</div>
			</div>
		</div>
	</Transition>
</template>

<script>
import {
	X,
	Archive,
	Trash2,
	MailOpen,
	Mail,
	FolderInput,
	ChevronDown,
	MoreHorizontal,
	Star,
	AlertTriangle,
	Folder,
} from "lucide-vue-next";

export default {
	name: "BulkActionBar",

	components: {
		X,
		Archive,
		Trash2,
		MailOpen,
		Mail,
		FolderInput,
		ChevronDown,
		MoreHorizontal,
		Star,
		AlertTriangle,
		Folder,
	},

	props: {
		selectedCount: { type: Number, required: true },
		folders: { type: Array, default: () => [] },
		currentFolder: { type: String, default: "" },
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

	emits: [
		"clear",
		"archive",
		"delete",
		"mark-read",
		"mark-unread",
		"move",
		"toggle-star",
		"spam",
		"delete-permanent",
	],

	data() {
		return {
			showMoveMenu: false,
			showMoreMenu: false,
		};
	},

	computed: {
		availableFolders() {
			return this.folders
				.filter((f) => f.name !== this.currentFolder && f.selectable)
				.map((f) => ({
					name: f.name,
					displayName: this.getFolderDisplayName(f.name),
				}));
		},
	},

	mounted() {
		document.addEventListener("click", this.handleClickOutside);
	},

	beforeUnmount() {
		document.removeEventListener("click", this.handleClickOutside);
	},

	methods: {
		toggleMoveMenu() {
			this.showMoveMenu = !this.showMoveMenu;
			this.showMoreMenu = false;
		},

		toggleMoreMenu() {
			this.showMoreMenu = !this.showMoreMenu;
			this.showMoveMenu = false;
		},

		handleClickOutside(event) {
			if (this.$refs.moveDropdown && !this.$refs.moveDropdown.contains(event.target)) {
				this.showMoveMenu = false;
			}
			if (this.$refs.moreDropdown && !this.$refs.moreDropdown.contains(event.target)) {
				this.showMoreMenu = false;
			}
		},

		selectMoveFolder(folderName) {
			this.$emit("move", folderName);
			this.showMoveMenu = false;
		},

		handleAction(action) {
			this.$emit(action);
			this.showMoreMenu = false;
		},

		getFolderDisplayName(folderName) {
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

			const parts = folderName.split("/");
			return parts[parts.length - 1];
		},
	},
};
</script>

<style scoped>
.bulk-action-bar {
	display: flex !important;
	flex-direction: row !important;
	align-items: center !important;
	justify-content: space-between !important;
	padding: 8px 16px !important;
	background: var(--primary-color, #2490ef) !important;
	color: white !important;
	border-radius: 8px 8px 0 0 !important;
	box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15) !important;
	z-index: 10;
}

.selection-info {
	display: flex !important;
	flex-direction: row !important;
	align-items: center !important;
	gap: 8px !important;
}

.btn-clear {
	display: flex !important;
	align-items: center !important;
	justify-content: center !important;
	width: 28px !important;
	height: 28px !important;
	padding: 0 !important;
	border: none !important;
	background: rgba(255, 255, 255, 0.2) !important;
	color: white !important;
	border-radius: 4px !important;
	cursor: pointer;
	transition: background 0.15s ease;
}

.btn-clear:hover {
	background: rgba(255, 255, 255, 0.3) !important;
}

.selection-count {
	font-size: 14px !important;
	font-weight: 600 !important;
	color: white !important;
}

.bulk-actions {
	display: flex !important;
	flex-direction: row !important;
	align-items: center !important;
	gap: 4px !important;
}

.separator {
	width: 1px !important;
	height: 24px !important;
	background: rgba(255, 255, 255, 0.3) !important;
	margin: 0 8px !important;
}

.action-btn {
	display: inline-flex !important;
	align-items: center !important;
	gap: 4px !important;
	padding: 6px 8px !important;
	border: none !important;
	background: transparent !important;
	color: white !important;
	border-radius: 4px !important;
	cursor: pointer;
	transition: background 0.15s ease;
	font-size: 13px;
}

.action-btn:hover {
	background: rgba(255, 255, 255, 0.2) !important;
}

.dropdown {
	position: relative;
	display: inline-block !important;
}

.dropdown-trigger {
	display: inline-flex !important;
	align-items: center !important;
	gap: 4px !important;
}

.dropdown-menu {
	position: absolute;
	top: 100%;
	right: 0;
	margin-top: 4px;
	min-width: 180px;
	max-height: 300px;
	overflow-y: auto;
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
	z-index: 100;
}

.dropdown-item {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 10px 14px;
	color: var(--text-color, #333);
	cursor: pointer;
	transition: background 0.15s ease;
	font-size: 13px;
}

.dropdown-item:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.dropdown-item.danger {
	color: var(--red-500, #dc2626);
}

.dropdown-item.danger:hover {
	background: rgba(220, 38, 38, 0.1);
}

.dropdown-separator {
	height: 1px;
	background: var(--border-color, #e5e5e5);
	margin: 4px 0;
}

.dropdown-empty {
	padding: 12px 14px;
	color: var(--text-muted, #8d99a6);
	font-size: 13px;
	text-align: center;
}

/* Slide animation */
.slide-down-enter-active,
.slide-down-leave-active {
	transition: all 0.2s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
	transform: translateY(-100%);
	opacity: 0;
}

/* Responsive */
@media (max-width: 640px) {
	.bulk-action-bar {
		padding: 6px 12px;
	}

	.action-btn {
		padding: 6px 8px;
	}

	.separator {
		margin: 0 4px;
	}
}
</style>
