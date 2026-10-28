from datetime import UTC, datetime

import pytest

from tests.pipeline import FALLBACK_DECISION, LGPL, run_fixture
from whycode.extract.prompt import PROMPT_VERSION
from whycode.graph.build import build_pr_graph
from whycode.graph.queries import Answer, Refusal, current_decisions, neo4j_runner
from whycode.graph.schema import apply_schema
from whycode.graph.writer import delete_repo, repo_counts, write_batch

A, B = "test/fixture", "test/fixture-b"
NOW = datetime(2026, 10, 28, tzinfo=UTC)
DETECT = "test/fixture#fn:src/fixture/compat.py::Detector.detect"
TO_TEXT = "test/fixture#fn:lib/fixture/utils.py::to_text"


def batch_for(repo=A, **kw):
    p = run_fixture(repo, **kw)
    return build_pr_graph(
        p.store,
        p.thread,
        p.result.decisions,
        p.checks,
        index=p.index,
        prompt_version=PROMPT_VERSION,
        now=NOW,
    )


@pytest.fixture
def db(neo4j_test):
    driver, database = neo4j_test
    apply_schema(driver, database)
    for repo in (A, B):
        delete_repo(driver, database, repo)
    yield driver, database
    for repo in (A, B):
        delete_repo(driver, database, repo)


def test_written_counts_match_the_batch(db):
    driver, database = db
    batch = batch_for()
    stats = write_batch(driver, database, batch)
    by_label, rels = repo_counts(driver, database, A)
    assert by_label == {label: len(nodes) for label, nodes in batch.nodes.items()}
    assert rels == stats.relationships == batch.count()[1]


def test_writing_the_same_pr_twice_changes_nothing(db):
    driver, database = db
    batch = batch_for()
    write_batch(driver, database, batch)
    first = repo_counts(driver, database, A)
    stats = write_batch(driver, database, batch)
    assert repo_counts(driver, database, A) == first
    assert stats.decisions_replaced == 2  # the same two decisions, deleted and rewritten


def test_re_extraction_replaces_decisions_instead_of_adding(db):
    driver, database = db
    write_batch(driver, database, batch_for())
    write_batch(driver, database, batch_for(decisions=(FALLBACK_DECISION,)))
    rows = neo4j_runner(driver, database)(
        "MATCH (d:Decision {repo: $repo}) RETURN d.summary AS s", {"repo": A}
    )
    assert [r["s"] for r in rows] == [FALLBACK_DECISION["summary"]]


def test_two_repos_with_the_same_pr_number_stay_separate(db):
    driver, database = db
    write_batch(driver, database, batch_for(A))
    write_batch(driver, database, batch_for(B))
    run = neo4j_runner(driver, database)
    prs = run("MATCH (p:PullRequest {number: 1565}) RETURN p.id AS id ORDER BY id", {})
    assert [r["id"] for r in prs] == ["test/fixture#pr:1565", "test/fixture-b#pr:1565"]
    answer = current_decisions(run, A, DETECT)
    assert isinstance(answer, Answer)
    assert all(d.id.startswith("test/fixture#") for d in answer.decisions)
    assert all(e.id.startswith("test/fixture#") for d in answer.decisions for e in d.evidence)
    # Repo B's query for repo A's entity id finds nothing: every query filters on repo.
    assert isinstance(current_decisions(run, B, DETECT), Refusal)


def test_query_5a_returns_the_decision_with_verified_quotes(db):
    driver, database = db
    write_batch(driver, database, batch_for())
    r = current_decisions(neo4j_runner(driver, database), A, DETECT)
    assert isinstance(r, Answer)
    (d,) = r.decisions
    assert d.summary == "Switch the X parser for Y" and d.decided_at == NOW.replace(2021, 6, 21)
    assert LGPL in [e.quote for e in d.evidence]
    assert [p.login for p in d.proposed_by] == ["alice"]
    assert [p.login for p in d.approved_by] == ["bob"]
    assert d.decided_in[0].label == "PR #1565"


def test_query_5a_refuses_with_facts_for_code_without_a_decision(db):
    driver, database = db
    write_batch(driver, database, batch_for())
    r = current_decisions(neo4j_runner(driver, database), A, TO_TEXT)
    assert isinstance(r, Refusal) and r.entity_found
    assert r.known_facts[0].title.startswith("Commit 1111111: Use Y instead of X")
    assert r.known_facts[0].detail == "changed it: +0 / -1 lines"
    assert r.last_owner.login == "alice"


def test_query_5a_refuses_an_unknown_entity(db):
    driver, database = db
    write_batch(driver, database, batch_for())
    r = current_decisions(neo4j_runner(driver, database), A, "test/fixture#fn:nowhere.py::ghost")
    assert isinstance(r, Refusal) and not r.entity_found
