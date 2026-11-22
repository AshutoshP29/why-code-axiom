"""Knowledge risk for engineering leads: where the "why" is about to be lost, or already is.

Two readings of the graph, both read-only and both repo-scoped (schema rule 3):

- **Orphaned decisions.** Code whose decisions still govern it, where every person who proposed
  or approved them is inactive. The reason is recorded, but nobody left can be asked about it.
  "In force" is query 5a's rule: no `reverses`/`replaces` SUPERSEDES points at the decision.
- **Changed often, never explained.** Code commits keep modifying that no decision explains.

Each query starts with a "// q:<name>" comment, as the other reads do.
"""

from datetime import UTC, datetime, timedelta

from whycode.api import models as m
from whycode.api import reads
from whycode.graph.queries import Run

TOP = 20  # rows per table; `counts` is over the whole repo

# Functions, classes and config keys. A file is skipped: a decision rarely explains a whole file,
# and the explorer already shows files by how well they are explained.
_CODE = "(e:Function OR e:Class OR e:ConfigKey)"
# Query 5a's rule for a decision that still governs its code.
_IN_FORCE = (
    "NOT EXISTS { MATCH (d)<-[s:SUPERSEDES]-(:Decision) WHERE s.kind IN ['reverses', 'replaces'] }"
)
# The same window as `active` (whycode.graph.build.ACTIVE_WITHIN, about 18 months); a unit test
# keeps the two equal. Not imported: build pulls in the whole extraction pipeline.
ACTIVE_WITHIN = timedelta(days=548)
# Nobody around decided it. Collected per entity, so one person around anywhere clears it.
# `active` only reflects the pull requests that were read, so a maintainer last seen in an old PR
# looks gone; a commit they authored within the same window ($since) counts as being around too.
_ALL_GONE = (
    "size(proposers + approvers) > 0 "
    "AND all(p IN proposers + approvers WHERE coalesce(p.active, false) = false "
    "AND NOT EXISTS { MATCH (p)-[:AUTHORED]->(c:Commit {repo: $repo}) WHERE c.date >= $since })"
)
_ORPHANED_MATCH = f"""
MATCH (e {{repo: $repo}})<-[:AFFECTS]-(d:Decision {{repo: $repo}})
WHERE {_CODE} AND {_IN_FORCE}
OPTIONAL MATCH (d)-[:PROPOSED_BY]->(pp:Person {{repo: $repo}})
OPTIONAL MATCH (d)-[:APPROVED_BY]->(ap:Person {{repo: $repo}})
WITH e,
     count(DISTINCT d) AS decisions,
     max(d.decided_at) AS last_decided_at,
     collect(DISTINCT pp) AS proposers,
     collect(DISTINCT ap) AS approvers
WHERE {_ALL_GONE}
"""

Q_ORPHANED = f"""// q:risk_orphaned{_ORPHANED_MATCH}
RETURN e, decisions, last_decided_at, proposers, approvers
ORDER BY decisions DESC, last_decided_at DESC
LIMIT $limit
"""
Q_ORPHANED_COUNT = f"""// q:risk_orphaned_count{_ORPHANED_MATCH}
RETURN count(e) AS orphaned
"""
Q_UNEXPLAINED = f"""// q:risk_unexplained
MATCH (c:Commit {{repo: $repo}})-[:MODIFIES]->(e {{repo: $repo}})
WHERE {_CODE} AND NOT EXISTS {{ MATCH (e)<-[:AFFECTS]-(:Decision {{repo: $repo}}) }}
OPTIONAL MATCH (a:Person {{repo: $repo}})-[:AUTHORED]->(c)
WITH e, count(DISTINCT c) AS commits, count(DISTINCT a) AS authors, max(c.date) AS last_changed_at
RETURN e, commits, authors, last_changed_at
ORDER BY commits DESC, e.id
LIMIT $limit
"""
Q_COUNTS = f"""// q:risk_counts
RETURN COUNT {{
         MATCH (e {{repo: $repo}})
         WHERE {_CODE} AND EXISTS {{ MATCH (e)<-[:AFFECTS]-(:Decision {{repo: $repo}}) }}
       }} AS code_with_decisions,
       COUNT {{
         MATCH (e {{repo: $repo}})
         WHERE {_CODE}
           AND EXISTS {{ MATCH (:Commit {{repo: $repo}})-[:MODIFIES]->(e) }}
           AND NOT EXISTS {{ MATCH (e)<-[:AFFECTS]-(:Decision {{repo: $repo}}) }}
       }} AS changed_without_reason
"""


def _person(node: dict, role: str) -> m.Person:
    return m.Person(
        login=node["login"],
        role=role,
        active=bool(node.get("active")),
        last_seen=reads.native(node.get("last_seen")),
        url=f"https://github.com/{node['login']}",
    )


def _people(row: dict) -> list[m.Person]:
    """Everyone who decided it, the one seen most recently first (they are all inactive)."""
    people: dict[str, m.Person] = {}
    for node in row["proposers"]:
        people.setdefault(node["login"], _person(node, "Proposed the decision"))
    for node in row["approvers"]:
        people.setdefault(node["login"], _person(node, "Approved it"))
    unknown = datetime.min.replace(tzinfo=UTC)  # never seen here: listed last
    return sorted(people.values(), key=lambda p: p.last_seen or unknown, reverse=True)


def _orphaned(row: dict) -> m.OrphanedCode:
    return m.OrphanedCode(
        entity=reads.entity(row["e"]),
        decisions=row["decisions"],
        people=_people(row),
        last_decided_at=reads.native(row["last_decided_at"]),
    )


def _unexplained(row: dict) -> m.UnexplainedCode:
    return m.UnexplainedCode(
        entity=reads.entity(row["e"]),
        commits=row["commits"],
        authors=row["authors"],
        last_changed_at=reads.native(row["last_changed_at"]),
    )


def knowledge_risk(run: Run, repo: str, now: datetime | None = None) -> m.KnowledgeRisk:
    since = (now or datetime.now(UTC)) - ACTIVE_WITHIN  # a commit after this: still around
    params = {"repo": repo, "limit": TOP}
    orphaned = [_orphaned(r) for r in run(Q_ORPHANED, {**params, "since": since})]
    unexplained = [_unexplained(r) for r in run(Q_UNEXPLAINED, params)]
    counts = run(Q_COUNTS, {"repo": repo})[0]
    orphaned_rows = run(Q_ORPHANED_COUNT, {"repo": repo, "since": since})
    return m.KnowledgeRisk(
        orphaned=orphaned,
        unexplained=unexplained,
        counts=m.RiskCounts(
            code_with_decisions=counts["code_with_decisions"],
            orphaned=orphaned_rows[0]["orphaned"] if orphaned_rows else 0,
            changed_without_reason=counts["changed_without_reason"],
        ),
    )
