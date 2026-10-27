import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { E } from '../api/sample'
import { currentLocation, renderApp } from '../test/render'

describe('Home', () => {
  it('shows the hero, the graph summary, hotspots and examples', async () => {
    renderApp('/')
    expect(await screen.findByRole('heading', { level: 1, name: 'Why is the code like this?' })).toBeInTheDocument()

    const summary = await screen.findByRole('region', { name: 'Graph summary' })
    for (const value of ['2,140', '312', '9,860', '14.2k']) {
      expect(within(summary).getByText(value)).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: /max_retries\s*4 reversals/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Why is pool_maxsize 10?' })).toBeInTheDocument()
    expect(screen.getByText('Sample data')).toBeInTheDocument()
  })

  it('asks only after an entity is picked', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const ask = await screen.findByRole('search', { name: 'Ask why' })
    const trace = within(ask).getByRole('button', { name: 'Trace' })
    expect(trace).toBeDisabled()

    await user.click(within(ask).getByRole('button', { name: 'Pick an entity' }))
    await user.type(screen.getByRole('combobox', { name: /search functions/i }), 'rebuild')
    await user.click(await screen.findByRole('option', { name: /Session\.rebuild_auth/ }))

    expect(trace).toBeEnabled()
    await user.type(within(ask).getByRole('textbox', { name: 'Your question' }), 'why strip the header?')
    await user.click(trace)
    expect(currentLocation()).toBe(`/why?entity=${E.rebuildAuth.id}&q=why strip the header?`)
  })

  it('picks an entity with the keyboard', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const ask = await screen.findByRole('search', { name: 'Ask why' })
    await user.click(within(ask).getByRole('button', { name: 'Pick an entity' }))
    await user.type(screen.getByRole('combobox'), 'max_r')
    await screen.findByRole('option', { name: /max_retries/ })
    await user.keyboard('{Enter}')

    expect(within(ask).getByRole('button', { name: /Entity: max_retries/ })).toBeInTheDocument()
    expect(within(ask).getByRole('textbox', { name: 'Your question' })).toHaveFocus()
  })

  it('opens the decision history from a hotspot', async () => {
    const user = userEvent.setup()
    renderApp('/')
    await user.click(await screen.findByRole('link', { name: /max_retries\s*4 reversals/ }))
    expect(currentLocation()).toBe(`/lineage?entity=${E.maxRetries.id}`)
    expect(await screen.findByRole('heading', { name: 'Decision history: max_retries' })).toBeInTheDocument()
  })
})
