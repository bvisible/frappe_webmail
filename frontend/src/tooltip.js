// Tooltips for icon-only controls (folder rail, top bar, reader actions, Nora
// panel). One shared element appended to <body> and positioned with fixed
// coordinates, so a scrolling rail or a clipped column never hides it — the
// native `title` tooltip is slow and looks foreign next to the cockpit's.
//
// Usage: give the control `data-tip="Sent"` (+ `aria-label` when it has no
// visible text) and optionally `data-tip-pos="right|left|top|bottom"`.
// Install once on the app root: `const off = installTooltips(rootEl)`.
const SHOW_DELAY_MS = 220;
const GAP_PX = 8;
const STYLE_ID = "wm-tooltip-style";

// The element sits on <body>, outside the app root and its stylesheet (nested
// under .webmail-app): the helper carries its own styles — ink on paper,
// inverted in dark mode.
const CSS = `
.wm-tooltip {
	position: fixed;
	z-index: 2000;
	pointer-events: none;
	background: #141414;
	color: #fffdf8;
	font-family: inherit;
	font-size: 12px;
	font-weight: 500;
	line-height: 1.3;
	padding: 5px 9px;
	border-radius: 7px;
	white-space: nowrap;
	max-width: 280px;
	box-shadow: 0 4px 14px rgba(20, 20, 20, 0.18);
	opacity: 0;
	transform: translateY(-3px);
	transition: opacity 0.12s ease, transform 0.12s ease;
}
.wm-tooltip[data-pos="right"] { transform: translateX(-3px); }
.wm-tooltip.is-visible { opacity: 1; transform: none; }
[data-theme="dark"] .wm-tooltip { background: #fffdf8; color: #141414; }
`;

function ensureStyles() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = CSS;
	document.head.appendChild(style);
}

export function installTooltips(root) {
	let tip = null;
	let timer = null;
	let current = null;

	const ensureElement = () => {
		if (!tip) {
			ensureStyles();
			tip = document.createElement("div");
			tip.className = "wm-tooltip";
			tip.setAttribute("role", "tooltip");
			document.body.appendChild(tip);
		}
		return tip;
	};

	const clamp = (value, min, max) => Math.max(min, Math.min(value, max));

	const show = (target) => {
		const text = target.getAttribute("data-tip");
		if (!text) return;
		const el = ensureElement();
		el.textContent = text;
		const pos = target.getAttribute("data-tip-pos") || "bottom";
		el.dataset.pos = pos;
		// Measure before positioning (display is never "none", only opacity 0)
		const r = target.getBoundingClientRect();
		const t = el.getBoundingClientRect();
		let left;
		let top;
		if (pos === "right") {
			left = r.right + GAP_PX;
			top = r.top + r.height / 2 - t.height / 2;
		} else if (pos === "left") {
			left = r.left - t.width - GAP_PX;
			top = r.top + r.height / 2 - t.height / 2;
		} else if (pos === "top") {
			left = r.left + r.width / 2 - t.width / 2;
			top = r.top - t.height - GAP_PX;
		} else {
			left = r.left + r.width / 2 - t.width / 2;
			top = r.bottom + GAP_PX;
		}
		el.style.left = `${Math.round(clamp(left, 6, window.innerWidth - t.width - 6))}px`;
		el.style.top = `${Math.round(clamp(top, 6, window.innerHeight - t.height - 6))}px`;
		el.classList.add("is-visible");
	};

	const hide = () => {
		clearTimeout(timer);
		timer = null;
		current = null;
		if (tip) tip.classList.remove("is-visible");
	};

	const findTarget = (node) =>
		node && typeof node.closest === "function" ? node.closest("[data-tip]") : null;

	const onMouseOver = (event) => {
		const target = findTarget(event.target);
		if (!target || target === current) return;
		hide();
		current = target;
		timer = setTimeout(() => {
			if (current === target && target.isConnected) show(target);
		}, SHOW_DELAY_MS);
	};

	const onMouseOut = (event) => {
		if (!current) return;
		const to = event.relatedTarget;
		if (to && current.contains(to)) return;
		hide();
	};

	const onFocusIn = (event) => {
		const target = findTarget(event.target);
		if (!target) return;
		hide();
		current = target;
		show(target);
	};

	// A click usually changes the very state the tip describes ("Hide" → "Show")
	const onMouseDown = () => hide();

	root.addEventListener("mouseover", onMouseOver);
	root.addEventListener("mouseout", onMouseOut);
	root.addEventListener("focusin", onFocusIn);
	root.addEventListener("focusout", hide);
	root.addEventListener("mousedown", onMouseDown);
	window.addEventListener("scroll", hide, true);
	window.addEventListener("resize", hide);

	return () => {
		root.removeEventListener("mouseover", onMouseOver);
		root.removeEventListener("mouseout", onMouseOut);
		root.removeEventListener("focusin", onFocusIn);
		root.removeEventListener("focusout", hide);
		root.removeEventListener("mousedown", onMouseDown);
		window.removeEventListener("scroll", hide, true);
		window.removeEventListener("resize", hide);
		hide();
		if (tip) tip.remove();
		tip = null;
	};
}
