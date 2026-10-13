/**
 * The attachment's menu, as the server describes it: groups, icons, the stream's address.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CloudUpload, Eye, File } from "lucide-vue-next";
import {
	downloadUrl,
	loadAttachmentActions,
	menuItems,
	previewable,
	resetAttachmentActions,
} from "@/attachmentActions.js";

const ACTIONS = [
	{ key: "preview", label: "Preview", icon: "eye", kind: "client", group: "view" },
	{ key: "download", label: "Save as…", icon: "download", kind: "client", group: "view" },
	{
		key: "save_to_drive",
		label: "Save to the Drive…",
		icon: "cloud-upload",
		kind: "pick_folder",
		group: "neoffice",
		method: "m.drive",
	},
	{
		key: "new_one",
		label: "Something new",
		icon: "sparkles",
		kind: "now",
		group: "neoffice",
		method: "m.new",
	},
	{ key: "forward", label: "Forward", icon: "forward", kind: "client", group: "share" },
];

describe("attachment actions", () => {
	beforeEach(() => resetAttachmentActions());

	it("draws one entry per action and a line between the groups the server named", () => {
		const items = menuItems(ACTIONS);
		expect(items.map((i) => (i.separator ? "—" : i.id))).toEqual([
			"preview",
			"download",
			"—",
			"save_to_drive",
			"new_one",
			"—",
			"forward",
		]);
		expect(items[0].icon).toBe(Eye);
		expect(items[3].icon).toBe(CloudUpload);
		// An icon the desk does not know yet still draws (a new action needs no screen code)
		expect(items[4].icon).toBe(File);
		expect(items[4].action).toBe(ACTIONS[3]);
	});

	it("asks the server once per page", async () => {
		const call = vi.fn().mockResolvedValue({ message: ACTIONS });
		const [a, b] = await Promise.all([
			loadAttachmentActions(call),
			loadAttachmentActions(call),
		]);
		expect(call).toHaveBeenCalledTimes(1);
		expect(a).toBe(b);
	});

	it("asks again after a failure", async () => {
		const call = vi
			.fn()
			.mockRejectedValueOnce(new Error("offline"))
			.mockResolvedValue({ message: ACTIONS });
		expect(await loadAttachmentActions(call)).toEqual([]);
		expect(await loadAttachmentActions(call)).toEqual(ACTIONS);
	});

	it("builds the stream's address with every argument encoded", () => {
		const url = new URL(
			downloadUrl({
				account: "a+b@example.com",
				folder: "Clients/2026 & co",
				uid: 42,
				attachmentId: "logo@x",
				inline: true,
			}),
			"http://site.test"
		);
		expect(url.pathname).toBe("/api/method/frappe_webmail.attachments.download_attachment");
		expect(Object.fromEntries(url.searchParams)).toEqual({
			account_name: "a+b@example.com",
			folder: "Clients/2026 & co",
			uid: "42",
			attachment_id: "logo@x",
			inline: "1",
		});
	});

	it("shows in the browser only what it can show safely", () => {
		expect(previewable("application/pdf")).toBe(true);
		expect(previewable("image/jpeg")).toBe(true);
		expect(previewable("text/html")).toBe(false);
		expect(previewable("image/svg+xml")).toBe(false);
		expect(previewable(undefined)).toBe(false);
	});
});
