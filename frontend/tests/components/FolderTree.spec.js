/**
 * FolderTree — the folders lent to the desk's cockpit (Neodesk plan W1).
 *
 * Headless, the tree draws no list (the cockpit does): it keeps the folders, their roles, their unread mail, their
 * menu and their dialogs, and tells the page what the cockpit should draw (`nav-changed`).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import FolderTree from "@/components/FolderTree.vue";

const FOLDERS = [
	{ name: "INBOX", delimiter: "/", flags: [], selectable: true },
	{ name: "Sent", delimiter: "/", flags: ["\\Sent"], selectable: true },
	{ name: "Brouillons", delimiter: "/", flags: ["\\Drafts"], selectable: true },
	{ name: "Clients", delimiter: "/", flags: [], selectable: true },
	{ name: "Clients/2026", delimiter: "/", flags: [], selectable: true },
	{ name: "Junk", delimiter: "/", flags: ["\\Junk"], selectable: true },
];

const answer = (method) => {
	if (method.endsWith("get_folders")) return { message: FOLDERS };
	if (method.endsWith("get_folder_counts")) {
		return {
			message: {
				INBOX: { unseen: 12, messages: 40 },
				"Clients/2026": { unseen: 2, messages: 9 },
			},
		};
	}
	if (method.endsWith("get_folder_mapping"))
		return { message: { effective: { inbox: "INBOX" } } };
	return { message: {} };
};

describe("FolderTree, headless", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		frappe.call.mockImplementation(async ({ method }) => answer(method));
	});

	it("draws no list, and tells the page the folders with their role, icon, depth and unread mail", async () => {
		const wrapper = mount(FolderTree, {
			props: { account: "me@example.com", headless: true },
		});
		await flushPromises();
		await flushPromises();

		expect(wrapper.find(".folder-list").exists()).toBe(false);
		expect(wrapper.find(".folder-header").exists()).toBe(false);

		const told = wrapper.emitted("nav-changed");
		expect(told).toBeTruthy();
		const items = told[told.length - 1][0];
		const by = Object.fromEntries(items.map((f) => [f.name, f]));
		expect(by.INBOX).toMatchObject({
			role: "inbox",
			icon: "lucide-inbox",
			depth: 0,
			unread: 12,
		});
		expect(by.Sent).toMatchObject({ role: "sent", icon: "lucide-send" });
		// Its role from its flag; its name its own, as the tree shows it (only the mapping's folders are renamed)
		expect(by.Brouillons).toMatchObject({
			role: "drafts",
			icon: "lucide-file-pen",
			label: "Brouillons",
		});
		expect(by.Junk).toMatchObject({ role: "spam", icon: "lucide-shield-alert" });
		expect(by.Clients).toMatchObject({
			role: null,
			icon: "lucide-folder",
			depth: 0,
			unread: 0,
		});
		expect(by["Clients/2026"]).toMatchObject({ depth: 1, unread: 2, label: "2026" });
	});

	it("keeps its menu: a folder's right-click from the cockpit opens it at the pointer", async () => {
		const wrapper = mount(FolderTree, {
			props: { account: "me@example.com", headless: true },
		});
		await flushPromises();
		wrapper.vm.showContextMenu({ clientX: 40, clientY: 300 }, FOLDERS[3]);
		expect(wrapper.vm.contextMenuVisible).toBe(true);
		expect(wrapper.vm.contextMenuPosition).toEqual({ x: 40, y: 300 });
		expect(wrapper.vm.contextMenuItems.map((i) => i.id).filter(Boolean)).toContain(
			"delete-folder"
		);
	});

	it("draws the list itself when it is not headless, with the unread mail it now knows", async () => {
		const wrapper = mount(FolderTree, { props: { account: "me@example.com" } });
		await flushPromises();
		await flushPromises();
		expect(wrapper.find(".folder-list").exists()).toBe(true);
		expect(wrapper.find(".unread-count").text()).toBe("12");
	});
});
