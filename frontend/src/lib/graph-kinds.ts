import type { EntityKind, GraphViewKind } from '../api/types'
import type { Tone } from './tones'

// How each kind of node is drawn on the Graph screen. Hex values are the theme tokens in index.css
// (SVG attributes and canvas cannot read Tailwind classes). Code is blue, files white; a ring
// (hollow node) marks a file, a module or a config key, so the shared colours stay apart.
const INK = '#e8eaed'
const BLUE = '#60a5fa'
const TEAL = '#2dd4bf'
const AMBER = '#f5a524'
const VIOLET = '#a78bfa'
const RED = '#f26b6b'
const GRAY = '#8b93a1'
const GREEN = '#3fb950'

export const EDGE_COLOR = '#3a4351'
export const EDGE_ACTIVE = TEAL
export const FRESH_COLOR = AMBER
export const CANVAS_BG = '#0d1117' // --color-sunken

export interface KindStyle {
  label: string // in the legend and the side panel
  tone: Tone // the same colour as a badge
  color: string
  radius: number
  ring: boolean // drawn hollow
}

export const KIND_STYLE: Record<GraphViewKind, KindStyle> = {
  decision: { label: 'Decision', tone: 'teal', color: TEAL, radius: 7.5, ring: false },
  evidence: { label: 'Evidence', tone: 'amber', color: AMBER, radius: 4, ring: false },
  pull_request: { label: 'Pull request', tone: 'violet', color: VIOLET, radius: 6, ring: false },
  issue: { label: 'Issue', tone: 'red', color: RED, radius: 6, ring: false },
  commit: { label: 'Commit', tone: 'gray', color: GRAY, radius: 4, ring: false },
  person: { label: 'Person', tone: 'green', color: GREEN, radius: 5.5, ring: false },
  module: { label: 'Module', tone: 'gray', color: INK, radius: 9, ring: true },
  file: { label: 'File', tone: 'gray', color: INK, radius: 7, ring: true },
  class: { label: 'Class', tone: 'blue', color: BLUE, radius: 6.5, ring: false },
  function: { label: 'Function', tone: 'blue', color: BLUE, radius: 4.5, ring: false },
  config: { label: 'Config key', tone: 'blue', color: BLUE, radius: 5, ring: true },
}

/** Legend order: the decision graph first, then the code it explains. */
export const KIND_ORDER = Object.keys(KIND_STYLE) as GraphViewKind[]

const CODE_KINDS: ReadonlySet<GraphViewKind> = new Set(['file', 'class', 'function', 'config', 'module'])

/** Code items can be asked about and have a decision history. */
export function isCodeKind(kind: GraphViewKind): kind is EntityKind {
  return CODE_KINDS.has(kind)
}
