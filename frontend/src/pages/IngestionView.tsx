import { useState } from 'react'
import { useIngestion } from '../api/queries'
import { Badge, Button, ErrorNotice, Loading, ProgressBar } from '../components/ui'
import { INGEST_STAGE_TITLE, STATE_TONE } from '../lib/stages'
import { BADGE_TONE, cx } from '../lib/tones'
import { useRepo } from '../state/repo-context'

/** "Reading owner/name": shown on Home while the selected repo is still being ingested. */
export function IngestionView({ repoId }: { repoId: string }) {
  const { allowPartial, notifying, notifyWhenReady } = useRepo()
  const { data, error, refetch } = useIngestion(repoId)
  const [blocked, setBlocked] = useState(false)

  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!data) return <Loading label="Checking progress" />

  return (
    <div className="flex flex-1 items-start justify-center px-4 py-12">
      <section className="w-full max-w-2xl rounded-2xl border border-line bg-surface p-6">
        <h1 className="text-xl font-semibold">Reading {repoId}</h1>
        <p className="mt-1 text-sm text-muted">
          You can start asking now. Answers will say “partial history” until reading finishes.
        </p>

        <ol className="mt-5 space-y-2">
          {data.stages.map((s, i) => {
            const tone = STATE_TONE[s.state]
            return (
              <li key={s.stage} className="flex items-center gap-3 rounded-xl border border-line bg-raised px-4 py-3">
                <span
                  aria-hidden
                  className={cx('grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold', BADGE_TONE[tone])}
                >
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{INGEST_STAGE_TITLE[s.stage]}</span>
                  <span className="block truncate text-xs text-faint">{s.detail}</span>
                </span>
                <ProgressBar
                  value={s.progress_pct / 100}
                  tone={tone}
                  label={`${INGEST_STAGE_TITLE[s.stage]} progress`}
                  className="hidden w-40 sm:block"
                />
                <Badge tone={tone}>{s.state}</Badge>
              </li>
            )
          })}
        </ol>

        <p className="mt-4 rounded-lg border border-amber/30 bg-amber/10 px-3 py-2 text-xs text-muted">
          Partial history: answers may miss older decisions and will show a lower confidence.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <Button variant="primary" onClick={() => allowPartial(repoId)}>
            Ask now (partial history)
          </Button>
          <Button
            disabled={notifying(repoId)}
            onClick={async () => setBlocked(!(await notifyWhenReady(repoId)))}
          >
            {notifying(repoId) ? 'We will notify you' : 'Notify me when ready'}
          </Button>
          {blocked && (
            <span role="alert" className="text-xs text-muted">
              Notifications are blocked in this browser. Check back here instead.
            </span>
          )}
        </div>
      </section>
    </div>
  )
}
