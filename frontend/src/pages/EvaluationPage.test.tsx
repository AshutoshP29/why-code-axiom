import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { E } from '../api/sample'
import { whyPath } from '../lib/routes'
import { currentLocation, renderApp } from '../test/render'

const questionRows = () => within(screen.getAllByRole('table')[1]).getAllByRole('row').slice(1)

describe('Evaluation', () => {
  it('lists the labelled questions and says nothing has been run yet', async () => {
    renderApp('/evaluation')
    expect(await screen.findByRole('heading', { level: 1, name: 'Evaluation' })).toBeInTheDocument()
    expect(screen.getByText('Placeholder values')).toBeInTheDocument()
    expect(screen.getByText('8 of 40 written so far.')).toBeInTheDocument()
    expect(questionRows()).toHaveLength(8)
    // Three systems per question, none run yet.
    expect(screen.getAllByText('Not run')).toHaveLength(24)
  })

  it('filters by the right response', async () => {
    const user = userEvent.setup()
    renderApp('/evaluation')
    await user.click(await screen.findByRole('radio', { name: 'No record (4)' }))
    expect(currentLocation()).toBe('/evaluation?expected=refused')
    expect(questionRows()).toHaveLength(4)
    expect(questionRows().every((r) => within(r).queryByText('No record'))).toBe(true)

    await user.click(screen.getByRole('radio', { name: 'All (8)' }))
    expect(questionRows()).toHaveLength(8)
  })

  it('opens a question in the workspace', async () => {
    const user = userEvent.setup()
    renderApp('/evaluation')
    await user.click(await screen.findByRole('link', { name: 'Why is max_retries off by default?' }))
    expect(currentLocation()).toBe(decodeURIComponent(whyPath(E.maxRetries.id, 'Why is max_retries off by default?')).replace(/\+/g, ' '))
  })

  it('is reached from Graph health', async () => {
    const user = userEvent.setup()
    renderApp('/health')
    await user.click(await screen.findByRole('link', { name: /See every question and result/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Evaluation' })).toBeInTheDocument()
  })
})
