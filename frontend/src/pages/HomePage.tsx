import { Link } from 'react-router'
import { useOverview } from '../api/queries'
import type { Overview, ShowcaseOutcome } from '../api/types'
import { AskBar } from '../components/AskBar'
import { Badge, Card, ErrorNotice, Loading, ProgressBar } from '../components/ui'
import { entityLabel } from '../lib/entity'
import { formatCount, plural } from '../lib/format'
import { useTitle } from '../lib/hooks'
import { lineagePath, whyPath } from '../lib/routes'
import { TEXT_TONE, type Tone } from '../lib/tones'
import { useRepo } from '../state/repo-context'
import { IngestionView } from './IngestionView'

const STATS: { key: keyof Overview['counts']; label: string; caption: string; tone: Tone }[] = [
  { key: 'decisions', label: 'Decisions found', caption: 'extracted from PRs and issues', tone: 'teal' },
  { key: 'superseded', label: 'Superseded', caption: 'old rules shown as history', tone: 'amber' },
  { key: 'evidence_links', label: 'Evidence links', caption: 'every claim cites a source', tone: 'blue' },
  { key: 'entities', label: 'Entities mapped', caption: 'files, functions, config keys', tone: 'violet' },
]

const OUTCOME: Record<ShowcaseOutcome, { label: string; tone: Tone }> = {
  answered: { label: 'Answered', tone: 'teal' },
  superseded: { label: 'Superseded', tone: 'amber' },
  hedged: { label: 'Low confidence', tone: 'amber' },
  refused: { label: 'Refused', tone: 'red' },
}

function HomeContent({ repoId, partialNote }: { repoId: string; partialNote: string | null }) {
  const { data, error, refetch } = useOverview(repoId)
  const maxReversals = Math.max(1, ...(data?.hotspots.map((h) => h.reversals) ?? []))

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6">
      {partialNote && (
        <p className="mb-6 rounded-lg border border-amber/30 bg-amber/10 px-3 py-2 text-sm text-muted">
          Partial history: {partialNote}, so answers may miss older decisions and will show a lower confidence.
        </p>
      )}

      <section className="text-center">
        <Badge tone="teal">Ask the codebase why</Badge>
        <h1 className="mt-4 text-4xl font-bold tracking-tight sm:text-5xl">Why is the code like this?</h1>
        <p className="mx-auto mt-4 max-w-xl text-muted">
          Ask a question, or pick a function, file or config key first. Every answer comes with its evidence, its
          date and the person to ask. If the history does not say, WhyCode says so.
        </p>
        <div className="mx-auto mt-7 max-w-2xl">
          <AskBar variant="hero" />
        </div>
        {data && data.example_questions.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-xs">
            <span className="text-faint">Try</span>
            {data.example_questions.map((ex) => (
              <Link
                key={ex.question}
                to={whyPath(ex.entity.id, ex.question)}
                className="rounded-full border border-line bg-surface px-3 py-1.5 text-muted hover:border-line-strong hover:text-ink"
              >
                {ex.question}
              </Link>
            ))}
          </div>
        )}
      </section>

      {error && <ErrorNotice error={error} onRetry={() => refetch()} />}
      {!data && !error && <Loading label="Loading the graph summary" />}

      {data && (
        <>
          <section aria-label="Graph summary" className="mt-12 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {STATS.map((s) => (
              <Card key={s.key} className="p-4">
                <h2 className="text-[11px] font-semibold tracking-wider text-faint uppercase">{s.label}</h2>
                <p className={`mt-1 text-3xl font-semibold ${TEXT_TONE[s.tone]}`}>{formatCount(data.counts[s.key])}</p>
                <p className="mt-1 text-xs text-faint">{s.caption}</p>
              </Card>
            ))}
          </section>

          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1.45fr_1fr]">
            <Card>
              <div className="flex flex-wrap items-baseline gap-2 border-b border-line px-5 py-4">
                <h2 className="font-semibold">Hotspots</h2>
                <span className="text-xs text-faint">entities whose rules were reversed most often</span>
              </div>
              {data.hotspots.length === 0 ? (
                <p className="px-5 py-6 text-sm text-faint">No reversed rules found yet.</p>
              ) : (
                <ul>
                  {data.hotspots.map((h) => (
                    <li key={h.entity.id} className="border-b border-line last:border-0">
                      <Link
                        to={lineagePath(h.entity.id)}
                        className="flex items-center gap-4 px-5 py-3 hover:bg-raised"
                      >
                        <span className="min-w-0 flex-1 truncate font-mono text-sm text-blue">
                          {entityLabel(h.entity)}
                        </span>
                        <span className="text-xs whitespace-nowrap text-amber">{plural(h.reversals, 'reversal')}</span>
                        <ProgressBar value={h.reversals / maxReversals} tone="amber" className="hidden w-40 sm:block" />
                        <span aria-hidden className="text-faint">
                          →
                        </span>
                        <span className="sr-only">, view decision history</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card className="p-5">
              <h2 className="font-semibold">What you will see</h2>
              {data.showcase.length === 0 ? (
                <p className="mt-4 text-sm text-faint">Examples appear once decisions have been read.</p>
              ) : (
                <ul className="mt-4 space-y-3">
                  {data.showcase.map((s) => (
                    <li key={s.entity.id}>
                      <Link
                        to={whyPath(s.entity.id, s.question)}
                        className="block rounded-xl border border-line bg-raised p-4 hover:border-line-strong"
                      >
                        <Badge tone={OUTCOME[s.outcome].tone}>{OUTCOME[s.outcome].label}</Badge>
                        <span className="mt-2 block text-sm font-semibold">{s.question}</span>
                        <span className="mt-1 block text-xs text-faint">{s.summary}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

export function HomePage() {
  const { repo, partialAllowed } = useRepo()
  useTitle('Why is the code like this?')
  if (!repo) return null
  const unfinished = repo.status === 'QUEUED' || repo.status === 'INGESTING' || repo.status === 'ERROR'
  if (unfinished && !partialAllowed(repo.id)) return <IngestionView repoId={repo.id} />
  const note = !repo.partial
    ? null
    : repo.status === 'ERROR'
      ? `reading ${repo.id} stopped before it finished`
      : `${repo.id} is still being read`
  return <HomeContent repoId={repo.id} partialNote={note} />
}
