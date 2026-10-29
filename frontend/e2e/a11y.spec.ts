import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { expect, ID, lineage, ready, test, why } from './fixtures'

// Automatic accessibility scan (axe-core) against WCAG 2.1 A and AA on every screen and dialog.

// A full-page scan is slow, and the first one in a browser also loads axe-core: on a busy laptop
// that went past the 30-second default with the page fully loaded. The checks are unchanged.
test.describe.configure({ timeout: 60_000 })

async function expectNoViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const found = results.violations.map(
    (v) =>
      `${v.id} [${v.impact}] ${v.help}: ${v.nodes
        .slice(0, 4)
        .map((n) => n.target.join(' '))
        .join(' ; ')}${v.nodes.length > 4 ? ` (+${v.nodes.length - 4} more)` : ''}`,
  )
  expect(found).toEqual([])
}

const PAGES: { name: string; path: string; loaded: string }[] = [
  { name: 'Home', path: '/', loaded: 'Hotspots' },
  { name: 'Why Workspace', path: why(ID.rebuildAuth, 'q'), loaded: 'Chain of evidence' },
  { name: 'Refusal', path: why(ID.checkCompatibility, 'q'), loaded: 'What the graph does know' },
  { name: 'Hedged answer', path: why(ID.timeout, 'q'), loaded: 'Low confidence: check before relying on this' },
  { name: 'Plain question, matched', path: why(null, 'why does rebuild_auth strip the header?'), loaded: 'Chain of evidence' },
  { name: 'Plain question, no match', path: why(null, 'why did requests drop python 2 support?'), loaded: 'What the graph does know' },
  { name: 'Decision lineage', path: lineage(ID.maxRetries), loaded: 'Commits that touched this key' },
  { name: 'Graph health', path: '/health', loaded: 'Graph contents' },
  { name: 'Evaluation', path: '/evaluation', loaded: 'How a response is scored' },
  { name: 'Explore', path: '/explore', loaded: 'src/requests/adapters.py' },
  { name: 'Not found', path: '/nope', loaded: 'This page does not exist' },
]

for (const p of PAGES) {
  test(`${p.name} has no WCAG A/AA violations`, async ({ page }) => {
    await page.goto(p.path)
    await expect(page.getByRole('heading', { name: p.loaded }).first()).toBeVisible()
    await expectNoViolations(page)
  })
}

test('Repo switcher has no violations', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await expect(page.getByRole('dialog', { name: 'Your repositories' })).toBeVisible()
  await expectNoViolations(page)
})

test('Entity picker with results has no violations', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('search', { name: 'Ask why' }).getByRole('button', { name: 'Pick an entity' }).click()
  await page.getByRole('combobox').fill('session')
  await expect(page.getByRole('option').first()).toBeVisible()
  await expectNoViolations(page)
})

test('"Pick a different entity" list has no violations', async ({ page }) => {
  await page.goto(why(null, 'why does rebuild_auth strip the header?'))
  await page.getByRole('button', { name: 'Pick a different entity' }).click()
  await page.getByRole('combobox').fill('session')
  await expect(page.getByRole('option').first()).toBeVisible()
  await expectNoViolations(page)
})

test('Ask bar with a picked entity and its clear button has no violations', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('search', { name: 'Ask why' }).getByRole('button', { name: 'Pick an entity' }).click()
  await page.getByRole('combobox').fill('verify')
  await page.getByRole('option').first().click()
  await expect(page.getByRole('button', { name: 'Clear entity' })).toBeVisible()
  await expectNoViolations(page)
})

test('Add repository dialog with a checked repo has no violations', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await page.getByRole('button', { name: /Add a repository/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a repository' })
  await dialog.getByRole('textbox').fill('encode/httpx')
  await dialog.getByRole('button', { name: 'Check' }).click()
  await expect(dialog.getByText('Public repository found')).toBeVisible()
  await expectNoViolations(page)
})

test('Ask-the-maintainer dialog has no violations', async ({ page }) => {
  await page.goto(why(ID.rebuildAuth, 'q'))
  await page.getByRole('button', { name: 'Ask @maintainer_a' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectNoViolations(page)
})

test('Ingestion screen has no violations', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await page.getByRole('dialog', { name: 'Your repositories' }).getByRole('button', { name: /encode\/httpx/ }).click()
  await expect(page.getByRole('heading', { name: 'Reading encode/httpx' })).toBeVisible()
  await expectNoViolations(page)
})
