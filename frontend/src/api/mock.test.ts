import { describe, expect, it } from 'vitest'
import { ApiError } from './http'
import { createMockApi, SIMULATED_RUN_MS } from './mock'
import { E, SAMPLE_REPO } from './sample'

function clock(start = new Date('2026-10-26T12:00:00Z').getTime()) {
  let t = start
  return { now: () => t, advance: (ms: number) => (t += ms) }
}

describe('mock API', () => {
  it('answers, refuses, and refuses unknown items without guessing', async () => {
    const api = createMockApi({ delayMs: 0 })
    expect((await api.ask(SAMPLE_REPO, E.rebuildAuth.id, 'why?')).verdict).toBe('answered')
    expect((await api.ask(SAMPLE_REPO, E.poolMaxsize.id, 'why?')).verdict).toBe('refused')
    const unknown = await api.ask(SAMPLE_REPO, E.json.id, 'Why does json() raise?')
    expect(unknown).toMatchObject({ verdict: 'refused', question: 'Why does json() raise?' })
  })

  it('rejects items that are not in the graph', async () => {
    const api = createMockApi({ delayMs: 0 })
    await expect(api.ask(SAMPLE_REPO, 'psf/requests#fn:nope', 'why?')).rejects.toBeInstanceOf(ApiError)
  })

  it('filters lineage by the as-of date', async () => {
    const api = createMockApi({ delayMs: 0 })
    const all = await api.getLineage(SAMPLE_REPO, E.maxRetries.id, null)
    const in2016 = await api.getLineage(SAMPLE_REPO, E.maxRetries.id, '2016-12-31')
    expect(all.decisions).toHaveLength(3)
    expect(in2016.decisions.map((d) => d.summary)).toEqual([
      'Retry failed requests up to 10 times',
      'Cap retries at 3 and add backoff',
    ])
    expect(in2016.commits.every((c) => c.date <= '2016-12-31')).toBe(true)
  })

  it('counts flags in the gap queue', async () => {
    const api = createMockApi({ delayMs: 0 })
    await api.flagGap(SAMPLE_REPO, E.poolMaxsize.id, 'Why 10?')
    await api.flagGap(SAMPLE_REPO, E.json.id, 'Why does json() raise?')
    const queue = (await api.getHealth(SAMPLE_REPO)).gap_queue
    expect(queue[0]).toMatchObject({ entity: { id: E.json.id }, flags: 1 })
    expect(queue.find((g) => g.entity.id === E.poolMaxsize.id)?.flags).toBe(3)
  })

  it('checks links before adding a repo', async () => {
    const api = createMockApi({ delayMs: 0 })
    await expect(api.checkRepo('not a repo')).rejects.toMatchObject({ status: 400 })
    expect(await api.checkRepo('github.com/encode/httpx')).toMatchObject({ repo: 'encode/httpx', commits: 2900 })
    await expect(api.addRepo('psf/requests', true)).rejects.toMatchObject({ status: 409 })
  })

  it('plays an added repo through ingestion to READY', async () => {
    const t = clock()
    const api = createMockApi({ delayMs: 0, now: t.now })
    const added = await api.addRepo('https://github.com/someone/project', true)
    expect(added).toMatchObject({ id: 'someone/project', status: 'INGESTING', partial: true })

    t.advance(SIMULATED_RUN_MS * 0.7)
    const midway = await api.getIngestion('someone/project')
    expect(midway.repo.stage).toBe('extract')
    expect(midway.stages.map((s) => s.state)).toEqual(['done', 'done', 'done', 'running', 'queued'])

    t.advance(SIMULATED_RUN_MS)
    const repo = (await api.listRepos()).find((r) => r.id === 'someone/project')
    expect(repo).toMatchObject({ status: 'READY', partial: false, progress_pct: 100 })
  })
})
