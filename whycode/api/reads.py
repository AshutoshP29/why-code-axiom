"""Graph reads behind the API endpoints. Every query filters on `repo` (schema rule 3).

Each query starts with a "// q:<name>" comment so logs and test fakes can tell them apart.
Rows come from a Run (whycode.graph.queries): cypher + params -> list of plain dicts.
"""

import re

from whycode.api import models as m
from whycode.graph.queries import Run

LABEL_BY_KIND = {
    "file": "File",
    "cls": "Class",
    "fn": "Function",
    "cfg": "ConfigKey",
    "mod": "Module",
}
API_KIND = {"file": "file", "cls": "class", "fn": "function", "cfg": "config", "mod": "module"}
CODE_LABELS = ("File", "Class", "Function", "ConfigKey", "Module")
SEARCH_LIMIT = 10

Q_REPOS = """// q:repos
MATCH (r:Repo)
RETURN r,
       COUNT { MATCH (c:Commit {repo: r.id}) } AS commits,
       COUNT { MATCH (d:Decision {repo: r.id}) } AS decisions
ORDER BY r.last_synced_at DESC
"""
Q_REPO = """// q:repo
MATCH (r:Repo {id: $repo})
RETURN r,
       COUNT { MATCH (c:Commit {repo: $repo}) } AS commits,
       COUNT { MATCH (d:Decision {repo: $repo}) } AS decisions
"""
Q_ENTITY = """// q:entity
MATCH (e:{label} {{id: $id, repo: $repo}}) RETURN e
"""
Q_SEARCH = """// q:search
CALL db.index.fulltext.queryNodes('entity_search', $q) YIELD node, score
WHERE node.repo = $repo
RETURN node, score ORDER BY score DESC LIMIT $limit
"""


def native(value):
    """Neo4j temporal values to Python ones; everything else unchanged."""
    return value.to_native() if hasattr(value, "to_native") else value


def id_kind(entity_id: str) -> str | None:
    """ "psf/requests#fn:..." -> "fn"; None for anything that is not a code entity id."""
    if "#" not in entity_id:
        return None
    kind = entity_id.split("#", 1)[1].split(":", 1)[0]
    return kind if kind in LABEL_BY_KIND else None


def entity(node: dict) -> m.Entity:
    kind = id_kind(node["id"]) or "file"
    path = node.get("path") or node.get("file_path")
    name = node.get("name") or (path.rsplit("/", 1)[-1] if path else node["id"])
    qualified = node.get("qualified_name") or name
    return m.Entity(
        id=node["id"],
        kind=API_KIND[kind],
        name=name,
        qualified_name=qualified,
        path=None if kind == "mod" else path,
    )


def _repo(row: dict) -> m.Repo:
    r = row["r"]
    status = r.get("status") or "READY"
    stage = r.get("stage") if r.get("stage") in m.STAGES else None
    progress = r.get("progress_pct")
    return m.Repo(
        id=r["id"],
        status=status,
        stage=stage,
        progress_pct=progress if progress is not None else (100 if status == "READY" else 0),
        partial=bool(r.get("partial", False)),
        error=r.get("error"),
        last_synced_at=native(r.get("last_synced_at")),
        commits_count=row["commits"],
        decisions_count=row["decisions"],
    )


def repos(run: Run) -> list[m.Repo]:
    return [_repo(row) for row in run(Q_REPOS, {})]


def repo(run: Run, repo_id: str) -> m.Repo | None:
    rows = run(Q_REPO, {"repo": repo_id})
    return _repo(rows[0]) if rows else None


def get_entity(run: Run, repo_id: str, entity_id: str) -> m.Entity | None:
    kind = id_kind(entity_id)
    if kind is None or not entity_id.startswith(f"{repo_id}#"):
        return None
    rows = run(Q_ENTITY.format(label=LABEL_BY_KIND[kind]), {"repo": repo_id, "id": entity_id})
    return entity(rows[0]["e"]) if rows else None


def lucene_query(text: str) -> str:
    """Words and dotted names from free text, OR-ed; drops every Lucene operator character."""
    words = (w.strip(".") for w in re.findall(r"[\w.]+", text))
    return " ".join(w for w in words if w)


def scale(score: float) -> float:
    """Lucene scores are unbounded; s / (1 + s) keeps their order and maps them into 0..1."""
    return round(score / (1.0 + score), 2) if score > 0 else 0.0


def search(run: Run, repo_id: str, text: str, limit: int = SEARCH_LIMIT) -> list[m.EntityMatch]:
    q = lucene_query(text)
    if not q:
        return []
    rows = run(Q_SEARCH, {"repo": repo_id, "q": q, "limit": limit})
    return [
        m.EntityMatch(**entity(r["node"]).model_dump(), score=scale(r["score"]))
        for r in rows
        if id_kind(r["node"].get("id", ""))
    ]


# ---------- overview ----------

Q_OVERVIEW_COUNTS = """// q:overview_counts
RETURN COUNT { MATCH (d:Decision {repo: $repo}) } AS decisions,
       COUNT { MATCH (d:Decision {repo: $repo}) WHERE d.status = 'SUPERSEDED' } AS superseded,
       COUNT { MATCH (:Decision {repo: $repo})-[:SUPPORTED_BY]->(:Evidence {repo: $repo}) }
         AS evidence_links,
       COUNT { MATCH (e {repo: $repo}) WHERE e:File OR e:Class OR e:Function OR e:ConfigKey }
         AS entities
"""
# Schema query 5d.
Q_HOTSPOTS = """// q:hotspots
MATCH (e {repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})
      <-[:SUPERSEDES {kind: 'reverses'}]-(:Decision {repo: $repo})
RETURN e, count(DISTINCT d) AS reversals ORDER BY reversals DESC LIMIT 10
"""
Q_DECIDED = """// q:decided
MATCH (e {repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})
WHERE e:File OR e:Class OR e:Function OR e:ConfigKey
WITH e, d ORDER BY d.decided_at DESC
WITH e, collect(d)[0] AS latest, count(d) AS n
RETURN e, latest.summary AS summary, n
ORDER BY 'File' IN labels(e), n DESC, e.id LIMIT 8
"""
Q_UNEXPLAINED = """// q:unexplained
MATCH (:Commit {repo: $repo})-[:MODIFIES]->(e {repo: $repo})
WHERE (e:Class OR e:Function OR e:ConfigKey)
  AND NOT EXISTS { MATCH (e)<-[:AFFECTS]-(:Decision {repo: $repo}) }
RETURN DISTINCT e ORDER BY e.id LIMIT 1
"""
EXAMPLE_LIMIT = 4
SHOWCASE_ANSWERED = 3
NO_DECISION_SUMMARY = "No recorded decision. WhyCode shows what changed it instead of guessing."


def question_for(e: m.Entity, value: str | None = None) -> str:
    """A plain question about an entity, built from its name only."""
    if e.kind == "config":
        return f"Why is {e.qualified_name} set to {value}?" if value else f"Why is {e.name} set?"
    if e.kind == "file":
        return f"Why is {e.name} built this way?"
    return f"Why does {e.qualified_name} work this way?"


def overview(run: Run, repo_id: str) -> m.Overview:
    params = {"repo": repo_id}
    counts = run(Q_OVERVIEW_COUNTS, params)[0]
    hotspots = [
        m.Hotspot(entity=entity(r["e"]), reversals=r["reversals"]) for r in run(Q_HOTSPOTS, params)
    ]
    decided = run(Q_DECIDED, params)
    examples, showcase = [], []
    for r in decided:
        e = entity(r["e"])
        question = question_for(e, r["e"].get("value"))
        if len(examples) < EXAMPLE_LIMIT:
            examples.append(m.ExampleQuestion(entity=e, question=question))
        if len(showcase) < SHOWCASE_ANSWERED:
            showcase.append(
                m.ShowcaseItem(
                    outcome="answered", entity=e, question=question, summary=r["summary"]
                )
            )
    for r in run(Q_UNEXPLAINED, params):
        e = entity(r["e"])
        showcase.append(
            m.ShowcaseItem(
                outcome="refused",
                entity=e,
                question=question_for(e, r["e"].get("value")),
                summary=NO_DECISION_SUMMARY,
            )
        )
    return m.Overview(
        counts=m.OverviewCounts(**counts),
        hotspots=hotspots,
        example_questions=examples,
        showcase=showcase,
    )


# ---------- explorer ----------

Q_EXPLORER_NODES = """// q:explorer_nodes
MATCH (n {repo: $repo}) WHERE n:File OR n:Class OR n:Function OR n:ConfigKey
OPTIONAL MATCH (n)<-[:AFFECTS]-(d:Decision {repo: $repo})
RETURN n, count(d) AS decisions, count(CASE WHEN d.status = 'SUPERSEDED' THEN 1 END) AS superseded
"""
Q_EXPLORER_EDGES = """// q:explorer_edges
MATCH (a {repo: $repo})-[:CONTAINS]->(b {repo: $repo})
WHERE (a:File OR a:Class OR a:Function) AND (b:Class OR b:Function)
RETURN a.id AS parent, b.id AS child
"""


def _root(paths: list[str]) -> str:
    """The directory every file is under, with a trailing slash ("src/requests/"); "" if none."""
    dirs = [p.split("/")[:-1] for p in paths]
    if not dirs:
        return ""
    common = []
    for parts in zip(*dirs, strict=False):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return "/".join(common) + "/" if common else ""


def explorer(run: Run, repo_id: str) -> m.Explorer:
    params = {"repo": repo_id}
    items: dict[str, m.ExplorerItem] = {}
    order: dict[str, tuple] = {}
    for r in run(Q_EXPLORER_NODES, params):
        e = entity(r["n"])
        items[e.id] = m.ExplorerItem(
            entity=e, decision_count=r["decisions"], has_superseded=r["superseded"] > 0
        )
        order[e.id] = (r["n"].get("start_line") or 0, e.qualified_name)
    for r in sorted(run(Q_EXPLORER_EDGES, params), key=lambda r: order.get(r["child"], ())):
        parent, child = items.get(r["parent"]), items.get(r["child"])
        if parent is not None and child is not None:
            parent.children.append(child)
    files = sorted(
        (i for i in items.values() if i.entity.kind == "file"), key=lambda i: i.entity.path or ""
    )
    config = sorted(
        (i for i in items.values() if i.entity.kind == "config"), key=lambda i: i.entity.name
    )
    return m.Explorer(
        root=_root([i.entity.path for i in files if i.entity.path]), files=files, config_keys=config
    )
