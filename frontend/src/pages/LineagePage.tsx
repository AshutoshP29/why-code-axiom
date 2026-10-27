import { Fragment } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router'
import { useLineage } from '../api/queries'
import type { EntityKind, SupersedeKind } from '../api/types'
import { Breadcrumb } from '../components/answer-parts'
import { SegmentedControl } from '../components/SegmentedControl'
import { Badge, ErrorNotice, Loading, Meta, SourceLink } from '../components/ui'
import { defaultQuestion, entityCrumbs, entityLabel } from '../lib/entity'
import { formatMonth } from '../lib/format'
import { useTitle } from '../lib/hooks'
import { asOfDate, buildLineageView, type ViewStatus } from '../lib/lineage'
import { whyPath } from '../lib/routes'
import { cx, type Tone } from '../lib/tones'
import { useRepo } from '../state/repo-context'

const STATUS: Record<ViewStatus, { label: string; tone: Tone; card: string }> = {
  // Dimmed with colour, not opacity, so its text still meets contrast rules.
  superseded: { label: 'Superseded', tone: 'amber', card: 'border-amber/40 bg-sunken' },
  partial: { label: 'Partial', tone: 'blue', card: 'border-blue/40' },
  active: { label: 'Active', tone: 'teal', card: 'border-teal/40' },
}

const LINK_LABEL: Record<SupersedeKind, string> = {
  reverses: 'Reversed by',
  replaces: 'Replaced by',
  refines: 'Refined by',
}

const KIND_NOUN: Record<EntityKind, string> = {
  config: 'key',
  function: 'function',
  file: 'file',
  module: 'module',
}

/** /lineage?entity=<id>&asof=<year>: every decision about one item, oldest first, with time travel. */
export function LineagePage() {
  const [params, setParams] = useSearchParams()
  const entityId = params.get('entity')
  const asofParam = params.get('asof')
  const year = asofParam && /^\d{4}$/.test(asofParam) ? Number(asofParam) : null
  const { repo } = useRepo()
  const { data, error, refetch, isFetching } = useLineage(repo?.id ?? null, entityId, asOfDate(year))
  // Previous data is kept while a new "as of" loads, but never another item's.
  const lineage = data && data.entity.id === entityId ? data : undefined
  useTitle(lineage ? `Decision history: ${entityLabel(lineage.entity)}` : 'Decision history')

  if (!entityId) return <Navigate to="/" replace />
  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!lineage) return <Loading label="Loading the decision history" />

  const cards = buildLineageView(lineage.decisions)
  const cardById = new Map(cards.map((c) => [c.decision.id, c]))
  const setYear = (y: number | null) =>
    setParams(y === null ? { entity: entityId } : { entity: entityId, asof: String(y) }, { replace: true })
  // A year typed into the URL that is not offered still shows as the selected choice.
  const years = [...new Set([...lineage.as_of_years, ...(year === null ? [] : [year])])].sort((a, b) => a - b)
  const options: (number | null)[] = [...years, null]
  const askPath = whyPath(entityId, defaultQuestion(lineage.entity))

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Breadcrumb parts={entityCrumbs(lineage.entity, true)} />
          <h1 className="mt-2 text-2xl font-semibold">Decision history: {entityLabel(lineage.entity)}</h1>
        </div>
        {options.length > 1 && (
          <div className="flex items-center gap-3">
            <span id="asof-label" className="text-xs text-faint">
              View as of
            </span>
            <SegmentedControl
              labelledBy="asof-label"
              options={options.map((y) => ({ value: y, label: y === null ? 'Today' : String(y) }))}
              value={year}
              onChange={setYear}
            />
          </div>
        )}
      </div>

      <p className="sr-only" aria-live="polite">
        {isFetching ? 'Updating' : `Showing decisions as of ${year ?? 'today'}`}
      </p>

      {cards.length === 0 ? (
        <p className="mt-8 text-sm text-muted">
          No decisions are recorded for this item{year ? ` as of ${year}` : ''}.{' '}
          <Link to={askPath} className="text-blue underline underline-offset-2">
            Ask why anyway →
          </Link>
        </p>
      ) : (
        <div className={cx('mt-6 flex flex-col gap-3 lg:flex-row lg:items-center', isFetching && 'opacity-60')}>
          {cards.map((card) => {
            const s = STATUS[card.status]
            const d = card.decision
            return (
              <Fragment key={d.id}>
                {card.number > 1 && (
                  <div className="flex shrink-0 items-center justify-center gap-2 text-center lg:w-24 lg:flex-col lg:gap-0">
                    <span aria-hidden className={cx('text-lg', card.link ? 'text-amber' : 'text-faint')}>
                      <span className="hidden lg:inline">→</span>
                      <span className="lg:hidden">↓</span>
                    </span>
                    <span
                      className={cx(
                        'text-[10px] font-semibold tracking-wider uppercase',
                        card.link ? 'text-amber' : 'text-faint',
                      )}
                    >
                      {card.link ? LINK_LABEL[card.link.kind] : 'Then'}
                    </span>
                    {card.link && <span className="text-[10px] text-faint">{formatMonth(card.link.date)}</span>}
                  </div>
                )}
                <article className={cx('rounded-xl border bg-surface p-4 lg:flex-1', s.card)}>
                  <div className="flex items-center justify-between gap-2">
                    <Badge tone={s.tone}>{s.label}</Badge>
                    <span className="text-xs text-faint">{formatMonth(d.decided_at)}</span>
                  </div>
                  <h2 className={cx('mt-3 text-sm font-semibold', card.status === 'superseded' && 'text-muted line-through')}>
                    <Link to={askPath} className="hover:underline">
                      {d.summary}
                    </Link>
                  </h2>
                  <p className="mt-2 text-xs text-muted">{d.rationale}</p>
                  <Meta className="mt-3">
                    {[
                      <a key="src" href={d.source.url} target="_blank" rel="noreferrer" className="hover:underline">
                        {d.source.label}
                      </a>,
                      d.proposed_by ? <span key="by">@{d.proposed_by}</span> : null,
                      <SourceLink key="ev" href={d.source.url}>
                        View evidence
                      </SourceLink>,
                    ]}
                  </Meta>
                </article>
              </Fragment>
            )
          })}
        </div>
      )}

      <section className="mt-10" aria-labelledby="commits-heading">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 id="commits-heading" className="font-semibold">
            Commits that touched this {KIND_NOUN[lineage.entity.kind]}
          </h2>
          <span className="text-xs text-faint">
            {lineage.commits.length} of {lineage.commit_total} shown. Each one is linked to a decision or marked as
            having none.
          </span>
        </div>
        <div className="mt-3 overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <thead className="sr-only">
              <tr>
                <th>Commit</th>
                <th className="hidden sm:table-cell">Date</th>
                <th>Message</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {lineage.commits.map((c) => {
                const card = c.decision_id ? cardById.get(c.decision_id) : undefined
                return (
                  <tr key={c.sha} className="border-b border-line last:border-0">
                    <td className="px-4 py-3">
                      <a href={c.url} target="_blank" rel="noreferrer" className="font-mono text-blue hover:underline">
                        {c.sha.slice(0, 7)}
                      </a>
                    </td>
                    <td className="hidden px-2 py-3 text-xs whitespace-nowrap text-faint sm:table-cell">
                      {c.date.slice(0, 10)}
                    </td>
                    <td className="w-full px-2 py-3">{c.message}</td>
                    <td className="px-4 py-3 text-right">
                      {card ? (
                        <Badge tone={STATUS[card.status].tone}>Decision {card.number}</Badge>
                      ) : (
                        <Badge>No decision</Badge>
                      )}
                    </td>
                  </tr>
                )
              })}
              {lineage.commits.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-sm text-faint">
                    No commits recorded{year ? ` up to ${year}` : ''}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
