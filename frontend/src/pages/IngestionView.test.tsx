import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { createMockApi } from '../api/mock'
import { sampleStages } from '../api/sample'
import type { Repo, WhyCodeApi } from '../api/types'
import { renderApp } from '../test/render'

const ERROR_MESSAGE = 'The AI provider quota ran out after 412 of 958 threads.'

/** The sample API, except pallets/flask stopped while reading discussions. */
function apiWithStoppedRepo(): WhyCodeApi {
  const base = createMockApi({ delayMs: 0 })
  const stop = (r: Repo): Repo =>
    r.id === 'pallets/flask'
      ? { ...r, status: 'ERROR', stage: 'extract', partial: true, error: ERROR_MESSAGE }
      : r
  return {
    ...base,
    listRepos: async () => (await base.listRepos()).map(stop),
    getIngestion: async (repoId) => {
      const ingestion = await base.getIngestion(repoId)
      const repo = stop(ingestion.repo)
      return { repo, stages: sampleStages(repo) }
    },
  }
}

describe('Ingestion stopped', () => {
  it('says where reading stopped and why', async () => {
    window.localStorage.setItem('whycode.repo', 'pallets/flask')
    renderApp('/', { api: apiWithStoppedRepo() })

    expect(await screen.findByRole('heading', { name: 'Reading pallets/flask stopped' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(ERROR_MESSAGE)
    expect(screen.getByText('stopped')).toBeInTheDocument() // the failed stage's badge
    expect(screen.getAllByText('done')).toHaveLength(3)
    expect(screen.queryByRole('button', { name: 'Notify me when ready' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /current:\s*pallets\/flask/ })).toHaveTextContent('Stopped')
  })

  it('runs it again', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem('whycode.repo', 'pallets/flask')
    const api = apiWithStoppedRepo()
    const reingest = vi.spyOn(api, 'reingest')
    renderApp('/', { api })

    await user.click(await screen.findByRole('button', { name: 'Run it again' }))
    expect(reingest).toHaveBeenCalledWith('pallets/flask')
  })

  it('lets you ask about what was read, with a partial-history warning', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem('whycode.repo', 'pallets/flask')
    renderApp('/', { api: apiWithStoppedRepo() })

    await user.click(await screen.findByRole('button', { name: 'Ask about what was read' }))
    expect(
      await screen.findByText(/Partial history: reading pallets\/flask stopped before it finished/),
    ).toBeInTheDocument()
  })
})
