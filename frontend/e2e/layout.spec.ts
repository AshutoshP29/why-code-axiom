import { expect, ID, lineage, test, why } from './fixtures'

// Every screen at the project's screen size: nothing spills sideways, and a full-page
// screenshot is attached to the HTML report for a visual check against the designs.

const PAGES: { name: string; path: string; loaded: string }[] = [
  { name: 'home', path: '/', loaded: 'Hotspots' },
  { name: 'why-workspace', path: why(ID.rebuildAuth, 'strips the Authorization header on redirect?'), loaded: 'Chain of evidence' },
  { name: 'refusal', path: why(ID.poolMaxsize, 'why is the default 10?'), loaded: 'What the graph does know' },
  { name: 'lineage', path: lineage(ID.maxRetries), loaded: 'Commits that touched this key' },
  { name: 'health', path: '/health', loaded: 'Graph contents' },
  { name: 'evaluation', path: '/evaluation', loaded: 'How a response is scored' },
  { name: 'explore', path: '/explore', loaded: 'src/requests/adapters.py' },
]

for (const p of PAGES) {
  test(`${p.name} fits the screen`, async ({ page }, testInfo) => {
    await page.goto(p.path)
    await expect(page.getByRole('heading', { name: p.loaded }).first()).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, 'page scrolls sideways').toBeLessThanOrEqual(0)
    await testInfo.attach(`${p.name}.png`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png',
    })
  })
}
