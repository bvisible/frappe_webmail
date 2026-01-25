<template>
	<div class="email-composer">
		<!-- Header with Send button -->
		<div class="composer-header">
			<div class="header-left">
				<button class="btn btn-light" @click="$emit('close')" :title="__('Close')">
					✕
				</button>
				<span class="composer-title">{{ __("New message") }}</span>
			</div>
			<div class="header-right">
				<button
					class="btn btn-secondary"
					@click="$refs.fileInput.click()"
					:title="__('Attach a file')"
				>
					📎
				</button>
				<button
					class="btn btn-secondary"
					@click="saveDraft"
					:disabled="isSavingDraft"
					:title="__('Save')"
				>
					💾
				</button>
				<button
					v-if="draftUid"
					class="btn btn-danger-light"
					@click="deleteDraft"
					:title="__('Delete draft')"
				>
					🗑️
				</button>
				<button class="btn btn-primary btn-send" @click="send" :disabled="sending">
					{{ sending ? __("Sending...") : "📤 " + __("Send") }}
				</button>
			</div>
			<input
				type="file"
				ref="fileInput"
				multiple
				@change="handleFiles"
				style="display: none"
			/>
		</div>

		<!-- Recipients -->
		<div class="composer-field">
			<label>{{ __("To:") }}</label>
			<ContactAutocomplete v-model="emailData.to" :placeholder="__('Add recipients...')" />
		</div>
		<div class="composer-field">
			<label>{{ __("Cc:") }}</label>
			<ContactAutocomplete v-model="emailData.cc" :placeholder="__('Carbon copy...')" />
		</div>
		<div class="composer-field">
			<label>{{ __("Subject:") }}</label>
			<input v-model="emailData.subject" type="text" :placeholder="__('Message subject')" />
		</div>

		<!-- Toolbar -->
		<div class="editor-toolbar" v-if="editor">
			<button
				@click="editor.chain().focus().toggleBold().run()"
				:class="{ active: editor.isActive('bold') }"
				:title="__('Bold')"
			>
				<strong>B</strong>
			</button>
			<button
				@click="editor.chain().focus().toggleItalic().run()"
				:class="{ active: editor.isActive('italic') }"
				:title="__('Italic')"
			>
				<em>I</em>
			</button>
			<button
				@click="editor.chain().focus().toggleUnderline().run()"
				:class="{ active: editor.isActive('underline') }"
				:title="__('Underline')"
			>
				<u>U</u>
			</button>
			<span class="separator"></span>
			<button
				@click="editor.chain().focus().toggleBulletList().run()"
				:class="{ active: editor.isActive('bulletList') }"
				:title="__('Bullet list')"
			>
				•
			</button>
			<button
				@click="editor.chain().focus().toggleOrderedList().run()"
				:class="{ active: editor.isActive('orderedList') }"
				:title="__('Numbered list')"
			>
				1.
			</button>
			<span class="separator"></span>
			<button @click="insertLink" :title="__('Link')">🔗</button>
			<button @click="insertImage" :title="__('Image')">🖼️</button>
			<span class="separator"></span>
			<button @click="insertSignature" :title="__('Signature')">✍️</button>
		</div>

		<!-- Editor -->
		<div class="editor-container">
			<editor-content :editor="editor" />
		</div>

		<!-- Attachments -->
		<div class="attachments-section" v-if="attachments.length">
			<div v-for="(file, idx) in attachments" :key="idx" class="attachment-chip">
				<span>{{ file.name }}</span>
				<span class="size">({{ formatSize(file.size) }})</span>
				<button @click="removeAttachment(idx)" class="remove">x</button>
			</div>
		</div>

		<!-- Footer with status -->
		<div class="composer-footer">
			<div class="draft-status" v-if="lastSaved || isSavingDraft">
				<span v-if="isSavingDraft" class="saving">{{ __("Saving...") }}</span>
				<span v-else-if="lastSaved" class="saved">
					✓ {{ __("Saved at {0}", [formatLastSaved()]) }}
				</span>
			</div>
		</div>
	</div>
</template>

<script>
import { Editor, EditorContent } from "@tiptap/vue-3";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Link from "@tiptap/extension-link";
import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import ContactAutocomplete from "./ContactAutocomplete.vue";

export default {
	name: "EmailComposer",
	components: { EditorContent, ContactAutocomplete },

	props: {
		account: { type: String, required: true },
		replyTo: { type: Object, default: null },
		forwardEmail: { type: Object, default: null },
		editDraft: { type: Object, default: null },
		signature: { type: String, default: "" },
		folder: { type: String, default: "INBOX" },
	},

	emits: ["sent", "close", "draft-deleted"],

	data() {
		return {
			editor: null,
			emailData: {
				to: "",
				cc: "",
				bcc: "",
				subject: "",
			},
			attachments: [],
			sending: false,
			isSavingDraft: false,
			draftUid: null,
			draftFolder: null,
		};
	},

	mounted() {
		this.initEditor();

		if (this.replyTo) {
			this.setupReply();
		} else if (this.forwardEmail) {
			this.setupForward();
		} else if (this.editDraft) {
			this.setupDraftEdit();
		}
	},

	beforeUnmount() {
		if (this.editor) {
			this.editor.destroy();
		}
	},

	methods: {
		initEditor() {
			let initialContent = "";

			if (this.signature) {
				initialContent = `<p></p><br><p>--</p>${this.signature}`;
			}

			this.editor = new Editor({
				content: initialContent,
				extensions: [
					StarterKit,
					Underline,
					Link.configure({ openOnClick: false }),
					Image.configure({ inline: true }),
					Placeholder.configure({
						placeholder: __("Write your message..."),
					}),
				],
			});
		},

		async saveDraftNow() {
			if (this.isSavingDraft || this.sending) return;

			// Don't save empty drafts
			const hasContent =
				this.emailData.to ||
				this.emailData.subject ||
				(this.editor && this.editor.getText().trim());

			if (!hasContent) return;

			this.isSavingDraft = true;

			try {
				await frappe.call({
					method: "frappe_webmail.api.save_draft_imap",
					args: {
						account_name: this.account,
						to: this.emailData.to,
						cc: this.emailData.cc,
						subject: this.emailData.subject,
						html_content: this.editor ? this.editor.getHTML() : "",
						draft_uid: this.draftUid,
						draft_folder: this.draftFolder,
					},
				});
				// Clear draft UID after saving (new draft created)
				this.draftUid = null;
				this.draftFolder = null;
			} catch (error) {
				console.error("Save draft failed:", error);
				frappe.toast({ message: __("Error saving draft"), indicator: "red" });
			} finally {
				this.isSavingDraft = false;
			}
		},

		setupReply() {
			const reply = this.replyTo;
			this.emailData.to = reply.from_email;
			this.emailData.subject = reply.subject.startsWith("Re:")
				? reply.subject
				: `Re: ${reply.subject}`;

			const date = new Date(reply.date).toLocaleString();
			const quoteContent = `
        <br><br>
        <p>${__("On {0}, {1} wrote:", [date, reply.from_name || reply.from_email])}</p>
        <blockquote style="border-left: 2px solid #ccc; padding-left: 10px; margin-left: 0; color: #666;">
          ${reply.html || reply.text || ""}
        </blockquote>
      `;

			let content = "<p></p>";
			if (this.signature) {
				content += `<br><p>--</p>${this.signature}`;
			}
			content += quoteContent;

			this.editor.commands.setContent(content);
			this.editor.commands.focus("start");
		},

		setupForward() {
			const fwd = this.forwardEmail;
			this.emailData.subject = fwd.subject.startsWith("Fwd:")
				? fwd.subject
				: `Fwd: ${fwd.subject}`;

			const date = new Date(fwd.date).toLocaleString();
			const forwardContent = `
        <br><br>
        <p>---------- ${__("Forwarded message")} ----------</p>
        <p>${__("From:")} ${fwd.from_name || fwd.from_email} &lt;${fwd.from_email}&gt;</p>
        <p>${__("Date:")} ${date}</p>
        <p>${__("Subject:")} ${fwd.subject}</p>
        <p>${__("To:")} ${fwd.to}</p>
        <br>
        ${fwd.html || fwd.text || ""}
      `;

			let content = "<p></p>";
			if (this.signature) {
				content += `<br><p>--</p>${this.signature}`;
			}
			content += forwardContent;

			this.editor.commands.setContent(content);
			this.editor.commands.focus("start");
		},

		setupDraftEdit() {
			const draft = this.editDraft;

			// Store the draft UID and folder for updating
			this.draftUid = draft.uid || null;
			this.draftFolder = draft.folder || this.folder;

			// Fill in the fields
			this.emailData.to = draft.to || "";
			this.emailData.cc = draft.cc || "";
			this.emailData.subject = draft.subject || "";

			// Set the body content
			const content = draft.html || draft.text || "";
			this.editor.commands.setContent(content);
			this.editor.commands.focus("end");
		},

		insertSignature() {
			if (this.signature) {
				this.editor.chain().focus().insertContent(`<br><p>--</p>${this.signature}`).run();
			}
		},

		insertLink() {
			const url = prompt(__("Link URL:"));
			if (url) {
				this.editor.chain().focus().setLink({ href: url }).run();
			}
		},

		insertImage() {
			const url = prompt(__("Image URL:"));
			if (url) {
				this.editor.chain().focus().setImage({ src: url }).run();
			}
		},

		handleFiles(event) {
			const files = Array.from(event.target.files);
			this.attachments.push(...files);
		},

		removeAttachment(index) {
			this.attachments.splice(index, 1);
		},

		formatSize(bytes) {
			if (bytes < 1024) return bytes + " B";
			if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
			return (bytes / (1024 * 1024)).toFixed(1) + " MB";
		},

		async prepareAttachments() {
			const result = [];
			for (const file of this.attachments) {
				const data = await this.fileToBase64(file);
				result.push({
					filename: file.name,
					content_type: file.type,
					data: data,
				});
			}
			return result;
		},

		fileToBase64(file) {
			return new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = () => {
					const base64 = reader.result.split(",")[1];
					resolve(base64);
				};
				reader.onerror = reject;
				reader.readAsDataURL(file);
			});
		},

		async send() {
			// Validate recipient
			if (!this.emailData.to || !this.emailData.to.trim()) {
				frappe.msgprint({
					title: __("Recipient required"),
					indicator: "red",
					message: __("Please enter at least one recipient."),
				});
				return;
			}

			// Validate body content
			const bodyText = this.editor ? this.editor.getText().trim() : "";
			if (!bodyText) {
				frappe.msgprint({
					title: __("Empty message"),
					indicator: "red",
					message: __("Please enter a message before sending."),
				});
				return;
			}

			// Warn if no subject
			if (!this.emailData.subject || !this.emailData.subject.trim()) {
				const confirmed = await new Promise((resolve) => {
					frappe.confirm(
						__("You have not entered a subject. Do you want to send anyway?"),
						() => resolve(true),
						() => resolve(false)
					);
				});
				if (!confirmed) return;
			}

			this.sending = true;

			try {
				const attachments = await this.prepareAttachments();

				await frappe.call({
					method: "frappe_webmail.api.send_email",
					args: {
						account_name: this.account,
						to: this.emailData.to,
						cc: this.emailData.cc || null,
						subject: this.emailData.subject,
						html_content: this.editor.getHTML(),
						reply_to_message_id: this.replyTo?.message_id || null,
						attachments: attachments.length ? JSON.stringify(attachments) : null,
					},
				});

				// Delete draft after successful send
				if (this.currentDraftId) {
					try {
						await frappe.call({
							method: "frappe_webmail.api.delete_draft",
							args: { draft_id: this.currentDraftId },
						});
					} catch (e) {
						console.warn("Failed to delete draft:", e);
					}
				}

				frappe.toast({ message: __("Email sent!"), indicator: "green" });
				this.isDirty = false; // Prevent save on unmount
				this.$emit("sent");
				this.$emit("close");
			} catch (error) {
				frappe.toast({
					message: error.message || __("Send error"),
					indicator: "red",
				});
			} finally {
				this.sending = false;
			}
		},

		async saveDraft() {
			await this.saveDraftNow();
			frappe.toast({
				message: __("Draft saved"),
				indicator: "blue",
			});
			// Close the composer after manual save
			this.$emit("close");
		},

		deleteDraft() {
			if (!this.draftUid || !this.draftFolder) return;

			frappe.confirm(__("Are you sure you want to delete this draft?"), async () => {
				try {
					await frappe.call({
						method: "frappe_webmail.api.delete_emails",
						args: {
							account_name: this.account,
							uids: JSON.stringify([this.draftUid]),
							folder: this.draftFolder,
							permanent: false,
						},
					});
					frappe.toast({ message: __("Draft deleted"), indicator: "green" });
					this.$emit("draft-deleted");
					this.$emit("close");
				} catch (error) {
					console.error("Delete draft failed:", error);
					frappe.toast({ message: __("Delete error"), indicator: "red" });
				}
			});
		},

		formatLastSaved() {
			if (!this.lastSaved) return "";
			return new Date(this.lastSaved).toLocaleTimeString("fr-FR");
		},
	},
};
</script>

<style scoped>
.email-composer {
	display: flex;
	flex-direction: column;
	height: 100%;
	background: white;
	border-radius: 8px;
}

.composer-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 12px 16px;
	background: var(--bg-light-gray, #f8f9fa);
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	border-radius: 8px 8px 0 0;
}

.header-left {
	display: flex;
	align-items: center;
	gap: 12px;
}

.header-left .btn-light {
	padding: 4px 8px;
	font-size: 16px;
	background: transparent;
	border: none;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
}

.header-left .btn-light:hover {
	color: var(--text-color, #333);
}

.composer-title {
	font-weight: 600;
	font-size: 15px;
	color: var(--text-color, #333);
}

.header-right {
	display: flex;
	align-items: center;
	gap: 8px;
}

.header-right .btn {
	padding: 8px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	cursor: pointer;
	font-size: 14px;
	background: white;
}

.header-right .btn:hover {
	background: var(--bg-gray, #eee);
}

.header-right .btn-send {
	background: var(--primary-color, #2490ef);
	color: white;
	border-color: var(--primary-color, #2490ef);
	padding: 8px 20px;
	font-weight: 500;
}

.header-right .btn-send:hover {
	background: #1a7fd4;
}

.header-right .btn-send:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}

.header-right .btn-danger-light {
	color: #dc3545;
	border-color: #dc3545;
}

.header-right .btn-danger-light:hover {
	background: #dc3545;
	color: white;
}

.composer-field {
	display: flex;
	align-items: center;
	padding: 10px 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	min-height: 44px;
}

.composer-field label {
	width: 50px;
	flex-shrink: 0;
	color: var(--text-muted, #8d99a6);
	font-size: 13px;
	margin-bottom: 0;
}

.composer-field input {
	flex: 1;
	border: none;
	outline: none;
	font-size: 14px;
	padding: 0;
	background: transparent;
}

.composer-field :deep(.contact-autocomplete) {
	flex: 1;
}

.composer-field :deep(.tags input) {
	font-size: 14px;
	padding: 0;
}

.editor-toolbar {
	display: flex;
	align-items: center;
	padding: 8px 16px;
	gap: 4px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	background: var(--bg-light-gray, #f5f5f5);
}

.editor-toolbar button {
	padding: 4px 8px;
	border: 1px solid transparent;
	border-radius: 4px;
	background: transparent;
	cursor: pointer;
	font-size: 14px;
}

.editor-toolbar button:hover {
	background: var(--bg-gray, #eee);
}

.editor-toolbar button.active {
	background: var(--primary-light, #e3f2fd);
	border-color: var(--primary-color, #2490ef);
}

.editor-toolbar .separator {
	width: 1px;
	height: 20px;
	background: var(--border-color, #e5e5e5);
	margin: 0 8px;
}

.editor-container {
	flex: 1;
	padding: 16px;
	overflow-y: auto;
}

.editor-container :deep(.ProseMirror) {
	min-height: 200px;
	outline: none;
}

.editor-container :deep(.ProseMirror p.is-editor-empty:first-child::before) {
	color: var(--text-muted, #8d99a6);
	content: attr(data-placeholder);
	float: left;
	height: 0;
	pointer-events: none;
}

.attachments-section {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	padding: 12px 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
}

.attachment-chip {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 4px 8px;
	background: var(--bg-light-gray, #f5f5f5);
	border-radius: 4px;
	font-size: 12px;
}

.attachment-chip .size {
	color: var(--text-muted, #8d99a6);
}

.attachment-chip .remove {
	border: none;
	background: none;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
	font-size: 16px;
	padding: 0 4px;
}

.attachment-chip .remove:hover {
	color: #e74c3c;
}

.composer-footer {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 8px 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
	background: var(--bg-light-gray, #f8f9fa);
	min-height: 40px;
}

.draft-status {
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
}

.draft-status .saving {
	color: var(--primary-color, #2490ef);
}

.draft-status .saved {
	color: var(--success-color, #28a745);
}

.footer-actions {
	display: flex;
	gap: 8px;
}

.btn-sm {
	padding: 4px 10px;
	font-size: 12px;
}

.btn-danger-light {
	background: white;
	color: #dc3545;
	border: 1px solid #dc3545;
	border-radius: 4px;
	cursor: pointer;
}

.btn-danger-light:hover {
	background: #dc3545;
	color: white;
}
</style>
