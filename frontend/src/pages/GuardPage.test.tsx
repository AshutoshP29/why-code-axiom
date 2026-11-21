import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { currentLocation, renderApp } from '../test/render'

describe('PR Guard', () => {
  it('checks a pasted pull request and lists the decisions on the code it changes', async () => {
    const user = userEvent.setup()
    renderApp('/guard')
    await user.type(await screen.findByLabelText('Pull request number or link'), '#7501')
    await user.click(screen.getByRole('button', { name: 'Check pull request' }))

    expect(currentLocation()).toBe('/guard?pr=#7501')
    expect(await screen.findByRole('link', { name: '#7501 Sample pull request' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /2 decisions on the code this PR changes/ })).toBeInTheDocument()
    expect(screen.getAllByText('Evidence')).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: 'Ask why' })).toHaveLength(2)
  })

  it('opens straight on a shared link and shows a refusal from the API', async () => {
    renderApp('/guard?pr=not-a-pr')
    expect(await screen.findByRole('alert')).toHaveTextContent('Give a pull request number')
  })

  it('is in the main navigation', async () => {
    renderApp('/')
    expect(await screen.findByRole('link', { name: 'PR Guard' })).toHaveAttribute('href', '/guard')
  })
})
