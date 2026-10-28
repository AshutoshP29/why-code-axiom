import { describe, expect, it } from 'vitest'
import { ANSWERS, E, ENTITIES, EVALUATION, EXPLORER, HEALTH, LINEAGES, OVERVIEW, SAMPLE_REPO } from './sample'
import type { Decision } from './types'

const PROMPT_VERSION = 'extract-v2' // whycode/extract/prompt.py

// The id forms in whycode/ids.py and whycode/graph/schema.cypher, for every kind the sample uses.
const ID_FORMS = [
  String.raw`pr:\d+`,
  String.raw`issue:\d+`,
  'commit:[0-9a-f]{40}', // the full sha, lowercase
  'dec:[0-9a-f]{16}',
  String.raw`ev:pr:\d+:(body|ic:\d+|rc:\d+)`,
  String.raw`file:src/requests/\w+\.py`,
  String.raw`(cls|fn):src/requests/\w+\.py::[A-Za-z_][\w.]*`,
  String.raw`cfg:\w+`,
]
const GRAPH_ID = new RegExp(`^${SAMPLE_REPO}#(${ID_FORMS.join('|')})$`)

const ID_FIELDS = new Set(['id', 'entity_id', 'decision_id', 'from', 'to'])

/** Every graph id in a value: the id fields at any depth. */
function graphIds(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const v of value) graphIds(v, found)
  } else if (value && typeof value === 'object') {
    for (const [key, v] of Object.entries(value)) {
      if (ID_FIELDS.has(key) && typeof v === 'string') found.push(v)
      else graphIds(v, found)
    }
  }
  return found
}

// Evaluation questions have ids of their own ("q01"), so only their entities are graph data.
const SAMPLE = [ENTITIES, EXPLORER, OVERVIEW, ANSWERS, LINEAGES, HEALTH.gap_queue, EVALUATION.questions.map((q) => q.entity)]

function decisions(): Decision[] {
  const all: Decision[] = Object.values(LINEAGES).flatMap((l) => l.decisions)
  for (const answer of Object.values(ANSWERS)) {
    if (answer.verdict === 'refused') continue
    all.push(answer.decision, ...answer.superseded.map((s) => s.decision))
  }
  return all
}

/** decision_key in whycode/ids.py: sha256 of "source id|prompt version|index", first 16 hex digits. */
async function decisionKey(sourceId: string, index: number): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${sourceId}|${PROMPT_VERSION}|${index}`))
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16)
}

describe('sample ids', () => {
  it('all have a form whycode/ids.py builds', () => {
    const ids = graphIds(SAMPLE)
    expect(ids.length).toBeGreaterThan(100)
    expect(ids.filter((i) => !GRAPH_ID.test(i))).toEqual([])
  })

  it('give lineage commits their full sha', () => {
    const shas = Object.values(LINEAGES).flatMap((l) => l.commits.map((c) => c.sha))
    expect(shas.filter((sha) => !/^[0-9a-f]{40}$/.test(sha))).toEqual([])
  })

  it('point graph nodes and lineage commits at items and decisions that exist', () => {
    const entityIds = new Set(ENTITIES.map((e) => e.id))
    for (const answer of Object.values(ANSWERS)) {
      if (answer.verdict === 'refused') continue
      const nodeIds = new Set(answer.graph.nodes.map((n) => n.id))
      for (const n of answer.graph.nodes) if (n.entity_id) expect(entityIds).toContain(n.entity_id)
      for (const e of answer.graph.edges) expect([nodeIds.has(e.from), nodeIds.has(e.to)]).toEqual([true, true])
    }
    for (const l of Object.values(LINEAGES)) {
      const decisionIds = new Set(l.decisions.map((d) => d.id))
      for (const c of l.commits) if (c.decision_id) expect(decisionIds).toContain(c.decision_id)
    }
  })

  it('hash each decision from its source, the prompt version and its position, as decision_key does', async () => {
    // Worked out with whycode.ids.decision_id("psf/requests", "psf/requests#pr:5797", "extract-v2", 0).
    expect(`${SAMPLE_REPO}#dec:${await decisionKey('psf/requests#pr:5797', 0)}`).toBe('psf/requests#dec:e15ff91b2e4f9b4d')

    const all = decisions()
    expect(all.length).toBeGreaterThan(5)
    for (const d of all) {
      expect(d.id, d.summary).toBe(`${SAMPLE_REPO}#dec:${await decisionKey(d.source.id, 0)}`)
    }
  })

  it('use the real items exactly as the graph has them', () => {
    expect(E.rebuildAuth.id).toBe('psf/requests#fn:src/requests/sessions.py::SessionRedirectMixin.rebuild_auth')
  })
})
