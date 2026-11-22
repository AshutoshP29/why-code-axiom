"""GET /api/graph: a repo's graph as nodes and links, for the Graph screen.

The scope is picked in this order:

- focus: the node asked for and everything within two hops of it, nearest first;
- all: the whole repo graph, when it has at most `limit` nodes (a small sample repo);
- decisions: every decision with the code it AFFECTS, the pull request it was DECIDED_IN, the
  people who PROPOSED and APPROVED it and the decisions it SUPERSEDES, newest first (psf/requests
  has about 12,000 nodes, so it gets this).

Each is cut to `limit` nodes; `truncated` says the screen shows less than there is. Read only:
nothing here writes to the graph. Every query filters on `repo` (schema rule 3).
"""

from datetime import date, datetime

from fastapi import HTTPException

from whycode.api import models as m
from whycode.api.reads import native
from whycode.graph.queries import Run

DEFAULT_LIMIT = 600
MAX_LIMIT = 1500
HOPS = 2

KIND_BY_LABEL: dict[str, m.GraphViewKind] = {
    "File": "file",
    "Class": "class",
    "Function": "function",
    "ConfigKey": "config",
    "Module": "module",
    "Decision": "decision",
    "Evidence": "evidence",
    "PullRequest": "pull_request",
    "Issue": "issue",
    "Commit": "commit",
    "Person": "person",
}
DECISION_LINKS = "AFFECTS|DECIDED_IN|PROPOSED_BY|APPROVED_BY|SUPERSEDES"
EVIDENCE_SOURCE = {
    "pr_body": "PR description",
    "pr_comment": "PR comment",
    "review_comment": "Review comment",
    "issue_comment": "Issue comment",
    "commit_msg": "Commit message",
    "doc": "Doc",
}


def _shown(var: str) -> str:
    return "(" + " OR ".join(f"{var}:{label}" for label in KIND_BY_LABEL) + ")"


def _fields(var: str) -> str:
    """Only what the labels need: an Evidence node also holds a 384-number embedding."""
    return (
        f"{var} {{.id, .name, .qualified_name, .path, .summary, .status, .decided_at, .number,"
        f" .title, .message, .sha, .date, .login, .source_type, .author,"
        f" text: left({var}.text, 200), labels: labels({var})}}"
    )


Q_TOTALS = f"""// q:graph_totals
MATCH (n {{repo: $repo}}) WHERE {_shown("n")}
WITH count(n) AS nodes
RETURN nodes, COUNT {{ MATCH (a {{repo: $repo}})-->(b {{repo: $repo}}) }} AS edges
"""
Q_ALL = f"""// q:graph_all
MATCH (n {{repo: $repo}}) WHERE {_shown("n")}
RETURN {_fields("n")} AS n
ORDER BY n.id LIMIT $limit
"""
Q_DECISIONS = f"""// q:graph_decisions
MATCH (d:Decision {{repo: $repo}})
OPTIONAL MATCH (d)-[:{DECISION_LINKS}]->(x {{repo: $repo}})
WITH d, collect(DISTINCT {_fields("x")}) AS around
RETURN {_fields("d")} AS d, around
ORDER BY d.decided_at DESC, d.id
"""
Q_FOCUS = f"""// q:graph_focus
MATCH (n {{id: $focus, repo: $repo}}) WHERE {_shown("n")}
RETURN {_fields("n")} AS n
"""
Q_NEIGHBOURS = f"""// q:graph_neighbours
MATCH (a {{repo: $repo}})--(n {{repo: $repo}})
WHERE a.id IN $ids AND NOT n.id IN $seen AND {_shown("n")}
RETURN DISTINCT {_fields("n")} AS n
ORDER BY n.id LIMIT $limit
"""
Q_EDGES = """// q:graph_edges
MATCH (a {repo: $repo})-[r]->(b {repo: $repo})
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS source, b.id AS target, type(r) AS type
"""


def _cut(text: str | None, size: int) -> str:
    """One line of at most `size` characters, with an ellipsis when something was cut."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= size else flat[: size - 1].rstrip() + "…"


def _day(value) -> str | None:
    value = native(value)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10] if value else None


def _join(*parts: str | None) -> str | None:
    return ", ".join(p for p in parts if p) or None


def _describe(kind: m.GraphViewKind, n: dict) -> tuple[str, str | None]:
    """The node's label and its short second line."""
    # The id without repo and kind ("fn:a.py::f" -> "a.py::f"), for a node missing its fields.
    key = n["id"].split("#", 1)[-1].split(":", 1)[-1]
    if kind in ("function", "class", "config"):
        return n.get("qualified_name") or n.get("name") or key, n.get("path")
    if kind == "file":
        path = n.get("path")
        return n.get("name") or (path.rsplit("/", 1)[-1] if path else key), path
    if kind == "module":
        return n.get("name") or key, None
    if kind == "decision":
        status = (n.get("status") or "").lower()
        return _cut(n.get("summary") or key, 80), _join(
            _day(n.get("decided_at")), status if status not in ("", "active") else None
        )
    if kind == "evidence":
        source = EVIDENCE_SOURCE.get(n.get("source_type") or "", "Evidence")
        return _cut(n.get("text") or key, 60), _join(source, n.get("author"), _day(n.get("date")))
    if kind in ("pull_request", "issue"):
        prefix = "PR" if kind == "pull_request" else "Issue"
        number = n.get("number")
        label = f"{prefix} #{number}" if number is not None else key
        return label, _cut(n.get("title"), 80) or None
    if kind == "commit":
        sha = (n.get("sha") or key)[:7]
        lines = (n.get("message") or "").strip().splitlines()
        return (_cut(lines[0], 60) if lines else sha), _join(sha, _day(n.get("date")))
    return n.get("login") or key, n.get("name") if n.get("name") != n.get("login") else None


def node(row: dict) -> m.GraphViewNode | None:
    """A graph view node from a projected row; None for a label the screen does not draw."""
    kind = next((KIND_BY_LABEL[x] for x in row.get("labels") or [] if x in KIND_BY_LABEL), None)
    if kind is None:
        return None
    label, detail = _describe(kind, row)
    return m.GraphViewNode(id=row["id"], kind=kind, label=label, detail=detail)


def _focus(run: Run, repo: str, focus: str, limit: int) -> tuple[list[dict], bool]:
    """The focus node, then each hop out from it, until `limit`; True when some were left out."""
    found = run(Q_FOCUS, {"repo": repo, "focus": focus})
    if not found:
        raise HTTPException(404, f"{focus} is not in the graph for {repo}")
    rows = [found[0]["n"]]
    seen = [rows[0]["id"]]
    frontier, cut = seen, False
    for _ in range(HOPS):
        room = max(0, limit - len(rows))
        # One more than there is room for, to tell "exactly full" from "cut".
        more = [
            r["n"]
            for r in run(
                Q_NEIGHBOURS, {"repo": repo, "ids": frontier, "seen": seen, "limit": room + 1}
            )
        ]
        cut = cut or len(more) > room
        more = more[:room]
        if not more:
            break
        rows += more
        frontier = [r["id"] for r in more]
        seen = seen + frontier
    return rows, cut


def _decisions(run: Run, repo: str, limit: int) -> list[dict]:
    """Each decision followed by what it links to, newest decision first, up to `limit`."""
    rows: list[dict] = []
    seen: set[str] = set()
    for row in run(Q_DECISIONS, {"repo": repo}):
        for n in (row["d"], *row["around"]):
            if n["id"] in seen:
                continue
            if len(rows) == limit:
                return rows
            seen.add(n["id"])
            rows.append(n)
    return rows


def _edges(run: Run, repo: str, ids: list[str]) -> list[m.GraphViewEdge]:
    out: list[m.GraphViewEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for r in run(Q_EDGES, {"repo": repo, "ids": ids}):
        key = (r["source"], r["target"], r["type"])
        if key not in seen:
            seen.add(key)
            out.append(m.GraphViewEdge(source=r["source"], target=r["target"], type=r["type"]))
    return out


def view(run: Run, repo: str, focus: str | None = None, limit: int = DEFAULT_LIMIT) -> m.GraphView:
    totals = run(Q_TOTALS, {"repo": repo})[0]
    total_nodes, total_edges = totals["nodes"], totals["edges"]
    scope: m.GraphScope
    cut = False
    if focus:
        scope = "focus"
        rows, cut = _focus(run, repo, focus, limit)
    elif total_nodes <= limit:
        scope = "all"
        rows = [r["n"] for r in run(Q_ALL, {"repo": repo, "limit": limit})]
    else:
        scope = "decisions"
        rows = _decisions(run, repo, limit)
        if not rows:  # read, but no decisions yet: the first nodes of the whole graph instead
            scope = "all"
            rows = [r["n"] for r in run(Q_ALL, {"repo": repo, "limit": limit})]
    nodes: dict[str, m.GraphViewNode] = {}
    for row in rows:
        if (n := node(row)) is not None and n.id not in nodes:
            nodes[n.id] = n
    ids = list(nodes)
    return m.GraphView(
        nodes=list(nodes.values()),
        edges=_edges(run, repo, ids) if ids else [],
        scope=scope,
        # A focus cut is known from its hops; any other scope shows less when nodes are missing.
        truncated=cut if scope == "focus" else len(nodes) < total_nodes,
        total_nodes=total_nodes,
        total_edges=total_edges,
    )
