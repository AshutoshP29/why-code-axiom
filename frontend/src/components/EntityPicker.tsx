import { useId, useRef, useState, type KeyboardEvent } from 'react'
import { useEntitySearch } from '../api/queries'
import type { Entity } from '../api/types'
import { entityLabel, kindLabel } from '../lib/entity'
import { useDismiss } from '../lib/hooks'
import { cx } from '../lib/tones'
import { useRepoId } from '../state/repo-context'

/** "pick an entity" chip that opens a searchable list of files, functions and config keys. */
export function EntityPicker({
  value,
  onChange,
}: {
  value: Entity | null
  onChange: (entity: Entity) => void
}) {
  const repoId = useRepoId()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const listId = useId()
  useDismiss(rootRef, open, () => setOpen(false))

  const search = useEntitySearch(repoId, open ? text : '')
  const matches = text.trim() ? (search.data ?? []) : []
  const current = Math.min(active, matches.length - 1)

  function choose(entity: Entity) {
    onChange(entity)
    setOpen(false)
    setText('')
    setActive(0)
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, matches.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault() // never submit the ask form from inside the picker
      if (matches[current]) choose(matches[current])
    } else if (e.key === 'Escape') {
      setOpen(false)
      buttonRef.current?.focus()
    }
  }

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={value ? `Entity: ${entityLabel(value)}. Change entity` : 'Pick an entity'}
        onClick={() => setOpen((o) => !o)}
        className={cx(
          'max-w-56 truncate rounded-md border px-2 py-1 font-mono text-xs',
          value
            ? 'border-blue/50 bg-blue/10 text-blue hover:bg-blue/20'
            : 'border-line-strong bg-raised text-muted hover:text-ink',
        )}
      >
        {value ? entityLabel(value) : 'pick an entity'}
      </button>

      {open && (
        <div className="absolute top-full left-0 z-40 mt-2 w-[min(22rem,80vw)] rounded-xl border border-line bg-surface p-2 shadow-2xl">
          <input
            autoFocus
            role="combobox"
            aria-expanded={matches.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={matches[current] ? `${listId}-${current}` : undefined}
            aria-label="Search functions, files and config keys"
            placeholder="Search functions, files, config keys"
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
            className="w-full rounded-lg border border-line bg-sunken px-3 py-2 text-sm outline-none placeholder:text-faint focus:border-teal/60"
          />
          <ul id={listId} role="listbox" aria-label="Matching entities" className="mt-1 max-h-72 overflow-y-auto">
            {matches.map((entity, i) => (
              <li
                key={entity.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === current}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(entity)}
                className={cx(
                  'cursor-pointer rounded-lg px-3 py-2',
                  i === current ? 'bg-teal/10' : 'hover:bg-raised',
                )}
              >
                <span className="block font-mono text-sm text-ink">{entityLabel(entity)}</span>
                <span className="block truncate text-xs text-faint">
                  {kindLabel(entity.kind)}
                  {entity.path ? ` · ${entity.path}` : ''}
                </span>
              </li>
            ))}
          </ul>
          <p className="px-3 py-2 text-xs text-faint" aria-live="polite">
            {!text.trim()
              ? 'Type part of a name, for example max_retries'
              : search.isFetching && matches.length === 0
                ? 'Searching…'
                : matches.length === 0
                  ? `Nothing called “${text.trim()}” in ${repoId}`
                  : ''}
          </p>
        </div>
      )}
    </div>
  )
}
