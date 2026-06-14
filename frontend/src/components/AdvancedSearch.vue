<template>
	<div class="advanced-search">
		<!-- Header -->
		<div class="search-header">
			<h3>{{ __("Advanced search") }}</h3>
			<button @click="$emit('close')" class="close-btn" :title="__('Close')">
				<X :size="18" />
			</button>
		</div>

		<!-- Form (compact, placeholders only — no labels above) -->
		<div class="search-form">
			<!-- Wrap the general search in a .row so its width matches the
			     two-column rows below (grid context = same available width). -->
			<div class="row row-1">
				<input
					v-model="filters.query"
					type="text"
					class="field"
					:placeholder="__('Search in all fields…')"
					@keyup.enter="search"
					ref="generalInput"
				/>
			</div>

			<div class="row">
				<input
					v-model="filters.from"
					type="text"
					class="field"
					:placeholder="__('From — sender email')"
					@keyup.enter="search"
				/>
				<input
					v-model="filters.to"
					type="text"
					class="field"
					:placeholder="__('To — recipient email')"
					@keyup.enter="search"
				/>
			</div>

			<div class="row">
				<input
					v-model="filters.subject"
					type="text"
					class="field"
					:placeholder="__('Subject contains…')"
					@keyup.enter="search"
				/>
				<select v-model="filters.folder" class="field">
					<option value="">{{ __("All folders") }}</option>
					<option v-for="folder in folders" :key="folder.name" :value="folder.name">
						{{ folder.name }}
					</option>
				</select>
			</div>

			<div class="row">
				<input
					v-model="filters.dateFrom"
					type="date"
					class="field"
					:title="__('From date')"
				/>
				<input v-model="filters.dateTo" type="date" class="field" :title="__('To date')" />
			</div>

			<!-- Inline toggles row -->
			<div class="toggles">
				<label class="toggle">
					<input type="checkbox" v-model="filters.hasAttachment" />
					<span>{{ __("Attachments") }}</span>
				</label>
				<label class="toggle">
					<input type="checkbox" v-model="filters.isUnread" />
					<span>{{ __("Unread") }}</span>
				</label>
				<label class="toggle">
					<input type="checkbox" v-model="filters.isFlagged" />
					<span>{{ __("Starred") }}</span>
				</label>
			</div>
		</div>

		<!-- Inline actions bar (sticky between form and results) -->
		<div class="search-actions">
			<button @click="clearFilters" class="btn btn-secondary">
				{{ __("Clear") }}
			</button>
			<button @click="search" class="btn btn-primary" :disabled="searching">
				<Search :size="14" />
				<span>{{ searching ? __("Searching...") : __("Search") }}</span>
			</button>
			<span v-if="hasSearched" class="results-summary">
				{{ __("{0} result(s) out of {1}", [results.length, total]) }}
			</span>
		</div>

		<!-- Results — always visible (or empty state) once a search has run -->
		<div class="search-results">
			<div v-if="!hasSearched && !searching" class="results-hint">
				<Search :size="32" />
				<p>{{ __("Fill in any field and hit Search to find emails.") }}</p>
			</div>

			<div v-else-if="searching && results.length === 0" class="results-loading">
				<div class="spinner-sm"></div>
				<p>{{ __("Searching...") }}</p>
			</div>

			<div v-else-if="results.length === 0" class="no-results">
				<p>{{ __("No results found") }}</p>
				<small>{{ __("Try fewer filters or a different folder.") }}</small>
			</div>

			<div v-else class="results-list">
				<div
					v-for="email in results"
					:key="email.folder + '-' + email.uid"
					class="result-item"
					:class="{ unread: !email.seen }"
					@click="selectEmail(email)"
				>
					<div class="result-avatar" :class="getAvatarColor(email.from_email)">
						{{ getAvatarInitials(email.from_name, email.from_email) }}
					</div>
					<div class="result-body">
						<div class="result-top">
							<span class="result-from">{{
								email.from_name || email.from_email
							}}</span>
							<span v-if="email.has_attachments" class="result-att">
								<Paperclip :size="11" />
							</span>
							<span class="result-date">{{ formatDate(email.date) }}</span>
						</div>
						<div class="result-subject">{{ email.subject || __("(No subject)") }}</div>
						<div v-if="email.folder" class="result-folder">{{ email.folder }}</div>
					</div>
				</div>
				<button
					v-if="hasMore"
					@click="loadMore"
					class="load-more-btn"
					:disabled="searching"
				>
					{{ searching ? __("Loading...") : __("Load more") }}
				</button>
			</div>
		</div>
	</div>
</template>

<script>
import { X, Search, Paperclip } from "lucide-vue-next";

export default {
	name: "AdvancedSearch",

	components: {
		X,
		Search,
		Paperclip,
	},

	props: {
		account: { type: String, required: true },
		folders: { type: Array, default: () => [] },
		initialFolder: { type: String, default: "" },
		initialQuery: { type: String, default: "" },
	},

	emits: ["close", "select"],

	data() {
		return {
			filters: {
				query: this.initialQuery || "",
				from: "",
				to: "",
				subject: "",
				dateFrom: "",
				dateTo: "",
				hasAttachment: false,
				isUnread: false,
				isFlagged: false,
				// Empty string = search across ALL folders (the new default).
				folder: "",
			},
			results: [],
			total: 0,
			hasMore: false,
			searching: false,
			hasSearched: false,
		};
	},

	mounted() {
		this.$nextTick(() => {
			this.$refs.generalInput?.focus();
			// Auto-run the search when the dialog is opened from the cmd-palette
			// with a pre-filled query (so the user immediately sees results).
			if (this.initialQuery && this.initialQuery.trim()) {
				this.search();
			}
		});
	},

	methods: {
		// Folders we will iterate over when the user picks "All folders".
		// Skips non-selectable special IMAP nodes (\Noselect).
		searchableFolders() {
			return (this.folders || []).filter((f) => f.selectable !== false);
		},

		// Build the args object for the backend (same shape as legacy version).
		buildArgs(folder, offset = 0, limit = 50) {
			return {
				account_name: this.account,
				folder: folder,
				query: this.filters.query || null,
				from_filter: this.filters.from || null,
				to_filter: this.filters.to || null,
				subject_filter: this.filters.subject || null,
				date_from: this.filters.dateFrom || null,
				date_to: this.filters.dateTo || null,
				has_attachment: this.filters.hasAttachment || null,
				is_unread: this.filters.isUnread || null,
				is_flagged: this.filters.isFlagged || null,
				limit,
				offset,
			};
		},

		async search() {
			this.searching = true;
			this.hasSearched = true;
			this.results = [];
			this.total = 0;
			this.hasMore = false;

			try {
				if (this.filters.folder) {
					// Single-folder search (legacy fast path).
					const response = await frappe.call({
						method: "frappe_webmail.api.search_emails",
						args: this.buildArgs(this.filters.folder, 0, 50),
					});
					const data = response.message || {};
					this.results = (data.emails || []).map((e) => ({
						...e,
						folder: this.filters.folder,
					}));
					this.total = data.total || this.results.length;
					this.hasMore = !!data.has_more;
				} else {
					// "All folders": fan-out across every selectable folder. We
					// cap at 30/folder so the request stays responsive on big
					// mailboxes — Load more on a per-folder filter for deep dives.
					const folders = this.searchableFolders();
					const perFolder = 30;
					const aggregated = [];
					let total = 0;
					await Promise.all(
						folders.map(async (f) => {
							try {
								const response = await frappe.call({
									method: "frappe_webmail.api.search_emails",
									args: this.buildArgs(f.name, 0, perFolder),
								});
								const data = response.message || {};
								(data.emails || []).forEach((e) =>
									aggregated.push({ ...e, folder: f.name })
								);
								total += data.total || (data.emails || []).length;
							} catch (e) {
								/* skip the folder we couldn't search */
							}
						})
					);
					// Most recent first.
					aggregated.sort((a, b) => {
						const da = a.date ? new Date(a.date).getTime() : 0;
						const db = b.date ? new Date(b.date).getTime() : 0;
						return db - da;
					});
					this.results = aggregated;
					this.total = total;
					this.hasMore = false; // pagination not supported in fan-out mode
				}
			} catch (error) {
				frappe.toast({ message: this.__("Search error"), indicator: "red" });
			} finally {
				this.searching = false;
			}
		},

		async loadMore() {
			if (!this.hasMore || this.searching) return;
			this.searching = true;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.search_emails",
					args: this.buildArgs(this.filters.folder, this.results.length, 50),
				});
				const data = response.message || {};
				(data.emails || []).forEach((e) =>
					this.results.push({ ...e, folder: this.filters.folder })
				);
				this.hasMore = !!data.has_more;
			} catch (error) {
				frappe.toast({ message: this.__("Error"), indicator: "red" });
			} finally {
				this.searching = false;
			}
		},

		clearFilters() {
			this.filters = {
				query: "",
				from: "",
				to: "",
				subject: "",
				dateFrom: "",
				dateTo: "",
				hasAttachment: false,
				isUnread: false,
				isFlagged: false,
				folder: "",
			};
			this.results = [];
			this.total = 0;
			this.hasMore = false;
			this.hasSearched = false;
			this.$nextTick(() => this.$refs.generalInput?.focus());
		},

		selectEmail(email) {
			this.$emit("select", {
				email,
				folder: email.folder || this.filters.folder,
			});
		},

		formatDate(dateStr) {
			if (!dateStr) return "";
			const date = new Date(dateStr);
			const now = new Date();
			const sameYear = date.getFullYear() === now.getFullYear();
			return date.toLocaleDateString("fr-FR", {
				day: "numeric",
				month: "short",
				...(sameYear ? {} : { year: "numeric" }),
			});
		},

		// Deterministic avatar color (c1-c6) for the result row — matches the
		// gradient palette used in EmailList so the same sender keeps the
		// same color across the list and the search results.
		getAvatarColor(email) {
			const src = (email || "").toLowerCase();
			let hash = 0;
			for (let i = 0; i < src.length; i++) {
				hash = (hash << 5) - hash + src.charCodeAt(i);
				hash |= 0;
			}
			return "c" + ((Math.abs(hash) % 6) + 1);
		},

		getAvatarInitials(name, email) {
			const raw = (name || email || "?").trim();
			const parts = raw.split(/[\s@._-]+/).filter(Boolean);
			if (parts.length >= 2 && parts[0] && parts[1]) {
				return (parts[0][0] + parts[1][0]).toUpperCase();
			}
			return ((parts[0] || raw)[0] || "?").toUpperCase();
		},
	},
};
</script>

<style scoped>
.advanced-search {
	display: flex;
	flex-direction: column;
	height: 100%;
	background: var(--wm-bg-raised, #fff);
	overflow: hidden;
}

/* ===== Header (serif title) ===== */
.search-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 14px 18px 10px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
	flex-shrink: 0;
}

.search-header h3 {
	margin: 0;
	font-family: Forum, Georgia, serif;
	font-size: 19px;
	font-weight: 400;
	letter-spacing: -0.005em;
	color: var(--wm-ink, #1a1a1a);
}

.close-btn {
	width: 28px;
	height: 28px;
	display: grid;
	place-items: center;
	background: transparent;
	border: 0;
	border-radius: 6px;
	cursor: pointer;
	color: var(--wm-ink-mute, #8d99a6);
	transition: background 0.15s, color 0.15s;
}

.close-btn:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
	color: var(--wm-ink, #1a1a1a);
}

/* ===== Compact form — placeholders only, no field labels ===== */
.search-form {
	padding: 10px 16px 12px;
	flex-shrink: 0;
	display: flex;
	flex-direction: column;
	gap: 6px;
}

.row {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 6px;
}

/* Single-column row (used for the general search) — keeps the same outer
   width as the two-column rows below so all fields align perfectly. */
.row-1 {
	grid-template-columns: 1fr;
}

.field {
	width: 100%;
	padding: 6px 10px;
	border: 1px solid var(--wm-line, #e5e5e5);
	border-radius: 6px;
	font-size: 13px;
	background: var(--wm-bg-raised, #fff);
	color: var(--wm-ink, #1a1a1a);
	font-family: inherit;
	min-width: 0;
	transition: border-color 0.15s;
}

.field:focus {
	outline: none;
	border-color: var(--wm-accent, var(--wm-accent));
}

.field::placeholder {
	color: var(--wm-ink-mute, #b0b0b0);
}

/* Inline checkbox row */
.toggles {
	display: flex;
	align-items: center;
	gap: 16px;
	padding: 4px 2px 0;
	flex-wrap: wrap;
}

/* Override the global Frappe Desk `label { display: inline-block;
   margin-bottom: 0.5rem }` rule that otherwise squeezes our toggle
   labels to a 9×9 box and overlaps their content. */
.toggle {
	display: inline-flex !important;
	align-items: center;
	gap: 6px;
	font-size: 12.5px;
	color: var(--wm-ink-soft, #555);
	cursor: pointer;
	user-select: none;
	white-space: nowrap;
	width: max-content !important;
	margin: 0 !important;
	font-weight: 400;
}

.toggle span {
	display: inline-block;
}

.toggle input[type="checkbox"] {
	width: 14px;
	height: 14px;
	margin: 0 !important;
	cursor: pointer;
	accent-color: var(--wm-accent, var(--wm-accent));
	flex-shrink: 0;
}

/* ===== Actions bar (between form and results) ===== */
.search-actions {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 10px 18px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
	background: var(--wm-bg, #fafafa);
	flex-shrink: 0;
}

.results-summary {
	margin-left: auto;
	font-size: 12px;
	color: var(--wm-ink-mute, #8d99a6);
	font-variant-numeric: tabular-nums;
}

.btn {
	padding: 7px 14px;
	border-radius: 7px;
	cursor: pointer;
	font-size: 12.5px;
	font-weight: 500;
	font-family: inherit;
	display: inline-flex;
	align-items: center;
	gap: 6px;
	transition: background 0.15s, color 0.15s;
}

.btn-primary {
	background: var(--wm-accent, var(--wm-accent));
	color: white;
	border: 0;
	box-shadow: 0 1px 2px rgba(214, 138, 89, 0.3);
}

.btn-primary:hover {
	background: var(--wm-accent-hover, #4338d4);
}

.btn-primary:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}

.btn-secondary {
	background: var(--wm-bg-raised, #fff);
	color: var(--wm-ink, #1a1a1a);
	border: 1px solid var(--wm-line, #e5e5e5);
}

.btn-secondary:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
}

/* ===== Results area — flex 1, always visible after first search ===== */
.search-results {
	flex: 1;
	min-height: 0;
	overflow-y: auto;
	background: var(--wm-bg-raised, #fff);
}

.results-hint,
.results-loading,
.no-results {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 8px;
	padding: 40px 20px;
	color: var(--wm-ink-mute, #8d99a6);
	text-align: center;
}

.results-hint svg {
	opacity: 0.4;
}

.no-results small {
	font-size: 11.5px;
}

.spinner-sm {
	width: 22px;
	height: 22px;
	border: 2px solid var(--wm-line, #e5e5e5);
	border-top-color: var(--wm-accent, var(--wm-accent));
	border-radius: 50%;
	animation: spin 1s linear infinite;
}

@keyframes spin {
	to {
		transform: rotate(360deg);
	}
}

.results-list {
	display: flex;
	flex-direction: column;
}

.result-item {
	display: flex;
	gap: 10px;
	padding: 10px 18px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
	cursor: pointer;
	transition: background 0.12s;
}

.result-item:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
}

.result-item.unread .result-from,
.result-item.unread .result-subject {
	font-weight: 600;
	color: var(--wm-ink, #1a1a1a);
}

/* Gradient avatar — same palette as the main inbox list. */
.result-avatar {
	flex-shrink: 0;
	width: 30px;
	height: 30px;
	border-radius: 50%;
	display: grid;
	place-items: center;
	color: white;
	font-size: 11px;
	font-weight: 600;
	align-self: flex-start;
	margin-top: 1px;
}

.result-avatar.c1 {
	background: linear-gradient(135deg, var(--wm-accent), var(--wm-nora-2));
}
.result-avatar.c2 {
	background: linear-gradient(135deg, #b45309, #f59e0b);
}
.result-avatar.c3 {
	background: linear-gradient(135deg, #047857, #34d399);
}
.result-avatar.c4 {
	background: linear-gradient(135deg, #be185d, #ec4899);
}
.result-avatar.c5 {
	background: linear-gradient(135deg, #0e7490, #06b6d4);
}
.result-avatar.c6 {
	background: linear-gradient(135deg, #6d28d9, #c084fc);
}

.result-body {
	flex: 1;
	min-width: 0;
}

.result-top {
	display: flex;
	align-items: baseline;
	gap: 6px;
	margin-bottom: 2px;
}

.result-from {
	flex: 1;
	min-width: 0;
	font-size: 13px;
	color: var(--wm-ink, #1a1a1a);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.result-att {
	color: var(--wm-ink-mute, #8d99a6);
	flex-shrink: 0;
}

.result-date {
	font-size: 11px;
	color: var(--wm-ink-mute, #8d99a6);
	flex-shrink: 0;
	font-variant-numeric: tabular-nums;
}

.result-subject {
	font-size: 12.5px;
	color: var(--wm-ink-soft, #555);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.result-folder {
	display: inline-block;
	margin-top: 2px;
	font-size: 10.5px;
	color: var(--wm-ink-mute, #8d99a6);
	background: var(--wm-bg-sunken, #f5f5f5);
	padding: 1px 6px;
	border-radius: 4px;
}

.load-more-btn {
	margin: 10px auto;
	padding: 7px 16px;
	font-size: 12px;
	border: 1px solid var(--wm-line, #e5e5e5);
	background: var(--wm-bg-raised, #fff);
	border-radius: 7px;
	cursor: pointer;
	color: var(--wm-ink-soft, #555);
	font-family: inherit;
}

.load-more-btn:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
}

.load-more-btn:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}
</style>
