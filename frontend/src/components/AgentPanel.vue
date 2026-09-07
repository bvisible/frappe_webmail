<template>
	<div class="agent">
		<div class="ag-head">
			<span class="ag-mark"><Sparkles :size="15" :stroke-width="1.7" /></span>
			<div class="ag-title">
				<h3>Nora</h3>
				<p class="ag-sub">{{ accountEmail || account }}</p>
			</div>
			<button
				class="ag-icon"
				@click="newConversation"
				:disabled="busy"
				:data-tip="__('New conversation')"
				:aria-label="__('New conversation')"
			>
				<RotateCcw :size="14" />
			</button>
			<button
				class="ag-icon"
				@click="$emit('close')"
				:data-tip="__('Close')"
				:aria-label="__('Close')"
			>
				<X :size="15" />
			</button>
		</div>

		<!-- Two scopes, never mixed: the open message, or the mailbox as a whole -->
		<div class="ag-tabs" role="tablist">
			<button
				class="ag-tab"
				role="tab"
				:class="{ active: scope === 'message' }"
				:disabled="!selectedEmail"
				:data-tip="selectedEmail ? null : __('Open a message first')"
				@click="switchScope('message')"
			>
				<Mail :size="13" :stroke-width="1.7" />
				<span>{{ __("This message") }}</span>
			</button>
			<button
				class="ag-tab"
				role="tab"
				:class="{ active: scope === 'mailbox' }"
				@click="switchScope('mailbox')"
			>
				<Inbox :size="13" :stroke-width="1.7" />
				<span>{{ __("The mailbox") }}</span>
			</button>
		</div>

		<div class="ag-context" v-if="scope === 'message' && selectedEmail">
			<span class="ag-ctx-text">{{ selectedEmail.subject || __("(No subject)") }}</span>
			<span class="ag-ctx-from" v-if="selectedEmail.from_name || selectedEmail.from_email">
				— {{ selectedEmail.from_name || selectedEmail.from_email }}
			</span>
		</div>

		<div class="ag-messages" ref="scroller">
			<div v-if="!messages.length && !busy && !cards.length" class="ag-empty">
				<p v-if="scope === 'message'">
					{{
						__(
							"Ask Nora about this message: summarise it, decide what to answer, draft the reply. Nothing is sent without your approval."
						)
					}}
				</p>
				<p v-else>
					{{
						__(
							"Ask Nora about this mailbox: invoices to process, recurring jobs, searches. Nothing is sent without your approval."
						)
					}}
				</p>
			</div>

			<div v-for="(m, i) in messages" :key="i" class="ag-msg" :class="m.role">
				<div v-if="m.role === 'user'" class="ag-bubble">{{ m.content }}</div>
				<div v-else-if="m.role === 'status'" class="ag-status">{{ m.content }}</div>

				<!-- Text Nora rewrote for the draft being written: back into the editor on a click -->
				<div v-else-if="m.role === 'draft'" class="ag-block" :class="{ done: m.applied }">
					<div class="ag-block-head">
						<Wand2 :size="13" :stroke-width="1.7" />
						<span>{{ m.label }}</span>
						<span v-if="m.applied" class="ag-pill executed">{{ __("Applied") }}</span>
					</div>
					<div class="ag-block-body" v-html="sanitize(m.preview || m.html)"></div>
					<details v-if="m.original" class="ag-original">
						<summary>{{ __("Original") }}</summary>
						<div class="ag-block-body muted">{{ m.original }}</div>
					</details>
					<div class="ag-card-actions" v-if="!m.applied">
						<button class="ag-btn primary" @click="applyDraft(m)">
							<Check :size="13" />
							<span>{{ __("Replace in the editor") }}</span>
						</button>
						<button class="ag-btn" @click="dismiss(m)">{{ __("Ignore") }}</button>
					</div>
				</div>

				<!-- A recurring job the panel is about to create — nothing exists before "Create" -->
				<div v-else-if="m.role === 'automation'" class="ag-block" :class="m.state">
					<div class="ag-block-head">
						<Bot :size="13" :stroke-width="1.7" />
						<span>{{ m.preview.kind_label }}</span>
						<span v-if="m.state === 'created'" class="ag-pill executed">{{
							__("Created")
						}}</span>
						<span v-else-if="m.state === 'cancelled'" class="ag-pill rejected">{{
							__("Cancelled")
						}}</span>
					</div>
					<div class="ag-kv">
						<span>{{ __("Mailbox") }}</span
						><strong>{{ m.preview.mailbox || account }}</strong>
						<span>{{ __("Cadence") }}</span
						><strong>{{ m.preview.when_label }}</strong>
						<span>{{ __("Delivery") }}</span
						><strong>{{ __("Nora chat") }}</strong>
					</div>
					<div class="ag-card-actions" v-if="m.state === 'pending'">
						<button
							class="ag-btn primary"
							@click="createAutomation(m)"
							:disabled="m.busy"
						>
							<Loader2 v-if="m.busy" :size="13" class="spin" />
							<Check v-else :size="13" />
							<span>{{ __("Create") }}</span>
						</button>
						<button class="ag-btn" @click="cancelAutomation(m)" :disabled="m.busy">
							{{ __("Cancel") }}
						</button>
					</div>
				</div>

				<!-- The mailbox's recurring jobs, with their controls -->
				<div v-else-if="m.role === 'automations'" class="ag-block">
					<div class="ag-block-head">
						<Bot :size="13" :stroke-width="1.7" />
						<span>{{ __("Automations on this mailbox") }}</span>
					</div>
					<p v-if="!m.rows.length" class="ag-muted">{{ __("None yet.") }}</p>
					<div
						v-for="row in m.rows"
						:key="row.id"
						class="ag-row"
						:class="{ off: !row.enabled }"
					>
						<div class="ag-row-main">
							<strong>{{ kindLabel(row.task_type) }}</strong>
							<span class="ag-muted">
								{{ cadenceLabel(row.schedule_days, row.schedule_time) }}
								· {{ row.enabled ? __("active") : __("paused") }}
							</span>
						</div>
						<div class="ag-row-actions">
							<button
								class="ag-btn"
								@click="toggleAutomation(m, row)"
								:disabled="m.busy"
								:data-tip="row.enabled ? __('Pause') : __('Resume')"
							>
								<Pause v-if="row.enabled" :size="13" />
								<Play v-else :size="13" />
							</button>
							<button
								class="ag-btn danger"
								@click="deleteAutomation(m, row)"
								:disabled="m.busy"
								:data-tip="__('Delete')"
							>
								<Trash2 :size="13" />
							</button>
						</div>
					</div>
				</div>

				<div v-else class="ag-bubble md">
					<div v-html="renderMarkdown(m.content)"></div>
					<button
						v-if="m.retry"
						class="ag-btn ag-retry"
						@click="send(m.retry)"
						:disabled="busy"
					>
						<RotateCcw :size="12" />
						<span>{{ __("Retry") }}</span>
					</button>
				</div>
			</div>

			<!-- Nora's proposals (NORA Action Card): approve here, nothing leaves before -->
			<div
				v-for="c in cards"
				:key="c.token"
				class="ag-card"
				:class="String(c.status || '').toLowerCase()"
			>
				<div class="ag-card-head">
					<FileText v-if="c.kind === 'Dunning'" :size="14" :stroke-width="1.7" />
					<Mail v-else :size="14" :stroke-width="1.7" />
					<span class="ag-card-title">{{ c.title }}</span>
					<span class="ag-pill" :class="String(c.status || '').toLowerCase()">
						{{ statusLabel(c.status) }}
					</span>
				</div>

				<template v-if="editing[c.token]">
					<label class="ag-field">
						<span>{{ __("To") }}</span>
						<input type="email" v-model="editing[c.token].recipient" />
					</label>
					<label class="ag-field">
						<span>{{ __("Subject") }}</span>
						<input type="text" v-model="editing[c.token].subject" />
					</label>
					<label class="ag-field">
						<span>{{ __("Message") }}</span>
						<textarea rows="6" v-model="editing[c.token].body"></textarea>
					</label>
					<div class="ag-card-actions">
						<button
							class="ag-btn primary"
							@click="saveEdit(c)"
							:disabled="cardBusy[c.token]"
						>
							<Check :size="13" />
							<span>{{ __("Save changes") }}</span>
						</button>
						<button
							class="ag-btn"
							@click="cancelEdit(c)"
							:disabled="cardBusy[c.token]"
						>
							{{ __("Cancel") }}
						</button>
					</div>
				</template>
				<template v-else>
					<div class="ag-card-meta" v-if="c.payload && c.payload.recipient">
						<span>{{ __("To") }} : {{ c.payload.recipient }}</span>
						<span v-if="c.payload.subject">· {{ c.payload.subject }}</span>
					</div>
					<div
						class="ag-block-body"
						v-if="c.payload && c.payload.body_html"
						v-html="sanitize(c.payload.body_html)"
					></div>
					<div class="ag-card-actions" v-if="c.status === 'Pending'">
						<button
							class="ag-btn primary"
							@click="respond(c, 'approve')"
							:disabled="cardBusy[c.token]"
						>
							<Loader2 v-if="cardBusy[c.token]" :size="13" class="spin" />
							<SendHorizonal v-else :size="13" />
							<span>{{ __("Send") }}</span>
						</button>
						<button class="ag-btn" @click="startEdit(c)" :disabled="cardBusy[c.token]">
							<Pencil :size="13" />
							<span>{{ __("Edit") }}</span>
						</button>
						<button
							class="ag-btn danger"
							@click="respond(c, 'reject')"
							:disabled="cardBusy[c.token]"
						>
							<Ban :size="13" />
							<span>{{ __("Reject") }}</span>
						</button>
					</div>
					<div class="ag-card-result" v-else-if="c.result">{{ c.result }}</div>
				</template>
			</div>

			<div v-if="busy" class="ag-msg assistant">
				<div class="ag-bubble ag-thinking">
					<span class="dot"></span><span class="dot"></span><span class="dot"></span>
					{{ busyLabel || __("Nora is working…") }}
				</div>
			</div>
		</div>

		<!-- One-click asks, chosen from what is on screen (draft, open message, mailbox) -->
		<div class="ag-quick" v-if="!busy">
			<span v-if="composerOpen" class="ag-quick-label">{{ __("Your draft") }}</span>
			<button v-for="s in suggestions" :key="s.text" class="ag-chip" @click="send(s.text)">
				{{ s.text }}
			</button>
		</div>

		<div class="ag-input">
			<textarea
				ref="input"
				v-model="draft"
				rows="2"
				:placeholder="
					scope === 'message'
						? __('Ask Nora about this message…')
						: __('Ask Nora about this mailbox…')
				"
				:disabled="busy"
				@keydown.enter.exact.prevent="send()"
			></textarea>
			<button
				class="ag-send"
				@click="send()"
				:disabled="!draft.trim() || busy"
				:data-tip="__('Send')"
				:aria-label="__('Send')"
			>
				<SendHorizonal :size="15" />
			</button>
		</div>
	</div>
</template>

<script>
import DOMPurify from "dompurify";
import {
	Sparkles,
	X,
	RotateCcw,
	Mail,
	Inbox,
	FileText,
	SendHorizonal,
	Check,
	Pencil,
	Ban,
	Loader2,
	Wand2,
	Bot,
	Pause,
	Play,
	Trash2,
} from "lucide-vue-next";
import { classifyIntent } from "../agentIntents";
import { joinQuote } from "../quoteSplit";
import { CONTEXT_TAG, cleanEcho, friendlyAnswer } from "../agentText";

// Nora in the webmail, in two scopes that never mix: THIS MESSAGE (one thread
// per open e-mail) and the MAILBOX (invoices, recurring jobs, searches). The
// conversation is a Hermes thread on the same engine as the desk Quick Chat
// (nora.api.chat.*): replies arrive asynchronously and are polled; proposals
// come back as NORA Action Cards approved here. What can be answered without
// a language model is: reply / write / fix / translate (the webmail's own
// endpoints) and recurring jobs (the deterministic router's parser + the
// briefings API, with the user's rights) — the features people sell must not
// depend on the model being available.
const POLL_MS = 1500;
const POLL_TIMEOUT_MS = 180000;
const MAX_LOG = 40;
const MAILBOX_TASK_TYPES = ["invoice_scan", "email_digest"];

// Intermediate acknowledgements and gateway notices — the final answer comes later.
const DEFERRED = [
	/NO_REPLY/,
	/je reviens|d[èe]s que possible/i,
	/votre p[oô]le|je confie|je transmets|r[ée]ponse dans un instant|j'arrive/i,
	/sous-agent.*lanc[éè]/i,
	/I'm passing this to your|I'll be right back with you/i,
	/Ich leite Ihre Anfrage|ich melde mich gleich/i,
	/a pris trop de temps|je r[ée]essaie|retrying|nouvel essai/i,
	/Redirected current run|First-time tip|\/busy queue/i,
];
// A pole that gave up: offer "Retry" instead of a dead end
const FAILURE =
	/incident technique|n'ai pas pu traiter|did not answer|service busy|empty stream|API call failed|Provider returned/i;

export default {
	name: "AgentPanel",
	components: {
		Sparkles,
		X,
		RotateCcw,
		Mail,
		Inbox,
		FileText,
		SendHorizonal,
		Check,
		Pencil,
		Ban,
		Loader2,
		Wand2,
		Bot,
		Pause,
		Play,
		Trash2,
	},

	props: {
		account: { type: String, required: true },
		accountEmail: { type: String, default: "" },
		folder: { type: String, default: "INBOX" },
		// The email open in the reader (uid, subject, from_email, from_name, date)
		selectedEmail: { type: Object, default: null },
		// The composer, when open: `readComposer()` → {mode, to, subject, html, text, own, quote}
		composerOpen: { type: Boolean, default: false },
		readComposer: { type: Function, default: null },
	},

	emits: [
		"close",
		"apply-draft",
		"reply-with-draft",
		"compose-with-draft",
		"automations-changed",
	],

	data() {
		return {
			scope: this.selectedEmail ? "message" : "mailbox",
			threadId: null,
			messages: [],
			cards: [],
			draft: "",
			busy: false,
			busyLabel: "",
			editing: {},
			cardBusy: {},
			pollHandle: null,
		};
	},

	computed: {
		suggestions() {
			// Imperative forms on purpose: the same text goes through classifyIntent
			if (this.composerOpen) {
				return [
					{ text: __("Proofread my draft") },
					{ text: __("Improve the wording") },
					{ text: __("Translate my draft into English") },
				];
			}
			if (this.scope === "message" && this.selectedEmail) {
				return [
					{ text: __("Summarise this email") },
					{ text: __("Write a reply") },
					{ text: __("What should I reply?") },
				];
			}
			return [
				{ text: __("Any invoices to process in this mailbox?") },
				{ text: __("Which automations are active?") },
				{ text: __("Check this mailbox every hour for invoices") },
			];
		},
	},

	watch: {
		account() {
			this.reload();
		},
		selectedEmail(next, prev) {
			// Opening a message shows its own thread; closing the reader goes back to the mailbox
			if (next && (!prev || next.uid !== prev.uid)) {
				this.scope = "message";
				this.reload();
			} else if (!next && this.scope === "message") {
				this.scope = "mailbox";
				this.reload();
			}
		},
	},

	created() {
		this.reload();
	},

	beforeUnmount() {
		this.stopPolling();
	},

	methods: {
		// ── scopes & storage ─────────────────────────────────────────────────
		scopeKey() {
			return this.scope === "message" && this.selectedEmail
				? `${this.account}#${this.selectedEmail.uid}`
				: this.account;
		},

		storageKey(kind) {
			return `webmail_nora_${kind}:${this.scopeKey()}`;
		},

		switchScope(scope) {
			if (scope === this.scope || (scope === "message" && !this.selectedEmail)) return;
			this.scope = scope;
			this.reload();
		},

		reload() {
			this.stopPolling();
			this.busy = false;
			this.busyLabel = "";
			this.cards = [];
			this.restore();
			this.refreshCards();
		},

		restore() {
			try {
				this.threadId = localStorage.getItem(this.storageKey("thread")) || null;
				const raw = localStorage.getItem(this.storageKey("log"));
				this.messages = raw ? JSON.parse(raw) : [];
			} catch (e) {
				this.threadId = null;
				this.messages = [];
			}
			this.scrollDown();
			this.resumePending();
		},

		persist() {
			try {
				if (this.threadId) localStorage.setItem(this.storageKey("thread"), this.threadId);
				localStorage.setItem(
					this.storageKey("log"),
					JSON.stringify(this.messages.slice(-MAX_LOG))
				);
			} catch (e) {
				/* storage unavailable — the conversation just won't survive a reload */
			}
		},

		newConversation() {
			this.stopPolling();
			this.threadId = null;
			this.messages = [];
			this.cards = [];
			this.writePending(null);
			try {
				localStorage.removeItem(this.storageKey("thread"));
				localStorage.removeItem(this.storageKey("log"));
			} catch (e) {
				/* ignore */
			}
		},

		// A reply still in flight when this panel is re-created (reload, account or scope
		// switch) is picked up again instead of being lost.
		readPending() {
			try {
				const raw = localStorage.getItem(this.storageKey("pending"));
				return raw ? JSON.parse(raw) : null;
			} catch (e) {
				return null;
			}
		},

		writePending(value) {
			try {
				if (value) localStorage.setItem(this.storageKey("pending"), JSON.stringify(value));
				else localStorage.removeItem(this.storageKey("pending"));
			} catch (e) {
				/* ignore */
			}
		},

		resumePending() {
			const pending = this.readPending();
			if (!pending || !this.threadId) return;
			if (Date.now() - (pending.startedAt || 0) > POLL_TIMEOUT_MS) {
				this.writePending(null);
				return;
			}
			this.busy = true;
			this.waitForReply(
				Array.isArray(pending.baseline) ? pending.baseline : [],
				pending.startedAt,
				Array.isArray(pending.shownAcks) ? pending.shownAcks : [],
				pending.ask || ""
			).finally(() => {
				this.busy = false;
			});
		},

		push(role, content, extra) {
			this.messages.push({ role, content, ts: Date.now(), ...(extra || {}) });
			this.persist();
			this.scrollDown();
		},

		dismiss(m) {
			this.messages = this.messages.filter((x) => x !== m);
			this.persist();
		},

		scrollDown() {
			this.$nextTick(() => {
				const el = this.$refs.scroller;
				if (el) el.scrollTop = el.scrollHeight;
			});
		},

		// ── what Nora receives ───────────────────────────────────────────────
		captureContext() {
			const e = this.scope === "message" ? this.selectedEmail : null;
			const ctx = {
				route: "webmail",
				doctype: "Webmail Account",
				name: this.account,
				title: e ? e.subject || this.accountEmail : this.accountEmail || this.account,
				channel: "chat",
				webmail: {
					account: this.account,
					account_email: this.accountEmail,
					folder: this.folder,
				},
			};
			if (e) {
				ctx.webmail.email = {
					uid: e.uid,
					subject: e.subject,
					from_email: e.from_email,
					from_name: e.from_name,
					date: e.date,
				};
			}
			return ctx;
		},

		// Agent-facing block appended to every outgoing message (the user never sees it):
		// which mailbox, which message is open, the exact calls — a specialist pole never
		// reads the page context, so the facts travel with the text.
		agentContextSuffix() {
			const e = this.scope === "message" ? this.selectedEmail : null;
			const lines = [
				`mailbox account: "${this.account}"` +
					(this.accountEmail && this.accountEmail !== this.account
						? ` (${this.accountEmail})`
						: ""),
				`folder: "${this.folder}"`,
			];
			if (e) {
				const from = [e.from_name, e.from_email ? `<${e.from_email}>` : ""]
					.filter(Boolean)
					.join(" ");
				lines.push(
					`open email: UID ${e.uid}, subject "${e.subject || ""}"` +
						(from ? `, from ${from}` : "") +
						(e.date ? `, date ${e.date}` : ""),
					`"this email" / "ce mail" means that one — read it with ` +
						`get_inbox_email(uid="${e.uid}", account="${this.account}", folder="${this.folder}")`
				);
			} else {
				lines.push(
					`the user talks about the mailbox as a whole — use list_inbox_emails / search_inbox_emails with account="${this.account}"`
				);
			}
			if (this.threadId) {
				lines.push(
					`conversation_id: "${this.threadId}" — pass it to every tool that accepts it`
				);
			}
			if (window.frappe && frappe.session && frappe.session.user) {
				lines.push(`requester user: "${frappe.session.user}"`);
			}
			const composer = this.composerOpen && this.readComposer ? this.readComposer() : null;
			if (composer) {
				lines.push(
					`the user is writing an email (${composer.mode}) to "${composer.to}", subject "${composer.subject}"; ` +
						`draft so far: ${JSON.stringify((composer.text || "").slice(0, 400))}`
				);
			}
			return (
				`\n\n${CONTEXT_TAG}\nnever quote this block; when you delegate, title the task with the user's request only\n` +
				lines.join("\n")
			);
		},

		extractContent(msg) {
			let raw = msg.content || msg.text || msg.body || "";
			if (Array.isArray(raw)) {
				raw = raw
					.map((p) => (p && (p.content || p.text) ? p.content || p.text : ""))
					.filter(Boolean)
					.join("\n");
			}
			return typeof raw === "string" ? raw : "";
		},

		messageKey(m) {
			return String(this.extractContent(m) || "").slice(0, 300);
		},

		cleanEcho(text) {
			return cleanEcho(text);
		},

		friendlyAnswer(text) {
			return friendlyAnswer(
				text,
				__("Nora's model did not answer (service busy). Please try again in a moment.")
			);
		},

		looksDeferred(text) {
			return DEFERRED.some((re) => re.test(text || ""));
		},

		async fetchThread() {
			if (!this.threadId) return { messages: [], cards: [] };
			const r = await frappe.call({
				method: "nora.api.chat.get_messages",
				args: { thread_id: this.threadId },
			});
			return r.message || { messages: [], cards: [] };
		},

		async refreshCards() {
			if (!this.threadId) return;
			try {
				const data = await this.fetchThread();
				this.cards = (data.cards || []).filter(
					(c) => c.kind === "Email" || c.kind === "Dunning"
				);
			} catch (e) {
				/* cards are additive — never break the panel over them */
			}
		},

		// ── sending ──────────────────────────────────────────────────────────
		async send(preset) {
			const text = (preset != null ? preset : this.draft).trim();
			if (!text || this.busy) return;
			this.draft = "";
			this.push("user", text);
			this.busy = true;

			try {
				// Reply / write / fix / translate / recurring jobs: answered here, in
				// seconds, with the user's rights — no orchestrator round trip.
				const intent = classifyIntent(text, {
					composerOpen: this.composerOpen,
					emailOpen: !!this.selectedEmail,
				});
				if (intent && (await this.runLocalIntent(intent, text))) return;

				// What the thread already holds — by CONTENT, not by count: the replies
				// buffer is not append-only (a pole's answer lives in the per-user buffer,
				// the next run writes the thread's), so counting missed real answers.
				let baseline = [];
				if (this.threadId) {
					try {
						baseline = ((await this.fetchThread()).messages || []).map((m) =>
							this.messageKey(m)
						);
					} catch (e) {
						baseline = [];
					}
				}
				const args = {
					message: text + this.agentContextSuffix(),
					context: JSON.stringify(this.captureContext()),
					block: 0,
				};
				if (this.threadId) args.thread_id = this.threadId;
				const r = await frappe.call({
					method: this.threadId
						? "nora.api.chat.post_message"
						: "nora.api.chat.start_or_resume_thread",
					args,
				});
				const data = r.message || {};
				if (data.thread_id) this.threadId = data.thread_id;
				this.persist();
				const startedAt = Date.now();
				this.writePending({ baseline, startedAt, shownAcks: [], ask: text });
				await this.waitForReply(baseline, startedAt, [], text);
			} catch (e) {
				this.writePending(null);
				this.push("assistant", __("Nora could not be reached. Please try again."), {
					retry: text,
				});
			} finally {
				this.busy = false;
				this.busyLabel = "";
				this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
			}
		},

		waitForReply(baseline, startedAt = Date.now(), acksShown = [], ask = "") {
			return new Promise((resolve) => {
				const seen = new Set(baseline || []);
				const shown = new Set(acksShown || []);
				const finish = () => {
					this.writePending(null);
					resolve();
				};
				const tick = async () => {
					if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
						this.push(
							"assistant",
							__("Nora did not answer in time. Try again in a moment."),
							{
								retry: ask || undefined,
							}
						);
						return finish();
					}
					try {
						const data = await this.fetchThread();
						const list = data.messages || [];
						this.cards = (data.cards || []).filter(
							(c) => c.kind === "Email" || c.kind === "Dunning"
						);
						const fresh = list.filter(
							(m) =>
								(m.role === "assistant" || m.author === "assistant") &&
								this.extractContent(m) &&
								!seen.has(this.messageKey(m))
						);
						const final = [...fresh]
							.reverse()
							.find((m) => !this.looksDeferred(this.extractContent(m)));
						if (final) {
							const text = this.friendlyAnswer(
								this.cleanEcho(this.extractContent(final))
							);
							this.push(
								"assistant",
								text,
								FAILURE.test(text) ? { retry: ask || undefined } : undefined
							);
							return finish();
						}
						// Routing acknowledgements ("je transmets à votre pôle…") show once, as
						// status lines, while we keep waiting for the real answer.
						const acks = fresh.filter((m) => !shown.has(this.messageKey(m)));
						if (acks.length) {
							acks.forEach((m) => {
								shown.add(this.messageKey(m));
								this.push("status", this.extractContent(m));
							});
							this.writePending({ baseline, startedAt, shownAcks: [...shown], ask });
						}
					} catch (e) {
						/* transient — keep polling */
					}
					this.pollHandle = setTimeout(tick, POLL_MS);
				};
				tick();
			});
		},

		stopPolling() {
			if (this.pollHandle) {
				clearTimeout(this.pollHandle);
				this.pollHandle = null;
			}
		},

		// ── local actions (no language model round trip) ─────────────────────
		// Returns true when the request was handled here.
		async runLocalIntent(intent, text) {
			const composer = this.composerOpen && this.readComposer ? this.readComposer() : null;
			try {
				if (intent.kind === "reply") {
					if (!this.selectedEmail) {
						this.push(
							"assistant",
							__(
								"Open the message you want to answer first — I will draft the reply from it."
							)
						);
						return true;
					}
					this.busyLabel = __("Nora is drafting the reply… (about 10 s)");
					const r = await frappe.call({
						method: "nora.api.nora_webmail.quick_reply",
						args: {
							account_name: this.account,
							email_uid: this.selectedEmail.uid,
							folder: this.folder,
						},
					});
					const data = r.message || {};
					if (!data.success) throw new Error("quick_reply");
					this.$emit("reply-with-draft", {
						original_email: this.selectedEmail,
						draft_html: data.draft_html,
					});
					this.push(
						"assistant",
						__(
							"I opened the reply in the editor with a draft — read it, adjust it, then send."
						)
					);
					return true;
				}
				if (intent.kind === "compose") {
					this.busyLabel = __("Nora is writing… (about 10 s)");
					const r = await frappe.call({
						method: "nora.api.nora_webmail.generate_email",
						args: { prompt: text, account_name: this.account },
					});
					const data = r.message || {};
					if (!data.success) throw new Error("generate_email");
					this.$emit("compose-with-draft", { html: data.draft_html });
					this.push(
						"assistant",
						__(
							"Draft inserted in a new message — add the recipient and the subject, then send."
						)
					);
					return true;
				}
				if (intent.kind === "schedule") {
					return await this.proposeAutomation(text);
				}
				if (intent.kind === "list_automations") {
					await this.listAutomations();
					return true;
				}
				// proofread / improve / translate act on the draft being written
				if (!composer || !(composer.text || "").trim()) {
					this.push(
						"assistant",
						__(
							"Open the editor first (New message or Reply) and write your draft — I will work on the text you have there."
						)
					);
					return true;
				}
				// Only what the user wrote goes to Nora; the quoted original stays as it is
				const own = composer.own != null ? composer.own : composer.html;
				let method;
				let args;
				let label;
				let pick;
				if (intent.kind === "translate") {
					method = "nora.api.nora_webmail.translate";
					args = {
						html_content: own,
						target_language: intent.lang,
						account_name: this.account,
					};
					label = __("Translation");
					pick = (d) => d.translated_html || this.textToHtml(d.translated_text);
				} else if (intent.kind === "proofread") {
					method = "nora.api.nora_webmail.proofread";
					args = { html_content: own, account_name: this.account };
					label = __("Corrected draft");
					pick = (d) => d.corrected_html || this.textToHtml(d.corrected_text);
				} else {
					method = "nora.api.nora_webmail.improve";
					args = { html_content: own, account_name: this.account };
					label = __("Improved draft");
					pick = (d) => d.improved_html || this.textToHtml(d.improved_text);
				}
				this.busyLabel = __("Nora is working on your draft…");
				const r = await frappe.call({ method, args });
				const data = r.message || {};
				if (
					intent.kind === "translate" &&
					data.source_language &&
					data.source_language === data.target_language
				) {
					this.push("assistant", __("The draft is already in that language."));
					return true;
				}
				const html = pick(data);
				if (!html) throw new Error("empty");
				this.pushDraft({
					label,
					html: joinQuote(html, composer.quote || ""),
					preview: html,
					original: data.original_text || "",
				});
				return true;
			} catch (e) {
				this.push("assistant", __("That did not work — please try again."), {
					retry: text,
				});
				return true;
			}
		},

		// Also called by the composer's own Nora bar (through the page): one place for results
		// `html` is what goes back into the editor (rewritten part + untouched quote);
		// `preview` is what the block shows — the rewritten part alone.
		pushDraft({ label, html, original, preview }) {
			this.push("draft", "", {
				label,
				html,
				preview: preview || "",
				original: original || "",
				applied: false,
			});
		},

		applyDraft(m) {
			this.$emit("apply-draft", { html: m.html });
			m.applied = true;
			this.persist();
		},

		// ── recurring jobs, in code ──────────────────────────────────────────
		async proposeAutomation(text) {
			const r = await frappe.call({
				method: "nora.api.v2.task_router.preview_recurrent",
				args: { message: text, account: this.account },
			});
			const preview = r.message || {};
			if (!preview.ok || !preview.recognized) return false; // let Nora handle the question
			this.push("automation", "", { preview, state: "pending", busy: false });
			return true;
		},

		async createAutomation(m) {
			const p = m.preview;
			m.busy = true;
			try {
				const mailboxKind = MAILBOX_TASK_TYPES.includes(p.kind);
				const r = await frappe.call({
					method: "nora.api.v2.briefings.schedule",
					args: {
						briefing_title: p.title,
						prompt: mailboxKind ? "" : p.instruction || p.title,
						time_hh_mm: p.time_hh_mm,
						days: p.days,
						channel: "raven",
						task_type: mailboxKind ? p.kind : "briefing",
						config: mailboxKind
							? JSON.stringify({ account: p.mailbox || this.account })
							: null,
						send_confirmation: 0,
					},
				});
				const data = r.message || {};
				m.state = "created";
				m.id = data.briefing_id || data.id || null;
				this.persist();
				this.push(
					"assistant",
					__(
						"Done — {0}, {1}. You will find it under Automations, where you can pause or delete it.",
						[p.kind_label, (p.when_label || "").toLowerCase()]
					)
				);
				this.$emit("automations-changed");
			} catch (e) {
				this.push(
					"assistant",
					__("The automation could not be created — see the message above.")
				);
			} finally {
				m.busy = false;
				this.persist();
			}
		},

		cancelAutomation(m) {
			m.state = "cancelled";
			this.persist();
		},

		async fetchAutomations() {
			const r = await frappe.call({ method: "nora.api.v2.briefings.list_mine" });
			const rows = ((r.message || {}).briefings || []).filter((b) => {
				if (!MAILBOX_TASK_TYPES.includes(b.task_type)) return false;
				let cfg = {};
				try {
					cfg =
						typeof b.config === "string"
							? JSON.parse(b.config || "{}")
							: b.config || {};
				} catch (e) {
					cfg = {};
				}
				return !cfg.account || cfg.account === this.account;
			});
			return rows.map((b) => ({
				id: b.id,
				task_type: b.task_type,
				schedule_days: b.schedule_days,
				schedule_time: b.schedule_time,
				enabled: !!b.enabled,
				title: b.briefing_title,
			}));
		},

		async listAutomations() {
			const rows = await this.fetchAutomations();
			this.push("automations", "", { rows, busy: false });
		},

		async toggleAutomation(m, row) {
			m.busy = true;
			try {
				await frappe.call({
					method: row.enabled
						? "nora.api.v2.briefings.pause"
						: "nora.api.v2.briefings.resume",
					args: { briefing_id: row.id },
				});
				m.rows = await this.fetchAutomations();
				this.$emit("automations-changed");
			} catch (e) {
				frappe.toast({
					message: __("That did not work — please try again."),
					indicator: "red",
				});
			} finally {
				m.busy = false;
				this.persist();
			}
		},

		async deleteAutomation(m, row) {
			m.busy = true;
			try {
				await frappe.call({
					method: "nora.api.v2.briefings.delete",
					args: { briefing_id: row.id },
				});
				m.rows = await this.fetchAutomations();
				this.$emit("automations-changed");
			} catch (e) {
				frappe.toast({
					message: __("That did not work — please try again."),
					indicator: "red",
				});
			} finally {
				m.busy = false;
				this.persist();
			}
		},

		kindLabel(taskType) {
			return (
				{
					invoice_scan: __("Invoices → Document Scan"),
					email_digest: __("New mail summary"),
				}[taskType] || taskType
			);
		},

		cadenceLabel(days, time) {
			const map = {
				hourly: __("Every hour"),
				daily: __("Every day at {0}", [time]),
				weekdays: __("Weekdays at {0}", [time]),
				weekly_monday: __("Every Monday at {0}", [time]),
				monthly_first: __("1st of the month at {0}", [time]),
			};
			return map[days] || `${days} ${time || ""}`.trim();
		},

		// ── cards ──────────────────────────────────────────────────────────
		statusLabel(status) {
			const map = {
				Pending: __("To approve"),
				Approved: __("Approved"),
				Executed: __("Sent"),
				Rejected: __("Rejected"),
				Failed: __("Failed"),
				Expired: __("Expired"),
			};
			return map[status] || status;
		},

		htmlToText(html) {
			const div = document.createElement("div");
			div.innerHTML = this.sanitize(html || "");
			return (div.innerText || div.textContent || "").trim();
		},

		textToHtml(text) {
			return (text || "")
				.split(/\n{2,}/)
				.map((p) => `<p>${this.escapeHtml(p).replace(/\n/g, "<br>")}</p>`)
				.join("");
		},

		escapeHtml(s) {
			return String(s || "")
				.replace(/&/g, "&amp;")
				.replace(/</g, "&lt;")
				.replace(/>/g, "&gt;")
				.replace(/"/g, "&quot;");
		},

		startEdit(card) {
			const p = card.payload || {};
			this.editing = {
				...this.editing,
				[card.token]: {
					recipient: p.recipient || "",
					subject: p.subject || "",
					body: this.htmlToText(p.body_html),
				},
			};
		},

		cancelEdit(card) {
			const next = { ...this.editing };
			delete next[card.token];
			this.editing = next;
		},

		async saveEdit(card) {
			const e = this.editing[card.token];
			if (!e) return;
			await this.respond(card, "edit", {
				recipient: e.recipient,
				subject: e.subject,
				body_html: this.textToHtml(e.body),
			});
			this.cancelEdit(card);
		},

		async respond(card, action, edits) {
			this.cardBusy = { ...this.cardBusy, [card.token]: true };
			try {
				await frappe.call({
					method: "nora.api.cards.respond",
					args: {
						token: card.token,
						action,
						edits: edits ? JSON.stringify(edits) : null,
					},
				});
				await this.refreshCards();
				if (action === "approve")
					frappe.toast({ message: __("Sent by Nora"), indicator: "green" });
			} catch (err) {
				frappe.toast({
					message: (err && err.message) || __("Nora could not apply this action"),
					indicator: "red",
				});
			} finally {
				this.cardBusy = { ...this.cardBusy, [card.token]: false };
			}
		},

		// ── rendering ──────────────────────────────────────────────────────
		sanitize(html) {
			return DOMPurify.sanitize(html || "", {
				ALLOWED_TAGS: [
					"p",
					"br",
					"b",
					"strong",
					"i",
					"em",
					"u",
					"ul",
					"ol",
					"li",
					"a",
					"code",
					"pre",
					"blockquote",
					"h1",
					"h2",
					"h3",
					"h4",
					"table",
					"thead",
					"tbody",
					"tr",
					"th",
					"td",
					"span",
					"div",
				],
				ALLOWED_ATTR: ["href", "target", "rel"],
			});
		},

		renderMarkdown(text) {
			let html;
			if (window.frappe && typeof frappe.markdown === "function") {
				html = frappe.markdown(text || "");
			} else {
				html = this.textToHtml(text);
			}
			return this.sanitize(html);
		},
	},
};
</script>

<style scoped>
.agent {
	display: flex;
	flex-direction: column;
	height: 100%;
	min-height: 0;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
}

.ag-head {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 10px 12px 6px;
}

.ag-mark {
	width: 28px;
	height: 28px;
	border-radius: 8px;
	display: grid;
	place-items: center;
	background: var(--wm-nora-soft, #faefe6);
	color: var(--wm-nora, #d68a59);
	flex-shrink: 0;
}

.ag-title {
	flex: 1;
	min-width: 0;
}

.ag-title h3 {
	margin: 0;
	font-size: 13.5px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
}

.ag-sub {
	margin: 0;
	font-size: 11px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.ag-icon {
	width: 28px;
	height: 28px;
	border: 0;
	background: transparent;
	border-radius: 6px;
	display: grid;
	place-items: center;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	cursor: pointer;
	flex-shrink: 0;
}

.ag-icon:hover {
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f5f5f5));
	color: var(--wm-ink, var(--text-color, #333));
}

/* Tabs: the scope is always visible */
.ag-tabs {
	display: flex;
	gap: 4px;
	padding: 0 12px;
	border-bottom: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
}

.ag-tab {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 8px 10px;
	border: 0;
	border-bottom: 2px solid transparent;
	margin-bottom: -1px;
	background: transparent;
	font-size: 12.5px;
	font-family: inherit;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	cursor: pointer;
}

.ag-tab.active {
	color: var(--wm-ink, var(--text-color, #333));
	border-bottom-color: var(--wm-accent, #d68a59);
	font-weight: 600;
}

.ag-tab:disabled {
	opacity: 0.45;
	cursor: not-allowed;
}

.ag-context {
	display: flex;
	align-items: baseline;
	gap: 4px;
	padding: 7px 12px;
	font-size: 11.5px;
	color: var(--wm-ink-soft, var(--text-color, #555));
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f8f8f8));
	border-bottom: 1px solid var(--wm-line-soft, var(--border-color, #eee));
	white-space: nowrap;
	overflow: hidden;
}

.ag-ctx-text {
	font-weight: 600;
	overflow: hidden;
	text-overflow: ellipsis;
}

.ag-ctx-from {
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	flex-shrink: 0;
}

.ag-messages {
	flex: 1;
	overflow-y: auto;
	padding: 12px;
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.ag-empty {
	font-size: 12.5px;
	color: var(--wm-ink-soft, var(--text-color, #555));
	line-height: 1.45;
	padding: 6px 2px;
}

.ag-msg {
	display: flex;
}

.ag-msg.user {
	justify-content: flex-end;
}

.ag-bubble {
	max-width: 92%;
	padding: 8px 11px;
	border-radius: 12px;
	font-size: 13px;
	line-height: 1.45;
	white-space: pre-wrap;
	word-break: break-word;
}

.ag-msg.user .ag-bubble {
	background: var(--wm-accent, #d68a59);
	color: #fff;
	border-bottom-right-radius: 4px;
}

.ag-msg.assistant .ag-bubble {
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f5f5f5));
	color: var(--wm-ink, var(--text-color, #333));
	border-bottom-left-radius: 4px;
	white-space: normal;
}

.ag-bubble.md :deep(p) {
	margin: 0 0 6px;
}

.ag-bubble.md :deep(p:last-child) {
	margin-bottom: 0;
}

.ag-bubble.md :deep(ul),
.ag-bubble.md :deep(ol) {
	margin: 4px 0;
	padding-left: 18px;
}

.ag-bubble.md :deep(code) {
	background: rgba(0, 0, 0, 0.06);
	padding: 1px 4px;
	border-radius: 4px;
	font-size: 12px;
}

.ag-retry {
	margin-top: 8px;
}

.ag-status {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	font-style: italic;
	padding: 0 4px;
}

.ag-thinking {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	font-size: 12px;
}

.ag-thinking .dot {
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: var(--wm-nora, #d68a59);
	animation: ag-blink 1.2s infinite ease-in-out;
}

.ag-thinking .dot:nth-child(2) {
	animation-delay: 0.2s;
}

.ag-thinking .dot:nth-child(3) {
	animation-delay: 0.4s;
}

@keyframes ag-blink {
	0%,
	80%,
	100% {
		opacity: 0.25;
	}
	40% {
		opacity: 1;
	}
}

/* Blocks: a rewritten draft, a job to create, the jobs list, a proposal card */
.ag-block,
.ag-card {
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-left: 3px solid var(--wm-accent, #d68a59);
	border-radius: 10px;
	padding: 10px 12px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	display: flex;
	flex-direction: column;
	gap: 8px;
	width: 100%;
}

.ag-card {
	border-left-color: var(--wm-amber, #b45309);
}

.ag-block.done,
.ag-block.created,
.ag-card.executed {
	border-left-color: var(--wm-sage, #047857);
}

.ag-block.cancelled,
.ag-card.rejected,
.ag-card.failed,
.ag-card.expired {
	border-left-color: var(--wm-line-strong, #ccc);
	opacity: 0.75;
}

.ag-block-head,
.ag-card-head {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 12.5px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
}

.ag-block-head .ag-pill {
	margin-left: auto;
}

.ag-card-title {
	flex: 1;
	min-width: 0;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.ag-pill {
	font-size: 10.5px;
	font-weight: 600;
	padding: 1px 7px;
	border-radius: 999px;
	background: var(--wm-amber-soft, #fef3c7);
	color: var(--wm-amber, #b45309);
	white-space: nowrap;
}

.ag-pill.executed {
	background: var(--wm-sage-soft, #d1fae5);
	color: var(--wm-sage, #047857);
}

.ag-pill.rejected,
.ag-pill.failed,
.ag-pill.expired {
	background: var(--wm-bg-sunken, #f5f5f5);
	color: var(--wm-ink-mute, #8d99a6);
}

.ag-block-body {
	font-size: 12.5px;
	line-height: 1.45;
	color: var(--wm-ink, var(--text-color, #333));
	max-height: 260px;
	overflow-y: auto;
}

.ag-block-body.muted {
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	white-space: pre-wrap;
	max-height: 160px;
}

.ag-block-body :deep(p) {
	margin: 0 0 6px;
}

.ag-original summary {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	cursor: pointer;
}

.ag-kv {
	display: grid;
	grid-template-columns: auto 1fr;
	gap: 3px 10px;
	font-size: 12px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.ag-kv strong {
	color: var(--wm-ink, var(--text-color, #333));
	font-weight: 500;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.ag-muted {
	font-size: 12px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	margin: 0;
}

.ag-row {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 6px 0;
	border-top: 1px solid var(--wm-line-soft, var(--border-color, #eee));
	font-size: 12.5px;
}

.ag-row.off .ag-row-main {
	opacity: 0.6;
}

.ag-row-main {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.ag-row-actions {
	display: flex;
	gap: 4px;
}

.ag-card-meta {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	display: flex;
	gap: 6px;
	flex-wrap: wrap;
}

.ag-card-result {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.ag-card-actions {
	display: flex;
	gap: 6px;
	flex-wrap: wrap;
}

.ag-btn {
	height: 28px;
	padding: 0 10px;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 7px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	color: var(--wm-ink, var(--text-color, #333));
	font-size: 12px;
	display: inline-flex;
	align-items: center;
	gap: 5px;
	cursor: pointer;
	font-family: inherit;
}

.ag-btn.primary {
	background: var(--color-primary, #141414);
	color: var(--color-primary-fg, #fffdf8);
	border-color: transparent;
}

.ag-btn.danger:hover {
	color: var(--wm-danger, #dc2626);
	border-color: var(--wm-danger, #dc2626);
}

.ag-btn:disabled {
	opacity: 0.55;
	cursor: wait;
}

.ag-field {
	display: flex;
	flex-direction: column;
	gap: 3px;
	font-size: 11px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.ag-field input,
.ag-field textarea {
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 6px;
	padding: 6px 8px;
	font-size: 12.5px;
	font-family: inherit;
	color: var(--wm-ink, var(--text-color, #333));
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	resize: vertical;
}

.ag-quick {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: 6px;
	padding: 8px 12px 0;
}

.ag-quick-label {
	font-size: 11px;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
}

.ag-chip {
	padding: 5px 9px;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 999px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	color: var(--wm-ink, var(--text-color, #333));
	font-size: 12px;
	cursor: pointer;
	font-family: inherit;
	transition: border-color 0.15s, background 0.15s;
}

.ag-chip:hover:not(:disabled) {
	border-color: var(--wm-accent, #d68a59);
	background: var(--wm-accent-tint, #fdf6f0);
}

.ag-input {
	display: flex;
	gap: 6px;
	align-items: flex-end;
	padding: 10px 12px;
	border-top: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	margin-top: 8px;
}

.ag-input textarea {
	flex: 1;
	resize: none;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 9px;
	padding: 8px 10px;
	font-size: 13px;
	font-family: inherit;
	color: var(--wm-ink, var(--text-color, #333));
	background: var(--wm-bg-raised, var(--card-bg, #fff));
}

.ag-input textarea:focus {
	outline: none;
	border-color: var(--wm-accent, #d68a59);
}

.ag-send {
	width: 34px;
	height: 34px;
	border: 0;
	border-radius: 9px;
	background: var(--color-primary, #141414);
	color: var(--color-primary-fg, #fffdf8);
	display: grid;
	place-items: center;
	cursor: pointer;
	flex-shrink: 0;
}

.ag-send:disabled {
	opacity: 0.45;
	cursor: not-allowed;
}

.spin {
	animation: ag-spin 0.9s linear infinite;
}

@keyframes ag-spin {
	to {
		transform: rotate(360deg);
	}
}
</style>
