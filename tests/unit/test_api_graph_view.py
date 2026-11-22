"""GET /api/graph: which nodes each scope returns, the cut at `limit`, labels, and the rules
every endpoint keeps (repo filter, read only, sign-in)."""

import re
from datetime import UTC, datetime

import pytest

from tests.api_fakes import CLS, DEC, FILE, FN, PR, REPO, FakeGraph, assert_repo_filtered, client
from whycode.api import auth, graph_view

PERSON = f"{REPO}#user:ashb"
COMMIT = f"{REPO}#commit:0123456789abcdef"
EV = f"{REPO}#ev:pr:5797:body"
ISSUE = f"{REPO}#issue:812"
OLD = f"{REPO}#dec:old"
MODELS = "src/requests/models.py"


def row(node_id: str, *labels: str, **props) -> dict:
    """A node as the queries project it: its fields plus its labels."""
    return {"id": node_id, "labels": list(labels), **props}


ROWS = {
    r["id"]: r
    for r in (
        row(FILE, "File", name="models.py", path=MODELS),
        row(CLS, "Class", name="Response", qualified_name="Response", path=MODELS),
        row(
            FN,
            "Function",
            name="apparent_encoding",
            qualified_name="Response.apparent_encoding",
            path=MODELS,
        ),
        row(
            DEC,
            "Decision",
            summary="Replace chardet with charset_normalizer",
            status="ACTIVE",
            decided_at=datetime(2021, 7, 6, tzinfo=UTC),
        ),
        row(
            OLD,
            "Decision",
            summary="Use chardet",
            status="SUPERSEDED",
            decided_at=datetime(2014, 1, 2, tzinfo=UTC),
        ),
        row(PR, "PullRequest", number=5797, title="Switch to charset_normalizer"),
        row(PERSON, "Person", login="ashb", name="Ash Berlin-Taylor"),
        row(
            COMMIT,
            "Commit",
            sha="0123456789abcdef",
            message="Switch to charset_normalizer\n\nBody",
            date=datetime(2021, 7, 6, tzinfo=UTC),
        ),
        row(
            EV,
            "Evidence",
            source_type="pr_body",
            author="ashb",
            text="By changing out this dependency\nfor one under MIT we remove all ambiguity.",
            date=datetime(2021, 4, 22, tzinfo=UTC),
        ),
        row(ISSUE, "Issue", "Incident", number=812, title="Credentials reach another host"),
    )
}
EDGES = [
    (FILE, CLS, "CONTAINS"),
    (CLS, FN, "CONTAINS"),
    (DEC, FN, "AFFECTS"),
    (DEC, PR, "DECIDED_IN"),
    (DEC, PERSON, "PROPOSED_BY"),
    (DEC, EV, "SUPPORTED_BY"),
    (DEC, OLD, "SUPERSEDES"),
    (PR, COMMIT, "CONTAINS"),
    (COMMIT, FN, "MODIFIES"),
    (PR, ISSUE, "CLOSES"),
]


def edges(p: dict) -> list[dict]:
    ids = set(p["ids"])
    return [{"source": a, "target": b, "type": t} for a, b, t in EDGES if a in ids and b in ids]


def neighbours(p: dict) -> list[dict]:
    """Undirected neighbours of $ids not in $seen, by id, as many as $limit."""
    ids, seen = set(p["ids"]), set(p["seen"])
    found = {b for a, b, _ in EDGES if a in ids} | {a for a, b, _ in EDGES if b in ids}
    return [{"n": ROWS[i]} for i in sorted(found - seen)][: p["limit"]]


def graph(total: int | None = None, **handlers) -> FakeGraph:
    defaults = {
        "graph_totals": [{"nodes": len(ROWS) if total is None else total, "edges": len(EDGES)}],
        "graph_all": lambda p: [{"n": r} for r in sorted(ROWS.values(), key=lambda r: r["id"])][
            : p["limit"]
        ],
        "graph_decisions": [
            {"d": ROWS[DEC], "around": [ROWS[FN], ROWS[PR], ROWS[PERSON], ROWS[OLD]]},
            {"d": ROWS[OLD], "around": [ROWS[FN]]},
        ],
        "graph_focus": lambda p: [{"n": ROWS[p["focus"]]}] if p["focus"] in ROWS else [],
        "graph_neighbours": neighbours,
        "graph_edges": edges,
    }
    return FakeGraph(**{**defaults, **handlers})


def get(g: FakeGraph, **params):
    return client(g).get("/api/graph", params={"repo": REPO, **params})


def test_a_small_repo_shows_its_whole_graph():
    g = graph()
    body = get(g).json()
    assert body["scope"] == "all"
    assert body["truncated"] is False
    assert {n["id"] for n in body["nodes"]} == set(ROWS)
    assert len(body["edges"]) == len(EDGES)
    assert (body["total_nodes"], body["total_edges"]) == (len(ROWS), len(EDGES))
    assert "graph_decisions" not in g.tags()


def test_each_kind_has_its_label_and_detail():
    nodes = {n["id"]: n for n in get(graph()).json()["nodes"]}
    shown = {i: (n["kind"], n["label"], n["detail"]) for i, n in nodes.items()}
    assert shown == {
        FILE: ("file", "models.py", "src/requests/models.py"),
        CLS: ("class", "Response", "src/requests/models.py"),
        FN: ("function", "Response.apparent_encoding", "src/requests/models.py"),
        DEC: ("decision", "Replace chardet with charset_normalizer", "2021-07-06"),
        OLD: ("decision", "Use chardet", "2014-01-02, superseded"),
        PR: ("pull_request", "PR #5797", "Switch to charset_normalizer"),
        PERSON: ("person", "ashb", "Ash Berlin-Taylor"),
        COMMIT: ("commit", "Switch to charset_normalizer", "0123456, 2021-07-06"),
        EV: (
            "evidence",
            "By changing out this dependency for one under MIT we remove…",
            "PR description, ashb, 2021-04-22",
        ),
        ISSUE: ("issue", "Issue #812", "Credentials reach another host"),
    }


def test_long_summaries_and_commit_lines_are_cut():
    long_dec = row(DEC, "Decision", summary="word " * 40, status="ACTIVE")
    long_commit = row(COMMIT, "Commit", sha="abcdef0123", message="x" * 90 + "\n\nbody")
    dec, commit = graph_view.node(long_dec), graph_view.node(long_commit)
    assert len(dec.label) == 80 and dec.label.endswith("…")
    assert len(commit.label) == 60 and commit.label.endswith("…")
    assert graph_view.node(row(f"{REPO}#x:1", "Chunk")) is None  # a label the screen does not draw


def test_a_big_repo_shows_its_decision_graph_newest_first():
    g = graph(total=12_000)
    body = get(g).json()
    assert body["scope"] == "decisions"
    assert body["truncated"] is True
    assert [n["id"] for n in body["nodes"]] == [DEC, FN, PR, PERSON, OLD]
    assert {(e["source"], e["target"]) for e in body["edges"]} == {
        (DEC, FN),
        (DEC, PR),
        (DEC, PERSON),
        (DEC, OLD),
    }
    assert body["total_nodes"] == 12_000
    assert "graph_all" not in g.tags()


def test_the_decision_graph_is_cut_at_the_limit():
    g = graph(total=12_000)
    body = get(g, limit=3).json()
    assert [n["id"] for n in body["nodes"]] == [DEC, FN, PR]
    assert body["truncated"] is True
    edge_ids = next(p["ids"] for c, p in g.calls if "// q:graph_edges" in c)
    assert edge_ids == [DEC, FN, PR]  # links only between the nodes shown


def test_a_big_repo_with_no_decisions_yet_shows_its_first_nodes():
    body = get(graph(total=12_000, graph_decisions=[]), limit=4).json()
    assert body["scope"] == "all"
    assert len(body["nodes"]) == 4
    assert body["truncated"] is True


def test_focus_shows_two_hops_around_a_node():
    g = graph()
    body = get(g, focus=PR).json()
    assert body["scope"] == "focus"
    assert body["truncated"] is False
    ids = [n["id"] for n in body["nodes"]]
    assert ids[0] == PR
    one_hop = {DEC, COMMIT, ISSUE}
    assert set(ids[1:4]) == one_hop  # nearest first
    assert set(ids) == {PR} | one_hop | {FN, PERSON, EV, OLD}
    assert FILE not in ids and CLS not in ids  # three hops away
    hops = [p for c, p in g.calls if "// q:graph_neighbours" in c]
    assert hops[0]["ids"] == [PR]
    assert set(hops[1]["seen"]) == {PR} | one_hop


def test_focus_is_cut_at_the_limit():
    body = get(graph(), focus=PR, limit=3).json()
    assert len(body["nodes"]) == 3
    assert body["nodes"][0]["id"] == PR
    assert body["truncated"] is True


def test_focus_that_fills_the_limit_exactly_is_not_cut():
    # PR, its 3 neighbours, their 4: eight in all.
    assert get(graph(), focus=PR, limit=8).json()["truncated"] is False


def test_unknown_focus_is_404():
    res = get(graph(), focus=f"{REPO}#fn:nope.py::gone")
    assert res.status_code == 404
    assert "is not in the graph" in res.json()["detail"]


def test_unknown_repo_is_404():
    res = client(graph()).get("/api/graph", params={"repo": "other/repo"})
    assert res.status_code == 404


@pytest.mark.parametrize(
    ("total", "params"),
    [(None, {}), (12_000, {}), (12_000, {"limit": 2}), (None, {"focus": PR})],
)
def test_every_query_filters_on_repo_and_only_reads(total, params):
    g = graph(total=total)
    assert get(g, **params).status_code == 200
    assert_repo_filtered(g)
    for cypher, _ in g.calls:
        assert not re.search(r"\b(CREATE|MERGE|SET|DELETE|REMOVE|DETACH)\b", cypher)


@pytest.mark.parametrize("limit", [0, graph_view.MAX_LIMIT + 1])
def test_limit_outside_the_range_is_refused(limit):
    assert get(graph(), limit=limit).status_code == 422


def test_needs_sign_in(monkeypatch):
    monkeypatch.setenv(auth.AUTH_ENV, "github")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")
    assert get(graph()).status_code == 401
