/**
 * What a message's body may fetch from elsewhere before its reader says so: nothing but what it carries itself. A
 * sender's server learns from any fetch that the message was opened, when, and from where (a tracking pixel).
 *
 * Two layers. The sanitizer's hook (blockRemote) takes away, on each element, the addresses it would fetch: an image's
 * `src` (kept aside, the image drawn as a placeholder), its `srcset`, a `background` attribute, an SVG image's `href`;
 * it says whether there were any, for the notice. The frame's policy (framePolicy) then lets the frame fetch no image
 * but those written into the message (`data:`), whatever the CSS says: a `url()` or an `image-set()` in a style, in
 * whatever form the sanitizer keeps it. Only `img src` used to be blocked: a style's background, a `srcset` or a
 * `background` attribute still loaded, and no notice said so. The images come back when the reader asks, or trusts the
 * sender.
 */

const LOCAL = /^\s*(data:|cid:|#)/i;
const SVG_NS = "http://www.w3.org/2000/svg";
const PLACEHOLDER =
	'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" fill="gray" font-size="12">[×]</text></svg>';

/** Whether an address is one the message carries itself (data:, cid:, a fragment), which fetches nothing. */
export function isLocal(url) {
	return LOCAL.test(url || "");
}

/** Whether a style asks for something to fetch: a url() that is not the message's own, an image-set(), or an escape
 * (CSS reads `\75 rl(` as `url(`). Said for the notice only: the frame's policy blocks them all the same. */
export function styleFetches(style) {
	const css = style || "";
	if (/image-set\s*\(|cross-fade\s*\(|\\/i.test(css)) return true;
	const urls = css.matchAll(/url\s*\(\s*(['"]?)(.*?)\1\s*\)/gi);
	for (const [, , url] of urls) {
		if (!isLocal(url)) return true;
	}
	return false;
}

/**
 * Take away from `node` (an element the sanitizer just cleaned) what it would fetch from elsewhere. `title`: what a
 * blocked image says when pointed at. True when something was blocked.
 */
export function blockRemote(node, title) {
	let blocked = false;
	if (node.tagName === "IMG") {
		const src = node.getAttribute("src");
		if (src && !isLocal(src)) {
			node.setAttribute("data-blocked-src", src);
			node.setAttribute("src", PLACEHOLDER);
			node.style.cursor = "pointer";
			if (title) node.title = title;
			blocked = true;
		}
	}
	const srcset = node.getAttribute("srcset");
	if (srcset !== null) {
		if (srcset.trim() && !isLocal(srcset)) blocked = true;
		node.removeAttribute("srcset");
	}
	const background = node.getAttribute("background");
	if (background !== null && !isLocal(background)) {
		node.removeAttribute("background");
		blocked = true;
	}
	if (node.namespaceURI === SVG_NS) {
		for (const name of ["href", "xlink:href"]) {
			const href = node.getAttribute(name);
			if (href !== null && !isLocal(href) && /^(image|feimage|use)$/i.test(node.localName)) {
				node.removeAttribute(name);
				blocked = true;
			}
		}
	}
	if (styleFetches(node.getAttribute("style"))) blocked = true;
	return blocked;
}

/**
 * The frame's Content-Security-Policy, as the first element of its head: no script, nothing fetched but images, and
 * only the message's own images (`data:`) while `blocking`. The styles stay (the frame's own and the message's).
 */
export function framePolicy(blocking) {
	const images = blocking ? "data:" : "* data: blob:";
	return `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${images}; style-src 'unsafe-inline'; font-src data:">`;
}
