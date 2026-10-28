import type { Page, Route } from '@playwright/test'
import { ApiError } from '../src/api/http'
import { createMockApi } from '../src/api/mock'
import type { WhyCodeApi } from '../src/api/types'
import { expect, ID, test, why } from './fixtures'

// The real HTTP client (VITE_API_URL=/api) against a fake backend that answers /api/* inside the
// browser. It checks the requests the screens send and how they cope when the backend misbehaves.

interface Call {
  method: string
  path: string
  params: Record<string, string>
  body: unknown
}

type Fault = (call: Call) => { status: number; detail: string } | 'abort' | number | null // number = delay in ms

function dispatch(api: WhyCodeApi, { method, path, params: q, body }: Call): Promise<unknown> {
  const b = (body ?? {}) as Record<string, string>
  switch (`${method} ${path}`) {
    case 'GET /repos': return api.listRepos()
    case 'POST /repos/check': return api.checkRepo(b.input)
    case 'POST /repos': return api.addRepo(b.repo, Boolean(b.keep_updated))
    case 'POST /repos/sync': return api.syncRepo(b.repo)
    case 'POST /repos/reingest': return api.reingest(b.repo)
    case 'GET /ingestion': return api.getIngestion(q.repo)
    case 'GET /overview': return api.getOverview(q.repo)
    case 'GET /explorer': return api.getExplorer(q.repo)
    case 'GET /entities/search': return api.searchEntities(q.repo, q.q)
    case 'GET /entities': return api.getEntity(q.repo, q.id)
    case 'POST /ask': return api.ask(b.repo, b.entity_id, b.question)
    case 'GET /lineage': return api.getLineage(q.repo, q.entity_id, q.as_of ?? null)
    case 'GET /health': return api.getHealth(q.repo)
    case 'GET /evaluation': return api.getEvaluation(q.repo)
    case 'POST /gaps': return api.flagGap(b.repo, b.entity_id, b.question)
    default: return Promise.reject(new ApiError(404, `No route ${method} ${path}`))
  }
}

/** `edit` changes a successful response before it is sent, to play a backend with other settings. */
async function fakeBackend(page: Page, fault: Fault = () => null, edit: (call: Call, data: unknown) => unknown = (_, d) => d) {
  const api = createMockApi({ delayMs: 0 })
  const calls: Call[] = []
  // Only the API: the dev server also serves source files under /src/api/.
  await page.route((url) => url.pathname.startsWith('/api/'), async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const call: Call = {
      method: req.method(),
      path: url.pathname.replace(/^\/api/, ''),
      params: Object.fromEntries(url.searchParams),
      body: req.postData() ? req.postDataJSON() : null,
    }
    calls.push(call)
    const f = fault(call)
    if (f === 'abort') return route.abort('connectionrefused')
    if (typeof f === 'number') await new Promise((r) => setTimeout(r, f))
    else if (f) return route.fulfill({ status: f.status, json: { detail: f.detail } })
    try {
      await route.fulfill({ json: edit(call, await dispatch(api, call)) })
    } catch (e) {
      if (!(e instanceof ApiError)) throw e
      await route.fulfill({ status: e.status, json: { detail: e.message } })
    }
  })
  return calls
}

test('Talks to the API: no sample badge, and requests carry the repo and graph ids', async ({ page }) => {
  const calls = await fakeBackend(page)
  await page.goto('/')
  await expect(page.getByText('Hotspots')).toBeVisible()
  await expect(page.getByText('Sample data')).toHaveCount(0)

  await page.getByRole('link', { name: 'Why does rebuild_auth strip headers?' }).click()
  await expect(page.getByText('Active decision', { exact: true })).toBeVisible()

  expect(calls).toContainEqual({
    method: 'POST',
    path: '/ask',
    params: {},
    body: { repo: 'psf/requests', entity_id: ID.rebuildAuth, question: 'Why does rebuild_auth strip headers?' },
  })
  const scoped = calls.filter((c) => c.method === 'GET' && c.path !== '/repos')
  expect(scoped.length).toBeGreaterThan(0)
  for (const c of scoped) expect(c.params.repo, `${c.path} must say which repo`).toBe('psf/requests')
})

test('A plain question sends entity_id: null, and the page shows what the API matched', async ({ page }) => {
  const calls = await fakeBackend(page)
  await page.goto(why(null, 'why does rebuild_auth strip the header?'))
  await expect(page.getByText(/^Matched to/)).toContainText('SessionRedirectMixin.rebuild_auth (score 0.90)')
  expect(calls).toContainEqual({
    method: 'POST',
    path: '/ask',
    params: {},
    body: { repo: 'psf/requests', entity_id: null, question: 'why does rebuild_auth strip the header?' },
  })
})

test('A hedged answer shows its warning and the thresholds the API sent', async ({ page }) => {
  await fakeBackend(page, undefined, (call, data) =>
    call.path === '/ask' ? { ...(data as object), thresholds: { answer: 0.8, refuse: 0.5 } } : data,
  )
  await page.goto(why(ID.timeout, 'q'))
  await expect(page.getByRole('region', { name: 'Low confidence: check before relying on this' })).toBeVisible()
  await expect(page.getByText('Refuses below 50% · warns below 80%')).toBeVisible()
})

test.describe('when the backend fails', () => {
  test.use({ allowConsoleErrors: [/Failed to load resource/] })

  test('shows the reason, and Try again recovers once the backend is back', async ({ page }) => {
    let down = true
    await fakeBackend(page, (c) => (down && c.path === '/repos' ? { status: 503, detail: 'Database unavailable' } : null))
    await page.goto('/')
    await expect(page.getByRole('alert')).toContainText('Database unavailable')
    down = false
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByText('Hotspots')).toBeVisible()
  })

  test('says plainly when the backend cannot be reached', async ({ page }) => {
    await fakeBackend(page, () => 'abort')
    await page.goto('/')
    await expect(page.getByRole('alert')).toContainText('Could not reach the WhyCode API')
  })

  test('shows the API reason for an unknown item', async ({ page }) => {
    await fakeBackend(page)
    await page.goto(why('psf/requests#fn:src/requests/nope.py::nope', 'q'))
    await expect(page.getByRole('alert')).toContainText('That item is not in the graph for this repository')
  })
})

test('A slow answer shows a loading state, then the answer', async ({ page }) => {
  await fakeBackend(page, (c) => (c.path === '/ask' ? 1500 : null))
  await page.goto(why(ID.rebuildAuth, 'q'))
  await expect(page.getByText('Tracing the history…')).toBeVisible()
  await expect(page.getByText('Active decision', { exact: true })).toBeVisible({ timeout: 10_000 })
})

test('Flagging a gap sends the item and the question', async ({ page }) => {
  const calls = await fakeBackend(page)
  await page.goto(why(ID.poolMaxsize, 'why is the default 10?'))
  await page.getByRole('button', { name: 'Flag as missing context' }).click()
  await expect(page.getByRole('button', { name: 'Flagged' })).toBeVisible()
  expect(calls).toContainEqual({
    method: 'POST',
    path: '/gaps',
    params: {},
    body: { repo: 'psf/requests', entity_id: ID.poolMaxsize, question: 'why is the default 10?' },
  })
})
