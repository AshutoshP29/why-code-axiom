import { Link, NavLink } from 'react-router'
import { useApi } from '../api/context'
import { useEntity, useSyncRepo } from '../api/queries'
import type { EntityKind, Repo } from '../api/types'
import { formatRelative } from '../lib/format'
import { useNow } from '../lib/hooks'
import { cx } from '../lib/tones'
import { useRepo, useRepoId } from '../state/repo-context'
import { AskBar } from './AskBar'
import { RepoSwitcher } from './RepoSwitcher'
import { Badge, Dot } from './ui'

/** What the compact ask bar shows on answer pages; null shows the nav instead. */
export interface TopBarAsk {
  entityId: string
  text: string | null // null = the history prompt for the entity's kind
}

const HISTORY_PROMPT: Record<EntityKind, string> = {
  config: 'what is the history of this setting?',
  function: 'what is the history of this function?',
  file: 'what is the history of this file?',
  module: 'what is the history of this module?',
}

function Logo() {
  return (
    <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold" aria-label="WhyCode home">
      <span aria-hidden className="grid size-7 place-items-center rounded-md bg-teal text-sm font-bold text-teal-ink">
        W
      </span>
      <span className="hidden sm:inline">WhyCode</span>
    </Link>
  )
}

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/explore', label: 'Explore', end: false },
  { to: '/health', label: 'Graph health', end: false },
]

function Nav() {
  return (
    <nav aria-label="Main" className="order-last flex w-full min-w-0 items-center gap-1 overflow-x-auto md:order-none md:w-auto">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cx(
              'rounded-lg px-3 py-1.5 text-sm whitespace-nowrap',
              isActive ? 'bg-teal/10 font-semibold text-teal' : 'text-muted hover:text-ink',
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

function CompactAsk({ entityId, text }: TopBarAsk) {
  const repoId = useRepoId()
  const { data: entity } = useEntity(repoId, entityId)
  const initialText = entity ? (text ?? HISTORY_PROMPT[entity.kind]) : ''
  return (
    // Its own row on phones, the middle of the bar on wider screens.
    <div className="order-last flex w-full min-w-0 md:order-none md:w-auto md:flex-1">
      {entity ? (
        // Keyed so the bar resets when the user moves to another question.
        <AskBar key={`${entityId}|${initialText}`} variant="compact" initialEntity={entity} initialText={initialText} />
      ) : (
        <div className="h-11 flex-1" />
      )}
    </div>
  )
}

function SyncChip({ repo }: { repo: Repo }) {
  const now = useNow()
  const sync = useSyncRepo()
  return (
    <div className="hidden items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs md:flex">
      <Dot tone="green" />
      <span className="text-muted" aria-live="polite">
        {sync.isPending
          ? 'Syncing…'
          : repo.last_synced_at
            ? `Synced ${formatRelative(repo.last_synced_at, now)}`
            : 'Not synced yet'}
      </span>
      <button
        type="button"
        onClick={() => sync.mutate(repo.id)}
        disabled={sync.isPending}
        className="font-semibold text-teal hover:underline disabled:text-faint"
      >
        Sync now
      </button>
    </div>
  )
}

export function TopBar({ ask }: { ask: TopBarAsk | null }) {
  const { repo } = useRepo()
  const { sample } = useApi()
  return (
    <header className="sticky top-0 z-30 flex min-h-14 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-chrome px-4 py-2">
      <Logo />
      <RepoSwitcher />
      {ask ? <CompactAsk {...ask} /> : <Nav />}
      <div className="ml-auto flex shrink-0 items-center gap-3">
        {repo?.status === 'READY' && <SyncChip repo={repo} />}
        {sample && (
          <Badge tone="amber" className="hidden sm:inline-flex">
            Sample data
          </Badge>
        )}
      </div>
    </header>
  )
}
