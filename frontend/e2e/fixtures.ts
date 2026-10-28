import { expect, test as base, type Page } from '@playwright/test'

// Ids from the sample data (src/api/sample.ts).
export const ID = {
  rebuildAuth: 'psf/requests#fn:src/requests/sessions.py::Session.rebuild_auth',
  resolveRedirects: 'psf/requests#fn:src/requests/sessions.py::Session.resolve_redirects',
  maxRetries: 'psf/requests#cfg:max_retries',
  poolMaxsize: 'psf/requests#cfg:pool_maxsize',
  timeout: 'psf/requests#cfg:timeout', // the hedged sample
}

/** entityId null: a plain question, as typed with nothing picked. */
export const why = (entityId: string | null, q: string) =>
  `/why?${new URLSearchParams(entityId ? { entity: entityId, q } : { q })}`
export const lineage = (entityId: string, asof?: number) =>
  `/lineage?${new URLSearchParams(asof ? { entity: entityId, asof: String(asof) } : { entity: entityId })}`

/**
 * Every test fails on any console error or uncaught exception, unless the test lists it as
 * expected. Google Fonts is answered locally so runs do not depend on the network.
 */
export const test = base.extend<{ allowConsoleErrors: RegExp[]; guard: void }>({
  allowConsoleErrors: [[], { option: true }],
  guard: [
    async ({ page, allowConsoleErrors }, use) => {
      const problems: string[] = []
      page.on('console', (msg) => {
        if (msg.type() === 'error' && !allowConsoleErrors.some((re) => re.test(msg.text()))) {
          problems.push(`console: ${msg.text()}`)
        }
      })
      page.on('pageerror', (err) => problems.push(`exception: ${err.message}`))
      page.on('dialog', (dialog) => {
        problems.push(`unexpected browser dialog: ${dialog.message()}`)
        void dialog.dismiss()
      })
      await page.route(/fonts\.(googleapis|gstatic)\.com/, (route) =>
        route.fulfill({ status: 200, contentType: 'text/css', body: '' }),
      )
      await use()
      expect(problems, 'console errors, exceptions or dialogs during the test').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

/**
 * Wait until the app has loaded the repo list. The switcher is there while it loads, so wait for it
 * to name a repo ("current: psf/requests"), not just for the button.
 */
export async function ready(page: Page) {
  await expect(page.getByRole('button', { name: /Switch repository, current:\s*[\w.-]+\/[\w.-]+/ })).toBeVisible()
}
