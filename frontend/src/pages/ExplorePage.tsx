import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useEntitySearch, useExplorer } from '../api/queries'
import type { Entity } from '../api/types'
import { ExplorerPanel } from '../components/ExplorerPanel'
import { Badge, Card, ErrorNotice, LinkButton, Loading } from '../components/ui'
import { defaultQuestion, entityLabel, kindLabel } from '../lib/entity'
import { plural } from '../lib/format'
import { useTitle } from '../lib/hooks'
import { lineagePath, whyPath } from '../lib/routes'
import { useRepo } from '../state/repo-context'

function EntityRow({ entity, decisions }: { entity: Entity; decisions?: number }) {
  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
      <Badge>{kindLabel(entity.kind)}</Badge>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono text-sm">{entityLabel(entity)}</span>
        {entity.path && <span className="block truncate text-xs text-faint">{entity.path}</span>}
      </span>
      {decisions !== undefined && <span className="text-xs text-faint">{plural(decisions, 'decision')}</span>}
      <LinkButton variant="primary" to={whyPath(entity.id, defaultQuestion(entity))} className="px-3 py-1.5 text-xs">
        Ask why
      </LinkButton>
      <LinkButton variant="ghost" to={lineagePath(entity.id)} className="px-3 py-1.5 text-xs">
        History
      </LinkButton>
    </li>
  )
}

/** File tree plus search. The designs leave this page open; it reuses the Explorer sidebar. */
export function ExplorePage() {
  const [params] = useSearchParams()
  const { repo } = useRepo()
  const repoId = repo?.id ?? null
  const explorer = useExplorer(repoId)
  const [text, setText] = useState('')
  const search = useEntitySearch(repoId, text)
  useTitle('Explore')

  const files = explorer.data?.files ?? []
  const file = files.find((f) => f.entity.id === params.get('file')) ?? files[0]

  return (
    <div className="grid flex-1 grid-cols-1 lg:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="hidden border-r border-line bg-chrome lg:block">
        <ExplorerPanel activeFileId={file?.entity.id ?? null} />
      </aside>
      <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-8">
        <h1 className="text-2xl font-semibold">Explore</h1>
        <p className="mt-1 text-sm text-muted">Find a function, file or config key, then ask why or open its history.</p>
        <input
          type="search"
          aria-label="Search functions, files and config keys"
          placeholder="Search functions, files, config keys"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="mt-5 w-full rounded-xl border border-line bg-sunken px-4 py-2.5 text-sm outline-none placeholder:text-faint focus:border-teal/60"
        />

        {explorer.error && <ErrorNotice error={explorer.error} onRetry={() => explorer.refetch()} />}

        {text.trim() ? (
          <Card className="mt-4">
            <ul aria-label="Search results">
              {(search.data ?? []).map((e) => (
                <EntityRow key={e.id} entity={e} />
              ))}
            </ul>
            {search.data?.length === 0 && <p className="px-4 py-6 text-sm text-faint">Nothing matches “{text.trim()}”.</p>}
          </Card>
        ) : !explorer.data ? (
          !explorer.error && <Loading label="Loading files" />
        ) : file ? (
          <section className="mt-6" aria-labelledby="file-heading">
            <h2 id="file-heading" className="font-mono text-sm text-muted">
              {file.entity.path}
            </h2>
            <Card className="mt-3">
              <ul>
                <EntityRow entity={file.entity} decisions={file.decision_count} />
                {file.children.map((child) => (
                  <EntityRow key={child.entity.id} entity={child.entity} decisions={child.decision_count} />
                ))}
              </ul>
            </Card>
          </section>
        ) : (
          <p className="mt-6 text-sm text-faint">No files are mapped for {repoId} yet.</p>
        )}
      </div>
    </div>
  )
}
