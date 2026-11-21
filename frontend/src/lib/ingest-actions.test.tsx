import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { createMockApi } from '../api/mock'
import { renderApp } from '../test/render'

describe('a repository read by the team, not added from the screens', () => {
  it('offers no Sync now or Re-run ingestion, but still offers Add a repository', async () => {
    const api = createMockApi({ delayMs: 0 })
    const listRepos = api.listRepos.bind(api)
    api.listRepos = async () => (await listRepos()).map((r) => ({ ...r, added: false }))
    const user = userEvent.setup()
    renderApp('/health', { api })

    expect(await screen.findByRole('heading', { name: 'Graph health' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Re-run ingestion' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /psf\/requests/ }))
    expect(screen.getByText('Add a repository')).toBeInTheDocument()
  })
})
