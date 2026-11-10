// The signature in the composer: one block the editor keeps as it came (its table, colours, logo), shown as it will be
// sent and not edited in place. The editor's own nodes would rebuild it from paragraphs and lose its layout: a
// company's signature is a table (signatures.py), and one pasted from a generator too.
import { Node } from "@tiptap/core";
import DOMPurify from "dompurify";

// What marks the block in the HTML the composer writes and reads back (a draft reopened finds its signature whole).
export const SIGNATURE_ATTRIBUTE = "data-webmail-signature";

// What the block may show: what a message sent may carry (the server cleans it again when it leaves), nothing that
// runs, fetches by itself or takes input.
const SHOWN = {
	FORBID_TAGS: [
		"style",
		"link",
		"meta",
		"base",
		"form",
		"input",
		"button",
		"textarea",
		"select",
		"iframe",
		"object",
		"embed",
		"svg",
		"math",
	],
	FORBID_ATTR: ["srcset", "action", "formaction"],
	ALLOW_DATA_ATTR: false,
};

export function shownSignature(html) {
	return DOMPurify.sanitize(html || "", SHOWN);
}

// The signature's HTML as the composer puts it in a message: in its block.
export function signatureBlock(html) {
	return html ? `<div ${SIGNATURE_ATTRIBUTE}="">${html}</div>` : "";
}

// The signature as it follows the text of a message: a line of space, then its block. No « -- » line before it: the
// block already sets it apart, and a company's signature (signatures.py) is a card with its logo, which the old
// plain-text separator only made look dated in every mail client (10.11.2026, the team's first messages).
export function signatureAfterText(html) {
	return html ? `<br>${signatureBlock(html)}` : "";
}

export const SignatureBlock = Node.create({
	name: "signatureBlock",
	group: "block",
	atom: true,
	selectable: true,
	draggable: false,
	// Read before the other extensions take its paragraphs and cells for their own.
	priority: 1000,

	addAttributes() {
		return {
			html: { default: "", parseHTML: (element) => element.innerHTML, rendered: false },
		};
	},

	parseHTML() {
		return [{ tag: `div[${SIGNATURE_ATTRIBUTE}]` }];
	},

	renderHTML({ node }) {
		const block = document.createElement("div");
		block.setAttribute(SIGNATURE_ATTRIBUTE, "");
		block.innerHTML = shownSignature(node.attrs.html);
		return block;
	},

	addNodeView() {
		return ({ node }) => {
			const block = document.createElement("div");
			block.setAttribute(SIGNATURE_ATTRIBUTE, "");
			block.className = "webmail-signature-block";
			block.contentEditable = "false";
			block.innerHTML = shownSignature(node.attrs.html);
			return { dom: block };
		};
	},
});
