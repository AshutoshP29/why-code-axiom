import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import { useApi } from '../api/context'
import { useMe } from '../api/queries'
import { Button, Card, ErrorNotice, Loading } from './ui'

/** Shows the screens only to a signed-in user when the API has sign-in on; sample data skips it. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { sample } = useApi()
  const me = useMe(!sample)
  if (sample) return children
  if (me.isPending || me.error)
    return (
      <main>
        <h1 className="sr-only">WhyCode</h1>
        {me.error ? (
          <ErrorNotice error={me.error} onRetry={() => me.refetch()} />
        ) : (
          <Loading label="Checking sign-in" />
        )}
      </main>
    )
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
        <ReviewerSignIn />
      </Card>
    </main>
  )
}

const FIELD =
  'w-full rounded-lg border border-line-strong bg-sunken px-3 py-2 text-sm placeholder:text-faint focus:border-teal focus:outline-none'

/** For evaluators and test tools that cannot sign in through GitHub. */
function ReviewerSignIn() {
  const { api } = useApi()
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.reviewerLogin(username.trim(), password)
      await queryClient.invalidateQueries({ queryKey: ['me'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-6 border-t border-line pt-5 text-left" aria-labelledby="reviewer-heading">
      <h2 id="reviewer-heading" className="text-sm font-semibold">
        Reviewer account
      </h2>
      <p className="mt-1 text-xs text-faint">For evaluators given a WhyCode username and password.</p>
      <label htmlFor="reviewer-username" className="mt-3 block text-xs text-muted">
        Username
      </label>
      <input
        id="reviewer-username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        className={FIELD}
        required
      />
      <label htmlFor="reviewer-password" className="mt-3 block text-xs text-muted">
        Password
      </label>
      <input
        id="reviewer-password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        className={FIELD}
        required
      />
      {error && (
        <p role="alert" className="mt-3 text-xs text-red">
          {error}
        </p>
      )}
      <Button type="submit" className="mt-4 w-full" disabled={busy || !username.trim() || !password}>
        {busy ? 'Signing in…' : 'Sign in'}
      </Button>
    </form>
  )
}
