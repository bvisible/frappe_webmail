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
	},

	props: {
		email: { type: Object, default: null },
		account: { type: String, required: true },
		folder: { type: String, default: "INBOX" },
	},

	emits: ["reply", "forward", "delete", "flag-changed", "mark-unread"],

	data() {
		return {
			showExternalImages: false,
			hasBlockedImages: false,
			senderContact: null,
			showAllAttachments: false,
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
	padding: 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	flex: 0 0 auto;
}

.email-subject {
	font-size: 18px;
	font-weight: 600;
	margin-bottom: 12px;
	color: var(--text-color, #333);
}

.email-meta {
	font-size: 13px;
	color: var(--text-muted, #8d99a6);
}

.email-meta .from {
	color: var(--text-color, #333);
	margin-bottom: 4px;
}

.email-meta .email-address {
	color: var(--text-muted, #8d99a6);
	font-weight: normal;
}

.email-actions {
	display: flex;
	gap: 8px;
	padding: 8px 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	background: var(--subtle-bg, #f5f5f5);
	flex: 0 0 auto;
}

.email-actions .btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 6px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	background: var(--card-bg, white);
	cursor: pointer;
	font-size: 13px;
	color: var(--text-color, #333);
	transition: all 0.15s ease;
}

.email-actions .btn:hover {
	background: var(--hover-bg, #eee);
}

.email-actions .btn.starred {
	color: var(--yellow-500, #eab308);
}

.email-actions .btn-danger:hover {
	background: var(--red-50, #fef2f2);
	border-color: var(--red-200, #fecaca);
	color: var(--red-600, #dc2626);
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
</style>
