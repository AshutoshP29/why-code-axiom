from datetime import UTC, datetime

from tests.api_fakes import (
    COMMIT,
    DEC,
    DECISION_NODE,
    FN,
    GH,
    PR,
    PR_NODE,
    REPO,
    FakeGraph,
    assert_repo_filtered,
    client,
)

OLD = f"{REPO}#dec:old"
OLD_NODE = {
    **DECISION_NODE,
    "id": OLD,
    "summary": "Use chardet",
    "decided_at": datetime(2012, 3, 1, tzinfo=UTC),
    "status": "SUPERSEDED",
    "evidence_kind": "INFERRED",
}
DECISIONS = [
    {
        "d": OLD_NODE,
        "supersedes": [{"id": None, "kind": None}],
        "proposers": [],
        "approvers": [],
        "sources": [],
    },
    {
        "d": DECISION_NODE,
        "supersedes": [{"id": OLD, "kind": "replaces"}],
        "proposers": ["ashb"],
        "approvers": ["nateprewitt", "sigmavirus24"],
        "sources": [PR_NODE],
    },
]
OLD_COMMIT = {
    "id": f"{REPO}#commit:aaa",
    "sha": "aaaaaaaaaaaa",
    "message": "Add chardet",
    "date": datetime(2012, 3, 1, tzinfo=UTC),
}
MERGE_COMMIT = {"id": f"{REPO}#commit:bbb", "sha": "bbbbbbbbbbbb", "url": f"{GH}/commit/bbb"}
COMMITS = [
    {"c": COMMIT, "merged": [], "decisions": [DEC]},
    {"c": MERGE_COMMIT, "merged": [datetime(2021, 7, 9, tzinfo=UTC)], "decisions": []},
    {"c": OLD_COMMIT, "merged": [None], "decisions": []},
    {"c": {"id": "x", "sha": "cccc"}, "merged": [], "decisions": []},  # no date at all
]


def lineage(params):
    graph = FakeGraph(lineage_decisions=DECISIONS, lineage_commits=COMMITS)
    res = client(graph).get("/api/lineage", params={"repo": REPO, "entity_id": FN, **params})
    return graph, res


def test_full_lineage_oldest_first():
    graph, res = lineage({})
    assert res.status_code == 200
    body = res.json()
    assert body["entity"]["id"] == FN
    assert body["as_of"] is None
    assert body["as_of_years"] == [2012, 2021]
    assert [(d["id"], d["status"], d["supersedes"]) for d in body["decisions"]] == [
        (OLD, "SUPERSEDED", []),
        (DEC, "ACTIVE", [{"decision_id": OLD, "kind": "replaces"}]),
    ]
    current = body["decisions"][1]
    assert (current["proposed_by"], current["reviewed_by"], current["approved_by"]) == (
        "ashb",
        "nateprewitt",
        ["nateprewitt", "sigmavirus24"],
    )
    assert current["source"] == {"id": PR, "label": "PR #5797", "url": f"{GH}/pull/5797"}
    assert body["decisions"][0]["source"]["label"] == "Decision"
    assert [(c["sha"], c["message"], c["date"], c["decision_id"]) for c in body["commits"]] == [
        ("aaaaaaaaaaaa", "Add chardet", "2012-03-01T00:00:00Z", None),
        ("0123456789abcdef", "Switch to charset_normalizer", "2021-07-06T00:00:00Z", DEC),
        ("bbbbbbbbbbbb", "", "2021-07-09T00:00:00Z", None),  # dated by its PR's merge
    ]
    assert body["commits"][0]["url"] == f"{GH}/commit/aaaaaaaaaaaa"
    assert body["commit_total"] == 4
    assert_repo_filtered(graph)
    assert all(":Function" in c for c, _ in graph.calls if "lineage" in c)


def test_as_of_keeps_only_what_existed_then():
    _, res = lineage({"as_of": "2016-12-31"})
    body = res.json()
    assert body["as_of"] == "2016-12-31"
    assert [d["id"] for d in body["decisions"]] == [OLD]
    assert [c["sha"] for c in body["commits"]] == ["aaaaaaaaaaaa"]
    assert body["as_of_years"] == [2012, 2021]  # always from the full history
    assert body["commit_total"] == 4


def test_as_of_is_inclusive_of_the_whole_day():
    _, res = lineage({"as_of": "2021-07-06"})
    body = res.json()
    assert [d["id"] for d in body["decisions"]] == [OLD, DEC]
    assert [c["sha"] for c in body["commits"]] == ["aaaaaaaaaaaa", "0123456789abcdef"]


def test_bad_as_of_is_422_and_unknown_entity_404():
    _, res = lineage({"as_of": "last summer"})
    assert res.status_code == 422
    res = client(FakeGraph()).get(
        "/api/lineage", params={"repo": REPO, "entity_id": f"{REPO}#fn:a.py::nope"}
    )
    assert res.status_code == 404


def test_issue_and_other_sources():
    from whycode.api.lineage import _source

    issue = {"id": f"{REPO}#issue:812", "number": 812}
    assert _source(issue, "d", REPO).model_dump() == {
        "id": f"{REPO}#issue:812",
        "label": "Issue #812",
        "url": GH,
    }
    commit = {"id": f"{REPO}#commit:abc", "url": f"{GH}/commit/abc"}
    assert _source(commit, "d", REPO).label == "commit:abc"
