import { describe, expect, it } from "vitest";
import { classifyIntent } from "@/agentIntents";

const kind = (text, ctx) => (classifyIntent(text, ctx) || { kind: null }).kind;

describe("classifyIntent — what the panel handles without the orchestrator", () => {
	it("replying to the open message", () => {
		expect(kind("Réponds à ce mail")).toBe("reply");
		expect(kind("réponds à cet email en confirmant le rendez-vous")).toBe("reply");
		expect(kind("Nora, peux-tu répondre à l'expéditeur ?")).toBe("reply");
		expect(kind("Rédige une réponse")).toBe("reply");
		expect(kind("prépare-moi la réponse et propose-la moi")).toBe("reply");
		expect(kind("Rédige-moi un email de réponse poli")).toBe("reply");
		expect(kind("Reply to this email")).toBe("reply");
	});

	it("does not mistake a question for a reply", () => {
		expect(kind("Réponds-moi : combien de factures sont en retard ?")).toBeNull();
		expect(kind("Réponds en une phrase : qui a écrit ce mail ?")).toBeNull();
	});

	it("writing a new email", () => {
		expect(kind("Rédige-moi un email à Jean pour annuler le rendez-vous de mardi")).toBe(
			"compose"
		);
		expect(kind("Écris un message de relance pour la facture impayée")).toBe("compose");
		expect(kind("peux-tu écrire un mail au fournisseur")).toBe("compose");
		expect(kind("Write an email to the supplier about the delay")).toBe("compose");
	});

	it("fixing the draft being written", () => {
		expect(kind("Corrige mon email")).toBe("proofread");
		expect(kind("relis mon brouillon")).toBe("proofread");
		expect(kind("Vérifie les fautes de mon message")).toBe("proofread");
		expect(kind("améliore le style de ce mail")).toBe("improve");
		expect(kind("raccourcis ce texte")).toBe("improve");
		expect(kind("reformule ma réponse plus poliment")).toBe("improve");
		// A bare verb while the composer is open is about the draft
		expect(kind("Corrige", { composerOpen: true })).toBe("proofread");
		expect(kind("Corrige", { composerOpen: false })).toBeNull();
	});

	it("translating the draft, only into languages the endpoint knows", () => {
		expect(classifyIntent("Traduis mon mail en anglais")).toEqual({
			kind: "translate",
			lang: "en",
		});
		expect(classifyIntent("traduis-le en allemand")).toEqual({
			kind: "translate",
			lang: "de",
		});
		expect(classifyIntent("Translate my draft to French")).toEqual({
			kind: "translate",
			lang: "fr",
		});
		expect(kind("traduis en italien")).toBeNull();
	});

	it("recurring mailbox jobs are scheduled by the panel itself", () => {
		expect(kind("Relève la boîte toutes les heures pour les factures")).toBe("schedule");
		expect(kind("Relève cette boîte toutes les heures pour les factures")).toBe("schedule");
		expect(kind("Résume-moi les nouveaux mails chaque matin")).toBe("schedule");
		expect(kind("Envoie-moi chaque lundi les devis en attente")).toBe("schedule");
		expect(kind("Check this mailbox every hour for invoices")).toBe("schedule");
	});

	it("listing automations is answered by the panel too", () => {
		expect(kind("Quelles automatisations sont actives ?")).toBe("list_automations");
		expect(kind("Mes automatisations")).toBe("list_automations");
		expect(kind("Which automations are active?")).toBe("list_automations");
		expect(kind("Quelles tâches programmées existent ?")).toBe("list_automations");
	});

	it("leaves everything else to Nora", () => {
		expect(kind("Résume ce mail")).toBeNull();
		expect(kind("Des factures à traiter dans cette boîte ?")).toBeNull();
		expect(kind("Combien de factures sont arrivées cette semaine ?")).toBeNull();
		expect(kind("")).toBeNull();
	});
});
