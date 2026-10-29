"""The ingestion runner end to end on real Postgres (jobs) and the local test Neo4j."""

import pytest

from tests.fakes import MemoryRawStore
from tests.integration.conftest import TEST_REPO
from tests.unit.test_ingest_run import Setup
from whycode.graph.queries import Answer, current_decisions, neo4j_runner
from whycode.graph.schema import apply_schema
from whycode.graph.writer import delete_repo, repo_counts
from whycode.ingest.run import Neo4jSink, ingest
from whycode.ingest.select import JobStore, eligible_prs


@pytest.fixture
def env(raw_store, neo4j_test):
    driver, database = neo4j_test
    apply_schema(driver, database)
    delete_repo(driver, database, TEST_REPO)
    jobs = JobStore(raw_store.conn)
    jobs.ensure_schema()
    jobs.delete_repo(TEST_REPO)
    yield jobs, driver, database
    jobs.delete_repo(TEST_REPO)
    delete_repo(driver, database, TEST_REPO)


def run_once(jobs, driver, database):
    s = Setup()
    jobs.enqueue(TEST_REPO, eligible_prs(s.gh, TEST_REPO, 5, 50))
    sink = Neo4jSink(driver, database, TEST_REPO)
    return ingest(TEST_REPO, jobs, s.gh, MemoryRawStore(), s.llm, sink), s


def test_run_writes_the_graph_records_jobs_and_repo_progress(env):
    jobs, driver, database = env
    report, _ = run_once(jobs, driver, database)
    assert [o.status for o in report.outcomes] == ["failed", "written"]
    assert {j.number: j.status for j in jobs.all(TEST_REPO)} == {9999: "failed", 1565: "written"}
    run = neo4j_runner(driver, database)
    repo = run("MATCH (r:Repo {id: $r}) RETURN r", {"r": TEST_REPO})[0]["r"]
    assert repo["status"] == "READY" and repo["progress_pct"] == 100.0 and repo["partial"] is True
    answer = current_decisions(
        run, TEST_REPO, "test/fixture#fn:src/fixture/compat.py::Detector.detect"
    )
    assert isinstance(answer, Answer)


def test_a_fresh_run_after_completion_changes_nothing(env):
    jobs, driver, database = env
    run_once(jobs, driver, database)
    first = repo_counts(driver, database, TEST_REPO)
    report, s = run_once(jobs, driver, database)
    assert report.outcomes == [] and s.provider.calls == []
    assert repo_counts(driver, database, TEST_REPO) == first
