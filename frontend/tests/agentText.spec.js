import { describe, expect, it } from "vitest";
import { CONTEXT_TAG, cleanEcho, friendlyAnswer } from "@/agentText";

describe("cleanEcho — our context block never reaches the screen", () => {
	it("strips a whole echoed block and its field lines", () => {
		const echoed = `✅ Support — Résumer ce mail\n\n${CONTEXT_TAG} mailbox account: "nora@noraai.ch" folder: "INBOX" Résumé du mail UID 24 : simple envoi de facture.`;
		expect(cleanEcho(echoed)).toBe(
			"✅ Support — Résumer ce mail\n\nRésumé du mail UID 24 : simple envoi de facture."
		);
	});

	it("strips the long-form tag earlier bundles sent, even cut short", () => {
		const cut =
			"✅ Support — Résumer ce mail\n\n[Webmail context for the assistant — not written by the user. Never quote it, and when you delegate, ti\nRésumé du mail UID 24.";
		expect(cleanEcho(cut)).toBe("✅ Support — Résumer ce mail\n\nRésumé du mail UID 24.");
	});

	it("leaves an ordinary answer alone", () => {
		expect(cleanEcho("Le mail demande un paiement à 30 jours.")).toBe(
			"Le mail demande un paiement à 30 jours."
		);
	});
});

describe("friendlyAnswer — provider failures get a human sentence", () => {
	it("replaces a raw gateway failure", () => {
		expect(
			friendlyAnswer(
				"API call failed after 3 retries: Provider returned an empty stream",
				"Nora n'a pas répondu."
			)
		).toBe("Nora n'a pas répondu.");
	});
	it("keeps real answers", () => {
		expect(friendlyAnswer("Voici le résumé.", "x")).toBe("Voici le résumé.");
	});
});
