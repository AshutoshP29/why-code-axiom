import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Entity } from '../api/types'
import { defaultQuestion } from '../lib/entity'
import { whyPath } from '../lib/routes'
import { cx } from '../lib/tones'
import { EntityPicker } from './EntityPicker'
import { Badge, Button } from './ui'

/**
 * Ask why about a picked code item, or type a plain question and let the API find the item.
 * The hero version sits on Home, the compact one in the top bar.
 */
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
  const question = text.trim()
  const canAsk = entity !== null || question !== ''

  function submit(e: FormEvent) {
    e.preventDefault()
    if (entity) navigate(whyPath(entity.id, question || defaultQuestion(entity)))
    else if (question) navigate(whyPath(null, question))
  }

  function pick(picked: Entity | null) {
    setEntity(picked)
    inputRef.current?.focus()
  }

  return (
    <form
      role="search"
      aria-label="Ask why"
      onSubmit={submit}
      className={cx(
        // Wraps on a narrow screen, so a long picked name cannot squeeze the question box to nothing.
        'flex min-w-0 flex-wrap items-center gap-2 rounded-xl border bg-sunken focus-within:border-teal/70',
        variant === 'hero' ? 'border-teal/40 p-2.5 pl-3.5' : 'flex-1 border-line p-1.5 pl-2.5',
      )}
    >
      <Badge tone="teal">Why</Badge>
      <EntityPicker value={entity} onChange={pick} />
      {entity && (
        <button
          type="button"
          onClick={() => pick(null)}
          className="-ml-1 grid size-6 shrink-0 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink"
        >
          <span aria-hidden>×</span>
          <span className="sr-only">Clear entity</span>
        </button>
      )}
      <input
        ref={inputRef}
        aria-label="Your question"
        placeholder={entity ? 'then ask why it is this way...' : 'or type a question...'}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="min-w-32 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
      />
      <Button
        type="submit"
        variant="primary"
        disabled={!canAsk}
        title={canAsk ? undefined : 'Pick an entity or type a question'}
        className={variant === 'compact' ? 'px-3 py-1.5' : undefined}
      >
        Trace
      </Button>
    </form>
  )
}
