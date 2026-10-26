import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useRepos } from '../api/queries'
import { RepoContext, type RepoContextValue } from './repo-context'

const STORAGE_KEY = 'whycode.repo'

// Storage can be missing or blocked (private windows, previews); the choice is only a convenience.
function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStored(repoId: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, repoId)
  } catch {
    // ignore
  }
}

const addTo = (set: ReadonlySet<string>, value: string) => new Set(set).add(value)

export function RepoProvider({ children }: { children: ReactNode }) {
  const { data: repos = [], isPending, error } = useRepos()
  const [chosen, setChosen] = useState<string | null>(readStored)
  const [partial, setPartial] = useState<ReadonlySet<string>>(() => new Set())
  const [watched, setWatched] = useState<ReadonlySet<string>>(() => new Set())

  // With no stored choice, pick once (the first ready repo) and keep it, so the view does not
  // jump to another repo when this one starts re-ingesting. Setting state during render is
  // React's pattern for deriving state from newly loaded data.
  if (chosen === null && repos.length > 0) {
    setChosen((repos.find((r) => r.status === 'READY') ?? repos[0]).id)
  }
  const repo = repos.find((r) => r.id === chosen) ?? repos[0] ?? null

  // Fire the promised notification each time a watched repo finishes reading.
  const notified = useRef(new Set<string>())
  useEffect(() => {
    for (const r of repos) {
      if (!watched.has(r.id)) continue
      if (r.status !== 'READY') {
        notified.current.delete(r.id) // reading again: notify again when it ends
      } else if (!notified.current.has(r.id)) {
        notified.current.add(r.id)
        new Notification(`${r.id} is ready`, { body: 'WhyCode has finished reading its history.' })
      }
    }
  }, [repos, watched])

  const selectRepo = useCallback((repoId: string) => {
    setChosen(repoId)
    writeStored(repoId)
  }, [])

  const allowPartial = useCallback((repoId: string) => setPartial((prev) => addTo(prev, repoId)), [])

  const notifyWhenReady = useCallback(async (repoId: string) => {
    if (!('Notification' in window)) return false
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return false
    setWatched((prev) => addTo(prev, repoId))
    return true
  }, [])

  const value = useMemo<RepoContextValue>(
    () => ({
      repos,
      repo,
      loading: isPending,
      error,
      selectRepo,
      partialAllowed: (repoId) => partial.has(repoId),
      allowPartial,
      notifying: (repoId) => watched.has(repoId) && !repos.some((r) => r.id === repoId && r.status === 'READY'),
      notifyWhenReady,
    }),
    [repos, repo, isPending, error, selectRepo, partial, allowPartial, watched, notifyWhenReady],
  )

  return <RepoContext value={value}>{children}</RepoContext>
}
