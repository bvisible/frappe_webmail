/**
 * EmailViewer Component Tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import EmailViewer from "@/components/EmailViewer.vue";
import { resetAttachmentActions } from "@/attachmentActions.js";
import { Archive, File, FileText, Film, Image, Music } from "lucide-vue-next";

// Mock DOMPurify
vi.mock("dompurify", () => ({
	default: {
		sanitize: (html, config) => {
			// Simple mock that strips script tags
			return html.replace(/<script[^>]*>.*?<\/script>/gi, "");
		},
		addHook: vi.fn(),
		removeHook: vi.fn(),
	},
}));

describe("EmailViewer", () => {
	const mockEmail = {
		uid: 1,
		message_id: "<test123@example.com>",
		subject: "Test Subject",
		from_email: "sender@example.com",
		from_name: "Sender Name",
		to: "recipient@example.com",
		cc: "cc@example.com",
		date: "2024-01-15T10:30:00",
		html: "<p>Test email content</p>",
		text: "Test email content",
		attachments: [],
		seen: true,
		flagged: false,
	};

	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("renders empty state when no email", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: null,
				account: "test@example.com",
			},
		});

		expect(wrapper.text()).toContain("Select an e-mail to read it");
	});

	it("renders email content when email provided", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		expect(wrapper.find(".email-subject").text()).toBe("Test Subject");
		expect(wrapper.text()).toContain("Sender Name");
		expect(wrapper.text()).toContain("sender@example.com");
	});

	it("displays recipient information", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		expect(wrapper.text()).toContain("recipient@example.com");
		expect(wrapper.text()).toContain("cc@example.com");
	});

	it("renders email in sandboxed iframe", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		const iframe = wrapper.find("iframe");
		expect(iframe.exists()).toBe(true);
		expect(iframe.attributes("sandbox")).toContain("allow-popups");
		expect(iframe.attributes("referrerpolicy")).toBe("no-referrer");
	});

	it("sanitizes HTML content", () => {
		const emailWithScript = {
			...mockEmail,
			html: '<p>Safe content</p><script>alert("xss")</script>',
		};

		const wrapper = mount(EmailViewer, {
			props: {
				email: emailWithScript,
				account: "test@example.com",
			},
		});

		const srcdoc = wrapper.find("iframe").attributes("srcdoc");
		expect(srcdoc).not.toContain("<script>");
		expect(srcdoc).toContain("Safe content");
	});

	it("shows attachments section when email has attachments", () => {
		const emailWithAttachments = {
			...mockEmail,
			attachments: [
				{
					id: "0",
					filename: "document.pdf",
					content_type: "application/pdf",
					size: 10240,
				},
			],
		};

		const wrapper = mount(EmailViewer, {
			props: {
				email: emailWithAttachments,
				account: "test@example.com",
			},
		});

		expect(wrapper.find(".email-attachments").exists()).toBe(true);
		expect(wrapper.text()).toContain("document.pdf");
	});

	it("does not show attachments section when no attachments", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		expect(wrapper.find(".email-attachments").exists()).toBe(false);
	});

	it("emits reply event when reply button clicked", async () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		await wrapper.findAll(".email-actions .btn").at(0).trigger("click");

		expect(wrapper.emitted("reply")).toBeTruthy();
		expect(wrapper.emitted("reply")[0][0]).toEqual(mockEmail);
	});

	it("emits forward event when forward button clicked", async () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		await wrapper.findAll(".email-actions .btn").at(1).trigger("click");

		expect(wrapper.emitted("forward")).toBeTruthy();
	});

	it("emits delete event when delete button clicked", async () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		await wrapper.find(".email-actions .btn-danger").trigger("click");

		expect(wrapper.emitted("delete")).toBeTruthy();
	});

	it("toggles star and emits flag-changed event", async () => {
		frappe.call.mockResolvedValue({ message: { success: true } });

		const wrapper = mount(EmailViewer, {
			props: {
				email: { ...mockEmail, flagged: false },
				account: "test@example.com",
			},
		});

		await wrapper.vm.toggleStar();
		await flushPromises();

		expect(frappe.call).toHaveBeenCalledWith({
			method: "frappe_webmail.api.set_flags",
			args: expect.objectContaining({
				add_flags: expect.stringContaining("Flagged"),
			}),
		});

		expect(wrapper.emitted("flag-changed")).toBeTruthy();
	});

	it("formats date correctly", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		const formatted = wrapper.vm.formatDate("2024-01-15T10:30:00");
		expect(formatted).toBeTruthy();
		// Should be a readable date format
		expect(formatted.length).toBeGreaterThan(5);
	});

	it("formats file size correctly", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		// Intl writes a no-break space between the number and the unit
		const size = (bytes) => wrapper.vm.formatSize(bytes).replace(/\s/g, " ");
		expect(size(500)).toBe("500 byte");
		expect(size(1024)).toBe("1 kB");
		expect(size(1536)).toBe("1.5 kB");
		expect(size(1048576)).toBe("1 MB");
	});

	it("writes a size and an attachment's kind in the reader's language", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});
		frappe.boot.lang = "fr";
		try {
			const plain = (text) => text.replace(/\s/g, " ");
			expect(plain(wrapper.vm.formatSize(188416))).toBe("184 ko");
			expect(plain(wrapper.vm.formatSize(1258291))).toBe("1,2 Mo");
			expect(
				plain(
					wrapper.vm.attachmentMeta({ filename: "Facture-2026-118.pdf", size: 188416 })
				)
			).toBe("PDF · 184 ko");
			// No extension: the size alone
			expect(plain(wrapper.vm.attachmentMeta({ filename: "README", size: 500 }))).toBe(
				"500 o"
			);
		} finally {
			delete frappe.boot.lang;
		}
	});

	it("returns correct file icons", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		// Icons are Lucide components since the redesign (no more emoji)
		expect(wrapper.vm.getFileIcon("application/pdf")).toBe(FileText);
		expect(wrapper.vm.getFileIcon("image/png")).toBe(Image);
		expect(wrapper.vm.getFileIcon("video/mp4")).toBe(Film);
		expect(wrapper.vm.getFileIcon("audio/mpeg")).toBe(Music);
		expect(wrapper.vm.getFileIcon("application/zip")).toBe(Archive);
		expect(wrapper.vm.getFileIcon("text/plain")).toBe(File);
	});

	it("saves an attachment from the server's stream, not from base64 in JSON", async () => {
		const attachment = {
			id: "0",
			filename: "test.pdf",
			content_type: "application/pdf",
			size: 1024,
		};
		const wrapper = mount(EmailViewer, {
			props: {
				email: { ...mockEmail, attachments: [attachment] },
				account: "test@example.com",
				folder: "INBOX",
			},
		});
		let href = null;
		const clickSpy = vi
			.spyOn(HTMLAnchorElement.prototype, "click")
			.mockImplementation(function () {
				href = this.getAttribute("href");
			});
		try {
			wrapper.vm.downloadAttachment(attachment);
			expect(clickSpy).toHaveBeenCalledTimes(1);
		} finally {
			clickSpy.mockRestore();
		}
		const url = new URL(href, "http://site.test");
		expect(url.pathname).toBe("/api/method/frappe_webmail.attachments.download_attachment");
		expect(Object.fromEntries(url.searchParams)).toEqual({
			account_name: "test@example.com",
			folder: "INBOX",
			uid: "1",
			attachment_id: "0",
			inline: "0",
		});
		expect(frappe.call).not.toHaveBeenCalledWith(
			expect.objectContaining({ method: "frappe_webmail.api.get_attachment" })
		);
	});

	it("wraps plain text emails correctly", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		const result = wrapper.vm.wrapPlainText("Line 1\nLine 2");
		expect(result).toContain("<br>");
		expect(result).toContain("Line 1");
		expect(result).toContain("Line 2");
	});

	it("escapes HTML in plain text", () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		const result = wrapper.vm.wrapPlainText('<script>alert("xss")</script>');
		expect(result).not.toContain("<script>");
		expect(result).toContain("&lt;script&gt;");
	});

	it("resets state when email changes", async () => {
		const wrapper = mount(EmailViewer, {
			props: {
				email: mockEmail,
				account: "test@example.com",
			},
		});

		// Set some state
		wrapper.vm.showExternalImages = true;
		wrapper.vm.hasBlockedImages = true;

		// Change email
		await wrapper.setProps({
			email: { ...mockEmail, uid: 2, subject: "Different Email" },
		});

		// State should be reset
		expect(wrapper.vm.showExternalImages).toBe(false);
		expect(wrapper.vm.hasBlockedImages).toBe(false);
	});

	describe("the attachment's menu (described by the server)", () => {
		const attachment = {
			id: "0",
			filename: "Facture.pdf",
			content_type: "application/pdf",
			size: 1024,
		};
		const actions = [
			{ key: "preview", label: "Preview", icon: "eye", kind: "client", group: "view" },
			{
				key: "document_scan",
				label: "Create a scanned document",
				icon: "scan-line",
				kind: "now",
				group: "neoffice",
				method: "m.scan",
			},
			{
				key: "save_to_drive",
				label: "Save to the Drive…",
				icon: "cloud-upload",
				kind: "pick_folder",
				group: "neoffice",
				method: "m.drive",
			},
		];
		const mountWith = () =>
			mount(EmailViewer, {
				props: {
					email: { ...mockEmail, attachments: [attachment] },
					account: "me@example.com",
					folder: "INBOX",
				},
			});

		beforeEach(() => {
			resetAttachmentActions();
			frappe.call.mockImplementation(async ({ method }) =>
				method === "frappe_webmail.attachments.get_attachment_actions"
					? { message: actions }
					: {
							message: {
								message: "Sent to the scanned documents",
								url: "/app/document-scan/S-1",
							},
					  }
			);
			frappe.show_alert = vi.fn();
			frappe.utils = { escape_html: (text) => String(text) };
		});

		afterEach(() => {
			frappe.call.mockReset();
			frappe.call.mockResolvedValue({ message: {} });
		});

		it("opens on a right-click with the server's entries", async () => {
			const wrapper = mountWith();
			await flushPromises();
			await wrapper
				.find(".attachment-item")
				.trigger("contextmenu", { clientX: 10, clientY: 20 });
			expect(wrapper.vm.attachmentMenu.visible).toBe(true);
			expect(wrapper.vm.attachmentMenu.position).toEqual({ x: 10, y: 20 });
			expect(
				wrapper.vm.attachmentMenuItems.filter((i) => !i.separator).map((i) => i.id)
			).toEqual(["preview", "document_scan", "save_to_drive"]);
		});

		it("runs an action at once on the attachment the menu was opened for, and says what the server said", async () => {
			const wrapper = mountWith();
			await flushPromises();
			wrapper.vm.openAttachmentMenu(
				{ type: "contextmenu", clientX: 1, clientY: 1 },
				attachment
			);
			wrapper.vm.onAttachmentAction({ action: actions[1] });
			await flushPromises();
			expect(frappe.call).toHaveBeenCalledWith({
				method: "m.scan",
				args: {
					account_name: "me@example.com",
					folder: "INBOX",
					uid: 1,
					attachment_id: "0",
				},
			});
			expect(frappe.show_alert.mock.calls[0][0].message).toContain(
				"Sent to the scanned documents"
			);
			expect(frappe.show_alert.mock.calls[0][0].message).toContain(
				'href="/app/document-scan/S-1"'
			);
		});

		it("asks for a Drive folder before saving there", async () => {
			const wrapper = mountWith();
			await flushPromises();
			wrapper.vm.openAttachmentMenu(
				{ type: "contextmenu", clientX: 1, clientY: 1 },
				attachment
			);
			wrapper.vm.onAttachmentAction({ action: actions[2] });
			expect(wrapper.vm.picker.kind).toBe("pick_folder");
			expect(frappe.call).not.toHaveBeenCalledWith(
				expect.objectContaining({ method: "m.drive" })
			);
			await wrapper.vm.runAttachmentAction(actions[2], attachment, { drive_folder: "f-42" });
			expect(frappe.call).toHaveBeenCalledWith({
				method: "m.drive",
				args: {
					account_name: "me@example.com",
					folder: "INBOX",
					uid: 1,
					attachment_id: "0",
					drive_folder: "f-42",
				},
			});
			expect(wrapper.vm.picker.kind).toBe(null);
		});
	});
});
