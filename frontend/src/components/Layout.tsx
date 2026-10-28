import { useState } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router'
import { useRepo } from '../state/repo-context'
import { AddRepoDialog } from './AddRepoDialog'
import { TopBar, type TopBarAsk } from './TopBar'
import { Button, ErrorNotice, Loading } from './ui'

function NoRepos() {
  const [adding, setAdding] = useState(false)
  return (
    <div className="mx-auto mt-24 max-w-md px-4 text-center">
      <h1 className="text-2xl font-semibold">No repositories yet</h1>
      <p className="mt-2 text-sm text-muted">Add a public GitHub repository and WhyCode will read its history.</p>
      <Button variant="primary" className="mt-5" onClick={() => setAdding(true)}>
        Add a repository
      </Button>
      {adding && <AddRepoDialog onClose={() => setAdding(false)} />}
    </div>
  )
}

export function Layout() {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const { repo, loading, error, retry } = useRepo()

  // Answer pages swap the nav for an ask bar holding the current question, as in the designs.
  const entityId = params.get('entity')
  const question = params.get('q') ?? ''
  const ask: TopBarAsk | null =
    pathname === '/why' && (entityId || question.trim())
      ? { entityId, text: question }
      : entityId && pathname === '/lineage'
        ? { entityId, text: null }
        : null

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-teal px-3 py-2 text-teal-ink focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <TopBar ask={repo ? ask : null} />
      <main id="main" tabIndex={-1} className="flex flex-1 flex-col">
        {loading ? (
          <Loading label="Loading repositories" />
        ) : error ? (
          <ErrorNotice error={error} onRetry={retry} />
        ) : !repo ? (
          <NoRepos />
        ) : (
          <Outlet />
        )}
      </main>
    </div>
  )
}
