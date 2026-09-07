<template>
	<div class="automations">
		<div class="au-head">
			<div class="au-title">
				<span class="au-mark"><Bot :size="16" :stroke-width="1.7" /></span>
				<div>
					<h3>{{ __("Nora automations") }}</h3>
					<p class="au-sub">{{ accountEmail || account }}</p>
				</div>
			</div>
			<button class="au-close" @click="$emit('close')" :title="__('Close')">
				<X :size="16" />
			</button>
		</div>

		<div class="au-body">
			<!-- Existing automations on this mailbox -->
			<section class="au-section">
				<div class="au-section-title">
					{{ __("Active on this mailbox") }}
					<button
						class="au-refresh"
						@click="load"
						:disabled="loading"
						:title="__('Refresh')"
					>
						<RefreshCw :size="13" :class="{ spin: loading }" />
					</button>
				</div>

				<div v-if="loading && !items.length" class="au-empty">{{ __("Loading...") }}</div>
				<div v-else-if="!items.length" class="au-empty">
					{{
						__(
							"No automation yet. Create one below — Nora will check this mailbox on schedule."
						)
					}}
				</div>

				<div
					v-for="b in items"
					:key="b.id"
					class="au-item"
					:class="{ paused: !b.enabled }"
				>
					<div class="au-item-ic">
						<component :is="kindIcon(b)" :size="16" :stroke-width="1.7" />
					</div>
					<div class="au-item-main">
						<div class="au-item-title">{{ b.briefing_title }}</div>
						<div class="au-item-meta">
							<span>{{ cadenceLabel(b) }}</span>
							<span class="dot">·</span>
							<span>{{ lastRunLabel(b) }}</span>
						</div>
						<div
							v-if="results[b.id]"
							class="au-result"
							:class="{ ok: results[b.id].ok }"
						>
							{{ results[b.id].text }}
						</div>
					</div>
					<div class="au-item-status">
						<span
							v-if="b.consecutive_failures >= 3 || !b.enabled"
							class="pill pill-off"
						>
							{{ b.enabled ? __("Failing") : __("Paused") }}
						</span>
						<span v-else class="pill pill-on">{{ __("Active") }}</span>
					</div>
					<div class="au-item-actions">
						<button
							class="au-act"
							@click="runNow(b)"
							:disabled="busy[b.id]"
							:title="__('Run now')"
						>
							<Loader2 v-if="busy[b.id]" :size="14" class="spin" />
							<Play v-else :size="14" />
						</button>
						<button
							class="au-act"
							@click="togglePause(b)"
							:disabled="busy[b.id]"
							:title="b.enabled ? __('Pause') : __('Resume')"
						>
							<Pause v-if="b.enabled" :size="14" />
							<PlayCircle v-else :size="14" />
						</button>
						<button
							class="au-act danger"
							@click="remove(b)"
							:disabled="busy[b.id]"
							:title="__('Delete')"
						>
							<Trash2 :size="14" />
						</button>
					</div>
				</div>
			</section>

			<!-- New automation -->
			<section class="au-section">
				<div class="au-section-title">{{ __("New automation") }}</div>

				<div class="au-presets">
					<button
						v-for="p in presets"
						:key="p.key"
						class="au-preset"
						:class="{ selected: form.preset === p.key }"
						@click="form.preset = p.key"
					>
						<span class="au-preset-ic"
							><component :is="p.icon" :size="18" :stroke-width="1.6"
						/></span>
						<span class="au-preset-text">
							<strong>{{ p.title }}</strong>
							<small>{{ p.description }}</small>
						</span>
					</button>
				</div>

				<div class="au-form">
					<label class="au-field">
						<span>{{ __("How often") }}</span>
						<select v-model="form.cadence">
							<option value="hourly">{{ __("Every hour") }}</option>
							<option value="daily">{{ __("Every day") }}</option>
							<option value="weekdays">{{ __("Weekdays only") }}</option>
						</select>
					</label>
					<label class="au-field" v-if="form.cadence !== 'hourly'">
						<span>{{ __("At") }}</span>
						<input type="time" v-model="form.time" />
					</label>
					<label class="au-field">
						<span>{{ __("Report to") }}</span>
						<select v-model="form.channel">
							<option value="raven">{{ __("Nora chat (desk)") }}</option>
							<option value="whatsapp">{{ __("WhatsApp") }}</option>
							<option value="email">{{ __("Email") }}</option>
						</select>
					</label>
					<label class="au-field" v-if="form.channel === 'email'">
						<span>{{ __("Email address") }}</span>
						<input
							type="email"
							v-model="form.target"
							:placeholder="__('you@company.ch')"
						/>
					</label>
				</div>

				<p class="au-hint">{{ selectedPreset.hint }}</p>

				<div class="au-form-actions">
					<button class="au-create" @click="create" :disabled="creating">
						<Loader2 v-if="creating" :size="14" class="spin" />
						<Plus v-else :size="14" />
						<span>{{ __("Create automation") }}</span>
					</button>
				</div>
			</section>
		</div>
	</div>
</template>

<script>
import {
	Bot,
	X,
	RefreshCw,
	Play,
	PlayCircle,
	Pause,
	Trash2,
	Plus,
	Loader2,
	FileText,
	Inbox,
} from "lucide-vue-next";

// Mailbox automations = NORA scheduled tasks (nora.api.v2.briefings) whose config
// points at this Webmail Account. Two deterministic task types exist server-side:
//   invoice_scan  — every new PDF attachment goes through the OCR pipeline and is
//                   filed as a Document Scan (accounting-ready)
//   email_digest  — a plain list of the new mail (sender, time, subject)
// This panel only creates / lists / runs those; the scheduler (nora tick) does the
// work under the mailbox owner's identity.
const MAILBOX_TASK_TYPES = ["invoice_scan", "email_digest"];

export default {
	name: "AutomationsPanel",
	components: {
		Bot,
		X,
		RefreshCw,
		Play,
		PlayCircle,
		Pause,
		Trash2,
		Plus,
		Loader2,
		FileText,
		Inbox,
	},

	props: {
		account: { type: String, required: true },
		accountEmail: { type: String, default: "" },
	},

	emits: ["close"],

	data() {
		return {
			loading: false,
			creating: false,
			all: [],
			busy: {},
			results: {},
			form: {
				preset: "invoice_scan",
				cadence: "hourly",
				time: "08:00",
				channel: "raven",
				target: "",
			},
		};
	},

	computed: {
		presets() {
			return [
				{
					key: "invoice_scan",
					icon: FileText,
					title: __("Invoices → Document Scan"),
					description: __(
						"Every new PDF attachment is read by the OCR and filed in Document Scan."
					),
					hint: __(
						"Nora reads the new emails of this mailbox, sends each PDF attachment through the OCR pipeline and files it as a Document Scan, ready for accounting. Emails already processed are remembered (they are never re-imported)."
					),
					title_fn: (email) => __("Invoices from {0}", [email]),
				},
				{
					key: "email_digest",
					icon: Inbox,
					title: __("New mail summary"),
					description: __("A short list of the new emails: sender, time, subject."),
					hint: __(
						"Nora lists the emails received since the previous run — sender, time and subject — and sends it to the channel you choose. Nothing is moved or marked as read in your mailbox."
					),
					title_fn: (email) => __("New mail in {0}", [email]),
				},
			];
		},
		selectedPreset() {
			return this.presets.find((p) => p.key === this.form.preset) || this.presets[0];
		},
		items() {
			return this.all.filter(
				(b) =>
					MAILBOX_TASK_TYPES.includes(b.task_type) &&
					this.configAccount(b) === this.account
			);
		},
	},

	watch: {
		account: {
			immediate: true,
			handler() {
				this.load();
			},
		},
	},

	methods: {
		configAccount(b) {
			try {
				const cfg = typeof b.config === "string" ? JSON.parse(b.config) : b.config;
				return (cfg && cfg.account) || "";
			} catch (e) {
				return "";
			}
		},

		kindIcon(b) {
			return b.task_type === "invoice_scan" ? FileText : Inbox;
		},

		cadenceLabel(b) {
			const days = (b.schedule_days || "daily").toLowerCase();
			if (days === "hourly") return __("Every hour");
			const at = b.schedule_time ? String(b.schedule_time).slice(0, 5) : "";
			if (days === "weekdays") return __("Weekdays at {0}", [at]);
			if (days === "weekly_monday") return __("Mondays at {0}", [at]);
			if (days === "monthly_first") return __("1st of the month at {0}", [at]);
			return __("Every day at {0}", [at]);
		},

		lastRunLabel(b) {
			if (!b.last_run_at) return __("Never run yet");
			const when = frappe.datetime.prettyDate
				? frappe.datetime.prettyDate(b.last_run_at)
				: b.last_run_at;
			if (b.last_success_at && b.last_success_at === b.last_run_at) {
				return __("Last run {0}", [when]);
			}
			if (b.consecutive_failures) {
				return __("Last run {0} — {1} failure(s)", [when, b.consecutive_failures]);
			}
			return __("Last run {0}", [when]);
		},

		async load() {
			if (!this.account) return;
			this.loading = true;
			try {
				const r = await frappe.call({ method: "nora.api.v2.briefings.list_mine" });
				this.all = (r.message && r.message.briefings) || [];
			} catch (e) {
				frappe.toast({ message: __("Could not load the automations"), indicator: "red" });
			} finally {
				this.loading = false;
			}
		},

		async create() {
			if (this.creating) return;
			if (this.form.channel === "email" && !/@/.test(this.form.target || "")) {
				frappe.toast({
					message: __("Enter the email address to report to"),
					indicator: "orange",
				});
				return;
			}
			this.creating = true;
			try {
				const preset = this.selectedPreset;
				await frappe.call({
					method: "nora.api.v2.briefings.schedule",
					args: {
						briefing_title: preset.title_fn(this.accountEmail || this.account),
						prompt: "",
						time_hh_mm:
							this.form.cadence === "hourly" ? "00:00" : this.form.time || "08:00",
						days: this.form.cadence,
						channel: this.form.channel,
						delivery_target: this.form.channel === "email" ? this.form.target : null,
						task_type: preset.key,
						config: JSON.stringify({ account: this.account }),
						send_confirmation: 0,
					},
				});
				frappe.toast({ message: __("Automation created"), indicator: "green" });
				await this.load();
			} catch (e) {
				frappe.toast({
					message: (e && e.message) || __("Could not create the automation"),
					indicator: "red",
				});
			} finally {
				this.creating = false;
			}
		},

		async runNow(b) {
			this.busy = { ...this.busy, [b.id]: true };
			this.results = { ...this.results, [b.id]: null };
			try {
				const r = await frappe.call({
					method: "nora.api.v2.briefings.test_run",
					args: { briefing_id: b.id },
					freeze: false,
				});
				const res = r.message || {};
				const text = res.ok
					? __("Done — {0}", [res.text || res.response || __("delivered")])
					: __("Failed: {0}", [res.error || res.reason || __("see the Nora logs")]);
				this.results = { ...this.results, [b.id]: { ok: !!res.ok, text } };
				await this.load();
			} catch (e) {
				this.results = {
					...this.results,
					[b.id]: { ok: false, text: (e && e.message) || __("Run failed") },
				};
			} finally {
				this.busy = { ...this.busy, [b.id]: false };
			}
		},

		async togglePause(b) {
			this.busy = { ...this.busy, [b.id]: true };
			try {
				await frappe.call({
					method: b.enabled
						? "nora.api.v2.briefings.pause"
						: "nora.api.v2.briefings.resume",
					args: { briefing_id: b.id },
				});
				await this.load();
			} catch (e) {
				frappe.toast({ message: __("Could not update the automation"), indicator: "red" });
			} finally {
				this.busy = { ...this.busy, [b.id]: false };
			}
		},

		remove(b) {
			frappe.confirm(__("Delete the automation « {0} »?", [b.briefing_title]), async () => {
				this.busy = { ...this.busy, [b.id]: true };
				try {
					await frappe.call({
						method: "nora.api.v2.briefings.delete",
						args: { briefing_id: b.id },
					});
					await this.load();
				} catch (e) {
					frappe.toast({
						message: __("Could not delete the automation"),
						indicator: "red",
					});
				} finally {
					this.busy = { ...this.busy, [b.id]: false };
				}
			});
		},
	},
};
</script>

<style scoped>
.automations {
	display: flex;
	flex-direction: column;
	max-height: 86vh;
	min-height: 0;
}

.au-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 16px 18px 12px;
	border-bottom: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
}

.au-title {
	display: flex;
	align-items: center;
	gap: 12px;
}

.au-title h3 {
	margin: 0;
	font-size: 15px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
}

.au-sub {
	margin: 2px 0 0;
	font-size: 12px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.au-mark {
	width: 32px;
	height: 32px;
	border-radius: 9px;
	display: grid;
	place-items: center;
	background: var(--wm-nora-soft, #faefe6);
	color: var(--wm-nora, #d68a59);
}

.au-close,
.au-refresh,
.au-act {
	border: 0;
	background: transparent;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	cursor: pointer;
	border-radius: 6px;
	display: grid;
	place-items: center;
	transition: background 0.15s, color 0.15s;
}

.au-close {
	width: 30px;
	height: 30px;
}

.au-close:hover,
.au-refresh:hover,
.au-act:hover {
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f5f5f5));
	color: var(--wm-ink, var(--text-color, #333));
}

.au-act.danger:hover {
	color: var(--wm-danger, #dc2626);
}

.au-body {
	overflow-y: auto;
	padding: 6px 18px 18px;
	display: flex;
	flex-direction: column;
	gap: 18px;
}

.au-section-title {
	display: flex;
	align-items: center;
	gap: 8px;
	margin: 12px 0 8px;
	font-size: 10.5px;
	font-weight: 600;
	letter-spacing: 0.08em;
	text-transform: uppercase;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.au-refresh {
	width: 22px;
	height: 22px;
	margin-left: auto;
}

.au-empty {
	font-size: 12.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	padding: 10px 12px;
	border: 1px dashed var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 8px;
}

.au-item {
	display: grid;
	grid-template-columns: 30px 1fr auto auto;
	gap: 10px;
	align-items: center;
	padding: 10px 12px;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 10px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	margin-bottom: 8px;
}

.au-item.paused {
	opacity: 0.7;
}

.au-item-ic {
	width: 30px;
	height: 30px;
	border-radius: 8px;
	display: grid;
	place-items: center;
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f5f5f5));
	color: var(--wm-ink-soft, var(--text-color, #333));
}

.au-item-title {
	font-size: 13px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
}

.au-item-meta {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	display: flex;
	gap: 6px;
	flex-wrap: wrap;
}

.au-result {
	margin-top: 6px;
	font-size: 12px;
	white-space: pre-wrap;
	padding: 6px 8px;
	border-radius: 6px;
	background: var(--wm-danger-soft, #fee2e2);
	color: var(--wm-ink, var(--text-color, #333));
}

.au-result.ok {
	background: var(--wm-sage-soft, #d1fae5);
}

.pill {
	font-size: 11px;
	font-weight: 600;
	padding: 2px 8px;
	border-radius: 999px;
	white-space: nowrap;
}

.pill-on {
	background: var(--wm-sage-soft, #d1fae5);
	color: var(--wm-sage, #047857);
}

.pill-off {
	background: var(--wm-amber-soft, #fef3c7);
	color: var(--wm-amber, #b45309);
}

.au-item-actions {
	display: flex;
	gap: 2px;
}

.au-act {
	width: 28px;
	height: 28px;
}

.au-presets {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 8px;
}

.au-preset {
	display: flex;
	gap: 10px;
	align-items: flex-start;
	text-align: left;
	padding: 10px 12px;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 10px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	cursor: pointer;
	font-family: inherit;
	color: var(--wm-ink, var(--text-color, #333));
	transition: border-color 0.15s, background 0.15s;
}

.au-preset:hover {
	border-color: var(--wm-line-strong, var(--border-color, #ccc));
}

.au-preset.selected {
	border-color: var(--wm-accent, #d68a59);
	background: var(--wm-accent-tint, #fdf6f0);
}

.au-preset-ic {
	width: 32px;
	height: 32px;
	border-radius: 8px;
	display: grid;
	place-items: center;
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f5f5f5));
	color: var(--wm-ink-soft, var(--text-color, #333));
	flex-shrink: 0;
}

.au-preset.selected .au-preset-ic {
	background: var(--wm-accent-soft, #faefe6);
	color: var(--wm-accent, #d68a59);
}

.au-preset-text {
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.au-preset-text strong {
	font-size: 12.5px;
	font-weight: 600;
}

.au-preset-text small {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	line-height: 1.35;
}

.au-form {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	gap: 10px;
	margin-top: 12px;
}

.au-field {
	display: flex;
	flex-direction: column;
	gap: 4px;
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.au-field select,
.au-field input {
	height: 32px;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 7px;
	padding: 0 10px;
	font-size: 12.5px;
	font-family: inherit;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	color: var(--wm-ink, var(--text-color, #333));
}

.au-hint {
	margin: 10px 0 0;
	font-size: 12px;
	line-height: 1.45;
	color: var(--wm-ink-soft, var(--text-color, #555));
}

.au-form-actions {
	display: flex;
	justify-content: flex-end;
	margin-top: 12px;
}

.au-create {
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
	cursor: pointer;
	font-family: inherit;
}

.au-create:disabled {
	opacity: 0.6;
	cursor: wait;
}

.spin {
	animation: au-spin 0.9s linear infinite;
}

@keyframes au-spin {
	to {
		transform: rotate(360deg);
	}
}
</style>
