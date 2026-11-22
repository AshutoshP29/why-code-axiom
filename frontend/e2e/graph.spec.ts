import AxeBuilder from '@axe-core/playwright'
import { expect, ID, test } from './fixtures'

// The Graph tab on the sample data: the drawing loads, a node opens in the side panel, and the
// page passes the same WCAG scan as every other screen.

// The layout runs in the page while the test works; on a busy laptop a test took over the 30 s
// default with every step passing, as the a11y scans did.
test.describe.configure({ timeout: 60_000 })

test('Graph loads the sample graph and opens a node', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Graph', exact: true }).click()
  await expect(page).toHaveURL(/\/graph$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Graph' })).toBeVisible()
  await expect(page.getByText(/^\d+ nodes, \d+ links$/)).toBeVisible()
  await expect(page.getByRole('list', { name: 'Legend' })).toContainText('Decision')

  const node = page.getByRole('button', { name: 'Response.apparent_encoding, function' })
  await expect(node).toBeVisible()
  // The layout is still moving; the keyboard does not need the node to keep still.
  await node.focus()
  await page.keyboard.press('Enter')
  const panel = page.getByRole('complementary', { name: 'Selected node' })
  await expect(panel.getByRole('heading', { name: 'Response.apparent_encoding' })).toBeVisible()
  await expect(panel.getByRole('link', { name: 'Ask why' })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, 'page scrolls sideways').toBeLessThanOrEqual(0)
  await testInfo.attach('graph.png', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
})

test('Graph focuses on a searched item', async ({ page }) => {
  await page.goto('/graph')
  await page.getByRole('searchbox', { name: 'Search the graph' }).fill('apparent')
  await page.getByRole('list', { name: 'Search results' }).getByRole('button', { name: /Response\.apparent_encoding/ }).click()
  await expect(page.getByText(/Two links around/)).toBeVisible()
  expect(new URL(page.url()).searchParams.get('focus')).toBe(ID.apparentEncoding)
  await expect(page.getByRole('complementary', { name: 'Selected node' })).toContainText('Response.apparent_encoding')
})

test('Graph has no WCAG A/AA violations', async ({ page }) => {
  await page.goto('/graph')
  await expect(page.getByRole('list', { name: 'Legend' })).toBeVisible()
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' ; ')}`)).toEqual([])
})
