// The webmail on a bench of its own: the real Vue code, invented mailboxes, the desk's real theme. For looking at
// the screen, and comparing it with the design boards, without opening anyone's mailbox. See README.md here.
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "path";

export default defineConfig({
	root: __dirname,
	plugins: [vue()],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "../src"),
		},
	},
	server: {
		host: "127.0.0.1",
		port: 5199,
		strictPort: true,
		fs: { allow: [path.resolve(__dirname, "../..")] },
	},
});
