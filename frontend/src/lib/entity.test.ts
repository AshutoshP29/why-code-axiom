import { describe, expect, it } from 'vitest'
import { E } from '../api/sample'
import { defaultQuestion, entityCrumbs, entityLabel, parseRepoInput } from './entity'

describe('parseRepoInput', () => {
  it.each([
    ['encode/httpx', 'encode/httpx'],
    ['github.com/encode/httpx', 'encode/httpx'],
    ['https://github.com/encode/httpx', 'encode/httpx'],
    ['https://www.github.com/Encode/HTTPX.git', 'encode/httpx'],
    ['https://github.com/encode/httpx/tree/master/httpx', 'encode/httpx'],
    ['  psf/requests/  ', 'psf/requests'],
  ])('reads %s', (input, expected) => {
    expect(parseRepoInput(input)).toBe(expected)
  })

  it.each(['', 'requests', 'psf/', '/requests', 'psf/requests/extra', 'psf requests', 'https://gitlab.com/a/b'])(
    'rejects %j',
    (input) => {
      expect(parseRepoInput(input)).toBeNull()
    },
  )
})

describe('class entities', () => {
  it('use the graph id format and are named without call brackets', () => {
    expect(E.sessionClass.id).toBe('psf/requests#cls:src/requests/sessions.py::Session')
    expect(entityLabel(E.sessionClass)).toBe('Session')
    expect(entityCrumbs(E.sessionClass, true)).toEqual(['class', 'sessions.py', 'Session'])
  })
})

describe('entity names', () => {
  it('shows methods and settings by qualified name', () => {
    expect(entityLabel(E.rebuildAuth)).toBe('SessionRedirectMixin.rebuild_auth')
    expect(entityLabel(E.poolMaxsize)).toBe('HTTPAdapter.pool_maxsize')
    expect(entityLabel(E.maxRetries)).toBe('max_retries')
  })

  it('prefixes module-level functions with their module', () => {
    expect(entityLabel(E.netrc)).toBe('utils.get_netrc_auth')
    // A package's __init__.py is the package itself.
    expect(entityLabel(E.checkCompatibility)).toBe('requests.check_compatibility')
  })

  it('builds breadcrumbs like the designs', () => {
    expect(entityCrumbs(E.rebuildAuth)).toEqual(['sessions.py', 'SessionRedirectMixin.rebuild_auth()'])
    expect(entityCrumbs(E.maxRetries, true)).toEqual(['config key', 'adapters.py', 'max_retries'])
  })

  it('writes a default question', () => {
    expect(defaultQuestion(E.verify)).toBe('Why is verify like this?')
  })
})
