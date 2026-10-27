const grouped = new Intl.NumberFormat('en-US')

/** 2140 -> "2,140"; 14200 -> "14.2k" (big numbers are shortened, as on the Home cards). */
export function formatCount(n: number): string {
  return n >= 10_000 ? formatCompact(n) : grouped.format(n)
}

/** 6495 -> "6.5k"; 950 -> "950". */
export function formatCompact(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${trimZero((n / 1000).toFixed(1))}k`
  return `${trimZero((n / 1_000_000).toFixed(1))}M`
}

const trimZero = (s: string) => s.replace(/\.0$/, '')

/** 0.87 -> "87%". */
export function formatPct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

function parse(iso: string): Date {
  // A bare date ("2013-03-14") is a calendar day, not UTC midnight.
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso)
}

const pad = (n: number) => String(n).padStart(2, '0')

/** "2013-03-14T..." -> "2013-03". */
export function formatMonth(iso: string): string {
  const d = parse(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2012-11-02" -> "Nov 2012". */
export function formatMonthYear(iso: string): string {
  const d = parse(iso)
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

/** "2026-10-24T14:10:00" -> "2026-10-24 14:10", in local time. */
export function formatDateTime(iso: string): string {
  const d = parse(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatYear(iso: string): string {
  return String(parse(iso).getFullYear())
}

/** "10 min ago", "2 hours ago", "3 days ago". */
export function formatRelative(iso: string, now: number): string {
  const minutes = Math.floor((now - parse(iso).getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`
  const days = Math.floor(hours / 24)
  return `${days} ${days === 1 ? 'day' : 'days'} ago`
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${grouped.format(n)} ${n === 1 ? one : many}`
}
