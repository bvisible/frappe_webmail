<template>
	<div class="nora-mini-chat">
		<div class="chat-header">
			<span class="chat-title">
				<Sparkles :size="14" />
				{{ __("Chat with Nora") }}
			</span>
			<button class="btn-close-chat" @click="$emit('close')" :title="__('Close')">
				<X :size="16" />
			</button>
		</div>

		<div class="chat-messages" ref="messagesContainer">
			<div v-if="messages.length === 0" class="chat-empty">
				<MessageSquare :size="24" />
				<p>{{ __("Describe the email you want to write...") }}</p>
			</div>
			<div v-for="(msg, idx) in messages" :key="idx" class="chat-message" :class="msg.role">
				<div class="message-content">{{ msg.content }}</div>
			</div>
			<div v-if="loading" class="chat-message assistant">
				<div class="message-content">
					<div class="typing-indicator"><span></span><span></span><span></span></div>
				</div>
			</div>
		</div>

		<div class="chat-input-area">
			<div class="chat-input-row">
				<textarea
					ref="chatInput"
					v-model="inputText"
					:placeholder="__('Describe the email...')"
					@keydown.enter.exact.prevent="sendMessage"
					rows="2"
					:disabled="loading"
				></textarea>
				<button
					class="btn-send-chat"
					@click="sendMessage"
					:disabled="!inputText.trim() || loading"
					:title="__('Send')"
				>
					<SendHorizonal :size="16" />
				</button>
			</div>
			<button
				v-if="lastDraftHtml"
				class="btn-insert"
				@click="$emit('insert-content', lastDraftHtml)"
				:title="__('Insert into email editor')"
			>
				<ArrowDownToLine :size="14" />
				{{ __("Insert in editor") }}
			</button>
		</div>
	</div>
</template>

<script>
import { Sparkles, X, MessageSquare, SendHorizonal, ArrowDownToLine } from "lucide-vue-next";

export default {
	name: "NoraMiniChat",
	components: { Sparkles, X, MessageSquare, SendHorizonal, ArrowDownToLine },

	props: {
		account: { type: String, required: true },
		replyContext: { type: String, default: "" },
	},

	emits: ["close", "insert-content"],

	data() {
		return {
			inputText: "",
			messages: [],
			loading: false,
			lastDraftHtml: "",
		};
	},

	methods: {
		async sendMessage() {
			const text = this.inputText.trim();
			if (!text || this.loading) return;

			this.messages.push({ role: "user", content: text });
			this.inputText = "";
			this.loading = true;
			this.scrollToBottom();

			try {
				const result = await frappe.call({
					method: "nora.api.nora_webmail.generate_email",
					args: {
						prompt: text,
						account_name: this.account,
						conversation_history: JSON.stringify(this.messages),
						reply_context: this.replyContext || "",
					},
				});

				const data = result.message || result;

				if (data.success) {
					const assistantMsg = data.conversation_entry || {
						role: "assistant",
						content: data.draft_text || "",
					};
					this.messages.push(assistantMsg);
					this.lastDraftHtml = data.draft_html || "";
				} else {
					this.messages.push({
						role: "assistant",
						content: __("Sorry, I encountered an error. Please try again."),
					});
				}
			} catch (error) {
				console.error("Nora chat error:", error);
				this.messages.push({
					role: "assistant",
					content: __("Connection error. Please try again."),
				});
			} finally {
				this.loading = false;
				this.scrollToBottom();
			}
		},

		scrollToBottom() {
			this.$nextTick(() => {
				const container = this.$refs.messagesContainer;
				if (container) {
					container.scrollTop = container.scrollHeight;
				}
			});
		},
	},

	mounted() {
		this.$nextTick(() => {
			if (this.$refs.chatInput) {
				this.$refs.chatInput.focus();
			}
		});
	},
};
</script>

<style scoped>
.nora-mini-chat {
	border: 1px solid var(--primary-color, #2490ef);
	border-radius: 8px;
	margin: 8px 16px;
	background: var(--card-bg, white);
	display: flex;
	flex-direction: column;
	max-height: 400px;
	overflow: hidden;
}

.chat-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 8px 12px;
	background: var(--bg-light-gray, #f8f9fa);
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.chat-title {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
	font-weight: 600;
	color: var(--primary-color, #2490ef);
}

.btn-close-chat {
	padding: 2px;
	border: none;
	background: transparent;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
	border-radius: 4px;
}

.btn-close-chat:hover {
	background: var(--bg-gray, #eee);
	color: var(--text-color, #333);
}

.chat-messages {
	flex: 1;
	overflow-y: auto;
	padding: 12px;
	min-height: 120px;
	max-height: 250px;
}

.chat-empty {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	height: 100%;
	color: var(--text-muted, #8d99a6);
	gap: 8px;
}

.chat-empty p {
	font-size: 13px;
	margin: 0;
}

.chat-message {
	margin-bottom: 8px;
}

.chat-message.user .message-content {
	background: var(--primary-color, #2490ef);
	color: white;
	margin-left: 40px;
	border-radius: 12px 12px 4px 12px;
}

.chat-message.assistant .message-content {
	background: var(--bg-light-gray, #f0f0f0);
	color: var(--text-color, #333);
	margin-right: 40px;
	border-radius: 12px 12px 12px 4px;
}

.message-content {
	padding: 8px 12px;
	font-size: 13px;
	line-height: 1.5;
	white-space: pre-wrap;
	word-wrap: break-word;
}

.typing-indicator {
	display: flex;
	gap: 4px;
	padding: 4px 0;
}

.typing-indicator span {
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: var(--text-muted, #8d99a6);
	animation: typing-bounce 1.2s ease-in-out infinite;
}

.typing-indicator span:nth-child(2) {
	animation-delay: 0.2s;
}
.typing-indicator span:nth-child(3) {
	animation-delay: 0.4s;
}

@keyframes typing-bounce {
	0%,
	60%,
	100% {
		transform: translateY(0);
	}
	30% {
		transform: translateY(-4px);
	}
}

.chat-input-area {
	padding: 8px 12px;
	border-top: 1px solid var(--border-color, #e5e5e5);
	background: var(--bg-light-gray, #f8f9fa);
}

.chat-input-row {
	display: flex;
	gap: 8px;
	align-items: flex-end;
}

.chat-input-row textarea {
	flex: 1;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 8px;
	padding: 8px 12px;
	font-size: 13px;
	resize: none;
	outline: none;
	font-family: inherit;
	background: var(--card-bg, white);
}

.chat-input-row textarea:focus {
	border-color: var(--primary-color, #2490ef);
}

.btn-send-chat {
	padding: 8px;
	border: none;
	background: var(--primary-color, #2490ef);
	color: white;
	border-radius: 8px;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: background 0.15s ease;
}

.btn-send-chat:hover:not(:disabled) {
	background: var(--primary-dark, #1a7fd4);
}

.btn-send-chat:disabled {
	opacity: 0.4;
	cursor: not-allowed;
}

.btn-insert {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 6px;
	width: 100%;
	margin-top: 8px;
	padding: 6px 12px;
	border: 1px dashed var(--primary-color, #2490ef);
	border-radius: 6px;
	background: transparent;
	color: var(--primary-color, #2490ef);
	cursor: pointer;
	font-size: 12px;
	font-weight: 500;
	transition: all 0.15s ease;
}

.btn-insert:hover {
	background: var(--primary-color, #2490ef);
	color: white;
	border-style: solid;
}
</style>
