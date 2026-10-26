import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Entity } from '../api/types'
import { defaultQuestion } from '../lib/entity'
import { whyPath } from '../lib/routes'
import { cx } from '../lib/tones'
import { EntityPicker } from './EntityPicker'
import { Badge, Button } from './ui'

/** Pick a code item first, then ask why. The hero version sits on Home, the compact one in the top bar. */
export function AskBar({
  variant,
  initialEntity = null,
  initialText = '',
}: {
  variant: 'hero' | 'compact'
  initialEntity?: Entity | null
  initialText?: string
}) {
  const navigate = useNavigate()
  const [entity, setEntity] = useState<Entity | null>(initialEntity)
  const [text, setText] = useState(initialText)
  const inputRef = useRef<HTMLInputElement>(null)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!entity) return
    navigate(whyPath(entity.id, text.trim() || defaultQuestion(entity)))
  }

  return (
    <form
      role="search"
      aria-label="Ask why"
      onSubmit={submit}
      className={cx(
        'flex min-w-0 items-center gap-2 rounded-xl border bg-sunken focus-within:border-teal/70',
        variant === 'hero' ? 'border-teal/40 p-2.5 pl-3.5' : 'flex-1 border-line p-1.5 pl-2.5',
      )}
    >
      <Badge tone="teal">Why</Badge>
      <EntityPicker
        value={entity}
        onChange={(picked) => {
          setEntity(picked)
          inputRef.current?.focus()
        }}
      />
      <input
        ref={inputRef}
        aria-label="Your question"
        placeholder="then ask why it is this way..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
      />
      <Button
        type="submit"
        variant="primary"
        disabled={!entity}
        title={entity ? undefined : 'Pick an entity first'}
        className={variant === 'compact' ? 'px-3 py-1.5' : undefined}
      >
        Trace
      </Button>
    </form>
  )
}
