import { skipToken, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useApi } from '../api/context'
import type { GuardHit, GuardReport } from '../api/types'
import { EvidenceChain } from '../components/EvidenceChain'
import { Badge, Button, Card, ErrorNotice, Loading, SectionLabel } from '../components/ui'
import { defaultQuestion, entityLabel } from '../lib/entity'
import { plural } from '../lib/format'
import { useTitle } from '../lib/hooks'
import { lineagePath, whyPath } from '../lib/routes'
import { useRepo } from '../state/repo-context'

const STATE_TONE = { open: 'green', merged: 'violet', closed: 'gray' } as const

/** PR Guard: paste a pull request, see which recorded decisions it touches before it merges. */
export function GuardPage() {
  const { repo } = useRepo()
  const { api } = useApi()
  const [params, setParams] = useSearchParams()
  const pr = params.get('pr')?.trim() ?? ''
  const [text, setText] = useState(pr)
  useTitle('PR Guard')
  const report = useQuery({
    queryKey: ['guard', repo?.id, pr],
    queryFn: repo && pr ? () => api.checkPull(repo.id, pr) : skipToken,
    retry: false,
    staleTime: 5 * 60_000,
  })

  if (!repo) return null

  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim()) setParams({ pr: text.trim() })
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
      <h1 className="text-2xl font-semibold">PR Guard</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Paste a pull request for {repo.id}. WhyCode finds the functions it changes and the recorded decisions on
        them, so a reviewer sees what the change may undo, with the evidence and who to ask.
      </p>

      <form onSubmit={submit} className="mt-5 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="pull" className="sr-only">
          Pull request number or link
        </label>
        <input
          id="pull"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={`7501, or https://github.com/${repo.id}/pull/7501`}
          className="min-w-0 flex-1 rounded-lg border border-line-strong bg-sunken px-3 py-2 text-sm placeholder:text-faint focus:border-teal focus:outline-none"
        />
        <Button type="submit" variant="primary" disabled={!text.trim() || report.isFetching}>
          {report.isFetching ? 'Checking…' : 'Check pull request'}
        </Button>
      </form>

      <div className="mt-6">
        {!pr ? null : report.isPending ? (
          <Loading label="Reading the pull request and the graph" />
        ) : report.error ? (
          <ErrorNotice error={report.error} onRetry={() => report.refetch()} />
        ) : (
          <Report report={report.data} />
        )}
      </div>
    </div>
  )
}

function Report({ report }: { report: GuardReport }) {
  const code = report.hits.filter((h) => h.level === 'code')
  const fileOnly = report.hits.filter((h) => h.level === 'file')
  const { pull } = report
  return (
    <div className="space-y-6">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATE_TONE[pull.state]}>{pull.state}</Badge>
          <a href={pull.url} target="_blank" rel="noreferrer" className="font-semibold hover:underline">
            #{pull.number} {pull.title}
          </a>
          {pull.author && <span className="text-xs text-faint">by @{pull.author}</span>}
        </div>
        <p className="mt-2 text-xs text-muted">
          {plural(report.files_changed, 'file')} changed, {plural(report.code_files_read, 'code file')} read,{' '}
          {plural(report.changed.length, 'known function or class', 'known functions or classes')} changed
          {report.changed.length > 0 && `: ${report.changed.map(entityLabel).join(', ')}`}.
        </p>
        {report.notes.map((n) => (
          <p key={n} className="mt-1 text-xs text-faint">
            {n}
          </p>
        ))}
      </Card>

      <section aria-labelledby="code-hits">
        <h2 id="code-hits" className="font-semibold">
          {code.length > 0
            ? `${plural(code.length, 'decision')} on the code this PR changes`
            : 'No recorded decision on the code this PR changes'}
        </h2>
        {code.length === 0 && (
          <p className="mt-1 text-sm text-muted">
            The graph holds no decision about the functions or classes it touches. That is not a green light: it
            means the history does not say.
          </p>
        )}
        <div className="mt-3 space-y-4">
          {code.map((h) => (
            <Hit key={h.decision.id} hit={h} />
          ))}
        </div>
      </section>

      {fileOnly.length > 0 && (
        <details className="rounded-xl border border-line bg-surface p-4">
          <summary className="cursor-pointer text-sm font-semibold">
            {plural(fileOnly.length, 'more decision')} on the same files, not on the changed code
          </summary>
          <ul className="mt-3 space-y-2 text-sm">
            {fileOnly.map((h) => (
              <li key={h.decision.id}>
                <a href={h.decision.source.url} target="_blank" rel="noreferrer" className="hover:underline">
                  {h.decision.summary}
                </a>{' '}
                <span className="text-xs text-faint">
                  {h.decision.source.label}, {h.decision.decided_at}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function Hit({ hit }: { hit: GuardHit }) {
  const { decision } = hit
  const touched = hit.touched[0]
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={decision.status === 'PARTIAL' ? 'amber' : 'teal'}>
          {decision.status === 'PARTIAL' ? 'Refined decision' : 'Active decision'}
        </Badge>
        <span className="text-xs text-faint">
          {decision.source.label}, {decision.decided_at}
        </span>
      </div>
      <p className="mt-3 text-[15px] leading-relaxed">{decision.summary}</p>
      <p className="mt-1 text-sm text-muted">{decision.rationale}</p>
      <p className="mt-3 text-xs text-muted">
        This PR changes{' '}
        {hit.touched.map((t, i) => (
          <span key={t.id}>
            {i > 0 && ', '}
            <code className="text-ink">{entityLabel(t)}</code>
          </span>
        ))}
        .{' '}
        {touched && (
          <>
            <Link to={whyPath(touched.id, defaultQuestion(touched))} className="text-blue hover:underline">
              Ask why
            </Link>{' '}
            ·{' '}
            <Link to={lineagePath(touched.id)} className="text-blue hover:underline">
              Decision history
            </Link>
          </>
        )}
      </p>
      <div className="mt-4">
        <SectionLabel>Evidence</SectionLabel>
        <div className="mt-2">
          <EvidenceChain steps={hit.evidence} />
        </div>
      </div>
      {hit.people.length > 0 && (
        <p className="mt-3 text-xs text-muted">
          Who to ask:{' '}
          {hit.people.map((p, i) => (
            <span key={p.login}>
              {i > 0 && ', '}
              <a href={p.url ?? `https://github.com/${p.login}`} target="_blank" rel="noreferrer" className="hover:underline">
                @{p.login}
              </a>
              {!p.active && <span className="text-faint"> (inactive)</span>}
            </span>
          ))}
        </p>
      )}
    </Card>
  )
}
