import { expect, ID, lineage, ready, test, why } from './fixtures'

const RESPONSE_JSON = 'psf/requests#fn:src/requests/models.py::Response.json'

test('Question text is shown as text, never run as code', async ({ page }) => {
  const q = `<img src=x onerror=alert(1)> "quotes" & ' apostrophes 🙂`
  await page.goto(why(RESPONSE_JSON, q))
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(q)
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveValue(q)
  expect(await page.locator('main img').count()).toBe(0)
})

test('A very long question wraps instead of breaking the layout', async ({ page }) => {
  const q = `Why ${'is this really necessary and '.repeat(60)}?`
  await page.goto(why(RESPONSE_JSON, q))
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(q)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('A blank question falls back to the default question', async ({ page }) => {
  await page.goto('/')
  const ask = page.getByRole('search', { name: 'Ask why' })
  await ask.getByRole('button', { name: 'Pick an entity' }).click()
  await page.getByRole('combobox').fill('verify')
  await page.getByRole('option', { name: /verify/ }).first().click()
  await ask.getByRole('textbox', { name: 'Your question' }).fill('    ')
  await ask.getByRole('button', { name: 'Trace' }).click()
  await expect(page).toHaveURL(/\/why\?/)
  expect(new URL(page.url()).searchParams.get('q')).toBe('Why is verify like this?')
})

test('A blank question with nothing picked cannot be sent', async ({ page }) => {
  await page.goto('/')
  const ask = page.getByRole('search', { name: 'Ask why' })
  await ask.getByRole('textbox', { name: 'Your question' }).fill('    ')
  await expect(ask.getByRole('button', { name: 'Trace' })).toBeDisabled()
  await ask.getByRole('textbox', { name: 'Your question' }).press('Enter')
  await expect(page).toHaveURL(/\/$/)
})

test('Clearing a picked entity sends the question on its own', async ({ page }) => {
  await page.goto('/')
  const ask = page.getByRole('search', { name: 'Ask why' })
  await ask.getByRole('button', { name: 'Pick an entity' }).click()
  await page.getByRole('combobox').fill('verify')
  await page.getByRole('option', { name: /verify/ }).first().click()
  await ask.getByRole('textbox', { name: 'Your question' }).fill('why did requests drop chardet?')
  await ask.getByRole('button', { name: 'Clear entity' }).click()
  await ask.getByRole('button', { name: 'Trace' }).click()

  await expect(page.getByText('No matching item')).toBeVisible()
  const params = new URL(page.url()).searchParams
  expect(params.has('entity')).toBe(false)
  expect(params.get('q')).toBe('why did requests drop chardet?')
})

test('Markup in a plain question is shown as text, never run', async ({ page }) => {
  const q = `<img src=x onerror=alert(1)> "quotes" & ' apostrophes 🙂`
  await page.goto(why(null, q))
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(q)
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveValue(q)
  expect(await page.locator('main img').count()).toBe(0)
})

test('Double-clicking "Flag as missing context" adds one flag, not two', async ({ page }) => {
  await page.goto(why(ID.poolMaxsize, 'q'))
  await page.getByRole('button', { name: 'Flag as missing context' }).dblclick()
  await expect(page.getByRole('button', { name: 'Flagged' })).toBeVisible()
  await page.getByRole('link', { name: 'Graph health' }).click()
  await expect(page.getByRole('link', { name: /HTTPAdapter\.pool_maxsize/ })).toContainText('3 flags')
})

test('Switching "View as of" quickly ends on the last choice', async ({ page }) => {
  await page.goto(lineage(ID.maxRetries))
  await expect(page.getByRole('article')).toHaveCount(3)
  await page.getByRole('radio', { name: '2013' }).click()
  await page.getByRole('radio', { name: '2016' }).click()
  await page.getByRole('radio', { name: 'Today' }).click()
  await page.getByRole('radio', { name: '2013' }).click()
  await expect(page.getByRole('radio', { name: '2013' })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByText(/1 of 12 shown/)).toBeVisible()
})

test('A search that matches nothing says so', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('search', { name: 'Ask why' }).getByRole('button', { name: 'Pick an entity' }).click()
  await page.getByRole('combobox').fill('zzzz')
  await expect(page.getByText('Nothing called “zzzz” in psf/requests')).toBeVisible()
})

test('A GitHub link pasted into the repo search finds the repo', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  const panel = page.getByRole('dialog', { name: 'Your repositories' })
  await panel.getByRole('textbox').fill('https://github.com/psf/requests/tree/main')
  await expect(panel.getByRole('listitem')).toHaveCount(1)
  await expect(panel.getByRole('listitem')).toContainText('psf/requests')
})

test('Adding a repo that is already there is refused clearly', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await page.getByRole('button', { name: /Add a repository/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a repository' })
  await dialog.getByRole('textbox').fill('psf/requests')
  await dialog.getByRole('button', { name: 'Check' }).click()
  await dialog.getByRole('button', { name: 'Start ingestion' }).click()
  await expect(dialog.getByRole('alert')).toHaveText('psf/requests is already added')
})

test('A link that is not a repository is explained', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: /Switch repository/ }).click()
  await page.getByRole('button', { name: /Add a repository/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a repository' })
  await dialog.getByRole('textbox').fill('https://gitlab.com/some/thing')
  await dialog.getByRole('button', { name: 'Check' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Paste a GitHub link like github.com/owner/name')
  await expect(dialog.getByRole('button', { name: 'Start ingestion' })).toBeDisabled()
})

test('Back and Forward keep each page as it was', async ({ page }) => {
  await page.goto(lineage(ID.maxRetries, 2016))
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.getByRole('link', { name: 'Cap retries at 3 and add backoff' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Why is max_retries off by default?')
  await page.goBack()
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.goForward()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Why is max_retries off by default?')
})
