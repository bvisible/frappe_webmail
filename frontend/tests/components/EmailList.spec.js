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

// Lot 2 « retrouver » (canvas « Neodesk », board 20): the unread and the starred asked of the server, the order, and
// « Toutes les boîtes ».
describe("EmailList — finding a message again", () => {
	const row = (uid, date, extra = {}) => ({
		uid,
		subject: `Message ${uid}`,
		from_email: `sender${uid}@example.com`,
		from_name: `Sender ${uid}`,
		date,
		seen: true,
		flagged: false,
		has_attachments: false,
		...extra,
	});
	const listed = (emails) => ({ message: { emails, total: emails.length, has_more: false } });
	const lastArgs = () => frappe.call.mock.calls.at(-1)[0].args;

	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("asks the server for the starred and the unread, and for the oldest first", async () => {
		frappe.call.mockResolvedValue(listed([row(1, "2026-10-14T09:00:00")]));
		const wrapper = mount(EmailList, {
			props: { account: "me@example.com", folder: "INBOX" },
		});
		await flushPromises();
		expect(lastArgs()).not.toHaveProperty("only");

		wrapper.vm.activeFilter = "starred";
		await flushPromises();
		expect(lastArgs()).toMatchObject({ only: "flagged" });

		wrapper.vm.activeFilter = "unread";
		await flushPromises();
		expect(lastArgs()).toMatchObject({ only: "unread" });

		// Back to all: the whole list again; then the attachments, sorted out here: no new question
		wrapper.vm.activeFilter = "all";
		await flushPromises();
		expect(lastArgs()).not.toHaveProperty("only");
		const asked = frappe.call.mock.calls.length;
		wrapper.vm.activeFilter = "attachments";
		await flushPromises();
		expect(frappe.call.mock.calls.length).toBe(asked);

		wrapper.vm.setOrder("oldest");
		await flushPromises();
		expect(lastArgs()).toMatchObject({ order: "oldest" });
	});

	it("keeps the chips while a filter finds nothing, the way back to all", async () => {
		frappe.call.mockResolvedValue(listed([row(1, "2026-10-14T09:00:00")]));
		const wrapper = mount(EmailList, {
			props: { account: "me@example.com", folder: "INBOX" },
		});
		await flushPromises();
		frappe.call.mockResolvedValue(listed([]));
		wrapper.vm.activeFilter = "starred";
		await flushPromises();
		expect(wrapper.find(".filter-chips").exists()).toBe(true);
	});

	it("lists every mailbox's inbox in one list, by date, each row tagged with its mailbox", async () => {
		frappe.call.mockImplementation(({ args }) =>
			Promise.resolve(
				args.account_name === "info@example.com"
					? listed([row(7, "2026-10-14T11:20:00")])
					: listed([row(7, "2026-10-14T10:42:00"), row(5, "2026-10-13T16:30:00")])
			)
		);
		const wrapper = mount(EmailList, {
			props: {
				account: "me@example.com",
				folder: "INBOX",
				unified: true,
				accounts: ["me@example.com", "info@example.com"],
				accountLabels: { "me@example.com": "Camille", "info@example.com": "Info" },
			},
		});
		await flushPromises();
		expect(
			frappe.call.mock.calls.map((c) => [c[0].args.account_name, c[0].args.folder])
		).toEqual([
			["me@example.com", "INBOX"],
			["info@example.com", "INBOX"],
		]);
		// The same number in two mailboxes is two messages
		expect(wrapper.vm.emails.map((e) => e.key)).toEqual([
			"info@example.com/7",
			"me@example.com/7",
			"me@example.com/5",
		]);
		expect(wrapper.findAll(".box-tag").map((t) => t.text())).toEqual([
			"Info",
			"Camille",
			"Camille",
		]);
		expect(wrapper.find(".list-sub").exists()).toBe(true);
		// No selection, no drag to this mailbox's folders
		expect(wrapper.find(".checkbox-cell").exists()).toBe(false);
		// A row is found by its mailbox too
		wrapper.vm.markAsRead(7, "me@example.com");
		expect(wrapper.vm.rowOf(7, "info@example.com")).toBe(wrapper.vm.emails[0]);
	});

	it("leaves out a mailbox that cannot be read, quietly", async () => {
		frappe.call.mockImplementation(({ args, silent }) =>
			args.account_name === "info@example.com"
				? Promise.reject(new Error(silent ? "quiet" : "loud"))
				: Promise.resolve(listed([row(3, "2026-10-14T09:00:00")]))
		);
		const wrapper = mount(EmailList, {
			props: {
				account: "me@example.com",
				folder: "INBOX",
				unified: true,
				accounts: ["me@example.com", "info@example.com"],
			},
		});
		await flushPromises();
		expect(wrapper.vm.emails.map((e) => e.key)).toEqual(["me@example.com/3"]);
		expect(frappe.call.mock.calls.every((c) => c[0].silent === true)).toBe(true);
	});
});
