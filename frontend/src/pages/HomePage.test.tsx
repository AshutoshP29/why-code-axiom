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
    expect(screen.getByRole('link', { name: 'Why does apparent_encoding use charset_normalizer?' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Why is pool_maxsize 10?' })).toBeInTheDocument()
    expect(screen.getByText('Sample data')).toBeInTheDocument()
  })

  it('asks about a picked entity', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const ask = await screen.findByRole('search', { name: 'Ask why' })
    const trace = within(ask).getByRole('button', { name: 'Trace' })
    expect(trace).toBeDisabled()

    await user.click(within(ask).getByRole('button', { name: 'Pick an entity' }))
    await user.type(screen.getByRole('combobox', { name: /search functions/i }), 'rebuild')
    await user.click(await screen.findByRole('option', { name: /SessionRedirectMixin\.rebuild_auth/ }))

    expect(trace).toBeEnabled()
    await user.type(within(ask).getByRole('textbox', { name: 'Your question' }), 'why strip the header?')
    await user.click(trace)
    expect(currentLocation()).toBe(`/why?entity=${E.rebuildAuth.id}&q=why strip the header?`)
  })

  it('asks a plain question with nothing picked', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const ask = await screen.findByRole('search', { name: 'Ask why' })
    await user.type(within(ask).getByRole('textbox', { name: 'Your question' }), 'why does rebuild_auth strip the header?')
    await user.click(within(ask).getByRole('button', { name: 'Trace' }))

    expect(currentLocation()).toBe('/why?q=why does rebuild_auth strip the header?')
    expect(
      await screen.findByRole('heading', { level: 1, name: /rebuild_auth strip the Authorization header/ }),
    ).toBeInTheDocument()
    // The top bar keeps the question as typed, still with no entity picked.
    const bar = screen.getByRole('search', { name: 'Ask why' })
    expect(within(bar).getByRole('textbox', { name: 'Your question' })).toHaveValue('why does rebuild_auth strip the header?')
    expect(within(bar).getByRole('button', { name: 'Pick an entity' })).toBeInTheDocument()
  })

  it('does not send a blank question', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const ask = await screen.findByRole('search', { name: 'Ask why' })
    await user.type(within(ask).getByRole('textbox', { name: 'Your question' }), '   ')
    expect(within(ask).getByRole('button', { name: 'Trace' })).toBeDisabled()
    await user.keyboard('{Enter}')
    expect(currentLocation()).toBe('/')
  })

  it('clears a picked entity to ask a plain question instead', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const ask = await screen.findByRole('search', { name: 'Ask why' })
    await user.click(within(ask).getByRole('button', { name: 'Pick an entity' }))
    await user.type(screen.getByRole('combobox'), 'verify')
    await user.click(await screen.findByRole('option', { name: /verify/ }))

    await user.click(within(ask).getByRole('button', { name: 'Clear entity' }))
    expect(within(ask).getByRole('button', { name: 'Pick an entity' })).toBeInTheDocument()
    expect(within(ask).queryByRole('button', { name: 'Clear entity' })).not.toBeInTheDocument()
    expect(within(ask).getByRole('textbox', { name: 'Your question' })).toHaveFocus()
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

  it('shows all four outcomes, the hedged one included', async () => {
    const user = userEvent.setup()
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'What you will see' })).toBeInTheDocument()
    for (const badge of ['Answered', 'Superseded', 'Low confidence', 'Refused']) {
      expect(screen.getByText(badge, { selector: 'span' })).toBeInTheDocument()
    }
    await user.click(screen.getByRole('link', { name: /Why is there no default timeout\?/ }))
    expect(currentLocation()).toBe(`/why?entity=${E.timeout.id}&q=Why is there no default timeout?`)
    expect(await screen.findByRole('region', { name: 'Low confidence: check before relying on this' })).toBeInTheDocument()
  })

  it('opens the decision history from a hotspot', async () => {
    const user = userEvent.setup()
    renderApp('/')
    await user.click(await screen.findByRole('link', { name: /max_retries\s*4 reversals/ }))
    expect(currentLocation()).toBe(`/lineage?entity=${E.maxRetries.id}`)
    expect(await screen.findByRole('heading', { name: 'Decision history: max_retries' })).toBeInTheDocument()
  })
})
