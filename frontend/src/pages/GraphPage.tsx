import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useEntitySearch, useGraphView } from '../api/queries'
import type { GraphView, GraphViewKind, GraphViewNode } from '../api/types'
import { ForceGraph } from '../components/ForceGraph'
import { Badge, Button, ErrorNotice, LinkButton, Loading, SectionLabel } from '../components/ui'
import { entityLabel, questionAbout } from '../lib/entity'
import { formatNumber, plural } from '../lib/format'
import { isCodeKind, KIND_ORDER, KIND_STYLE } from '../lib/graph-kinds'
import { useTitle } from '../lib/hooks'
import { lineagePath, whyPath } from '../lib/routes'
import { cx } from '../lib/tones'
import { useRepoId } from '../state/repo-context'

/** How long a node new since the last fetch stays highlighted. */
export const FRESH_MS = 4000
const LINKS_SHOWN = 12
const RESULTS_SHOWN = 8

/** Ids that the latest fetch added to the one before it; empty after FRESH_MS. */
function useFreshIds(view: GraphView | undefined): ReadonlySet<string> {
  const before = useRef<Set<string> | null>(null)
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set())
  useEffect(() => {
    if (!view) return
    const ids = new Set(view.nodes.map((n) => n.id))
    const previous = before.current
    before.current = ids
    const added = previous ? [...ids].filter((id) => !previous.has(id)) : []
    if (added.length === 0) return
    setFresh(new Set(added))
    const timer = window.setTimeout(() => setFresh(new Set()), FRESH_MS)
    return () => window.clearTimeout(timer)
  }, [view])
  return fresh
}

function Swatch({ kind }: { kind: GraphViewKind }) {
  const style = KIND_STYLE[kind]
  return (
    <svg aria-hidden width="14" height="14" viewBox="-7 -7 14 14" className="shrink-0">
      <circle
        r={Math.min(6, style.radius)}
        fill={style.ring ? 'none' : style.color}
        stroke={style.color}
        strokeWidth={style.ring ? 1.75 : 0}
      />
    </svg>
  )
}

function Legend({ nodes }: { nodes: GraphViewNode[] }) {
  const present = new Set(nodes.map((n) => n.kind))
  return (
    <ul aria-label="Legend" className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted">
      {KIND_ORDER.filter((k) => present.has(k)).map((kind) => (
        <li key={kind} className="flex items-center gap-1.5">
          <Swatch kind={kind} /> {KIND_STYLE[kind].label}
        </li>
      ))}
    </ul>
  )
}

function LiveToggle({ live, onChange }: { live: boolean; onChange: (live: boolean) => void }) {
  return (
    <button
      type="button"
      aria-pressed={live}
      onClick={() => onChange(!live)}
      title={live ? 'Refreshing every 5 seconds' : 'Refresh every 5 seconds'}
      className={cx(
        'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-semibold',
        live ? 'border-green/40 bg-green/10 text-green' : 'border-line-strong bg-raised text-muted hover:text-ink',
      )}
    >
      <span aria-hidden className={cx('size-2 rounded-full', live ? 'animate-pulse bg-green' : 'bg-gray')} />
      Live
    </button>
  )
}

interface Result {
  id: string
  label: string
  kind: GraphViewKind
}

/** Code items from the search index, plus anything already drawn whose label matches. */
function GraphSearch({
  repoId,
  nodes,
  onPick,
}: {
  repoId: string | null
  nodes: GraphViewNode[]
  onPick: (id: string) => void
}) {
  const [text, setText] = useState('')
  const search = useEntitySearch(repoId, text)
  const q = text.trim().toLowerCase()
  const results: Result[] = []
  if (q) {
    const seen = new Set<string>()
    const code = (search.data ?? []).map((e) => ({ id: e.id, label: entityLabel(e), kind: e.kind }))
    const drawn = nodes.filter((n) => !isCodeKind(n.kind) && n.label.toLowerCase().includes(q))
    for (const r of [...code, ...drawn]) {
      if (!seen.has(r.id) && results.length < RESULTS_SHOWN) {
        seen.add(r.id)
        results.push({ id: r.id, label: r.label, kind: r.kind })
      }
    }
  }
  return (
    <div role="search" aria-label="Find a node" className="relative mt-3 max-w-xl">
      <input
        type="search"
        aria-label="Search the graph"
        placeholder="Search code, pull requests, decisions, people"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && setText('')}
        className="w-full rounded-xl border border-line bg-sunken px-4 py-2.5 text-sm outline-none placeholder:text-faint focus:border-teal/60"
      />
      {q && (
        <ul
          aria-label="Search results"
          className="absolute inset-x-0 top-full z-20 mt-1 max-h-80 overflow-auto rounded-xl border border-line bg-surface py-1 shadow-lg"
        >
          {results.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => {
                  onPick(r.id)
                  setText('')
                }}
                className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm hover:bg-raised"
              >
                <Badge tone={KIND_STYLE[r.kind].tone}>{KIND_STYLE[r.kind].label}</Badge>
                <span className="min-w-0 truncate font-mono">{r.label}</span>
              </button>
            </li>
          ))}
          {results.length === 0 && !search.isFetching && (
            <li className="px-4 py-3 text-sm text-faint">Nothing matches “{text.trim()}”.</li>
          )}
        </ul>
      )}
    </div>
  )
}

function Note({ view, focusNode }: { view: GraphView; focusNode: GraphViewNode | undefined }) {
  if (!view.truncated) return null
  const shown = formatNumber(view.nodes.length)
  return (
    <p role="note" className="mt-3 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-sm text-ink">
      {view.scope === 'decisions'
        ? `Showing the decision graph: ${shown} of ${formatNumber(view.total_nodes)} nodes. Search to focus.`
        : view.scope === 'focus'
          ? `Showing the ${shown} nodes nearest to ${focusNode?.label ?? 'this node'}; more are linked to it.`
          : `Showing ${shown} of ${formatNumber(view.total_nodes)} nodes. Search to focus.`}
    </p>
  )
}

function NodePanel({
  node,
  view,
  focus,
  onSelect,
  onFocus,
}: {
  node: GraphViewNode
  view: GraphView
  focus: string | null
  onSelect: (id: string | null) => void
  onFocus: (id: string | null) => void
}) {
  const style = KIND_STYLE[node.kind]
  const byId = new Map(view.nodes.map((n) => [n.id, n]))
  const links = view.edges.flatMap((e) => {
    const other = e.source === node.id ? byId.get(e.target) : e.target === node.id ? byId.get(e.source) : undefined
    return other ? [{ type: e.type, outgoing: e.source === node.id, other }] : []
  })
  return (
    <aside
      aria-label="Selected node"
      className="border-t border-line bg-chrome px-5 py-5 lg:w-80 lg:shrink-0 lg:border-t-0 lg:border-l"
    >
      <div className="flex items-start justify-between gap-3">
        <Badge tone={style.tone}>{style.label}</Badge>
        <button
          type="button"
          aria-label="Close"
          onClick={() => onSelect(null)}
          className="-mt-1 rounded-md px-2 text-lg leading-none text-muted hover:text-ink"
        >
          ×
        </button>
      </div>
      <h2 className="mt-3 font-mono text-sm font-semibold break-words">{node.label}</h2>
      {node.detail && <p className="mt-1 text-xs break-words text-muted">{node.detail}</p>}
      <p className="mt-2 font-mono text-[11px] break-all text-faint">{node.id}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {isCodeKind(node.kind) && (
          <>
            <LinkButton variant="primary" to={whyPath(node.id, questionAbout(node.label))} className="px-3 py-1.5 text-xs">
              Ask why
            </LinkButton>
            <LinkButton to={lineagePath(node.id)} className="px-3 py-1.5 text-xs">
              Decision history
            </LinkButton>
          </>
        )}
        {focus !== node.id && (
          <Button variant="ghost" onClick={() => onFocus(node.id)} className="px-3 py-1.5 text-xs">
            Focus here
          </Button>
        )}
      </div>
      {links.length > 0 && (
        <>
          <SectionLabel className="mt-6">{plural(links.length, 'link')}</SectionLabel>
          <ul className="mt-2 space-y-0.5">
            {links.slice(0, LINKS_SHOWN).map(({ type, outgoing, other }) => (
              <li key={`${type}|${outgoing}|${other.id}`}>
                <button
                  type="button"
                  onClick={() => onSelect(other.id)}
                  className="flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-raised"
                >
                  <span className="shrink-0 font-mono text-[10px] text-faint">
                    {outgoing ? `${type} →` : `← ${type}`}
                  </span>
                  <span className="min-w-0 truncate">{other.label}</span>
                </button>
              </li>
            ))}
          </ul>
          {links.length > LINKS_SHOWN && (
            <p className="mt-1 px-2 text-xs text-faint">and {formatNumber(links.length - LINKS_SHOWN)} more</p>
          )}
        </>
      )}
    </aside>
  )
}

/** The whole graph of a small repo, the decision graph of a big one, or two hops around a node. */
export function GraphPage() {
  const [params, setParams] = useSearchParams()
  const focus = params.get('focus')
  const repoId = useRepoId()
  const [live, setLive] = useState(false)
  useTitle('Graph')
  // Keyed: a new repo or focus starts with that node selected and nothing marked as new.
  return (
    <GraphScreen
      key={`${repoId}|${focus}`}
      repoId={repoId}
      focus={focus}
      live={live}
      onLive={setLive}
      setFocus={(id) => setParams(id ? { focus: id } : {})}
    />
  )
}

function GraphScreen({
  repoId,
  focus,
  live,
  onLive,
  setFocus,
}: {
  repoId: string | null
  focus: string | null
  live: boolean
  onLive: (live: boolean) => void
  setFocus: (id: string | null) => void
}) {
  const graph = useGraphView(repoId, focus, live)
  const [selectedId, setSelectedId] = useState<string | null>(focus)
  const view = graph.data
  // A placeholder is the previous view, shown while this one loads: nothing in it is new.
  const fresh = useFreshIds(graph.isPlaceholderData ? undefined : view)
  const selected = view?.nodes.find((n) => n.id === selectedId)
  const focusNode = view?.nodes.find((n) => n.id === focus)

  return (
    <div className="flex flex-1 flex-col lg:flex-row">
      <section aria-labelledby="graph-heading" className="flex min-w-0 flex-1 flex-col px-4 py-5 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 id="graph-heading" className="text-2xl font-semibold">
            Graph
          </h1>
          {view && (
            <p className="text-sm text-muted">
              {formatNumber(view.nodes.length)} nodes, {formatNumber(view.edges.length)} links
            </p>
          )}
          <div className="ml-auto flex items-center gap-3">
            <p aria-live="polite" className="text-xs text-amber">
              {fresh.size > 0 ? `${plural(fresh.size, 'new node')}` : ''}
            </p>
            <LiveToggle live={live} onChange={onLive} />
          </div>
        </div>
        <GraphSearch repoId={repoId} nodes={view?.nodes ?? []} onPick={setFocus} />
        {focus && (
          <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted">
            Two links around <span className="font-mono text-ink">{focusNode?.label ?? focus}</span>
            <Button variant="ghost" onClick={() => setFocus(null)} className="px-2 py-1 text-xs">
              Show the whole graph
            </Button>
          </p>
        )}
        {view && <Note view={view} focusNode={focusNode} />}

        {graph.error ? (
          <ErrorNotice error={graph.error} onRetry={() => graph.refetch()} />
        ) : !view ? (
          <Loading label="Loading the graph" />
        ) : view.nodes.length === 0 ? (
          <p className="mt-6 text-sm text-faint">Nothing is in the graph for {repoId} yet.</p>
        ) : (
          <>
            <div className="relative mt-3 h-[min(70vh,720px)] min-h-[360px] overflow-hidden rounded-xl border border-line bg-sunken">
              <ForceGraph
                nodes={view.nodes}
                edges={view.edges}
                layoutKey={`${repoId}|${focus}|${view.scope}`}
                selectedId={selectedId}
                fresh={fresh}
                onSelect={setSelectedId}
                label={`Graph of ${repoId}: ${view.nodes.length} nodes`}
              />
            </div>
            <Legend nodes={view.nodes} />
          </>
        )}
      </section>
      {view && selected && (
        <NodePanel node={selected} view={view} focus={focus} onSelect={setSelectedId} onFocus={setFocus} />
      )}
    </div>
  )
}
