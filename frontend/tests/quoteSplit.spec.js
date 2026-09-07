import { describe, expect, it } from "vitest";
import { joinQuote, splitQuote } from "@/quoteSplit";

describe("splitQuote — Nora only rewrites what the user wrote", () => {
	it("stops at the blockquote of a reply", () => {
		const html =
			"<p>Bonjour Madame Favre,</p><p>Merci pour votre facture.</p>" +
			"<p>Le 12/06/2026 16:26:25, nora@noraai.ch a écrit :</p><blockquote><p>salut</p></blockquote>";
		const { own, quote } = splitQuote(html);
		expect(own).toBe("<p>Bonjour Madame Favre,</p><p>Merci pour votre facture.</p>");
		expect(quote).toContain("a écrit");
		expect(quote).toContain("<blockquote>");
	});

	it("keeps everything when there is no quote", () => {
		const html = "<p>Un message neuf</p><p>Cordialement</p>";
		expect(splitQuote(html)).toEqual({ own: html, quote: "" });
	});

	it("recognises imported quote wrappers", () => {
		const html = '<p>Merci.</p><div class="gmail_quote"><p>On Mon, X wrote:</p></div>';
		expect(splitQuote(html).own).toBe("<p>Merci.</p>");
	});

	it("puts the rewritten part back in front of the untouched quote", () => {
		const html = "<p>Bonjour</p><blockquote><p>original</p></blockquote>";
		const { quote } = splitQuote(html);
		expect(joinQuote("<p>Hello</p>", quote)).toBe(
			"<p>Hello</p><blockquote><p>original</p></blockquote>"
		);
	});
});
