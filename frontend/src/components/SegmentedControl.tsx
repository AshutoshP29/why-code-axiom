import { useRef, type KeyboardEvent } from 'react'
import { cx } from '../lib/tones'

/** A row of choices that behaves as a radio group: one Tab stop, arrow keys move and select. */
export function SegmentedControl<T extends string | number | null>({
  label,
  labelledBy,
  options,
  value,
  onChange,
}: {
  label?: string
  labelledBy?: string
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([])
  const current = Math.max(0, options.findIndex((o) => o.value === value))

  function onKeyDown(e: KeyboardEvent) {
    const last = options.length - 1
    const next: Record<string, number> = {
      ArrowRight: current === last ? 0 : current + 1,
      ArrowDown: current === last ? 0 : current + 1,
      ArrowLeft: current === 0 ? last : current - 1,
      ArrowUp: current === 0 ? last : current - 1,
      Home: 0,
      End: last,
    }
    const to = next[e.key]
    if (to === undefined) return
    e.preventDefault()
    onChange(options[to].value)
    buttons.current[to]?.focus()
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-labelledby={labelledBy}
      onKeyDown={onKeyDown}
      className="flex flex-wrap rounded-lg border border-line bg-surface p-1"
    >
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          ref={(el) => {
            buttons.current[i] = el
          }}
          type="button"
          role="radio"
          aria-checked={i === current}
          tabIndex={i === current ? 0 : -1}
          onClick={() => onChange(o.value)}
          className={cx(
            'rounded-md border px-3 py-1 text-sm',
            i === current ? 'border-teal/40 bg-teal/10 font-semibold text-teal' : 'border-transparent text-muted hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
