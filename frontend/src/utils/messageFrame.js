/**
 * How a message's body is drawn in its frame, in the desk's theme.
 *
 * A message that sets no colour of its own is drawn in the desk's colours: light words on the dark desk, as Neodesk
 * draws it. A message that sets its own colours (a newsletter, a coloured signature) keeps them, on a light sheet in
 * the dark theme, the way Apple Mail shows it: its dark words never land on the dark desk. Neodesk follows the same
 * rule (neoffice-mobile `utils/mail.ts`, hasOwnColours).
 */

/** Whether a message's HTML sets colours of its own, for its text or a background. */
export function hasOwnColours(html) {
	return /\bbgcolor\s*=|<font\b[^>]*\bcolor\s*=|\bstyle\s*=\s*(?:"[^"]*|'[^']*)\b(?:color|background(?:-color)?)\s*:/i.test(
		html || ""
	);
}

// The light sheet: the paper and the ink of the Neoffice palette
const LIGHT = {
	scheme: "light",
	bg: "#ffffff",
	text: "#2a2622",
	muted: "#524b41",
	line: "#dcd4c7",
	link: "#a15a2e",
	code: "#f6f3ed",
};

/**
 * The colours of the frame. `desk` holds the page's own (its --wm-* variables, read where the mail is drawn); `sheet`
 * says the light sheet stands on a dark desk.
 */
export function frameColours({ dark, ownColours, desk = {} }) {
	if (!dark) return { ...LIGHT, bg: desk.bg || LIGHT.bg, sheet: false };
	if (ownColours) return { ...LIGHT, sheet: true };
	return {
		scheme: "dark",
		bg: desk.bg || "#1c2127",
		text: desk.text || "#f2efe8",
		muted: desk.muted || "#a39a8c",
		line: desk.line || "rgba(220, 210, 190, 0.18)",
		link: "#d68a59",
		code: desk.sunken || "rgba(255, 255, 255, 0.06)",
		sheet: false,
	};
}

/** The style of the frame's document, from those colours. */
export function frameStyle(colours) {
	return [
		`:root { color-scheme: ${colours.scheme}; }`,
		`html, body { background: ${colours.bg}; }`,
		"* { box-sizing: border-box; }",
		"body {",
		"  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;",
		`  font-size: 14px; line-height: 1.6; color: ${colours.text};`,
		"  margin: 0; padding: 16px; word-wrap: break-word;",
		"}",
		"img { max-width: 100%; height: auto; }",
		`a { color: ${colours.link}; }`,
		`blockquote { border-left: 3px solid ${colours.line}; margin: 10px 0; padding-left: 15px; color: ${colours.muted}; }`,
		`pre, code { background: ${colours.code}; padding: 2px 6px; border-radius: 3px; font-size: 13px; }`,
		"pre { padding: 10px; overflow-x: auto; }",
		"table { max-width: 100%; }",
	].join("\n");
}
