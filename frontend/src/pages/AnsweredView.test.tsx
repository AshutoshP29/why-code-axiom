import { QueryClient } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AppProviders } from '../App'
import { createMockApi } from '../api/mock'
import { ANSWERS, E, SAMPLE_REPO } from '../api/sample'
import { AnsweredView } from './AnsweredView'

describe('Answer card', () => {
  it('labels each "Also considered" list with the heading in its own card', () => {
    const answer = ANSWERS[E.rebuildAuth.id]
    if (answer.verdict !== 'answered') throw new Error(`expected an answer, got ${answer.verdict}`)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <MemoryRouter>
        <AppProviders api={{ api: createMockApi({ delayMs: 0 }), sample: true }} queryClient={queryClient}>
          <AnsweredView answer={answer} repoId={SAMPLE_REPO} asked="q" />
          <AnsweredView answer={answer} repoId={SAMPLE_REPO} asked="q" />
        </AppProviders>
      </MemoryRouter>,
    )

    const lists = screen.getAllByRole('list', { name: 'Also considered' })
    expect(lists).toHaveLength(2)
    for (const list of lists) {
      const heading = document.getElementById(list.getAttribute('aria-labelledby') ?? '')
      expect(list.parentElement).toContainElement(heading)
    }
  })
})
