import { useRef, useState } from 'react'
import type { Entity, Person } from '../api/types'
import { entityLabel } from '../lib/entity'
import { Dialog } from './Dialog'
import { Button, ExternalButton } from './ui'

/**
 * WhyCode cannot message people itself, so it writes the question for the user to send:
 * which code, what was asked, and what the graph did or did not find.
 */
export function AskMaintainerDialog({
  person,
  repo,
  entity,
  question,
  finding,
  onClose,
}: {
  person: Person
  repo: string
  entity: Entity | null // null when the question matched no item
  question: string
  finding: string // "WhyCode found: ..." or "WhyCode found no recorded decision ..."
  onClose: () => void
}) {
  const where = entity ? `${entityLabel(entity)} in ${repo}${entity.path ? ` (${entity.path})` : ''}` : repo
  const [message, setMessage] = useState(
    `Hi @${person.login}, I'm looking at ${where}.\n\n` +
      `${question}\n\n${finding}\n\n` +
      'Could you share the reasoning, or point me to where it was discussed? Thanks!',
  )
  const [copied, setCopied] = useState(false)
  const textRef = useRef<HTMLTextAreaElement>(null)

  async function copy() {
    try {
      await navigator.clipboard.writeText(message)
      setCopied(true)
    } catch {
      // No clipboard access: select the text so the user can copy it themselves.
      textRef.current?.select()
    }
  }

  return (
    <Dialog
      title={`Ask @${person.login}`}
      description={`${person.role}. ${person.active ? 'Active in this repository.' : 'No longer active here, so a reply may take time.'}`}
      onClose={onClose}
    >
      <label className="text-xs font-semibold tracking-wider text-faint uppercase" htmlFor="ask-message">
        Message
      </label>
      <textarea
        id="ask-message"
        ref={textRef}
        rows={8}
        value={message}
        onChange={(e) => {
          setMessage(e.target.value)
          setCopied(false)
        }}
        className="mt-2 w-full rounded-lg border border-line bg-sunken p-3 text-sm outline-none focus:border-teal/60"
      />
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button onClick={onClose}>Close</Button>
        {person.url && (
          <ExternalButton href={person.url}>Open GitHub profile</ExternalButton>
        )}
        <Button variant="primary" onClick={copy}>
          {copied ? 'Copied' : 'Copy message'}
        </Button>
      </div>
    </Dialog>
  )
}
