"""The code map in the local test Neo4j: idempotent, and repos never mix."""

import pytest

from tests.gitrepo import make_repo
from whycode.graph.schema import apply_schema
from whycode.graph.writer import delete_repo, repo_counts
from whycode.ingest.codemap import run_codemap, write_code_map

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
    write_code_map(driver, database, batch)
    first = repo_counts(driver, database, A)
    write_code_map(driver, database, run_codemap(A, tiny)[0])
    assert repo_counts(driver, database, A) == first
    by_label, rels = first
    assert by_label == {label: len(nodes) for label, nodes in batch.nodes.items()}
    refs = sum(len(p) for (t, _, _), p in batch.rels.items() if t == "REFERENCES")
    assert rels == batch.count()[1] - refs  # no PR is in the graph, so no REFERENCES
    assert "Decision" not in by_label and "PullRequest" not in by_label


def test_a_second_repo_stays_separate(db, tiny):
    driver, database = db
    write_code_map(driver, database, run_codemap(A, tiny)[0])
    alone = repo_counts(driver, database, A)
    write_code_map(driver, database, run_codemap(B, tiny)[0])
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
    write_code_map(driver, database, run_codemap(A, tiny)[0])
    by_label, _ = repo_counts(driver, database, A)
    assert by_label["Decision"] == 1


def test_references_only_pull_requests_already_ingested(db, tiny):
    driver, database = db
    pr = f"{A}#pr:12"
    with driver.session(database=database) as s:
        s.run(
            "MERGE (p:PullRequest {id: $id}) SET p.repo = $repo, p.number = 12, p.title = 'kept'",
            id=pr,
            repo=A,
        ).consume()
    write_code_map(driver, database, run_codemap(A, tiny)[0])
    with driver.session(database=database) as s:
        rows = s.run(
            "MATCH (c:Commit {repo: $repo})-[:REFERENCES]->(p:PullRequest {repo: $repo}) "
            "RETURN p.id AS id, p.title AS title",
            repo=A,
        ).data()
    assert rows == [{"id": pr, "title": "kept"}]  # "#7" is not in the graph, so not linked


def test_file_aliases_already_there_are_kept(db, tiny):
    driver, database = db
    core = f"{A}#file:pkg/core.py"
    with driver.session(database=database) as s:
        s.run(
            "MERGE (f:File {id: $id}) SET f.repo = $repo, f.aliases = ['pkg/from_a_pr.py'], "
            "f.aliases_text = 'pkg/from_a_pr.py'",
            id=core,
            repo=A,
        ).consume()
    for _ in range(2):
        write_code_map(driver, database, run_codemap(A, tiny)[0])
    with driver.session(database=database) as s:
        f = s.run("MATCH (f:File {id: $id}) RETURN f", id=core).single()["f"]
        tool = s.run("MATCH (f:File {id: $id}) RETURN f", id=f"{A}#file:scripts/tool.py").single()[
            "f"
        ]
    assert f["aliases"] == ["pkg/from_a_pr.py", "pkg/old_name.py"]
    assert f["aliases_text"] == "pkg/from_a_pr.py pkg/old_name.py"
    assert f["path"] == "pkg/core.py"
    assert (tool["aliases"], tool["aliases_text"]) == ([], "")
