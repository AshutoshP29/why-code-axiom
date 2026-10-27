import { Link } from 'react-router'
import type { SupersededNote } from '../api/types'
import { formatMonthYear, formatPct } from '../lib/format'
import { lineagePath } from '../lib/routes'
import { TEXT_TONE, type Tone } from '../lib/tones'
import { ProgressBar } from './ui'

export function Breadcrumb({ parts }: { parts: string[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1.5 font-mono text-xs text-faint">
        {parts.map((part, i) => (
          <li key={`${i}-${part}`} className="flex items-center gap-1.5">
            {i > 0 && <span aria-hidden>›</span>}
            {part}
          </li>
        ))}
      </ol>
    </nav>
  )
}

export function ConfidenceMeter({ value, tone, note }: { value: number; tone: Tone; note?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-faint">Confidence</span>
      <ProgressBar value={value} tone={tone} label="Confidence" className="w-28" />
      <span className={`font-semibold ${TEXT_TONE[tone]}`}>{formatPct(value)}</span>
      {note && <span className="text-faint">{note}</span>}
    </div>
  )
}

export function PartialHistoryNote() {
  return (
    <p className="mt-4 rounded-lg border border-amber/30 bg-amber/10 px-3 py-2 text-sm text-muted">
      Partial history: this repository is still being read, so older decisions may be missing and confidence is
      lower.
    </p>
  )
}

const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

/** The amber warning: an older rule exists but must not be trusted as current guidance. */
export function SupersededBanner({ note, entityId }: { note: SupersededNote; entityId: string }) {
  const old = note.decision
  return (
    <div role="note" className="mt-4 flex gap-3 rounded-xl border border-amber/40 bg-amber/10 p-4">
      <span aria-hidden className="grid size-5 shrink-0 place-items-center rounded-full bg-amber text-xs font-bold text-canvas">
        !
      </span>
      <div className="text-sm">
        <p className="font-semibold text-amber">
          An earlier decision was {note.kind === 'reverses' ? 'reversed' : 'overridden'}
        </p>
        <p className="mt-1 text-muted">
          The older rule, {lowerFirst(old.summary)} ({old.source.label}, {formatMonthYear(old.decided_at)}), is shown
          as history only and is not used as current guidance.{' '}
          <Link to={lineagePath(entityId)} className="text-blue underline underline-offset-2">
            See the full history →
          </Link>
        </p>
      </div>
    </div>
  )
}
