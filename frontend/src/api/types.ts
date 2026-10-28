// The contract between the screens and the WhyCode API (FastAPI).
// Field names are snake_case to match the Python side. Every call is scoped to one repo,
// mirroring the graph rule that every query filters on `repo`.
// Ids are the graph ids from whycode/ids.py, e.g. "psf/requests#fn:src/requests/sessions.py::Session.send".

export type RepoStatus = 'QUEUED' | 'INGESTING' | 'READY' | 'ERROR'
export type Stage = 'fetch' | 'parse' | 'link' | 'extract' | 'supersession'

export interface Repo {
  id: string // "psf/requests"
  status: RepoStatus
  stage: Stage | null // current stage while ingesting
  progress_pct: number // overall ingestion progress
  partial: boolean // true while ingestion is unfinished; answers say "partial history"
  error: string | null // why ingestion stopped, when status is ERROR; shown to the user
  last_synced_at: string | null
  commits_count: number
  decisions_count: number
}

/** Result of checking a GitHub link before ingesting it (Add repository dialog). */
export interface RepoCheck {
  repo: string
  found: boolean
  is_public: boolean
  commits: number
  pull_requests: number
  issues: number
  minutes_low: number
  minutes_high: number
  ai_calls: number
  fits_free_tier: boolean
  capped: boolean // large repos are capped to their most-discussed PRs and issues
}

export type StageState = 'done' | 'running' | 'queued' | 'error'

export interface StageProgress {
  stage: Stage
  state: StageState
  progress_pct: number
  headline: string // big number on Graph health: "1,236 PRs", "1,670 of 2,140"
  detail: string // line on the ingestion screen: "about 430 of 700 threads, each result saved"
}

export interface Ingestion {
  repo: Repo
  stages: StageProgress[]
}

// A class's id is "<repo>#cls:<path>::<qualified name>", as in whycode/graph/schema.cypher.
export type EntityKind = 'file' | 'class' | 'function' | 'module' | 'config'

export interface Entity {
  id: string
  kind: EntityKind
  name: string // "rebuild_auth"
  qualified_name: string // "Session.rebuild_auth"
  path: string | null // "src/requests/sessions.py"
}

export interface EntityMatch extends Entity {
  score: number // 0..1
}

export interface ExplorerItem {
  entity: Entity
  decision_count: number
  has_superseded: boolean
  children: ExplorerItem[] // functions inside a file
}

export interface Explorer {
  root: string // "requests/"
  files: ExplorerItem[]
  config_keys: ExplorerItem[]
}

export interface SourceRef {
  id: string // graph id of the PR, issue, commit or evidence
  label: string // "PR #1565", "Issue #812"
  url: string
}

export interface Person {
  login: string
  role: string // "Proposed the decision", "Reviewed it", "Wrote the line"
  active: boolean // seen in this repo within ~18 months
  last_seen: string | null
  url: string | null
}

export type DecisionStatus = 'ACTIVE' | 'SUPERSEDED' | 'PARTIAL'
export type SupersedeKind = 'reverses' | 'replaces' | 'refines'

export interface Decision {
  id: string
  summary: string
  rationale: string
  decided_at: string // ISO date
  status: DecisionStatus // status today, not as of any earlier date
  evidence_kind: 'EXPLICIT' | 'INFERRED'
  proposed_by: string | null // login
  reviewed_by: string | null
  source: SourceRef
}

/** An older decision that the current one overrode. Drives the amber banner. */
export interface SupersededNote {
  decision: Decision
  kind: SupersedeKind
  superseded_at: string
}

export type EvidenceKind = 'incident' | 'issue' | 'discussion' | 'commit' | 'code'

export interface EvidenceStep {
  kind: EvidenceKind
  title: string
  excerpt: string
  meta: string[] // "2012-11-20", "opened by @reporter_1", "14 comments"
  source: SourceRef
}

export interface ConfidenceFactor {
  label: string // "Entity match", "Independent sources"
  value: number // 0..1, fills the bar
  display: string // "95%", "4 of 4", "Yes", "Not applicable"
  tone: 'good' | 'bad' | 'neutral'
}

export type GraphNodeKind = 'entity' | 'decision' | 'pull_request' | 'issue' | 'commit' | 'person'

export interface GraphNode {
  id: string
  kind: GraphNodeKind
  label: string
  dimmed: boolean // superseded decisions get a dashed edge
  center: boolean // the hub of the drawing, normally the current decision
  url: string | null // source to open on click
  entity_id: string | null // set on entity nodes: clicking re-asks about this entity
}

export interface GraphEdge {
  from: string
  to: string
  label: string // relationship type, e.g. "AFFECTS"
}

/** Something the history states as fact, kept apart from reasons on the refusal screen. */
export interface Fact {
  title: string
  detail: string
  meta: string[]
  source: SourceRef
}

/** An item that mentions the topic but does not explain it. */
export interface RelatedItem {
  title: string
  match_score: number // 0..1
  source: SourceRef
}

/**
 * Where confidence turns into each outcome, sent with every answer so the screens never hardcode
 * them. The screens only display these; the verdict itself is always the API's.
 */
export interface AnswerThresholds {
  answer: number // at or above this, a plain answer (0.70 today)
  refuse: number // below this, a refusal (0.40 today); in between, a hedged answer
}

/** How the item an answer is about was found. */
export type MatchedBy =
  | 'selected' // the user picked the entity before asking
  | 'search' // the question came without one; the API chose it (full-text search, then vector search over evidence)

interface AnswerBase {
  question: string
  /**
   * The code item the answer is about: the one the user picked, or the one the API matched from
   * the question. null only on a refusal where nothing in the graph matched the question.
   */
  entity: Entity | null
  matched_by: MatchedBy
  match_score: number | null // 0..1, how well the question matched `entity`; null unless matched_by is 'search' and an entity was found
  confidence: number // 0..1
  thresholds: AnswerThresholds
  partial_history: boolean
  who_to_ask: Person[]
  confidence_factors: ConfidenceFactor[]
}

export interface AnsweredAnswer extends AnswerBase {
  verdict: 'answered'
  entity: Entity // an answer is always about one item
  answer_text: string // worded by the LLM from graph facts only
  decision: Decision // the current governing decision
  superseded: SupersededNote[]
  evidence_chain: EvidenceStep[]
  graph: { nodes: GraphNode[]; edges: GraphEdge[] }
}

export interface RefusedAnswer extends AnswerBase {
  verdict: 'refused'
  reason: string
  known_facts: Fact[]
  related: RelatedItem[]
  history_url: string // commit history of the item on GitHub
}

/**
 * A full answer given with a visible warning, for thresholds.refuse <= confidence < thresholds.answer.
 * Everything an AnsweredAnswer has is still there; the screens add the warning and never show it
 * as a confident answer.
 */
export interface HedgedAnswer extends Omit<AnsweredAnswer, 'verdict'> {
  verdict: 'hedged'
  warning: string // why confidence is limited, written by the backend from the factors
}

/**
 * The API picks the verdict from the confidence and the thresholds it sends:
 * confidence >= answer: 'answered'; refuse <= confidence < answer: 'hedged'; below refuse: 'refused'.
 */
export type Answer = AnsweredAnswer | HedgedAnswer | RefusedAnswer

export interface Hotspot {
  entity: Entity
  reversals: number
}

export interface ExampleQuestion {
  entity: Entity
  question: string
}

export type ShowcaseOutcome = 'answered' | 'superseded' | 'hedged' | 'refused'

export interface ShowcaseItem {
  outcome: ShowcaseOutcome
  entity: Entity
  question: string
  summary: string
}

export interface Overview {
  counts: {
    decisions: number
    superseded: number
    evidence_links: number
    entities: number
  }
  hotspots: Hotspot[]
  example_questions: ExampleQuestion[]
  showcase: ShowcaseItem[]
}

export interface LineageDecision extends Decision {
  /** Edges to OLDER decisions this one supersedes. */
  supersedes: { decision_id: string; kind: SupersedeKind }[]
}

export interface LineageCommit {
  sha: string
  message: string // first line
  date: string
  url: string
  decision_id: string | null // null = no recorded decision for this change
}

export interface Lineage {
  entity: Entity
  as_of: string | null // echo of the request ("2016-12-31"); null = today
  as_of_years: number[] // years offered by the "View as of" switch (Today is always added)
  decisions: LineageDecision[] // decided on or before as_of, oldest first
  commits: LineageCommit[] // on or before as_of, oldest first
  commit_total: number // all commits that touched the entity, before any limit
}

export interface Gap {
  entity: Entity
  flags: number
  last_question: string
  last_flagged_at: string
}

export interface EvalRow {
  metric: string
  llm_only: number | null // 0..1; null until the evaluation has run
  vector_rag: number | null
  whycode: number | null
}

export interface EvaluationSummary {
  question_count: number // the size of the labelled set (40)
  measured: boolean // false = the numbers are placeholders
  rows: EvalRow[]
}

export type EvalSystem = 'llm_only' | 'vector_rag' | 'whycode'

/** What the right response to a labelled question is. */
export type ExpectedOutcome = 'answered' | 'superseded' | 'refused'

export interface EvalResult {
  // What the system actually did. A hedged answer is still an answer: it counts as 'answered', or as
  // 'superseded' when it names the rules it replaced, exactly as a confident answer would.
  outcome: ExpectedOutcome
  correct: boolean
  cited_source: boolean
}

export interface EvalQuestion {
  id: string // "q01"
  question: string
  entity: Entity | null
  expected: ExpectedOutcome
  results: Record<EvalSystem, EvalResult | null> // null = not run yet
}

export interface Evaluation extends EvaluationSummary {
  questions: EvalQuestion[] // the questions written so far
}

export interface Health {
  last_ingest_at: string | null
  stages: StageProgress[]
  counts: {
    commits: number
    issues: number
    entities: number // functions and files
    pull_requests: number
    decisions: number
    people: number
  }
  gap_queue: Gap[]
  evaluation: EvaluationSummary
}

export interface WhyCodeApi {
  listRepos(): Promise<Repo[]>
  checkRepo(input: string): Promise<RepoCheck>
  addRepo(repo: string, keepUpdated: boolean): Promise<Repo>
  syncRepo(repo: string): Promise<Repo>
  getIngestion(repo: string): Promise<Ingestion>
  getOverview(repo: string): Promise<Overview>
  getExplorer(repo: string): Promise<Explorer>
  searchEntities(repo: string, text: string): Promise<EntityMatch[]>
  getEntity(repo: string, entityId: string): Promise<Entity>
  /** entityId null: the user picked nothing, so the API finds the entity from the question itself. */
  ask(repo: string, entityId: string | null, question: string): Promise<Answer>
  getLineage(repo: string, entityId: string, asOf: string | null): Promise<Lineage>
  getHealth(repo: string): Promise<Health>
  getEvaluation(repo: string): Promise<Evaluation>
  reingest(repo: string): Promise<Repo>
  flagGap(repo: string, entityId: string, question: string): Promise<Gap>
}
