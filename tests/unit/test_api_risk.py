"""GET /api/risk: orphaned decisions and code nobody explained."""

import time
from datetime import UTC, datetime

import pytest

from tests.api_fakes import (
    CFG,
    CLS,
    FN,
    REPO,
    UNEXPLAINED,
    FakeGraph,
    assert_repo_filtered,
    client,
)
from whycode.api import auth, risk

GONE = {"login": "ashb", "active": False, "last_seen": datetime(2021, 7, 6, tzinfo=UTC)}
ALSO_GONE = {
    "login": "maintainer_b",
    "active": False,
    "last_seen": datetime(2019, 4, 1, tzinfo=UTC),
}
NO_DATE = {"login": "driveby", "active": False, "last_seen": None}
DECIDED = datetime(2021, 7, 6, tzinfo=UTC)
CHANGED = datetime(2024, 3, 9, tzinfo=UTC)


def orphan(node_id: str, decisions: int, when: datetime, proposers=None, approvers=None) -> dict:
    from tests.api_fakes import NODES

    return {
        "e": NODES[node_id],
        "decisions": decisions,
        "last_decided_at": when,
        "proposers": [GONE] if proposers is None else proposers,
        "approvers": [ALSO_GONE] if approvers is None else approvers,
    }


def unexplained(node_id: str, commits: int, authors: int, when=CHANGED) -> dict:
    from tests.api_fakes import NODES

    return {"e": NODES[node_id], "commits": commits, "authors": authors, "last_changed_at": when}


def graph(orphaned=None, rows=None, counts=None, total=None) -> FakeGraph:
    return FakeGraph(
        risk_orphaned=orphaned if orphaned is not None else [orphan(FN, 2, DECIDED)],
        risk_unexplained=rows if rows is not None else [unexplained(UNEXPLAINED, 12, 4)],
        risk_counts=counts or [{"code_with_decisions": 31, "changed_without_reason": 87}],
        risk_orphaned_count=total or [{"orphaned": 5}],
    )


def get(g: FakeGraph, repo: str = REPO):
    return client(g).get("/api/risk", params={"repo": repo})


def test_both_tables_and_the_repo_wide_counts():
    g = graph()
    res = get(g)
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == {
        "code_with_decisions": 31,
        "orphaned": 5,  # the whole repo, not the rows returned
        "changed_without_reason": 87,
    }
    (o,) = body["orphaned"]
    assert o["entity"]["id"] == FN and o["decisions"] == 2
    assert o["last_decided_at"].startswith("2021-07-06")
    assert [(p["login"], p["role"], p["active"]) for p in o["people"]] == [
        ("ashb", "Proposed the decision", False),
        ("maintainer_b", "Approved it", False),
    ]
    assert o["people"][0]["url"] == "https://github.com/ashb"
    (u,) = body["unexplained"]
    assert u["entity"]["id"] == UNEXPLAINED
    assert (u["commits"], u["authors"]) == (12, 4)
    assert u["last_changed_at"].startswith("2024-03-09")
    assert_repo_filtered(g)


def test_every_query_asks_for_one_repo_and_the_top_twenty():
    g = graph()
    get(g)
    assert set(g.tags()) >= {"risk_orphaned", "risk_unexplained", "risk_counts"}
    for cypher, params in g.calls:
        if "// q:risk_orphaned\n" in cypher or "// q:risk_unexplained" in cypher:
            assert params["limit"] == risk.TOP == 20
            assert "LIMIT $limit" in cypher


def test_the_in_force_rule_and_the_all_inactive_rule_are_in_the_cypher():
    # Copied from query 5a: a decision reversed or replaced by a newer one no longer governs.
    assert "SUPERSEDES" in risk.Q_ORPHANED and "'reverses', 'replaces'" in risk.Q_ORPHANED
    assert "coalesce(p.active, false) = false" in risk.Q_ORPHANED
    assert "size(proposers + approvers) > 0" in risk.Q_ORPHANED  # nobody known is not "orphaned"
    assert "ORDER BY decisions DESC, last_decided_at DESC" in risk.Q_ORPHANED
    assert "ORDER BY commits DESC" in risk.Q_UNEXPLAINED
    # The counting query must not carry the row limit, so counts cover the whole repo.
    assert "LIMIT" not in risk.Q_COUNTS and "LIMIT" not in risk.Q_ORPHANED_COUNT


def test_a_recent_commit_counts_as_still_around():
    # psf/requests: the current maintainer was last seen in a 2016 PR, so `active` is false, but
    # he committed in 2026. A commit within the `active` window keeps a person off the orphan list.
    assert "-[:AUTHORED]->(c:Commit {repo: $repo}) WHERE c.date >= $since" in risk.Q_ORPHANED
    assert "$since" in risk.Q_ORPHANED_COUNT  # the count follows the same rule
    now = datetime(2026, 11, 22, tzinfo=UTC)
    g = graph()
    risk.knowledge_risk(g, REPO, now=now)
    for cypher, params in g.calls:
        if "// q:risk_orphaned" in cypher:
            assert params["since"] == now - risk.ACTIVE_WITHIN
            assert params["since"].date().isoformat() == "2025-05-23"  # about 18 months back


def test_the_window_is_the_one_that_sets_active():
    from whycode.graph.build import ACTIVE_WITHIN

    assert risk.ACTIVE_WITHIN == ACTIVE_WITHIN


def test_rows_keep_the_order_the_graph_sorted_them_in():
    rows = [orphan(CFG, 4, DECIDED), orphan(CLS, 2, CHANGED), orphan(FN, 2, DECIDED)]
    body = get(graph(orphaned=rows)).json()
    assert [o["entity"]["id"] for o in body["orphaned"]] == [CFG, CLS, FN]
    many = [unexplained(UNEXPLAINED, 9, 2), unexplained(FN, 3, 1)]
    assert [u["commits"] for u in get(graph(rows=many)).json()["unexplained"]] == [9, 3]


def test_a_person_seen_more_recently_is_listed_first():
    row = orphan(FN, 1, DECIDED, proposers=[ALSO_GONE, NO_DATE], approvers=[GONE])
    body = get(graph(orphaned=[row])).json()
    assert [p["login"] for p in body["orphaned"][0]["people"]] == [
        "ashb",  # 2021
        "maintainer_b",  # 2019
        "driveby",  # never seen
    ]


def test_someone_in_both_roles_is_listed_once_as_the_proposer():
    row = orphan(FN, 1, DECIDED, proposers=[GONE], approvers=[GONE])
    people = get(graph(orphaned=[row])).json()["orphaned"][0]["people"]
    assert [(p["login"], p["role"]) for p in people] == [("ashb", "Proposed the decision")]


def test_code_with_no_recorded_change_date_is_still_listed():
    body = get(graph(rows=[unexplained(UNEXPLAINED, 2, 1, when=None)])).json()
    assert body["unexplained"][0]["last_changed_at"] is None


def test_nothing_at_risk_is_an_empty_answer_not_an_error():
    g = graph(
        orphaned=[],
        rows=[],
        counts=[{"code_with_decisions": 0, "changed_without_reason": 0}],
        total=[{"orphaned": 0}],
    )
    body = get(g).json()
    assert body["orphaned"] == [] and body["unexplained"] == []
    assert body["counts"]["orphaned"] == 0


def test_a_repo_that_is_not_in_the_graph_is_a_404():
    res = get(graph(), repo="other/repo")
    assert res.status_code == 404
    assert res.json()["detail"] == "other/repo is not in the graph"


def test_a_repo_that_is_not_owner_name_is_a_400():
    assert get(graph(), repo="nonsense").status_code == 400


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv(auth.AUTH_ENV, "github")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")


def test_signing_in_is_needed_when_it_is_switched_on(auth_on):
    c = client(graph())
    assert c.get("/api/risk", params={"repo": REPO}).status_code == 401
    user = {"login": "octocat", "name": None, "avatar_url": None}
    token = auth.sign({"user": user, "exp": time.time() + 60}, "test-session-secret")
    cookie = {auth.SESSION_COOKIE: token}
    assert c.get("/api/risk", params={"repo": REPO}, cookies=cookie).status_code == 200
