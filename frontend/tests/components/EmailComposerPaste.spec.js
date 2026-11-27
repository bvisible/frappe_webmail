/**
 * EmailComposer — a picture pasted in a new message goes in its text (pastedImages.js): a screenshot, a picture copied
 * in a viewer or the Finder. A text copied with a picture of itself (Word) stays text, and a picture too large is said.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import EmailComposer from "@/components/EmailComposer.vue";

// The 8 bytes a PNG starts with: enough for the editor, which never decodes it
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function composer() {
	return mount(EmailComposer, {
		props: { account: "box@example.org", noraEnabled: false },
		global: { stubs: { ContactAutocomplete: true, AttachmentPicker: true, NoraBar: true } },
		attachTo: document.body,
	});
}

function clipboard({ files = [], html = "", text = "" }) {
	return { files, getData: (type) => ({ "text/html": html, "text/plain": text }[type] || "") };
}

function paste(wrapper, data) {
	const editor = wrapper.vm.editor;
	const event = { clipboardData: clipboard(data), preventDefault: vi.fn() };
	return editor.options.editorProps.handlePaste(editor.view, event, null);
}

const shot = (name = "Capture d’écran.png", bytes = PNG) =>
	new File([bytes], name, { type: "image/png" });

describe("EmailComposer: a pasted picture", () => {
	beforeEach(() => {
		frappe.toast.mockClear();
	});

	it("puts a screenshot in the text", async () => {
		const wrapper = composer();
		expect(paste(wrapper, { files: [shot()] })).toBe(true);
		await vi.waitFor(() =>
			expect(wrapper.vm.editor.getHTML()).toContain('src="data:image/png;base64,')
		);
		wrapper.unmount();
	});

	it("puts a picture copied in the Finder in the text, its name being all the plain text", async () => {
		const wrapper = composer();
		expect(paste(wrapper, { files: [shot("photo.png")], text: "photo.png" })).toBe(true);
		await vi.waitFor(() => expect(wrapper.vm.editor.getHTML()).toContain("data:image/png"));
		wrapper.unmount();
	});

	it("leaves a text copied with a picture of itself to the editor", () => {
		const wrapper = composer();
		const word = {
			files: [shot("image.png")],
			html: "<p>Offre du 12 mars</p>",
			text: "Offre du 12 mars",
		};
		expect(paste(wrapper, word)).toBe(false);
		expect(paste(wrapper, { files: [], text: "just text" })).toBe(false);
		wrapper.unmount();
	});

	it("says a picture is too large instead of putting it in", async () => {
		const wrapper = composer();
		const big = shot("big.png", new Uint8Array(5 * 1024 * 1024 + 1));
		expect(paste(wrapper, { files: [big] })).toBe(true);
		await vi.waitFor(() => expect(frappe.toast).toHaveBeenCalled());
		expect(wrapper.vm.editor.getHTML()).not.toContain("data:image");
		wrapper.unmount();
	});

	it("keeps a picture of a draft taken back", () => {
		const wrapper = composer();
		wrapper.vm.editor.commands.setContent(
			'<p>Voici <img src="data:image/png;base64,iVBORw0KGgo="></p>'
		);
		expect(wrapper.vm.editor.getHTML()).toContain('src="data:image/png;base64,iVBORw0KGgo="');
		wrapper.unmount();
	});
});
