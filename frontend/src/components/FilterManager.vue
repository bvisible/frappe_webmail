<template>
	<div class="filter-manager">
		<div class="manager-header">
			<h3>Filtres email</h3>
			<button @click="$emit('close')" class="close-btn">&times;</button>
		</div>

		<div class="manager-content">
			<!-- Filter List -->
			<div class="filter-list" v-if="!showForm">
				<div class="list-header">
					<span>{{ filters.length }} filtre(s)</span>
					<button @click="showCreateForm" class="btn btn-primary btn-sm">
						+ Nouveau filtre
					</button>
				</div>

				<div v-if="filters.length" class="filters">
					<div
						v-for="filter in filters"
						:key="filter.name"
						class="filter-item"
						:class="{ disabled: !filter.enabled }"
					>
						<div class="filter-info">
							<div class="filter-name">
								{{ filter.filter_name }}
								<span v-if="!filter.enabled" class="badge disabled"
									>(desactive)</span
								>
							</div>
							<div class="filter-conditions">
								<span v-if="filter.from_contains"
									>De: {{ filter.from_contains }}</span
								>
								<span v-if="filter.to_contains">A: {{ filter.to_contains }}</span>
								<span v-if="filter.subject_contains"
									>Objet: {{ filter.subject_contains }}</span
								>
								<span v-if="filter.has_attachment">Avec PJ</span>
							</div>
							<div class="filter-action">→ {{ getActionLabel(filter) }}</div>
							<div class="filter-stats" v-if="filter.times_applied">
								Applique {{ filter.times_applied }} fois
							</div>
						</div>
						<div class="filter-actions">
							<button
								@click="toggleFilter(filter)"
								class="btn-icon"
								:title="filter.enabled ? 'Desactiver' : 'Activer'"
							>
								{{ filter.enabled ? "✓" : "○" }}
							</button>
							<button @click="editFilter(filter)" class="btn-icon" title="Modifier">
								✏️
							</button>
							<button
								@click="deleteFilter(filter)"
								class="btn-icon"
								title="Supprimer"
							>
								🗑️
							</button>
						</div>
					</div>
				</div>

				<div v-else class="empty-state">
					<p>Aucun filtre configure.</p>
					<p>Les filtres permettent de trier automatiquement vos emails.</p>
				</div>

				<div class="list-footer">
					<button
						@click="applyFiltersNow"
						class="btn btn-secondary"
						:disabled="!filters.length || applying"
					>
						{{ applying ? "Application..." : "Appliquer maintenant" }}
					</button>
				</div>
			</div>

			<!-- Filter Form -->
			<div class="filter-form" v-else>
				<div class="form-header">
					<h4>{{ editingFilter ? "Modifier le filtre" : "Nouveau filtre" }}</h4>
				</div>

				<div class="form-body">
					<div class="form-group">
						<label>Nom du filtre *</label>
						<input
							v-model="formData.filter_name"
							type="text"
							placeholder="Ex: Newsletters"
						/>
					</div>

					<div class="form-section">
						<h5>Conditions</h5>
						<div class="form-group">
							<label>Correspondance</label>
							<select v-model="formData.match_type">
								<option value="any">Au moins une condition (OU)</option>
								<option value="all">Toutes les conditions (ET)</option>
							</select>
						</div>

						<div class="form-group">
							<label>De contient</label>
							<input
								v-model="formData.from_contains"
								type="text"
								placeholder="Ex: newsletter@"
							/>
						</div>

						<div class="form-group">
							<label>A contient</label>
							<input
								v-model="formData.to_contains"
								type="text"
								placeholder="Ex: moi@example.com"
							/>
						</div>

						<div class="form-group">
							<label>Objet contient</label>
							<input
								v-model="formData.subject_contains"
								type="text"
								placeholder="Ex: [SPAM]"
							/>
						</div>

						<div class="form-group checkbox">
							<label>
								<input type="checkbox" v-model="formData.has_attachment" />
								A des pieces jointes
							</label>
						</div>
					</div>

					<div class="form-section">
						<h5>Actions</h5>
						<div class="form-group">
							<label>Action principale *</label>
							<select v-model="formData.action_type">
								<option value="move">Deplacer vers un dossier</option>
								<option value="delete">Supprimer</option>
								<option value="mark_read">Marquer comme lu</option>
								<option value="mark_starred">Marquer comme important</option>
							</select>
						</div>

						<div class="form-group" v-if="formData.action_type === 'move'">
							<label>Dossier de destination *</label>
							<select v-model="formData.target_folder">
								<option value="">Selectionner...</option>
								<option
									v-for="folder in folders"
									:key="folder.name"
									:value="folder.name"
								>
									{{ folder.name }}
								</option>
							</select>
						</div>

						<div class="form-group checkbox">
							<label>
								<input type="checkbox" v-model="formData.mark_as_read" />
								Marquer aussi comme lu
							</label>
						</div>

						<div class="form-group checkbox">
							<label>
								<input type="checkbox" v-model="formData.mark_as_starred" />
								Marquer aussi comme important
							</label>
						</div>
					</div>
				</div>

				<div class="form-footer">
					<button @click="cancelForm" class="btn btn-secondary">Annuler</button>
					<button @click="saveFilter" class="btn btn-primary" :disabled="saving">
						{{ saving ? "Enregistrement..." : "Enregistrer" }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<script>
export default {
	name: "FilterManager",

	props: {
		account: { type: String, required: true },
		folders: { type: Array, default: () => [] },
	},

	emits: ["close"],

	data() {
		return {
			filters: [],
			showForm: false,
			editingFilter: null,
			formData: this.getEmptyFormData(),
			loading: false,
			saving: false,
			applying: false,
		};
	},

	mounted() {
		this.loadFilters();
	},

	methods: {
		getEmptyFormData() {
			return {
				filter_name: "",
				match_type: "any",
				from_contains: "",
				to_contains: "",
				subject_contains: "",
				has_attachment: false,
				action_type: "move",
				target_folder: "",
				mark_as_read: false,
				mark_as_starred: false,
			};
		},

		async loadFilters() {
			this.loading = true;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_filters",
					args: { account_name: this.account },
				});
				this.filters = response.message || [];
			} catch (error) {
				frappe.toast({ message: "Erreur de chargement des filtres", indicator: "red" });
			} finally {
				this.loading = false;
			}
		},

		showCreateForm() {
			this.editingFilter = null;
			this.formData = this.getEmptyFormData();
			this.showForm = true;
		},

		editFilter(filter) {
			this.editingFilter = filter;
			this.formData = {
				filter_name: filter.filter_name,
				match_type: filter.match_type,
				from_contains: filter.from_contains || "",
				to_contains: filter.to_contains || "",
				subject_contains: filter.subject_contains || "",
				has_attachment: !!filter.has_attachment,
				action_type: filter.action_type,
				target_folder: filter.target_folder || "",
				mark_as_read: !!filter.mark_as_read,
				mark_as_starred: !!filter.mark_as_starred,
			};
			this.showForm = true;
		},

		cancelForm() {
			this.showForm = false;
			this.editingFilter = null;
			this.formData = this.getEmptyFormData();
		},

		async saveFilter() {
			// Validation
			if (!this.formData.filter_name) {
				frappe.toast({ message: "Le nom du filtre est requis", indicator: "orange" });
				return;
			}

			const hasCondition =
				this.formData.from_contains ||
				this.formData.to_contains ||
				this.formData.subject_contains ||
				this.formData.has_attachment;

			if (!hasCondition) {
				frappe.toast({
					message: "Au moins une condition est requise",
					indicator: "orange",
				});
				return;
			}

			if (this.formData.action_type === "move" && !this.formData.target_folder) {
				frappe.toast({
					message: "Le dossier de destination est requis",
					indicator: "orange",
				});
				return;
			}

			this.saving = true;

			try {
				if (this.editingFilter) {
					await frappe.call({
						method: "frappe_webmail.api.update_filter",
						args: {
							filter_name: this.editingFilter.name,
							...this.formData,
						},
					});
					frappe.toast({ message: "Filtre modifie", indicator: "green" });
				} else {
					await frappe.call({
						method: "frappe_webmail.api.create_filter",
						args: {
							account_name: this.account,
							...this.formData,
						},
					});
					frappe.toast({ message: "Filtre cree", indicator: "green" });
				}

				this.cancelForm();
				this.loadFilters();
			} catch (error) {
				frappe.toast({ message: "Erreur lors de l'enregistrement", indicator: "red" });
			} finally {
				this.saving = false;
			}
		},

		async toggleFilter(filter) {
			try {
				await frappe.call({
					method: "frappe_webmail.api.update_filter",
					args: {
						filter_name: filter.name,
						enabled: !filter.enabled,
					},
				});
				filter.enabled = !filter.enabled;
			} catch (error) {
				frappe.toast({ message: "Erreur", indicator: "red" });
			}
		},

		async deleteFilter(filter) {
			if (!confirm(`Supprimer le filtre "${filter.filter_name}" ?`)) return;

			try {
				await frappe.call({
					method: "frappe_webmail.api.delete_filter",
					args: { filter_name: filter.name },
				});
				frappe.toast({ message: "Filtre supprime", indicator: "green" });
				this.loadFilters();
			} catch (error) {
				frappe.toast({ message: "Erreur lors de la suppression", indicator: "red" });
			}
		},

		async applyFiltersNow() {
			this.applying = true;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.apply_filters_to_folder",
					args: {
						account_name: this.account,
						folder: "INBOX",
						limit: 100,
					},
				});

				const result = response.message;
				frappe.toast({
					message: `${result.applied} filtre(s) applique(s) sur ${result.processed} emails`,
					indicator: "green",
				});

				this.loadFilters(); // Refresh stats
			} catch (error) {
				frappe.toast({ message: "Erreur lors de l'application", indicator: "red" });
			} finally {
				this.applying = false;
			}
		},

		getActionLabel(filter) {
			const actions = {
				move: `Deplacer vers ${filter.target_folder || "?"}`,
				delete: "Supprimer",
				mark_read: "Marquer comme lu",
				mark_starred: "Marquer comme important",
			};
			return actions[filter.action_type] || filter.action_type;
		},
	},
};
</script>

<style scoped>
.filter-manager {
	display: flex;
	flex-direction: column;
	height: 100%;
}

.manager-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.manager-header h3 {
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

.manager-content {
	flex: 1;
	overflow-y: auto;
	padding: 16px;
}

.list-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	margin-bottom: 16px;
}

.filters {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.filter-item {
	display: flex;
	justify-content: space-between;
	padding: 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	background: white;
}

.filter-item.disabled {
	opacity: 0.6;
	background: var(--bg-light-gray, #f5f5f5);
}

.filter-info {
	flex: 1;
}

.filter-name {
	font-weight: 500;
	margin-bottom: 4px;
}

.badge.disabled {
	font-size: 11px;
	font-weight: normal;
	color: var(--text-muted, #8d99a6);
}

.filter-conditions {
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
}

.filter-conditions span {
	background: var(--bg-light-gray, #f5f5f5);
	padding: 2px 6px;
	border-radius: 4px;
}

.filter-action {
	font-size: 12px;
	margin-top: 4px;
	color: var(--primary-color, #2490ef);
}

.filter-stats {
	font-size: 11px;
	color: var(--text-muted, #8d99a6);
	margin-top: 4px;
}

.filter-actions {
	display: flex;
	gap: 4px;
	align-items: flex-start;
}

.btn-icon {
	background: none;
	border: none;
	cursor: pointer;
	padding: 4px 8px;
	font-size: 14px;
	border-radius: 4px;
}

.btn-icon:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.empty-state {
	text-align: center;
	padding: 40px;
	color: var(--text-muted, #8d99a6);
}

.list-footer {
	margin-top: 16px;
	padding-top: 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
}

/* Form styles */
.form-header {
	margin-bottom: 16px;
}

.form-header h4 {
	margin: 0;
}

.form-body {
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.form-section {
	margin-top: 16px;
}

.form-section h5 {
	margin: 0 0 12px 0;
	font-size: 14px;
	color: var(--text-muted, #8d99a6);
}

.form-group {
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.form-group label {
	font-size: 12px;
	font-weight: 500;
}

.form-group input[type="text"],
.form-group select {
	padding: 8px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	font-size: 14px;
}

.form-group.checkbox {
	flex-direction: row;
	align-items: center;
}

.form-group.checkbox label {
	display: flex;
	align-items: center;
	gap: 8px;
	font-weight: normal;
	cursor: pointer;
}

.form-footer {
	display: flex;
	justify-content: flex-end;
	gap: 8px;
	margin-top: 24px;
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

.btn-sm {
	padding: 4px 12px;
	font-size: 12px;
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

.btn-secondary:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}
</style>
