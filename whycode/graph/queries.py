"""Query 5a: the current governing decision(s) for a code entity, with their evidence.

Returns a typed Answer, or a Refusal when the graph holds no decision for the entity. A refusal
never contains a generated reason: only facts the graph states (commits that changed the entity,
the last person who changed it), kept apart from reasons.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from whycode.ids import normalize_repo

Run = Callable[[str, dict], list[dict]]  # cypher, params -> records as dicts

LABEL_BY_KIND = {"file": "File", "cls": "Class", "fn": "Function", "cfg": "ConfigKey"}

# Schema query 5a, with the label inserted from LABEL_BY_KIND (labels cannot be parameters).
Q5A = """
MATCH (e:{label} {{id: $entityId, repo: $repo}})<-[:AFFECTS]-(d:Decision {{repo: $repo}})
WHERE NOT EXISTS {{ MATCH (d)<-[s:SUPERSEDES]-(:Decision) WHERE s.kind IN ['reverses','replaces'] }}
MATCH (d)-[sb:SUPPORTED_BY]->(ev:Evidence)
OPTIONAL MATCH (d)-[:PROPOSED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:APPROVED_BY]->(a:Person)
OPTIONAL MATCH (d)-[:DECIDED_IN]->(src)
RETURN d,
       collect(DISTINCT {{ev: ev, start: sb.span_start, end: sb.span_end}}) AS evidence,
       collect(DISTINCT p) AS proposers,
       collect(DISTINCT a) AS approvers,
       collect(DISTINCT src) AS sources
ORDER BY d.decided_at DESC
"""
Q_ENTITY = "MATCH (e:{label} {{id: $entityId, repo: $repo}}) RETURN e.id AS id LIMIT 1"
Q_FACTS = """
MATCH (c:Commit {{repo: $repo}})-[m:MODIFIES]->(e:{label} {{id: $entityId, repo: $repo}})
OPTIONAL MATCH (p:Person {{repo: $repo}})-[:AUTHORED]->(c)
RETURN c, properties(m) AS m, p ORDER BY c.date DESC LIMIT 10
"""


class PersonRef(BaseModel):
    login: str
    active: bool | None = None
    last_seen: datetime | None = None


class EvidenceRef(BaseModel):
    id: str
    quote: str  # exactly the span of the stored source text the extraction verified
    source_type: str
    url: str | None = None
    author: str | None = None
    date: datetime | None = None


class SourceRef(BaseModel):
    id: str
    label: str  # "PR #5797"
    url: str | None = None


class DecisionView(BaseModel):
    id: str
    summary: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    decided_at: datetime
    status: str
    evidence_kind: str
    confidence: float
    evidence: list[EvidenceRef] = Field(min_length=1)
    proposed_by: list[PersonRef] = Field(default_factory=list)
    approved_by: list[PersonRef] = Field(default_factory=list)
    decided_in: list[SourceRef] = Field(default_factory=list)


class Answer(BaseModel):
    verdict: Literal["answered"] = "answered"
    repo: str
    entity_id: str
    decisions: list[DecisionView] = Field(min_length=1)  # newest first


class Fact(BaseModel):
    title: str
    detail: str
    date: datetime | None = None
    url: str | None = None


class Refusal(BaseModel):
    verdict: Literal["refused"] = "refused"
    repo: str
    entity_id: str
    entity_found: bool
    reason: str
    known_facts: list[Fact] = Field(default_factory=list)
    last_owner: PersonRef | None = None


def label_for(entity_id: str) -> str:
    """The node label for a code entity id ("<repo>#fn:..." -> "Function")."""
    kind = entity_id.split("#", 1)[1].split(":", 1)[0] if "#" in entity_id else ""
    if kind not in LABEL_BY_KIND:
        raise ValueError(f"not a code entity id: {entity_id!r}")
    return LABEL_BY_KIND[kind]


def _native(value):
    """Neo4j temporal values to Python ones; everything else unchanged."""
    return value.to_native() if hasattr(value, "to_native") else value


def _person(p: dict | None) -> PersonRef | None:
    if not p:
        return None
    return PersonRef(
        login=p["login"], active=p.get("active"), last_seen=_native(p.get("last_seen"))
    )


def _source(s: dict) -> SourceRef:
    if s.get("number") is not None:
        kind = "PR" if "#pr:" in s["id"] else "Issue"
        return SourceRef(id=s["id"], label=f"{kind} #{s['number']}", url=s.get("url"))
    return SourceRef(id=s["id"], label=s["id"].split("#", 1)[-1], url=s.get("url"))


def _decision(row: dict) -> DecisionView:
    d = row["d"]
    evidence = []
    for item in row["evidence"]:
        ev = item["ev"]
        text = ev.get("text") or ""
        start, end = item.get("start"), item.get("end")
        quote = text[start:end] if start is not None and end is not None else text
        evidence.append(
            EvidenceRef(
                id=ev["id"],
                quote=quote,
                source_type=ev.get("source_type", ""),
                url=ev.get("url"),
                author=ev.get("author"),
                date=_native(ev.get("date")),
            )
        )
    evidence.sort(key=lambda e: (e.date is None, e.date))
    return DecisionView(
        id=d["id"],
        summary=d["summary"],
        rationale=d["rationale"],
        alternatives=list(d.get("alternatives") or []),
        decided_at=_native(d["decided_at"]),
        status=d.get("status", "ACTIVE"),
        evidence_kind=d.get("evidence_kind", ""),
        confidence=d.get("extraction_confidence", 0.0),
        evidence=evidence,
        proposed_by=[p for p in map(_person, row["proposers"]) if p],
        approved_by=[p for p in map(_person, row["approvers"]) if p],
        decided_in=[_source(s) for s in row["sources"]],
    )


def current_decisions(run: Run, repo: str, entity_id: str) -> Answer | Refusal:
    repo = normalize_repo(repo)
    label = label_for(entity_id)
    params = {"repo": repo, "entityId": entity_id}
    rows = run(Q5A.format(label=label), params)
    if rows:
        return Answer(repo=repo, entity_id=entity_id, decisions=[_decision(r) for r in rows])

    if not run(Q_ENTITY.format(label=label), params):
        return Refusal(
            repo=repo,
            entity_id=entity_id,
            entity_found=False,
            reason=f"{entity_id} is not in the graph for {repo}.",
        )
    facts, last_owner = [], None
    for r in run(Q_FACTS.format(label=label), params):
        c, m = r["c"], r["m"] or {}
        first_line = (c.get("message") or "").splitlines()[0] if c.get("message") else ""
        facts.append(
            Fact(
                title=f"Commit {c['sha'][:7]}" + (f": {first_line}" if first_line else ""),
                detail=f"changed it: +{m.get('added', 0)} / -{m.get('removed', 0)} lines",
                date=_native(c.get("date")),
                url=c.get("url"),
            )
        )
        last_owner = last_owner or _person(r["p"])
    return Refusal(
        repo=repo,
        entity_id=entity_id,
        entity_found=True,
        reason=(
            "The graph has no recorded decision for this. The facts below say what changed it "
            "and when; they are not reasons."
        ),
        known_facts=facts,
        last_owner=last_owner,
    )


def neo4j_runner(driver, database: str) -> Run:
    """A Run backed by a Neo4j driver; records come back as plain dicts.

    Nodes become property dicts; relationships must be returned as properties(r), because
    record.data() turns a relationship into a (start, type, end) tuple. Server notices are off:
    until Phase 2 writes SUPERSEDES, every 5a query would warn that the type does not exist.
    """

    def run(cypher: str, params: dict) -> list[dict]:
        with driver.session(database=database, notifications_min_severity="OFF") as session:
            return [r.data() for r in session.run(cypher, params)]

    return run
