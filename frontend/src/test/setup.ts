import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
  // The chosen repo must not leak between tests. Tests that run in Node have no window.
  if (typeof window !== 'undefined') window.localStorage.clear()
})
