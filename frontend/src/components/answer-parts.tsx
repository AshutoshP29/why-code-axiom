import { Link, useNavigate } from 'react-router'
import type { Answer, AnswerThresholds, SupersededNote } from '../api/types'
import { entityLabel } from '../lib/entity'
import { formatMonthYear, formatPct } from '../lib/format'
import { lineagePath, whyPath } from '../lib/routes'
import { TEXT_TONE, type Tone } from '../lib/tones'
import { EntityPicker } from './EntityPicker'
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

/** The score, with both cut-offs from the response marked on the bar and spelled out below it. */
export function ConfidenceMeter({
  value,
  tone,
  thresholds,
}: {
  value: number
  tone: Tone
  thresholds: AnswerThresholds
}) {
  return (
    <div className="text-xs">
      <div className="flex items-center gap-2">
        <span className="text-faint">Confidence</span>
        <div className="relative w-28">
          <ProgressBar value={value} tone={tone} label="Confidence" />
          {[thresholds.refuse, thresholds.answer].map((t, i) => (
            <span
              key={i}
              aria-hidden
              className="absolute -top-0.5 h-2.5 w-0.5 -translate-x-1/2 rounded-full bg-ink/80"
              style={{ left: `${t * 100}%` }}
            />
          ))}
        </div>
        <span className={`font-semibold ${TEXT_TONE[tone]}`}>{formatPct(value)}</span>
      </div>
      <p className="mt-1 text-faint">
        Refuses below {formatPct(thresholds.refuse)} · warns below {formatPct(thresholds.answer)}
      </p>
    </div>
  )
}

/**
 * For a question asked without an entity: which item the API matched it to, and a way to ask about
 * another one instead. `asked` is the question as typed, reused for the new item.
 */
export function MatchNote({ answer, asked }: { answer: Answer; asked: string }) {
  const navigate = useNavigate()
  if (answer.matched_by !== 'search' || !answer.entity) return null
  return (
    <div className="mt-4 rounded-lg border border-line bg-surface px-3 py-2.5 text-sm">
      <p className="text-muted">
        Matched to <span className="font-mono text-ink">{entityLabel(answer.entity)}</span>
        {answer.match_score !== null && ` (score ${answer.match_score.toFixed(2)})`} from your question.
      </p>
      {/* The picker starts the row so its list opens inside the column, phones included. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
        <EntityPicker
          value={null}
          emptyLabel="pick a different entity"
          onChange={(picked) => navigate(whyPath(picked.id, asked || answer.question))}
        />
        <span className="text-xs text-faint">if this is not the item you meant</span>
      </div>
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
