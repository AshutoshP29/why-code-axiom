import { useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import type { Repo, RepoStatus } from '../api/types'
import { parseRepoInput } from '../lib/entity'
import { formatCompact, formatRelative } from '../lib/format'
import { useDismiss, useNow } from '../lib/hooks'
import { stageSummary } from '../lib/stages'
import { cx, type Tone } from '../lib/tones'
import { useRepo } from '../state/repo-context'
import { AddRepoDialog } from './AddRepoDialog'
import { Badge, Dot, ProgressBar, SectionLabel } from './ui'

const STATUS_TONE: Record<RepoStatus, Tone> = {
  READY: 'green',
  INGESTING: 'blue',
  QUEUED: 'blue',
  ERROR: 'red',
}

const isBusy = (r: Repo) => r.status === 'INGESTING' || r.status === 'QUEUED'

function RepoMeta({ repo, now }: { repo: Repo; now: number }) {
  if (repo.status === 'ERROR') {
    return (
      <span className="text-xs text-red">
        Stopped{repo.stage ? ` at ${stageSummary(repo.stage).toLowerCase()}` : ''}
        {repo.error ? `: ${repo.error}` : ''}
      </span>
    )
  }
  if (isBusy(repo)) {
    return (
      <>
        <span className="text-xs text-muted">
          {repo.stage ? stageSummary(repo.stage) : 'Waiting to start'} | {repo.progress_pct}%
        </span>
        <ProgressBar value={repo.progress_pct / 100} tone="blue" className="mt-1.5" />
      </>
    )
  }
  return (
    <span className="text-xs text-muted">
      {repo.last_synced_at ? `Synced ${formatRelative(repo.last_synced_at, now)}` : 'Not synced yet'} |{' '}
      {formatCompact(repo.commits_count)} commits | {formatCompact(repo.decisions_count)} decisions
    </span>
  )
}

export function RepoSwitcher() {
  const { repos, repo, selectRepo } = useRepo()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const now = useNow()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [adding, setAdding] = useState<string | null>(null) // input to prefill, or null when closed
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  useDismiss(rootRef, open, () => setOpen(false))

  const q = filter.trim().toLowerCase()
  const shown = repos.filter((r) => r.id.includes(q) || r.id === parseRepoInput(q))

  function choose(r: Repo) {
    selectRepo(r.id)
    setOpen(false)
    setFilter('')
    // Answer and history pages are about one repo's code; leave them when the repo changes.
    if (r.id !== repo?.id && (pathname === '/why' || pathname === '/lineage')) navigate('/')
  }

  function startAdding() {
    setAdding(parseRepoInput(filter) ? filter.trim() : '')
    setOpen(false)
    setFilter('')
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cx(
          'flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm whitespace-nowrap hover:border-line-strong',
          open ? 'border-teal/60' : 'border-line bg-surface',
        )}
      >
        {/* Spoken as "Switch repository, current: psf/requests"; the visible name stays part of it. */}
        <span className="sr-only">Switch repository, current: </span>
        {repo ? (
          <>
            <Dot tone={STATUS_TONE[repo.status]} />
            <span className="max-w-40 truncate">{repo.id}</span>
            {isBusy(repo) && <Badge tone="blue">Ingesting {repo.progress_pct}%</Badge>}
            {repo.status === 'ERROR' && <Badge tone="red">Stopped</Badge>}
          </>
        ) : (
          <span className="text-muted">No repository</span>
        )}
        <span aria-hidden className="text-[10px] text-faint">
          ▾
        </span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Your repositories"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setOpen(false)
              buttonRef.current?.focus()
            }
          }}
          className="absolute top-full left-0 z-40 mt-2 w-[min(24rem,90vw)] rounded-xl border border-line bg-surface p-3 shadow-2xl"
        >
          <SectionLabel>Your repositories</SectionLabel>
          <input
            autoFocus
            aria-label="Search repositories, or paste a GitHub link"
            placeholder="Search, or paste a GitHub link"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="mt-2 w-full rounded-lg border border-line bg-sunken px-3 py-2 text-sm outline-none placeholder:text-faint focus:border-teal/60"
          />
          <ul className="mt-2 space-y-1">
            {shown.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  aria-current={r.id === repo?.id ? 'true' : undefined}
                  onClick={() => choose(r)}
                  className={cx(
                    'w-full rounded-lg border px-3 py-2.5 text-left',
                    r.id === repo?.id ? 'border-teal/50 bg-teal/5' : 'border-transparent hover:bg-raised',
                  )}
                >
                  <span className="flex items-center gap-2">
                    <Dot tone={STATUS_TONE[r.status]} />
                    <span className="text-sm font-semibold">{r.id}</span>
                    <Badge tone={STATUS_TONE[r.status]} className="ml-auto">
                      {r.status === 'QUEUED' ? 'Queued' : r.status}
                    </Badge>
                  </span>
                  <span className="mt-1 block">
                    <RepoMeta repo={r} now={now} />
                  </span>
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="px-3 py-2 text-xs text-faint">No repository matches “{filter}”.</li>}
          </ul>
          <div className="mt-2 border-t border-line pt-2">
            <button
              type="button"
              onClick={startAdding}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-raised"
            >
              <span aria-hidden className="grid size-7 place-items-center rounded-full border border-teal/50 text-teal">
                +
              </span>
              <span>
                <span className="block text-sm font-semibold text-teal">Add a repository</span>
                <span className="block text-xs text-faint">Paste a GitHub link or type owner/name</span>
              </span>
            </button>
          </div>
        </div>
      )}

      {adding !== null && <AddRepoDialog initialInput={adding} onClose={() => setAdding(null)} />}
    </div>
  )
}
