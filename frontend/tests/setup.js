/**
 * Vitest/Jest Test Setup
 *
 * Global setup for frontend tests.
 */

import { vi } from 'vitest'

// Mock frappe global object
global.frappe = {
  call: vi.fn().mockResolvedValue({ message: {} }),
  toast: vi.fn(),
  set_route: vi.fn(),
  throw: vi.fn((msg) => { throw new Error(msg) }),
  session: {
    user: 'test@example.com'
  },
  boot: {
    user: {
      email: 'test@example.com',
      name: 'Test User'
    }
  },
  _: (str) => str, // Translation mock
  parse_json: JSON.parse,
  db: {
    exists: vi.fn().mockResolvedValue(false),
    get_value: vi.fn().mockResolvedValue(null)
  }
}

// Mock window.frappe
window.frappe = global.frappe

// Reset all mocks before each test
beforeEach(() => {
  vi.clearAllMocks()
})

// Clean up after all tests
afterAll(() => {
  vi.restoreAllMocks()
})

// Console error/warn suppression for cleaner test output
const originalError = console.error
const originalWarn = console.warn

beforeAll(() => {
  console.error = (...args) => {
    // Suppress Vue warnings during tests
    if (args[0]?.includes?.('[Vue warn]')) return
    originalError.apply(console, args)
  }
  console.warn = (...args) => {
    if (args[0]?.includes?.('[Vue warn]')) return
    originalWarn.apply(console, args)
  }
})

afterAll(() => {
  console.error = originalError
  console.warn = originalWarn
})
