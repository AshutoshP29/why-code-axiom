// Sample data that mirrors the Figma designs, so the screens work before the API exists.
// Two items are real, as the graph holds them: the answer for Response.apparent_encoding (PR #5797
// replaced chardet with charset_normalizer) and the refusal for check_compatibility (changed by the
// PR's commit 3e798b9, with no recorded reason). Their people, dates, quotes and links are real.
// Everything else (the maintainer_* people, other PRs, issues and commits) is made up, and its links
// open GitHub searches rather than invented pages. Scores and counts are made up throughout.
// Every id is built the way whycode/ids.py builds it. The UI shows "Sample data" while this is in use.

import type {
  Answer,
  AnsweredAnswer,
  AnswerThresholds,
  Decision,
  Entity,
  Evaluation,
  Explorer,
  ExplorerItem,
  GraphEdge,
  GraphNode,
  HedgedAnswer,
  Health,
  Ingestion,
  LineageCommit,
  LineageDecision,
  Overview,
  Person,
  RefusedAnswer,
  RelatedItem,
  Repo,
  SourceRef,
  StageProgress,
} from './types'

export const SAMPLE_REPO = 'psf/requests'
const GH = 'https://github.com/psf/requests'

const id = (kind: string, key: string) => `${SAMPLE_REPO}#${kind}:${key}`

function search(term: string, type: 'issues' | 'pullrequests' | 'commits' | 'code'): string {
  return `https://github.com/search?q=${encodeURIComponent(`repo:${SAMPLE_REPO} ${term}`)}&type=${type}`
}

const pr = (n: number, term: string): SourceRef => ({
  id: id('pr', String(n)),
  label: `PR #${n}`,
  url: search(term, 'pullrequests'),
})
const issue = (n: number, term: string): SourceRef => ({
  id: id('issue', String(n)),
  label: `Issue #${n}`,
  url: search(term, 'issues'),
})
/** Invented commits. Ids carry the full 40-character sha, as in the graph; screens show the first 7. */
const FULL_SHA: Record<string, string> = {
  a1b2c3d: 'a1b2c3daf81ce2c3d2d61bef8cd2dfa780e9cab2',
  c1d4a99: 'c1d4a998d940813fa6150f29a6c3c92998854065',
  '4b7e2d1': '4b7e2d11d65fa1c3b33418784fc0e2c428187950',
  d7a3f10: 'd7a3f1016b0f70cd8ec7b0b65de30e759309f2b2',
  f3e91c2: 'f3e91c27d0502053d2700037d9d41fe4cb965ca9',
  b82d7e0: 'b82d7e05c6446873edb555fce5dc470ad5a10a61',
  '9e0f5b1': '9e0f5b13f0e228a2e19074d2b8063eb024bc8242',
  '7d3e1aa': '7d3e1aa72765f4db397e58ff21d75ece1ab5a506',
  '5c8f0e2': '5c8f0e2d5a46bbeb80d24138d0c9d2552d72b33b',
  '0b9d7c4': '0b9d7c433279465671fe579d0fb5035ae7ab8277',
  '2e6a9f3': '2e6a9f39d07dc50a99667e1bed31ecb5a7f7c68f',
  '3c9b2e7': '3c9b2e7ea5c00e182155e3358d8333d6390a8f5c',
}

function fullSha(short: string): string {
  const sha = FULL_SHA[short]
  if (!sha) throw new Error(`No full sha for sample commit ${short}`)
  return sha
}

const commit = (short: string, term: string): SourceRef => ({
  id: id('commit', fullSha(short)),
  label: `Commit ${short}`,
  url: search(term, 'commits'),
})
const code = (path: string, term: string): SourceRef => ({
  id: id('file', path),
  label: path,
  url: search(term, 'code'),
})

// The real items link to their own pages on GitHub.
const PR_5797 = 5797
const SWITCH_SHA = '3e798b94717918ea48a38cdc315bf47a1067cb39' // the PR's only commit
const realPr = (n: number): SourceRef => ({ id: id('pr', String(n)), label: `PR #${n}`, url: `${GH}/pull/${n}` })
const realCommit = (sha: string): SourceRef => ({
  id: id('commit', sha),
  label: `Commit ${sha.slice(0, 7)}`,
  url: `${GH}/commit/${sha}`,
})

// ---------- entities ----------

function file(path: string): Entity {
  const name = path.slice(path.lastIndexOf('/') + 1)
  return { id: id('file', path), kind: 'file', name, qualified_name: name, path }
}

function fn(path: string, qualified: string): Entity {
  const name = qualified.slice(qualified.lastIndexOf('.') + 1)
  return { id: id('fn', `${path}::${qualified}`), kind: 'function', name, qualified_name: qualified, path }
}

function cls(path: string, qualified: string): Entity {
  const name = qualified.slice(qualified.lastIndexOf('.') + 1)
  return { id: id('cls', `${path}::${qualified}`), kind: 'class', name, qualified_name: qualified, path }
}

function cfg(path: string, key: string, qualified = key): Entity {
  return { id: id('cfg', key), kind: 'config', name: key, qualified_name: qualified, path }
}

const INIT = 'src/requests/__init__.py'
const SESSIONS = 'src/requests/sessions.py'
const ADAPTERS = 'src/requests/adapters.py'
const AUTH = 'src/requests/auth.py'
const MODELS = 'src/requests/models.py'
const UTILS = 'src/requests/utils.py'

// Function and class names are the ones in psf/requests, as whycode/code/entities.py parses them.
export const E = {
  init: file(INIT),
  sessions: file(SESSIONS),
  adapters: file(ADAPTERS),
  auth: file(AUTH),
  models: file(MODELS),
  utils: file(UTILS),
  checkCompatibility: fn(INIT, 'check_compatibility'),
  sessionClass: cls(SESSIONS, 'Session'),
  // The redirect methods live on the mixin that Session inherits from, not on Session itself.
  rebuildAuth: fn(SESSIONS, 'SessionRedirectMixin.rebuild_auth'),
  resolveRedirects: fn(SESSIONS, 'SessionRedirectMixin.resolve_redirects'),
  mergeEnv: fn(SESSIONS, 'Session.merge_environment_settings'),
  trustEnv: cfg(SESSIONS, 'trust_env', 'Session.trust_env'),
  verify: cfg(SESSIONS, 'verify'),
  allowRedirects: cfg(SESSIONS, 'allow_redirects'),
  send: fn(ADAPTERS, 'HTTPAdapter.send'),
  poolMaxsize: cfg(ADAPTERS, 'pool_maxsize', 'HTTPAdapter.pool_maxsize'),
  maxRetries: cfg(ADAPTERS, 'max_retries'),
  timeout: cfg(ADAPTERS, 'timeout'),
  basicAuth: fn(AUTH, 'HTTPBasicAuth.__call__'),
  digestHeader: fn(AUTH, 'HTTPDigestAuth.build_digest_header'),
  apparentEncoding: fn(MODELS, 'Response.apparent_encoding'),
  text: fn(MODELS, 'Response.text'),
  iterContent: fn(MODELS, 'Response.iter_content'),
  json: fn(MODELS, 'Response.json'),
  netrc: fn(UTILS, 'get_netrc_auth'),
  bypassProxies: fn(UTILS, 'should_bypass_proxies'),
} satisfies Record<string, Entity>

export const ENTITIES: Entity[] = Object.values(E)

const item = (
  entity: Entity,
  decision_count: number,
  has_superseded = false,
  children: ExplorerItem[] = [],
): ExplorerItem => ({ entity, decision_count, has_superseded, children })

export const EXPLORER: Explorer = {
  root: 'requests/',
  files: [
    item(E.adapters, 4, false, [item(E.send, 1), item(E.poolMaxsize, 0)]),
    item(E.auth, 3, false, [item(E.basicAuth, 2), item(E.digestHeader, 1)]),
    item(E.sessions, 8, true, [
      item(E.rebuildAuth, 2, true),
      item(E.resolveRedirects, 3),
      item(E.mergeEnv, 2),
      item(E.trustEnv, 1),
    ]),
    item(E.models, 5, false, [item(E.apparentEncoding, 1), item(E.text, 2), item(E.iterContent, 1), item(E.json, 1)]),
    item(E.utils, 2, false, [item(E.netrc, 1), item(E.bypassProxies, 1)]),
    item(E.init, 0, false, [item(E.checkCompatibility, 0)]),
  ],
  config_keys: [
    item(E.maxRetries, 5, true),
    item(E.verify, 2),
    item(E.allowRedirects, 4),
    item(E.timeout, 1),
  ],
}

// ---------- repositories and ingestion ----------

const minutesAgo = (now: number, minutes: number) => new Date(now - minutes * 60_000).toISOString()

export function sampleRepos(now: number): Repo[] {
  return [
    {
      id: SAMPLE_REPO,
      status: 'READY',
      stage: null,
      progress_pct: 100,
      partial: false,
      error: null,
      last_synced_at: minutesAgo(now, 10),
      commits_count: 6495,
      decisions_count: 2140,
    },
    {
      id: 'pallets/flask',
      status: 'READY',
      stage: null,
      progress_pct: 100,
      partial: false,
      error: null,
      last_synced_at: minutesAgo(now, 120),
      commits_count: 5400,
      decisions_count: 1600,
    },
    {
      id: 'encode/httpx',
      status: 'INGESTING',
      stage: 'extract',
      progress_pct: 62,
      partial: true,
      error: null,
      last_synced_at: null,
      commits_count: 2900,
      decisions_count: 430,
    },
  ]
}

export function sampleStages(repo: Repo): StageProgress[] {
  if (repo.id === 'encode/httpx') {
    return [
      { stage: 'fetch', state: 'done', progress_pct: 100, headline: '2,100 PRs', detail: '2,900 commits, 2,100 pull requests, 3,400 issues' },
      { stage: 'parse', state: 'done', progress_pct: 100, headline: '1,180 entities', detail: 'files, functions and settings' },
      { stage: 'link', state: 'done', progress_pct: 100, headline: '4,020 links', detail: 'commits to PRs, PRs to issues' },
      { stage: 'extract', state: 'running', progress_pct: 61, headline: '430 of 700', detail: 'about 430 of 700 threads, each result saved' },
      { stage: 'supersession', state: 'queued', progress_pct: 0, headline: 'not started', detail: 'starts when reading finishes' },
    ]
  }
  if (repo.status === 'ERROR') {
    // Stages before the failed one finished; the failed one shows the error; the rest never ran.
    const failedAt = STAGE_KEYS.indexOf(repo.stage ?? 'fetch')
    return queuedStages().map((s, i) =>
      i < failedAt
        ? { ...s, state: 'done', progress_pct: 100, headline: 'done' }
        : i === failedAt
          ? { ...s, state: 'error', headline: 'stopped', detail: repo.error ?? 'stopped with an error' }
          : s,
    )
  }
  if (repo.status === 'READY') {
    return [
      { stage: 'fetch', state: 'done', progress_pct: 100, headline: '1,236 PRs', detail: 'commits, PRs, issues, docs' },
      { stage: 'parse', state: 'done', progress_pct: 100, headline: '3,201 entities', detail: 'files, functions and settings' },
      { stage: 'link', state: 'done', progress_pct: 100, headline: '9,860 links', detail: 'commits to PRs, PRs to issues' },
      { stage: 'extract', state: 'done', progress_pct: 100, headline: '2,140 decisions', detail: 'each result saved' },
      { stage: 'supersession', state: 'done', progress_pct: 100, headline: '312 found', detail: 'reverts, later overrides' },
    ]
  }
  return queuedStages()
}

const STAGE_KEYS: StageProgress['stage'][] = ['fetch', 'parse', 'link', 'extract', 'supersession']

/** Every stage waiting to run, as for a repo just added. */
function queuedStages(): StageProgress[] {
  const detail: Record<StageProgress['stage'], string> = {
    fetch: 'downloading commits, pull requests and issues',
    parse: 'files, functions and settings',
    link: 'commits to PRs, PRs to issues',
    extract: 'reading discussions with AI',
    supersession: 'starts when reading finishes',
  }
  return STAGE_KEYS.map((stage) => ({
    stage,
    state: 'queued',
    progress_pct: 0,
    headline: 'not started',
    detail: detail[stage],
  }))
}

export function sampleIngestion(repo: Repo): Ingestion {
  return { repo, stages: sampleStages(repo) }
}

// ---------- home ----------

export const OVERVIEW: Overview = {
  counts: { decisions: 2140, superseded: 312, evidence_links: 9860, entities: 14200 },
  hotspots: [
    { entity: E.maxRetries, reversals: 4 },
    { entity: E.rebuildAuth, reversals: 3 },
    { entity: E.verify, reversals: 3 },
    { entity: E.allowRedirects, reversals: 2 },
    { entity: E.text, reversals: 2 },
  ],
  example_questions: [
    { entity: E.apparentEncoding, question: 'Why does apparent_encoding use charset_normalizer?' },
    { entity: E.maxRetries, question: 'Why is max_retries off by default?' },
    { entity: E.rebuildAuth, question: 'Why does rebuild_auth strip headers?' },
    { entity: E.poolMaxsize, question: 'Why is pool_maxsize 10?' },
  ],
  showcase: [
    {
      outcome: 'answered',
      entity: E.apparentEncoding,
      question: 'Why does apparent_encoding use charset_normalizer?',
      summary: 'Decision, discussion, commit and the people to ask.',
    },
    {
      outcome: 'superseded',
      entity: E.maxRetries,
      question: 'Why is max_retries off by default?',
      summary: 'Shows the newest rule and the replaced ones as history.',
    },
    {
      outcome: 'hedged',
      entity: E.timeout,
      question: 'Why is there no default timeout?',
      summary: 'A likely reason from a single source, given under a warning.',
    },
    {
      outcome: 'refused',
      entity: E.checkCompatibility,
      question: 'Why does check_compatibility cap the charset_normalizer version?',
      summary: 'No recorded reason, so it lists facts and who to ask.',
    },
  ],
}

// ---------- people ----------

const person = (login: string, role: string, active: boolean, last_seen: string): Person => ({
  login,
  role,
  active,
  last_seen,
  url: null,
})

// ---------- decisions ----------

/**
 * `key` is decision_key(source id, "extract-v2", 0) from whycode/ids.py: each sample decision is the
 * first one extracted from its source, with the prompt version in whycode/extract/prompt.py.
 */
function decision(
  key: string,
  fields: Omit<Decision, 'id' | 'evidence_kind' | 'reviewed_by' | 'alternatives' | 'approved_by'> &
    Partial<Pick<Decision, 'evidence_kind' | 'reviewed_by' | 'alternatives' | 'approved_by'>>,
  supersedes: LineageDecision['supersedes'] = [],
): LineageDecision {
  return {
    id: id('dec', key),
    evidence_kind: 'EXPLICIT',
    reviewed_by: null,
    alternatives: [], // none recorded
    approved_by: [],
    ...fields,
    supersedes,
  }
}

const RA1 = decision('1c247d00b677b378', {
  summary: 'Forward the header on every redirect',
  rationale: 'Redirects were treated as part of the same request, so auth went along unchanged.',
  decided_at: '2012-11-02',
  status: 'SUPERSEDED',
  evidence_kind: 'INFERRED',
  proposed_by: 'maintainer_a',
  source: issue(812, 'redirect authorization header'),
})

const RA2 = decision(
  '155ebf64b6fa487c',
  {
    summary: 'Strip the Authorization header when a redirect changes host',
    rationale:
      'To avoid leaking credentials to a different host, the session drops the Authorization header when a redirect points to another origin.',
    decided_at: '2013-03-14',
    status: 'ACTIVE',
    proposed_by: 'maintainer_a',
    reviewed_by: 'maintainer_b',
    source: pr(1565, 'rebuild_auth'),
    alternatives: ['Strip the header on every redirect, even to the same host', 'Keep the header and leave it to the caller'],
    approved_by: ['maintainer_b', 'maintainer_c'],
  },
  [{ decision_id: RA1.id, kind: 'replaces' }],
)

const MR1 = decision('3bf1fc9dfbee99f0', {
  summary: 'Retry failed requests up to 10 times',
  rationale: 'Default of 10 retries chosen to hide flaky networks.',
  decided_at: '2012-06-04',
  status: 'SUPERSEDED',
  proposed_by: 'maintainer_a',
  source: issue(455, 'max_retries'),
})

const MR2 = decision(
  '4acafa2cdf3e5064',
  {
    summary: 'Cap retries at 3 and add backoff',
    rationale: 'Limit lowered after retry storms; backoff introduced for connection errors only.',
    decided_at: '2014-02-11',
    status: 'PARTIAL',
    proposed_by: 'maintainer_b',
    source: pr(1830, 'max_retries backoff'),
    approved_by: ['maintainer_a'],
  },
  [{ decision_id: MR1.id, kind: 'replaces' }],
)

const MR3 = decision(
  'd51e4a05c292ace2',
  {
    summary: 'Retries off by default, opt in with a Retry object',
    rationale: 'Silent retries caused duplicate side effects on non-idempotent calls.',
    decided_at: '2019-08-30',
    status: 'ACTIVE',
    proposed_by: 'maintainer_c',
    reviewed_by: 'maintainer_b',
    source: pr(5012, 'max_retries Retry'),
    alternatives: ['Retry only idempotent methods by default', 'Keep 3 retries and document the risk'],
    approved_by: ['maintainer_b'],
  },
  [{ decision_id: MR2.id, kind: 'refines' }],
)

const V1 = decision('97486b58f76a530c', {
  summary: 'Verify TLS certificates by default',
  rationale:
    'Unchecked certificates let a man-in-the-middle pass silently, so callers who need to skip the check must say verify=False.',
  decided_at: '2012-01-23',
  status: 'ACTIVE',
  proposed_by: 'maintainer_a',
  reviewed_by: 'maintainer_c',
  source: pr(300, 'verify certificates default'),
  alternatives: ['Warn about unverified certificates instead of failing'],
  approved_by: ['maintainer_c'],
})

// The hedged sample: the reason is only inferred, from one commit message and nothing else.
const T1 = decision('3e429f501fd9e9ec', {
  summary: 'Leave timeouts to the caller',
  rationale: 'Inferred from a commit message: a fixed default would cut off slow downloads that are still working.',
  decided_at: '2013-08-19',
  status: 'ACTIVE',
  evidence_kind: 'INFERRED',
  proposed_by: 'maintainer_b',
  source: commit('d7a3f10', 'timeout'),
})

// Real: decision 11 of those the graph recorded from PR #5797, decided (merged) on 2021-07-06.
// Decision 0 from the same PR is a different one (adding a requests[lgpl] extra).
const AE1 = decision('89ca71956b80d160', {
  summary: 'Replace chardet (LGPL) with charset_normalizer (MIT)',
  rationale:
    'With an LGPL dependency it was unclear whether projects that bundle requests into one binary must be LGPL too, and the Apache Software Foundation cannot depend on LGPL code. charset_normalizer is MIT licensed; chardet is still used first if it is installed.',
  decided_at: '2021-07-06',
  status: 'ACTIVE',
  proposed_by: 'ashb',
  reviewed_by: 'sigmavirus24',
  // Who merged the PR, then each approving review in order, as whycode/graph/build.py records them.
  approved_by: ['sigmavirus24', 'Ousret', 'mik-laj', 'kaxil', 'sethmlarson', 'nateprewitt'],
  source: realPr(PR_5797),
})

const withoutEdges = ({ supersedes: _ignored, ...d }: LineageDecision): Decision => d

// ---------- answers ----------

/** The cut-offs the API sends with every answer (see AnswerThresholds). */
const THRESHOLDS: AnswerThresholds = { answer: 0.7, refuse: 0.4 }

const node = (
  nodeId: string,
  kind: GraphNode['kind'],
  label: string,
  extra: Partial<Omit<GraphNode, 'id' | 'kind' | 'label'>> = {},
): GraphNode => ({
  id: nodeId,
  kind,
  label,
  dimmed: false,
  center: false,
  url: null,
  entity_id: null,
  ...extra,
})

const edge = (from: string, to: string, label: string): GraphEdge => ({ from, to, label })

// Real, apart from the scores: the graph's answer for Response.apparent_encoding.
const APPARENT_ENCODING: AnsweredAnswer = {
  verdict: 'answered',
  question: 'Why does Response.apparent_encoding use charset_normalizer instead of chardet?',
  entity: E.apparentEncoding,
  matched_by: 'selected',
  match_score: null,
  confidence: 0.88,
  thresholds: THRESHOLDS,
  partial_history: false,
  answer_text:
    'Because chardet is LGPL licensed. Projects that bundle requests into a single binary could not tell whether the result had to be LGPL too, and the Apache Software Foundation does not allow a required LGPL dependency. charset_normalizer is MIT licensed, so requests switched to it in 2021, and still uses chardet first when it is installed.',
  decision: withoutEdges(AE1),
  superseded: [],
  evidence_chain: [
    {
      kind: 'discussion',
      title: "PR #5797: Switch LGPL'd chardet for MIT licensed charset_normalizer",
      excerpt:
        '"By changing out this dependency for one under MIT we remove all license ambiguity." chardet stays as an escape hatch: it is used first if it is installed.',
      meta: ['2021-04-22 to 07-06', '105 comments', 'opened by @ashb'],
      source: { id: id('ev', `pr:${PR_5797}:body`), label: `PR #${PR_5797}`, url: `${GH}/pull/${PR_5797}` },
    },
    {
      kind: 'discussion',
      title: 'PR #5797: comment by @Ousret',
      excerpt:
        '"I have re-run all the tests proposed by the community, including mine" … "Everything is OK. Sames conclusion, all around ~80% compatibility." The tests compare what charset_normalizer detects with what chardet detects.',
      meta: ['2021-05-17', '@Ousret'],
      source: {
        id: id('ev', `pr:${PR_5797}:ic:842306896`),
        label: `PR #${PR_5797} comment`,
        url: `${GH}/pull/${PR_5797}#issuecomment-842306896`,
      },
    },
    {
      kind: 'commit',
      title: "3e798b9: Switch LGPL'd chardet for MIT licensed charset_normalizer",
      excerpt: 'The only commit in the PR. Its message gives the same licence reason and keeps chardet in use when it is installed.',
      meta: ['2021-07-06', '@ashb', '10 files'],
      source: realCommit(SWITCH_SHA),
    },
    {
      kind: 'code',
      title: 'models.py › Response.apparent_encoding()',
      excerpt:
        'Changed by the commit above (+1 / -1). It calls chardet.detect(), and compat.py binds that name to chardet if it is installed, otherwise to charset_normalizer.',
      meta: [MODELS],
      source: { id: E.apparentEncoding.id, label: MODELS, url: `${GH}/blob/main/${MODELS}` },
    },
  ],
  who_to_ask: [
    person('ashb', 'Proposed the decision', false, '2021-07-06'),
    person('nateprewitt', 'Approved it', true, '2026-08-25'),
    person('sigmavirus24', 'Approved and merged it', true, '2026-05-31'),
  ],
  confidence_factors: [
    { label: 'Entity match', value: 0.96, display: '96%', tone: 'good' },
    { label: 'Evidence directness', value: 0.92, display: '92%', tone: 'good' },
    { label: 'Independent sources', value: 1, display: '3 of 3', tone: 'good' },
    { label: 'Supersession resolved', value: 1, display: 'Not applicable', tone: 'neutral' },
  ],
  graph: {
    nodes: [
      node(AE1.id, 'decision', 'Replace chardet', { center: true, url: AE1.source.url }),
      node(E.apparentEncoding.id, 'entity', 'Response.apparent_encoding', { entity_id: E.apparentEncoding.id }),
      node(id('pr', String(PR_5797)), 'pull_request', `PR #${PR_5797}`, { url: realPr(PR_5797).url }),
      node(id('commit', SWITCH_SHA), 'commit', SWITCH_SHA.slice(0, 7), { url: realCommit(SWITCH_SHA).url }),
      node(E.checkCompatibility.id, 'entity', 'requests.check_compatibility', { entity_id: E.checkCompatibility.id }),
    ],
    edges: [
      edge(AE1.id, E.apparentEncoding.id, 'AFFECTS'),
      edge(AE1.id, id('pr', String(PR_5797)), 'DECIDED_IN'),
      edge(id('pr', String(PR_5797)), id('commit', SWITCH_SHA), 'CONTAINS'),
      edge(id('commit', SWITCH_SHA), E.apparentEncoding.id, 'MODIFIES'),
      edge(id('commit', SWITCH_SHA), E.checkCompatibility.id, 'MODIFIES'),
    ],
  },
}

const REBUILD_AUTH: AnsweredAnswer = {
  verdict: 'answered',
  question: 'Why does rebuild_auth strip the Authorization header on redirect?',
  entity: E.rebuildAuth,
  matched_by: 'selected',
  match_score: null,
  confidence: 0.87,
  thresholds: THRESHOLDS,
  partial_history: false,
  answer_text:
    'To avoid leaking credentials to a different host, the session drops the Authorization header when a redirect points to another origin, and re-applies auth for the new host instead. Same-host redirects keep the header.',
  decision: withoutEdges(RA2),
  superseded: [{ decision: withoutEdges(RA1), kind: 'replaces', superseded_at: RA2.decided_at }],
  evidence_chain: [
    {
      kind: 'incident',
      title: 'Issue #812: credentials reached an unrelated host after a redirect',
      excerpt: 'Reporter shows the header arriving at a third-party domain after a 302 response.',
      meta: ['2012-11-20', 'opened by @reporter_1'],
      source: issue(812, 'redirect authorization header'),
    },
    {
      kind: 'discussion',
      title: 'PR #1565: only strip auth when the host changes',
      excerpt:
        'Maintainers agree to drop the header on cross-host redirects while keeping same-host redirects working.',
      meta: ['2013-03-09 to 03-14', '14 comments'],
      source: pr(1565, 'rebuild_auth'),
    },
    {
      kind: 'commit',
      title: 'a1b2c3d: rebuild_auth strips on host change only',
      excerpt: 'Commit message cites #812 and the review outcome from the PR thread.',
      meta: ['2013-03-14', '@maintainer_a'],
      source: commit('a1b2c3d', 'rebuild_auth'),
    },
    {
      kind: 'code',
      title: 'sessions.py › SessionRedirectMixin.rebuild_auth()',
      excerpt: 'Function changed by the commit above. Later edits (2019, 2023) did not alter the rule.',
      meta: ['last touched 2023-06'],
      source: code(SESSIONS, 'def rebuild_auth'),
    },
  ],
  who_to_ask: [
    person('maintainer_a', 'Proposed the decision', true, '2025-09-01'),
    person('maintainer_b', 'Reviewed it', false, '2021-04-12'),
  ],
  confidence_factors: [
    { label: 'Entity match', value: 0.95, display: '95%', tone: 'good' },
    { label: 'Evidence directness', value: 0.9, display: '90%', tone: 'good' },
    { label: 'Independent sources', value: 1, display: '4 of 4', tone: 'good' },
    { label: 'Supersession resolved', value: 1, display: 'Yes', tone: 'good' },
  ],
  graph: {
    nodes: [
      node(RA2.id, 'decision', 'Strip auth on host change', { center: true, url: RA2.source.url }),
      node(E.rebuildAuth.id, 'entity', 'SessionRedirectMixin.rebuild_auth', { entity_id: E.rebuildAuth.id }),
      node(E.resolveRedirects.id, 'entity', 'SessionRedirectMixin.resolve_redirects', {
        entity_id: E.resolveRedirects.id,
      }),
      node(id('pr', '1565'), 'pull_request', 'PR #1565', { url: pr(1565, 'rebuild_auth').url }),
      node(id('issue', '812'), 'issue', 'Issue #812', { url: issue(812, 'redirect').url }),
      node(id('commit', fullSha('a1b2c3d')), 'commit', 'a1b2c3d', { url: commit('a1b2c3d', 'rebuild_auth').url }),
      node(RA1.id, 'decision', 'Forward on every redirect', { dimmed: true, url: RA1.source.url }),
    ],
    edges: [
      edge(RA2.id, E.rebuildAuth.id, 'AFFECTS'),
      edge(RA2.id, E.resolveRedirects.id, 'AFFECTS'),
      edge(RA2.id, id('pr', '1565'), 'DECIDED_IN'),
      edge(id('pr', '1565'), id('issue', '812'), 'CLOSES'),
      edge(RA2.id, id('commit', fullSha('a1b2c3d')), 'SUPPORTED_BY'),
      edge(RA2.id, RA1.id, 'SUPERSEDES'),
    ],
  },
}

const MAX_RETRIES: AnsweredAnswer = {
  verdict: 'answered',
  question: 'Why is max_retries off by default?',
  entity: E.maxRetries,
  matched_by: 'selected',
  match_score: null,
  confidence: 0.91,
  thresholds: THRESHOLDS,
  partial_history: false,
  answer_text:
    'Retries are off by default because silent retries repeated non-idempotent calls, such as POSTs, and caused duplicate side effects. Callers who want retries pass a Retry object, which keeps the backoff rule from 2014 for connection errors.',
  decision: withoutEdges(MR3),
  superseded: [{ decision: withoutEdges(MR1), kind: 'replaces', superseded_at: MR2.decided_at }],
  evidence_chain: [
    {
      kind: 'incident',
      title: 'Issue #4991: a retried POST created duplicate orders',
      excerpt: 'Reporter shows one call reaching the server three times after a read timeout.',
      meta: ['2019-06-17', 'opened by @reporter_2'],
      source: issue(4991, 'retry duplicate POST'),
    },
    {
      kind: 'discussion',
      title: 'PR #5012: turn retries off by default',
      excerpt: 'Maintainers agree that retrying must be an explicit choice, made with a Retry object.',
      meta: ['2019-07-02 to 08-30', '22 comments'],
      source: pr(5012, 'max_retries Retry'),
    },
    {
      kind: 'commit',
      title: 'c1d4a99: Retries off by default; opt in via Retry object',
      excerpt: 'Commit message links #4991 and #5012.',
      meta: ['2019-08-30', '@maintainer_c'],
      source: commit('c1d4a99', 'max_retries'),
    },
    {
      kind: 'code',
      title: 'adapters.py › max_retries',
      excerpt: 'Default set by the commit above. One later edit (2021) only fixed a docstring.',
      meta: ['last touched 2021-03'],
      source: code(ADAPTERS, 'max_retries'),
    },
  ],
  who_to_ask: [
    person('maintainer_c', 'Proposed the decision', true, '2026-08-20'),
    person('maintainer_b', 'Reviewed it', false, '2021-04-12'),
  ],
  confidence_factors: [
    { label: 'Entity match', value: 0.98, display: '98%', tone: 'good' },
    { label: 'Evidence directness', value: 0.88, display: '88%', tone: 'good' },
    { label: 'Independent sources', value: 1, display: '4 of 4', tone: 'good' },
    { label: 'Supersession resolved', value: 1, display: 'Yes', tone: 'good' },
  ],
  graph: {
    nodes: [
      node(MR3.id, 'decision', 'Off by default', { center: true, url: MR3.source.url }),
      node(E.maxRetries.id, 'entity', 'max_retries', { entity_id: E.maxRetries.id }),
      node(E.send.id, 'entity', 'HTTPAdapter.send', { entity_id: E.send.id }),
      node(id('pr', '5012'), 'pull_request', 'PR #5012', { url: pr(5012, 'max_retries').url }),
      node(id('issue', '4991'), 'issue', 'Issue #4991', { url: issue(4991, 'retry').url }),
      node(MR2.id, 'decision', 'Cap at 3 with backoff', { url: MR2.source.url }),
      node(MR1.id, 'decision', 'Retry up to 10 times', { dimmed: true, url: MR1.source.url }),
    ],
    edges: [
      edge(MR3.id, E.maxRetries.id, 'AFFECTS'),
      edge(MR3.id, E.send.id, 'AFFECTS'),
      edge(MR3.id, id('pr', '5012'), 'DECIDED_IN'),
      edge(id('pr', '5012'), id('issue', '4991'), 'CLOSES'),
      edge(MR3.id, MR2.id, 'SUPERSEDES'),
      edge(MR2.id, MR1.id, 'SUPERSEDES'),
    ],
  },
}

const VERIFY: AnsweredAnswer = {
  verdict: 'answered',
  question: 'Why is verify=True the default?',
  entity: E.verify,
  matched_by: 'selected',
  match_score: null,
  confidence: 0.84,
  thresholds: THRESHOLDS,
  partial_history: false,
  answer_text:
    'Certificates are checked by default because an unchecked certificate lets a man-in-the-middle read or change traffic without any error. Skipping the check has to be written out as verify=False, so it is always a visible choice.',
  decision: withoutEdges(V1),
  superseded: [],
  evidence_chain: [
    {
      kind: 'issue',
      title: 'Issue #271: HTTPS requests do not check certificates',
      excerpt: 'Reporter connects to a host with a self-signed certificate and gets no warning.',
      meta: ['2011-12-02', 'opened by @reporter_3'],
      source: issue(271, 'certificate verification'),
    },
    {
      kind: 'discussion',
      title: 'PR #300: verify certificates by default',
      excerpt: 'Reviewers agree a secure default matters more than the extra setup some users need.',
      meta: ['2012-01-10 to 01-23', '9 comments'],
      source: pr(300, 'verify certificates default'),
    },
    {
      kind: 'commit',
      title: '4b7e2d1: Turn on certificate verification by default',
      excerpt: 'Commit message links the PR and the issue.',
      meta: ['2012-01-23', '@maintainer_a'],
      source: commit('4b7e2d1', 'verify'),
    },
    {
      kind: 'code',
      title: 'sessions.py › verify',
      excerpt: 'Default set by the commit above and unchanged since.',
      meta: ['last touched 2020-11'],
      source: code(SESSIONS, 'self.verify = True'),
    },
  ],
  who_to_ask: [
    person('maintainer_a', 'Proposed the decision', true, '2025-09-01'),
    person('maintainer_c', 'Reviewed it', true, '2026-08-20'),
  ],
  confidence_factors: [
    { label: 'Entity match', value: 0.9, display: '90%', tone: 'good' },
    { label: 'Evidence directness', value: 0.82, display: '82%', tone: 'good' },
    { label: 'Independent sources', value: 0.75, display: '3 of 4', tone: 'good' },
    { label: 'Supersession resolved', value: 1, display: 'Not applicable', tone: 'neutral' },
  ],
  graph: {
    nodes: [
      node(V1.id, 'decision', 'Verify by default', { center: true, url: V1.source.url }),
      node(E.verify.id, 'entity', 'verify', { entity_id: E.verify.id }),
      node(E.mergeEnv.id, 'entity', 'Session.merge_environment_settings', {
        entity_id: E.mergeEnv.id,
      }),
      node(id('pr', '300'), 'pull_request', 'PR #300', { url: pr(300, 'verify').url }),
      node(id('issue', '271'), 'issue', 'Issue #271', { url: issue(271, 'certificate').url }),
    ],
    edges: [
      edge(V1.id, E.verify.id, 'AFFECTS'),
      edge(V1.id, E.mergeEnv.id, 'AFFECTS'),
      edge(V1.id, id('pr', '300'), 'DECIDED_IN'),
      edge(id('pr', '300'), id('issue', '271'), 'CLOSES'),
    ],
  },
}

const TIMEOUT: HedgedAnswer = {
  verdict: 'hedged',
  question: 'Why is there no default timeout?',
  entity: E.timeout,
  matched_by: 'selected',
  match_score: null,
  confidence: 0.55,
  thresholds: THRESHOLDS,
  partial_history: false,
  warning:
    'Only one source supports this, and the reason is inferred from a commit message rather than stated in a discussion or issue. Treat it as a lead and confirm it with the people below.',
  answer_text:
    'Timeouts seem to be left to the caller because no single value suits both quick API calls and long downloads. The only evidence is one commit message, so this is the likely reason, not a recorded decision.',
  decision: withoutEdges(T1),
  superseded: [],
  evidence_chain: [
    {
      kind: 'commit',
      title: 'd7a3f10: Pass timeout through to urllib3 instead of setting one',
      excerpt: 'The message says a fixed default "would cut off long downloads". No pull request or issue is linked to it.',
      meta: ['2013-08-19', '@maintainer_b'],
      source: commit('d7a3f10', 'timeout'),
    },
    {
      kind: 'code',
      title: 'adapters.py › timeout',
      excerpt: 'Still passed through unchanged. Later edits only renamed variables.',
      meta: ['last touched 2022-01'],
      source: code(ADAPTERS, 'timeout'),
    },
  ],
  who_to_ask: [
    person('maintainer_b', 'Wrote the commit', false, '2021-04-12'),
    person('maintainer_a', 'Last touched the line', true, '2025-09-01'),
  ],
  confidence_factors: [
    { label: 'Entity match', value: 0.94, display: '94%', tone: 'good' },
    { label: 'Evidence directness', value: 0.45, display: '45%, inferred', tone: 'bad' },
    { label: 'Independent sources', value: 0.5, display: '1 of 2 needed', tone: 'bad' },
    { label: 'Supersession resolved', value: 1, display: 'Not applicable', tone: 'neutral' },
  ],
  graph: {
    nodes: [
      node(T1.id, 'decision', 'Leave timeouts to the caller', { center: true, url: T1.source.url }),
      node(E.timeout.id, 'entity', 'timeout', { entity_id: E.timeout.id }),
      node(E.send.id, 'entity', 'HTTPAdapter.send', { entity_id: E.send.id }),
      node(id('commit', fullSha('d7a3f10')), 'commit', 'd7a3f10', { url: commit('d7a3f10', 'timeout').url }),
    ],
    edges: [
      edge(T1.id, E.timeout.id, 'AFFECTS'),
      edge(T1.id, E.send.id, 'AFFECTS'),
      edge(T1.id, id('commit', fullSha('d7a3f10')), 'SUPPORTED_BY'),
    ],
  },
}

// Real, apart from the scores: the graph has a commit that changed check_compatibility, but no
// decision that affects it, so it gives that fact and no reason (as whycode/graph/queries.py does).
const CHECK_COMPATIBILITY: RefusedAnswer = {
  verdict: 'refused',
  question: 'Why does check_compatibility cap the charset_normalizer version?',
  entity: E.checkCompatibility,
  matched_by: 'selected',
  match_score: null,
  confidence: 0.12,
  thresholds: THRESHOLDS,
  partial_history: false,
  reason:
    'The graph has no recorded decision for check_compatibility. It knows which commit changed it, but those are facts, not reasons, so WhyCode will not guess why. Here is what it can show instead.',
  known_facts: [
    {
      title: "Commit 3e798b9: Switch LGPL'd chardet for MIT licensed charset_normalizer",
      detail: 'changed it: +14 / -6 lines',
      meta: ['2021-07-06', '@ashb'],
      source: realCommit(SWITCH_SHA),
    },
  ],
  related: [
    {
      title: "PR #5797: Switch LGPL'd chardet for MIT licensed charset_normalizer",
      match_score: 0.36,
      source: realPr(PR_5797),
    },
  ],
  history_url: `${GH}/commits/main/${INIT}`,
  who_to_ask: [person('ashb', 'Last changed it', false, '2021-07-06')],
  confidence_factors: [
    { label: 'Entity match', value: 0.96, display: '96%', tone: 'good' },
    { label: 'Evidence directness', value: 0.05, display: '5%', tone: 'bad' },
    { label: 'Independent sources', value: 0, display: '0 of 2 needed', tone: 'bad' },
    { label: 'Supersession resolved', value: 1, display: 'Not applicable', tone: 'neutral' },
  ],
}

export const ANSWERS: Record<string, Answer> = {
  [E.apparentEncoding.id]: APPARENT_ENCODING,
  [E.rebuildAuth.id]: REBUILD_AUTH,
  [E.maxRetries.id]: MAX_RETRIES,
  [E.verify.id]: VERIFY,
  [E.timeout.id]: TIMEOUT,
  [E.checkCompatibility.id]: CHECK_COMPATIBILITY,
}

/** What the API says for an item the sample data knows nothing about. */
export function genericRefusal(entity: Entity, question: string): RefusedAnswer {
  return {
    verdict: 'refused',
    question,
    entity,
    matched_by: 'selected',
    match_score: null,
    confidence: 0.05,
    thresholds: THRESHOLDS,
    partial_history: false,
    reason:
      'The sample data has no decision, discussion or incident for this item, so WhyCode will not give a reason.',
    known_facts: [],
    related: [],
    history_url: entity.path ? `${GH}/commits/main/${entity.path}` : `${GH}/commits/main`,
    who_to_ask: [],
    confidence_factors: [
      { label: 'Entity match', value: 1, display: '100%', tone: 'good' },
      { label: 'Evidence directness', value: 0, display: '0%', tone: 'bad' },
      { label: 'Independent sources', value: 0, display: '0 of 2 needed', tone: 'bad' },
      { label: 'Supersession resolved', value: 1, display: 'Not applicable', tone: 'neutral' },
    ],
  }
}

/** What the API says when a question asked without an entity matches nothing in the graph. */
export function noMatchRefusal(question: string, related: RelatedItem[]): RefusedAnswer {
  return {
    verdict: 'refused',
    question,
    entity: null,
    matched_by: 'search',
    match_score: null,
    confidence: 0.04,
    thresholds: THRESHOLDS,
    partial_history: false,
    reason:
      'No function, file or config key in the graph matches this question, so WhyCode cannot tell which code it is about and will not guess. Pick an item and ask again.',
    known_facts: [],
    related,
    history_url: `${GH}/commits/main`,
    who_to_ask: [],
    confidence_factors: [
      { label: 'Entity match', value: 0, display: 'No match', tone: 'bad' },
      { label: 'Evidence directness', value: 0, display: '0%', tone: 'bad' },
      { label: 'Independent sources', value: 0, display: '0 of 2 needed', tone: 'bad' },
      { label: 'Supersession resolved', value: 1, display: 'Not applicable', tone: 'neutral' },
    ],
  }
}

// ---------- lineage ----------

const lineageCommit = (
  short: string,
  date: string,
  message: string,
  decision: LineageDecision | null,
): LineageCommit => ({
  sha: fullSha(short),
  date,
  message,
  url: search(short, 'commits'),
  decision_id: decision?.id ?? null,
})

// The commit the graph has for both real items. It is linked to a decision only where the
// decision affects the item: Response.apparent_encoding, not check_compatibility.
const switchCommit = (decision: LineageDecision | null): LineageCommit => ({
  sha: SWITCH_SHA,
  date: '2021-07-06',
  message: "Switch LGPL'd chardet for MIT licensed charset_normalizer",
  url: realCommit(SWITCH_SHA).url,
  decision_id: decision?.id ?? null,
})

interface LineageSample {
  as_of_years: number[]
  decisions: LineageDecision[]
  commits: LineageCommit[]
  commit_total: number
}

export const LINEAGES: Record<string, LineageSample> = {
  // Real: the PR #5797 slice of the graph has one commit for each of these.
  [E.apparentEncoding.id]: {
    as_of_years: [],
    decisions: [AE1],
    commits: [switchCommit(AE1)],
    commit_total: 1,
  },
  [E.checkCompatibility.id]: {
    as_of_years: [],
    decisions: [],
    commits: [switchCommit(null)],
    commit_total: 1,
  },
  [E.maxRetries.id]: {
    as_of_years: [2013, 2016],
    decisions: [MR1, MR2, MR3],
    commits: [
      lineageCommit('f3e91c2', '2012-06-04', 'Add max_retries to adapter config', MR1),
      lineageCommit('b82d7e0', '2014-02-11', 'Cap retries at 3 and add backoff', MR2),
      lineageCommit('c1d4a99', '2019-08-30', 'Retries off by default; opt in via Retry object', MR3),
      lineageCommit('9e0f5b1', '2021-03-02', 'Fix typo in docstring', null),
    ],
    commit_total: 12,
  },
  [E.rebuildAuth.id]: {
    as_of_years: [2012, 2016],
    decisions: [RA1, RA2],
    commits: [
      lineageCommit('7d3e1aa', '2012-11-02', 'Keep auth on redirects', RA1),
      lineageCommit('a1b2c3d', '2013-03-14', 'rebuild_auth strips on host change only', RA2),
      lineageCommit('5c8f0e2', '2019-02-07', 'Move redirect helpers into SessionRedirectMixin', null),
      lineageCommit('0b9d7c4', '2023-06-21', 'Add type hints to sessions', null),
    ],
    commit_total: 9,
  },
  [E.verify.id]: {
    as_of_years: [],
    decisions: [V1],
    commits: [
      lineageCommit('4b7e2d1', '2012-01-23', 'Turn on certificate verification by default', V1),
      lineageCommit('2e6a9f3', '2020-11-04', 'Document verify in the session docstring', null),
    ],
    commit_total: 6,
  },
  [E.timeout.id]: {
    as_of_years: [],
    decisions: [T1],
    commits: [
      lineageCommit('d7a3f10', '2013-08-19', 'Pass timeout through to urllib3 instead of setting one', T1),
      lineageCommit('3c9b2e7', '2022-01-12', 'Rename timeout variables in HTTPAdapter.send', null),
    ],
    commit_total: 5,
  },
}

// ---------- graph health ----------

export const HEALTH: Health = {
  last_ingest_at: '2026-10-24T14:10:00',
  stages: [
    { stage: 'fetch', state: 'done', progress_pct: 100, headline: '1,236 PRs', detail: 'commits, PRs, issues, docs' },
    { stage: 'parse', state: 'done', progress_pct: 100, headline: '3,201 entities', detail: 'files, functions, config keys' },
    { stage: 'link', state: 'done', progress_pct: 100, headline: '9,860 links', detail: 'commit to code, PR to issue' },
    { stage: 'extract', state: 'running', progress_pct: 78, headline: '1,670 of 2,140', detail: 'with evidence spans' },
    { stage: 'supersession', state: 'queued', progress_pct: 45, headline: '312 found so far', detail: 'reverts, later overrides' },
  ],
  counts: {
    commits: 4812,
    issues: 2077,
    entities: 3201,
    pull_requests: 1236,
    decisions: 2140,
    people: 212,
  },
  gap_queue: [
    {
      entity: E.poolMaxsize,
      flags: 2,
      last_question: 'Why is HTTPAdapter.pool_maxsize 10 by default?',
      last_flagged_at: '2026-10-24T11:02:00',
    },
    {
      entity: E.trustEnv,
      flags: 1,
      last_question: 'Why does trust_env read proxy settings?',
      last_flagged_at: '2026-10-23T16:40:00',
    },
    {
      entity: E.netrc,
      flags: 1,
      last_question: 'Why is .netrc read when no auth is passed?',
      last_flagged_at: '2026-10-22T09:15:00',
    },
  ],
  evaluation: {
    question_count: 40,
    measured: false,
    rows: [
      { metric: 'Citation accuracy', llm_only: 0.41, vector_rag: 0.63, whycode: 0.91 },
      { metric: 'Supersession detected correctly', llm_only: 0.12, vector_rag: 0.34, whycode: 0.88 },
      { metric: 'Correct refusals', llm_only: 0.08, vector_rag: 0.3, whycode: 0.92 },
      { metric: 'Answers with evidence links', llm_only: 0.2, vector_rag: 0.55, whycode: 1 },
    ],
  },
}

// ---------- evaluation ----------

const notRun = { llm_only: null, vector_rag: null, whycode: null }

/**
 * Sample labelled questions, consistent with the sample answers above. The real set of 40, with
 * known right answers, is written by the team; until it has been run every result is null.
 */
export const EVALUATION: Evaluation = {
  ...HEALTH.evaluation,
  questions: [
    { id: 'q01', question: 'Why does Response.apparent_encoding use charset_normalizer instead of chardet?', entity: E.apparentEncoding, expected: 'answered', results: notRun },
    { id: 'q02', question: 'Why is max_retries off by default?', entity: E.maxRetries, expected: 'superseded', results: notRun },
    { id: 'q03', question: 'Why is verify=True the default?', entity: E.verify, expected: 'answered', results: notRun },
    { id: 'q04', question: 'Why does check_compatibility cap the charset_normalizer version?', entity: E.checkCompatibility, expected: 'refused', results: notRun },
    { id: 'q05', question: 'What was the retry rule in 2013?', entity: E.maxRetries, expected: 'superseded', results: notRun },
    { id: 'q06', question: 'Why does trust_env read proxy settings from the environment?', entity: E.trustEnv, expected: 'refused', results: notRun },
    { id: 'q07', question: 'Why is .netrc read when no auth is passed?', entity: E.netrc, expected: 'refused', results: notRun },
    { id: 'q08', question: 'Why does iter_content default to a chunk size of 1?', entity: E.iterContent, expected: 'refused', results: notRun },
  ],
}

/** Overview for a sample repo other than psf/requests: real-looking counts, no content yet. */
export function emptyOverview(repo: Repo): Overview {
  return {
    counts: { decisions: repo.decisions_count, superseded: 0, evidence_links: 0, entities: 0 },
    hotspots: [],
    example_questions: [],
    showcase: [],
  }
}
