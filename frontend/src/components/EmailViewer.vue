<template>
	<div class="email-viewer" v-if="email">
		<!-- Scrollable content area -->
		<div class="email-content">
			<!-- Header, as the canvas « Neodesk » draws it (board 7): the subject in Forum with the message's actions
			     beside it (Nora's reply first), then who wrote, to whom and when -->
			<div class="email-header">
				<div class="subject-row">
					<div class="email-subject">{{ email.subject || __("(No subject)") }}</div>
					<div class="email-actions">
						<button
							v-if="noraEnabled"
							@click="handleQuickReply"
							class="nora-reply"
							:disabled="quickReplyLoading"
							:data-tip="__('Let Nora draft the reply (about 10 s)')"
						>
							<NoraOrb :size="20" />
							<span>{{
								quickReplyLoading ? __("Nora is drafting…") : __("Reply with Nora")
							}}</span>
							<div v-if="quickReplyLoading" class="nora-spinner-small"></div>
						</button>
						<button
							@click="$emit('reply', email)"
							class="btn"
							:data-tip="__('Reply')"
							:aria-label="__('Reply')"
						>
							<Reply :size="16" />
						</button>
						<button
							@click="$emit('forward', email)"
							class="btn"
							:data-tip="__('Forward')"
							:aria-label="__('Forward')"
						>
							<Forward :size="16" />
						</button>
						<button
							@click="markAsUnread"
							class="btn"
							:data-tip="__('Mark as unread')"
							:aria-label="__('Mark as unread')"
						>
							<MailOpen :size="16" />
						</button>
						<button
							@click="toggleStar"
							class="btn"
							:class="{ starred: email.flagged }"
							:data-tip="email.flagged ? __('Remove star') : __('Star')"
							:aria-label="email.flagged ? __('Remove star') : __('Star')"
						>
							<Star :size="16" :fill="email.flagged ? 'currentColor' : 'none'" />
						</button>
						<button
							@click="$emit('delete', email)"
							class="btn btn-danger"
							:data-tip="__('Delete')"
							:aria-label="__('Delete')"
						>
							<Trash2 :size="16" />
						</button>
					</div>
				</div>
				<div class="email-meta">
					<div class="from-info">
						<strong>{{ email.from_name || email.from_email }}</strong>
						<span class="email-address">&lt;{{ email.from_email }}&gt;</span>
						<span
							v-if="senderContact"
							class="contact-badge"
							:title="__('Contact: {0}', [senderContact.full_name])"
						>
							<User :size="13" />
						</span>
						<button
							v-else
							@click="saveAsContact(email.from_email, email.from_name)"
							class="add-contact-btn"
							:data-tip="__('Add to contacts')"
							:aria-label="__('Add to contacts')"
						>
							<UserPlus :size="13" />
						</button>
					</div>
					<div class="meta-line">
						<span class="to">{{ __("To: {0}", [email.to]) }}</span>
						<span v-if="email.cc" class="cc">· {{ __("Cc: {0}", [email.cc]) }}</span>
						<span class="date">· {{ formatDate(email.date) }}</span>
					</div>
				</div>
				<!-- Who wrote, in Neoffice: their supplier or customer, its invoices of the year, its record (board 7) -->
				<div v-if="senderCard" class="sender-card">
					<span class="sender-mark">{{ initials(senderCard.title) }}</span>
					<span class="sender-text">
						{{ senderCard.kind }} <b>{{ senderCard.title }}</b
						><template v-if="senderInvoices"> · {{ senderInvoices }}</template>
					</span>
					<button class="sender-open" @click="openSenderCard">
						{{ __("Open the record") }}
					</button>
				</div>
			</div>

			<!-- External images warning -->
			<div v-if="hasBlockedImages && !showExternalImages" class="blocked-images-notice">
				<AlertTriangle :size="16" class="warning-icon" />
				<span>{{ __("External images were blocked for your safety.") }}</span>
				<button @click="showExternalImages = true">{{ __("Show the images") }}</button>
				<button @click="trustSender" class="trust-btn" :title="email.from_email">
					{{ __("Always for this sender") }}
				</button>
				<button v-if="senderDomain" @click="trustDomain" class="trust-btn">
					{{ __("Always for {0}", [senderDomain]) }}
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

		<!-- Attachments footer (sticky at bottom): a card each, its kind and its size under its name, as the
		     canvas « Neodesk » draws them (boards 2 and 7) -->
		<div v-if="email.attachments?.length" class="email-attachments">
			<div class="attachments-header" @click="toggleAttachments">
				<div class="attachments-title">
					<Paperclip :size="13" />
					<span>{{
						email.attachments.length > 1
							? __("{0} attachments", [email.attachments.length])
							: __("1 attachment")
					}}</span>
				</div>
				<button v-if="email.attachments.length > 2" class="toggle-btn">
					<ChevronUp v-if="showAllAttachments" :size="16" />
					<ChevronDown v-else :size="16" />
				</button>
			</div>
			<div class="attachment-list" :class="{ expanded: showAllAttachments }">
				<!-- A click opens it (shown if the browser can, saved otherwise); a right-click, or ⋯,
				     the menu the server describes (attachmentActions.js) -->
				<div
					v-for="att in visibleAttachments"
					:key="att.id"
					class="attachment-item"
					:class="{
						'menu-open': attachmentMenu.visible && attachmentMenu.attachment === att,
					}"
					role="button"
					tabindex="0"
					:title="att.filename"
					@click.stop="openAttachment(att)"
					@keydown.enter.prevent="openAttachment(att)"
					@contextmenu.prevent.stop="openAttachmentMenu($event, att)"
				>
					<span class="file-glyph">
						<component :is="getFileIcon(att.content_type)" :size="18" />
					</span>
					<span class="att-text">
						<span class="name">{{ att.filename }}</span>
						<span class="meta">{{ attachmentMeta(att) }}</span>
					</span>
					<button
						v-if="attachmentActions.length"
						class="attachment-more"
						:aria-label="__('Actions on {0}', [att.filename])"
						@click.stop="openAttachmentMenu($event, att)"
					>
						<MoreHorizontal :size="14" />
					</button>
				</div>
				<button
					v-if="!showAllAttachments && email.attachments.length > 2"
					class="show-more-btn"
					@click.stop="showAllAttachments = true"
				>
					{{ __("+{0} more", [email.attachments.length - 2]) }}
				</button>
			</div>
			<ContextMenu
				:visible="attachmentMenu.visible"
				:items="attachmentMenuItems"
				:position="attachmentMenu.position"
				@select="onAttachmentAction"
				@close="attachmentMenu.visible = false"
			/>
			<DriveFolderPicker
				v-if="picker.kind === 'pick_folder'"
				:attachment="picker.attachment"
				:busy="picker.busy"
				@pick="
					(folder) =>
						runAttachmentAction(picker.action, picker.attachment, {
							drive_folder: folder.name,
						})
				"
				@close="closePicker"
			/>
			<DocumentPicker
				v-if="picker.kind === 'pick_document'"
				:attachment="picker.attachment"
				:busy="picker.busy"
				@pick="(doc) => runAttachmentAction(picker.action, picker.attachment, doc)"
				@close="closePicker"
			/>
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
		<p>{{ __("Select an e-mail to read it") }}</p>
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
	Send,
	Maximize2,
	MoreHorizontal,
} from "lucide-vue-next";
import NoraOrb from "./NoraOrb.vue";
import ContextMenu from "./ContextMenu.vue";
import DriveFolderPicker from "./DriveFolderPicker.vue";
import DocumentPicker from "./DocumentPicker.vue";
import {
	downloadUrl,
	loadAttachmentActions,
	menuItems,
	previewable,
} from "../attachmentActions.js";

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
		NoraOrb,
		Send,
		Maximize2,
		MoreHorizontal,
		ContextMenu,
		DriveFolderPicker,
		DocumentPicker,
	},

	props: {
		email: { type: Object, default: null },
		account: { type: String, required: true },
		folder: { type: String, default: "INBOX" },
		// False on a site without the `nora` app: no AI buttons that would 404
		noraEnabled: { type: Boolean, default: true },
	},

	emits: [
		"reply",
		"forward",
		"delete",
		"flag-changed",
		"mark-unread",
		"quick-reply",
		"forward-attachment",
	],

	data() {
		return {
			showExternalImages: false,
			hasBlockedImages: false,
			senderContact: null,
			// Who wrote, in Neoffice: their supplier or customer and its invoices of the year (get_sender_card)
			senderCard: null,
			showAllAttachments: false,
			quickReplyLoading: false,
			// Inline reply bar state — lets the user answer without opening
			// the full composer modal.
			quickReplyText: "",
			sendingReply: false,
			// The menu of an attachment, as the server describes it (attachmentActions.js)
			attachmentActions: [],
			attachmentMenu: { visible: false, position: { x: 0, y: 0 }, attachment: null },
			// The window an action asks for first: a Drive folder, a Neoffice document
			picker: { kind: null, action: null, attachment: null, busy: false },
		};
	},

	computed: {
		senderDomain() {
			if (!this.email?.from_email) return "";
			const parts = this.email.from_email.split("@");
			return parts.length > 1 ? parts[1] : "";
		},

		// « 3 invoices this year », or nothing for whom may not read them (invoices is null)
		senderInvoices() {
			const n = this.senderCard?.invoices;
			if (n === null || n === undefined) return "";
			if (n === 0) return this.__("No invoice this year");
			return n === 1
				? this.__("1 invoice this year")
				: this.__("{0} invoices this year", [n]);
		},

		attachmentMenuItems() {
			return menuItems(this.attachmentActions);
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
							'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" fill="gray" font-size="12">[×]</text></svg>'
						);
						node.style.cursor = "pointer";
						node.title = __("External image blocked");
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

	mounted() {
		loadAttachmentActions().then((actions) => {
			this.attachmentActions = actions;
		});
	},

	watch: {
		email: {
			immediate: true,
			handler(newEmail) {
				this.showExternalImages = false;
				this.hasBlockedImages = false;
				this.showAllAttachments = false;
				this.attachmentMenu.visible = false;
				this.closePicker();
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

		/** A size in the reader's language and units (« 184 ko », « 1,2 Mo »; « 184 kB » in English). */
		formatSize(bytes) {
			const lang = frappe.boot?.lang || document.documentElement.lang || "en";
			const units = [
				["gigabyte", 1024 ** 3],
				["megabyte", 1024 ** 2],
				["kilobyte", 1024],
				["byte", 1],
			];
			const [unit, scale] = units.find(([, size]) => (bytes || 0) >= size) || units[3];
			const value = (bytes || 0) / scale;
			return new Intl.NumberFormat(lang, {
				style: "unit",
				unit,
				unitDisplay: "short",
				maximumFractionDigits: unit !== "byte" && value < 10 ? 1 : 0,
			}).format(value);
		},

		/** Two letters for a name (« Sanitaires Romands SA » → « SR »). */
		initials(name) {
			const words = (name || "").split(/\s+/).filter((word) => /^[\p{L}\p{N}]/u.test(word));
			return ((words[0]?.[0] || "") + (words[1]?.[0] || "")).toUpperCase() || "?";
		},

		/** What sits under an attachment's name: its kind, from its extension, and its size (« PDF · 184 ko »). */
		attachmentMeta(att) {
			const name = att.filename || "";
			const dot = name.lastIndexOf(".");
			const kind =
				dot > 0 && name.length - dot <= 6 ? name.slice(dot + 1).toUpperCase() : "";
			return [kind, this.formatSize(att.size)].filter(Boolean).join(" · ");
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
				frappe.toast({ message: __("Something went wrong"), indicator: "red" });
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
				frappe.toast({ message: __("Marked as unread"), indicator: "green" });
			} catch (error) {
				frappe.toast({ message: __("Something went wrong"), indicator: "red" });
			}
		},

		attachmentUrl(attachment, inline) {
			return downloadUrl({
				account: this.account,
				folder: this.folder,
				uid: this.email.uid,
				attachmentId: attachment.id,
				inline,
			});
		},

		// A click: shown by the browser when it can (PDF, images, text), saved otherwise
		openAttachment(attachment) {
			if (previewable(attachment.content_type)) {
				window.open(this.attachmentUrl(attachment, true), "_blank", "noopener");
			} else {
				this.downloadAttachment(attachment);
			}
		},

		// Streamed by the server (attachments.download_attachment), not base64 through JSON
		downloadAttachment(attachment) {
			const a = document.createElement("a");
			a.href = this.attachmentUrl(attachment, false);
			a.download = attachment.filename || "";
			document.body.appendChild(a);
			a.click();
			a.remove();
		},

		openAttachmentMenu(event, attachment) {
			if (!this.attachmentActions.length) return;
			const box = event.currentTarget?.getBoundingClientRect?.();
			// From the ⋯ button (or the keyboard) the menu hangs under it; from a right-click, at the pointer
			const fromPointer = event.type === "contextmenu" && event.clientX;
			this.attachmentMenu = {
				visible: true,
				attachment,
				position: fromPointer
					? { x: event.clientX, y: event.clientY }
					: { x: box ? box.left : 0, y: box ? box.bottom + 4 : 0 },
			};
		},

		onAttachmentAction({ action }) {
			const attachment = this.attachmentMenu.attachment;
			this.attachmentMenu.visible = false;
			if (!action || !attachment) return;
			if (action.kind === "client") {
				if (action.key === "preview")
					window.open(this.attachmentUrl(attachment, true), "_blank", "noopener");
				else if (action.key === "download") this.downloadAttachment(attachment);
				else if (action.key === "forward")
					this.$emit("forward-attachment", { email: this.email, attachment });
				return;
			}
			if (action.kind === "pick_folder" || action.kind === "pick_document") {
				this.picker = { kind: action.kind, action, attachment, busy: false };
				return;
			}
			this.runAttachmentAction(action, attachment, {});
		},

		closePicker() {
			this.picker = { kind: null, action: null, attachment: null, busy: false };
		},

		// Every server action takes the attachment, plus what its window asked for; it answers its own message
		async runAttachmentAction(action, attachment, extra) {
			if (!action?.method || !this.email) return;
			this.picker.busy = true;
			try {
				const r = await frappe.call({
					method: action.method,
					args: {
						account_name: this.account,
						folder: this.folder,
						uid: this.email.uid,
						attachment_id: attachment.id,
						...extra,
					},
				});
				const result = r.message || {};
				this.closePicker();
				const link = result.url
					? ` <a href="${frappe.utils.escape_html(
							result.url
					  )}">${frappe.utils.escape_html(__("Open"))}</a>`
					: "";
				frappe.show_alert(
					{
						message: `${frappe.utils.escape_html(
							result.message || __("Done")
						)}${link}`,
						indicator: "green",
					},
					8
				);
			} catch (error) {
				this.picker.busy = false;
				// The server's message (refused folder, document not found…) is already shown by frappe.call
			}
		},

		async loadSenderContact(email) {
			if (!email) {
				this.senderContact = null;
				this.senderCard = null;
				return;
			}
			this.loadSenderCard(email);

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

		// The card under the sender (board 7): kept only while the same message is open
		async loadSenderCard(email) {
			this.senderCard = null;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_sender_card",
					args: { email },
				});
				if (this.email?.from_email === email) this.senderCard = response.message || null;
			} catch (error) {
				this.senderCard = null;
			}
		},

		openSenderCard() {
			if (this.senderCard)
				frappe.set_route("Form", this.senderCard.doctype, this.senderCard.name);
		},

		async saveAsContact(email, name) {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.create_contact_from_email",
					args: { email, name },
				});

				if (response.message.success) {
					frappe.toast({
						message: __("Contact created: {0}", [response.message.full_name]),
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
					message: __("The contact could not be created"),
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
					message: __("Sender added to the trusted list"),
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({
					message: __("Something went wrong"),
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
					message: __("Domain added to the trusted list"),
					indicator: "green",
				});
			} catch (error) {
				frappe.toast({
					message: __("Something went wrong"),
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
	padding: 18px 26px 14px;
	border-bottom: 1px solid var(--wm-line-soft, #efefef);
	flex: 0 0 auto;
	background: var(--wm-bg-raised, #ffffff);
}

/* The subject and, beside it, the message's actions (board 7); they go under it when the column is narrow */
.subject-row {
	display: flex;
	align-items: flex-start;
	flex-wrap: wrap;
	gap: 10px 16px;
	margin-bottom: 10px;
}

/* Subject: serif heading from the Neoffice theme (Forum). We don't override
   font-family here on purpose so the global h1/h2 style still wins. */
.email-subject {
	flex: 1 1 260px;
	min-width: 0;
	font-size: 24px;
	font-weight: 400;
	letter-spacing: -0.005em;
	color: var(--wm-ink, #1a1a1a);
	line-height: 1.25;
}

/* Who wrote, to whom and when: two quiet lines */
.email-meta {
	font-size: 13px;
	color: var(--wm-ink-mute, #8d99a6);
	display: flex;
	flex-direction: column;
	gap: 3px;
}

.email-meta .from-info strong {
	font-weight: 600;
	color: var(--wm-ink, #1a1a1a);
}

.email-meta .email-address {
	color: var(--wm-ink-mute, #8d99a6);
	font-weight: normal;
}

.meta-line {
	display: flex;
	flex-wrap: wrap;
	gap: 0 5px;
	font-size: 12.5px;
	color: var(--wm-ink-mute, #8d99a6);
}

/* The actions: Nora's reply as a pill, the others as round buttons */
.email-actions {
	display: flex;
	gap: 8px;
	flex: none;
	align-items: center;
	flex-wrap: wrap;
}

.email-actions .nora-reply {
	height: 36px;
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 0 14px 0 8px;
	border: 1px solid var(--wm-line, #e5e5e5);
	border-radius: 999px;
	background: var(--wm-bg-raised, #ffffff);
	color: var(--wm-ink, #1a1a1a);
	cursor: pointer;
	font-family: inherit;
	font-size: 13px;
	font-weight: 600;
	transition: border-color 0.15s, background 0.15s;
}

.email-actions .nora-reply:hover {
	border-color: var(--wm-accent);
	background: var(--wm-accent-soft);
}

.email-actions .nora-reply:disabled {
	opacity: 0.6;
	cursor: wait;
}

.email-actions .btn {
	width: 36px;
	height: 36px;
	display: inline-grid;
	place-items: center;
	padding: 0;
	border: 1px solid var(--wm-line, #e5e5e5);
	border-radius: 999px;
	background: var(--wm-bg-raised, #ffffff);
	color: var(--wm-ink-soft, #555);
	cursor: pointer;
	transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.email-actions .btn:hover {
	border-color: var(--wm-line-strong, #cfcfcf);
	color: var(--wm-ink, #1a1a1a);
}

.email-actions .btn.starred {
	color: var(--wm-amber, #b45309);
}

.email-actions .btn-danger:hover {
	border-color: var(--wm-danger, #dc2626);
	background: var(--wm-danger-soft, #fee2e2);
	color: var(--wm-danger, #dc2626);
}

/* The sender's card (board 7): their mark, what they are in Neoffice, the way to their record */
.sender-card {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-top: 12px;
	padding: 9px 12px;
	border: 1px solid var(--wm-line, #e5e5e5);
	border-radius: 12px;
	background: var(--wm-bg, #fafafa);
	font-size: 13.5px;
	color: var(--wm-ink, #1a1a1a);
}

.sender-mark {
	flex: none;
	width: 28px;
	height: 28px;
	display: grid;
	place-items: center;
	border: 1px solid var(--wm-line, #e5e5e5);
	border-radius: 999px;
	background: var(--wm-bg-raised, #ffffff);
	font-size: 11px;
	font-weight: 700;
	color: var(--wm-ink-soft, #555);
}

.sender-text {
	flex: 1;
	min-width: 0;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.sender-open {
	flex: none;
	border: 0;
	background: transparent;
	padding: 4px 6px;
	border-radius: 6px;
	font: inherit;
	font-size: 13px;
	font-weight: 600;
	color: var(--wm-accent);
	cursor: pointer;
}

.sender-open:hover {
	background: var(--wm-accent-soft);
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

/* Attachments footer, always visible at the bottom: an eyebrow, then a card each (canvas « Neodesk », boards 2 and 7) */
.email-attachments {
	flex: 0 0 auto;
	padding: 12px 18px 14px;
	border-top: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	background: var(--wm-bg, var(--subtle-bg, #f5f5f5));
	max-height: 196px;
	overflow-y: auto;
}

.attachments-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	cursor: pointer;
	margin-bottom: 10px;
}

.attachments-title {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 11px;
	line-height: 14px;
	font-weight: 600;
	letter-spacing: 0.1em;
	text-transform: uppercase;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
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
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	cursor: pointer;
	border-radius: 6px;
	transition: all 0.15s ease;
}

.toggle-btn:hover {
	background: var(--wm-bg-sunken, rgba(0, 0, 0, 0.05));
	color: var(--wm-ink, var(--text-color, #333));
}

.attachment-list {
	display: flex;
	flex-wrap: wrap;
	gap: 10px;
	align-items: stretch;
}

.attachment-item {
	display: flex;
	align-items: center;
	gap: 12px;
	flex: 1 1 240px;
	max-width: 340px;
	min-width: 0;
	padding: 10px 12px;
	background: var(--wm-bg-raised, var(--card-bg, white));
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 12px;
	cursor: pointer;
	transition: all 0.15s ease;
}

.attachment-item:hover,
.attachment-item.menu-open {
	border-color: var(--wm-accent);
}

.attachment-item.menu-open {
	background: var(--wm-accent-soft);
}

.attachment-item .file-glyph {
	display: inline-grid;
	place-items: center;
	flex: none;
	width: 34px;
	height: 34px;
	border-radius: 9px;
	background: var(--wm-bg-sunken, var(--bg-light-gray));
	color: var(--wm-accent);
}

.attachment-item .att-text {
	display: flex;
	flex-direction: column;
	gap: 1px;
	flex: 1;
	min-width: 0;
}

.attachment-item .name {
	font-size: 14px;
	line-height: 18px;
	font-weight: 600;
	color: var(--wm-ink, var(--text-color, #333));
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.attachment-item .meta {
	font-size: 12px;
	line-height: 15px;
	color: var(--wm-ink-mute, var(--text-muted, #8d99a6));
	white-space: nowrap;
}

/* ⋯ : the attachment's menu without a right-click (touch screens, keyboard) */
.attachment-more {
	display: inline-grid;
	place-items: center;
	flex: none;
	width: 26px;
	height: 26px;
	padding: 0;
	border: 0;
	border-radius: 7px;
	background: transparent;
	color: var(--wm-ink-mute, var(--text-muted));
	cursor: pointer;
	opacity: 0.55;
}

.attachment-item:hover .attachment-more,
.attachment-item:focus-within .attachment-more,
.attachment-item.menu-open .attachment-more {
	opacity: 1;
}

.attachment-more:hover {
	background: var(--wm-bg-sunken, var(--bg-light-gray));
	color: var(--wm-ink, var(--text-color));
}

.show-more-btn {
	display: inline-flex;
	align-items: center;
	align-self: center;
	padding: 6px 12px;
	background: transparent;
	color: var(--wm-ink-soft, var(--text-color));
	border: 1px solid var(--wm-line, var(--border-color, #e5e5e5));
	border-radius: 999px;
	font-size: 12px;
	font-weight: 600;
	cursor: pointer;
	transition: all 0.15s ease;
}

.show-more-btn:hover {
	border-color: var(--wm-accent);
	color: var(--wm-ink, var(--text-color));
}

.from-info {
	display: flex;
	align-items: center;
	gap: 6px;
	flex-wrap: wrap;
	font-size: 14px;
}

.contact-badge,
.add-contact-btn {
	display: inline-grid;
	place-items: center;
	width: 24px;
	height: 24px;
	padding: 0;
	border-radius: 7px;
}

.contact-badge {
	background: var(--wm-accent-soft);
	color: var(--wm-accent);
	cursor: help;
}

.add-contact-btn {
	background: none;
	border: 1px dashed var(--wm-line-strong, #ccc);
	cursor: pointer;
	color: var(--wm-ink-mute, #8d99a6);
	transition: all 0.15s ease;
}

.add-contact-btn:hover {
	background: var(--wm-accent-soft);
	border-color: var(--wm-accent);
	border-style: solid;
	color: var(--wm-accent);
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
	border-color: var(--wm-accent, var(--wm-accent));
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
	background: var(--wm-accent, var(--wm-accent));
	color: white;
	font-size: 12.5px;
	font-weight: 500;
	cursor: pointer;
	display: inline-flex;
	align-items: center;
	gap: 5px;
	box-shadow: 0 1px 2px rgba(214, 138, 89, 0.3);
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
