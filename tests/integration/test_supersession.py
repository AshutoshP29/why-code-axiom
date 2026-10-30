import json
from datetime import UTC, datetime

import pytest

from tests.fakes import FakeProvider, MemoryLLMCache
from tests.pipeline import SWITCH_DECISION, run_fixture
from whycode.extract.prompt import PROMPT_VERSION
from whycode.graph.build import build_pr_graph
from whycode.graph.queries import Answer, current_decisions, neo4j_runner
from whycode.graph.schema import apply_schema
from whycode.graph.supersession import supersede
from whycode.graph.writer import delete_repo, repo_counts, write_batch
from whycode.llm.client import Budget, LLMClient

R = "test/fixture"
DETECT = "test/fixture#fn:src/fixture/compat.py::Detector.detect"
NEWER_EVIDENCE = "test/fixture#ev:pr:1565:rc:7001"
# A later decision on the same function, quoting the review comment.
FALLBACK_ON_DETECT = {
    "summary": "Keep the old X import as a fallback in Detector.detect for one release",
    "rationale": "Users need one release to migrate.",
    "alternatives": [],
    "decided_at": "2021-06-25",
    "affects": [{"kind": "function", "path": "src/fixture/compat.py", "name": "Detector.detect"}],
    "evidence": [
        {
            "source_id": "pr:1565:rc:7001",
            "exact_quote": "Keep the old import as a fallback for one release.",
        }
    ],
    "evidence_kind": "EXPLICIT",
    "confidence": 0.8,
}


def judge(kind, evidence_id=NEWER_EVIDENCE):
    reply = json.dumps(
        {"kind": kind, "confidence": 0.9, "evidence_id": evidence_id, "explanation": "test"}
    )
    return LLMClient([FakeProvider("gemini", "judge", [reply])], MemoryLLMCache(), Budget(5))


@pytest.fixture
def graph(neo4j_test):
    driver, database = neo4j_test
    apply_schema(driver, database)
    delete_repo(driver, database, R)
    p = run_fixture(decisions=(SWITCH_DECISION, FALLBACK_ON_DETECT))
    batch = build_pr_graph(
        p.store,
        p.thread,
        p.result.decisions,
        p.checks,
        index=p.index,
        prompt_version=PROMPT_VERSION,
        now=datetime(2026, 10, 28, tzinfo=UTC),
    )
    write_batch(driver, database, batch)
    yield driver, database, neo4j_runner(driver, database)
    delete_repo(driver, database, R)


def statuses(run):
    rows = run("MATCH (d:Decision {repo: $r}) RETURN d.summary AS s, d.status AS st", {"r": R})
    return {r["s"][:12]: r["st"] for r in rows}


def test_replacing_decision_supersedes_the_older_one_and_5a_shows_only_the_newer(graph):
    driver, database, run = graph
    report = supersede(run, driver, database, judge("replaces"), R)
    assert len(report.pairs) == 1 and report.judgements[0].verdict.kind == "replaces"
    assert statuses(run) == {"Switch the X": "SUPERSEDED", "Keep the old": "ACTIVE"}
    answer = current_decisions(run, R, DETECT)
    assert isinstance(answer, Answer)
    assert [d.summary[:12] for d in answer.decisions] == ["Keep the old"]
    edge = run(
        "MATCH (:Decision)-[s:SUPERSEDES]->(:Decision {repo: $r}) RETURN properties(s) AS p",
        {"r": R},
    )[0]["p"]
    assert edge["kind"] == "replaces" and edge["evidence_id"] == NEWER_EVIDENCE


def test_refines_marks_the_older_decision_partial(graph):
    driver, database, run = graph
    supersede(run, driver, database, judge("refines"), R)
    assert statuses(run)["Switch the X"] == "PARTIAL"


def test_running_twice_changes_nothing(graph):
    driver, database, run = graph
    supersede(run, driver, database, judge("replaces"), R)
    first = repo_counts(driver, database, R), statuses(run)
    supersede(run, driver, database, judge("replaces"), R)
    assert (repo_counts(driver, database, R), statuses(run)) == first


def test_a_later_unrelated_verdict_removes_the_link(graph):
    driver, database, run = graph
    supersede(run, driver, database, judge("replaces"), R)
    supersede(run, driver, database, judge("unrelated", None), R)
    assert statuses(run) == {"Switch the X": "ACTIVE", "Keep the old": "ACTIVE"}
    assert run("MATCH ()-[s:SUPERSEDES]->(:Decision {repo: $r}) RETURN s", {"r": R}) == []


def test_a_link_on_invented_evidence_is_never_written(graph):
    driver, database, run = graph
    report = supersede(run, driver, database, judge("replaces", "test/fixture#ev:invented"), R)
    assert report.judgements[0].rejected and statuses(run)["Switch the X"] == "ACTIVE"


def test_dry_run_lists_pairs_without_calls_or_writes(graph):
    driver, database, run = graph
    llm = judge("replaces")
    report = supersede(run, driver, database, llm, R, dry_run=True)
    assert len(report.pairs) == 1 and llm.api_calls == 0 and report.statuses == {}
    assert statuses(run)["Switch the X"] == "ACTIVE"
