// Text hygiene for what Nora's orchestrator sends back to the webmail panel.
//
// Every outgoing message carries an agent-facing context block (mailbox, open
// message, thread id…). The orchestrator sometimes copies the whole message —
// block included — into a delegated task's title, and the pole echoes that
// title back, truncated at an arbitrary character. The tag that opens the
// block is therefore kept SHORT, so it survives the cut whole, and everything
// we know about the block is stripped here before display.

export const CONTEXT_TAG = "[agent-only context]";

const FIELD_LINE =
	/(?:mailbox account|folder|open email|conversation_id|requester user)\s*:\s*"?[\w@.\-]*"?\s*(?:\([^)]*\)\s*)?/g;

/** Strip our own context block (whole or cut short) from an answer. */
export function cleanEcho(text) {
	return (
		String(text || "")
			// the current tag, and the long-form tag earlier bundles sent
			.replace(/\[agent-only context\]\s*/g, "")
			.replace(/\[Webmail context for the assistant[^\]]*\]\s*/g, "")
			.replace(/\[(?:agent-only cont|Webmail context for)[^\]\n]*$\n?/gm, "")
			.replace(/never quote this block[^\n]*\n?/gi, "")
			.replace(FIELD_LINE, "")
			.replace(/—\s*pass it to every tool that accepts it\s*/g, "")
			.trim()
	);
}

/** Raw provider failures relayed by the gateway are not something to show verbatim. */
export function friendlyAnswer(text, fallback) {
	if (/API call failed|empty stream|no finish_reason|Provider returned/i.test(text || "")) {
		return fallback;
	}
	return text;
}
