import { describe, expect, it } from "vitest";
import { blockRemote, framePolicy, isLocal, styleFetches } from "../src/utils/remoteContent.js";

/** The first element of `html`, as the sanitizer's hook is given it. Parsed in a template, where a cell or a row
 * stays what it is: in a div the HTML parser drops a `<td>` without its table, as every browser does. */
function element(html) {
	const box = document.createElement("template");
	box.innerHTML = html;
	return box.content.firstElementChild;
}

describe("blockRemote", () => {
	it("blocks an image from elsewhere and keeps its address aside", () => {
		const img = element('<img src="https://tracker.example/p.gif">');
		expect(blockRemote(img, "External image blocked")).toBe(true);
		expect(img.getAttribute("src")).toMatch(/^data:image\/svg\+xml,/);
		expect(img.getAttribute("data-blocked-src")).toBe("https://tracker.example/p.gif");
	});

	it("takes away a srcset and a background attribute, which loaded with no notice", () => {
		const img = element('<img src="cid:logo" srcset="https://tracker.example/s.gif 1x">');
		expect(blockRemote(img)).toBe(true);
		expect(img.hasAttribute("srcset")).toBe(false);
		const table = element(
			'<table background="https://tracker.example/bg.gif"><tr><td>x</td></tr></table>'
		);
		expect(blockRemote(table)).toBe(true);
		expect(table.hasAttribute("background")).toBe(false);
	});

	it("says a style asks for an address, even written with an escape", () => {
		expect(
			blockRemote(
				element('<td style="background:url(https://tracker.example/c.gif)">x</td>')
			)
		).toBe(true);
		expect(
			styleFetches("background-image: image-set('https://tracker.example/i.gif' 1x)")
		).toBe(true);
		expect(styleFetches("background: \\75 rl(https://tracker.example/e.gif)")).toBe(true);
	});

	it("leaves what the message carries itself, and a plain layout", () => {
		const inline = element('<img src="data:image/png;base64,iVBORw0KGgo=">');
		expect(blockRemote(inline)).toBe(false);
		expect(inline.getAttribute("src")).toBe("data:image/png;base64,iVBORw0KGgo=");
		expect(blockRemote(element('<p style="color:#1F497D;margin:0">Bonjour</p>'))).toBe(false);
		expect(
			blockRemote(element('<td style="background:url(data:image/gif;base64,R0lGOD)">x</td>'))
		).toBe(false);
		expect(isLocal("cid:part1")).toBe(true);
		expect(isLocal("https://example.com/a.png")).toBe(false);
	});
});

describe("framePolicy", () => {
	it("lets the frame fetch the message's own images only while they are blocked", () => {
		expect(framePolicy(true)).toContain("img-src data:;");
		expect(framePolicy(true)).toContain("default-src 'none'");
	});

	it("lets the images come once the reader asks", () => {
		expect(framePolicy(false)).toContain("img-src * data: blob:;");
	});
});
