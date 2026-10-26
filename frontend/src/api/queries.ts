import {
  keepPreviousData,
  skipToken,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useApi } from './context'
import type { Repo } from './types'

const isBusy = (repo: Repo) => repo.status === 'QUEUED' || repo.status === 'INGESTING'

export function useRepos() {
  const { api } = useApi()
  return useQuery({
    queryKey: ['repos'],
    queryFn: () => api.listRepos(),
    // Keep progress moving in the switcher while anything is being read.
    refetchInterval: (query) => (query.state.data?.some(isBusy) ? 3000 : false),
  })
}

export function useIngestion(repo: string | null) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['ingestion', repo],
    queryFn: repo ? () => api.getIngestion(repo) : skipToken,
    refetchInterval: (query) => (query.state.data && !isBusy(query.state.data.repo) ? false : 2000),
  })
}

export function useOverview(repo: string | null) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['overview', repo],
    queryFn: repo ? () => api.getOverview(repo) : skipToken,
  })
}

export function useExplorer(repo: string | null) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['explorer', repo],
    queryFn: repo ? () => api.getExplorer(repo) : skipToken,
  })
}

export function useEntitySearch(repo: string | null, text: string) {
  const { api } = useApi()
  const q = text.trim()
  return useQuery({
    queryKey: ['entity-search', repo, q],
    queryFn: repo && q ? () => api.searchEntities(repo, q) : skipToken,
    placeholderData: keepPreviousData,
  })
}

export function useEntity(repo: string | null, entityId: string | null) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['entity', repo, entityId],
    queryFn: repo && entityId ? () => api.getEntity(repo, entityId) : skipToken,
    staleTime: Infinity,
  })
}

export function useAnswer(repo: string | null, entityId: string | null, question: string) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['answer', repo, entityId, question],
    queryFn: repo && entityId ? () => api.ask(repo, entityId, question) : skipToken,
    staleTime: 5 * 60_000,
  })
}

export function useLineage(repo: string | null, entityId: string | null, asOf: string | null) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['lineage', repo, entityId, asOf],
    queryFn: repo && entityId ? () => api.getLineage(repo, entityId, asOf) : skipToken,
    placeholderData: keepPreviousData, // switching "View as of" keeps the old cards until the new ones land
  })
}

export function useHealth(repo: string | null) {
  const { api } = useApi()
  return useQuery({
    queryKey: ['health', repo],
    queryFn: repo ? () => api.getHealth(repo) : skipToken,
    refetchInterval: (query) =>
      query.state.data?.stages.some((s) => s.state === 'running') ? 5000 : false,
  })
}

export function useCheckRepo() {
  const { api } = useApi()
  return useMutation({ mutationFn: (input: string) => api.checkRepo(input) })
}

export function useAddRepo() {
  const { api } = useApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ repo, keepUpdated }: { repo: string; keepUpdated: boolean }) =>
      api.addRepo(repo, keepUpdated),
    onSuccess: () => client.invalidateQueries({ queryKey: ['repos'] }),
  })
}

/** Refetch everything that belongs to a repo after its data changed. */
function useInvalidateRepo() {
  const client = useQueryClient()
  return (repo: string) =>
    client.invalidateQueries({
      predicate: (query) => query.queryKey[0] === 'repos' || query.queryKey[1] === repo,
    })
}

export function useSyncRepo() {
  const { api } = useApi()
  const invalidate = useInvalidateRepo()
  return useMutation({
    mutationFn: (repo: string) => api.syncRepo(repo),
    onSuccess: (repo) => invalidate(repo.id),
  })
}

export function useReingest() {
  const { api } = useApi()
  const invalidate = useInvalidateRepo()
  return useMutation({
    mutationFn: (repo: string) => api.reingest(repo),
    onSuccess: (repo) => invalidate(repo.id),
  })
}

export function useFlagGap(repo: string | null) {
  const { api } = useApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ entityId, question }: { entityId: string; question: string }) => {
      if (!repo) throw new Error('No repository selected')
      return api.flagGap(repo, entityId, question)
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['health', repo] }),
  })
}
