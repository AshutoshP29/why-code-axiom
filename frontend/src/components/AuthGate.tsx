import type { ReactNode } from 'react'
import { useLocation } from 'react-router'
import { useApi } from '../api/context'
import { useMe } from '../api/queries'
import { Card, ErrorNotice, Loading } from './ui'

/** Shows the screens only to a signed-in user when the API has sign-in on; sample data skips it. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { sample } = useApi()
  const me = useMe(!sample)
  if (sample) return children
  if (me.isPending) return <Loading label="Checking sign-in" />
  if (me.error) return <ErrorNotice error={me.error} onRetry={() => me.refetch()} />
  if (me.data.enabled && !me.data.user) return <SignIn />
  return children
}

function SignIn() {
  const { api } = useApi()
  const { pathname, search } = useLocation()
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <Card className="w-full max-w-md p-8 text-center">
        <span
          aria-hidden
          className="mx-auto grid size-10 place-items-center rounded-lg bg-teal text-lg font-bold text-teal-ink"
        >
          W
        </span>
        <h1 className="mt-4 text-2xl font-semibold">Sign in to WhyCode</h1>
        <p className="mt-2 text-sm text-muted">
          Ask why the code is the way it is, and get the decision behind it with its evidence. WhyCode only
          reads your GitHub name and picture.
        </p>
        <a
          href={api.loginUrl(pathname + search)}
          className="mt-6 inline-flex items-center justify-center rounded-lg bg-teal px-4 py-2.5 text-sm font-semibold text-teal-ink hover:opacity-90"
        >
          Sign in with GitHub
        </a>
      </Card>
    </main>
  )
}
