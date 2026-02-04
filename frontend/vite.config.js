import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "path";

export default defineConfig({
	plugins: [vue()],
	define: {
		"process.env.NODE_ENV": JSON.stringify("production"),
	},
	build: {
		outDir: "../frappe_webmail/public/js",
		emptyOutDir: false,
		// Disable sourcemaps in production to reduce memory usage
		sourcemap: false,
		lib: {
			entry: path.resolve(__dirname, "src/main.js"),
			name: "FrappeWebmail",
			fileName: "frappe_webmail.bundle",
			formats: ["iife"],
		},
		rollupOptions: {
			output: {
				assetFileNames: "frappe_webmail.[ext]",
			},
		},
		cssCodeSplit: false,
	},
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	test: {
		globals: true,
		environment: "happy-dom",
		setupFiles: ["./tests/setup.js"],
		include: ["tests/**/*.spec.js"],
		coverage: {
			provider: "v8",
			reporter: ["text", "json", "html"],
			include: ["src/**/*.vue", "src/**/*.js"],
		},
	},
});
