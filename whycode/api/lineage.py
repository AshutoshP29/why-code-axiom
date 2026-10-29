"""GET /api/lineage: every decision on an entity (schema query 5b) and the commits that changed it.

`as_of` keeps decisions and commits dated on or before the end of that day; the years offered by
the "View as of" switch always come from the full history. A commit with no date at all (neither
its own nor its pull request's merge date) counts in commit_total but is not listed.
"""

from datetime import UTC, date, datetime, time

from whycode.api import models as m
from whycode.api import reads
from whycode.graph.queries import Run

Q_LINEAGE_DECISIONS = """// q:lineage_decisions
MATCH (e:{label} {{id: $id, repo: $repo}})<-[:AFFECTS]-(d:Decision {{repo: $repo}})
OPTIONAL MATCH (d)-[s:SUPERSEDES]->(o:Decision {{repo: $repo}})
OPTIONAL MATCH (d)-[:PROPOSED_BY]->(p:Person {{repo: $repo}})
OPTIONAL MATCH (d)-[:APPROVED_BY]->(a:Person {{repo: $repo}})
OPTIONAL MATCH (d)-[:DECIDED_IN]->(src {{repo: $repo}})
RETURN d,
       collect(DISTINCT {{id: o.id, kind: s.kind}}) AS supersedes,
       collect(DISTINCT p.login) AS proposers,
       collect(DISTINCT a.login) AS approvers,
       collect(DISTINCT src) AS sources
ORDER BY d.decided_at
"""
Q_LINEAGE_COMMITS = """// q:lineage_commits
MATCH (c:Commit {{repo: $repo}})-[:MODIFIES]->(e:{label} {{id: $id, repo: $repo}})
OPTIONAL MATCH (pr:PullRequest {{repo: $repo}})-[:CONTAINS]->(c)
OPTIONAL MATCH (d:Decision {{repo: $repo}})-[:DECIDED_IN]->(pr)
WHERE (d)-[:AFFECTS]->(e)
RETURN c, collect(DISTINCT pr.merged_at) AS merged, collect(DISTINCT d.id) AS decisions
"""


def _source(src: dict | None, fallback_id: str, repo: str) -> m.SourceRef:
    gh = f"https://github.com/{repo}"
    if not src:
        return m.SourceRef(id=fallback_id, label="Decision", url=gh)
    if src.get("number") is not None:
        kind = "PR" if "#pr:" in src["id"] else "Issue"
        return m.SourceRef(id=src["id"], label=f"{kind} #{src['number']}", url=src.get("url") or gh)
    return m.SourceRef(id=src["id"], label=src["id"].split("#", 1)[-1], url=src.get("url") or gh)


def _decision(row: dict, repo: str) -> m.LineageDecision:
    d = row["d"]
    approvers = [a for a in row["approvers"] if a]
    proposers = [p for p in row["proposers"] if p]
    return m.LineageDecision(
        id=d["id"],
        summary=d.get("summary", ""),
        rationale=d.get("rationale", ""),
        alternatives=list(d.get("alternatives") or []),
        decided_at=reads.native(d["decided_at"]).date(),
        status=d.get("status")
        if d.get("status") in ("ACTIVE", "SUPERSEDED", "PARTIAL")
        else "ACTIVE",
        evidence_kind="EXPLICIT" if d.get("evidence_kind") == "EXPLICIT" else "INFERRED",
        proposed_by=proposers[0] if proposers else None,
        reviewed_by=approvers[0] if approvers else None,
        approved_by=approvers,
        source=_source(row["sources"][0] if row["sources"] else None, d["id"], repo),
        supersedes=[
            m.SupersedesRef(decision_id=s["id"], kind=s["kind"])
            for s in row["supersedes"]
            if s.get("id") and s.get("kind")
        ],
    )


def _commit(row: dict, repo: str) -> m.LineageCommit | None:
    c = row["c"]
    merged = [reads.native(x) for x in row["merged"] if x is not None]
    when = reads.native(c.get("date")) or (min(merged) if merged else None)
    if when is None:
        return None
    message = c.get("message") or ""
    decisions = [d for d in row["decisions"] if d]
    return m.LineageCommit(
        sha=c["sha"],
        message=message.splitlines()[0] if message else "",
        date=when,
        url=c.get("url") or f"https://github.com/{repo}/commit/{c['sha']}",
        decision_id=decisions[0] if decisions else None,
    )


def lineage(run: Run, repo: str, entity: m.Entity, as_of: date | None) -> m.Lineage:
    label = reads.LABEL_BY_KIND[reads.id_kind(entity.id)]
    params = {"repo": repo, "id": entity.id}
    decisions = [_decision(r, repo) for r in run(Q_LINEAGE_DECISIONS.format(label=label), params)]
    commit_rows = run(Q_LINEAGE_COMMITS.format(label=label), params)
    commits = sorted(
        (c for c in (_commit(r, repo) for r in commit_rows) if c is not None),
        key=lambda c: c.date,
    )
    years = sorted({d.decided_at.year for d in decisions} | {c.date.year for c in commits})
    if as_of is not None:
        end = datetime.combine(as_of, time.max, tzinfo=UTC)
        decisions = [d for d in decisions if d.decided_at <= as_of]
        commits = [c for c in commits if c.date <= end]
    return m.Lineage(
        entity=entity,
        as_of=as_of,
        as_of_years=years,
        decisions=decisions,
        commits=commits,
        commit_total=len(commit_rows),
    )
