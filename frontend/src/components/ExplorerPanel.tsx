import { Link } from 'react-router'
import { useExplorer } from '../api/queries'
import type { Entity, ExplorerItem } from '../api/types'
import { defaultQuestion, entityLabel } from '../lib/entity'
import { explorePath, whyPath } from '../lib/routes'
import { cx } from '../lib/tones'
import { useRepoId } from '../state/repo-context'
import { Dot, SectionLabel } from './ui'

function Row({ item, to, active }: { item: ExplorerItem; to: string; active: boolean }) {
  return (
    <li>
      <Link
        to={to}
        aria-current={active ? 'page' : undefined}
        className={cx(
          'flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm',
          active ? 'border-teal/40 bg-teal/10 font-semibold text-ink' : 'border-transparent text-muted hover:bg-raised hover:text-ink',
        )}
      >
        <Dot tone={item.has_superseded ? 'amber' : 'teal'} />
        <span className="truncate">{item.entity.kind === 'file' ? item.entity.name : entityLabel(item.entity)}</span>
        <span className="ml-auto text-xs text-faint" aria-hidden>
          {item.decision_count}
        </span>
        <span className="sr-only">
          , {item.decision_count} decisions{item.has_superseded ? ', some superseded' : ''}
        </span>
      </Link>
    </li>
  )
}

/** Left sidebar: files and config keys, coloured by whether any of their rules were replaced. */
export function ExplorerPanel({
  activeEntity = null,
  activeFileId = null,
}: {
  activeEntity?: Entity | null
  activeFileId?: string | null
}) {
  const repoId = useRepoId()
  const { data } = useExplorer(repoId)

  return (
    <nav aria-label="Explorer" className="space-y-6 p-4">
      <div>
        <SectionLabel>Explorer</SectionLabel>
        {data && (
          <>
            <p className="mt-2 px-1 text-sm text-muted">{data.root}</p>
            <ul className="mt-1 space-y-0.5 pl-2">
              {data.files.map((item) => (
                <Row
                  key={item.entity.id}
                  item={item}
                  to={explorePath(item.entity.id)}
                  active={item.entity.id === activeFileId || (!!activeEntity?.path && item.entity.path === activeEntity.path)}
                />
              ))}
            </ul>
            {data.files.length === 0 && <p className="mt-2 px-1 text-xs text-faint">No files mapped yet.</p>}
          </>
        )}
      </div>

      {data && data.config_keys.length > 0 && (
        <div>
          <SectionLabel>Config keys</SectionLabel>
          <ul className="mt-2 space-y-0.5">
            {data.config_keys.map((item) => (
              <Row
                key={item.entity.id}
                item={item}
                to={whyPath(item.entity.id, defaultQuestion(item.entity))}
                active={item.entity.id === activeEntity?.id}
              />
            ))}
          </ul>
        </div>
      )}

      <div>
        <SectionLabel>Legend</SectionLabel>
        <ul className="mt-2 space-y-1 text-xs text-faint">
          <li className="flex items-center gap-2">
            <Dot tone="teal" /> Only active decisions
          </li>
          <li className="flex items-center gap-2">
            <Dot tone="amber" /> Has superseded decisions
          </li>
        </ul>
      </div>
    </nav>
  )
}
