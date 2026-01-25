<template>
	<div class="advanced-search">
		<div class="search-header">
			<h3>Recherche avancee</h3>
			<button @click="$emit('close')" class="close-btn">&times;</button>
		</div>

		<div class="search-form">
			<!-- Quick search -->
			<div class="form-group">
				<label>Recherche generale</label>
				<input
					v-model="filters.query"
					type="text"
					placeholder="Rechercher dans tous les champs..."
					@keyup.enter="search"
				/>
			</div>

			<!-- From -->
			<div class="form-group">
				<label>De</label>
				<input
					v-model="filters.from"
					type="text"
					placeholder="Adresse email de l'expediteur"
				/>
			</div>

			<!-- To -->
			<div class="form-group">
				<label>A</label>
				<input
					v-model="filters.to"
					type="text"
					placeholder="Adresse email du destinataire"
				/>
			</div>

			<!-- Subject -->
			<div class="form-group">
				<label>Objet</label>
				<input v-model="filters.subject" type="text" placeholder="Mots dans l'objet" />
			</div>

			<!-- Date range -->
			<div class="form-row">
				<div class="form-group">
					<label>Date debut</label>
					<input v-model="filters.dateFrom" type="date" />
				</div>
				<div class="form-group">
					<label>Date fin</label>
					<input v-model="filters.dateTo" type="date" />
				</div>
			</div>

			<!-- Checkboxes -->
			<div class="form-row checkboxes">
				<label class="checkbox-label">
					<input type="checkbox" v-model="filters.hasAttachment" />
					Avec pieces jointes
				</label>
				<label class="checkbox-label">
					<input type="checkbox" v-model="filters.isUnread" />
					Non lus uniquement
				</label>
				<label class="checkbox-label">
					<input type="checkbox" v-model="filters.isFlagged" />
					Marques uniquement
				</label>
			</div>

			<!-- Folder selection -->
			<div class="form-group">
				<label>Dossier</label>
				<select v-model="filters.folder">
					<option v-for="folder in folders" :key="folder.name" :value="folder.name">
						{{ folder.name }}
					</option>
				</select>
			</div>
		</div>

		<div class="search-actions">
			<button @click="clearFilters" class="btn btn-secondary">Effacer</button>
			<button @click="search" class="btn btn-primary" :disabled="searching">
				{{ searching ? "Recherche..." : "Rechercher" }}
			</button>
		</div>

		<!-- Results -->
		<div class="search-results" v-if="hasSearched">
			<div class="results-header">
				<span>{{ results.length }} resultat(s) sur {{ total }}</span>
				<button v-if="hasMore" @click="loadMore" class="btn btn-link">Charger plus</button>
			</div>

			<div class="results-list" v-if="results.length">
				<div
					v-for="email in results"
					:key="email.uid"
					class="result-item"
					:class="{ unread: !email.seen }"
					@click="selectEmail(email)"
				>
					<div class="result-from">{{ email.from_name || email.from_email }}</div>
					<div class="result-subject">{{ email.subject || "(Sans objet)" }}</div>
					<div class="result-date">{{ formatDate(email.date) }}</div>
				</div>
			</div>

			<div class="no-results" v-else>Aucun resultat trouve</div>
		</div>
	</div>
</template>

<script>
export default {
	name: "AdvancedSearch",

	props: {
		account: { type: String, required: true },
		folders: { type: Array, default: () => [] },
		initialFolder: { type: String, default: "INBOX" },
	},

	emits: ["close", "select"],

	data() {
		return {
			filters: {
				query: "",
				from: "",
				to: "",
				subject: "",
				dateFrom: "",
				dateTo: "",
				hasAttachment: false,
				isUnread: false,
				isFlagged: false,
				folder: this.initialFolder,
			},
			results: [],
			total: 0,
			hasMore: false,
			searching: false,
			hasSearched: false,
		};
	},

	methods: {
		async search() {
			this.searching = true;
			this.hasSearched = true;
			this.results = [];

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.search_emails",
					args: {
						account_name: this.account,
						folder: this.filters.folder,
						query: this.filters.query || null,
						from_filter: this.filters.from || null,
						to_filter: this.filters.to || null,
						subject_filter: this.filters.subject || null,
						date_from: this.filters.dateFrom || null,
						date_to: this.filters.dateTo || null,
						has_attachment: this.filters.hasAttachment || null,
						is_unread: this.filters.isUnread || null,
						is_flagged: this.filters.isFlagged || null,
						limit: 50,
						offset: 0,
					},
				});

				const data = response.message;
				this.results = data.emails;
				this.total = data.total;
				this.hasMore = data.has_more;
			} catch (error) {
				frappe.toast({ message: "Erreur de recherche", indicator: "red" });
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
					args: {
						account_name: this.account,
						folder: this.filters.folder,
						query: this.filters.query || null,
						from_filter: this.filters.from || null,
						to_filter: this.filters.to || null,
						subject_filter: this.filters.subject || null,
						date_from: this.filters.dateFrom || null,
						date_to: this.filters.dateTo || null,
						has_attachment: this.filters.hasAttachment || null,
						is_unread: this.filters.isUnread || null,
						is_flagged: this.filters.isFlagged || null,
						limit: 50,
						offset: this.results.length,
					},
				});

				const data = response.message;
				this.results.push(...data.emails);
				this.hasMore = data.has_more;
			} catch (error) {
				frappe.toast({ message: "Erreur", indicator: "red" });
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
				folder: this.initialFolder,
			};
			this.results = [];
			this.hasSearched = false;
		},

		selectEmail(email) {
			this.$emit("select", {
				email,
				folder: this.filters.folder,
			});
		},

		formatDate(dateStr) {
			if (!dateStr) return "";
			const date = new Date(dateStr);
			return date.toLocaleDateString("fr-FR", {
				day: "numeric",
				month: "short",
				year: "numeric",
			});
		},
	},
};
</script>

<style scoped>
.advanced-search {
	display: flex;
	flex-direction: column;
	height: 100%;
	padding: 16px;
}

.search-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	margin-bottom: 16px;
}

.search-header h3 {
	margin: 0;
	font-size: 18px;
}

.close-btn {
	background: none;
	border: none;
	font-size: 24px;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
}

.close-btn:hover {
	color: var(--text-color, #333);
}

.search-form {
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.form-group {
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.form-group label {
	font-size: 12px;
	font-weight: 500;
	color: var(--text-muted, #8d99a6);
}

.form-group input,
.form-group select {
	padding: 8px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	font-size: 14px;
}

.form-group input:focus,
.form-group select:focus {
	outline: none;
	border-color: var(--primary-color, #2490ef);
}

.form-row {
	display: flex;
	gap: 12px;
}

.form-row .form-group {
	flex: 1;
}

.form-row.checkboxes {
	flex-wrap: wrap;
}

.checkbox-label {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
	cursor: pointer;
}

.checkbox-label input {
	margin: 0;
}

.search-actions {
	display: flex;
	justify-content: flex-end;
	gap: 8px;
	margin-top: 16px;
	padding-top: 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
}

.btn {
	padding: 8px 16px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	cursor: pointer;
	font-size: 13px;
}

.btn-primary {
	background: var(--primary-color, #2490ef);
	color: white;
	border-color: var(--primary-color, #2490ef);
}

.btn-primary:hover {
	background: #1a7fd4;
}

.btn-primary:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}

.btn-secondary {
	background: white;
}

.btn-secondary:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.btn-link {
	background: none;
	border: none;
	color: var(--primary-color, #2490ef);
	padding: 4px 8px;
}

.btn-link:hover {
	text-decoration: underline;
}

.search-results {
	flex: 1;
	margin-top: 16px;
	overflow: hidden;
	display: flex;
	flex-direction: column;
}

.results-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 8px 0;
	font-size: 13px;
	color: var(--text-muted, #8d99a6);
}

.results-list {
	flex: 1;
	overflow-y: auto;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
}

.result-item {
	padding: 10px 12px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	cursor: pointer;
}

.result-item:last-child {
	border-bottom: none;
}

.result-item:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.result-item.unread {
	font-weight: 600;
	background: #f0f7ff;
}

.result-from {
	font-size: 13px;
	margin-bottom: 2px;
}

.result-subject {
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.result-date {
	font-size: 11px;
	color: var(--text-muted, #8d99a6);
	margin-top: 4px;
}

.no-results {
	padding: 40px;
	text-align: center;
	color: var(--text-muted, #8d99a6);
}
</style>
