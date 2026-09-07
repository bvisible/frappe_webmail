// Requests the Nora panel answers itself, without a round trip through the
// orchestrator: the three things people ask a mail assistant most — reply to
// this message, write a new one, fix the one being written — plus translating
// it. They map to the webmail's direct LLM endpoints (seconds, deterministic,
// run with the user's own rights). Everything else goes to Nora.
//
// Patterns are anchored on the first words so that "réponds-moi : combien de
// factures ?" stays a question for Nora and never becomes a reply draft.

const LEAD =
	"^(?:nora[ ,:]*)?(?:peux[- ]tu |pourrais[- ]tu |tu peux |stp |merci de |please )?(?:me |m')?";

const REPLY_VERB = new RegExp(LEAD + "(?:r[ée]pond(?:s|re|ez)?|reply|answer)\\b", "i");
// JS `\b` is ASCII-only — there is no word boundary before "à", so anchor on whitespace
const REPLY_OBJECT =
	/(?:^|\s)(?:[àa] (?:ce|cet|cette|l'|la |son |sa )|au (?:mail|message|courriel|client|fournisseur)|[àa] l'exp[ée]diteur|to (?:this|the|him|her|them)|this (?:e-?mail|mail|message))/i;
const REPLY_DRAFT = new RegExp(
	LEAD +
		"(?:r[ée]dige[sz]?|[ée]cri(?:s|t|re|vez)|pr[ée]pare[sz]?|propose[sz]?|fai[st]|g[ée]n[èe]re[sz]?|draft|write|prepare)\\b[^.?!]{0,40}\\b(?:une |la |sa |ma |a |the |my )?(?:r[ée]ponse|reply|answer)\\b",
	"i"
);

const IMPROVE_VERB = new RegExp(
	LEAD +
		"(corrige[sz]?|reli(?:s|t|re)|v[ée]rifie[sz]?|am[ée]liore[sz]?|reformule[sz]?|peaufine[sz]?|raccourci[st]|allonge[sz]?|simplifie[sz]?|rends?|revois|proofread|fix|correct|improve|rewrite|polish|shorten|check)\\b",
	"i"
);
const PROOFREAD_VERBS = /^(?:corrige|reli|v[ée]rifie|proofread|fix|correct|check)/i;
const IMPROVE_OBJECT =
	/\b(?:mon |ce |cet |le |ma |mes |this |my |the )?(?:mail|e-?mail|courriel|message|brouillon|texte|r[ée]ponse|draft|text|wording|style|ton|orthographe|fautes?)\b/i;

const TRANSLATE_VERB = new RegExp(LEAD + "(?:tradui[st]|traduire|translate)\\b", "i");
// Only the languages the endpoint knows (nora.api.nora_webmail.translate)
const LANGUAGES = [
	[/\b(?:anglais|english)\b/i, "en"],
	[/\b(?:allemand|deutsch|german)\b/i, "de"],
	[/\b(?:fran[çc]ais|francais|french)\b/i, "fr"],
];

const COMPOSE_VERB = new RegExp(
	LEAD +
		"(?:r[ée]dige[sz]?|[ée]cri(?:s|t|re|vez)|compose[sz]?|pr[ée]pare[sz]?|fai[st]|cr[ée]e[sz]?|g[ée]n[èe]re[sz]?|draft|write|compose)\\b",
	"i"
);
const COMPOSE_OBJECT =
	/\b(?:un |une |le |la |a |an |the |nouveau |nouvel |new )?(?:mail|e-?mail|courriel|message|lettre|mot|relance|email)\b/i;

/**
 * @param {string} text  what the user typed
 * @param {{composerOpen?: boolean, emailOpen?: boolean}} ctx
 * @returns {null | {kind: "reply"} | {kind: "compose"} | {kind: "proofread"} | {kind: "improve"} | {kind: "translate", lang: string}}
 */
export function classifyIntent(text, ctx = {}) {
	const t = (text || "").trim();
	if (!t) return null;

	if (TRANSLATE_VERB.test(t)) {
		const hit = LANGUAGES.find(([re]) => re.test(t.replace(TRANSLATE_VERB, "")));
		return hit ? { kind: "translate", lang: hit[1] } : null;
	}

	const improve = t.match(IMPROVE_VERB);
	if (improve && (IMPROVE_OBJECT.test(t) || (ctx.composerOpen && t.length < 60))) {
		return { kind: PROOFREAD_VERBS.test(improve[1]) ? "proofread" : "improve" };
	}

	if (REPLY_DRAFT.test(t) || (REPLY_VERB.test(t) && REPLY_OBJECT.test(t))) {
		return { kind: "reply" };
	}

	if (COMPOSE_VERB.test(t) && COMPOSE_OBJECT.test(t)) {
		return { kind: "compose" };
	}

	return null;
}
