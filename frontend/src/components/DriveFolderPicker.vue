<template>
	<Teleport to="body">
		<div class="dfp-veil" @click.self="$emit('close')" @keydown.esc="$emit('close')">
			<div class="dfp" role="dialog" aria-modal="true" :aria-label="__('Save to the Drive')">
				<header class="dfp-head">
					<h2 class="dfp-title">{{ __("Save to the Drive") }}</h2>
					<button class="dfp-icon" :aria-label="__('Close')" @click="$emit('close')">
						<X :size="16" />
					</button>
				</header>

				<div class="dfp-body">
					<div v-if="attachment" class="dfp-file">
						<FileText :size="16" />
						<span class="dfp-file-name">{{ attachment.filename }}</span>
						<span class="dfp-file-size">{{ size }}</span>
					</div>

					<label class="dfp-search">
						<Search :size="15" />
						<input
							ref="search"
							v-model="query"
							type="text"
							:placeholder="__('Search for a folder')"
							@input="onSearch"
						/>
					</label>

					<button
						v-if="last && !query"
						class="dfp-last"
						:class="{ on: selected === last.name }"
						@click="select(last)"
					>
						<Clock :size="15" />
						<span class="dfp-last-text">
							<span class="dfp-last-label">{{ __("Last used") }}</span>
							<span class="dfp-last-path">{{ last.path || last.title }}</span>
						</span>
					</button>

					<div class="dfp-tree" role="tree">
						<div v-if="loading" class="dfp-empty">{{ __("Loading…") }}</div>
						<template v-else-if="query">
							<div v-if="!results.length" class="dfp-empty">
								{{ __("No folder found") }}
							</div>
							<button
								v-for="f in results"
								:key="f.name"
								class="dfp-row"
								:class="{ on: selected === f.name }"
								role="treeitem"
								@click="select(f)"
							>
								<span class="dfp-chev" />
								<Folder :size="16" />
								<span class="dfp-row-text">
									<span>{{ f.title }}</span>
									<small v-if="f.path">{{ f.path }}</small>
								</span>
							</button>
						</template>
						<template v-else>
							<button
								v-for="row in rows"
								:key="row.key"
								class="dfp-row"
								:class="{
									on: selected === row.folder.name,
									muted: !row.folder.can_write,
								}"
								:style="{ paddingLeft: 8 + row.depth * 18 + 'px' }"
								role="treeitem"
								:aria-expanded="
									row.folder.has_children
										? String(!!open[row.folder.name])
										: undefined
								"
								@click="onRow(row.folder)"
							>
								<span class="dfp-chev" @click.stop="toggle(row.folder)">
									<template v-if="row.folder.has_children">
										<ChevronDown v-if="open[row.folder.name]" :size="13" />
										<ChevronRight v-else :size="13" />
									</template>
								</span>
								<component :is="iconFor(row.folder)" :size="16" />
								<span class="dfp-row-text"
									><span>{{ row.folder.title }}</span></span
								>
							</button>
						</template>
					</div>

					<p class="dfp-hint">
						{{
							__(
								"The file is copied by the server, straight from the e-mail: nothing is downloaded."
							)
						}}
					</p>
				</div>

				<footer class="dfp-foot">
					<button
						v-if="creating === null"
						class="dfp-btn ghost"
						:disabled="!canCreate"
						@click="startCreate"
					>
						<FolderPlus :size="15" />
						{{ __("New folder") }}
					</button>
					<form v-else class="dfp-new" @submit.prevent="createFolder">
						<input
							ref="newName"
							v-model="creating"
							type="text"
							:placeholder="__('Name of the folder')"
							@keydown.esc.stop="creating = null"
						/>
						<button
							class="dfp-btn ghost"
							type="submit"
							:disabled="!creating.trim() || busy"
						>
							{{ __("Create") }}
						</button>
					</form>
					<span class="dfp-spacer" />
					<button class="dfp-btn ink" :disabled="!canSave || busy" @click="save">
						{{ busy ? __("Saving…") : __("Save here") }}
					</button>
				</footer>
			</div>
		</div>
	</Teleport>
</template>

<script>
import {
	ChevronDown,
	ChevronRight,
	Clock,
	FileText,
	Folder,
	FolderPlus,
	HardDrive,
	Home,
	Search,
	Users,
	X,
} from "lucide-vue-next";

const FOLDERS_METHOD = "frappe_webmail.attachments.get_drive_folders";
const CREATE_METHOD = "frappe_webmail.attachments.create_drive_folder";

export default {
	name: "DriveFolderPicker",

	components: { ChevronDown, ChevronRight, Clock, FileText, Folder, FolderPlus, Search, X },

	props: {
		// { filename, size } of the attachment being filed
		attachment: { type: Object, default: null },
		busy: { type: Boolean, default: false },
	},

	emits: ["pick", "close"],

	data() {
		return {
			loading: true,
			roots: [],
			children: {},
			open: {},
			last: null,
			selected: null,
			selectedFolder: null,
			query: "",
			results: [],
			creating: null,
			searchTimer: null,
		};
	},

	computed: {
		// The tree, flattened in display order, opening what is open
		rows() {
			const out = [];
			const walk = (folders, depth) => {
				for (const folder of folders || []) {
					out.push({ key: `${depth}:${folder.name}`, folder, depth });
					if (this.open[folder.name]) walk(this.children[folder.name], depth + 1);
				}
			};
			walk(this.roots, 0);
			return out;
		},
		canSave() {
			return Boolean(this.selectedFolder && this.selectedFolder.can_write);
		},
		canCreate() {
			return this.canSave;
		},
		size() {
			const bytes = this.attachment?.size || 0;
			if (!bytes) return "";
			const units = ["B", "KB", "MB", "GB"];
			const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
			return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
		},
	},

	async mounted() {
		try {
			const r = await frappe.call({ method: FOLDERS_METHOD });
			this.roots = r.message?.folders || [];
			this.last = r.message?.last || null;
			if (this.last) this.select(this.last);
		} finally {
			this.loading = false;
		}
		this.$nextTick(() => this.$refs.search?.focus());
	},

	beforeUnmount() {
		clearTimeout(this.searchTimer);
	},

	methods: {
		iconFor(folder) {
			if (folder.kind === "home") return Home;
			if (folder.kind === "shared_drive") return HardDrive;
			if (folder.kind === "shared_with_me") return Users;
			return Folder;
		},
		select(folder) {
			this.selected = folder.name;
			this.selectedFolder = folder;
		},
		onRow(folder) {
			if (folder.can_write) this.select(folder);
			if (folder.has_children && !this.open[folder.name]) this.toggle(folder);
		},
		async toggle(folder) {
			if (!folder.has_children) return;
			if (this.open[folder.name]) {
				this.open = { ...this.open, [folder.name]: false };
				return;
			}
			if (!this.children[folder.name]) {
				const r = await frappe.call({
					method: FOLDERS_METHOD,
					args: { parent: folder.name },
				});
				this.children = { ...this.children, [folder.name]: r.message?.folders || [] };
			}
			this.open = { ...this.open, [folder.name]: true };
		},
		onSearch() {
			clearTimeout(this.searchTimer);
			const text = this.query.trim();
			if (!text) {
				this.results = [];
				return;
			}
			this.searchTimer = setTimeout(async () => {
				const r = await frappe.call({ method: FOLDERS_METHOD, args: { search: text } });
				if (this.query.trim() === text) this.results = r.message?.folders || [];
			}, 250);
		},
		startCreate() {
			this.creating = "";
			this.$nextTick(() => this.$refs.newName?.focus());
		},
		async createFolder() {
			const name = (this.creating || "").trim();
			const parent = this.selectedFolder;
			if (!name || !parent) return;
			const r = await frappe.call({
				method: CREATE_METHOD,
				args: { parent: parent.name, title: name },
			});
			const folder = r.message;
			if (!folder) return;
			this.children = {
				...this.children,
				[parent.name]: [...(this.children[parent.name] || []), folder],
			};
			this.open = { ...this.open, [parent.name]: true };
			parent.has_children = true;
			this.creating = null;
			this.select(folder);
		},
		save() {
			if (this.canSave) this.$emit("pick", this.selectedFolder);
		},
	},
};
</script>

<style>
/* Teleported to <body>, outside .webmail-app: the dialog carries the webmail's clay tokens itself */
.dfp-veil {
	--wm-accent: var(--nw-accent, #d68a59);
	--wm-accent-hover: var(--nw-accent-deep, #a15a2e);
	--wm-accent-soft: var(--nw-accent-soft, #faefe6);
	position: fixed;
	inset: 0;
	z-index: 1060;
	font-family: Karla, var(--font-stack, system-ui), sans-serif;
	display: flex;
	align-items: center;
	justify-content: center;
	background: rgba(20, 16, 10, 0.32);
}
.dfp {
	width: min(560px, calc(100vw - 32px));
	max-height: calc(100vh - 48px);
	display: flex;
	flex-direction: column;
	overflow: hidden;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 18px;
	background: var(--wm-bg, var(--bg-color));
	box-shadow: 0 30px 70px rgba(40, 28, 10, 0.25);
	color: var(--wm-ink, var(--text-color));
}
.dfp-head {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 16px 18px;
	border-bottom: 1px solid var(--wm-line, var(--border-color));
}
.dfp-title {
	flex: 1;
	margin: 0;
	font: 400 22px/26px Forum, Georgia, serif;
}
.dfp-icon {
	width: 32px;
	height: 32px;
	display: grid;
	place-items: center;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 999px;
	background: var(--wm-bg-raised, var(--card-bg));
	color: inherit;
	cursor: pointer;
}
.dfp-body {
	display: flex;
	flex-direction: column;
	gap: 12px;
	padding: 16px 18px;
	min-height: 0;
	overflow: auto;
}
.dfp-file {
	display: flex;
	align-items: center;
	gap: 10px;
	height: 44px;
	padding: 0 12px;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 12px;
	background: var(--wm-bg-raised, var(--card-bg));
}
.dfp-file-name {
	flex: 1;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	font-weight: 600;
}
.dfp-file-size,
.dfp-hint,
.dfp-row small,
.dfp-last-label {
	color: var(--wm-ink-mute, var(--text-muted));
	font-size: 12px;
}
.dfp-search {
	display: flex;
	align-items: center;
	gap: 8px;
	height: 38px;
	padding: 0 12px;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 12px;
	background: var(--wm-bg-raised, var(--card-bg));
	color: var(--wm-ink-mute, var(--text-muted));
}
.dfp-search input,
.dfp-new input {
	flex: 1;
	min-width: 0;
	border: 0;
	outline: 0;
	background: transparent;
	color: var(--wm-ink, var(--text-color));
	font: inherit;
}
.dfp-last {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 8px 12px;
	border: 1px dashed var(--wm-line-strong, var(--border-color));
	border-radius: 12px;
	background: transparent;
	color: inherit;
	text-align: left;
	cursor: pointer;
}
.dfp-last-text {
	display: flex;
	flex-direction: column;
	min-width: 0;
}
.dfp-last-path {
	font-weight: 600;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.dfp-tree {
	display: flex;
	flex-direction: column;
	gap: 1px;
	max-height: 300px;
	overflow: auto;
	padding: 8px;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 14px;
	background: var(--wm-bg-raised, var(--card-bg));
}
.dfp-row {
	display: flex;
	align-items: center;
	gap: 8px;
	min-height: 34px;
	padding: 4px 10px;
	border: 0;
	border-radius: 8px;
	background: transparent;
	color: inherit;
	font-family: inherit;
	font-size: 14px;
	font-weight: 500;
	line-height: 18px;
	text-align: left;
	cursor: pointer;
}
.dfp-row:hover {
	background: var(--wm-bg-sunken, var(--bg-light-gray));
}
.dfp-row.muted {
	color: var(--wm-ink-mute, var(--text-muted));
}
.dfp-row.on,
.dfp-last.on {
	border-color: var(--wm-accent);
	background: var(--wm-accent-soft);
	color: var(--wm-accent-hover);
	font-weight: 600;
}
.dfp-row-text {
	display: flex;
	flex-direction: column;
	min-width: 0;
}
.dfp-chev {
	width: 14px;
	display: inline-flex;
	justify-content: center;
	color: var(--wm-ink-mute, var(--text-muted));
}
.dfp-empty {
	padding: 10px;
	color: var(--wm-ink-mute, var(--text-muted));
	font-size: 13px;
}
.dfp-hint {
	margin: 0;
}
.dfp-foot {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 12px 18px 16px;
}
.dfp-spacer {
	flex: 1;
}
.dfp-new {
	display: flex;
	align-items: center;
	gap: 8px;
	flex: 1;
	height: 38px;
	padding: 0 4px 0 12px;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 10px;
	background: var(--wm-bg-raised, var(--card-bg));
}
.dfp-btn {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	height: 36px;
	padding: 0 14px;
	border: 1px solid transparent;
	border-radius: 10px;
	font-family: inherit;
	font-size: 14px;
	font-weight: 600;
	line-height: 1;
	cursor: pointer;
}
.dfp-btn:disabled {
	opacity: 0.5;
	cursor: default;
}
.dfp-btn.ghost {
	border-color: var(--wm-line, var(--border-color));
	background: var(--wm-bg-raised, var(--card-bg));
	color: var(--wm-ink, var(--text-color));
}
.dfp-btn.ink {
	background: #141414;
	color: #fffdf8;
}
[data-theme="dark"] .dfp-btn.ink {
	background: #ededed;
	color: #141414;
}
</style>
