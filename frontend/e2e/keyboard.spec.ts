import type { Locator, Page } from '@playwright/test'
import { expect, ID, lineage, ready, test, why } from './fixtures'

// Everything here is done without the mouse.

/** Press Tab until `target` has focus (at most `limit` presses). */
async function tabTo(page: Page, target: Locator, limit = 40) {
  for (let i = 0; i < limit; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return
    await page.keyboard.press('Tab')
  }
  throw new Error(`could not reach ${target} with Tab`)
}

test('Skip link jumps past the top bar', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to content' })
  await expect(skip).toBeFocused()
  await expect(skip).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main')).toBeFocused()
})

test('Ask a question with the keyboard only', async ({ page }) => {
  await page.goto('/')
  const ask = page.getByRole('search', { name: 'Ask why' })
  await tabTo(page, ask.getByRole('button', { name: 'Pick an entity' }))
  await page.keyboard.press('Enter')
  await expect(page.getByRole('combobox')).toBeFocused()
  await page.keyboard.type('max_r')
  await expect(page.getByRole('option', { name: /max_retries/ })).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(ask.getByRole('textbox', { name: 'Your question' })).toBeFocused()
  await page.keyboard.type('why is it off?')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Why is max_retries off by default?')
})

test('Entity picker: arrows move through results, Escape closes and returns focus', async ({ page }) => {
  await page.goto('/')
  const ask = page.getByRole('search', { name: 'Ask why' })
  const trigger = ask.getByRole('button', { name: 'Pick an entity' })
  await tabTo(page, trigger)
  await page.keyboard.press('Enter')
  await page.keyboard.type('session')
  const options = page.getByRole('option')
  await expect(options.first()).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowDown')
  await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('combobox')).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('Dialogs keep focus inside and give it back on close', async ({ page }) => {
  await page.goto(why(ID.rebuildAuth, 'q'))
  const person = page.getByRole('button', { name: 'Ask @maintainer_a' })
  // Reaching the card by Tab takes ~35 presses (covered by the graph-node test); start on it.
  await person.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Ask @maintainer_a' })
  await expect(dialog).toBeVisible()
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press(i % 3 === 2 ? 'Shift+Tab' : 'Tab')
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(person).toBeFocused()
})

test('Repo switcher closes on Escape and returns focus', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  const trigger = page.getByRole('button', { name: /Switch repository/ })
  await tabTo(page, trigger)
  await page.keyboard.press('Enter')
  const panel = page.getByRole('dialog', { name: 'Your repositories' })
  await expect(panel.getByRole('textbox')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('"View as of" moves with the arrow keys', async ({ page }) => {
  await page.goto(lineage(ID.maxRetries))
  const today = page.getByRole('radio', { name: 'Today' })
  await tabTo(page, today)
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByRole('radio', { name: '2016' })).toBeFocused()
  await expect(page.getByRole('radio', { name: '2016' })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('article')).toHaveCount(2)
})

test('Graph nodes can be reached and used from the keyboard', async ({ page }) => {
  await page.goto(why(ID.rebuildAuth, 'q'))
  await tabTo(page, page.getByRole('button', { name: 'Ask about Session.resolve_redirects' }), 80)
  await page.keyboard.press('Enter')
  await expect(page.getByText('No recorded decision')).toBeVisible()
})

test('Focus is always visible on buttons and links', async ({ page }) => {
  await page.goto('/')
  await ready(page)
  // Tab through Home's own links too, not off the end of a page that is still loading.
  await expect(page.getByRole('heading', { name: 'Hotspots' })).toBeVisible()
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab')
    const style = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement
      const s = getComputedStyle(el)
      return { tag: el.tagName, outline: s.outlineStyle, width: s.outlineWidth, text: el.textContent?.trim().slice(0, 30) }
    })
    if (style.tag === 'INPUT') continue // inputs show focus on their surrounding bar instead
    expect(style.outline, `focus outline on ${style.tag} "${style.text}"`).not.toBe('none')
  }
})
