<template>
	<Teleport to="body">
		<div class="dfp-veil" @click.self="$emit('close')" @keydown.esc="$emit('close')">
			<div
				class="dfp"
				role="dialog"
				aria-modal="true"
				:aria-label="__('Attach to a Neoffice document')"
			>
				<header class="dfp-head">
					<h2 class="dfp-title">{{ __("Attach to a Neoffice document") }}</h2>
					<button class="dfp-icon" :aria-label="__('Close')" @click="$emit('close')">
						<X :size="16" />
					</button>
				</header>

				<div class="dfp-body">
					<div v-if="attachment" class="dfp-file">
						<FileText :size="16" />
						<span class="dfp-file-name">{{ attachment.filename }}</span>
					</div>

					<div class="dcp-kinds" role="radiogroup">
						<button
							v-for="kind in kinds"
							:key="kind.doctype"
							class="dcp-kind"
							:class="{ on: doctype === kind.doctype }"
							role="radio"
							:aria-checked="String(doctype === kind.doctype)"
							@click="choose(kind.doctype)"
						>
							{{ kind.label }}
						</button>
					</div>

					<label class="dfp-search">
						<Search :size="15" />
						<input
							ref="search"
							v-model="query"
							type="text"
							:placeholder="__('Search')"
							:disabled="!doctype"
							@input="onSearch"
						/>
					</label>

					<div class="dfp-tree" role="listbox">
						<div v-if="!doctype" class="dfp-empty">
							{{ __("No kind of document can be attached to here") }}
						</div>
						<div v-else-if="loading" class="dfp-empty">{{ __("Loading…") }}</div>
						<div v-else-if="!results.length" class="dfp-empty">
							{{ __("No document found") }}
						</div>
						<button
							v-for="r in results"
							:key="r.value"
							class="dfp-row"
							:class="{ on: selected === r.value }"
							role="option"
							:aria-selected="String(selected === r.value)"
							@click="selected = r.value"
							@dblclick="attach"
						>
							<span class="dfp-row-text">
								<span>{{ r.value }}</span>
								<small v-if="r.description">{{ r.description }}</small>
							</span>
						</button>
					</div>
				</div>

				<footer class="dfp-foot">
					<span class="dfp-spacer" />
					<button class="dfp-btn ink" :disabled="!selected || busy" @click="attach">
						{{ busy ? __("Attaching…") : __("Attach") }}
					</button>
				</footer>
			</div>
		</div>
	</Teleport>
</template>

<script>
import { FileText, Search, X } from "lucide-vue-next";

export default {
	name: "DocumentPicker",

	components: { FileText, Search, X },

	props: {
		attachment: { type: Object, default: null },
		busy: { type: Boolean, default: false },
	},

	emits: ["pick", "close"],

	data() {
		return {
			kinds: [],
			doctype: null,
			query: "",
			results: [],
			selected: null,
			loading: false,
			searchTimer: null,
		};
	},

	async mounted() {
		const r = await frappe.call({
			method: "frappe_webmail.attachments.get_attachable_doctypes",
		});
		this.kinds = r.message || [];
		if (this.kinds.length) this.choose(this.kinds[0].doctype);
	},

	beforeUnmount() {
		clearTimeout(this.searchTimer);
	},

	methods: {
		async choose(doctype) {
			this.doctype = doctype;
			this.selected = null;
			await this.load();
			this.$nextTick(() => this.$refs.search?.focus());
		},
		onSearch() {
			clearTimeout(this.searchTimer);
			this.searchTimer = setTimeout(() => this.load(), 250);
		},
		async load() {
			if (!this.doctype) return;
			const text = this.query.trim();
			const doctype = this.doctype;
			this.loading = true;
			try {
				const r = await frappe.call({
					method: text
						? "frappe_webmail.webmail_api.search_documents"
						: "frappe_webmail.webmail_api.get_recent_documents",
					args: text ? { doctype, search_text: text } : { doctype },
				});
				// A slower answer for another kind or another word is not this one's
				if (this.doctype === doctype && this.query.trim() === text)
					this.results = r.message || [];
			} finally {
				this.loading = false;
			}
		},
		attach() {
			if (this.selected)
				this.$emit("pick", { doctype: this.doctype, docname: this.selected });
		},
	},
};
</script>

<style>
.dcp-kinds {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
}
.dcp-kind {
	height: 30px;
	padding: 0 12px;
	border: 1px solid var(--wm-line, var(--border-color));
	border-radius: 999px;
	background: var(--wm-bg-raised, var(--card-bg));
	color: var(--wm-ink, var(--text-color));
	font-family: inherit;
	font-size: 13px;
	font-weight: 600;
	line-height: 1;
	cursor: pointer;
}
.dcp-kind.on {
	border-color: var(--wm-accent);
	background: var(--wm-accent-soft);
	color: var(--wm-accent-hover);
}
</style>
