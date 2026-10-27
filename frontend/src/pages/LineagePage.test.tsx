import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { E } from '../api/sample'
import { lineagePath } from '../lib/routes'
import { currentLocation, renderApp } from '../test/render'

const cardTitles = () => screen.getAllByRole('article').map((a) => within(a).getByRole('heading').textContent)
const cardBadges = () => screen.getAllByRole('article').map((a) => a.querySelector('span')?.textContent)

describe('Decision lineage', () => {
  it('shows superseded, partial and active decisions in order', async () => {
    renderApp(lineagePath(E.maxRetries.id))
    await screen.findByRole('heading', { name: 'Decision history: max_retries' })

    expect(cardTitles()).toEqual([
      'Retry failed requests up to 10 times',
      'Cap retries at 3 and add backoff',
      'Retries off by default, opt in with a Retry object',
    ])
    expect(cardBadges()).toEqual(['Superseded', 'Partial', 'Active'])
    expect(screen.getByText('Replaced by')).toBeInTheDocument()
    expect(screen.getByText('Refined by')).toBeInTheDocument()
    expect(screen.getByText('config key')).toBeInTheDocument()
  })

  it('links every commit to a decision or says it has none', async () => {
    renderApp(lineagePath(E.maxRetries.id))
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1) // skip the header row
    expect(rows.map((r) => within(r).getAllByRole('cell').at(-1)?.textContent)).toEqual([
      'Decision 1',
      'Decision 2',
      'Decision 3',
      'No decision',
    ])
    expect(screen.getByText(/4 of 12 shown/)).toBeInTheDocument()
  })

  it('travels back in time with "View as of"', async () => {
    const user = userEvent.setup()
    renderApp(lineagePath(E.maxRetries.id))
    await screen.findByRole('heading', { name: 'Decision history: max_retries' })

    await user.click(screen.getByRole('radio', { name: '2016' }))
    expect(currentLocation()).toBe(`/lineage?entity=${E.maxRetries.id}&asof=2016`)
    await screen.findByText(/2 of 12 shown/)
    expect(cardTitles()).toHaveLength(2)
    expect(cardBadges()).toEqual(['Superseded', 'Active']) // in 2016 the cap at 3 was the rule

    await user.click(screen.getByRole('radio', { name: '2013' }))
    await screen.findByText(/1 of 12 shown/)
    expect(cardBadges()).toEqual(['Active'])

    await user.click(screen.getByRole('radio', { name: 'Today' }))
    await screen.findByText(/4 of 12 shown/)
    expect(screen.getByRole('radio', { name: 'Today' })).toHaveAttribute('aria-checked', 'true')
  })

  it('opens the workspace from a decision', async () => {
    const user = userEvent.setup()
    renderApp(lineagePath(E.maxRetries.id))
    await user.click(await screen.findByRole('link', { name: 'Cap retries at 3 and add backoff' }))
    expect(currentLocation()).toBe(`/why?entity=${E.maxRetries.id}&q=Why is max_retries like this?`)
  })
})
