import { describe, expect, it } from 'vitest'
import type { LineageDecision, SupersedeKind } from '../api/types'
import { asOfDate, buildLineageView } from './lineage'

function dec(id: string, date: string, supersedes: [string, SupersedeKind][] = []): LineageDecision {
  return {
    id,
    summary: id,
    rationale: '',
    alternatives: [],
    decided_at: date,
    status: 'ACTIVE', // stored status is ignored; the view derives its own
    evidence_kind: 'EXPLICIT',
    proposed_by: null,
    approved_by: [],
    reviewed_by: null,
    source: { id: `src-${id}`, label: id, url: 'https://example.invalid' },
    supersedes: supersedes.map(([decision_id, kind]) => ({ decision_id, kind })),
  }
}

const statuses = (decisions: LineageDecision[]) => buildLineageView(decisions).map((c) => c.status)

describe('buildLineageView', () => {
  it('returns nothing for no decisions', () => {
    expect(buildLineageView([])).toEqual([])
  })

  it('retires a replaced decision and links the cards', () => {
    const view = buildLineageView([dec('a', '2012-01-01'), dec('b', '2014-01-01', [['a', 'replaces']])])
    expect(view.map((c) => c.status)).toEqual(['superseded', 'active'])
    expect(view[0].link).toBeNull()
    expect(view[1].link).toEqual({ kind: 'replaces', date: '2014-01-01' })
    expect(view.map((c) => c.number)).toEqual([1, 2])
  })

  it('retires a reversed decision', () => {
    expect(statuses([dec('a', '2012-01-01'), dec('b', '2013-01-01', [['a', 'reverses']])])).toEqual([
      'superseded',
      'active',
    ])
  })

  it('keeps a refined decision partly in force', () => {
    expect(statuses([dec('a', '2012-01-01'), dec('b', '2013-01-01', [['a', 'refines']])])).toEqual([
      'partial',
      'active',
    ])
  })

  it('retires a refined decision once its refinement is itself replaced', () => {
    expect(
      statuses([
        dec('a', '2012-01-01'),
        dec('b', '2014-01-01', [['a', 'refines']]),
        dec('c', '2019-01-01', [['b', 'replaces']]),
      ]),
    ).toEqual(['superseded', 'superseded', 'active'])
  })

  it('shows the time-travel view from only the decisions given', () => {
    // As of 2016 the 2019 replacement does not exist yet, so b is still the rule.
    expect(statuses([dec('a', '2012-01-01'), dec('b', '2014-01-01', [['a', 'replaces']])])).toEqual([
      'superseded',
      'active',
    ])
    expect(statuses([dec('a', '2012-01-01')])).toEqual(['active'])
  })

  it('leaves unrelated decisions active with no link', () => {
    const view = buildLineageView([dec('a', '2012-01-01'), dec('b', '2013-01-01')])
    expect(view.map((c) => c.status)).toEqual(['active', 'active'])
    expect(view[1].link).toBeNull()
  })
})

describe('asOfDate', () => {
  it('turns a year into the last day of that year', () => {
    expect(asOfDate(2016)).toBe('2016-12-31')
    expect(asOfDate(null)).toBeNull()
  })
})
