import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { Entity, GraphEdge, GraphNode, GraphNodeKind } from '../api/types'
import { questionAbout } from '../lib/entity'
import { whyPath } from '../lib/routes'
import type { Tone } from '../lib/tones'
import { Dot, SectionLabel } from './ui'

// Hex values match the theme tokens; SVG presentation attributes cannot read Tailwind classes.
const COLOR = {
  teal: '#2dd4bf',
  amber: '#f5a524',
  violet: '#a78bfa',
  red: '#f26b6b',
  blue: '#60a5fa',
  gray: '#8b93a1',
  green: '#3fb950',
  edge: '#3a4351',
}

function nodeColor(node: GraphNode): string {
  if (node.kind === 'decision') return node.dimmed ? COLOR.amber : COLOR.teal
  const byKind: Record<Exclude<GraphNodeKind, 'decision'>, string> = {
    entity: COLOR.blue,
    pull_request: COLOR.violet,
    issue: COLOR.red,
    commit: COLOR.gray,
    person: COLOR.green,
  }
  return byKind[node.kind]
}

const W = 280
const H = 200

/** Hub in the middle, everything else evenly around it. Stable for the same input. */
function layout(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const hub = nodes.find((n) => n.center) ?? nodes[0]
  const rest = nodes.filter((n) => n !== hub)
  const pos = new Map<string, { x: number; y: number }>()
  if (hub) pos.set(hub.id, { x: W / 2, y: H / 2 })
  rest.forEach((n, i) => {
    const angle = -Math.PI / 2 + (i / rest.length) * 2 * Math.PI
    pos.set(n.id, { x: W / 2 + Math.cos(angle) * 105, y: H / 2 + Math.sin(angle) * 72 })
  })
  return pos
}

const LEGEND: { kind: GraphNodeKind | 'superseded'; tone: Tone; label: string }[] = [
  { kind: 'decision', tone: 'teal', label: 'Decision (active) | affects code' },
  { kind: 'superseded', tone: 'amber', label: 'Decision (superseded, dashed edge)' },
  { kind: 'pull_request', tone: 'violet', label: 'PR' },
  { kind: 'issue', tone: 'red', label: 'Incident issue' },
  { kind: 'entity', tone: 'blue', label: 'Code item (click to ask about it)' },
  { kind: 'commit', tone: 'gray', label: 'Commit' },
]

export function GraphNeighbourhood({
  nodes,
  edges,
  current,
}: {
  nodes: GraphNode[]
  edges: GraphEdge[]
  current: Entity
}) {
  const navigate = useNavigate()
  const [focused, setFocused] = useState<GraphNode | null>(null)
  const pos = layout(nodes)
  const byId = new Map(nodes.map((n) => [n.id, n]))

  function activate(node: GraphNode) {
    if (node.entity_id && node.entity_id !== current.id) {
      // "Re-ask for the neighbouring entity" in the user flow.
      navigate(whyPath(node.entity_id, questionAbout(node.label)))
    } else if (node.url) {
      window.open(node.url, '_blank', 'noopener,noreferrer')
    }
  }

  const present = new Set(nodes.map((n) => (n.kind === 'decision' && n.dimmed ? 'superseded' : n.kind)))

  return (
    <section>
      <SectionLabel>Graph neighbourhood</SectionLabel>
      <div className="mt-3 rounded-xl border border-line bg-sunken">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Items connected to this decision">
          {edges.map((e) => {
            const a = pos.get(e.from)
            const b = pos.get(e.to)
            if (!a || !b) return null
            const dashed = byId.get(e.to)?.dimmed || byId.get(e.from)?.dimmed
            return (
              <line
                key={`${e.from}-${e.to}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={dashed ? COLOR.amber : COLOR.edge}
                strokeWidth={1.5}
                strokeDasharray={dashed ? '3 3' : undefined}
              />
            )
          })}
          {nodes.map((n) => {
            const p = pos.get(n.id)
            if (!p) return null
            const color = nodeColor(n)
            const clickable = (n.entity_id && n.entity_id !== current.id) || n.url
            const r = n.center ? 13 : n.entity_id === current.id ? 12 : 9
            const action = n.entity_id && n.entity_id !== current.id ? `Ask about ${n.label}` : n.url ? `Open ${n.label}` : n.label
            return (
              <g
                key={n.id}
                role={clickable ? 'button' : 'img'}
                tabIndex={clickable ? 0 : undefined}
                aria-label={action}
                className={clickable ? 'cursor-pointer outline-none' : undefined}
                onClick={() => clickable && activate(n)}
                onKeyDown={(e) => {
                  if (clickable && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    activate(n)
                  }
                }}
                onMouseEnter={() => setFocused(n)}
                onMouseLeave={() => setFocused(null)}
                onFocus={() => setFocused(n)}
                onBlur={() => setFocused(null)}
              >
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={r + (focused?.id === n.id ? 2 : 0)}
                  fill={color}
                  fillOpacity={0.18}
                  stroke={color}
                  strokeWidth={focused?.id === n.id ? 2.5 : 1.75}
                  strokeDasharray={n.dimmed ? '3 2' : undefined}
                />
                <circle cx={p.x} cy={p.y} r={2.5} fill={color} />
              </g>
            )
          })}
        </svg>
        <p className="border-t border-line px-3 py-2 text-xs text-muted" aria-live="polite">
          {focused ? focused.label : 'Point at a node to see what it is.'}
        </p>
      </div>
      <ul className="mt-3 space-y-1 text-xs text-faint">
        {LEGEND.filter((l) => present.has(l.kind)).map((l) => (
          <li key={l.kind} className="flex items-center gap-2">
            <Dot tone={l.tone} /> {l.label}
          </li>
        ))}
      </ul>
    </section>
  )
}
