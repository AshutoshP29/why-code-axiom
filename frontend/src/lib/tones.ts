// Colour roles from the designs. Full class names are spelled out so Tailwind can find them.

export type Tone = 'teal' | 'amber' | 'red' | 'blue' | 'green' | 'violet' | 'gray'

export const BADGE_TONE: Record<Tone, string> = {
  teal: 'border-teal/40 bg-teal/10 text-teal',
  amber: 'border-amber/40 bg-amber/10 text-amber',
  red: 'border-red/40 bg-red/10 text-red',
  blue: 'border-blue/40 bg-blue/10 text-blue',
  green: 'border-green/40 bg-green/10 text-green',
  violet: 'border-violet/40 bg-violet/10 text-violet',
  gray: 'border-line-strong bg-raised text-muted',
}

export const FILL_TONE: Record<Tone, string> = {
  teal: 'bg-teal',
  amber: 'bg-amber',
  red: 'bg-red',
  blue: 'bg-blue',
  green: 'bg-green',
  violet: 'bg-violet',
  gray: 'bg-gray',
}

export const BORDER_TONE: Record<Tone, string> = {
  teal: 'border-teal/40',
  amber: 'border-amber/40',
  red: 'border-red/40',
  blue: 'border-blue/40',
  green: 'border-green/40',
  violet: 'border-violet/40',
  gray: 'border-line-strong',
}

export const TEXT_TONE: Record<Tone, string> = {
  teal: 'text-teal',
  amber: 'text-amber',
  red: 'text-red',
  blue: 'text-blue',
  green: 'text-green',
  violet: 'text-violet',
  gray: 'text-muted',
}

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')
