import { Link } from 'react-router'
import { useRisk } from '../api/queries'
import type { KnowledgeRisk, OrphanedCode, Person, UnexplainedCode } from '../api/types'
import { Badge, Card, ErrorNotice, Loading } from '../components/ui'
import { entityLabel } from '../lib/entity'
import { formatCount, formatDateTime, plural } from '../lib/format'
import { useTitle } from '../lib/hooks'
import { lineagePath, whyPath } from '../lib/routes'
import { useRepo } from '../state/repo-context'

const HEADLINE: { key: keyof KnowledgeRisk['counts']; label: string; detail: string }[] = [
  { key: 'code_with_decisions', label: 'Explained', detail: 'functions, classes and settings with a recorded decision' },
  { key: 'orphaned', label: 'At risk', detail: 'explained, but everyone who decided it has gone' },
  { key: 'changed_without_reason', label: 'Unexplained', detail: 'commits change it and no decision says why' },
]

function Links({ entityId, question }: { entityId: string; question: string }) {
  return (
    <div className="flex gap-3 whitespace-nowrap">
      <Link to={whyPath(entityId, question)} className="text-xs font-semibold text-teal hover:underline">
        Ask why
      </Link>
      <Link to={lineagePath(entityId)} className="text-xs text-blue hover:underline">
        Decision history
      </Link>
    </div>
  )
}

function ItemCell({ entity }: { entity: OrphanedCode['entity'] }) {
  return (
    <div className="min-w-0">
      <p className="truncate font-mono text-xs text-blue">{entityLabel(entity)}</p>
      {entity.path && <p className="truncate text-xs text-faint">{entity.path}</p>}
    </div>
  )
}

/** Everyone is inactive here, so the badge says so once per person rather than per row. */
function People({ people }: { people: Person[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {people.map((p) => (
        <li key={p.login}>
          <Badge tone="red">
            {p.login}
            <span className="ml-1 font-normal">inactive</span>
          </Badge>
        </li>
      ))}
    </ul>
  )
}

function Empty({ children }: { children: string }) {
  return <p className="mt-3 text-sm text-faint">{children}</p>
}

function OrphanedTable({ rows }: { rows: OrphanedCode[] }) {
  if (rows.length === 0) {
    return <Empty>Every decision still in force has someone active who made it.</Empty>
  }
  return (
    <table className="mt-3 w-full text-left text-sm">
      <thead className="text-xs text-muted">
        <tr>
          <th scope="col" className="py-2 font-medium">Item</th>
          <th scope="col" className="py-2 font-medium">Decisions</th>
          <th scope="col" className="py-2 font-medium">Who decided it</th>
          <th scope="col" className="py-2 font-medium">Last decided</th>
          <th scope="col" className="py-2" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.entity.id} className="border-t border-line align-top">
            <td className="max-w-xs py-3 pr-3">
              <ItemCell entity={row.entity} />
            </td>
            <td className="py-3 pr-3 text-xs whitespace-nowrap">{plural(row.decisions, 'decision')}</td>
            <td className="py-3 pr-3">
              <People people={row.people} />
            </td>
            <td className="py-3 pr-3 text-xs whitespace-nowrap text-muted">{formatDateTime(row.last_decided_at)}</td>
            <td className="py-3">
              <Links entityId={row.entity.id} question={`Why is ${row.entity.name} like this?`} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function UnexplainedTable({ rows }: { rows: UnexplainedCode[] }) {
  if (rows.length === 0) {
    return <Empty>Every item commits have changed has a decision that explains it.</Empty>
  }
  return (
    <table className="mt-3 w-full text-left text-sm">
      <thead className="text-xs text-muted">
        <tr>
          <th scope="col" className="py-2 font-medium">Item</th>
          <th scope="col" className="py-2 font-medium">Commits</th>
          <th scope="col" className="py-2 font-medium">Authors</th>
          <th scope="col" className="py-2 font-medium">Last changed</th>
          <th scope="col" className="py-2" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.entity.id} className="border-t border-line align-top">
            <td className="max-w-xs py-3 pr-3">
              <ItemCell entity={row.entity} />
            </td>
            <td className="py-3 pr-3 text-xs whitespace-nowrap">{formatCount(row.commits)}</td>
            <td className="py-3 pr-3 text-xs whitespace-nowrap">{formatCount(row.authors)}</td>
            <td className="py-3 pr-3 text-xs whitespace-nowrap text-muted">
              {row.last_changed_at ? formatDateTime(row.last_changed_at) : 'not recorded'}
            </td>
            <td className="py-3">
              <Links entityId={row.entity.id} question={`Why is ${row.entity.name} like this?`} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** For engineering leads: where the "why" has left with people, or was never written down. */
export function RiskPage() {
  const { repo } = useRepo()
  const { data, error, refetch } = useRisk(repo?.id ?? null)
  useTitle('Knowledge risk')

  if (!repo) return null
  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!data) return <Loading label="Loading knowledge risk" />

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
      <h1 className="text-2xl font-semibold">Knowledge risk</h1>
      <p className="mt-1 text-xs text-faint">
        {repo.id} | from the graph only: who decided what, and what nobody decided
      </p>

      <dl className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {HEADLINE.map((c) => (
          <Card key={c.key} className="p-4">
            <dt className="text-sm font-semibold">{c.label}</dt>
            <dd className="mt-1 text-2xl font-semibold">{formatCount(data.counts[c.key])}</dd>
            <dd className="mt-1 text-xs text-faint">{c.detail}</dd>
          </Card>
        ))}
      </dl>

      <Card className="mt-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">Nobody left to ask</h2>
          {data.orphaned.length > 0 && <Badge tone="red">{data.orphaned.length} shown</Badge>}
        </div>
        <p className="mt-2 text-xs text-faint">
          The decision is recorded and still in force, but everyone who proposed or approved it has
          gone quiet in this repository. Read the decision before changing the code.
        </p>
        <div className="mt-1 overflow-x-auto">
          <OrphanedTable rows={data.orphaned} />
        </div>
      </Card>

      <Card className="mt-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">Changed often, never explained</h2>
          {data.unexplained.length > 0 && <Badge tone="amber">{data.unexplained.length} shown</Badge>}
        </div>
        <p className="mt-2 text-xs text-faint">
          Commits keep changing these and no decision says why. WhyCode refuses to invent a reason;
          ask the authors and record what they say.
        </p>
        <div className="mt-1 overflow-x-auto">
          <UnexplainedTable rows={data.unexplained} />
        </div>
      </Card>
    </div>
  )
}
