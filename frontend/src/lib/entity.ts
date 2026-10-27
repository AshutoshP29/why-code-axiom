import type { Entity, EntityKind } from '../api/types'

export function basename(path: string): string {
  return path.slice(path.lastIndexOf('/') + 1)
}

/** How an entity is named on screen: "Session.rebuild_auth", "utils.get_netrc_auth", "max_retries". */
export function entityLabel(entity: Entity): string {
  if (entity.kind === 'function' && !entity.qualified_name.includes('.') && entity.path) {
    return `${basename(entity.path).replace(/\.py$/, '')}.${entity.qualified_name}`
  }
  return entity.qualified_name
}

const KIND_LABEL: Record<EntityKind, string> = {
  file: 'file',
  function: 'function',
  module: 'module',
  config: 'config key',
}

export function kindLabel(kind: EntityKind): string {
  return KIND_LABEL[kind]
}

/** Breadcrumb parts: ["sessions.py", "Session.rebuild_auth()"]. */
export function entityCrumbs(entity: Entity, withKind = false): string[] {
  const parts: string[] = withKind ? [kindLabel(entity.kind)] : []
  if (entity.kind === 'file') return [...parts, entity.path ?? entity.name]
  if (entity.path) parts.push(basename(entity.path))
  parts.push(entity.kind === 'function' ? `${entityLabel(entity)}()` : entityLabel(entity))
  return parts
}

export function questionAbout(label: string): string {
  return `Why is ${label} like this?`
}

export function defaultQuestion(entity: Entity): string {
  return questionAbout(entityLabel(entity))
}

const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9_.-]+$/

/**
 * Turn what a user pastes ("https://github.com/encode/httpx/tree/master", "github.com/encode/httpx.git",
 * "encode/httpx") into "encode/httpx", lowercased like the graph ids. Null if it is not a repo.
 */
export function parseRepoInput(input: string): string | null {
  const text = input.trim().replace(/^https?:\/\//i, '').replace(/\/+$/, '')
  const isUrl = /^(www\.)?github\.com\//i.test(text)
  const [owner, rawName, ...rest] = text.replace(/^(www\.)?github\.com\//i, '').split('/')
  // A bare "owner/name" must be exactly that; a GitHub URL may continue with /tree/..., /pulls, etc.
  if (!owner || !rawName || (!isUrl && rest.length > 0)) return null
  const repo = `${owner}/${rawName.replace(/\.git$/i, '')}`
  return REPO_RE.test(repo) ? repo.toLowerCase() : null
}
