import type { EvalSystem, ExpectedOutcome } from '../api/types'
import type { Tone } from './tones'

/** The three systems compared on the labelled questions, in table order. */
export const SYSTEMS: { key: EvalSystem; label: string; tone: Tone }[] = [
  { key: 'llm_only', label: 'LLM only', tone: 'gray' },
  { key: 'vector_rag', label: 'LLM + vector RAG', tone: 'blue' },
  { key: 'whycode', label: 'WhyCode', tone: 'teal' },
]

export const OUTCOME_LABEL: Record<ExpectedOutcome, { label: string; tone: Tone }> = {
  answered: { label: 'Answered', tone: 'teal' },
  superseded: { label: 'Superseded', tone: 'amber' },
  refused: { label: 'No record', tone: 'red' },
}
