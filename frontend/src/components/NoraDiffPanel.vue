<template>
	<div class="nora-diff-panel" v-if="visible">
		<div class="diff-header">
			<span class="diff-title">
				<Sparkles :size="14" />
				{{ title || __("Nora Suggestion") }}
			</span>
			<div class="diff-actions">
				<button class="btn-accept" @click="$emit('accept')" :title="__('Accept')">
					<Check :size="14" />
					<span>{{ __("Accept") }}</span>
				</button>
				<button class="btn-reject" @click="$emit('reject')" :title="__('Reject')">
					<X :size="14" />
					<span>{{ __("Reject") }}</span>
				</button>
			</div>
		</div>
		<div class="diff-content">
			<div class="diff-column">
				<div class="diff-column-header">{{ __("Original") }}</div>
				<div class="diff-text" v-html="originalHighlighted"></div>
			</div>
			<div class="diff-divider"></div>
			<div class="diff-column">
				<div class="diff-column-header">{{ __("Modified") }}</div>
				<div class="diff-text" v-html="modifiedHighlighted"></div>
			</div>
		</div>
	</div>
</template>

<script>
import { Sparkles, Check, X } from "lucide-vue-next";

export default {
	name: "NoraDiffPanel",
	components: { Sparkles, Check, X },

	props: {
		visible: { type: Boolean, default: false },
		originalText: { type: String, default: "" },
		modifiedText: { type: String, default: "" },
		title: { type: String, default: "" },
	},

	emits: ["accept", "reject"],

	computed: {
		originalHighlighted() {
			return this.computeDiff().original;
		},
		modifiedHighlighted() {
			return this.computeDiff().modified;
		},
	},

	methods: {
		computeDiff() {
			if (!this.originalText || !this.modifiedText) {
				return {
					original: this.escapeHtml(this.originalText || ""),
					modified: this.escapeHtml(this.modifiedText || ""),
				};
			}

			const origWords = this.tokenize(this.originalText);
			const modWords = this.tokenize(this.modifiedText);
			const lcs = this.longestCommonSubsequence(origWords, modWords);

			let originalHtml = "";
			let modifiedHtml = "";
			let oi = 0;
			let mi = 0;
			let li = 0;

			while (oi < origWords.length || mi < modWords.length) {
				if (
					li < lcs.length &&
					oi < origWords.length &&
					mi < modWords.length &&
					origWords[oi] === lcs[li] &&
					modWords[mi] === lcs[li]
				) {
					// Common word
					originalHtml += this.escapeHtml(origWords[oi]);
					modifiedHtml += this.escapeHtml(modWords[mi]);
					oi++;
					mi++;
					li++;
				} else if (li < lcs.length && oi < origWords.length && origWords[oi] !== lcs[li]) {
					// Deleted from original
					originalHtml += `<span class="diff-del">${this.escapeHtml(
						origWords[oi]
					)}</span>`;
					oi++;
				} else if (li < lcs.length && mi < modWords.length && modWords[mi] !== lcs[li]) {
					// Added in modified
					modifiedHtml += `<span class="diff-add">${this.escapeHtml(
						modWords[mi]
					)}</span>`;
					mi++;
				} else if (oi < origWords.length) {
					originalHtml += `<span class="diff-del">${this.escapeHtml(
						origWords[oi]
					)}</span>`;
					oi++;
				} else if (mi < modWords.length) {
					modifiedHtml += `<span class="diff-add">${this.escapeHtml(
						modWords[mi]
					)}</span>`;
					mi++;
				}
			}

			return {
				original: originalHtml.replace(/\n/g, "<br>"),
				modified: modifiedHtml.replace(/\n/g, "<br>"),
			};
		},

		tokenize(text) {
			// Split by whitespace but keep the whitespace as separate tokens
			return text.split(/(\s+)/).filter((t) => t.length > 0);
		},

		longestCommonSubsequence(a, b) {
			const m = a.length;
			const n = b.length;
			// Use simplified approach for performance — limit to first 500 tokens
			const maxLen = 500;
			const aa = a.slice(0, maxLen);
			const bb = b.slice(0, maxLen);
			const mm = aa.length;
			const nn = bb.length;

			const dp = Array(mm + 1)
				.fill(null)
				.map(() => Array(nn + 1).fill(0));

			for (let i = 1; i <= mm; i++) {
				for (let j = 1; j <= nn; j++) {
					if (aa[i - 1] === bb[j - 1]) {
						dp[i][j] = dp[i - 1][j - 1] + 1;
					} else {
						dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
					}
				}
			}

			// Backtrack to find LCS
			const result = [];
			let i = mm,
				j = nn;
			while (i > 0 && j > 0) {
				if (aa[i - 1] === bb[j - 1]) {
					result.unshift(aa[i - 1]);
					i--;
					j--;
				} else if (dp[i - 1][j] > dp[i][j - 1]) {
					i--;
				} else {
					j--;
				}
			}
			return result;
		},

		escapeHtml(text) {
			return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
		},
	},
};
</script>

<style scoped>
.nora-diff-panel {
	border: 1px solid var(--primary-color, #2490ef);
	border-radius: 8px;
	margin: 8px 16px;
	overflow: hidden;
	background: var(--card-bg, white);
}

.diff-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 8px 12px;
	background: var(--bg-light-gray, #f8f9fa);
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.diff-title {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
	font-weight: 600;
	color: var(--primary-color, #2490ef);
}

.diff-actions {
	display: flex;
	gap: 6px;
}

.btn-accept,
.btn-reject {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 4px 12px;
	border: 1px solid;
	border-radius: 6px;
	cursor: pointer;
	font-size: 12px;
	font-weight: 500;
	transition: all 0.15s ease;
}

.btn-accept {
	background: var(--green-100, #d4edda);
	border-color: var(--green-500, #28a745);
	color: var(--green-700, #155724);
}

.btn-accept:hover {
	background: var(--green-500, #28a745);
	color: white;
}

.btn-reject {
	background: var(--card-bg, white);
	border-color: var(--border-color, #e5e5e5);
	color: var(--text-muted, #8d99a6);
}

.btn-reject:hover {
	background: var(--bg-gray, #eee);
	color: var(--text-color, #333);
}

.diff-content {
	display: flex;
	max-height: 300px;
	overflow-y: auto;
}

.diff-column {
	flex: 1;
	padding: 12px;
	min-width: 0;
}

.diff-column-header {
	font-size: 11px;
	font-weight: 600;
	text-transform: uppercase;
	color: var(--text-muted, #8d99a6);
	margin-bottom: 8px;
	letter-spacing: 0.5px;
}

.diff-text {
	font-size: 13px;
	line-height: 1.6;
	color: var(--text-color, #333);
	white-space: pre-wrap;
	word-wrap: break-word;
}

.diff-divider {
	width: 1px;
	background: var(--border-color, #e5e5e5);
	flex-shrink: 0;
}

.diff-text :deep(.diff-del) {
	background: var(--red-100, #f8d7da);
	color: var(--red-700, #721c24);
	text-decoration: line-through;
	border-radius: 2px;
	padding: 0 2px;
}

.diff-text :deep(.diff-add) {
	background: var(--green-100, #d4edda);
	color: var(--green-700, #155724);
	border-radius: 2px;
	padding: 0 2px;
}
</style>
