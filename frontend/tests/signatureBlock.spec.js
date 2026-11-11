// The signature as the composer places it after the text of a message (signatureBlock.js): its block, after a line of
// space, and no « -- » line before it (10.11.2026: the team's first messages from the hub showed the old plain-text
// separator above the company's card).
import { describe, expect, it } from "vitest";

import { SIGNATURE_ATTRIBUTE, signatureAfterText, signatureBlock } from "../src/signatureBlock";

const CARD =
	'<table><tr><td><img src="/files/logo.png" width="180"><div>Alex Example</div></td></tr></table>';

describe("the signature after the text of a message", () => {
	it("is its block after a line of space, with no separator line", () => {
		const html = signatureAfterText(CARD);
		expect(html).toBe(`<br>${signatureBlock(CARD)}`);
		expect(html).not.toContain("--");
		const holder = document.createElement("div");
		holder.innerHTML = html;
		const block = holder.querySelector(`[${SIGNATURE_ATTRIBUTE}]`);
		expect(block).not.toBeNull();
		// The card as a browser writes it back (a table gets its tbody)
		const card = document.createElement("div");
		card.innerHTML = CARD;
		expect(block.innerHTML).toBe(card.innerHTML);
		// Nothing but the space before the block: no paragraph holding a separator
		expect(holder.querySelectorAll("p")).toHaveLength(0);
	});

	it("is nothing when there is no signature", () => {
		for (const none of ["", null, undefined]) {
			expect(signatureAfterText(none)).toBe("");
		}
	});

	it("is what the composer uses wherever it adds a signature", async () => {
		const { readFileSync } = await import("node:fs");
		const { resolve } = await import("node:path");
		// The tests run from the frontend folder (package.json)
		const source = readFileSync(
			resolve(process.cwd(), "src/components/EmailComposer.vue"),
			"utf8"
		);
		expect(source).not.toContain("<p>--</p>");
		// The new message, the reply, the forward and the signature button
		expect(source.match(/signatureAfterText\(this\.signature\)/g)).toHaveLength(4);
	});
});
