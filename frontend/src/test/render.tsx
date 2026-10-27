import { QueryClient } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AppProviders, AppRoutes } from '../App'
import { createMockApi } from '../api/mock'
import type { WhyCodeApi } from '../api/types'
import { LocationProbe } from './LocationProbe'

/** The whole app on the sample data, starting at `path`. */
export function renderApp(path = '/', { api = createMockApi({ delayMs: 0 }) }: { api?: WhyCodeApi } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const result = render(
    <MemoryRouter initialEntries={[path]}>
      <AppProviders api={{ api, sample: true }} queryClient={queryClient}>
        <AppRoutes />
        <LocationProbe />
      </AppProviders>
    </MemoryRouter>,
  )
  return { ...result, api }
}

/** Current router location as "/path?query", decoded for readable assertions. */
export function currentLocation(): string {
  return decodeURIComponent(screen.getByTestId('location').textContent ?? '').replace(/\+/g, ' ')
}
