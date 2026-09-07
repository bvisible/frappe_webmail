<template>
	<div class="nora-bar" v-if="editor">
		<div class="nora-bar-left">
			<span class="nora-label">
				<Sparkles :size="14" />
				<span>Nora</span>
			</span>
		</div>
		<div class="nora-bar-actions">
			<button
				class="nora-btn"
				@click="$emit('proofread')"
				:disabled="loading || !hasContent"
				:title="__('Proofread')"
			>
				<CheckCheck :size="14" />
				<span>{{ __("Proofread") }}</span>
			</button>
			<button
				class="nora-btn"
				@click="$emit('improve')"
				:disabled="loading || !hasContent"
				:title="__('Improve')"
			>
				<Wand2 :size="14" />
				<span>{{ __("Improve") }}</span>
			</button>
			<div class="nora-dropdown" ref="translateDropdown">
				<button
					class="nora-btn"
					@click="toggleTranslateMenu"
					:disabled="loading || !hasContent"
					:title="__('Translate')"
				>
					<Languages :size="14" />
					<span>{{ __("Translate") }}</span>
					<ChevronDown :size="12" />
				</button>
				<div class="nora-dropdown-menu" v-if="showTranslateMenu">
					<button @click="handleTranslate('fr')">{{ __("French") }}</button>
					<button @click="handleTranslate('en')">{{ __("English") }}</button>
					<button @click="handleTranslate('de')">{{ __("German") }}</button>
				</div>
			</div>
			<button
				class="nora-btn"
				@click="$emit('learn-style')"
				:disabled="loading"
				:title="__('Learn my writing style from my sent emails')"
			>
				<Signature :size="14" />
				<span>{{ __("My style") }}</span>
			</button>
			<span class="nora-separator"></span>
			<button
				class="nora-btn nora-btn-chat"
				@click="$emit('open-chat')"
				:disabled="loading"
				:title="__('Chat with Nora')"
			>
				<MessageSquare :size="14" />
				<span>{{ __("Chat") }}</span>
			</button>
		</div>
		<div class="nora-bar-status" v-if="loading">
			<div class="nora-spinner"></div>
			<span>{{ loadingText || __("Processing...") }}</span>
		</div>
	</div>
</template>

<script>
import {
	Sparkles,
	CheckCheck,
	Wand2,
	Languages,
	ChevronDown,
	MessageSquare,
	Signature,
} from "lucide-vue-next";

export default {
	name: "NoraBar",
	components: {
		Sparkles,
		CheckCheck,
		Wand2,
		Languages,
		ChevronDown,
		MessageSquare,
		Signature,
	},

	props: {
		editor: { type: Object, default: null },
		loading: { type: Boolean, default: false },
		loadingText: { type: String, default: "" },
	},

	emits: ["proofread", "improve", "translate", "learn-style", "open-chat"],

	data() {
		return {
			showTranslateMenu: false,
		};
	},

	computed: {
		hasContent() {
			if (!this.editor) return false;
			const text = this.editor.getText();
			return text && text.trim().length > 0;
		},
	},

	methods: {
		toggleTranslateMenu() {
			this.showTranslateMenu = !this.showTranslateMenu;
		},

		handleTranslate(lang) {
			this.showTranslateMenu = false;
			this.$emit("translate", lang);
		},

		handleClickOutside(event) {
			const dropdown = this.$refs.translateDropdown;
			if (dropdown && !dropdown.contains(event.target)) {
				this.showTranslateMenu = false;
			}
		},
	},

	mounted() {
		document.addEventListener("click", this.handleClickOutside);
	},

	beforeUnmount() {
		document.removeEventListener("click", this.handleClickOutside);
	},
};
</script>

<style scoped>
.nora-bar {
	display: flex;
	align-items: center;
	padding: 6px 16px;
	background: var(--bg-light-gray, #f8f9fa);
	border-top: 1px solid var(--border-color, #e5e5e5);
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	gap: 12px;
	min-height: 40px;
}

.nora-bar-left {
	flex-shrink: 0;
}

.nora-label {
	display: flex;
	align-items: center;
	gap: 4px;
	font-size: 12px;
	font-weight: 600;
	color: var(--primary-color, #2490ef);
	text-transform: uppercase;
	letter-spacing: 0.5px;
}

.nora-bar-actions {
	display: flex;
	align-items: center;
	gap: 4px;
}

.nora-btn {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 4px 10px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	background: var(--card-bg, white);
	cursor: pointer;
	font-size: 12px;
	color: var(--text-color, #333);
	white-space: nowrap;
	transition: all 0.15s ease;
}

.nora-btn:hover:not(:disabled) {
	background: var(--bg-gray, #eee);
	border-color: var(--primary-color, #2490ef);
	color: var(--primary-color, #2490ef);
}

.nora-btn:disabled {
	opacity: 0.4;
	cursor: not-allowed;
}

.nora-btn-chat {
	border-color: var(--primary-color, #2490ef);
	color: var(--primary-color, #2490ef);
}

.nora-separator {
	width: 1px;
	height: 20px;
	background: var(--border-color, #e5e5e5);
	margin: 0 4px;
}

.nora-dropdown {
	position: relative;
}

.nora-dropdown-menu {
	position: absolute;
	top: 100%;
	left: 0;
	margin-top: 4px;
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
	z-index: 100;
	min-width: 120px;
	overflow: hidden;
}

.nora-dropdown-menu button {
	display: block;
	width: 100%;
	padding: 8px 14px;
	border: none;
	background: transparent;
	cursor: pointer;
	font-size: 13px;
	text-align: left;
	color: var(--text-color, #333);
}

.nora-dropdown-menu button:hover {
	background: var(--bg-light-gray, #f5f5f5);
	color: var(--primary-color, #2490ef);
}

.nora-bar-status {
	display: flex;
	align-items: center;
	gap: 6px;
	margin-left: auto;
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
}

.nora-spinner {
	width: 14px;
	height: 14px;
	border: 2px solid var(--border-color, #e5e5e5);
	border-top: 2px solid var(--primary-color, #2490ef);
	border-radius: 50%;
	animation: nora-spin 0.8s linear infinite;
}

@keyframes nora-spin {
	to {
		transform: rotate(360deg);
	}
}
</style>
