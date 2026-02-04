<template>
	<div class="signature-editor">
		<div class="signature-header">
			<h3>{{ __("Manage signatures") }}</h3>
			<button @click="$emit('close')" class="close-btn">
				<X :size="18" />
			</button>
		</div>

		<div class="signature-content">
			<!-- Signature List -->
			<div class="signature-list">
				<div class="list-header">
					<span>{{ __("My signatures") }}</span>
					<button @click="createNew" class="add-btn">
						<Plus :size="14" />
						<span>{{ __("New") }}</span>
					</button>
				</div>

				<div
					v-for="sig in signatures"
					:key="sig.name"
					class="signature-item"
					:class="{ selected: sig.name === selectedSignature?.name }"
					@click="selectSignature(sig)"
				>
					<span class="sig-name">{{ sig.signature_name }}</span>
					<span v-if="sig.is_default" class="default-badge">{{ __("Default") }}</span>
				</div>

				<div v-if="!signatures.length" class="empty-state">{{ __("No signature") }}</div>
			</div>

			<!-- Signature Form -->
			<div class="signature-form" v-if="editingSignature">
				<div class="form-field">
					<label>{{ __("Signature name") }}</label>
					<input v-model="editingSignature.signature_name" type="text" />
				</div>

				<div class="form-field">
					<label>
						<input type="checkbox" v-model="editingSignature.is_default" />
						{{ __("Default signature") }}
					</label>
				</div>

				<!-- Editor Toolbar -->
				<div class="editor-toolbar" v-if="editor">
					<button
						@click="editor.chain().focus().toggleBold().run()"
						:class="{ active: editor.isActive('bold') }"
						:title="__('Bold')"
					>
						<Bold :size="16" />
					</button>
					<button
						@click="editor.chain().focus().toggleItalic().run()"
						:class="{ active: editor.isActive('italic') }"
						:title="__('Italic')"
					>
						<Italic :size="16" />
					</button>
					<button
						@click="editor.chain().focus().toggleUnderline().run()"
						:class="{ active: editor.isActive('underline') }"
						:title="__('Underline')"
					>
						<UnderlineIcon :size="16" />
					</button>
					<button @click="insertLink" :title="__('Link')">
						<LinkIcon :size="16" />
					</button>
					<button @click="insertImage" :title="__('Image')">
						<ImageIcon :size="16" />
					</button>
				</div>

				<!-- Editor -->
				<div class="editor-container">
					<editor-content :editor="editor" />
				</div>

				<!-- Actions -->
				<div class="form-actions">
					<button @click="saveSignature" class="btn btn-primary" :disabled="saving">
						{{ saving ? __("Saving...") : __("Save") }}
					</button>
					<button
						v-if="editingSignature.name"
						@click="deleteSignature"
						class="btn btn-danger"
					>
						{{ __("Delete") }}
					</button>
					<button @click="cancelEdit" class="btn btn-light">{{ __("Cancel") }}</button>
				</div>
			</div>

			<div v-else class="no-selection">
				<p>{{ __("Select a signature or create a new one") }}</p>
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
import {
	X,
	Plus,
	Bold,
	Italic,
	Underline as UnderlineIcon,
	Link as LinkIcon,
	Image as ImageIcon,
} from "lucide-vue-next";

export default {
	name: "SignatureEditor",
	components: {
		EditorContent,
		X,
		Plus,
		Bold,
		Italic,
		UnderlineIcon,
		LinkIcon,
		ImageIcon,
	},

	emits: ["close", "updated"],

	data() {
		return {
			signatures: [],
			selectedSignature: null,
			editingSignature: null,
			editor: null,
			saving: false,
		};
	},

	mounted() {
		this.loadSignatures();
	},

	beforeUnmount() {
		if (this.editor) {
			this.editor.destroy();
		}
	},

	methods: {
		async loadSignatures() {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.api.get_signatures",
				});
				this.signatures = response.message || [];
			} catch (error) {
				frappe.toast({ message: this.__("Loading error"), indicator: "red" });
			}
		},

		selectSignature(sig) {
			this.selectedSignature = sig;
			this.editingSignature = { ...sig };
			this.initEditor(sig.content);
		},

		createNew() {
			this.selectedSignature = null;
			this.editingSignature = {
				signature_name: "",
				content: "",
				is_default: this.signatures.length === 0,
			};
			this.initEditor("");
		},

		initEditor(content) {
			if (this.editor) {
				this.editor.destroy();
			}

			this.editor = new Editor({
				content: content || "",
				extensions: [
					StarterKit,
					Underline,
					Link.configure({ openOnClick: false }),
					Image.configure({ inline: true }),
				],
			});
		},

		insertLink() {
			const url = prompt(this.__("Link URL:"));
			if (url) {
				this.editor.chain().focus().setLink({ href: url }).run();
			}
		},

		insertImage() {
			const url = prompt(this.__("Image URL:"));
			if (url) {
				this.editor.chain().focus().setImage({ src: url }).run();
			}
		},

		async saveSignature() {
			if (!this.editingSignature.signature_name) {
				frappe.toast({ message: this.__("Please enter a name"), indicator: "red" });
				return;
			}

			this.saving = true;

			try {
				const content = this.editor.getHTML();

				if (this.editingSignature.name) {
					// Update existing
					await frappe.call({
						method: "frappe.client.set_value",
						args: {
							doctype: "Email Signature",
							name: this.editingSignature.name,
							fieldname: {
								signature_name: this.editingSignature.signature_name,
								content: content,
								is_default: this.editingSignature.is_default ? 1 : 0,
							},
						},
					});
				} else {
					// Create new
					await frappe.call({
						method: "frappe.client.insert",
						args: {
							doc: {
								doctype: "Email Signature",
								signature_name: this.editingSignature.signature_name,
								content: content,
								is_default: this.editingSignature.is_default ? 1 : 0,
							},
						},
					});
				}

				frappe.toast({ message: this.__("Signature saved"), indicator: "green" });
				await this.loadSignatures();
				this.$emit("updated");
				this.cancelEdit();
			} catch (error) {
				frappe.toast({ message: this.__("Save error"), indicator: "red" });
			} finally {
				this.saving = false;
			}
		},

		async deleteSignature() {
			if (!this.editingSignature.name) return;

			if (!confirm(this.__("Are you sure you want to delete this signature?"))) return;

			try {
				await frappe.call({
					method: "frappe.client.delete",
					args: {
						doctype: "Email Signature",
						name: this.editingSignature.name,
					},
				});

				frappe.toast({ message: this.__("Signature deleted"), indicator: "green" });
				await this.loadSignatures();
				this.$emit("updated");
				this.cancelEdit();
			} catch (error) {
				frappe.toast({ message: this.__("Delete error"), indicator: "red" });
			}
		},

		cancelEdit() {
			this.editingSignature = null;
			this.selectedSignature = null;
			if (this.editor) {
				this.editor.destroy();
				this.editor = null;
			}
		},
	},
};
</script>

<style scoped>
.signature-editor {
	display: flex;
	flex-direction: column;
	height: 100%;
	background: var(--card-bg, white);
}

.signature-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.signature-header h3 {
	margin: 0;
	font-size: 16px;
}

.close-btn {
	background: none;
	border: none;
	font-size: 20px;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
}

.signature-content {
	display: flex;
	flex: 1;
	overflow: hidden;
}

.signature-list {
	width: 250px;
	border-right: 1px solid var(--border-color, #e5e5e5);
	display: flex;
	flex-direction: column;
}

.list-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 12px 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	font-weight: 600;
	font-size: 13px;
}

.add-btn {
	background: var(--primary-color, #2490ef);
	color: white;
	border: none;
	padding: 4px 8px;
	border-radius: 4px;
	cursor: pointer;
	font-size: 12px;
}

.signature-item {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 12px 16px;
	cursor: pointer;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.signature-item:hover {
	background: var(--bg-light-gray, #f5f5f5);
}

.signature-item.selected {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
}

.sig-name {
	font-size: 13px;
}

.default-badge {
	font-size: 11px;
	padding: 2px 6px;
	background: var(--success-color, #28a745);
	color: white;
	border-radius: 4px;
}

.empty-state {
	padding: 16px;
	color: var(--text-muted, #8d99a6);
	text-align: center;
}

.signature-form {
	flex: 1;
	display: flex;
	flex-direction: column;
	padding: 16px;
	overflow: hidden;
}

.form-field {
	margin-bottom: 16px;
}

.form-field label {
	display: block;
	margin-bottom: 4px;
	font-size: 13px;
	font-weight: 600;
}

.form-field input[type="text"] {
	width: 100%;
	padding: 8px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
}

.editor-toolbar {
	display: flex;
	gap: 4px;
	padding: 8px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-bottom: none;
	border-radius: 4px 4px 0 0;
	background: var(--bg-light-gray, #f5f5f5);
}

.editor-toolbar button {
	padding: 4px 8px;
	border: 1px solid transparent;
	border-radius: 4px;
	background: transparent;
	cursor: pointer;
}

.editor-toolbar button:hover {
	background: var(--bg-gray, #eee);
}

.editor-toolbar button.active {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.15));
	border-color: var(--primary-color, #2490ef);
}

.editor-container {
	flex: 1;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 0 0 4px 4px;
	padding: 12px;
	overflow-y: auto;
}

.editor-container :deep(.ProseMirror) {
	min-height: 150px;
	outline: none;
}

.form-actions {
	display: flex;
	gap: 8px;
	margin-top: 16px;
	padding-top: 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
}

.form-actions .btn {
	padding: 8px 16px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	cursor: pointer;
}

.form-actions .btn-primary {
	background: var(--primary-color, #2490ef);
	color: white;
	border-color: var(--primary-color, #2490ef);
}

.form-actions .btn-danger {
	background: var(--red-500, #e74c3c);
	color: white;
	border-color: var(--red-500, #e74c3c);
}

.form-actions .btn-light {
	background: var(--card-bg, white);
}

.no-selection {
	flex: 1;
	display: flex;
	align-items: center;
	justify-content: center;
	color: var(--text-muted, #8d99a6);
}
</style>
