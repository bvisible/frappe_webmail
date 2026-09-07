import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "path";

export default defineConfig(({ mode }) => ({
	plugins: [vue()],
	// The IIFE bundle runs in the browser where `process` does not exist, so the
	// build inlines NODE_ENV. Never in tests: vitest would then load Vue's
	// production build, whose devtools hooks are stripped -> `wrapper.emitted()`
	// records nothing and every emit assertion fails.
	define: mode === "test" ? {} : { "process.env.NODE_ENV": JSON.stringify("production") },
	build: {
		outDir: "../frappe_webmail/public/js",
		emptyOutDir: false,
		// Disable sourcemaps in production to reduce memory usage
		sourcemap: false,
		// Use modern JS target to speed up build (no polyfills)
		target: "esnext",
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
}));
