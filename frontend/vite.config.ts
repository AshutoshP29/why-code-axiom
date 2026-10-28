import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import type { ProxyOptions } from 'vite'
import { defineConfig } from 'vitest/config'

// The WhyCode API (FastAPI), with every path under /api. 127.0.0.1, not "localhost": Node can
// resolve localhost to ::1 first, and uvicorn listens on 127.0.0.1 only by default.
const API_TARGET = 'http://127.0.0.1:8000'

/** Run with VITE_API_URL=/api to reach the API through the dev server, so no CORS is needed. */
const apiProxy: ProxyOptions = {
  target: API_TARGET,
  changeOrigin: true,
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': apiProxy } }, // `vite preview` uses it too
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // e2e/ belongs to Playwright
    include: ['src/**/*.test.{ts,tsx}', 'vite.config.test.ts'],
  },
})
