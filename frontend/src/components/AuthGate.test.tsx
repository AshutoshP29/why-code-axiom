import { QueryClient } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AppProviders, AppRoutes } from '../App'
import { ApiError } from '../api/http'
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
    api.getMe = async () => ({ enabled: true, user: null, can_add_repos: false })
    api.loginUrl = (next) => `/api/auth/login?next=${encodeURIComponent(next)}`
    const listRepos = vi.spyOn(api, 'listRepos')
    renderLive(api)

    const link = await screen.findByRole('link', { name: 'Sign in with GitHub' })
    expect(link).toHaveAttribute('href', '/api/auth/login?next=%2Fhealth%3Fx%3D1')
    expect(listRepos).not.toHaveBeenCalled() // no data request before sign-in
  })

  it('shows the screens and the user once signed in, and signs out', async () => {
    const api = createMockApi({ delayMs: 0 })
    api.getMe = async () => ({ enabled: true, user: OCTOCAT, can_add_repos: true })
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

describe('reviewer sign-in', () => {
  function signedOut() {
    const api = createMockApi({ delayMs: 0 })
    let signedIn = false
    api.getMe = async () => ({
      enabled: true,
      user: signedIn ? { ...OCTOCAT, login: 'reviewer' } : null,
      can_add_repos: signedIn,
    })
    api.reviewerLogin = vi.fn(async (username: string, password: string) => {
      if (password !== 'right-password') throw new ApiError(401, 'Wrong username or password.')
      signedIn = username === 'reviewer'
    })
    return api
  }

  it('signs in with the reviewer username and password and shows the screens', async () => {
    const user = userEvent.setup()
    const api = signedOut()
    renderLive(api, '/health')
    await user.type(await screen.findByLabelText('Username'), ' reviewer ')
    await user.type(screen.getByLabelText('Password'), 'right-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(api.reviewerLogin).toHaveBeenCalledWith('reviewer', 'right-password')
    expect(await screen.findByRole('heading', { name: 'Graph health' })).toBeInTheDocument()
  })

  it('says why a sign-in failed and stays on the form', async () => {
    const user = userEvent.setup()
    renderLive(signedOut(), '/health')
    await user.type(await screen.findByLabelText('Username'), 'reviewer')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.')
    expect(screen.getByRole('link', { name: 'Sign in with GitHub' })).toBeInTheDocument()
  })
})
