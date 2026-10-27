// In-browser stand-in for the WhyCode API, serving the sample data in ./sample.ts.
// It keeps state for the session (flags, added repos, re-runs) so every flow in the
// user journey can be clicked through before the backend exists.

import { entityLabel, parseRepoInput } from '../lib/entity'
import { ApiError } from './http'
import {
  ANSWERS,
  EXPLORER,
  emptyOverview,
  ENTITIES,
  EVALUATION,
  genericRefusal,
  HEALTH,
  LINEAGES,
  OVERVIEW,
  SAMPLE_REPO,
  sampleRepos,
  sampleStages,
} from './sample'
import type {
  Entity,
  EntityMatch,
  Health,
  Repo,
  RepoCheck,
  Stage,
  StageProgress,
  WhyCodeApi,
} from './types'

interface MockOptions {
  delayMs?: number
  now?: () => number
}

/** A simulated ingestion run takes this long from start to READY. */
export const SIMULATED_RUN_MS = 45_000

const STAGES: Stage[] = ['fetch', 'parse', 'link', 'extract', 'supersession']

// JSON round trip: callers get their own copy, as they would from a real response.
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export function createMockApi({ delayMs = 250, now = Date.now }: MockOptions = {}): WhyCodeApi {
  const repos = sampleRepos(now())
  const runs = new Map<string, number>() // repo id -> run start time
  const health = new Map<string, Health>([[SAMPLE_REPO, copy(HEALTH)]])

  const wait = () =>
    delayMs > 0 ? new Promise<void>((resolve) => setTimeout(resolve, delayMs)) : Promise.resolve()

  function runPct(repoId: string): number | null {
    const started = runs.get(repoId)
    if (started === undefined) return null
    return Math.min(100, Math.floor(((now() - started) / SIMULATED_RUN_MS) * 100))
  }

  /** Move a simulated run forward to the current time. */
  function refresh(repo: Repo): Repo {
    const pct = runPct(repo.id)
    if (pct === null) return repo
    if (pct >= 100) {
      runs.delete(repo.id)
      Object.assign(repo, {
        status: 'READY',
        stage: null,
        progress_pct: 100,
        partial: false,
        last_synced_at: new Date(now()).toISOString(),
      })
    } else {
      Object.assign(repo, {
        status: 'INGESTING',
        stage: STAGES[Math.min(4, Math.floor(pct / 20))],
        progress_pct: pct,
        partial: true,
        error: null,
      })
    }
    return repo
  }

  function findRepo(repoId: string): Repo {
    const repo = repos.find((r) => r.id === repoId)
    if (!repo) throw new ApiError(404, `${repoId} has not been added`)
    return refresh(repo)
  }

  function findEntity(repoId: string, entityId: string): Entity {
    findRepo(repoId)
    const entity = repoId === SAMPLE_REPO ? ENTITIES.find((e) => e.id === entityId) : undefined
    if (!entity) throw new ApiError(404, 'That item is not in the graph for this repository')
    return entity
  }

  function stagesFor(repo: Repo): StageProgress[] {
    const pct = runPct(repo.id)
    if (pct === null) return sampleStages(repo)
    return STAGES.map((stage, i) => {
      const stagePct = Math.max(0, Math.min(100, (pct - i * 20) * 5))
      return {
        stage,
        state: stagePct >= 100 ? 'done' : stagePct > 0 ? 'running' : 'queued',
        progress_pct: stagePct,
        headline: stagePct >= 100 ? 'done' : stagePct > 0 ? `${stagePct}%` : 'not started',
        detail: sampleStages({ ...repo, status: 'QUEUED' })[i].detail,
      }
    })
  }

  function healthFor(repo: Repo): Health {
    let h = health.get(repo.id)
    if (!h) {
      h = {
        last_ingest_at: repo.last_synced_at,
        stages: [],
        counts: { commits: repo.commits_count, issues: 0, entities: 0, pull_requests: 0, decisions: repo.decisions_count, people: 0 },
        gap_queue: [],
        evaluation: {
          question_count: 40,
          measured: false,
          rows: HEALTH.evaluation.rows.map((r) => ({ metric: r.metric, llm_only: null, vector_rag: null, whycode: null })),
        },
      }
      health.set(repo.id, h)
    }
    // Stages follow the repo (a re-run moves them); the rest is what was stored.
    h.stages = repo.id === SAMPLE_REPO && runPct(repo.id) === null ? HEALTH.stages : stagesFor(repo)
    return h
  }

  function estimate(repo: string): RepoCheck {
    if (repo === 'encode/httpx') {
      return { repo, found: true, is_public: true, commits: 2900, pull_requests: 2100, issues: 3400, minutes_low: 20, minutes_high: 30, ai_calls: 700, fits_free_tier: true, capped: true }
    }
    // Stable made-up numbers, so the same link always gives the same estimate.
    const h = [...repo].reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) % 100_003, 7)
    const commits = 1000 + (h % 80) * 100
    const pullRequests = Math.round((commits * 0.6) / 100) * 100
    const minutes = Math.max(5, Math.round(commits / 150))
    return {
      repo,
      found: true,
      is_public: true,
      commits,
      pull_requests: pullRequests,
      issues: Math.round((commits * 0.9) / 100) * 100,
      minutes_low: minutes,
      minutes_high: minutes + 10,
      ai_calls: Math.min(1000, Math.round(pullRequests / 3)),
      fits_free_tier: true,
      capped: pullRequests > 1000,
    }
  }

  return {
    async listRepos() {
      await wait()
      return copy(repos.map(refresh))
    },

    async checkRepo(input) {
      await wait()
      const repo = parseRepoInput(input)
      if (!repo) throw new ApiError(400, 'Paste a GitHub link like github.com/owner/name, or type owner/name.')
      return estimate(repo)
    },

    async addRepo(input) {
      await wait()
      const repoId = parseRepoInput(input)
      if (!repoId) throw new ApiError(400, 'Paste a GitHub link like github.com/owner/name, or type owner/name.')
      if (repos.some((r) => r.id === repoId)) throw new ApiError(409, `${repoId} is already added`)
      const repo: Repo = {
        id: repoId,
        status: 'QUEUED',
        stage: 'fetch',
        progress_pct: 0,
        partial: true,
        error: null,
        last_synced_at: null,
        commits_count: estimate(repoId).commits,
        decisions_count: 0,
      }
      repos.push(repo)
      runs.set(repoId, now())
      return copy(refresh(repo))
    },

    async syncRepo(repoId) {
      await wait()
      const repo = findRepo(repoId)
      if (repo.status === 'READY') repo.last_synced_at = new Date(now()).toISOString()
      return copy(repo)
    },

    async getIngestion(repoId) {
      await wait()
      const repo = findRepo(repoId)
      return copy({ repo, stages: stagesFor(repo) })
    },

    async getOverview(repoId) {
      await wait()
      const repo = findRepo(repoId)
      return copy(repoId === SAMPLE_REPO ? OVERVIEW : emptyOverview(repo))
    },

    async getExplorer(repoId) {
      await wait()
      findRepo(repoId)
      if (repoId === SAMPLE_REPO) return copy(EXPLORER)
      return { root: `${repoId.split('/')[1]}/`, files: [], config_keys: [] }
    },

    async searchEntities(repoId, text) {
      await wait()
      findRepo(repoId)
      const q = text.trim().toLowerCase()
      if (!q || repoId !== SAMPLE_REPO) return []
      const matches: EntityMatch[] = []
      for (const entity of ENTITIES) {
        const label = entityLabel(entity).toLowerCase()
        const score = label.startsWith(q) || entity.name.toLowerCase().startsWith(q)
          ? 1
          : label.includes(q)
            ? 0.8
            : (entity.path ?? '').toLowerCase().includes(q)
              ? 0.5
              : 0
        if (score > 0) matches.push({ ...entity, score })
      }
      return copy(matches.sort((a, b) => b.score - a.score).slice(0, 8))
    },

    async getEntity(repoId, entityId) {
      await wait()
      return copy(findEntity(repoId, entityId))
    },

    async ask(repoId, entityId, question) {
      await wait()
      const repo = findRepo(repoId)
      const entity = findEntity(repoId, entityId)
      // Sample answers keep their own wording of the question, as the API would normalise it.
      const answer = ANSWERS[entityId] ?? genericRefusal(entity, question.trim())
      return copy({ ...answer, partial_history: repo.partial })
    },

    async getLineage(repoId, entityId, asOf) {
      await wait()
      const entity = findEntity(repoId, entityId)
      const sample = LINEAGES[entityId] ?? { as_of_years: [], decisions: [], commits: [], commit_total: 0 }
      const upTo = <T extends { decided_at?: string; date?: string }>(rows: T[]) =>
        asOf === null ? rows : rows.filter((r) => (r.decided_at ?? r.date ?? '') <= asOf)
      return copy({
        entity,
        as_of: asOf,
        as_of_years: sample.as_of_years,
        decisions: upTo(sample.decisions),
        commits: upTo(sample.commits),
        commit_total: sample.commit_total,
      })
    },

    async getHealth(repoId) {
      await wait()
      return copy(healthFor(findRepo(repoId)))
    },

    async getEvaluation(repoId) {
      await wait()
      const repo = findRepo(repoId)
      return copy(repoId === SAMPLE_REPO ? EVALUATION : { ...healthFor(repo).evaluation, questions: [] })
    },

    async reingest(repoId) {
      await wait()
      const repo = findRepo(repoId)
      runs.set(repoId, now())
      return copy(refresh(repo))
    },

    async flagGap(repoId, entityId, question) {
      await wait()
      const entity = findEntity(repoId, entityId)
      const queue = healthFor(findRepo(repoId)).gap_queue
      const flaggedAt = new Date(now()).toISOString()
      let gap = queue.find((g) => g.entity.id === entityId)
      if (gap) {
        gap.flags += 1
        gap.last_question = question
        gap.last_flagged_at = flaggedAt
      } else {
        gap = { entity, flags: 1, last_question: question, last_flagged_at: flaggedAt }
        queue.unshift(gap)
      }
      return copy(gap)
    },
  }
}
