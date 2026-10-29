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

  it('marks a picked entity as selected, with no match score', async () => {
    const api = createMockApi({ delayMs: 0 })
    expect(await api.ask(SAMPLE_REPO, E.rebuildAuth.id, 'why?')).toMatchObject({ matched_by: 'selected', match_score: null })
  })

  it('finds the entity itself when none is picked', async () => {
    const api = createMockApi({ delayMs: 0 })
    const answer = await api.ask(SAMPLE_REPO, null, 'why does rebuild_auth strip the header?')
    expect(answer).toMatchObject({ verdict: 'answered', entity: { id: E.rebuildAuth.id }, matched_by: 'search', match_score: 0.9 })
    // The entity-match factor shows the same score the match line does.
    expect(answer.confidence_factors.find((f) => f.label === 'Entity match')).toMatchObject({ value: 0.9, display: '90%' })

    // A weak but real match still finds the item; here the item has no recorded reason.
    const pool = await api.ask(SAMPLE_REPO, null, 'why is the pool size 10?')
    expect(pool).toMatchObject({ verdict: 'refused', entity: { id: E.poolMaxsize.id }, matched_by: 'search' })
  })

  it('refuses with no entity when nothing matches the question', async () => {
    const api = createMockApi({ delayMs: 0 })
    const answer = await api.ask(SAMPLE_REPO, null, 'why did requests drop chardet?')
    expect(answer).toMatchObject({ verdict: 'refused', entity: null, matched_by: 'search', match_score: null })
    if (answer.verdict !== 'refused') throw new Error('expected a refusal')
    // Evidence that shares a word ("drop") is offered as related only, with a low score.
    expect(answer.related.map((r) => r.title)).toEqual(['PR #1565: only strip auth when the host changes'])
    expect(answer.related[0].match_score).toBeLessThan(0.4)

    // Other repos have no sample entities, so a plain question matches nothing there.
    expect((await api.ask('pallets/flask', null, 'why is max_retries off?')).entity).toBeNull()
  })

  it('hedges an answer whose evidence is thin, between the two thresholds', async () => {
    const api = createMockApi({ delayMs: 0 })
    const answer = await api.ask(SAMPLE_REPO, E.timeout.id, 'why no default?')
    if (answer.verdict !== 'hedged') throw new Error(`expected a hedged answer, got ${answer.verdict}`)
    expect(answer.warning).toMatch(/Only one source/)
    expect(answer.confidence).toBeGreaterThanOrEqual(answer.thresholds.refuse)
    expect(answer.confidence).toBeLessThan(answer.thresholds.answer)
    expect(answer.decision.evidence_kind).toBe('INFERRED')

    // Found by search, it is still hedged.
    expect(await api.ask(SAMPLE_REPO, null, 'Why is there no default timeout?')).toMatchObject({
      verdict: 'hedged',
      entity: { id: E.timeout.id },
      matched_by: 'search',
      match_score: 0.75,
    })
  })

  it('finds the sample class in an entity search', async () => {
    const api = createMockApi({ delayMs: 0 })
    const matches = await api.searchEntities(SAMPLE_REPO, 'Session')
    expect(matches.find((m) => m.kind === 'class')).toMatchObject({ id: E.sessionClass.id, qualified_name: 'Session' })
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

  it('sends alternatives and every approver with each decision, as lists', async () => {
    const api = createMockApi({ delayMs: 0 })
    const answer = await api.ask(SAMPLE_REPO, E.rebuildAuth.id, 'why?')
    if (answer.verdict !== 'answered') throw new Error(`expected an answer, got ${answer.verdict}`)
    expect(answer.decision.alternatives).toHaveLength(2)
    expect(answer.decision.approved_by).toEqual(['maintainer_b', 'maintainer_c'])
    // An older, replaced decision with nothing recorded still sends empty lists, never a missing field.
    expect(answer.superseded[0].decision).toMatchObject({ alternatives: [], approved_by: [] })

    const lineage = await api.getLineage(SAMPLE_REPO, E.maxRetries.id, null)
    for (const d of lineage.decisions) {
      expect(Array.isArray(d.alternatives) && Array.isArray(d.approved_by)).toBe(true)
    }
  })
})
