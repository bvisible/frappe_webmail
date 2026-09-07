/**
 * Vitest/Jest Test Setup
 *
 * Global setup for frontend tests.
 */

import { vi } from "vitest";
import { config } from "@vue/test-utils";

// Translation helper. The real app injects Frappe's `__` through
// app.config.globalProperties (main.js); components call `this.__()` and the
// templates call `__()`, so the test mounts need the same global or every
// render dies with "__ is not a function".
const translate = (str, args) => {
	if (!Array.isArray(args)) return str;
	return String(str).replace(/\{(\d+)\}/g, (m, i) => (args[i] === undefined ? m : args[i]));
};
global.__ = translate;
window.__ = translate;
config.global.mocks = { ...(config.global.mocks || {}), __: translate };

// Mock frappe global object
global.frappe = {
	call: vi.fn().mockResolvedValue({ message: {} }),
	toast: vi.fn(),
	set_route: vi.fn(),
	throw: vi.fn((msg) => {
		throw new Error(msg);
	}),
	session: {
		user: "test@example.com",
	},
	boot: {
		user: {
			email: "test@example.com",
			name: "Test User",
		},
	},
	_: (str) => str, // Translation mock
	parse_json: JSON.parse,
	db: {
		exists: vi.fn().mockResolvedValue(false),
		get_value: vi.fn().mockResolvedValue(null),
	},
};

// Mock window.frappe
window.frappe = global.frappe;

// Reset all mocks before each test
beforeEach(() => {
	vi.clearAllMocks();
});

// Clean up after all tests
afterAll(() => {
	vi.restoreAllMocks();
});

// Console error/warn suppression for cleaner test output
const originalError = console.error;
const originalWarn = console.warn;

beforeAll(() => {
	console.error = (...args) => {
		// Suppress Vue warnings during tests
		if (args[0]?.includes?.("[Vue warn]")) return;
		originalError.apply(console, args);
	};
	console.warn = (...args) => {
		if (args[0]?.includes?.("[Vue warn]")) return;
		originalWarn.apply(console, args);
	};
});

afterAll(() => {
	console.error = originalError;
	console.warn = originalWarn;
});
