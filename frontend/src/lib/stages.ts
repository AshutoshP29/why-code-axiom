import type { Stage, StageState } from '../api/types'
import type { Tone } from './tones'

export const STAGE_ORDER: Stage[] = ['fetch', 'parse', 'link', 'extract', 'supersession']

export const STATE_TONE: Record<StageState, Tone> = {
  done: 'green',
  running: 'blue',
  queued: 'gray',
  error: 'red',
}

/** Names on the Graph health cards. */
export const HEALTH_STAGE_TITLE: Record<Stage, string> = {
  fetch: 'Fetch history',
  parse: 'Parse code',
  link: 'Link entities',
  extract: 'Extract decisions',
  supersession: 'Detect supersession',
}

/** Plainer names on the "Reading owner/name" screen. */
export const INGEST_STAGE_TITLE: Record<Stage, string> = {
  fetch: 'Fetch history',
  parse: 'Map the code',
  link: 'Link everything',
  extract: 'Read discussions with AI',
  supersession: 'Mark replaced rules',
}

/** What a repo is doing right now, for the repo switcher: "Stage 4 of 5: reading discussions". */
const STAGE_DOING: Record<Stage, string> = {
  fetch: 'downloading history',
  parse: 'mapping the code',
  link: 'linking everything',
  extract: 'reading discussions',
  supersession: 'marking replaced rules',
}

export function stageSummary(stage: Stage): string {
  return `Stage ${STAGE_ORDER.indexOf(stage) + 1} of ${STAGE_ORDER.length}: ${STAGE_DOING[stage]}`
}
