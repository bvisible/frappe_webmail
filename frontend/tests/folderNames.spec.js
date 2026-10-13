import { afterEach, describe, expect, it } from "vitest";
import { folderName } from "../src/utils/folderNames.js";

describe("folderName", () => {
	afterEach(() => {
		delete window.__;
	});

	it("asks each special folder's name in the mail's context, never the bare word", () => {
		const asked = [];
		window.__ = (message, replace, context) => {
			asked.push([message, context]);
			return context === "Mail folder" && message === "Archive" ? "Archives" : `${message}*`;
		};
		// « Archive » alone is « Archiver » (a verb) in another app's catalog: the folder keeps its own word
		expect(folderName("archive")).toBe("Archives");
		expect(["inbox", "sent", "drafts", "trash", "spam"].map(folderName)).toEqual([
			"Inbox*",
			"Sent*",
			"Drafts*",
			"Trash*",
			"Spam*",
		]);
		expect(asked.every(([, context]) => context === "Mail folder")).toBe(true);
	});

	it("names nothing else", () => {
		expect(folderName("starred")).toBeNull();
		expect(folderName(undefined)).toBeNull();
	});

	it("gives the words as they are before Frappe's __ exists", () => {
		expect(folderName("sent")).toBe("Sent");
	});
});
