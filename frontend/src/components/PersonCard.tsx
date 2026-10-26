import type { Person } from '../api/types'
import { formatYear } from '../lib/format'
import { Avatar, Badge } from './ui'

/** A person to ask. Clicking opens the Ask dialog (the "Clicks a person" step in the user flow). */
export function PersonCard({ person, onAsk }: { person: Person; onAsk: (person: Person) => void }) {
  const seen = person.last_seen ? formatYear(person.last_seen) : null
  return (
    <button
      type="button"
      onClick={() => onAsk(person)}
      aria-label={`Ask @${person.login}`}
      className="flex w-full items-center gap-3 rounded-lg border border-line bg-raised px-3 py-2.5 text-left hover:border-line-strong"
    >
      <Avatar login={person.login} tone={person.active ? 'teal' : 'amber'} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">@{person.login}</span>
        <span className="block text-xs text-faint">
          {person.role}
          {seen && (person.active ? `, active ${seen}` : `, last seen ${seen}`)}
        </span>
      </span>
      <Badge tone={person.active ? 'green' : 'amber'}>{person.active ? 'Active' : 'Inactive'}</Badge>
    </button>
  )
}
