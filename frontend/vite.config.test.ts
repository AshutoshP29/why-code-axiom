// @vitest-environment node
import { createServer as createHttpServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { createServer, type ProxyOptions } from 'vite'
import { afterEach, describe, expect, it } from 'vitest'
import config from './vite.config.ts'

const apiProxy = config.server?.proxy?.['/api'] as ProxyOptions

const toClose: (() => Promise<unknown>)[] = []
afterEach(async () => {
  await Promise.all(toClose.splice(0).map((close) => close()))
})

const closeServer = (server: Server) => new Promise((resolve) => server.close(resolve))

/** Stands in for the FastAPI app: records the path of every request and answers []. */
async function fakeBackend() {
  const paths: string[] = []
  const server = createHttpServer((req, res) => {
    paths.push(req.url ?? '')
    res.writeHead(200, { 'Content-Type': 'application/json' }).end('[]')
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  return { url, paths, server }
}

/** A dev server with the app's /api proxy, sent to `target` instead of port 8000. */
async function devServer(target: string): Promise<string> {
  const vite = await createServer({
    configFile: false,
    logLevel: 'silent',
    server: { host: '127.0.0.1', port: 0, proxy: { '/api': { ...apiProxy, target } } },
  })
  await vite.listen()
  toClose.push(() => vite.close())
  return vite.resolvedUrls!.local[0].replace(/\/$/, '')
}

describe('dev proxy', () => {
  it('sends /api to the FastAPI port on 127.0.0.1', () => {
    expect(apiProxy.target).toBe('http://127.0.0.1:8000')
  })

  it('passes /api paths and queries through unchanged', async () => {
    const backend = await fakeBackend()
    toClose.push(() => closeServer(backend.server))
    const base = await devServer(backend.url)

    const res = await fetch(`${base}/api/entities/search?repo=psf%2Frequests&q=auth`)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual([])
    expect(backend.paths).toEqual(['/api/entities/search?repo=psf%2Frequests&q=auth'])
  })

  it('answers with a FastAPI-style detail when the backend is not running', async () => {
    const backend = await fakeBackend()
    await closeServer(backend.server) // a port nothing listens on
    const base = await devServer(backend.url)

    const res = await fetch(`${base}/api/repos`)
    expect(res.status).toBe(502)
    expect(await res.json()).toEqual({
      detail: `The WhyCode API is not reachable at ${backend.url}. Start the backend, or run without VITE_API_URL to use sample data.`,
    })
  })
})
