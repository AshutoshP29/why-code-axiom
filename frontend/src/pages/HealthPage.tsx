import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useHealth, useReingest } from '../api/queries'
import type { EvalRow, Health } from '../api/types'
import { Dialog } from '../components/Dialog'
import { Badge, Button, Card, ErrorNotice, Loading, ProgressBar } from '../components/ui'
import { entityLabel } from '../lib/entity'
import { formatCount, formatDateTime, formatPct, plural } from '../lib/format'
import { useTitle } from '../lib/hooks'
import { whyPath } from '../lib/routes'
import { HEALTH_STAGE_TITLE, STATE_TONE } from '../lib/stages'
import type { Tone } from '../lib/tones'
import { useRepo } from '../state/repo-context'

const SYSTEMS: { key: keyof Omit<EvalRow, 'metric'>; label: string; tone: Tone }[] = [
  { key: 'llm_only', label: 'LLM only', tone: 'gray' },
  { key: 'vector_rag', label: 'LLM + vector RAG', tone: 'blue' },
  { key: 'whycode', label: 'WhyCode', tone: 'teal' },
]

const CONTENTS: { key: keyof Health['counts']; label: string; tone: Tone }[] = [
  { key: 'commits', label: 'Commit', tone: 'violet' },
  { key: 'issues', label: 'Issue', tone: 'red' },
  { key: 'entities', label: 'Function / file', tone: 'blue' },
  { key: 'pull_requests', label: 'PR', tone: 'violet' },
  { key: 'decisions', label: 'Decision', tone: 'teal' },
  { key: 'people', label: 'Person', tone: 'gray' },
]

function downloadReport(repo: string, health: Health) {
  const report = { repo, exported_at: new Date().toISOString(), ...health }
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `whycode-health-${repo.replace('/', '-')}.json`
  a.click()
  URL.revokeObjectURL(url)
}

/** The numbers for judges: pipeline progress, what is stored, evaluation, and flagged gaps. */
export function HealthPage() {
  const { repo } = useRepo()
  const navigate = useNavigate()
  const { data, error, refetch } = useHealth(repo?.id ?? null)
  const reingest = useReingest()
  const [confirming, setConfirming] = useState(false)
  useTitle('Graph health')

  if (!repo) return null
  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!data) return <Loading label="Loading graph health" />

  const maxCount = Math.max(1, ...CONTENTS.map((c) => data.counts[c.key]))
  const flagged = data.gap_queue.length

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Graph health</h1>
          <p className="mt-1 text-xs text-faint">
            {repo.id} | last ingest {data.last_ingest_at ? formatDateTime(data.last_ingest_at) : 'not finished yet'}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => downloadReport(repo.id, data)}>Export report</Button>
          <Button variant="primary" onClick={() => setConfirming(true)}>
            Re-run ingestion
          </Button>
        </div>
      </div>

      <ol aria-label="Ingestion stages" className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {data.stages.map((s, i) => (
          <li key={s.stage}>
            <Card className="h-full p-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold">
                  {i + 1} {HEALTH_STAGE_TITLE[s.stage]}
                </h2>
                <Badge tone={STATE_TONE[s.state]}>{s.state}</Badge>
              </div>
              <p className={`mt-2 text-xl font-semibold ${s.state === 'queued' ? 'text-muted' : ''}`}>{s.headline}</p>
              <ProgressBar
                value={s.progress_pct / 100}
                tone={STATE_TONE[s.state]}
                label={`${HEALTH_STAGE_TITLE[s.stage]} progress`}
                className="mt-2"
              />
              <p className="mt-2 text-xs text-faint">{s.detail}</p>
            </Card>
          </li>
        ))}
      </ol>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1.45fr_1fr]">
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">Evaluation on {data.evaluation.question_count} labelled questions</h2>
            {!data.evaluation.measured && <Badge tone="amber">Placeholder values</Badge>}
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] tracking-wider uppercase">
                  <th scope="col" className="pb-2 font-semibold text-faint">
                    Metric
                  </th>
                  {SYSTEMS.map((s) => (
                    <th
                      key={s.key}
                      scope="col"
                      className={`pb-2 pl-4 font-semibold ${s.key === 'whycode' ? 'text-teal' : 'text-faint'}`}
                    >
                      {s.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.evaluation.rows.map((row) => (
                  <tr key={row.metric}>
                    <th scope="row" className="py-2.5 pr-2 text-left font-normal text-muted">
                      {row.metric}
                    </th>
                    {SYSTEMS.map((s) => {
                      const v = row[s.key]
                      return (
                        <td key={s.key} className="min-w-28 py-2.5 pl-4">
                          <span className={`text-xs ${s.key === 'whycode' ? 'font-semibold' : 'text-muted'}`}>
                            {v === null ? '—' : formatPct(v)}
                          </span>
                          <ProgressBar value={v ?? 0} tone={s.tone} className="mt-1" />
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="font-semibold">Graph contents</h2>
            <dl className="mt-3 space-y-3">
              {CONTENTS.map((c) => (
                <div key={c.key}>
                  <div className="flex justify-between text-xs">
                    <dt className="text-muted">{c.label}</dt>
                    <dd className="font-semibold">{formatCount(data.counts[c.key])}</dd>
                  </div>
                  <ProgressBar value={data.counts[c.key] / maxCount} tone={c.tone} className="mt-1" />
                </div>
              ))}
            </dl>
          </Card>

          <Card className="p-5">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">Gap queue</h2>
              {flagged > 0 && <Badge tone="red">{flagged} flagged</Badge>}
            </div>
            <p className="mt-2 text-xs text-faint">
              Questions users flagged as missing context. Fix by adding docs or asking the owner.
            </p>
            {flagged === 0 ? (
              <p className="mt-3 text-sm text-faint">Nothing flagged yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {data.gap_queue.map((g) => (
                  <li key={g.entity.id}>
                    <Link
                      to={whyPath(g.entity.id, g.last_question)}
                      className="flex items-center justify-between gap-2 rounded-lg border border-line bg-raised px-3 py-2 hover:border-line-strong"
                    >
                      <span className="truncate font-mono text-xs text-blue">{entityLabel(g.entity)}</span>
                      <span className="text-xs whitespace-nowrap text-faint">{plural(g.flags, 'flag')}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {confirming && (
        <Dialog
          title={`Re-run ingestion for ${repo.id}?`}
          description="WhyCode reads the history again. Saved AI results are reused, and answers say “partial history” until it finishes."
          onClose={() => setConfirming(false)}
        >
          {reingest.error && (
            <p role="alert" className="mb-3 text-sm text-red">
              {reingest.error.message}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button onClick={() => setConfirming(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={reingest.isPending}
              onClick={() =>
                reingest.mutate(repo.id, {
                  onSuccess: () => {
                    setConfirming(false)
                    navigate('/')
                  },
                })
              }
            >
              {reingest.isPending ? 'Starting…' : 'Re-run ingestion'}
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  )
}
