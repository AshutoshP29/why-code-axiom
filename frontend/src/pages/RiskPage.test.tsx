import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { createMockApi } from '../api/mock'
import type { KnowledgeRisk, WhyCodeApi } from '../api/types'
import { currentLocation, renderApp } from '../test/render'

/** The real mock API, with only the risk report replaced. */
function withRisk(risk: KnowledgeRisk): WhyCodeApi {
  return { ...createMockApi({ delayMs: 0 }), getRisk: async () => risk }
}

const EMPTY: KnowledgeRisk = {
  orphaned: [],
  unexplained: [],
  counts: { code_with_decisions: 12, orphaned: 0, changed_without_reason: 0 },
}

async function table(name: string) {
  const heading = await screen.findByRole('heading', { name })
  const card = heading.closest('div')?.parentElement
  if (!card) throw new Error(`no card around "${name}"`)
  return within(card)
}

describe('Knowledge risk', () => {
  it('shows the three counts and both tables from the graph', async () => {
    renderApp('/risk')
    expect(await screen.findByRole('heading', { name: 'Knowledge risk' })).toBeInTheDocument()

    const card = (label: string) => within(screen.getByText(label).closest('div') as HTMLElement)
    expect(card('Explained').getByText('17')).toBeInTheDocument()
    expect(card('At risk').getByText('2')).toBeInTheDocument()
    expect(card('Unexplained').getByText('2')).toBeInTheDocument()

    const orphaned = await table('Nobody left to ask')
    expect(orphaned.getByText('HTTPDigestAuth.build_digest_header')).toBeInTheDocument()
    expect(orphaned.getByText('2 decisions')).toBeInTheDocument()
    expect(orphaned.getAllByText('maintainer_d')).toHaveLength(2) // in both rows
    expect(orphaned.getAllByText('inactive').length).toBeGreaterThan(0)

    const unexplained = await table('Changed often, never explained')
    expect(unexplained.getByText(/check_compatibility/)).toBeInTheDocument()
    expect(unexplained.getByText('14')).toBeInTheDocument() // commits
    expect(unexplained.getByText('5')).toBeInTheDocument() // authors
  })

  it('links a row to its answer and to its decision history', async () => {
    const user = userEvent.setup()
    renderApp('/risk')
    const orphaned = await table('Nobody left to ask')
    const row = orphaned.getByText('HTTPDigestAuth.build_digest_header').closest('tr')
    await user.click(within(row as HTMLElement).getByRole('link', { name: 'Decision history' }))
    expect(currentLocation()).toContain('/lineage?entity=')
    expect(currentLocation()).toContain('build_digest_header')
  })

  it('asks why from a row that no decision explains', async () => {
    const user = userEvent.setup()
    renderApp('/risk')
    const unexplained = await table('Changed often, never explained')
    const row = unexplained.getByText(/check_compatibility/).closest('tr')
    await user.click(within(row as HTMLElement).getByRole('link', { name: 'Ask why' }))
    expect(currentLocation()).toContain('/why?entity=')
    expect(currentLocation()).toContain('Why is check_compatibility like this?')
  })

  it('says so plainly when nothing is at risk', async () => {
    renderApp('/risk', { api: withRisk(EMPTY) })
    expect(
      await screen.findByText('Every decision still in force has someone active who made it.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Every item commits have changed has a decision that explains it.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows an item whose last change the graph does not record', async () => {
    const risk: KnowledgeRisk = {
      ...EMPTY,
      unexplained: [
        {
          entity: {
            id: 'psf/requests#fn:src/requests/utils.py::guess_json_utf',
            kind: 'function',
            name: 'guess_json_utf',
            qualified_name: 'guess_json_utf',
            path: 'src/requests/utils.py',
          },
          commits: 3,
          authors: 1,
          last_changed_at: null,
        },
      ],
    }
    renderApp('/risk', { api: withRisk(risk) })
    const unexplained = await table('Changed often, never explained')
    expect(unexplained.getByText('not recorded')).toBeInTheDocument()
  })

  it('is reachable from the top bar', async () => {
    const user = userEvent.setup()
    renderApp('/health')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    await user.click(within(nav).getByRole('link', { name: 'Knowledge risk' }))
    expect(currentLocation()).toBe('/risk')
  })
})
