import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../test/render'

async function openSwitcher(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /Switch repository/ }))
  return screen.getByRole('dialog', { name: 'Your repositories' })
}

describe('Repo switcher', () => {
  it('lists repos with their state', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const panel = await openSwitcher(user)
    const items = within(panel).getAllByRole('listitem')
    expect(items.map((i) => within(i).getByRole('button').textContent)).toEqual([
      expect.stringContaining('psf/requests'),
      expect.stringContaining('pallets/flask'),
      expect.stringContaining('encode/httpx'),
    ])
    expect(items[0]).toHaveTextContent('Synced 10 min ago | 6.5k commits | 2.1k decisions')
    expect(items[2]).toHaveTextContent('Stage 4 of 5: reading discussions | 62%')
  })

  it('switches to another repo', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const panel = await openSwitcher(user)
    await user.click(within(panel).getByRole('button', { name: /pallets\/flask/ }))

    expect(screen.getByRole('button', { name: 'Repository: pallets/flask. Switch repository' })).toBeInTheDocument()
    expect(await screen.findByText('No reversed rules found yet.')).toBeInTheDocument()
  })

  it('shows reading progress for a repo still being ingested, and lets you ask anyway', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const panel = await openSwitcher(user)
    await user.click(within(panel).getByRole('button', { name: /encode\/httpx/ }))

    expect(await screen.findByRole('heading', { name: 'Reading encode/httpx' })).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Read discussions with AI progress' })).toHaveAttribute(
      'aria-valuenow',
      '61',
    )
    await user.click(screen.getByRole('button', { name: 'Ask now (partial history)' }))
    expect(await screen.findByText(/Partial history: encode\/httpx is still being read/)).toBeInTheDocument()
  })

  it('adds a repository after checking it', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const panel = await openSwitcher(user)
    await user.type(within(panel).getByRole('textbox'), 'github.com/someone/project')
    await user.click(within(panel).getByRole('button', { name: /Add a repository/ }))

    const dialog = screen.getByRole('dialog', { name: 'Add a repository' })
    const start = within(dialog).getByRole('button', { name: 'Start ingestion' })
    expect(start).toBeDisabled() // nothing checked yet
    await user.click(within(dialog).getByRole('button', { name: 'Check' }))
    expect(await within(dialog).findByText('Public repository found')).toBeInTheDocument()
    expect(within(dialog).getByRole('switch')).toBeChecked()

    await user.click(start)
    expect(await screen.findByRole('heading', { name: 'Reading someone/project' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('explains a bad link', async () => {
    const user = userEvent.setup()
    renderApp('/')
    const panel = await openSwitcher(user)
    await user.click(within(panel).getByRole('button', { name: /Add a repository/ }))
    const dialog = screen.getByRole('dialog', { name: 'Add a repository' })
    await user.type(within(dialog).getByRole('textbox'), 'not a repo')
    await user.click(within(dialog).getByRole('button', { name: 'Check' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Paste a GitHub link like github.com/owner/name')
  })
})
