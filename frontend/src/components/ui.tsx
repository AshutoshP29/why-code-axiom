import type { AnchorHTMLAttributes, ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router'
import { BADGE_TONE, cx, FILL_TONE, type Tone } from '../lib/tones'

export function Badge({
  tone = 'gray',
  className,
  children,
}: {
  tone?: Tone
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] leading-4 font-semibold tracking-wider whitespace-nowrap uppercase',
        BADGE_TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

type Variant = 'primary' | 'secondary' | 'ghost'

const VARIANT: Record<Variant, string> = {
  primary: 'bg-teal text-teal-ink hover:bg-teal/85 disabled:bg-teal/40',
  secondary: 'border border-line-strong bg-raised text-ink hover:border-faint disabled:text-faint',
  ghost: 'text-muted hover:bg-raised hover:text-ink',
}

const buttonClass = (variant: Variant, className?: string) =>
  cx(
    'inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed',
    VARIANT[variant],
    className,
  )

export function Button({
  variant = 'secondary',
  className,
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />
}

export function LinkButton({ variant = 'secondary', className, ...props }: LinkProps & { variant?: Variant }) {
  return <Link className={buttonClass(variant, className)} {...props} />
}

export function ExternalButton({
  variant = 'secondary',
  className,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant }) {
  return <a target="_blank" rel="noreferrer" className={buttonClass(variant, className)} {...props} />
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx('rounded-xl border border-line bg-surface', className)} {...props} />
}

export function ProgressBar({
  value,
  tone = 'teal',
  label,
  className,
}: {
  value: number // 0..1
  tone?: Tone
  label?: string // set when the bar carries meaning a screen reader should hear
  className?: string
}) {
  const pct = Math.max(0, Math.min(100, value * 100))
  return (
    <div
      className={cx('h-1.5 overflow-hidden rounded-full bg-track', className)}
      {...(label
        ? { role: 'progressbar', 'aria-label': label, 'aria-valuenow': Math.round(pct), 'aria-valuemin': 0, 'aria-valuemax': 100 }
        : { 'aria-hidden': true })}
    >
      <div className={cx('h-full rounded-full', FILL_TONE[tone])} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h2 className={cx('text-[11px] font-semibold tracking-wider text-faint uppercase', className)}>
      {children}
    </h2>
  )
}

/** Small grey items separated by bars: "2012-11-20 | opened by @reporter_1 | View source →". */
export function Meta({ children, className }: { children: ReactNode[]; className?: string }) {
  const items = children.filter(Boolean)
  return (
    <div className={cx('flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-blue', className)}>
      {items.map((child, i) => (
        <span key={i} className="flex items-center gap-2">
          {i > 0 && (
            <span aria-hidden className="text-line-strong">
              |
            </span>
          )}
          {child}
        </span>
      ))}
    </div>
  )
}

export function SourceLink({ href, children = 'View source' }: { href: string; children?: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-blue hover:underline">
      {children} <span aria-hidden>→</span>
    </a>
  )
}

export function Dot({ tone, className }: { tone: Tone; className?: string }) {
  return <span aria-hidden className={cx('inline-block size-1.5 shrink-0 rounded-full', FILL_TONE[tone], className)} />
}

/** "maintainer_a" -> "MA". */
function initials(login: string): string {
  const parts = login.split(/[_\-.]+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : login.slice(0, 2)
  return letters.toUpperCase()
}

export function Avatar({ login, tone }: { login: string; tone: Tone }) {
  return (
    <span
      aria-hidden
      className={cx(
        'grid size-8 shrink-0 place-items-center rounded-full text-[11px] font-bold text-canvas',
        FILL_TONE[tone],
      )}
    >
      {initials(login)}
    </span>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-muted">
      <span className="size-3 animate-spin rounded-full border-2 border-teal border-t-transparent" />
      {label}…
    </div>
  )
}

export function ErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-6 rounded-xl border border-red/40 bg-red/10 p-4 text-sm">
      <p className="font-semibold text-red">Something went wrong</p>
      <p className="mt-1 text-muted">{error.message}</p>
      {onRetry && (
        <Button className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}
