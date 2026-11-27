/**
 * The pictures a paste puts in a message's text: the image files of the clipboard (a screenshot, a picture copied in
 * an image viewer, a web page or the Finder), each read as a `data:` address, which the server sends as a part of the
 * message (inline_images.py). Without this, the editor took no file from a paste, and a picture could only be joined.
 *
 * A text copied with a picture of itself (Word, Excel, a page with words) stays text: a clipboard whose HTML holds words,
 * or whose plain text is more than the names of its files, gives no picture.
 */
export const MAX_PASTED_IMAGE = 5 * 1024 * 1024;

export function imagesToPaste(clipboardData) {
	if (!clipboardData) return [];
	const files = Array.from(clipboardData.files || []).filter((file) =>
		String(file.type || "").startsWith("image/")
	);
	if (!files.length) return [];
	const html = clipboardData.getData("text/html") || "";
	if (html) {
		const words = new DOMParser().parseFromString(html, "text/html").body.textContent || "";
		return words.trim() ? [] : files;
	}
	const text = (clipboardData.getData("text/plain") || "").trim();
	const names = new Set(files.map((file) => file.name));
	const onlyNames = text
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter(Boolean)
		.every((line) => names.has(line));
	return onlyNames ? files : [];
}

export function readAsDataUrl(file) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(reader.result);
		reader.onerror = () => reject(reader.error);
		reader.readAsDataURL(file);
	});
}
