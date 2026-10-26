import { describe, expect, it } from 'vitest'
import {
  formatCompact,
  formatCount,
  formatDateTime,
  formatMonth,
  formatMonthYear,
  formatPct,
  formatRelative,
  plural,
} from './format'

describe('numbers', () => {
  it('groups small counts and shortens big ones, as on the Home cards', () => {
    expect(formatCount(2140)).toBe('2,140')
    expect(formatCount(9860)).toBe('9,860')
    expect(formatCount(14200)).toBe('14.2k')
  })

  it('shortens counts for the repo switcher', () => {
    expect(formatCompact(6495)).toBe('6.5k')
    expect(formatCompact(2000)).toBe('2k')
    expect(formatCompact(950)).toBe('950')
    expect(formatCompact(1_250_000)).toBe('1.3M')
  })

  it('formats fractions as whole percents', () => {
    expect(formatPct(0.87)).toBe('87%')
    expect(formatPct(1)).toBe('100%')
  })

  it('pluralises', () => {
    expect(plural(1, 'flag')).toBe('1 flag')
    expect(plural(4, 'reversal')).toBe('4 reversals')
  })
})

describe('dates', () => {
  it('reads bare dates as calendar days', () => {
    expect(formatMonth('2013-03-14')).toBe('2013-03')
    expect(formatMonthYear('2012-11-02')).toBe('Nov 2012')
    expect(formatMonthYear('2012-01-01')).toBe('Jan 2012')
  })

  it('formats a timestamp without seconds', () => {
    expect(formatDateTime('2026-10-24T14:10:00')).toBe('2026-10-24 14:10')
  })

  it('describes how long ago', () => {
    const now = new Date('2026-10-26T12:00:00').getTime()
    expect(formatRelative('2026-10-26T11:59:40', now)).toBe('just now')
    expect(formatRelative('2026-10-26T11:50:00', now)).toBe('10 min ago')
    expect(formatRelative('2026-10-26T11:00:00', now)).toBe('1 hour ago')
    expect(formatRelative('2026-10-26T10:00:00', now)).toBe('2 hours ago')
    expect(formatRelative('2026-10-23T12:00:00', now)).toBe('3 days ago')
  })
})
