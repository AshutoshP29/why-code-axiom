import { LinkButton } from '../components/ui'
import { useTitle } from '../lib/hooks'

export function NotFoundPage() {
  useTitle('Not found')
  return (
    <div className="mx-auto mt-24 max-w-md px-4 text-center">
      <h1 className="text-2xl font-semibold">This page does not exist</h1>
      <p className="mt-2 text-sm text-muted">The link may be old, or the address has a typo.</p>
      <LinkButton to="/" variant="primary" className="mt-5">
        Go to Home
      </LinkButton>
    </div>
  )
}
