<template>
	<div class="webmail-app">
		<!-- TOPBAR 52px (no brand: we are already inside the Webmail route) -->
		<header class="topbar">
			<!-- Folder column toggle: collapses the folder tree to an icon rail so the
			     reader gets the width back (per-account preference) -->
			<button
				v-if="accounts.length"
				class="icon-btn sb-toggle"
				@click="toggleSidebar"
				:data-tip="sidebarCollapsed ? __('Show folders') : __('Hide folders')"
				:aria-label="sidebarCollapsed ? __('Show folders') : __('Hide folders')"
			>
				<PanelLeftOpen v-if="sidebarCollapsed" :size="15" :stroke-width="1.7" />
				<PanelLeftClose v-else :size="15" :stroke-width="1.7" />
			</button>

			<!-- Account switcher -->
			<div class="account-switch" v-if="currentAccount && accounts.length">
				<div class="av-mini">{{ accountInitial }}</div>
				<select v-model="currentAccount" @change="onAccountChange" class="account-select">
					<option v-for="acc in accounts" :key="acc.name" :value="acc.name">
						{{ acc.email }}{{ acc.is_shared ? ` (${__("shared")})` : "" }}
					</option>
				</select>
				<ChevronDown :size="11" class="ch" />
				<div
					v-if="currentAccountSharing"
					class="sharing-indicator-mini"
					@mouseenter="showSharingTooltip = true"
					@mouseleave="showSharingTooltip = false"
				>
					<Users :size="12" />
					<div v-if="showSharingTooltip" class="sharing-tooltip">
						{{ currentAccountSharing }}
					</div>
				</div>
			</div>

			<!-- Command palette search — real input + dropdown (Recent / Tips / Advanced).
			     `@mousedown.prevent` on the dropdown keeps focus on the input so
			     clicks inside the panel don't blur and close it. -->
			<div class="cmd-search" :class="{ 'is-open': searchOpen }">
				<Search :size="14" class="cmd-search-icon" />
				<input
					ref="cmdSearchInput"
					v-model="searchInput"
					type="text"
					class="cmd-search-input"
					:placeholder="__('Search in Webmail…')"
					@focus="searchOpen = true"
					@blur="onSearchBlur"
					@keydown.enter="runQuickSearch"
					@keydown.esc="closeSearch"
				/>
				<span class="kbd">⌘K</span>

				<div v-if="searchOpen" class="cmd-dropdown" @mousedown.prevent>
					<!-- Left panel: live results (when typing) OR recent searches -->
					<div class="cmd-panel cmd-panel-main">
						<template v-if="hasLiveQuery">
							<div class="cmd-panel-title">
								{{ __("Results") }}
								<span
									v-if="!liveSearching && liveResults.length"
									class="cmd-panel-meta"
								>
									{{ liveResults.length }}
								</span>
								<span v-if="liveSearching" class="cmd-spinner"></span>
							</div>
							<div
								v-if="liveSearching && liveResults.length === 0"
								class="cmd-empty"
							>
								{{ __("Searching…") }}
							</div>
							<div v-else-if="liveResults.length === 0" class="cmd-empty">
								{{ __("No match in {0}", [folderLabelForSearch]) }}
							</div>
							<button
								v-for="email in liveResults"
								:key="email.uid + '@' + email.folder"
								class="cmd-result"
								@click="pickResult(email)"
							>
								<div
									class="cmd-result-avatar"
									:class="getAvatarColor(email.from_email)"
								>
									{{ getAvatarInitials(email.from_name, email.from_email) }}
								</div>
								<div class="cmd-result-body">
									<div class="cmd-result-top">
										<span class="cmd-result-from">
											{{ email.from_name || email.from_email }}
										</span>
										<span class="cmd-result-date">
											{{ formatLiveDate(email.date) }}
										</span>
									</div>
									<div class="cmd-result-subject">
										{{ email.subject || __("(No subject)") }}
									</div>
								</div>
							</button>
						</template>
						<template v-else>
							<div class="cmd-panel-title">{{ __("Recent searches") }}</div>
							<div v-if="filteredRecent.length === 0" class="cmd-empty">
								{{ __("Nothing yet") }}
							</div>
							<button
								v-for="(s, i) in filteredRecent"
								:key="i"
								class="cmd-item"
								@click="pickRecent(s)"
							>
								<Search :size="13" />
								<span class="cmd-item-text">{{ s }}</span>
								<button
									class="cmd-item-remove"
									:title="__('Remove')"
									@click.stop="removeRecent(s)"
								>
									<X :size="11" />
								</button>
							</button>
						</template>
					</div>

					<!-- Right panel: tips / advanced search -->
					<div class="cmd-panel cmd-panel-tips">
						<div class="cmd-panel-title">{{ __("Tips") }}</div>
						<div class="cmd-tip">
							{{ __("Type words to search subject, body and sender.") }}
						</div>
						<div class="cmd-tip">
							{{ __("Live results search the {0} folder.", [folderLabelForSearch]) }}
						</div>
						<div class="cmd-tip">
							{{ __("Press {0} for advanced search.", ["⏎"]) }}
						</div>
						<button class="cmd-advanced-btn" @click="openAdvanced">
							<Filter :size="12" />
							{{ __("Advanced search…") }}
						</button>
					</div>
				</div>
			</div>

			<!-- Top actions -->
			<div class="top-actions">
				<button
					v-if="capabilities.nora"
					@click="toggleAgentPanel"
					class="icon-btn"
					:class="{ 'is-on': agentPanelOpen }"
					:data-tip="agentPanelOpen ? __('Hide Nora') : __('Ask Nora')"
					:aria-label="agentPanelOpen ? __('Hide Nora') : __('Ask Nora')"
				>
					<Sparkles :size="15" :stroke-width="1.7" />
				</button>
				<button
					v-if="capabilities.nora"
					@click="showAutomations = true"
					class="icon-btn"
					:data-tip="__('Nora automations')"
					:aria-label="__('Nora automations')"
				>
					<Bot :size="15" :stroke-width="1.7" />
				</button>
				<button
					@click="showFilters = true"
					class="icon-btn"
					:data-tip="__('Filters')"
					:aria-label="__('Filters')"
				>
					<Filter :size="14" />
				</button>
				<button
					@click="showSignatures = true"
					class="icon-btn"
					:data-tip="__('Signatures')"
					:aria-label="__('Signatures')"
				>
					<PenLine :size="14" />
				</button>
				<button
					@click="openSettings"
					class="icon-btn"
					:data-tip="__('Settings')"
					:aria-label="__('Settings')"
				>
					<Settings :size="14" />
				</button>
				<button @click="compose" class="btn-compose">
					<Plus :size="14" />
					<span>{{ __("New Message") }}</span>
				</button>
			</div>
		</header>

		<!-- MAIN — flex row with two draggable resizers between the columns.
		     Widths come from `sidebarWidth` / `emailListWidth` (persisted in
		     the Webmail Account UI preferences via saveUIPreferences). -->
		<div class="main" v-if="accounts.length" :class="{ 'is-resizing': isResizing }">
			<!-- Sidebar: Dossiers (FolderTree) + Étiquettes + Nora + storage footer -->
			<aside
				class="sidebar-col"
				:class="{ 'is-collapsed': sidebarCollapsed }"
				:style="{ width: (sidebarCollapsed ? 56 : sidebarWidth) + 'px' }"
			>
				<div class="sb-folders">
					<FolderTree
						ref="folderTree"
						:compact="sidebarCollapsed"
						:account="currentAccount"
						:account-email="currentAccountEmail"
						:selected-folder="currentFolder"
						@select="onFolderSelect"
						@drop-email="handleMoveEmail"
						@folder-mapping-loaded="onFolderMappingLoaded"
					/>
				</div>

				<!-- Storage — real IMAP quota (RFC 2087); hidden when the
				     server doesn't advertise QUOTA so we never show fake data -->
				<div class="storage" v-if="!sidebarCollapsed">
					<div class="storage-top" v-if="quota">
						<span>{{ quotaLabel }}</span>
					</div>
					<div class="storage-bar" v-if="quota">
						<span :style="{ width: quotaPercent + '%' }"></span>
					</div>
					<div class="storage-email" v-if="currentAccountEmail">
						{{ currentAccountEmail }}
					</div>
				</div>
			</aside>

			<!-- Resizer between sidebar and list -->
			<div
				v-if="!sidebarCollapsed"
				class="column-resizer"
				@mousedown="startResize('sidebar', $event)"
			>
				<div class="resizer-handle"></div>
			</div>

			<!-- Email List -->
			<section class="list-col" :style="{ width: emailListWidth + 'px' }">
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
			</section>

			<!-- Resizer between list and reader -->
			<div class="column-resizer" @mousedown="startResize('emailList', $event)">
				<div class="resizer-handle"></div>
			</div>

			<!-- Reader -->
			<section class="reader-col">
				<EmailViewer
					v-if="!showComposer"
					:email="selectedEmailContent"
					:account="currentAccount"
					:folder="currentFolder"
					:nora-enabled="capabilities.nora"
					@reply="replyTo"
					@forward="forwardEmail"
					@delete="deleteEmail"
					@flag-changed="onFlagChanged"
					@mark-unread="onMarkUnread"
					@quick-reply="handleQuickReply"
				/>
				<EmailComposer
					v-else
					ref="composer"
					:account="currentAccount"
					:nora-enabled="capabilities.nora"
					:reply-to="replyToEmail"
					:forward-email="forwardingEmail"
					:edit-draft="editingDraft"
					:signature="defaultSignature"
					:folder="currentFolder"
					@sent="onEmailSent"
					@close="closeComposer"
					@draft-deleted="onDraftDeleted"
					@nora-draft="onComposerNoraDraft"
					@open-nora="openAgentPanel"
				/>
			</section>

			<!-- Nora — mailbox-scoped chat, persistent across folders and emails -->
			<aside class="agent-col" v-if="capabilities.nora && agentPanelOpen">
				<AgentPanel
					ref="agentPanel"
					:account="currentAccount"
					:account-email="currentAccountEmail"
					:folder="currentFolder"
					:selected-email="selectedEmailContent"
					:composer-open="showComposer"
					:read-composer="readComposerState"
					@close="toggleAgentPanel"
					@apply-draft="applyDraftToComposer"
					@reply-with-draft="handleQuickReply"
					@compose-with-draft="composeWithDraft"
				/>
			</aside>
		</div>

		<!-- No Accounts State -->
		<div class="no-accounts" v-else-if="!loading">
			<div class="no-accounts-content">
				<h2>{{ __("Welcome to Webmail") }}</h2>
				<p>{{ __("You haven't configured any email account yet.") }}</p>
				<button @click="openSettings" class="btn-compose">
					{{ __("Configure an account") }}
				</button>
			</div>
		</div>

		<!-- Loading -->
		<div class="loading-overlay" v-if="loading">
			<div class="spinner"></div>
			<p>{{ __("Loading...") }}</p>
		</div>

		<!-- Nora automations (scheduled tasks on this mailbox) -->
		<div class="modal-overlay" v-if="showAutomations" @click.self="showAutomations = false">
			<div class="modal-content automations-modal">
				<AutomationsPanel
					:account="currentAccount"
					:account-email="currentAccountEmail"
					@close="showAutomations = false"
				/>
			</div>
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
					:initial-query="searchInput"
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
import AutomationsPanel from "../components/AutomationsPanel.vue";
import AgentPanel from "../components/AgentPanel.vue";
import { installTooltips } from "../tooltip";
import { splitQuote } from "../quoteSplit";
import {
	Mail,
	Search,
	SquarePen,
	Filter,
	PenLine,
	Settings,
	Users,
	ChevronDown,
	Plus,
	PanelLeftClose,
	PanelLeftOpen,
	Bot,
	Sparkles,
	X,
} from "lucide-vue-next";

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
		AutomationsPanel,
		AgentPanel,
		Mail,
		Search,
		SquarePen,
		Filter,
		PenLine,
		Settings,
		Users,
		ChevronDown,
		Plus,
		PanelLeftClose,
		PanelLeftOpen,
		Bot,
		Sparkles,
		X,
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
			showAutomations: false,
			// Nora side panel — remembered per browser (open by default)
			agentPanelOpen: (() => {
				try {
					const v = localStorage.getItem("webmail_agent_panel_open");
					return v === null ? true : v === "1";
				} catch (e) {
					return true;
				}
			})(),
			// Optional companions installed on this site (see get_capabilities)
			capabilities: { nora: false },
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
			// Folder column as an icon rail. First paint follows the viewport; the
			// account preference (null = never chosen) is applied once loaded.
			sidebarCollapsed: typeof window !== "undefined" && window.innerWidth < 1366,
			sidebarCollapsedPref: null,
			quota: null,
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
			// Topbar command palette state
			searchInput: "",
			searchOpen: false,
			recentSearches: [],
			searchBlurTimer: null,
			// Live search (debounced) — results shown inside the dropdown.
			liveResults: [],
			liveSearching: false,
			liveSearchTimer: null,
			liveSearchSeq: 0,
		};
	},

	computed: {
		quotaLabel() {
			if (!this.quota) return "";
			// small mailboxes: show MB usage instead of a misleading "0.0 GB"
			const fmt = (kb) =>
				kb < 1024 * 1024
					? `${Math.max(1, Math.round(kb / 1024))} MB`
					: `${(kb / 1024 / 1024).toFixed(1)} GB`;
			return `${fmt(this.quota.usage_kb)} / ${(this.quota.limit_kb / 1024 / 1024).toFixed(
				0
			)} GB`;
		},
		quotaPercent() {
			if (!this.quota || !this.quota.limit_kb) return 0;
			return Math.min(100, Math.round((this.quota.usage_kb / this.quota.limit_kb) * 100));
		},
		// True as soon as the user types ≥2 chars — switches the dropdown
		// from "Recent searches" to "Live results".
		hasLiveQuery() {
			return (this.searchInput || "").trim().length >= 2;
		},

		// Pretty label of the folder the live search runs against.
		folderLabelForSearch() {
			const f = this.currentFolder || "";
			const m = this.folderMapping || {};
			if (f === "INBOX" || f === m.inbox) return this.__("Inbox");
			if (f === m.sent) return this.__("Sent");
			if (f === m.drafts) return this.__("Drafts");
			if (f === m.trash) return this.__("Trash");
			if (f === m.spam) return this.__("Spam");
			if (f === m.archive) return this.__("Archive");
			return f.split("/").pop() || f;
		},

		// Filtered recent searches for the cmd-palette dropdown — shows only
		// the entries that contain the currently-typed query (most-recent first),
		// capped at 6 items so the panel stays compact.
		filteredRecent() {
			const q = (this.searchInput || "").trim().toLowerCase();
			if (!q) return this.recentSearches.slice(0, 6);
			return this.recentSearches.filter((s) => s.toLowerCase().includes(q)).slice(0, 6);
		},

		// Initial letter of the active account email, for the topbar avatar mini.
		accountInitial() {
			const email = this.currentAccountEmail || "";
			return (email.charAt(0) || "?").toUpperCase();
		},

		// Two-letter initials of the logged-in Frappe user, for the topbar avatar.
		userInitials() {
			const fullname =
				(window.frappe && (frappe.session.user_fullname || frappe.session.user)) || "";
			const parts = fullname.trim().split(/\s+/);
			if (parts.length >= 2 && parts[0] && parts[1]) {
				return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
			}
			return (fullname.charAt(0) || "?").toUpperCase();
		},

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

	watch: {
		// Debounced live search — fires 400ms after the user stops typing.
		// A monotonic seq guards against out-of-order responses (a slower
		// request resolving after a fresher one).
		searchInput(val) {
			if (this.liveSearchTimer) clearTimeout(this.liveSearchTimer);
			if (!this.hasLiveQuery) {
				this.liveResults = [];
				this.liveSearching = false;
				return;
			}
			this.liveSearchTimer = setTimeout(() => this.runLiveSearch(val), 400);
		},
	},

	mounted() {
		this.initialize().then(() => {
			this.loadQuota();
			this.applyUrlIntent();
		});
		this.exposeWebmailBridge();
		this.loadRecentSearches();
		// ⌘K / Ctrl+K focuses the cmd-palette input from anywhere.
		this._cmdShortcut = (e) => {
			if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
				e.preventDefault();
				const el = this.$refs.cmdSearchInput;
				if (el) {
					el.focus();
					el.select();
				}
			}
		};
		document.addEventListener("keydown", this._cmdShortcut);
		// Icon-only controls (folder rail, top bar, reader, Nora) explain themselves
		this._offTooltips = installTooltips(this.$el);
	},

	beforeUnmount() {
		if (this._offTooltips) {
			this._offTooltips();
		}
		if (this._cmdShortcut) {
			document.removeEventListener("keydown", this._cmdShortcut);
		}
		if (this.searchBlurTimer) {
			clearTimeout(this.searchBlurTimer);
		}
	},

	methods: {
		async loadQuota() {
			this.quota = null;
			if (!this.currentAccount) return;
			try {
				const r = await frappe.call({
					method: "frappe_webmail.webmail_api.get_quota",
					args: { account_name: this.currentAccount },
				});
				this.quota = r.message || null;
			} catch (e) {
				this.quota = null;
			}
		},
		// ===== Command palette (topbar search input + dropdown) =====
		loadRecentSearches() {
			try {
				const raw = localStorage.getItem("webmail_recent_searches");
				this.recentSearches = raw ? JSON.parse(raw) : [];
			} catch (e) {
				this.recentSearches = [];
			}
		},

		saveRecentSearches() {
			try {
				localStorage.setItem(
					"webmail_recent_searches",
					JSON.stringify(this.recentSearches)
				);
			} catch (e) {
				/* localStorage full or disabled - ignore */
			}
		},

		addRecentSearch(s) {
			const trimmed = (s || "").trim();
			if (!trimmed) return;
			// Move to top, dedupe, cap at 12.
			this.recentSearches = [
				trimmed,
				...this.recentSearches.filter((x) => x !== trimmed),
			].slice(0, 12);
			this.saveRecentSearches();
		},

		removeRecent(s) {
			this.recentSearches = this.recentSearches.filter((x) => x !== s);
			this.saveRecentSearches();
			// Keep focus on the input so the dropdown doesn't close.
			this.$nextTick(() => this.$refs.cmdSearchInput?.focus());
		},

		pickRecent(s) {
			this.searchInput = s;
			this.runQuickSearch();
		},

		runQuickSearch() {
			const q = (this.searchInput || "").trim();
			if (!q) return;
			this.addRecentSearch(q);
			this.searchOpen = false;
			this.$refs.cmdSearchInput?.blur();
			// Open the advanced search dialog with the typed query pre-filled
			// — reuses the existing results view inside the modal.
			this.showSearch = true;
		},

		openAdvanced() {
			this.searchOpen = false;
			this.$refs.cmdSearchInput?.blur();
			this.showSearch = true;
		},

		onSearchBlur() {
			// Delay so clicks inside the dropdown fire before it closes.
			this.searchBlurTimer = setTimeout(() => {
				this.searchOpen = false;
			}, 150);
		},

		closeSearch() {
			this.searchOpen = false;
			this.$refs.cmdSearchInput?.blur();
		},

		// Run a live search against the CURRENT folder (fast path) and stream
		// the first ~15 matches into the dropdown. Heavier multi-folder
		// queries stay behind the Advanced search dialog (⏎ on the input).
		async runLiveSearch(query) {
			if (!this.currentAccount || !query || !query.trim()) {
				this.liveResults = [];
				return;
			}
			const seq = ++this.liveSearchSeq;
			this.liveSearching = true;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.search_emails",
					args: {
						account_name: this.currentAccount,
						folder: this.currentFolder || "INBOX",
						query: query.trim(),
						limit: 15,
						offset: 0,
					},
				});
				// Ignore if a fresher query has already been launched.
				if (seq !== this.liveSearchSeq) return;
				const data = response.message || {};
				this.liveResults = (data.emails || []).map((e) => ({
					...e,
					folder: this.currentFolder || "INBOX",
				}));
			} catch (e) {
				if (seq === this.liveSearchSeq) this.liveResults = [];
			} finally {
				if (seq === this.liveSearchSeq) this.liveSearching = false;
			}
		},

		// User clicked a live result row → close the palette and load the
		// email into the reader (same flow as clicking it in the list).
		async pickResult(email) {
			this.closeSearch();
			this.searchInput = "";
			this.liveResults = [];
			// Switch the active folder if the result came from somewhere else.
			if (email.folder && email.folder !== this.currentFolder) {
				this.currentFolder = email.folder;
			}
			await this.onEmailSelect(email);
		},

		// Deterministic gradient class (c1-c6) for the result avatar — same
		// palette as EmailList so the colour for a sender is stable across
		// the inbox and the palette.
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

		formatLiveDate(dateStr) {
			if (!dateStr) return "";
			const d = new Date(dateStr);
			if (isNaN(d.getTime())) return "";
			const now = new Date();
			const sameYear = d.getFullYear() === now.getFullYear();
			return d.toLocaleDateString("fr-FR", {
				day: "numeric",
				month: "short",
				...(sameYear ? {} : { year: "numeric" }),
			});
		},

		async initialize() {
			this.loading = true;

			try {
				await this.loadAccounts();
				// Independent reads — fire them together instead of one after the other.
				await Promise.all([
					this.loadDefaultSignature(),
					this.loadUIPreferences(),
					this.loadCapabilities(),
				]);
			} catch (error) {
				console.error("Initialization error:", error);
			} finally {
				this.loading = false;
			}
		},

		// Deep-link support (used by the NeoCockpit mail panel):
		//   /app/webmail?compose=1                          → open the composer
		//   /app/webmail?account=<name|email>&folder=<F>&uid=<n> → open an email
		// The params are consumed once and stripped from the URL so reloads
		// and the browser back button behave normally afterwards.
		applyUrlIntent() {
			let params;
			try {
				params = new URLSearchParams(window.location.search);
			} catch (e) {
				return;
			}
			if (params.get("compose")) {
				this.compose();
				this.cleanIntentUrl();
				return;
			}
			const uid = parseInt(params.get("uid"), 10);
			if (!uid) return;
			const account = params.get("account");
			if (account) {
				const acc = this.accounts.find((a) => a.name === account || a.email === account);
				if (acc) this.currentAccount = acc.name;
			}
			this.currentFolder = params.get("folder") || "INBOX";
			// open after the account/folder state propagated to children
			this.$nextTick(() => this.onEmailSelect({ uid }));
			this.cleanIntentUrl();
		},

		cleanIntentUrl() {
			try {
				window.history.replaceState({}, "", window.location.pathname);
			} catch (e) {
				/* sandboxed iframe or very old browser — harmless */
			}
		},

		// Expose a small bridge on frappe.webmail so the global error handlers
		// can identify the account currently open when a sign-in fails.
		exposeWebmailBridge() {
			if (!window.frappe) return;
			frappe.provide("frappe.webmail");
			frappe.webmail.getActiveAccount = () => {
				const acc = this.accounts.find((a) => a.name === this.currentAccount);
				if (acc) {
					return {
						name: acc.name,
						email: acc.email,
						auth_type: acc.auth_type,
					};
				}
				return this.currentAccount ? { name: this.currentAccount } : null;
			};
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
			this.loadQuota();
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

		// ── Nora panel ↔ composer bridge ─────────────────────────────────────
		// The panel reads the draft being written and puts text back into it;
		// TipTap lives in the composer, so the parent is the only one who can reach both.
		readComposerState() {
			const c = this.$refs.composer;
			if (!this.showComposer || !c) return null;
			const html = c.editor ? c.editor.getHTML() : "";
			const { own, quote } = splitQuote(html);
			return {
				mode: this.replyToEmail ? "reply" : this.forwardingEmail ? "forward" : "new",
				to: (c.emailData && c.emailData.to) || "",
				subject: (c.emailData && c.emailData.subject) || "",
				html,
				text: c.editor ? c.editor.getText() : "",
				// what the user wrote / the quoted original — Nora only rewrites the former
				own,
				quote,
			};
		},

		openAgentPanel() {
			if (!this.agentPanelOpen) this.toggleAgentPanel();
		},

		// A result from the composer's own Nora bar is reviewed in the panel
		onComposerNoraDraft(payload) {
			this.openAgentPanel();
			let tries = 0;
			const hand = () => {
				const panel = this.$refs.agentPanel;
				if (!panel) {
					if (tries++ < 20) setTimeout(hand, 100);
					return;
				}
				panel.pushDraft(payload);
			};
			this.$nextTick(hand);
		},

		applyDraftToComposer({ html }) {
			const c = this.$refs.composer;
			if (c && html) c.insertNoraContent(html);
		},

		composeWithDraft({ html, subject, to }) {
			this.compose();
			// The composer mounts on the next tick and creates its editor in mounted()
			let tries = 0;
			const fill = () => {
				const c = this.$refs.composer;
				if (!c || !c.editor) {
					if (tries++ < 20) setTimeout(fill, 100);
					return;
				}
				if (to) c.emailData.to = to;
				if (subject) c.emailData.subject = subject;
				if (html) c.insertNoraContent(html);
			};
			this.$nextTick(fill);
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
					const pref = response.message.sidebar_collapsed;
					this.sidebarCollapsedPref =
						pref === null || pref === undefined ? null : !!pref;
					this.applySidebarDefault();
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
							// only once the user has actually chosen (null = leave the default)
							sidebar_collapsed:
								this.sidebarCollapsedPref === null
									? undefined
									: this.sidebarCollapsedPref
									? 1
									: 0,
						},
					});
				} catch (error) {
					console.error("Error saving UI preferences:", error);
				}
			}, 500);
		},

		// Folder column: an explicit user choice wins; otherwise collapse on narrow
		// viewports so the reader keeps a usable width next to the cockpit rail.
		applySidebarDefault() {
			if (this.sidebarCollapsedPref !== null) {
				this.sidebarCollapsed = this.sidebarCollapsedPref;
				return;
			}
			this.sidebarCollapsed = window.innerWidth < 1366;
		},

		toggleAgentPanel() {
			this.agentPanelOpen = !this.agentPanelOpen;
			try {
				localStorage.setItem("webmail_agent_panel_open", this.agentPanelOpen ? "1" : "0");
			} catch (e) {
				/* storage unavailable — fine */
			}
		},

		toggleSidebar() {
			this.sidebarCollapsed = !this.sidebarCollapsed;
			this.sidebarCollapsedPref = this.sidebarCollapsed;
			this.saveUIPreferences();
		},

		async loadCapabilities() {
			try {
				const r = await frappe.call({
					method: "frappe_webmail.webmail_api.get_capabilities",
				});
				this.capabilities = Object.assign({ nora: false }, r.message || {});
			} catch (e) {
				this.capabilities = { nora: false };
			}
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

<!-- ============================================================
     Webmail design tokens — global so child components (FolderTree,
     EmailList, EmailViewer...) can pick them up via var(--wm-*).
     Scoped to .webmail-app so they don't leak across the Frappe Desk.
     ============================================================ -->
<style>
.webmail-app {
	/* === Surface / text — point to Frappe vars so dark mode adapts auto.
	   Fallbacks keep the design working if Frappe ever renames its vars. */
	--wm-bg: var(--bg-color, oklch(0.985 0.004 80));
	--wm-bg-raised: var(--card-bg, #ffffff);
	--wm-bg-sunken: var(--bg-light-gray, oklch(0.965 0.005 80));
	--wm-bg-deeper: var(--bg-gray, oklch(0.955 0.006 80));
	--wm-line: var(--border-color, oklch(0.88 0.012 80));
	--wm-line-soft: var(--border-color, oklch(0.93 0.01 80));
	--wm-line-strong: var(--border-color, oklch(0.78 0.014 78));
	--wm-ink: var(--text-color, oklch(0.22 0.02 250));
	--wm-ink-soft: var(--text-light, var(--text-color, oklch(0.45 0.015 250)));
	--wm-ink-mute: var(--text-muted, oklch(0.62 0.012 250));
	--wm-ink-placeholder: var(--text-muted, oklch(0.72 0.01 70));

	/* === Brand / semantic accents — these stay the same across themes.
	   Only their *-soft variants get overridden under [data-theme="dark"]. */
	--wm-accent: #d68a59;
	--wm-accent-hover: #c2723f;
	--wm-accent-soft: #faefe6;
	--wm-accent-tint: #fdf6f0;
	--wm-nora: #d68a59;
	--wm-nora-2: #dda479;
	--wm-nora-soft: #faefe6;
	--wm-sage: #047857;
	--wm-sage-soft: #d1fae5;
	--wm-amber: #b45309;
	--wm-amber-soft: #fef3c7;
	--wm-rose: #be185d;
	--wm-rose-soft: #fce7f3;
	--wm-danger: #dc2626;
	--wm-danger-soft: #fee2e2;
}

/* ===== Dark mode tweaks =====
   The light pastel "*-soft" backgrounds are unreadable on dark surfaces.
   We swap them for translucent versions of the brand colours so each
   accent keeps its meaning while staying legible against #171717. */
[data-theme="dark"] .webmail-app {
	--wm-accent-soft: rgba(214, 138, 89, 0.22);
	--wm-accent-tint: rgba(214, 138, 89, 0.1);
	--wm-nora-soft: rgba(214, 138, 89, 0.2);
	--wm-sage-soft: rgba(52, 211, 153, 0.18);
	--wm-amber-soft: rgba(245, 158, 11, 0.2);
	--wm-rose-soft: rgba(236, 72, 153, 0.18);
	--wm-danger-soft: rgba(248, 113, 113, 0.18);
}

/* ===== Frappe Desk wrapper overrides =====
   The Frappe Desk page wraps our app in #webmail-app which ships with a
   border, background and radius from the Desk page styles. We strip ALL
   of that so the webmail looks like a flat full-screen app (same trick
   Builder / Insights use).

   CRITICAL: every rule in this <style> block is GLOBAL (no `scoped` on the
   block). Without an extra qualifier these rules would leak to every Desk
   page (Sales Invoice list, Customer form, etc.) and break their layout —
   the `.page-head{display:none}` leak hid the [+ New] / refresh / ⋮ toolbar
   from every list view. We gate each rule with `.page-container:has(.webmail-app)` so
   it only activates while the webmail component is actually mounted. The
   `#webmail-app` and `.webmail-app …` selectors below are inherently scoped
   to the wrapper and don't need the guard. */
#webmail-app {
	border: 0 !important;
	border-radius: 0 !important;
	background: transparent !important;
	box-shadow: none !important;
	height: 100% !important;
	padding: 0 !important;
	margin: 0 !important;
}

.page-container:has(.webmail-app) .layout-main-section-wrapper {
	padding: 0 !important;
	border: 0 !important;
}

.page-container:has(.webmail-app) .row.layout-main {
	margin: 0 !important;
}

.page-container:has(.webmail-app) .layout-main-section,
.page-container:has(.webmail-app) .page-content,
.page-container:has(.webmail-app) .page-wrapper,
.page-container:has(.webmail-app) .row.layout-main,
.page-container:has(.webmail-app) .col-md-12.layout-main-section-wrapper {
	border: 0 !important;
	background: transparent !important;
	height: 100% !important;
}

/* Bootstrap container constrains the page-body to a max-width and adds a
   15px padding. We blow it open so the webmail spans the full viewport. */
.page-container:has(.webmail-app) .container.page-body {
	max-width: none !important;
	width: 100% !important;
	padding: 0 !important;
	margin: 0 !important;
	height: calc(100vh - var(--navbar-height, 60px)) !important;
	overflow: hidden !important;
}

/* Frappe Desk normally has its own top navbar. The webmail topbar starts
   right under it — no need for the page header that sits in between. */
.page-container:has(.webmail-app) .page-head {
	display: none !important;
}

/* Warm Neoffice gradient on the webmail shell — same warm card as the form
   hero, with its dark variant (was light-only before). Outranks the scoped
   .webmail-app[data-v]{background:var(--wm-bg-sunken)}. */
html:not([data-theme="dark"]) .webmail-app {
	background: radial-gradient(
			ellipse 420px 180px at 85% 0%,
			rgba(214, 138, 89, 0.1),
			transparent 70%
		),
		linear-gradient(135deg, #faf3ea 0%, #fffdf8 60%);
}
html[data-theme="dark"] .webmail-app {
	background: radial-gradient(
			ellipse 420px 180px at 85% 0%,
			rgba(214, 138, 89, 0.08),
			transparent 70%
		),
		linear-gradient(135deg, #26211c 0%, #1c2127 60%);
}

/* The Neoffice theme already maps Forum onto every h1-h6. We force the
   same serif on our visual titles (email subject, composer title, list
   header) so the design feels consistent with the rest of Neoffice. */
.webmail-app .email-subject,
.webmail-app .composer-title,
.webmail-app .list-h h2,
.webmail-app .reader-h-top h1,
.webmail-app .no-accounts-content h2 {
	font-family: Forum, Georgia, "Times New Roman", serif;
	font-weight: 400;
	letter-spacing: 0;
}
</style>

<!-- Component-scoped styles for the new layout shell (topbar + grid). -->
<style scoped>
.webmail-app {
	display: grid;
	grid-template-rows: 52px 1fr;
	/* 100% (not 100vh) so the Frappe Desk navbar height is respected.
	   The parent wrappers (#webmail-app, .layout-main-section, …) are
	   already forced to height: 100% via the overrides above. */
	height: 100%;
	min-height: 0;
	background: var(--wm-bg-sunken);
	color: var(--wm-ink);
	font-size: 13.5px;
	overflow: hidden;
}

/* ===== TOPBAR ===== */
.topbar {
	display: flex;
	align-items: center;
	gap: 14px;
	padding: 0 16px;
	background: var(--wm-bg-raised);
	border-bottom: 1px solid var(--wm-line);
}

.brand {
	display: flex;
	align-items: center;
	gap: 10px;
	min-width: 180px;
}

.brand-mark {
	width: 28px;
	height: 28px;
	border-radius: 7px;
	background: linear-gradient(145deg, oklch(0.32 0.025 65), oklch(0.2 0.02 60));
	color: oklch(0.96 0.01 85);
	display: grid;
	place-items: center;
	flex-shrink: 0;
}

.brand-name {
	font-size: 17px;
	font-weight: 500;
	color: var(--wm-ink);
	letter-spacing: -0.005em;
}

/* Account switcher: avatar mini + email select + chevron, in a soft pill */
.account-switch {
	position: relative;
	display: flex;
	align-items: center;
	gap: 8px;
	height: 32px;
	padding: 0 28px 0 8px;
	background: var(--wm-bg-sunken);
	border: 1px solid var(--wm-line);
	border-radius: 8px;
	min-width: 220px;
	max-width: 280px;
	transition: border-color 0.15s;
}

.account-switch:hover {
	border-color: var(--wm-line-strong);
}

.account-switch .av-mini {
	width: 20px;
	height: 20px;
	border-radius: 50%;
	background: var(--wm-accent);
	color: white;
	display: grid;
	place-items: center;
	font-size: 10px;
	font-weight: 600;
	flex-shrink: 0;
}

.account-switch .account-select {
	flex: 1;
	min-width: 0;
	appearance: none;
	-webkit-appearance: none;
	border: 0;
	background: transparent;
	font-size: 12.5px;
	color: var(--wm-ink);
	cursor: pointer;
	outline: none;
	padding: 0;
	font-family: inherit;
}

.account-switch .ch {
	position: absolute;
	right: 10px;
	top: 50%;
	transform: translateY(-50%);
	color: var(--wm-ink-mute);
	pointer-events: none;
}

.sharing-indicator-mini {
	position: relative;
	display: grid;
	place-items: center;
	width: 22px;
	height: 22px;
	border-radius: 5px;
	background: var(--wm-accent-soft);
	color: var(--wm-accent);
	cursor: help;
	flex-shrink: 0;
	margin-right: -22px; /* pull back into the right padding of the switch */
}

.sharing-tooltip {
	position: absolute;
	top: calc(100% + 8px);
	right: 0;
	padding: 6px 10px;
	background: var(--wm-ink);
	color: white;
	font-size: 11px;
	border-radius: 6px;
	white-space: nowrap;
	z-index: 1000;
	box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
	pointer-events: none;
}

/* ===== Command palette: input + dropdown ===== */
.cmd-search {
	position: relative;
	flex: 1;
	max-width: 460px;
	height: 32px;
	padding: 0 12px;
	background: var(--wm-bg-sunken);
	border: 1px solid var(--wm-line);
	border-radius: 8px;
	display: flex;
	align-items: center;
	gap: 10px;
	transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}

.cmd-search:hover {
	border-color: var(--wm-line-strong);
}

.cmd-search.is-open {
	background: var(--wm-bg-raised);
	border-color: var(--wm-accent);
	box-shadow: 0 0 0 3px var(--wm-accent-soft);
}

.cmd-search-icon {
	color: var(--wm-ink-mute);
	flex-shrink: 0;
}

.cmd-search-input {
	flex: 1;
	min-width: 0;
	height: 100%;
	background: transparent;
	border: 0;
	outline: none;
	font-family: inherit;
	font-size: 12.5px;
	color: var(--wm-ink);
	padding: 0;
}

.cmd-search-input::placeholder {
	color: var(--wm-ink-mute);
}

.cmd-search .kbd {
	font-size: 10.5px;
	padding: 1px 6px;
	background: var(--wm-bg-raised);
	border: 1px solid var(--wm-line);
	border-radius: 4px;
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	color: var(--wm-ink-mute);
	flex-shrink: 0;
}

/* Dropdown panel — two side-by-side cards (Recent + Tips). Absolutely
   positioned just below the search input. */
.cmd-dropdown {
	position: absolute;
	top: calc(100% + 6px);
	left: 0;
	right: 0;
	min-width: 640px;
	display: grid;
	grid-template-columns: 1.4fr 1fr;
	gap: 8px;
	z-index: 1100;
	cursor: default;
}

.cmd-panel {
	background: var(--wm-bg-raised);
	border: 1px solid var(--wm-line);
	border-radius: 10px;
	padding: 10px 6px;
	box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}

.cmd-panel-title {
	padding: 2px 12px 6px;
	font-size: 10.5px;
	font-weight: 600;
	letter-spacing: 0.08em;
	text-transform: uppercase;
	color: var(--wm-ink-mute);
}

.cmd-empty {
	padding: 6px 12px 4px;
	font-size: 12px;
	color: var(--wm-ink-mute);
	font-style: italic;
}

.cmd-item {
	display: flex;
	align-items: center;
	gap: 9px;
	width: 100%;
	padding: 6px 10px;
	border: 0;
	background: transparent;
	border-radius: 6px;
	cursor: pointer;
	color: var(--wm-ink-soft);
	font-size: 12.5px;
	font-family: inherit;
	text-align: left;
	transition: background 0.12s, color 0.12s;
}

.cmd-item:hover {
	background: var(--wm-bg-sunken);
	color: var(--wm-ink);
}

.cmd-item > svg {
	color: var(--wm-ink-mute);
	flex-shrink: 0;
}

.cmd-item-text {
	flex: 1;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.cmd-item-remove {
	width: 20px;
	height: 20px;
	display: grid;
	place-items: center;
	border: 0;
	background: transparent;
	border-radius: 4px;
	cursor: pointer;
	color: var(--wm-ink-mute);
	opacity: 0;
	transition: opacity 0.12s, background 0.12s, color 0.12s;
}

.cmd-item:hover .cmd-item-remove {
	opacity: 1;
}

.cmd-item-remove:hover {
	background: var(--wm-line);
	color: var(--wm-ink);
}

/* === Live search results inside the cmd-palette dropdown === */
.cmd-panel-meta {
	margin-left: 6px;
	font-size: 10px;
	font-weight: 500;
	color: var(--wm-ink-mute);
	background: var(--wm-bg-sunken);
	padding: 1px 6px;
	border-radius: 999px;
	letter-spacing: 0;
	text-transform: none;
	font-variant-numeric: tabular-nums;
}

.cmd-spinner {
	display: inline-block;
	width: 11px;
	height: 11px;
	margin-left: 6px;
	border: 1.5px solid var(--wm-line);
	border-top-color: var(--wm-accent);
	border-radius: 50%;
	animation: spin 0.8s linear infinite;
	vertical-align: -1px;
}

.cmd-result {
	display: flex;
	align-items: flex-start;
	gap: 9px;
	width: 100%;
	padding: 7px 10px;
	border: 0;
	background: transparent;
	border-radius: 6px;
	cursor: pointer;
	color: var(--wm-ink);
	font-family: inherit;
	text-align: left;
	transition: background 0.12s;
}

.cmd-result:hover {
	background: var(--wm-bg-sunken);
}

.cmd-result-avatar {
	flex-shrink: 0;
	width: 26px;
	height: 26px;
	border-radius: 50%;
	display: grid;
	place-items: center;
	color: white;
	font-size: 10.5px;
	font-weight: 600;
	margin-top: 1px;
}

.cmd-result-avatar.c1 {
	background: linear-gradient(135deg, var(--wm-accent), var(--wm-nora-2));
}
.cmd-result-avatar.c2 {
	background: linear-gradient(135deg, #b45309, #f59e0b);
}
.cmd-result-avatar.c3 {
	background: linear-gradient(135deg, #047857, #34d399);
}
.cmd-result-avatar.c4 {
	background: linear-gradient(135deg, #be185d, #ec4899);
}
.cmd-result-avatar.c5 {
	background: linear-gradient(135deg, #0e7490, #06b6d4);
}
.cmd-result-avatar.c6 {
	background: linear-gradient(135deg, #6d28d9, #c084fc);
}

.cmd-result-body {
	flex: 1;
	min-width: 0;
}

.cmd-result-top {
	display: flex;
	align-items: baseline;
	gap: 6px;
}

.cmd-result-from {
	flex: 1;
	min-width: 0;
	font-size: 12.5px;
	font-weight: 500;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.cmd-result-date {
	font-size: 10.5px;
	color: var(--wm-ink-mute);
	flex-shrink: 0;
	font-variant-numeric: tabular-nums;
}

.cmd-result-subject {
	font-size: 11.5px;
	color: var(--wm-ink-mute);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

/* Cap the dropdown height and make the inner panels scrollable. */
.cmd-panel-main {
	max-height: 480px;
	overflow-y: auto;
}

.cmd-tip {
	padding: 5px 12px;
	font-size: 12px;
	color: var(--wm-ink-soft);
	line-height: 1.45;
}

.cmd-advanced-btn {
	margin: 6px 10px 0;
	padding: 7px 12px;
	border: 1px solid var(--wm-line);
	background: var(--wm-bg-sunken);
	border-radius: 7px;
	cursor: pointer;
	color: var(--wm-ink);
	font-size: 12px;
	font-weight: 500;
	font-family: inherit;
	display: inline-flex;
	align-items: center;
	gap: 6px;
	transition: background 0.12s, border-color 0.12s;
	width: calc(100% - 20px);
	justify-content: center;
}

.cmd-advanced-btn:hover {
	background: var(--wm-bg-raised);
	border-color: var(--wm-accent);
	color: var(--wm-accent);
}

/* Top actions cluster */
.top-actions {
	margin-left: auto;
	display: flex;
	align-items: center;
	gap: 4px;
}

.icon-btn {
	width: 32px;
	height: 32px;
	display: grid;
	place-items: center;
	border: 0;
	background: transparent;
	border-radius: 7px;
	color: var(--wm-ink-soft);
	cursor: pointer;
	transition: background 0.15s, color 0.15s;
}

.icon-btn:hover {
	background: var(--wm-bg-sunken);
	color: var(--wm-ink);
}

.btn-compose {
	height: 32px;
	padding: 0 14px;
	background: var(--color-primary, #141414);
	color: var(--color-primary-fg, #fffdf8);
	border: 0;
	border-radius: 8px;
	font-size: 12.5px;
	font-weight: 500;
	display: inline-flex;
	align-items: center;
	gap: 6px;
	box-shadow: 0 1px 2px rgba(20, 18, 16, 0.22);
	cursor: pointer;
	transition: background 0.15s;
	font-family: inherit;
}

.btn-compose:hover {
	background: var(--color-primary-hover, #232020);
}

/* DS: on dark, the primary button flips to a bright paper button (ink text) */
[data-theme="dark"] .btn-compose {
	background: var(--color-primary, #fffdf8);
	color: var(--color-primary-fg, #141414);
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
}

[data-theme="dark"] .btn-compose:hover {
	background: var(--color-primary-hover, #ece7de);
}

.avatar-me {
	width: 28px;
	height: 28px;
	border-radius: 50%;
	background: var(--wm-rose-soft);
	color: var(--wm-rose);
	display: grid;
	place-items: center;
	font-size: 11px;
	font-weight: 600;
	margin-left: 6px;
	flex-shrink: 0;
}

/* ===== MAIN — flex row with two draggable resizers ===== */
.main {
	display: flex;
	min-height: 0;
	overflow: hidden;
	height: 100%;
}

.main.is-resizing {
	cursor: col-resize;
}

.main.is-resizing * {
	pointer-events: none;
}

.sidebar-col {
	/* Background stays transparent so the sidebar blends into the webmail
	   surface — but a thin right border separates it from the email list,
	   matching the design reference. */
	background: transparent;
	border-right: 1px solid var(--wm-line);
	display: flex;
	flex-direction: column;
	overflow-y: auto;
	overflow-x: hidden;
	flex-shrink: 0;
	min-width: 0;
}

/* Slim drag handle between two columns. A 6px-wide hit area with a
   visible centered bar that grows on hover/active. */
.column-resizer {
	width: 6px;
	flex-shrink: 0;
	cursor: col-resize;
	background: transparent;
	display: flex;
	align-items: center;
	justify-content: center;
	margin: 0 -3px;
	position: relative;
	z-index: 10;
	transition: background 0.15s ease;
}

.column-resizer:hover,
.main.is-resizing .column-resizer {
	background: var(--wm-accent-soft);
}

.resizer-handle {
	width: 3px;
	height: 36px;
	background: var(--wm-line);
	border-radius: 2px;
	transition: background 0.15s ease, height 0.15s ease;
}

.column-resizer:hover .resizer-handle,
.main.is-resizing .resizer-handle {
	background: var(--wm-accent);
	height: 56px;
}

/* The FolderTree component wraps itself — we just give it a flex slot. */
.sb-folders {
	flex-shrink: 0;
}

/* Collapsed folder column: a 56px icon rail (FolderTree renders its compact
   mode, the quota block is hidden — no room for text). */
.sidebar-col.is-collapsed {
	overflow: visible;
}

.sb-toggle {
	flex-shrink: 0;
	margin-right: -6px;
}

.icon-btn.is-on {
	background: var(--wm-accent-soft);
	color: var(--wm-accent);
}

/* Nora column: fixed width, right of the reader, hidden on narrow screens */
.agent-col {
	width: 360px;
	flex-shrink: 0;
	min-width: 0;
	border-left: 1px solid var(--wm-line);
	display: flex;
	flex-direction: column;
	min-height: 0;
}

@media (max-width: 1100px) {
	.agent-col {
		display: none;
	}
}

/* Storage indicator pinned to the bottom of the sidebar.
   (Values are placeholders until we wire IMAP quota; the bar is hidden
   when the data isn't available so we don't show a misleading fill.) */
.storage {
	margin-top: auto;
	padding: 12px 14px;
	border-top: 1px solid var(--wm-line-soft);
	font-size: 11px;
	color: var(--wm-ink-mute);
	flex-shrink: 0;
}

.storage-top {
	display: flex;
	justify-content: space-between;
	align-items: center;
}

.upgrade {
	color: var(--wm-accent);
	cursor: pointer;
	text-decoration: none;
	font-weight: 500;
}

.upgrade:hover {
	text-decoration: underline;
}

.storage-bar {
	height: 4px;
	background: var(--wm-bg-sunken);
	border-radius: 2px;
	overflow: hidden;
	margin: 6px 0 4px;
}

.storage-bar > span {
	display: block;
	height: 100%;
	width: 0;
	background: linear-gradient(90deg, var(--wm-accent), var(--wm-nora-2));
	border-radius: 2px;
}

.storage-email {
	font-size: 11px;
	color: var(--wm-ink-mute);
	word-break: break-all;
}

.list-col {
	background: var(--wm-bg-raised);
	border-right: 1px solid var(--wm-line);
	display: flex;
	flex-direction: column;
	min-height: 0;
	min-width: 0;
	flex-shrink: 0;
	overflow: hidden;
}

.reader-col {
	/* Transparent by default — when no email is selected the column shows
	   through to the webmail surface, focusing the eye on the email list.
	   .email-viewer itself paints its own bg-raised when an email is open. */
	background: transparent;
	display: flex;
	flex-direction: column;
	min-height: 0;
	min-width: 0;
	flex: 1;
	overflow: hidden;
}

/* ===== Empty state, loading, modals ===== */
.no-accounts {
	grid-column: 1 / -1;
	display: flex;
	align-items: center;
	justify-content: center;
	background: var(--wm-bg-raised);
}

.no-accounts-content {
	text-align: center;
	padding: 40px;
}

.no-accounts-content h2 {
	margin: 0 0 16px;
	color: var(--wm-ink);
}

.no-accounts-content p {
	margin: 0 0 24px;
	color: var(--wm-ink-mute);
}

.loading-overlay {
	position: fixed;
	inset: 0;
	background: rgba(255, 255, 255, 0.92);
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	z-index: 1000;
}

.spinner {
	width: 40px;
	height: 40px;
	border: 3px solid var(--wm-line);
	border-top-color: var(--wm-accent);
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
	inset: 0;
	background: rgba(0, 0, 0, 0.5);
	display: flex;
	align-items: center;
	justify-content: center;
	z-index: 1000;
}

.modal-content {
	background: var(--wm-bg-raised);
	border-radius: 12px;
	overflow: hidden;
	box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
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

.automations-modal {
	width: 720px;
	max-width: 92vw;
	max-height: 86vh;
	overflow: hidden;
	display: flex;
	flex-direction: column;
}

/* ===== Responsive (flex-based) ===== */
@media (max-width: 768px) {
	.sidebar-col,
	.reader-col,
	.column-resizer {
		display: none;
	}
	.list-col {
		flex: 1;
		width: auto !important;
	}
}
</style>
