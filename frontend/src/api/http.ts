import type {
  Answer,
  Entity,
  EntityMatch,
  Evaluation,
  Explorer,
  Gap,
  Health,
  Ingestion,
  Lineage,
  Overview,
  Repo,
  RepoCheck,
  WhyCodeApi,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Params = Record<string, string | null>

/** Client for the WhyCode FastAPI. `baseUrl` is absolute ("http://localhost:8000/api") or a path ("/api"). */
export function createHttpApi(baseUrl: string, fetchFn: typeof fetch = fetch): WhyCodeApi {
  const base = baseUrl.replace(/\/+$/, '')

  async function request<T>(method: 'GET' | 'POST', path: string, params: Params, body?: object) {
    const url = new URL(base + path, window.location.origin)
    for (const [key, value] of Object.entries(params)) {
      if (value !== null) url.searchParams.set(key, value)
    }
    let res: Response
    try {
      res = await fetchFn(url, {
        method,
        headers: body
          ? { Accept: 'application/json', 'Content-Type': 'application/json' }
          : { Accept: 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
    } catch {
      // fetch only throws when no response came back at all (server down, offline, CORS).
      throw new ApiError(0, 'Could not reach the WhyCode API. Check that the backend is running.')
    }
    if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
    return (await res.json()) as T
  }

  const get = <T>(path: string, params: Params = {}) => request<T>('GET', path, params)
  const post = <T>(path: string, body: object) => request<T>('POST', path, {}, body)

  return {
    listRepos: () => get<Repo[]>('/repos'),
    checkRepo: (input) => post<RepoCheck>('/repos/check', { input }),
    addRepo: (repo, keepUpdated) => post<Repo>('/repos', { repo, keep_updated: keepUpdated }),
    syncRepo: (repo) => post<Repo>('/repos/sync', { repo }),
    getIngestion: (repo) => get<Ingestion>('/ingestion', { repo }),
    getOverview: (repo) => get<Overview>('/overview', { repo }),
    getExplorer: (repo) => get<Explorer>('/explorer', { repo }),
    searchEntities: (repo, text) => get<EntityMatch[]>('/entities/search', { repo, q: text }),
    getEntity: (repo, entityId) => get<Entity>('/entities', { repo, id: entityId }),
    ask: (repo, entityId, question) =>
      post<Answer>('/ask', { repo, entity_id: entityId, question }),
    getLineage: (repo, entityId, asOf) =>
      get<Lineage>('/lineage', { repo, entity_id: entityId, as_of: asOf }),
    getHealth: (repo) => get<Health>('/health', { repo }),
    getEvaluation: (repo) => get<Evaluation>('/evaluation', { repo }),
    reingest: (repo) => post<Repo>('/repos/reingest', { repo }),
    flagGap: (repo, entityId, question) =>
      post<Gap>('/gaps', { repo, entity_id: entityId, question }),
  }
}

/** FastAPI puts the reason in `detail`; fall back to the status text. Never echoes the request. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const data: unknown = await res.json()
    if (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string') {
      return data.detail
    }
  } catch {
    // body was not JSON
  }
  return res.statusText || `Request failed (${res.status})`
}
