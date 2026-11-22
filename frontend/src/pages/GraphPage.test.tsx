import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockApi, sampleGraph } from '../api/mock'
import { GRAPH_LIVE_MS } from '../api/queries'
import type { GraphView } from '../api/types'
import { lineagePath, whyPath } from '../lib/routes'
import { currentLocation, renderApp } from '../test/render'

const FN = 'psf/requests#fn:src/requests/models.py::Response.apparent_encoding'

afterEach(() => {
  vi.useRealTimers()
})

describe('Graph', () => {
  it('draws the whole sample graph with its counts and a legend', async () => {
    renderApp('/graph')
    const { nodes, edges } = sampleGraph()
    expect(await screen.findByText(`${nodes.length} nodes, ${edges.length} links`)).toBeInTheDocument()
    const drawing = screen.getByRole('group', { name: /^Graph of psf\/requests/ })
    expect(within(drawing).getAllByRole('button')).toHaveLength(nodes.length)
    const legend = screen.getByRole('list', { name: 'Legend' })
    for (const kind of ['Decision', 'Evidence', 'Pull request', 'Commit', 'Person', 'File', 'Class', 'Function', 'Config key']) {
      expect(within(legend).getByText(kind)).toBeInTheDocument()
    }
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('is in the nav right after Explore', async () => {
    renderApp('/graph')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    const names = within(nav)
      .getAllByRole('link')
      .map((a) => a.textContent)
    expect(names.slice(names.indexOf('Explore'), names.indexOf('Explore') + 2)).toEqual(['Explore', 'Graph'])
  })

  it('opens a code node in the side panel, with Ask why and its decision history', async () => {
    const user = userEvent.setup()
    renderApp('/graph')
    await user.click(await screen.findByRole('button', { name: 'Response.apparent_encoding, function' }))
    const panel = screen.getByRole('complementary', { name: 'Selected node' })
    expect(within(panel).getByRole('heading', { name: 'Response.apparent_encoding' })).toBeInTheDocument()
    expect(within(panel).getByText('src/requests/models.py')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Ask why' })).toHaveAttribute(
      'href',
      whyPath(FN, 'Why is Response.apparent_encoding like this?'),
    )
    expect(within(panel).getByRole('link', { name: 'Decision history' })).toHaveAttribute('href', lineagePath(FN))
    // Its links: the decision that affects it, and more.
    expect(within(panel).getByRole('button', { name: /← AFFECTS/ })).toBeInTheDocument()

    await user.click(within(panel).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('complementary', { name: 'Selected node' })).not.toBeInTheDocument()
  })

  it('offers no Ask why for a decision', async () => {
    const user = userEvent.setup()
    renderApp('/graph')
    const decisions = await screen.findAllByRole('button', { name: /, decision$/ })
    await user.click(decisions[0])
    const panel = screen.getByRole('complementary', { name: 'Selected node' })
    expect(within(panel).getByText('Decision')).toBeInTheDocument()
    expect(within(panel).queryByRole('link', { name: 'Ask why' })).not.toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Focus here' })).toBeInTheDocument()
  })

  it('focuses on what the search picks: the URL, the API call and the panel follow', async () => {
    const user = userEvent.setup()
    const api = createMockApi({ delayMs: 0 })
    const getGraph = vi.spyOn(api, 'getGraph')
    renderApp('/graph', { api })
    await user.type(await screen.findByRole('searchbox', { name: 'Search the graph' }), 'apparent')
    const results = await screen.findByRole('list', { name: 'Search results' })
    await user.click(await within(results).findByRole('button', { name: /Response\.apparent_encoding/ }))

    expect(await screen.findByText(/Two links around/)).toBeInTheDocument()
    expect(currentLocation()).toBe(`/graph?focus=${FN}`)
    expect(getGraph).toHaveBeenLastCalledWith('psf/requests', FN)
    expect(screen.getByRole('complementary', { name: 'Selected node' })).toHaveTextContent('Response.apparent_encoding')

    await user.click(screen.getByRole('button', { name: 'Show the whole graph' }))
    expect(currentLocation()).toBe('/graph')
  })

  it('says when big repos show only their decision graph', async () => {
    const api = createMockApi({ delayMs: 0 })
    const view: GraphView = {
      nodes: [{ id: 'psf/requests#dec:a', kind: 'decision', label: 'A decision', detail: null }],
      edges: [],
      scope: 'decisions',
      truncated: true,
      total_nodes: 12_104,
      total_edges: 40_000,
    }
    api.getGraph = async () => view
    renderApp('/graph', { api })
    expect(await screen.findByRole('note')).toHaveTextContent(
      'Showing the decision graph: 1 of 12,104 nodes. Search to focus.',
    )
  })

  it('Live refetches and marks the nodes that are new since the last fetch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const api = createMockApi({ delayMs: 0 })
    const first = api.getGraph
    let calls = 0
    api.getGraph = async (repo, focus) => {
      const view = await first(repo, focus)
      calls += 1
      if (calls === 1) return view
      const commit = { id: 'psf/requests#commit:feedface', kind: 'commit' as const, label: 'Live commit', detail: null }
      return { ...view, nodes: [...view.nodes, commit], edges: [...view.edges, { source: commit.id, target: FN, type: 'MODIFIES' }] }
    }
    renderApp('/graph', { api })
    const live = await screen.findByRole('button', { name: 'Live' })
    expect(live).toHaveAttribute('aria-pressed', 'false')
    await user.click(live)
    expect(live).toHaveAttribute('aria-pressed', 'true')

    await act(() => vi.advanceTimersByTimeAsync(GRAPH_LIVE_MS + 100))
    expect(await screen.findByText('1 new node')).toBeInTheDocument()
    const added = screen.getByRole('button', { name: 'Live commit, commit' })
    expect(added.querySelector('[data-fresh]')).not.toBeNull()
  })
})
