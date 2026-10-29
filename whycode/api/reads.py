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
