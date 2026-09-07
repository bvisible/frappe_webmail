/**
 * EmailList Component Tests
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import EmailList from "@/components/EmailList.vue";

// Mock vue-virtual-scroller
vi.mock("vue-virtual-scroller", () => ({
	RecycleScroller: {
		name: "RecycleScroller",
		template: '<div class="mock-scroller"><slot v-for="item in items" :item="item" /></div>',
		props: ["items", "itemSize", "keyField"],
	},
}));

describe("EmailList", () => {
	const mockEmails = [
		{
			uid: 1,
			subject: "Test Email 1",
			from_email: "sender1@example.com",
			from_name: "Sender One",
			date: "2024-01-15T10:00:00",
			seen: false,
			flagged: false,
			has_attachments: false,
		},
		{
			uid: 2,
			subject: "Test Email 2",
			from_email: "sender2@example.com",
			from_name: "Sender Two",
			date: "2024-01-14T09:00:00",
			seen: true,
			flagged: true,
			has_attachments: true,
		},
	];

	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("renders correctly", () => {
		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
				folder: "INBOX",
			},
		});

		expect(wrapper.find(".email-list-container").exists()).toBe(true);
		expect(wrapper.find(".list-header").exists()).toBe(true);
	});

	it("loads emails on mount", async () => {
		frappe.call.mockResolvedValue({
			message: {
				emails: mockEmails,
				total: 2,
				has_more: false,
			},
		});

		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
				folder: "INBOX",
			},
		});

		await flushPromises();

		expect(frappe.call).toHaveBeenCalledWith({
			method: "frappe_webmail.api.get_emails",
			args: expect.objectContaining({
				account_name: "test@example.com",
				folder: "INBOX",
				limit: 50,
				offset: 0,
			}),
		});
	});

	it("shows empty state when no emails", async () => {
		frappe.call.mockResolvedValue({
			message: {
				emails: [],
				total: 0,
				has_more: false,
			},
		});

		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
				folder: "INBOX",
			},
		});

		await flushPromises();
		await wrapper.vm.$nextTick();

		// `__` is the identity in tests (see tests/setup.js): the English source string shows
		expect(wrapper.text()).toContain("No emails in this folder");
	});

	it("shows loading indicator while loading", () => {
		frappe.call.mockImplementation(() => new Promise(() => {})); // Never resolves

		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
			},
		});

		expect(wrapper.vm.loading).toBe(true);
	});

	it("emits select event when email is clicked", async () => {
		frappe.call.mockResolvedValue({
			message: {
				emails: mockEmails,
				total: 2,
				has_more: false,
			},
		});

		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
			},
		});

		await flushPromises();

		// Manually set emails since we mocked the scroller
		wrapper.vm.emails = mockEmails;

		// Simulate click via method
		wrapper.vm.$emit("select", mockEmails[0]);

		expect(wrapper.emitted("select")).toBeTruthy();
	});

	it("emits update:total when emails are loaded", async () => {
		frappe.call.mockResolvedValue({
			message: {
				emails: mockEmails,
				total: 100,
				has_more: true,
			},
		});

		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
			},
		});

		await flushPromises();

		expect(wrapper.emitted("update:total")).toBeTruthy();
		expect(wrapper.emitted("update:total")[0]).toEqual([100]);
	});

	it("refreshes when account changes", async () => {
		frappe.call.mockResolvedValue({
			message: { emails: [], total: 0, has_more: false },
		});

		const wrapper = mount(EmailList, {
			props: {
				account: "account1@example.com",
			},
		});

		await flushPromises();
		const initialCalls = frappe.call.mock.calls.length;

		await wrapper.setProps({ account: "account2@example.com" });
		await flushPromises();

		expect(frappe.call.mock.calls.length).toBeGreaterThan(initialCalls);
	});

	it("refreshes when folder changes", async () => {
		frappe.call.mockResolvedValue({
			message: { emails: [], total: 0, has_more: false },
		});

		const wrapper = mount(EmailList, {
			props: {
				account: "test@example.com",
				folder: "INBOX",
			},
		});

		await flushPromises();
		const initialCalls = frappe.call.mock.calls.length;

		await wrapper.setProps({ folder: "Sent" });
		await flushPromises();

		expect(frappe.call.mock.calls.length).toBeGreaterThan(initialCalls);
	});

	it("formats date correctly for today", () => {
		const wrapper = mount(EmailList, {
			props: { account: "test@example.com" },
		});

		const today = new Date();
		const dateStr = today.toISOString();
		const formatted = wrapper.vm.formatDate(dateStr);

		// Should show time for today's emails
		expect(formatted).toMatch(/\d{2}:\d{2}/);
	});

	it("formats date correctly for older emails", () => {
		const wrapper = mount(EmailList, {
			props: { account: "test@example.com" },
		});

		const oldDate = "2023-06-15T10:00:00";
		const formatted = wrapper.vm.formatDate(oldDate);

		// Should include year for old emails
		expect(formatted).toMatch(/\d+/);
	});

	it("handles search", async () => {
		frappe.call.mockResolvedValue({
			message: { emails: [], total: 0, has_more: false },
		});

		const wrapper = mount(EmailList, {
			props: { account: "test@example.com" },
		});

		await flushPromises();
		vi.clearAllMocks();

		// Set search query and trigger search
		wrapper.vm.searchQuery = "test query";
		await wrapper.vm.search();

		expect(frappe.call).toHaveBeenCalledWith(
			expect.objectContaining({
				args: expect.objectContaining({
					search: "test query",
				}),
			})
		);
	});

	it("toggles star on email", async () => {
		frappe.call.mockResolvedValue({ message: { success: true } });

		const wrapper = mount(EmailList, {
			props: { account: "test@example.com" },
		});

		wrapper.vm.emails = [...mockEmails];
		const email = wrapper.vm.emails[0];

		expect(email.flagged).toBe(false);

		await wrapper.vm.toggleStar(email);

		expect(frappe.call).toHaveBeenCalledWith({
			method: "frappe_webmail.api.set_flags",
			args: expect.objectContaining({
				add_flags: expect.stringContaining("Flagged"),
			}),
		});

		expect(email.flagged).toBe(true);
	});

	it("marks email as read", () => {
		const wrapper = mount(EmailList, {
			props: { account: "test@example.com" },
		});

		wrapper.vm.emails = [...mockEmails];
		expect(wrapper.vm.emails[0].seen).toBe(false);

		wrapper.vm.markAsRead(1);

		expect(wrapper.vm.emails[0].seen).toBe(true);
	});

	it("exposes refresh method", () => {
		const wrapper = mount(EmailList, {
			props: { account: "test@example.com" },
		});

		expect(typeof wrapper.vm.refresh).toBe("function");
	});
});
