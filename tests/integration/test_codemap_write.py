"""The code map in the local test Neo4j: idempotent, and repos never mix."""

import pytest

from tests.gitrepo import make_repo
from whycode.graph.schema import apply_schema
from whycode.graph.writer import delete_repo, repo_counts, write_batch
from whycode.ingest.codemap import run_codemap

A, B = "test/codemap", "test/codemap-b"


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    root = tmp_path_factory.mktemp("codemap") / "repo"
    make_repo(root)
    return root


@pytest.fixture
def db(neo4j_test):
    driver, database = neo4j_test
    apply_schema(driver, database)
    for repo in (A, B):
        delete_repo(driver, database, repo)
    yield driver, database
    for repo in (A, B):
        delete_repo(driver, database, repo)


def test_writing_twice_changes_no_count(db, tiny):
    driver, database = db
    batch, _ = run_codemap(A, tiny)
    write_batch(driver, database, batch)
    first = repo_counts(driver, database, A)
    write_batch(driver, database, run_codemap(A, tiny)[0])
    assert repo_counts(driver, database, A) == first
    by_label, rels = first
    assert by_label == {label: len(nodes) for label, nodes in batch.nodes.items()}
    assert rels == batch.count()[1]
    assert "Decision" not in by_label


def test_a_second_repo_stays_separate(db, tiny):
    driver, database = db
    write_batch(driver, database, run_codemap(A, tiny)[0])
    alone = repo_counts(driver, database, A)
    write_batch(driver, database, run_codemap(B, tiny)[0])
    assert repo_counts(driver, database, A) == alone
    assert repo_counts(driver, database, B) == alone  # same history, its own nodes
    with driver.session(database=database) as s:
        crossing = s.run(
            "MATCH (a {repo: $a})-[r]-(b {repo: $b}) RETURN count(r) AS n", a=A, b=B
        ).single()["n"]
    assert crossing == 0


def test_codemap_leaves_decisions_alone(db, tiny):
    driver, database = db
    with driver.session(database=database) as s:
        s.run(
            "MERGE (d:Decision {id: $id}) SET d.repo = $repo, d.summary = 'kept'",
            id=f"{A}#dec:0000000000000000",
            repo=A,
        ).consume()
    write_batch(driver, database, run_codemap(A, tiny)[0])
    by_label, _ = repo_counts(driver, database, A)
    assert by_label["Decision"] == 1
