import { expect, ready, test } from './fixtures'

// The Knowledge risk tab, on the sample data: it loads, both tables are filled, and a row
// leads to the answer screen.

test('Knowledge risk loads with both tables', async ({ page }) => {
  await page.goto('/risk')
  await expect(page.getByRole('heading', { name: 'Knowledge risk' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Nobody left to ask' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Changed often, never explained' })).toBeVisible()

  const orphaned = page.getByRole('table').first()
  await expect(orphaned.getByText('HTTPDigestAuth.build_digest_header')).toBeVisible()
  await expect(orphaned.getByText('inactive').first()).toBeVisible()
  await expect(page.getByRole('table').nth(1).getByText(/check_compatibility/)).toBeVisible()
})

test('the nav reaches it and a row asks why', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Knowledge risk' }).click()

  const row = page.getByRole('row').filter({ hasText: 'build_digest_header' })
  await row.getByRole('link', { name: 'Ask why' }).click()
  await expect(page).toHaveURL(/\/why\?entity=/)
})
