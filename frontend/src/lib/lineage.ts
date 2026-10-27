import type { LineageDecision, SupersedeKind } from '../api/types'

export type ViewStatus = 'active' | 'partial' | 'superseded'

export interface LineageCard {
  decision: LineageDecision
  number: number // 1-based, as in "DECISION 2"
  status: ViewStatus
  /** How this card follows the one before it; null when it does not supersede it. */
  link: { kind: SupersedeKind; date: string } | null
}

const RETIRES: SupersedeKind[] = ['reverses', 'replaces']

/**
 * Work out each decision's status from the decisions given (oldest first), not from today's
 * stored status, so "View as of 2016" shows what was true in 2016. Rules from the graph schema:
 * 'reverses' and 'replaces' retire the older decision; 'refines' keeps it partly in force,
 * unless every decision that refined it was itself retired later.
 */
export function buildLineageView(decisions: LineageDecision[]): LineageCard[] {
  const status = new Map<string, ViewStatus>()

  // Newest first: a decision's status depends only on the ones after it.
  for (let i = decisions.length - 1; i >= 0; i--) {
    const d = decisions[i]
    const incoming = decisions
      .slice(i + 1)
      .flatMap((later) =>
        later.supersedes
          .filter((edge) => edge.decision_id === d.id)
          .map((edge) => ({ kind: edge.kind, by: later.id })),
      )
    let s: ViewStatus = 'active'
    if (incoming.some((e) => RETIRES.includes(e.kind))) {
      s = 'superseded'
    } else if (incoming.length > 0) {
      s = incoming.every((e) => status.get(e.by) === 'superseded') ? 'superseded' : 'partial'
    }
    status.set(d.id, s)
  }

  return decisions.map((decision, i) => {
    const previous = decisions[i - 1]
    const edge = previous && decision.supersedes.find((e) => e.decision_id === previous.id)
    return {
      decision,
      number: i + 1,
      status: status.get(decision.id) ?? 'active',
      link: edge ? { kind: edge.kind, date: decision.decided_at } : null,
    }
  })
}

/** The "View as of" year becomes an inclusive end date for the API. */
export function asOfDate(year: number | null): string | null {
  return year === null ? null : `${year}-12-31`
}
