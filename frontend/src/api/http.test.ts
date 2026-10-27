import { describe, expect, it, vi } from 'vitest'
import { ApiError, createHttpApi } from './http'

function fakeFetch(body: unknown, init: ResponseInit = { status: 200 }) {
  return vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), init))
}

const calledUrl = (f: ReturnType<typeof fakeFetch>) => new URL(String(f.mock.calls[0][0]))

describe('createHttpApi', () => {
  it('sends GETs with the repo and encodes graph ids', async () => {
    const f = fakeFetch({})
    const api = createHttpApi('/api/', f)
    await api.getLineage('psf/requests', 'psf/requests#cfg:max_retries', null)

    const url = calledUrl(f)
    expect(url.pathname).toBe('/api/lineage')
    expect(url.searchParams.get('repo')).toBe('psf/requests')
    expect(url.searchParams.get('entity_id')).toBe('psf/requests#cfg:max_retries')
    expect(url.searchParams.has('as_of')).toBe(false) // null means "today", so it is left out
    expect(f.mock.calls[0][1]?.method).toBe('GET')
  })

  it('passes as_of when time travelling', async () => {
    const f = fakeFetch({})
    await createHttpApi('/api', f).getLineage('psf/requests', 'x', '2016-12-31')
    expect(calledUrl(f).searchParams.get('as_of')).toBe('2016-12-31')
  })

  it('POSTs questions as JSON', async () => {
    const f = fakeFetch({ verdict: 'refused' })
    await createHttpApi('/api', f).ask('psf/requests', 'psf/requests#cfg:pool_maxsize', 'Why 10?')

    const init = f.mock.calls[0][1]
    expect(calledUrl(f).pathname).toBe('/api/ask')
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(init?.body))).toEqual({
      repo: 'psf/requests',
      entity_id: 'psf/requests#cfg:pool_maxsize',
      question: 'Why 10?',
    })
  })

  it('sends entity_id: null for a question asked without an entity', async () => {
    const f = fakeFetch({ verdict: 'refused' })
    await createHttpApi('/api', f).ask('psf/requests', null, 'why did requests drop chardet?')

    const body: unknown = JSON.parse(String(f.mock.calls[0][1]?.body))
    expect(body).toEqual({ repo: 'psf/requests', entity_id: null, question: 'why did requests drop chardet?' })
    expect(body).toHaveProperty('entity_id', null) // present and null, not left out
  })

  it('works with an absolute base URL', async () => {
    const f = fakeFetch([])
    await createHttpApi('http://localhost:8000/api', f).listRepos()
    expect(calledUrl(f).href).toBe('http://localhost:8000/api/repos')
  })

  it('raises the FastAPI detail on errors', async () => {
    const f = fakeFetch({ detail: 'That item is not in the graph' }, { status: 404, statusText: 'Not Found' })
    const error = await createHttpApi('/api', f).getEntity('psf/requests', 'nope').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, message: 'That item is not in the graph' })
  })

  it('falls back to the status text when the error body is not JSON', async () => {
    const f = vi.fn<typeof fetch>(async () => new Response('oops', { status: 502, statusText: 'Bad Gateway' }))
    await expect(createHttpApi('/api', f).listRepos()).rejects.toMatchObject({ status: 502, message: 'Bad Gateway' })
  })
})
