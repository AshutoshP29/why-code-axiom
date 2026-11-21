import { QueryClient } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AppProviders, AppRoutes } from '../App'
import { createMockApi } from '../api/mock'
import type { User, WhyCodeApi } from '../api/types'

const OCTOCAT: User = { login: 'octocat', name: 'The Octocat', avatar_url: 'https://example.com/a.png' }

function renderLive(api: WhyCodeApi, path = '/health?x=1') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppProviders api={{ api, sample: false }} queryClient={queryClient}>
        <AppRoutes />
      </AppProviders>
    </MemoryRouter>,
  )
}

describe('sign-in', () => {
  it('asks a signed-out visitor to sign in, coming back to the same page', async () => {
    const api = createMockApi({ delayMs: 0 })
    api.getMe = async () => ({ enabled: true, user: null })
    api.loginUrl = (next) => `/api/auth/login?next=${encodeURIComponent(next)}`
    const listRepos = vi.spyOn(api, 'listRepos')
    renderLive(api)

    const link = await screen.findByRole('link', { name: 'Sign in with GitHub' })
    expect(link).toHaveAttribute('href', '/api/auth/login?next=%2Fhealth%3Fx%3D1')
    expect(listRepos).not.toHaveBeenCalled() // no data request before sign-in
  })

  it('shows the screens and the user once signed in, and signs out', async () => {
    const api = createMockApi({ delayMs: 0 })
    api.getMe = async () => ({ enabled: true, user: OCTOCAT })
    const logout = vi.fn(async () => {})
    api.logout = logout
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    renderLive(api, '/health')

    expect(await screen.findByRole('heading', { name: 'Graph health' })).toBeInTheDocument()
    expect(screen.getByText('octocat')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign out' }))
    expect(logout).toHaveBeenCalled()
    expect(assign).toHaveBeenCalledWith('/')
    vi.unstubAllGlobals()
  })

  it('stays open when the API has sign-in off', async () => {
    renderLive(createMockApi({ delayMs: 0 }), '/health')
    expect(await screen.findByRole('heading', { name: 'Graph health' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  })
})
