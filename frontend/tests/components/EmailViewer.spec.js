/**
 * EmailViewer Component Tests
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import EmailViewer from "@/components/EmailViewer.vue";
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

		expect(wrapper.text()).toContain("Selectionnez un email");
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

		expect(wrapper.vm.formatSize(500)).toBe("500 B");
		expect(wrapper.vm.formatSize(1024)).toBe("1.0 KB");
		expect(wrapper.vm.formatSize(1048576)).toBe("1.0 MB");
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

	it("downloads attachment when clicked", async () => {
		const attachment = {
			id: "0",
			filename: "test.pdf",
			content_type: "application/pdf",
			size: 1024,
		};

		frappe.call.mockResolvedValue({
			message: {
				filename: "test.pdf",
				content_type: "application/pdf",
				data: "dGVzdA==", // base64 encoded "test"
				size: 4,
			},
		});

		// Mock URL and document methods
		const mockUrl = "blob:test";
		global.URL.createObjectURL = vi.fn(() => mockUrl);
		global.URL.revokeObjectURL = vi.fn();

		const wrapper = mount(EmailViewer, {
			props: {
				email: { ...mockEmail, attachments: [attachment] },
				account: "test@example.com",
			},
		});

		// Let the component build a real <a>; stub only the browser side effects
		// (object URL, the click) so Vue's own DOM work is never intercepted.
		const originalCreateObjectURL = URL.createObjectURL;
		const originalRevokeObjectURL = URL.revokeObjectURL;
		URL.createObjectURL = vi.fn(() => "blob:mock");
		URL.revokeObjectURL = vi.fn();
		const clickSpy = vi
			.spyOn(HTMLAnchorElement.prototype, "click")
			.mockImplementation(() => {});
		try {
			await wrapper.vm.downloadAttachment(attachment);
			await flushPromises();
			expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
			expect(clickSpy).toHaveBeenCalledTimes(1);
		} finally {
			clickSpy.mockRestore();
			URL.createObjectURL = originalCreateObjectURL;
			URL.revokeObjectURL = originalRevokeObjectURL;
		}

		expect(frappe.call).toHaveBeenCalledWith({
			method: "frappe_webmail.api.get_attachment",
			args: expect.objectContaining({
				attachment_id: "0",
			}),
		});
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
});
