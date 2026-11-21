import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'

vi.mock('./features', () => ({ INGEST_ACTIONS: false, useIngestActions: () => false }))

describe('with ingestion actions off (the live build)', () => {
  it('shows no Re-run ingestion, Sync now or Add a repository', async () => {
    const user = userEvent.setup()
    renderApp('/health')
    expect(await screen.findByRole('heading', { name: 'Graph health' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Re-run ingestion' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /psf\/requests/ }))
    expect(screen.queryByText('Add a repository')).not.toBeInTheDocument()
  })
})
