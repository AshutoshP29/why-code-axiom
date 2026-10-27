import { readFile } from 'node:fs/promises'
import { expect, ID, lineage, ready, test, why } from './fixtures'

// The user journey from the FigJam flow chart, one test per path.

test('Home → pick an entity → ask → Why Workspace with linked evidence', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Why is the code like this?' })).toBeVisible()
  const ask = page.getByRole('search', { name: 'Ask why' })
  await expect(ask.getByRole('button', { name: 'Trace' })).toBeDisabled()

  await ask.getByRole('button', { name: 'Pick an entity' }).click()
  await page.getByRole('combobox', { name: /Search functions/ }).fill('rebuild')
  await page.getByRole('option', { name: /Session\.rebuild_auth/ }).click()
  await ask.getByRole('textbox', { name: 'Your question' }).fill('why strip the header?')
  await ask.getByRole('button', { name: 'Trace' }).click()

  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Why does Session.rebuild_auth strip the Authorization header on redirect?',
  )
  expect(new URL(page.url()).searchParams.get('entity')).toBe(ID.rebuildAuth)
  await expect(page.getByText('Active decision', { exact: true })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('An earlier decision was overridden')

  const chain = page.getByRole('list', { name: 'Evidence, from the report to the code' })
  await expect(chain.getByRole('listitem')).toHaveCount(4)
  for (const link of await chain.getByRole('link').all()) {
    await expect(link).toHaveAttribute('target', '_blank')
    await expect(link).toHaveAttribute('rel', /noreferrer/)
    await expect(link).toHaveAttribute('href', /^https:\/\/github\.com\//)
  }
})

test('Home → plain question, nothing picked → matched answer → pick a different entity', async ({ page }) => {
  await page.goto('/')
  const ask = page.getByRole('search', { name: 'Ask why' })
  await ask.getByRole('textbox', { name: 'Your question' }).fill('why does rebuild_auth strip the header?')
  await ask.getByRole('button', { name: 'Trace' }).click()

  const match = page.getByText(/^Matched to/)
  await expect(match).toHaveText('Matched to Session.rebuild_auth (score 0.90) from your question.')
  expect(new URL(page.url()).searchParams.has('entity')).toBe(false)
  await expect(page.getByText('Active decision', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Pick a different entity' }).click()
  await page.getByRole('combobox').fill('resolve')
  await page.getByRole('option', { name: /Session\.resolve_redirects/ }).click()
  await expect(page.getByText('No recorded decision')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('entity')).toBe(ID.resolveRedirects)
  await expect(match).toHaveCount(0)

  await page.goBack()
  await expect(match).toBeVisible()
})

test('Plain question that matches nothing → refusal with no item → pick one and ask again', async ({ page }) => {
  await page.goto('/')
  const question = page.getByRole('search', { name: 'Ask why' }).getByRole('textbox', { name: 'Your question' })
  await question.fill('why did requests drop chardet?')
  await question.press('Enter')

  await expect(page.getByText('No matching item')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toHaveCount(0)
  await expect(page.getByText(/No function, file or config key in the graph matches/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'PR #1565: only strip auth when the host changes' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Flag as missing context' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Pick an item to ask about' }).click()
  await page.getByRole('combobox').fill('max_r')
  await page.getByRole('option', { name: /max_retries/ }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Why is max_retries off by default?')
})

test('Showcase → hedged answer → warning over a full answer → decision history', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: /Why is there no default timeout\?/ }).click()

  const warning = page.getByRole('region', { name: 'Low confidence: check before relying on this' })
  await expect(warning).toContainText('Only one source supports this')
  await expect(warning.getByRole('list', { name: 'What held confidence back' }).getByRole('listitem')).toHaveCount(2)
  await expect(page.getByText('Low confidence', { exact: true })).toBeVisible()
  await expect(page.getByText('Refuses below 40% · warns below 70%')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Evidence, from the report to the code' }).getByRole('listitem')).toHaveCount(2)
  await expect(page.getByRole('list', { name: 'Confidence factors' }).getByRole('listitem').first()).toContainText(
    'Evidence directness',
  )

  await page.getByRole('link', { name: 'Decision history →' }).click()
  await expect(page.getByRole('heading', { name: 'Decision history: timeout' })).toBeVisible()
})

test('Example chip → refusal → flag as missing context → gap queue → evaluation', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Why is pool_maxsize 10?', exact: true }).click()
  await expect(page.getByText('No recorded decision')).toBeVisible()
  await expect(page.getByText('Refuses below 40% · warns below 70%')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open commit history' })).toHaveAttribute(
    'href',
    'https://github.com/psf/requests/commits/main/src/requests/adapters.py',
  )

  await page.getByRole('button', { name: 'Flag as missing context' }).click()
  await expect(page.getByRole('button', { name: 'Flagged' })).toBeDisabled()
  await page.getByRole('link', { name: 'Graph health' }).click()
  await expect(page.getByRole('link', { name: /HTTPAdapter\.pool_maxsize/ })).toContainText('3 flags')

  await page.getByRole('link', { name: /See every question and result/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Evaluation' })).toBeVisible()
})

test('Hotspot → lineage → time travel → decision → workspace, and Back retraces', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: /max_retries 4 reversals/ }).click()
  await expect(page.getByRole('heading', { name: 'Decision history: max_retries' })).toBeVisible()
  const cards = page.getByRole('article')
  await expect(cards).toHaveCount(3)

  await page.getByRole('radio', { name: '2016' }).click()
  await expect(cards).toHaveCount(2)
  await expect(page).toHaveURL(/asof=2016/)
  await page.getByRole('radio', { name: '2013' }).click()
  await expect(cards).toHaveCount(1)
  await page.getByRole('radio', { name: 'Today' }).click()
  await expect(cards).toHaveCount(3)

  await page.getByRole('link', { name: 'Cap retries at 3 and add backoff' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Why is max_retries off by default?')
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Decision history: max_retries' })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { level: 1, name: 'Why is the code like this?' })).toBeVisible()
})

test('Graph node → re-ask about the neighbouring entity', async ({ page }) => {
  await page.goto(why(ID.rebuildAuth, 'q'))
  await page.getByRole('button', { name: 'Ask about Session.resolve_redirects' }).click()
  await expect(page.getByText('No recorded decision')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('entity')).toBe(ID.resolveRedirects)
})

test('Who to ask → message for the maintainer is copied', async ({ page, context, baseURL }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseURL })
  await page.goto(why(ID.rebuildAuth, 'q'))
  await page.getByRole('button', { name: 'Ask @maintainer_b' }).click()
  const dialog = page.getByRole('dialog', { name: 'Ask @maintainer_b' })
  await expect(dialog).toContainText('No longer active here')
  await dialog.getByRole('button', { name: 'Copy message' }).click()
  await expect(dialog.getByRole('button', { name: 'Copied' })).toBeVisible()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied).toContain("I'm looking at Session.rebuild_auth in psf/requests")
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('Switch repo → another repo with no content yet', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await page.getByRole('dialog', { name: 'Your repositories' }).getByRole('button', { name: /pallets\/flask/ }).click()
  await expect(page.getByText('No reversed rules found yet.')).toBeVisible()
  await expect(page.getByRole('button', { name: /Switch repository/ })).toContainText('pallets/flask')
})

test('Switch repo → one still being read → ask now with partial history', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await page.getByRole('dialog', { name: 'Your repositories' }).getByRole('button', { name: /encode\/httpx/ }).click()
  await expect(page.getByRole('heading', { name: 'Reading encode/httpx' })).toBeVisible()
  await page.getByRole('button', { name: 'Ask now (partial history)' }).click()
  await expect(page.getByText(/Partial history: encode\/httpx is still being read/)).toBeVisible()
})

test('Add a repository → check → start → ingestion moves forward', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  const panel = page.getByRole('dialog', { name: 'Your repositories' })
  await panel.getByRole('textbox').fill('https://github.com/someone/project')
  await panel.getByRole('button', { name: /Add a repository/ }).click()

  const dialog = page.getByRole('dialog', { name: 'Add a repository' })
  await expect(dialog.getByRole('textbox')).toHaveValue('https://github.com/someone/project')
  await dialog.getByRole('button', { name: 'Check' }).click()
  await expect(dialog.getByText('Public repository found')).toBeVisible()
  await dialog.getByRole('button', { name: 'Start ingestion' }).click()

  await expect(page.getByRole('heading', { name: 'Reading someone/project' })).toBeVisible()
  const fetchBar = page.getByRole('progressbar', { name: 'Fetch history progress' })
  if (await fetchBar.isVisible()) {
    // The bar is hidden on phones; on wider screens it must move as the run goes on.
    await expect.poll(async () => Number(await fetchBar.getAttribute('aria-valuenow')), { timeout: 15_000 }).toBeGreaterThan(0)
  }
})

test('Graph health → export report downloads the numbers', async ({ page }) => {
  await page.goto('/health')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export report' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe('whycode-health-psf-requests.json')
  const report = JSON.parse(await readFile(await file.path(), 'utf8'))
  expect(report.repo).toBe('psf/requests')
  expect(report.stages).toHaveLength(5)
  expect(report.evaluation.measured).toBe(false)
})

test('Graph health → re-run ingestion (after confirming) → progress on Home', async ({ page }) => {
  await page.goto('/health')
  await page.getByRole('button', { name: 'Re-run ingestion' }).click()
  const dialog = page.getByRole('dialog', { name: 'Re-run ingestion for psf/requests?' })
  await dialog.getByRole('button', { name: 'Re-run ingestion' }).click()
  await expect(page.getByRole('heading', { name: 'Reading psf/requests' })).toBeVisible()
})

test('Deep links survive a reload', async ({ page }) => {
  await page.goto(lineage(ID.maxRetries, 2016))
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.reload()
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByRole('radio', { name: '2016' })).toHaveAttribute('aria-checked', 'true')
})

test('Bad addresses are handled', async ({ page }) => {
  await page.goto('/no-such-page')
  await expect(page.getByRole('heading', { name: 'This page does not exist' })).toBeVisible()

  await page.goto('/why')
  await expect(page.getByRole('heading', { level: 1, name: 'Why is the code like this?' })).toBeVisible()

  await page.goto(why('psf/requests#fn:src/requests/nope.py::nope', 'q'))
  await expect(page.getByRole('alert')).toContainText('That item is not in the graph for this repository')
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
})
