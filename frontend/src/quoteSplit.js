// Split a reply into what the user wrote and the quoted original below it.
// Nora's proofread / improve / translate must only touch the user's own words:
// on 2026-09-07 the whole editor went through "Traduire" and the quoted French
// message came back in English. The composer inserts the quote as a
// <blockquote> preceded by the "Le … a écrit :" line; mail clients we import
// drafts from use gmail_quote-like wrappers — we stop at the first of them.

const QUOTE_SELECTORS = [
	"blockquote",
	".gmail_quote",
	".quote",
	"div[type='cite']",
	".moz-cite-prefix",
];
// "Le 12/06/2026 16:26:25, x@y a écrit :" / "On …, x wrote:" — the attribution line
const ATTRIBUTION_RE = /\b(a écrit\s*:|wrote:|schrieb:)\s*$/i;

/**
 * @param {string} html  full editor HTML
 * @returns {{ own: string, quote: string }}  own = HTML the user wrote, quote = the rest (may be "")
 */
export function splitQuote(html) {
	const doc = new DOMParser().parseFromString(`<div id="root">${html || ""}</div>`, "text/html");
	const root = doc.getElementById("root");
	const children = [...root.childNodes];
	let cut = -1;
	for (let i = 0; i < children.length; i++) {
		const node = children[i];
		if (node.nodeType !== 1) continue;
		if (QUOTE_SELECTORS.some((sel) => node.matches(sel) || node.querySelector(sel))) {
			cut = i;
			break;
		}
		if (ATTRIBUTION_RE.test((node.textContent || "").trim())) {
			cut = i;
			break;
		}
	}
	if (cut === -1) return { own: html || "", quote: "" };
	const serialize = (nodes) =>
		nodes.map((n) => (n.nodeType === 1 ? n.outerHTML : n.textContent || "")).join("");
	return { own: serialize(children.slice(0, cut)), quote: serialize(children.slice(cut)) };
}

/** Put a rewritten own part back in front of an untouched quote. */
export function joinQuote(ownHtml, quoteHtml) {
	return `${ownHtml || ""}${quoteHtml || ""}`;
}
