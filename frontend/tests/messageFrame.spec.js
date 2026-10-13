import { describe, expect, it } from "vitest";
import { frameColours, frameStyle, hasOwnColours } from "../src/utils/messageFrame.js";

describe("hasOwnColours", () => {
	it("knows a message that sets colours of its own", () => {
		expect(hasOwnColours('<p style="color:#1F497D">Meilleures salutations</p>')).toBe(true);
		expect(hasOwnColours("<td style='background-color: #003366'>Promo</td>")).toBe(true);
		expect(hasOwnColours('<table bgcolor="#ffffff"><tr><td>x</td></tr></table>')).toBe(true);
		expect(hasOwnColours('<font color="red">!</font>')).toBe(true);
	});

	it("leaves plain words and a layout without colour", () => {
		expect(hasOwnColours("<p>Bonjour,</p><p>Voici la facture.</p>")).toBe(false);
		expect(hasOwnColours('<p style="margin:0;font-size:14px">x</p>')).toBe(false);
		expect(hasOwnColours(null)).toBe(false);
	});
});

describe("frameColours", () => {
	const desk = { bg: "#1c2127", text: "#f0f0f0", muted: "#999", line: "#333", sunken: "#222" };

	it("draws a plain message in the dark desk's colours", () => {
		const c = frameColours({ dark: true, ownColours: false, desk });
		expect(c).toMatchObject({ scheme: "dark", bg: "#1c2127", text: "#f0f0f0", sheet: false });
	});

	it("keeps a message with colours of its own on a light sheet in the dark theme", () => {
		const c = frameColours({ dark: true, ownColours: true, desk });
		expect(c).toMatchObject({ scheme: "light", bg: "#ffffff", sheet: true });
	});

	it("draws everything light in the light theme, never a sheet", () => {
		expect(frameColours({ dark: false, ownColours: true })).toMatchObject({
			scheme: "light",
			sheet: false,
		});
		expect(frameColours({ dark: false, ownColours: false, desk: { bg: "#fffdf8" } }).bg).toBe(
			"#fffdf8"
		);
	});

	it("writes those colours into the frame's style, links in the clay of Neoffice", () => {
		const css = frameStyle(frameColours({ dark: true, ownColours: false, desk }));
		expect(css).toContain("color-scheme: dark");
		expect(css).toContain("background: #1c2127");
		expect(css).toContain("color: #f0f0f0");
		expect(css).toContain("a { color: #d68a59; }");
		expect(frameStyle(frameColours({ dark: false, ownColours: false }))).toContain(
			"a { color: #a15a2e; }"
		);
	});
});
