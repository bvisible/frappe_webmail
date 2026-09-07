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

		<!-- What Nora sees: the open email (sent as page context with every message) -->
		<div class="ag-context" v-if="selectedEmail">
			<Mail :size="12" :stroke-width="1.7" />
			<span class="ag-ctx-text">{{ selectedEmail.subject || __("(No subject)") }}</span>
		</div>

		<div class="ag-messages" ref="scroller">
			<div v-if="!messages.length && !busy && !cards.length" class="ag-empty">
				<p>
					{{
						__(
							"Ask Nora about this mailbox. She reads the open email, searches the folder and drafts replies — nothing is sent without your approval."
						)
					}}
				</p>
			</div>

			<div v-for="(m, i) in messages" :key="i" class="ag-msg" :class="m.role">
				<div v-if="m.role === 'user'" class="ag-bubble">{{ m.content }}</div>
				<div v-else-if="m.role === 'status'" class="ag-status">{{ m.content }}</div>
				<!-- Text Nora rewrote for the draft being written: goes into the editor on a click -->
				<div
					v-else-if="m.role === 'draft'"
					class="ag-draft"
					:class="{ applied: m.applied }"
				>
					<div class="ag-draft-head">
						<Wand2 :size="13" :stroke-width="1.7" />
						<span>{{ m.label }}</span>
						<span v-if="m.applied" class="ag-pill executed">{{ __("Applied") }}</span>
					</div>
					<div class="ag-draft-body" v-html="sanitize(m.html)"></div>
					<div class="ag-card-actions" v-if="!m.applied">
						<button class="ag-btn primary" @click="applyDraft(m)">
							<Check :size="13" />
							<span>{{ __("Replace in the editor") }}</span>
						</button>
						<button class="ag-btn" @click="dismissDraft(m)">{{ __("Ignore") }}</button>
					</div>
				</div>
				<div v-else class="ag-bubble md" v-html="renderMarkdown(m.content)"></div>
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
						class="ag-card-body"
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
					{{ __("Nora is working…") }}
				</div>
			</div>
		</div>

		<!-- One-click asks, chosen from what is on screen (draft, open email, mailbox) -->
		<div class="ag-quick" v-if="!busy">
			<button v-for="s in suggestions" :key="s.text" class="ag-chip" @click="send(s.text)">
				{{ s.text }}
			</button>
		</div>

		<div class="ag-input">
			<textarea
				ref="input"
				v-model="draft"
				rows="2"
				:placeholder="__('Ask Nora…')"
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
	FileText,
	SendHorizonal,
	Check,
	Pencil,
	Ban,
	Loader2,
	Wand2,
} from "lucide-vue-next";
import { classifyIntent } from "../agentIntents";

// Mailbox-scoped Nora chat. Same engine as the desk Quick Chat
// (nora.api.chat.*): the conversation is a Hermes thread, replies arrive
// asynchronously and are polled; Nora's proposals (an email she wants to send)
// come back as NORA Action Cards and are approved HERE — nothing leaves the
// mailbox without a click. Every message carries the open email as page
// context, so "résume ce mail" needs no copy-paste.
const POLL_MS = 1500;
const POLL_TIMEOUT_MS = 180000;
const MAX_LOG = 40;

// Intermediate acknowledgements Nora emits while a specialist works — the
// final answer comes later. Anchors mirror the gateway's ACK templates.
const DEFERRED = [
	/NO_REPLY/,
	/je reviens|d[èe]s que possible/i,
	/votre p[oô]le|je confie|je transmets|r[ée]ponse dans un instant|j'arrive/i,
	/sous-agent.*lanc[éè]/i,
	// A pole that timed out and retries ("⏱ Support — la demande a pris trop de temps, je
	// réessaie.") is a status, not an answer — keep waiting.
	/a pris trop de temps|je r[ée]essaie|retrying|nouvel essai/i,
	// Hermes gateway notices when a message arrives during a run
	/Redirected current run|First-time tip|\/busy queue/i,
	/I'm passing this to your|I'll be right back with you/i,
	/Ich leite Ihre Anfrage|ich melde mich gleich/i,
];

export default {
	name: "AgentPanel",
	components: {
		Sparkles,
		X,
		RotateCcw,
		Mail,
		FileText,
		SendHorizonal,
		Check,
		Pencil,
		Ban,
		Loader2,
		Wand2,
	},

	props: {
		account: { type: String, required: true },
		accountEmail: { type: String, default: "" },
		folder: { type: String, default: "INBOX" },
		// The email open in the reader (uid, subject, from_email, from_name, date)
		selectedEmail: { type: Object, default: null },
		// The composer, when open: `readComposer()` returns {mode, to, subject, html, text}
		composerOpen: { type: Boolean, default: false },
		readComposer: { type: Function, default: null },
	},

	emits: ["close", "apply-draft", "reply-with-draft", "compose-with-draft"],

	data() {
		return {
			threadId: null,
			messages: [],
			cards: [],
			draft: "",
			busy: false,
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
			if (this.selectedEmail) {
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
		account: {
			immediate: true,
			handler() {
				this.stopPolling();
				this.busy = false;
				this.restore();
				this.refreshCards();
			},
		},
	},

	beforeUnmount() {
		this.stopPolling();
	},

	methods: {
		storageKey(kind) {
			return `webmail_nora_${kind}:${this.account}`;
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

		// A reply still in flight when this panel is re-created (account switch, page
		// reload, parent re-render) is picked up again instead of being lost: the
		// answer lands in the thread whatever happens to the component.
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
				Array.isArray(pending.shownAcks) ? pending.shownAcks : []
			).finally(() => {
				this.busy = false;
			});
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

		push(role, content) {
			this.messages.push({ role, content, ts: Date.now() });
			this.persist();
			this.scrollDown();
		},

		scrollDown() {
			this.$nextTick(() => {
				const el = this.$refs.scroller;
				if (el) el.scrollTop = el.scrollHeight;
			});
		},

		// What Nora receives with every message. `hint` is for the agent (English,
		// like her tool descriptions); the rest mirrors the desk Quick Chat shape.
		captureContext() {
			const e = this.selectedEmail;
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
				ctx.hint =
					`The user is reading email UID ${e.uid} in folder "${this.folder}" of mailbox ` +
					`"${this.account}". Read it with get_inbox_email(uid="${e.uid}", account="${this.account}", ` +
					`folder="${this.folder}") before answering questions about "this email".`;
			} else {
				ctx.hint =
					`The user is browsing folder "${this.folder}" of mailbox "${this.account}". ` +
					`Use list_inbox_emails / search_inbox_emails with account="${this.account}".`;
			}
			return ctx;
		},

		// Agent-facing block appended to every outgoing message (the user never sees it):
		// which mailbox, which folder, which email is open and the exact call to read it.
		// English, like the tool descriptions the agent already reads.
		agentContextSuffix() {
			const e = this.selectedEmail;
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
					`no email is open — use list_inbox_emails / search_inbox_emails with account="${this.account}"`
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
			lines.push(
				`recurring mailbox job → nora_schedule_task(mailbox="${this.account}", kind="invoice_scan" when invoices/PDFs ` +
					`must be processed, "email_digest" for a plain summary; days="hourly" for "toutes les heures"); ` +
					`existing jobs → nora_list_tasks; call the tool yourself, do not delegate`
			);
			const composer = this.composerOpen && this.readComposer ? this.readComposer() : null;
			if (composer) {
				lines.push(
					`the user is writing an email (${composer.mode}) to "${composer.to}", subject "${composer.subject}"; ` +
						`draft so far: ${JSON.stringify((composer.text || "").slice(0, 400))}`
				);
			}
			return (
				`\n\n[Webmail context for the assistant — not written by the user. Never quote it, and when you delegate, title the task with the user's request only]\n` +
				lines.join("\n")
			);
		},

		// ── local actions (reply / write / fix / translate) ─────────────────
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
						return;
					}
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
					return;
				}
				if (intent.kind === "compose") {
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
					return;
				}
				// proofread / improve / translate act on the draft being written
				if (!composer || !(composer.text || "").trim()) {
					this.push(
						"assistant",
						__(
							"Open the editor first (New message or Reply) and write your draft — I will work on the text you have there."
						)
					);
					return;
				}
				let method;
				let args;
				let label;
				let pick;
				if (intent.kind === "translate") {
					method = "nora.api.nora_webmail.translate";
					args = {
						html_content: composer.html,
						target_language: intent.lang,
						account_name: this.account,
					};
					label = __("Translation");
					pick = (d) => d.translated_html || this.textToHtml(d.translated_text);
				} else if (intent.kind === "proofread") {
					method = "nora.api.nora_webmail.proofread";
					args = { html_content: composer.html, account_name: this.account };
					label = __("Corrected draft");
					pick = (d) => d.corrected_html || this.textToHtml(d.corrected_text);
				} else {
					method = "nora.api.nora_webmail.improve";
					args = { html_content: composer.html, account_name: this.account };
					label = __("Improved draft");
					pick = (d) => d.improved_html || this.textToHtml(d.improved_text);
				}
				const r = await frappe.call({ method, args });
				const data = r.message || {};
				if (
					intent.kind === "translate" &&
					data.source_language &&
					data.source_language === data.target_language
				) {
					this.push("assistant", __("The draft is already in that language."));
					return;
				}
				const html = pick(data);
				if (!html) throw new Error("empty");
				this.pushDraft({ label, html });
			} catch (e) {
				this.push("assistant", __("That did not work — please try again."));
			}
		},

		pushDraft({ label, html }) {
			this.messages.push({ role: "draft", label, html, applied: false, ts: Date.now() });
			this.persist();
			this.scrollDown();
		},

		applyDraft(m) {
			this.$emit("apply-draft", { html: m.html });
			m.applied = true;
			this.persist();
		},

		dismissDraft(m) {
			this.messages = this.messages.filter((x) => x !== m);
			this.persist();
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

		// The orchestrator sometimes copies the whole message (our block included) into
		// the delegated task's title, which the pole echoes back — strip it from display.
		cleanEcho(text) {
			return String(text || "")
				.replace(/\[Webmail context for the assistant[^\]]*\]\s*/g, "")
				.replace(
					/(?:mailbox account|folder|conversation_id|requester user)\s*:\s*"?[\w@.\-]*"?\s*(?:\([^)]*\)\s*)?/g,
					""
				)
				.replace(/—\s*pass it to every tool that accepts it\s*/g, "")
				.trim();
		},

		// Raw provider failures relayed by the gateway are not something to show verbatim
		friendlyAnswer(text) {
			if (/API call failed|empty stream|no finish_reason|Provider returned/i.test(text)) {
				return __(
					"Nora's model did not answer (service busy). Please try again in a moment."
				);
			}
			return text;
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

		async send(preset) {
			const text = (preset != null ? preset : this.draft).trim();
			if (!text || this.busy) return;
			this.draft = "";
			this.push("user", text);
			this.busy = true;

			try {
				// Reply / write / fix-my-draft: answered in seconds by the webmail's own
				// endpoints, with the user's rights — no orchestrator round trip.
				const intent = classifyIntent(text, {
					composerOpen: this.composerOpen,
					emailOpen: !!this.selectedEmail,
				});
				if (intent) {
					await this.runLocalIntent(intent, text);
					return;
				}
				// Replies accumulate in one thread: only answers beyond this count are ours.
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
				this.writePending({ baseline, startedAt, shownAcks: [] });
				await this.waitForReply(baseline, startedAt, []);
			} catch (e) {
				this.writePending(null);
				this.push("assistant", __("Nora could not be reached. Please try again."));
			} finally {
				this.busy = false;
				this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
			}
		},

		// A stable key for one buffered message (content, truncated)
		messageKey(m) {
			return String(this.extractContent(m) || "").slice(0, 300);
		},

		waitForReply(baseline, startedAt = Date.now(), acksShown = []) {
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
							__("Nora did not answer in time. Try again in a moment.")
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
							this.push(
								"assistant",
								this.friendlyAnswer(this.cleanEcho(this.extractContent(final)))
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
							this.writePending({ baseline, startedAt, shownAcks: [...shown] });
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
				if (action === "approve") {
					frappe.toast({ message: __("Sent by Nora"), indicator: "green" });
				}
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
	padding: 10px 12px;
	border-bottom: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
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

.ag-context {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 6px 12px;
	font-size: 11.5px;
	color: var(--wm-ink-soft, var(--text-color, #555));
	background: var(--wm-bg-sunken, var(--bg-light-gray, #f8f8f8));
	border-bottom: 1px solid var(--wm-line-soft, var(--border-color, #eee));
}

.ag-ctx-text {
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
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

.ag-suggestions {
	display: flex;
	flex-direction: column;
	gap: 6px;
	margin-top: 10px;
}

.ag-chip {
	text-align: left;
	padding: 8px 10px;
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 8px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	color: var(--wm-ink, var(--text-color, #333));
	font-size: 12.5px;
	cursor: pointer;
	font-family: inherit;
	transition: border-color 0.15s, background 0.15s;
}

.ag-chip:hover:not(:disabled) {
	border-color: var(--wm-accent, #d68a59);
	background: var(--wm-accent-tint, #fdf6f0);
}

.ag-chip:disabled {
	opacity: 0.45;
	cursor: not-allowed;
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

/* Proposal card — Nora's draft, approved here */
.ag-card {
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-left: 3px solid var(--wm-amber, #b45309);
	border-radius: 10px;
	padding: 10px 12px;
	background: var(--wm-bg-raised, var(--card-bg, #fff));
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.ag-card.executed {
	border-left-color: var(--wm-sage, #047857);
}

.ag-card.rejected,
.ag-card.failed,
.ag-card.expired {
	border-left-color: var(--wm-line-strong, #ccc);
	opacity: 0.75;
}

.ag-card-head {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 12.5px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
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

.ag-card-meta {
	font-size: 11.5px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	display: flex;
	gap: 6px;
	flex-wrap: wrap;
}

.ag-card-body {
	font-size: 12.5px;
	line-height: 1.45;
	color: var(--wm-ink, var(--text-color, #333));
	max-height: 220px;
	overflow-y: auto;
}

.ag-card-body :deep(p) {
	margin: 0 0 6px;
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

.ag-input {
	display: flex;
	gap: 6px;
	align-items: flex-end;
	padding: 10px 12px;
	border-top: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
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

.ag-quick {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	padding: 8px 12px 0;
}

.ag-quick .ag-chip {
	padding: 5px 9px;
	font-size: 12px;
	border-radius: 999px;
}

.ag-draft {
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

.ag-draft.applied {
	opacity: 0.75;
}

.ag-draft-head {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 12.5px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
}

.ag-draft-head .ag-pill {
	margin-left: auto;
}

.ag-draft-body {
	font-size: 12.5px;
	line-height: 1.45;
	color: var(--wm-ink, var(--text-color, #333));
	max-height: 260px;
	overflow-y: auto;
}

.ag-draft-body :deep(p) {
	margin: 0 0 6px;
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
