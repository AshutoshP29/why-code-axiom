from tests.api_fakes import (
    CFG,
    CLS,
    FILE,
    FN,
    NODES,
    REPO,
    UNEXPLAINED,
    FakeGraph,
    assert_repo_filtered,
    client,
)
from whycode.api import reads
from whycode.api.models import Entity

COUNTS = [{"decisions": 2, "superseded": 1, "evidence_links": 5, "entities": 40}]


def overview_graph(**kw):
    return FakeGraph(
        overview_counts=COUNTS,
        decided=[
            {"e": NODES[FN], "summary": "Replace chardet with charset_normalizer", "n": 2},
            {"e": NODES[CFG], "summary": "Retries are off by default", "n": 1},
            {"e": NODES[FILE], "summary": "Whole-file decision", "n": 1},
        ],
        unexplained=[{"e": NODES[UNEXPLAINED]}],
        **kw,
    )


def test_overview_counts_examples_and_showcase():
    graph = overview_graph()
    res = client(graph).get("/api/overview", params={"repo": REPO})
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == COUNTS[0]
    assert body["hotspots"] == []  # no reversals recorded yet
    assert [q["question"] for q in body["example_questions"]] == [
        "Why does Response.apparent_encoding work this way?",
        "Why is DEFAULT_RETRIES set to 0?",
        "Why is models.py built this way?",
    ]
    assert [(s["outcome"], s["entity"]["id"], s["summary"]) for s in body["showcase"]] == [
        ("answered", FN, "Replace chardet with charset_normalizer"),
        ("answered", CFG, "Retries are off by default"),
        ("answered", FILE, "Whole-file decision"),
        ("refused", UNEXPLAINED, reads.NO_DECISION_SUMMARY),
    ]
    assert_repo_filtered(graph)


def test_overview_hotspots_come_from_query_5d():
    graph = overview_graph(hotspots=[{"e": NODES[FN], "reversals": 3}])
    body = client(graph).get("/api/overview", params={"repo": REPO}).json()
    assert body["hotspots"] == [
        {
            "entity": {
                "id": FN,
                "kind": "function",
                "name": "apparent_encoding",
                "qualified_name": "Response.apparent_encoding",
                "path": "src/requests/models.py",
            },
            "reversals": 3,
        }
    ]
    hotspot_query = next(c for c, _ in graph.calls if "q:hotspots" in c)
    assert "SUPERSEDES {kind: 'reverses'}" in hotspot_query


def test_overview_of_an_empty_repo():
    graph = FakeGraph(overview_counts=[dict.fromkeys(COUNTS[0], 0)])
    body = client(graph).get("/api/overview", params={"repo": REPO}).json()
    assert body["example_questions"] == body["showcase"] == body["hotspots"] == []


def test_question_for_config_without_value():
    e = Entity(id=CFG, kind="config", name="X", qualified_name="f.x", path=None)
    assert reads.question_for(e) == "Why is X set?"


def explorer_graph():
    method = {**NODES[FN], "start_line": 900}
    helper = {
        "id": f"{REPO}#fn:src/requests/models.py::Response.json",
        "repo": REPO,
        "name": "json",
        "qualified_name": "Response.json",
        "path": "src/requests/models.py",
        "start_line": 950,
    }
    api_file = {"id": f"{REPO}#file:src/requests/api.py", "path": "src/requests/api.py"}
    return FakeGraph(
        explorer_nodes=[
            {"n": api_file, "decisions": 0, "superseded": 0},
            {"n": NODES[FILE], "decisions": 1, "superseded": 0},
            {"n": {**NODES[CLS], "start_line": 600}, "decisions": 0, "superseded": 0},
            {"n": helper, "decisions": 0, "superseded": 0},
            {"n": method, "decisions": 2, "superseded": 1},
            {"n": NODES[CFG], "decisions": 1, "superseded": 0},
        ],
        explorer_edges=[
            {"parent": CLS, "child": helper["id"]},
            {"parent": FILE, "child": CLS},
            {"parent": CLS, "child": FN},
            {"parent": FILE, "child": f"{REPO}#fn:gone.py::x"},  # dangling: ignored
        ],
    )


def test_explorer_tree_file_class_method():
    graph = explorer_graph()
    res = client(graph).get("/api/explorer", params={"repo": REPO})
    assert res.status_code == 200
    body = res.json()
    assert body["root"] == "src/requests/"
    assert [f["entity"]["path"] for f in body["files"]] == [
        "src/requests/api.py",
        "src/requests/models.py",
    ]
    models = body["files"][1]
    assert models["decision_count"] == 1
    (cls,) = models["children"]
    assert cls["entity"]["kind"] == "class"
    assert [
        (c["entity"]["name"], c["decision_count"], c["has_superseded"]) for c in cls["children"]
    ] == [
        ("apparent_encoding", 2, True),  # line 900 before line 950
        ("json", 0, False),
    ]
    assert [c["entity"]["id"] for c in body["config_keys"]] == [CFG]
    assert_repo_filtered(graph)


def test_explorer_root_edge_cases():
    assert reads._root([]) == ""
    assert reads._root(["setup.py", "src/a.py"]) == ""
    assert reads._root(["src/a/x.py", "src/b/y.py"]) == "src/"
