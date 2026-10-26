import type { ConfidenceFactor } from '../api/types'
import { formatPct } from '../lib/format'
import { TEXT_TONE, type Tone } from '../lib/tones'
import { ProgressBar, SectionLabel } from './ui'

const TONE: Record<ConfidenceFactor['tone'], Tone> = { good: 'teal', bad: 'red', neutral: 'gray' }

/** "WHY 87%?" — what the confidence score is made of. */
export function ConfidenceFactors({
  confidence,
  factors,
  refused,
}: {
  confidence: number
  factors: ConfidenceFactor[]
  refused: boolean
}) {
  return (
    <section>
      <SectionLabel>
        {refused ? 'Why only' : 'Why'} {formatPct(confidence)}?
      </SectionLabel>
      <ul className="mt-3 space-y-3">
        {factors.map((f) => (
          <li key={f.label}>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-muted">{f.label}</span>
              <span className={`font-semibold ${TEXT_TONE[TONE[f.tone]]}`}>{f.display}</span>
            </div>
            <ProgressBar value={f.value} tone={TONE[f.tone]} className="mt-1.5" />
          </li>
        ))}
      </ul>
    </section>
  )
}
