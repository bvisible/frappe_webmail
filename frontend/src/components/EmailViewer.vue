<template>
	<div class="email-viewer" v-if="email">
		<!-- Scrollable content area -->
		<div class="email-content">
			<!-- Header -->
			<div class="email-header">
				<div class="email-subject">{{ email.subject || "(Sans objet)" }}</div>
				<div class="email-meta">
					<div class="from">
						<div class="from-info">
							<strong>{{ email.from_name || email.from_email }}</strong>
							<span class="email-address">&lt;{{ email.from_email }}&gt;</span>
							<span
								v-if="senderContact"
								class="contact-badge"
								:title="'Contact: ' + senderContact.full_name"
							>
								<User :size="14" />
							</span>
							<button
								v-else
								@click="saveAsContact(email.from_email, email.from_name)"
								class="add-contact-btn"
								title="Ajouter aux contacts"
							>
								<UserPlus :size="14" />
							</button>
						</div>
					</div>
					<div class="to">A: {{ email.to }}</div>
					<div v-if="email.cc" class="cc">Cc: {{ email.cc }}</div>
					<div class="date">{{ formatDate(email.date) }}</div>
				</div>
			</div>

			<!-- Actions -->
			<div class="email-actions">
				<button @click="$emit('reply', email)" class="btn btn-sm">
					<Reply :size="16" />
					<span>Repondre</span>
				</button>
				<button @click="$emit('forward', email)" class="btn btn-sm">
					<Forward :size="16" />
					<span>Transferer</span>
				</button>
				<button @click="markAsUnread" class="btn btn-sm" title="Marquer comme non lu">
					<MailOpen :size="16" />
					<span>Non lu</span>
				</button>
				<button @click="toggleStar" class="btn btn-sm" :class="{ starred: email.flagged }">
					<Star :size="16" :fill="email.flagged ? 'currentColor' : 'none'" />
				</button>
				<button @click="$emit('delete', email)" class="btn btn-sm btn-danger">
					<Trash2 :size="16" />
				</button>
				<span class="actions-separator"></span>
				<button
					@click="handleQuickReply"
					class="btn btn-sm btn-nora"
					:disabled="quickReplyLoading"
					:title="__('Quick Reply with Nora')"
				>
					<Sparkles :size="16" />
					<span>{{ quickReplyLoading ? __("Generating...") : __("Quick Reply") }}</span>
					<div v-if="quickReplyLoading" class="nora-spinner-small"></div>
				</button>
			</div>

			<!-- External images warning -->
			<div v-if="hasBlockedImages && !showExternalImages" class="blocked-images-notice">
				<AlertTriangle :size="16" class="warning-icon" />
				<span>Les images externes ont ete bloquees pour votre securite.</span>
				<button @click="showExternalImages = true">Afficher les images</button>
				<button @click="trustSender" class="trust-btn" :title="email.from_email">
					Toujours pour cet expediteur
				</button>
				<button v-if="senderDomain" @click="trustDomain" class="trust-btn">
					Toujours pour {{ senderDomain }}
				</button>
			</div>

			<!-- Body (sandboxed iframe) -->
			<iframe
				ref="emailFrame"
				class="email-body"
				sandbox="allow-popups allow-popups-to-escape-sandbox"
				referrerpolicy="no-referrer"
				:srcdoc="sanitizedContent"
			/>
		</div>

		<!-- Attachments Footer (sticky at bottom) -->
		<div v-if="email.attachments?.length" class="email-attachments">
			<div class="attachments-header" @click="toggleAttachments">
				<div class="attachments-title">
					<Paperclip :size="14" />
					<span
						>{{ email.attachments.length }}
						{{
							email.attachments.length > 1 ? "pieces jointes" : "piece jointe"
						}}</span
					>
				</div>
				<button v-if="email.attachments.length > 2" class="toggle-btn">
					<ChevronUp v-if="showAllAttachments" :size="16" />
					<ChevronDown v-else :size="16" />
				</button>
			</div>
			<div class="attachment-list" :class="{ expanded: showAllAttachments }">
				<div
					v-for="(att, index) in visibleAttachments"
					:key="att.id"
					class="attachment-item"
					@click.stop="downloadAttachment(att)"
				>
					<component :is="getFileIcon(att.content_type)" :size="16" class="file-icon" />
					<span class="name">{{ att.filename }}</span>
					<span class="size">({{ formatSize(att.size) }})</span>
				</div>
				<button
					v-if="!showAllAttachments && email.attachments.length > 2"
					class="show-more-btn"
					@click.stop="showAllAttachments = true"
				>
					+{{ email.attachments.length - 2 }} autres
				</button>
			</div>
		</div>

		<!-- Inline reply bar — answer without opening the full composer.
		     Cmd/Ctrl + Enter sends. The maximize button opens the full
		     composer modal (formatting, attachments, signature…). -->
		<div class="reply-bar">
			<div class="reply-wrap">
				<textarea
					v-model="quickReplyText"
					class="reply-input"
					:placeholder="__('Reply to {0}…', [email.from_name || email.from_email])"
					@keydown.meta.enter.prevent="sendQuickReply"
					@keydown.ctrl.enter.prevent="sendQuickReply"
				></textarea>
				<div class="reply-foot">
					<button
						class="reply-tool"
						@click="$emit('reply', email)"
						:title="__('Open full composer (formatting, attachments…)')"
					>
						<Maximize2 :size="14" />
					</button>
					<span class="reply-spacer"></span>
					<button
						class="reply-send"
						@click="sendQuickReply"
						:disabled="!quickReplyText.trim() || sendingReply"
					>
						<Send :size="13" />
						<span>{{ sendingReply ? __("Sending…") : __("Send") }}</span>
					</button>
				</div>
			</div>
		</div>
	</div>
	<div v-else class="no-email-selected">
		<p>Selectionnez un email pour le lire</p>
	</div>
</template>

<script>
import DOMPurify from "dompurify";
import {
	User,
	UserPlus,
	Reply,
	Forward,
	MailOpen,
	Star,
	Trash2,
	AlertTriangle,
	Paperclip,
	File,
	FileText,
	Image,
	Film,
	Music,
	Archive,
	FileSpreadsheet,
	ChevronDown,
	ChevronUp,
	Sparkles,
	Send,
	Maximize2,
} from "lucide-vue-next";

export default {
	name: "EmailViewer",

	components: {
		User,
		UserPlus,
		Reply,
		Forward,
		MailOpen,
		Star,
		Trash2,
		AlertTriangle,
		Paperclip,
		File,
		FileText,
		Image,
		Film,
		Music,
		Archive,
		FileSpreadsheet,
		ChevronDown,
		ChevronUp,
		Sparkles,
		Send,
		Maximize2,
	},

	props: {
		email: { type: Object, default: null },
		account: { type: String, required: true },
		folder: { type: String, default: "INBOX" },
	},

	emits: ["reply", "forward", "delete", "flag-changed", "mark-unread", "quick-reply"],

	data() {
		return {
			showExternalImages: false,
			hasBlockedImages: false,
			senderContact: null,
			showAllAttachments: false,
			quickReplyLoading: false,
			// Inline reply bar state — lets the user answer without opening
			// the full composer modal.
			quickReplyText: "",
			sendingReply: false,
		};
	},

	computed: {
		senderDomain() {
			if (!this.email?.from_email) return "";
			const parts = this.email.from_email.split("@");
			return parts.length > 1 ? parts[1] : "";
		},

		visibleAttachments() {
			if (!this.email?.attachments) return [];
			if (this.showAllAttachments) return this.email.attachments;
			return this.email.attachments.slice(0, 2);
		},

		sanitizedContent() {
			if (!this.email) return "";

			const content = this.email.html || this.wrapPlainText(this.email.text);
			if (!content) return "";

			// Configure DOMPurify
			const config = {
				WHOLE_DOCUMENT: true,
				FORBID_TAGS: [
					"script",
					"style",
					"audio",
					"video",
					"form",
					"input",
					"button",
					"textarea",
					"object",
					"embed",
				],
				FORBID_ATTR: [
					"onerror",
					"onload",
					"onclick",
					"onmouseover",
					"onfocus",
					"onblur",
					"onsubmit",
				],
				ALLOW_DATA_ATTR: false,
			};

			// Hook to handle external images
			this.hasBlockedImages = false;
			const self = this;

			DOMPurify.addHook("afterSanitizeAttributes", (node) => {
				// Block external images unless allowed
				if (node.tagName === "IMG" && !self.showExternalImages) {
					const src = node.getAttribute("src");
					if (src && !src.startsWith("data:") && !src.startsWith("cid:")) {
						node.setAttribute("data-blocked-src", src);
						node.setAttribute(
							"src",
							'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" fill="gray" font-size="12">[Image bloquee]</text></svg>'
						);
						node.style.cursor = "pointer";
						node.title = "Image externe bloquee";
						self.hasBlockedImages = true;
					}
				}

				// Open links in new tab
				if (node.tagName === "A") {
					node.setAttribute("target", "_blank");
					node.setAttribute("rel", "noopener noreferrer");
				}
			});

			const clean = DOMPurify.sanitize(content, config);

			// Remove hook to avoid affecting other sanitizations
			DOMPurify.removeHook("afterSanitizeAttributes");

			// Wrap in HTML document with base styles
			return `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            * { box-sizing: border-box; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
              font-size: 14px;
              line-height: 1.6;
              color: #333;
              margin: 0;
              padding: 16px;
              word-wrap: break-word;
            }
            img { max-width: 100%; height: auto; }
            a { color: #0066cc; }
            blockquote {
              border-left: 3px solid #ccc;
              margin: 10px 0;
              padding-left: 15px;
              color: #666;
            }
            pre, code {
              background: #f5f5f5;
              padding: 2px 6px;
              border-radius: 3px;
              font-size: 13px;
            }
            pre { padding: 10px; overflow-x: auto; }
            table { max-width: 100%; }
          </style>
        </head>
        <body>${clean}</body>
        </html>
      `;
		},
	},

	watch: {
		email: {
			immediate: true,
			handler(newEmail) {
				this.showExternalImages = false;
				this.hasBlockedImages = false;
				this.showAllAttachments = false;
				if (newEmail?.from_email) {
					this.loadSenderContact(newEmail.from_email);
					this.checkTrustedSender();
				} else {
					this.senderContact = null;
				}
			},
		},
	},

	methods: {
		// Send a quick text reply from the inline bar at the bottom of
		// the reader. Skips the full composer modal — for one-liners.
		async sendQuickReply() {
			if (!this.quickReplyText.trim() || this.sendingReply || !this.email) return;
			this.sendingReply = true;
			try {
				const sub = (this.email.subject || "").trim();
				const subject = /^re\s*:/i.test(sub) ? sub : "Re: " + sub;
				const body = this.quickReplyText
					.split("\n")
					.map((line) => `<p>${this.escapeHtml(line) || "&nbsp;"}</p>`)
					.join("");
				await frappe.call({
					method: "frappe_webmail.api.send_email",
					args: {
						account_name: this.account,
						to: this.email.from_email,
						subject: subject,
						html_content: body,
						reply_to_message_id: this.email.message_id || null,
						reply_to_uid: this.email.uid,
						reply_to_folder: this.folder,
					},
				});
				frappe.show_alert({ message: this.__("Reply sent"), indicator: "green" }, 4);
				this.quickReplyText = "";
			} catch (e) {
				frappe.toast({
					message: this.__("Error sending reply"),
					indicator: "red",
				});
			} finally {
				this.sendingReply = false;
			}
		},

		// Minimal HTML escape so a quick reply can't inject markup.
		escapeHtml(s) {
			return (s || "")
				.replace(/&/g, "&amp;")
				.replace(/</g, "&lt;")
				.replace(/>/g, "&gt;")
				.replace(/"/g, "&quot;")
				.replace(/'/g, "&#039;");
		},

		async handleQuickReply() {
			if (this.quickReplyLoading || !this.email) return;
			this.quickReplyLoading = true;

			try {
				const result = await frappe.call({
					method: "nora.api.nora_webmail.quick_reply",
					args: {
						account_name: this.account,
						email_uid: this.email.uid,
						folder: this.folder,
					},
				});

				const data = result.message || result;
				if (data.success) {
					this.$emit("quick-reply", {
						draft_html: data.draft_html,
						draft_text: data.draft_text,
						original_email: this.email,
					});
				} else {
					frappe.toast({
						message: __("Failed to generate reply"),
						indicator: "red",
					});
				}
			} catch (error) {
				console.error("Quick reply error:", error);
				frappe.toast({
					message: __("Nora encountered an error. Please try again."),
					indicator: "red",
				});
			} finally {
				this.quickReplyLoading = false;
			}
		},

		toggleAttachments() {
			if (this.email?.attachments?.length > 2) {
				this.showAllAttachments = !this.showAllAttachments;
			}
		},

		wrapPlainText(text) {
			if (!text) return "";
			const escaped = text
				.replace(/&/g, "&amp;")
				.replace(/</g, "&lt;")
				.replace(/>/g, "&gt;")
				.replace(/\n/g, "<br>");
			return `<pre style="white-space: pre-wrap; font-family: inherit;">${escaped}</pre>`;
		},

		formatDate(dateStr) {
			if (!dateStr) return "";
			return new Date(dateStr).toLocaleString("fr-FR", {
				dateStyle: "full",
				timeStyle: "short",
			});
		},

		formatSize(bytes) {
			if (!bytes) return "0 B";
			if (bytes < 1024) return bytes + " B";
			if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
			return (bytes / (1024 * 1024)).toFixed(1) + " MB";
		},

		getFileIcon(contentType) {
			if (!contentType) return File;
			if (contentType.startsWith("image/")) return Image;
			if (contentType.startsWith("video/")) return Film;
			if (contentType.startsWith("audio/")) return Music;
			if (contentType.includes("pdf")) return FileText;
			if (contentType.includes("word") || contentType.includes("document")) return FileText;
			if (contentType.includes("sheet") || contentType.includes("excel"))
				return FileSpreadsheet;
			if (contentType.includes("zip") || contentType.includes("archive")) return Archive;
			return File;
		},

		async toggleStar() {
			const action = this.email.flagged ? "remove_flags" : "add_flags";
			const flags = ["\\Flagged"];

			try {
				await frappe.call({
					method: "frappe_webmail.api.set_flags",
					args: {
						account_name: this.account,
						uids: JSON.stringify([this.email.uid]),
						folder: this.folder,
						[action]: JSON.stringify(flags),
					},
				});

				this.email.flagged = !this.email.flagged;
				this.$emit("flag-changed", this.email);
			} catch (error) {
				frappe.toast({ message: "Erreur", indicator: "red" });
			}
		},

		async markAsUnread() {
			try {
				await frappe.call({
					method: "frappe_webmail.api.set_flags",
					args: {
						account_name: this.account,
						uids: JSON.stringify([this.email.uid]),
						folder: this.folder,
						remove_flags: JSON.stringify(["\\Seen"]),
					},
				});

				this.email.seen = false;
				this.$emit("mark-unread", this.email);
				frappe.toast({ message: "Marque comme non lu", indicator: "green" });
			} catch (error) {
				frappe.toast({ message: "Erreur", indicator: "red" });
			}
		},

		async downloadAttachment(attachment) {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_attachment",
					args: {
						account_name: this.account,
						uid: this.email.uid,
						folder: this.folder,
						attachment_id: attachment.id,
					},
				});

				const data = response.message;
				const byteCharacters = atob(data.data);
				const byteNumbers = new Array(byteCharacters.length);
				for (let i = 0; i < byteCharacters.length; i++) {
					byteNumbers[i] = byteCharacters.charCodeAt(i);
				}
				const byteArray = new Uint8Array(byteNumbers);
				const blob = new Blob([byteArray], { type: data.content_type });

				const url = URL.createObjectURL(blob);
				const a = document.createElement("a");
				a.href = url;
				a.download = data.filename;
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
			} catch (error) {
				frappe.toast({ message: "Erreur de telechargement", indicator: "red" });
			}
		},

		async loadSenderContact(email) {
			if (!email) {
				this.senderContact = null;
				return;
			}

			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_contact_by_email",
					args: { email },
				});
				this.senderContact = response.message;
			} catch (error) {
				this.senderContact = null;
			}
		},

		async saveAsContact(email, name) {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.create_contact_from_email",
					args: { email, name },
				});

				if (response.message.success) {
					frappe.toast({
						message: `Contact cree: ${response.message.full_name}`,
						indicator: "green",
					});
					this.loadSenderContact(email);
				} else {
					frappe.toast({
						message: response.message.message,
						indicator: "orange",
					});
					// Load existing contact
					this.loadSenderContact(email);
				}
			} catch (error) {
				frappe.toast({
					message: "Erreur lors de la creation du contact",
					indicator: "red",
				});
			}
		},

		async checkTrustedSender() {
			if (!this.email?.from_email) return;

			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.is_sender_trusted",
					args: {
						account_name: this.account,
						from_email: this.email.from_email,
					},
				});

				if (response.message) {
					this.showExternalImages = true;
				}
			} catch (error) {
				console.error("Error checking trusted sender:", error);
			}
		},

		async trustSender() {
			if (!this.email?.from_email) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.add_trusted_source",
					args: {
						account_name: this.account,
						value: this.email.from_email,
						source_type: "Sender",
					},
				});

				this.showExternalImages = true;
				frappe.toast({
					message: "Expediteur ajoute a la liste de confiance",
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({
					message: "Erreur",
					indicator: "red",
				});
			}
		},

		async trustDomain() {
			if (!this.senderDomain) return;

			try {
				await frappe.call({
					method: "frappe_webmail.webmail_api.add_trusted_source",
					args: {
						account_name: this.account,
						value: this.senderDomain,
						source_type: "Domain",
					},
				});

				this.showExternalImages = true;
				frappe.toast({
					message: "Domaine ajoute a la liste de confiance",
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({
					message: "Erreur",
					indicator: "red",
				});
			}
		},
	},
};
</script>

<style scoped>
.email-viewer {
	display: flex;
	flex-direction: column;
	height: 100%;
	background: var(--card-bg, white);
	position: relative;
	overflow: hidden;
	min-height: 0;
}

.email-content {
	flex: 1 1 0;
	display: flex;
	flex-direction: column;
	overflow-y: auto;
	overflow-x: hidden;
	min-height: 0;
}

.no-email-selected {
	display: flex;
	align-items: center;
	justify-content: center;
	height: 100%;
	color: var(--text-muted, #8d99a6);
}

.email-header {
	padding: 16px 26px 14px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
	flex: 0 0 auto;
	background: var(--wm-bg-raised, #ffffff);
}

/* Subject: serif heading from the Neoffice theme (Forum). We don't override
   font-family here on purpose so the global h1/h2 style still wins. */
.email-subject {
	font-size: 22px;
	font-weight: 400;
	letter-spacing: -0.005em;
	margin-bottom: 12px;
	color: var(--wm-ink, #1a1a1a);
	line-height: 1.25;
}

/* Sender meta block — visually grouped into a soft card to match the
   "sender-card" pattern from the design without restructuring the markup. */
.email-meta {
	font-size: 13px;
	color: var(--wm-ink-mute, #8d99a6);
	background: var(--wm-bg-sunken, #f7f7f5);
	border-radius: 10px;
	padding: 10px 12px;
	display: flex;
	flex-direction: column;
	gap: 3px;
}

.email-meta .from {
	color: var(--wm-ink, #1a1a1a);
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
}

.email-meta .from strong {
	font-weight: 600;
}

.email-meta .email-address {
	color: var(--wm-ink-mute, #8d99a6);
	font-weight: normal;
	font-size: 12px;
}

.email-meta .to,
.email-meta .cc,
.email-meta .date {
	font-size: 12px;
	color: var(--wm-ink-mute, #8d99a6);
}

/* Actions row: ghost buttons (no border) — only hover gives a soft bg. */
.email-actions {
	display: flex;
	gap: 4px;
	padding: 8px 22px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
	background: transparent;
	flex: 0 0 auto;
	align-items: center;
	flex-wrap: wrap;
}

.email-actions .btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 6px 10px;
	border: 0;
	border-radius: 7px;
	background: transparent;
	cursor: pointer;
	font-size: 12.5px;
	color: var(--wm-ink-soft, #555);
	transition: background 0.15s, color 0.15s;
	font-family: inherit;
	font-weight: 500;
}

.email-actions .btn:hover {
	background: var(--wm-bg-sunken, #f7f7f5);
	color: var(--wm-ink, #1a1a1a);
}

.email-actions .btn.starred {
	color: var(--wm-amber, #b45309);
}

.email-actions .btn-danger:hover {
	background: var(--wm-danger-soft, #fee2e2);
	color: var(--wm-danger, #dc2626);
}

.actions-separator {
	width: 1px;
	height: 16px;
	background: var(--wm-line, #e5e5e5);
	margin: 0 4px;
}

.blocked-images-notice {
	padding: 10px 16px;
	background: var(--yellow-50, #fefce8);
	border-bottom: 1px solid var(--yellow-300, #fcd34d);
	font-size: 13px;
	display: flex;
	align-items: center;
	gap: 10px;
	flex-wrap: wrap;
	color: var(--yellow-800, #854d0e);
	flex: 0 0 auto;
}

.blocked-images-notice .warning-icon {
	flex-shrink: 0;
}

.blocked-images-notice button {
	background: none;
	border: none;
	color: var(--primary-color, #2490ef);
	cursor: pointer;
	text-decoration: underline;
	font-size: 13px;
}

.blocked-images-notice .trust-btn {
	color: var(--text-muted, #666);
	font-size: 12px;
}

.blocked-images-notice .trust-btn:hover {
	color: var(--primary-color, #2490ef);
}

.email-body {
	flex: 1 1 0;
	border: none;
	width: 100%;
	min-height: 100px;
}

/* Attachments Footer - always visible at bottom */
.email-attachments {
	flex: 0 0 auto;
	padding: 10px 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
	background: var(--subtle-bg, #f5f5f5);
	max-height: 150px;
	overflow-y: auto;
}

.attachments-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	cursor: pointer;
	margin-bottom: 8px;
}

.attachments-title {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
	font-weight: 600;
	color: var(--text-color, #333);
}

.toggle-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 24px;
	height: 24px;
	padding: 0;
	border: none;
	background: transparent;
	color: var(--text-muted, #8d99a6);
	cursor: pointer;
	border-radius: 4px;
	transition: all 0.15s ease;
}

.toggle-btn:hover {
	background: rgba(0, 0, 0, 0.05);
	color: var(--text-color, #333);
}

.attachment-list {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	align-items: center;
}

.attachment-item {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 6px 10px;
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	cursor: pointer;
	font-size: 12px;
	transition: all 0.15s ease;
	max-width: 200px;
}

.attachment-item:hover {
	background: var(--hover-bg, #f5f5f5);
	border-color: var(--primary-color, #2490ef);
}

.attachment-item .file-icon {
	color: var(--text-muted, #8d99a6);
	flex-shrink: 0;
}

.attachment-item .name {
	color: var(--text-color, #333);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	max-width: 120px;
}

.attachment-item .size {
	color: var(--text-muted, #8d99a6);
	white-space: nowrap;
	flex-shrink: 0;
}

.show-more-btn {
	display: inline-flex;
	align-items: center;
	padding: 6px 12px;
	background: var(--primary-color, #2490ef);
	color: white;
	border: none;
	border-radius: 6px;
	font-size: 12px;
	font-weight: 500;
	cursor: pointer;
	transition: all 0.15s ease;
}

.show-more-btn:hover {
	background: var(--primary-dark, #1a7fd4);
}

.from-info {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-wrap: wrap;
}

.contact-badge {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	padding: 4px 8px;
	border-radius: 4px;
	cursor: help;
	color: var(--primary-color, #2490ef);
}

.add-contact-btn {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	background: none;
	border: 1px dashed var(--border-color, #ccc);
	border-radius: 4px;
	padding: 4px 8px;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
	transition: all 0.15s ease;
}

.add-contact-btn:hover {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	border-color: var(--primary-color, #2490ef);
	border-style: solid;
	color: var(--primary-color, #2490ef);
}

.actions-separator {
	width: 1px;
	height: 24px;
	background: var(--border-color, #e5e5e5);
	flex-shrink: 0;
}

.email-actions .btn-nora {
	border-color: var(--primary-color, #2490ef);
	color: var(--primary-color, #2490ef);
	font-weight: 500;
}

.email-actions .btn-nora:hover {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.1));
}

.email-actions .btn-nora:disabled {
	opacity: 0.6;
	cursor: wait;
}

.nora-spinner-small {
	width: 12px;
	height: 12px;
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

/* ========================================================================
   Inline reply bar — sticky at the bottom of the reader column.
   The textarea grows to 56px, focus puts a soft accent ring around the
   wrap. Cmd/Ctrl + Enter triggers Send via the keydown handler.
   ======================================================================== */
.reply-bar {
	flex-shrink: 0;
	padding: 10px 14px;
	border-top: 1px solid var(--wm-line, #e5e5e5);
	background: var(--wm-bg-sunken, #f5f5f5);
}

.reply-wrap {
	background: var(--wm-bg-raised, #fff);
	border: 1px solid var(--wm-line, #e5e5e5);
	border-radius: 10px;
	overflow: hidden;
	transition: border-color 0.15s, box-shadow 0.15s;
}

.reply-wrap:focus-within {
	border-color: var(--wm-accent, #5145e8);
	box-shadow: 0 0 0 3px var(--wm-accent-soft, #eeebfe);
}

.reply-input {
	display: block;
	width: 100%;
	padding: 10px 14px;
	border: 0;
	outline: none;
	resize: none;
	font-size: 13.5px;
	color: var(--wm-ink, #1a1a1a);
	background: transparent;
	font-family: inherit;
	line-height: 1.5;
	height: 56px;
}

.reply-input::placeholder {
	color: var(--wm-ink-mute, #b0b0b0);
}

.reply-foot {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 6px 8px;
	border-top: 1px solid var(--wm-line-soft, #efefef);
	background: var(--wm-bg, #fafafa);
}

.reply-tool {
	width: 26px;
	height: 26px;
	display: grid;
	place-items: center;
	border: 0;
	background: transparent;
	border-radius: 6px;
	cursor: pointer;
	color: var(--wm-ink-mute, #8d99a6);
	transition: background 0.15s, color 0.15s;
}

.reply-tool:hover {
	background: var(--wm-bg-sunken, #f5f5f5);
	color: var(--wm-ink, #1a1a1a);
}

.reply-spacer {
	flex: 1;
}

.reply-send {
	height: 28px;
	padding: 0 14px;
	border: 0;
	border-radius: 7px;
	background: var(--wm-accent, #5145e8);
	color: white;
	font-size: 12.5px;
	font-weight: 500;
	cursor: pointer;
	display: inline-flex;
	align-items: center;
	gap: 5px;
	box-shadow: 0 1px 2px rgba(81, 69, 232, 0.3);
	font-family: inherit;
	transition: background 0.15s;
}

.reply-send:hover:not(:disabled) {
	background: var(--wm-accent-hover, #4338d4);
}

.reply-send:disabled {
	opacity: 0.55;
	cursor: not-allowed;
}
</style>
