"""The knowledge risk queries against the local test Neo4j, on a hand-built test/fixture graph.

    docker compose up -d

The point is the Cypher itself: that it parses, that "in force" and "every decider inactive"
pick the rows they should, and that nothing from another repo leaks in.
"""

import pytest

from whycode.api import risk
from whycode.graph.queries import neo4j_runner
from whycode.graph.schema import apply_schema
from whycode.graph.writer import delete_repo

REPO = "test/fixture"
OTHER = "test/fixture-b"

# gone/also_gone have left; here/newcomer are still active.
GRAPH = """
MERGE (r:Repo {id: $repo}) SET r.repo = $repo, r.owner = 'test', r.name = 'fixture'
MERGE (gone:Person {id: $repo + '#person:gone'})
  SET gone.repo = $repo, gone.login = 'gone', gone.active = false,
      gone.last_seen = datetime('2020-01-01T00:00:00Z')
MERGE (older:Person {id: $repo + '#person:older'})
  SET older.repo = $repo, older.login = 'older', older.active = false,
      older.last_seen = datetime('2018-06-01T00:00:00Z')
MERGE (here:Person {id: $repo + '#person:here'})
  SET here.repo = $repo, here.login = 'here', here.active = true,
      here.last_seen = datetime('2026-10-01T00:00:00Z')

// orphaned: two decisions in force, every decider inactive
MERGE (a:Function {id: $repo + '#fn:pkg/a.py::alpha'})
  SET a.repo = $repo, a.name = 'alpha', a.qualified_name = 'alpha', a.path = 'pkg/a.py'
MERGE (d1:Decision {id: $repo + '#dec:1'})
  SET d1.repo = $repo, d1.summary = 'Alpha one', d1.rationale = 'r',
      d1.decided_at = datetime('2021-01-01T00:00:00Z'), d1.status = 'ACTIVE'
MERGE (d2:Decision {id: $repo + '#dec:2'})
  SET d2.repo = $repo, d2.summary = 'Alpha two', d2.rationale = 'r',
      d2.decided_at = datetime('2022-01-01T00:00:00Z'), d2.status = 'ACTIVE'
MERGE (d1)-[:AFFECTS]->(a)
MERGE (d2)-[:AFFECTS]->(a)
MERGE (d1)-[:PROPOSED_BY]->(gone)
MERGE (d1)-[:APPROVED_BY]->(older)
MERGE (d2)-[:PROPOSED_BY]->(gone)

// not orphaned: one decider is still active
MERGE (b:Function {id: $repo + '#fn:pkg/b.py::beta'})
  SET b.repo = $repo, b.name = 'beta', b.qualified_name = 'beta', b.path = 'pkg/b.py'
MERGE (d3:Decision {id: $repo + '#dec:3'})
  SET d3.repo = $repo, d3.summary = 'Beta', d3.rationale = 'r',
      d3.decided_at = datetime('2023-01-01T00:00:00Z'), d3.status = 'ACTIVE'
MERGE (d3)-[:AFFECTS]->(b)
MERGE (d3)-[:PROPOSED_BY]->(gone)
MERGE (d3)-[:APPROVED_BY]->(here)

// not orphaned: its only inactive-decided decision was replaced by one an active person made
MERGE (c:Class {id: $repo + '#cls:pkg/c.py::Gamma'})
  SET c.repo = $repo, c.name = 'Gamma', c.qualified_name = 'Gamma', c.path = 'pkg/c.py'
MERGE (old:Decision {id: $repo + '#dec:4'})
  SET old.repo = $repo, old.summary = 'Gamma old', old.rationale = 'r',
      old.decided_at = datetime('2019-01-01T00:00:00Z'), old.status = 'SUPERSEDED'
MERGE (new:Decision {id: $repo + '#dec:5'})
  SET new.repo = $repo, new.summary = 'Gamma new', new.rationale = 'r',
      new.decided_at = datetime('2024-01-01T00:00:00Z'), new.status = 'ACTIVE'
MERGE (old)-[:AFFECTS]->(c)
MERGE (new)-[:AFFECTS]->(c)
MERGE (old)-[:PROPOSED_BY]->(gone)
MERGE (new)-[:PROPOSED_BY]->(here)
MERGE (new)-[:SUPERSEDES {kind: 'replaces'}]->(old)

// unexplained: commits, no decision
MERGE (d:Function {id: $repo + '#fn:pkg/d.py::delta'})
  SET d.repo = $repo, d.name = 'delta', d.qualified_name = 'delta', d.path = 'pkg/d.py'
MERGE (k:ConfigKey {id: $repo + '#cfg:TIMEOUT'})
  SET k.repo = $repo, k.name = 'TIMEOUT', k.qualified_name = 'TIMEOUT', k.path = 'pkg/d.py'
MERGE (c1:Commit {id: $repo + '#commit:c1'})
  SET c1.repo = $repo, c1.sha = 'c1', c1.date = datetime('2024-02-01T00:00:00Z')
MERGE (c2:Commit {id: $repo + '#commit:c2'})
  SET c2.repo = $repo, c2.sha = 'c2', c2.date = datetime('2024-03-01T00:00:00Z')
MERGE (c3:Commit {id: $repo + '#commit:c3'})
  SET c3.repo = $repo, c3.sha = 'c3', c3.date = datetime('2024-04-01T00:00:00Z')
MERGE (c1)-[:MODIFIES]->(d)
MERGE (c2)-[:MODIFIES]->(d)
MERGE (c3)-[:MODIFIES]->(d)
MERGE (c1)-[:MODIFIES]->(k)
MERGE (gone)-[:AUTHORED]->(c1)
MERGE (here)-[:AUTHORED]->(c2)
MERGE (here)-[:AUTHORED]->(c3)
"""


@pytest.fixture(scope="module")
def run(neo4j_test):
    driver, database = neo4j_test
    apply_schema(driver, database)
    for repo in (REPO, OTHER):
        delete_repo(driver, database, repo)
    with driver.session(database=database) as s:
        s.run(GRAPH, repo=REPO).consume()
        s.run(GRAPH, repo=OTHER).consume()  # the same shape under another repo
    yield neo4j_runner(driver, database)
    for repo in (REPO, OTHER):
        delete_repo(driver, database, repo)


def test_only_code_nobody_active_decided_is_orphaned(run):
    report = risk.knowledge_risk(run, REPO)
    assert [o.entity.id for o in report.orphaned] == [f"{REPO}#fn:pkg/a.py::alpha"]
    (alpha,) = report.orphaned
    assert alpha.decisions == 2  # both are in force
    assert alpha.last_decided_at.year == 2022  # the newer one
    assert [(p.login, p.active) for p in alpha.people] == [("gone", False), ("older", False)]
    assert alpha.people[0].role == "Proposed the decision"
    assert alpha.people[1].role == "Approved it"


def test_code_that_commits_change_without_a_decision(run):
    report = risk.knowledge_risk(run, REPO)
    rows = {u.entity.id: u for u in report.unexplained}
    assert sorted(rows) == [f"{REPO}#cfg:TIMEOUT", f"{REPO}#fn:pkg/d.py::delta"]
    delta = rows[f"{REPO}#fn:pkg/d.py::delta"]
    assert (delta.commits, delta.authors) == (3, 2)
    assert delta.last_changed_at.year == 2024 and delta.last_changed_at.month == 4
    assert report.unexplained[0].entity.id.endswith("delta")  # most commits first


def test_counts_cover_the_whole_repo(run):
    counts = risk.knowledge_risk(run, REPO).counts
    assert counts.code_with_decisions == 3  # alpha, beta, Gamma
    assert counts.orphaned == 1
    assert counts.changed_without_reason == 2  # delta and TIMEOUT


def test_another_repo_with_the_same_shape_does_not_leak_in(run):
    report = risk.knowledge_risk(run, REPO)
    ids = [o.entity.id for o in report.orphaned] + [u.entity.id for u in report.unexplained]
    assert ids and all(i.startswith(f"{REPO}#") for i in ids)
    assert risk.knowledge_risk(run, OTHER).counts == report.counts


def test_a_repo_with_nothing_in_it_is_all_zeroes(run):
    report = risk.knowledge_risk(run, "test/empty")
    assert report.orphaned == [] and report.unexplained == []
    assert (report.counts.orphaned, report.counts.code_with_decisions) == (0, 0)
