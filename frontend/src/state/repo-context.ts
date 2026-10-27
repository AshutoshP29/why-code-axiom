import { createContext, useContext } from 'react'
import type { Repo } from '../api/types'

export interface RepoContextValue {
  repos: Repo[]
  /** The repository every screen is looking at; null until the list has loaded. */
  repo: Repo | null
  loading: boolean
  error: Error | null
  /** Load the repository list again after it failed. */
  retry: () => void
  selectRepo: (repoId: string) => void
  /** Repos the user chose to ask about before ingestion finished ("Ask now (partial history)"). */
  partialAllowed: (repoId: string) => boolean
  allowPartial: (repoId: string) => void
  /** "Notify me when ready": a browser notification fires when the repo turns READY. */
  notifying: (repoId: string) => boolean
  notifyWhenReady: (repoId: string) => Promise<boolean>
}

export const RepoContext = createContext<RepoContextValue | null>(null)

export function useRepo(): RepoContextValue {
  const value = useContext(RepoContext)
  if (!value) throw new Error('useRepo must be used inside <RepoProvider>')
  return value
}

/** Shortcut for the selected repo id, which nearly every query needs. */
export function useRepoId(): string | null {
  return useRepo().repo?.id ?? null
}
