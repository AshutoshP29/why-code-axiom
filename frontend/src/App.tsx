import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Route, Routes } from 'react-router'
import { ApiContext, type ApiContextValue } from './api/context'
import { Layout } from './components/Layout'
import { ExplorePage } from './pages/ExplorePage'
import { HealthPage } from './pages/HealthPage'
import { HomePage } from './pages/HomePage'
import { LineagePage } from './pages/LineagePage'
import { NotFoundPage } from './pages/NotFoundPage'
import { WhyPage } from './pages/WhyPage'
import { RepoProvider } from './state/RepoProvider'

export function AppProviders({
  api,
  queryClient,
  children,
}: {
  api: ApiContextValue
  queryClient?: QueryClient
  children: ReactNode
}) {
  const [client] = useState(
    () =>
      queryClient ??
      new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } }),
  )
  return (
    <QueryClientProvider client={client}>
      <ApiContext value={api}>
        <RepoProvider>{children}</RepoProvider>
      </ApiContext>
    </QueryClientProvider>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="why" element={<WhyPage />} />
        <Route path="lineage" element={<LineagePage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="explore" element={<ExplorePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
