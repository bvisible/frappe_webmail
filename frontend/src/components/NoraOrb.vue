<template>
	<img
		class="wm-nora-orb"
		:src="src"
		data-nora-icon="auto"
		alt=""
		aria-hidden="true"
		draggable="false"
		:width="size"
		:height="size"
		:style="{ width: size + 'px', height: size + 'px' }"
	/>
</template>

<script>
// Nora's icon, the nora app's orb (06.10: one Nora icon everywhere, in place of the spark).
// On a dark desk, nora_cockpit_orb.js switches every image marked data-nora-icon="auto"
// to the dark variant; the first paint already picks it.
export default {
	name: "NoraOrb",
	props: { size: { type: Number, default: 18 } },
	computed: {
		src() {
			return document.documentElement.getAttribute("data-theme") === "dark"
				? "/assets/nora/images/nora-orb-dark.svg"
				: "/assets/nora/images/nora-orb.svg";
		},
	},
};
</script>

<style scoped>
/* max-width none: the desk caps images at their box's width, which made an oval of the orb. */
.wm-nora-orb {
	display: block;
	flex: none;
	max-width: none;
	pointer-events: none;
}
</style>
