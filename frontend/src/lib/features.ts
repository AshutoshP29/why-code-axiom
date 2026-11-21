import { useApi } from '../api/context'
import { useMe } from '../api/queries'

/**
 * Adding, syncing and re-reading a repository start long ingestion runs. Built with
 * VITE_INGEST_ACTIONS=off, the screens leave those buttons out entirely.
 */
export const INGEST_ACTIONS = import.meta.env.VITE_INGEST_ACTIONS !== 'off'

/**
 * Whether to offer Add repository (and, for repos added from the screens, Sync now and Re-run):
 * the build allows it and the API says this user may (sign-in off, or on the WHYCODE_ADDERS list).
 * Sample data always may.
 */
export function useIngestActions(): boolean {
  const { sample } = useApi()
  const me = useMe(!sample)
  return INGEST_ACTIONS && (sample || me.data?.can_add_repos === true)
}
