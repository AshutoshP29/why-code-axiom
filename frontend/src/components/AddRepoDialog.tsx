import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { useApi } from '../api/context'
import { useAddRepo, useCheckRepo } from '../api/queries'
import { parseRepoInput } from '../lib/entity'
import { formatCount } from '../lib/format'
import { useRepo } from '../state/repo-context'
import { Dialog } from './Dialog'
import { Badge, Button } from './ui'

export function AddRepoDialog({ initialInput = '', onClose }: { initialInput?: string; onClose: () => void }) {
  const { sample } = useApi()
  const { selectRepo } = useRepo()
  const navigate = useNavigate()
  const [input, setInput] = useState(initialInput)
  const [keepUpdated, setKeepUpdated] = useState(true)
  const check = useCheckRepo()
  const add = useAddRepo()

  // A result only counts while the input still names the repo that was checked.
  const result = check.data && parseRepoInput(input) === check.data.repo ? check.data : null

  function onCheck(e: FormEvent) {
    e.preventDefault()
    add.reset()
    check.mutate(input)
  }

  function onStart() {
    if (!result) return
    add.mutate(
      { repo: result.repo, keepUpdated },
      {
        onSuccess: (repo) => {
          selectRepo(repo.id)
          onClose()
          navigate('/')
        },
      },
    )
  }

  return (
    <Dialog
      title="Add a repository"
      description="Paste a public GitHub link. We check it first and tell you how long it will take."
      onClose={onClose}
    >
      <form
        onSubmit={onCheck}
        className="flex items-center gap-2 rounded-xl border border-teal/40 bg-sunken p-2 pl-3 focus-within:border-teal/80"
      >
        <input
          aria-label="GitHub link or owner/name"
          placeholder="github.com/owner/name"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
        />
        <Button type="submit" variant="primary" disabled={!input.trim() || check.isPending}>
          {check.isPending ? 'Checking…' : 'Check'}
        </Button>
      </form>

      {check.error && (
        <p role="alert" className="mt-3 text-sm text-red">
          {check.error.message}
        </p>
      )}

      {result && !result.found && (
        <p role="alert" className="mt-3 text-sm text-red">
          We could not find a public repository at that link.
        </p>
      )}

      {result?.found && (
        <div className="mt-4 rounded-xl border border-teal/30 bg-raised p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="green">Public repository found</Badge>
            <span className="text-sm font-semibold">{result.repo}</span>
            <Badge tone="amber" className="ml-auto">
              {sample ? 'Sample estimate' : 'Estimate'}
            </Badge>
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2">
            {(
              [
                ['Commits', result.commits],
                ['Pull requests', result.pull_requests],
                ['Issues', result.issues],
              ] as const
            ).map(([label, n]) => (
              <div key={label} className="rounded-lg bg-sunken px-3 py-2">
                <dt className="text-[10px] font-semibold tracking-wider text-faint uppercase">{label}</dt>
                <dd className="text-sm font-semibold">about {formatCount(n)}</dd>
              </div>
            ))}
          </dl>
          <dl className="mt-3 space-y-1 text-xs">
            <div className="flex justify-between">
              <dt className="text-muted">Estimated time</dt>
              <dd className="font-semibold">
                {result.minutes_low} to {result.minutes_high} minutes
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">AI calls needed</dt>
              <dd className="font-semibold">about {formatCount(result.ai_calls)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Database room</dt>
              <dd className="font-semibold">
                {result.fits_free_tier ? 'fits the free tier' : 'needs more than the free tier'}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {result?.capped && (
        <p className="mt-3 rounded-lg border border-amber/30 bg-amber/10 px-3 py-2 text-xs text-muted">
          Large repositories are capped to their most-discussed pull requests and issues.
        </p>
      )}

      <label className="mt-4 flex cursor-pointer items-center gap-3 text-sm text-muted">
        <button
          type="button"
          role="switch"
          aria-checked={keepUpdated}
          onClick={() => setKeepUpdated((v) => !v)}
          className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${keepUpdated ? 'bg-teal' : 'bg-track'}`}
        >
          <span
            className={`absolute top-0.5 size-4 rounded-full bg-canvas transition-all ${keepUpdated ? 'left-4.5' : 'left-0.5'}`}
          />
        </button>
        Keep it up to date (check for changes every 15 minutes)
      </label>

      {add.error && (
        <p role="alert" className="mt-3 text-sm text-red">
          {add.error.message}
        </p>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!result?.found || add.isPending} onClick={onStart}>
          {add.isPending ? 'Starting…' : 'Start ingestion'}
        </Button>
      </div>
    </Dialog>
  )
}
