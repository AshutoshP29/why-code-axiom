import { defineConfig, devices } from '@playwright/test'

// Browser QA. Uses the Edge and Chrome already installed, so nothing big is downloaded.
//   sample: the production build on sample data (what the demo runs)
//   api:    the dev server with VITE_API_URL=/api; tests answer /api/* themselves to act as the backend
// 127.0.0.1, not localhost: on Windows, Chrome sometimes never got the first page from a server
// bound to "localhost" (about 1 run in 50), while the same tests passed in Edge.
const SAMPLE = 'http://127.0.0.1:4173'
const API = 'http://127.0.0.1:4174'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // More than 4 browsers at once overloaded a 12-thread laptop and caused timeouts unrelated to
  // the app. A test that passes only on its retry is still listed as "flaky" in the report.
  workers: 4,
  retries: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    {
      name: 'edge',
      use: { ...devices['Desktop Edge'], channel: 'msedge', baseURL: SAMPLE },
      testIgnore: /api\.spec/,
    },
    {
      name: 'chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome', baseURL: SAMPLE },
      testIgnore: /api\.spec/,
    },
    {
      name: 'phone',
      use: { ...devices['Pixel 7'], channel: 'msedge', baseURL: SAMPLE },
      testMatch: /(flows|layout)\.spec/,
    },
    {
      name: 'api',
      use: { ...devices['Desktop Edge'], channel: 'msedge', baseURL: API },
      testMatch: /api\.spec/,
    },
  ],
  webServer: [
    {
      command: 'npm run build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort',
      url: SAMPLE,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 4174 --strictPort',
      url: API,
      env: { VITE_API_URL: '/api' },
      reuseExistingServer: !process.env.CI,
    },
  ],
})
