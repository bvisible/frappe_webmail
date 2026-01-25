<template>
	<div class="folder-tree">
		<div v-if="loading" class="loading">Chargement...</div>

		<div v-else class="folder-list">
			<div
				v-for="folder in sortedFolders"
				:key="folder.name"
				class="folder-item"
				:class="{
					selected: folder.name === selectedFolder,
					disabled: !folder.selectable,
				}"
				:style="{ paddingLeft: getFolderIndent(folder) + 'px' }"
				@click="selectFolder(folder)"
			>
				<span class="folder-icon">{{ getFolderIcon(folder) }}</span>
				<span class="folder-name">{{ getDisplayName(folder) }}</span>
				<span v-if="folder.unread" class="unread-count">{{ folder.unread }}</span>
			</div>
		</div>
	</div>
</template>

<script>
export default {
	name: "FolderTree",

	props: {
		account: { type: String, required: true },
		accountEmail: { type: String, default: "" },
		selectedFolder: { type: String, default: "INBOX" },
	},

	emits: ["select"],

	data() {
		return {
			folders: [],
			loading: false,
		};
	},

	computed: {
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
	},

	watch: {
		account: {
			immediate: true,
			handler() {
				this.loadFolders();
			},
		},
	},

	methods: {
		async loadFolders() {
			if (!this.account) return;

			this.loading = true;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_folders",
					args: {
						account_name: this.account,
					},
				});

				this.folders = response.message || [];
			} catch (error) {
				frappe.toast({ message: "Erreur de chargement des dossiers", indicator: "red" });
			} finally {
				this.loading = false;
			}
		},

		selectFolder(folder) {
			if (folder.selectable) {
				this.$emit("select", folder.name);
			}
		},

		getFolderIcon(folder) {
			const name = folder.name.toLowerCase();
			const flags = folder.flags || [];

			// Check IMAP special-use flags first
			if (flags.includes("\\Inbox") || name === "inbox") return "📥";
			if (flags.includes("\\Sent")) return "📤";
			if (flags.includes("\\Drafts")) return "📝";
			if (flags.includes("\\Trash")) return "🗑️";
			if (flags.includes("\\Junk") || flags.includes("\\Spam")) return "⚠️";
			if (flags.includes("\\Archive")) return "📦";
			if (flags.includes("\\Flagged") || flags.includes("\\Starred")) return "⭐";
			if (flags.includes("\\Important")) return "❗";
			if (flags.includes("\\All")) return "📁";

			// Fallback to name-based detection
			if (name === "inbox") return "📥";
			if (name.includes("sent")) return "📤";
			if (name.includes("draft")) return "📝";
			if (name.includes("trash") || name.includes("deleted") || name.includes("corbeille"))
				return "🗑️";
			if (name.includes("spam") || name.includes("junk")) return "⚠️";
			if (name.includes("archive")) return "📦";
			if (name.includes("starred") || name.includes("important")) return "⭐";

			return "📁";
		},

		getDisplayName(folder) {
			// Remove prefix path and show just the folder name
			const parts = folder.name.split(folder.delimiter || "/");
			const name = parts[parts.length - 1];

			// Translate common folder names
			const translations = {
				INBOX: "Boite de reception",
				Sent: "Envoyes",
				"Sent Items": "Envoyes",
				"Sent Mail": "Envoyes",
				Drafts: "Brouillons",
				Trash: "Corbeille",
				"Deleted Items": "Corbeille",
				Spam: "Spam",
				Junk: "Spam",
				"Junk E-mail": "Spam",
				Archive: "Archives",
				Starred: "Suivis",
				Important: "Important",
			};

			return translations[name] || name;
		},

		getFolderIndent(folder) {
			// Calculate indentation based on folder depth
			const depth = (folder.name.match(/\//g) || []).length;
			return 16 + depth * 16;
		},
	},
};
</script>

<style scoped>
.folder-tree {
	display: flex;
	flex-direction: column;
	height: auto;
	background: white;
	border-right: 1px solid var(--border-color, #e5e5e5);
	padding: 0;
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
	padding: 10px 16px;
	cursor: pointer;
	gap: 10px;
	transition: background 0.15s ease;
	margin: 0;
}

.folder-item:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.folder-item.selected {
	background: var(--primary-light, #e3f2fd);
	font-weight: 600;
	border-left: 3px solid var(--primary-color, #2490ef);
	padding-left: 13px;
}

.folder-item.disabled {
	opacity: 0.5;
	cursor: not-allowed;
}

.folder-icon {
	font-size: 16px;
	flex-shrink: 0;
	width: 20px;
	text-align: center;
}

.folder-name {
	flex: 1;
	font-size: 14px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	color: var(--text-color, #333);
}

.unread-count {
	background: var(--primary-color, #2490ef);
	color: white;
	font-size: 11px;
	padding: 2px 8px;
	border-radius: 10px;
	min-width: 20px;
	text-align: center;
	font-weight: 500;
}
</style>
