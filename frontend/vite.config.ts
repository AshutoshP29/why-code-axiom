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
  configure(proxy, options) {
    // With the backend down, answer as FastAPI would, so the app shows this instead of "Bad Gateway".
    proxy.on('error', (_err, _req, res) => {
      if (!('writeHead' in res) || res.headersSent) return
      res.writeHead(502, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({
          detail: `The WhyCode API is not reachable at ${String(options.target)}. Start the backend, or run without VITE_API_URL to use sample data.`,
        }),
      )
    })
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': apiProxy } }, // `vite preview` uses it too
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // e2e/ belongs to Playwright
    include: ['src/**/*.test.{ts,tsx}', 'vite.config.test.ts'],
    // As in playwright.config.ts: with 12 workers on a 12-thread laptop, the first screen test in a
    // file took over the 5 s limit and failed at random.
    maxWorkers: 4,
  },
})
