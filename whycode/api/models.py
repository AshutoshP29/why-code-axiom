"""Response models: the frontend contract in frontend/src/api/types.ts, field for field.

Names are snake_case as the screens expect. Dates serialise as ISO strings. Decision also carries
`alternatives` and `approved_by` (all approvers); `reviewed_by` stays as the first approver.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

RepoStatus = Literal["QUEUED", "INGESTING", "READY", "ERROR"]
Stage = Literal["fetch", "parse", "link", "extract", "supersession"]
StageState = Literal["done", "running", "queued", "error"]
EntityKind = Literal["file", "class", "function", "module", "config"]
DecisionStatus = Literal["ACTIVE", "SUPERSEDED", "PARTIAL"]
SupersedeKind = Literal["reverses", "replaces", "refines"]
EvidenceKind = Literal["incident", "issue", "discussion", "commit", "code"]
Tone = Literal["good", "bad", "neutral"]
GraphNodeKind = Literal["entity", "decision", "pull_request", "issue", "commit", "person"]
MatchedBy = Literal["selected", "search"]
ShowcaseOutcome = Literal["answered", "superseded", "hedged", "refused"]

STAGES: tuple[Stage, ...] = ("fetch", "parse", "link", "extract", "supersession")


class Repo(BaseModel):
    id: str
    status: RepoStatus
    stage: Stage | None
    progress_pct: int
    partial: bool
    error: str | None
    last_synced_at: datetime | None
    commits_count: int
    decisions_count: int


class StageProgress(BaseModel):
    stage: Stage
    state: StageState
    progress_pct: int
    headline: str
    detail: str


class Entity(BaseModel):
    id: str
    kind: EntityKind
    name: str
    qualified_name: str
    path: str | None


class EntityMatch(Entity):
    score: float = Field(ge=0.0, le=1.0)


class ExplorerItem(BaseModel):
    entity: Entity
    decision_count: int
    has_superseded: bool
    children: list["ExplorerItem"] = Field(default_factory=list)


class Explorer(BaseModel):
    root: str
    files: list[ExplorerItem]
    config_keys: list[ExplorerItem]


class SourceRef(BaseModel):
    id: str
    label: str
    url: str


class Person(BaseModel):
    login: str
    role: str
    active: bool
    last_seen: datetime | None
    url: str | None


class Decision(BaseModel):
    id: str
    summary: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    decided_at: date
    status: DecisionStatus
    evidence_kind: Literal["EXPLICIT", "INFERRED"]
    proposed_by: str | None
    reviewed_by: str | None  # the first approver, kept for older screens
    approved_by: list[str] = Field(default_factory=list)
    source: SourceRef


class SupersededNote(BaseModel):
    decision: Decision
    kind: SupersedeKind
    superseded_at: date


class EvidenceStep(BaseModel):
    kind: EvidenceKind
    title: str
    excerpt: str
    meta: list[str]
    source: SourceRef


class ConfidenceFactor(BaseModel):
    label: str
    value: float = Field(ge=0.0, le=1.0)
    display: str
    tone: Tone


class GraphNode(BaseModel):
    id: str
    kind: GraphNodeKind
    label: str
    dimmed: bool = False
    center: bool = False
    url: str | None = None
    entity_id: str | None = None


class GraphEdge(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    label: str


class AnswerGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class Fact(BaseModel):
    title: str
    detail: str
    meta: list[str]
    source: SourceRef


class RelatedItem(BaseModel):
    title: str
    match_score: float
    source: SourceRef


class AnswerThresholds(BaseModel):
    answer: float
    refuse: float


class _AnswerBase(BaseModel):
    question: str
    entity: Entity | None
    matched_by: MatchedBy
    match_score: float | None
    confidence: float = Field(ge=0.0, le=1.0)
    thresholds: AnswerThresholds
    partial_history: bool
    who_to_ask: list[Person]
    confidence_factors: list[ConfidenceFactor]


class AnsweredAnswer(_AnswerBase):
    verdict: Literal["answered"] = "answered"
    entity: Entity
    answer_text: str
    decision: Decision
    superseded: list[SupersededNote]
    evidence_chain: list[EvidenceStep]
    graph: AnswerGraph


class HedgedAnswer(AnsweredAnswer):
    verdict: Literal["hedged"] = "hedged"
    warning: str


class RefusedAnswer(_AnswerBase):
    verdict: Literal["refused"] = "refused"
    reason: str
    known_facts: list[Fact]
    related: list[RelatedItem]
    history_url: str


Answer = Annotated[AnsweredAnswer | HedgedAnswer | RefusedAnswer, Field(discriminator="verdict")]


class Hotspot(BaseModel):
    entity: Entity
    reversals: int


class ExampleQuestion(BaseModel):
    entity: Entity
    question: str


class ShowcaseItem(BaseModel):
    outcome: ShowcaseOutcome
    entity: Entity
    question: str
    summary: str


class OverviewCounts(BaseModel):
    decisions: int
    superseded: int
    evidence_links: int
    entities: int


class Overview(BaseModel):
    counts: OverviewCounts
    hotspots: list[Hotspot]
    example_questions: list[ExampleQuestion]
    showcase: list[ShowcaseItem]


class SupersedesRef(BaseModel):
    decision_id: str
    kind: SupersedeKind


class LineageDecision(Decision):
    supersedes: list[SupersedesRef] = Field(default_factory=list)


class LineageCommit(BaseModel):
    sha: str
    message: str
    date: datetime
    url: str
    decision_id: str | None


class Lineage(BaseModel):
    entity: Entity
    as_of: date | None
    as_of_years: list[int]
    decisions: list[LineageDecision]
    commits: list[LineageCommit]
    commit_total: int


class Gap(BaseModel):
    entity: Entity
    flags: int
    last_question: str
    last_flagged_at: datetime


class EvalRow(BaseModel):
    metric: str
    llm_only: float | None
    vector_rag: float | None
    whycode: float | None


class EvaluationSummary(BaseModel):
    question_count: int
    measured: bool
    rows: list[EvalRow]


class HealthCounts(BaseModel):
    commits: int
    issues: int
    entities: int
    pull_requests: int
    decisions: int
    people: int


class Health(BaseModel):
    last_ingest_at: datetime | None
    stages: list[StageProgress]
    counts: HealthCounts
    gap_queue: list[Gap]
    evaluation: EvaluationSummary


class AskRequest(BaseModel):
    repo: str
    entity_id: str | None
    question: str = Field(min_length=1, max_length=2000)


class GapRequest(BaseModel):
    repo: str
    entity_id: str
    question: str = Field(min_length=1, max_length=2000)
