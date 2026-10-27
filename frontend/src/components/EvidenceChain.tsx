import type { EvidenceKind, EvidenceStep } from '../api/types'
import { BADGE_TONE, cx, type Tone } from '../lib/tones'
import { Badge, Meta, SourceLink } from './ui'

const KIND: Record<EvidenceKind, { label: string; tone: Tone }> = {
  incident: { label: 'Incident', tone: 'red' },
  issue: { label: 'Issue', tone: 'red' },
  discussion: { label: 'PR discussion', tone: 'blue' },
  commit: { label: 'Commit', tone: 'violet' },
  code: { label: 'Code', tone: 'green' },
}

/** Bug report → discussion → code change → the code itself, each step linked to its source. */
export function EvidenceChain({ steps }: { steps: EvidenceStep[] }) {
  return (
    <ol aria-label="Evidence, from the report to the code" className="space-y-3">
      {steps.map((step, i) => {
        const kind = KIND[step.kind]
        return (
          <li key={`${step.kind}-${i}`} className="flex gap-3 rounded-xl border border-line bg-surface p-4">
            <span
              aria-hidden
              className={cx('grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold', BADGE_TONE[kind.tone])}
            >
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={kind.tone}>{kind.label}</Badge>
                <a
                  href={step.source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-semibold hover:underline"
                >
                  {step.title}
                </a>
              </div>
              <p className="mt-1.5 text-sm text-muted">{step.excerpt}</p>
              <Meta className="mt-2">
                {[...step.meta.map((m) => <span key={m}>{m}</span>), <SourceLink key="src" href={step.source.url} />]}
              </Meta>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
