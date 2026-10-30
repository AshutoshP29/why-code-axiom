import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../test/render'

describe('Graph health', () => {
  it('shows the five stages, the contents, and marks evaluation numbers as placeholders', async () => {
    renderApp('/health')
    const stages = await screen.findByRole('list', { name: 'Ingestion stages' })
    expect(within(stages).getAllByRole('listitem')).toHaveLength(5)
    expect(within(stages).getByText('1,670 of 2,140')).toBeInTheDocument()

    expect(screen.getByText('Placeholder values')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'WhyCode' })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: 'Correct refusals' })).toBeInTheDocument()
    expect(screen.getByText('3 flagged')).toBeInTheDocument()
  })

  it('re-runs ingestion after confirming, then shows progress on Home', async () => {
    const user = userEvent.setup()
    renderApp('/health')
    await user.click(await screen.findByRole('button', { name: 'Re-run ingestion' }))
    const dialog = screen.getByRole('dialog', { name: 'Re-run ingestion for psf/requests?' })
    await user.click(within(dialog).getByRole('button', { name: 'Re-run ingestion' }))

    // Home loads the repo list and the ingestion first; on a busy laptop that took over the 1 s default.
    expect(await screen.findByRole('heading', { name: 'Reading psf/requests' }, { timeout: 5000 })).toBeInTheDocument()
  })
})
