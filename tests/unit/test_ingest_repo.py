from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tests.api_fakes import FakeGraph
from whycode.graph import supersession, writer
from whycode.ingest import repo as worker
from whycode.ingest.github import RateLimitError

REPO = "expressjs/express"
NOW = datetime(2026, 11, 21, 18, 0, tzinfo=UTC)


@dataclass
class Job:
    number: int
    status: str = "queued"


class FakeJobs:
    def __init__(self):
        self.jobs: dict[int, Job] = {}

    def enqueue(self, repo, candidates):
        for c in candidates:
            self.jobs.setdefault(c.number, Job(c.number))
        return len(candidates)

    def pending(self, repo):
        return [j for j in self.jobs.values() if j.status in ("queued", "fetched")]

    def mark(self, repo, number, status, **kw):
        self.jobs[number].status = status


@pytest.fixture
def world(monkeypatch):
    """A run with every outside call replaced: what it fetched, wrote and recorded."""
    w = SimpleNamespace(
        states=[],
        fetched=[],
        written=[],
        superseded=[],
        candidates=[1, 2, 3],
        known=[],
        decisions=iter([4, 6]),  # before and after extraction
        fetch_error=None,
        added=True,
        status="QUEUED",
    )

    def record(driver, database, repo, *, status, stage=None, progress_pct=None, **kw):
        w.states.append((status, stage, progress_pct, kw.get("error")))

    def fetch(gh, store, repo, number):
        if w.fetch_error and number == 2:
            raise w.fetch_error
        w.fetched.append(number)

    def fake_ingest(repo, jobs, gh, store, llm, sink):
        sink.progress(status="INGESTING", stage="extract", pct=0, partial=True)
        for job in jobs.pending(repo):
            jobs.mark(repo, job.number, "written")
        sink.progress(status="READY", stage="extract", pct=100, partial=True, error=None)
        return SimpleNamespace(stopped_early=None)

    monkeypatch.setattr(worker, "set_repo_state", record)
    monkeypatch.setattr(writer, "set_repo_state", record)
    monkeypatch.setattr(
        worker,
        "eligible_prs",
        lambda gh, repo, min_comments, limit: [SimpleNamespace(number=n) for n in w.candidates],
    )
    monkeypatch.setattr(worker, "fetch_pr", fetch)
    monkeypatch.setattr(worker.codemap, "clone_or_update", lambda url, dest: "headsha")
    monkeypatch.setattr(worker.codemap, "build_code_map", lambda repo, dest, head: "batch")
    monkeypatch.setattr(worker.codemap, "read_history", lambda dest, since: [since])
    monkeypatch.setattr(worker.codemap, "add_history", lambda batch, commits: None)
    monkeypatch.setattr(
        worker.codemap, "write_code_map", lambda driver, db, batch: w.written.append(batch)
    )
    monkeypatch.setattr(worker, "ingest", fake_ingest)
    monkeypatch.setattr(
        supersession,
        "supersede",
        lambda run, driver, db, llm, repo: (
            w.superseded.append(repo) or SimpleNamespace(stopped_early=None)
        ),
    )
    graph = FakeGraph(
        repo_state=lambda p: [{"added": w.added, "status": w.status, "error": None}],
        known_prs=lambda p: [{"id": f"{REPO}#pr:{n}"} for n in w.known],
        decision_count=lambda p: [{"n": next(w.decisions)}],
        repos_due=[{"id": REPO}, {"id": "a/b"}],
    )
    w.ctx = worker.Context(graph, None, "neo4j", None, None, FakeJobs(), None)
    return w


def test_every_stage_runs_in_the_order_the_screens_show(world):
    assert worker.run_repo(world.ctx, REPO, now=NOW) is None
    stages = [s[1] for s in world.states]
    assert list(dict.fromkeys(stages)) == ["fetch", "parse", "link", "extract", "supersession"]
    assert all(status == "INGESTING" for status, *_ in world.states[:-1])
    # ingest() says READY when its PRs are done; supersession still follows, so it is not READY.
    assert ("INGESTING", "extract", 100, None) in world.states
    assert world.states[-1] == ("READY", "supersession", 100, None)
    assert world.fetched == [1, 2, 3]
    assert world.written == ["batch"]
    assert world.superseded == [REPO]


def test_prs_already_in_the_graph_are_not_fetched_again(world):
    world.known = [1, 3]
    worker.run_repo(world.ctx, REPO, now=NOW)
    assert world.fetched == [2]
    assert world.ctx.jobs.jobs[1].status == "written"


def test_supersession_is_skipped_when_no_decision_was_added(world):
    world.decisions = iter([5, 5])
    worker.run_repo(world.ctx, REPO, now=NOW)
    assert world.superseded == []
    assert "supersession" not in [s[1] for s in world.states[:-1]]
    assert world.states[-1][0] == "READY"


def test_the_history_window_is_the_last_few_years(world, monkeypatch):
    seen = []
    monkeypatch.setattr(worker.codemap, "read_history", lambda dest, since: seen.append(since))
    worker.run_repo(world.ctx, REPO, now=NOW)
    assert seen == ["2023-11-22"]  # HISTORY_YEARS = 3 years of 365 days


def test_a_github_rate_limit_is_kept_as_the_reason_it_stopped(world):
    world.fetch_error = RateLimitError("limit")
    stopped = worker.run_repo(world.ctx, REPO, now=NOW)
    assert stopped.startswith("GitHub rate limit while fetching #2")
    assert world.states[-1] == ("READY", "supersession", 100, stopped)


def test_a_repo_read_by_hand_is_refused_before_anything_is_written(world):
    world.added = False
    with pytest.raises(worker.NotAddedError):
        worker.run_repo(world.ctx, REPO, now=NOW)
    assert world.states == [] and world.fetched == []


def test_a_failed_run_is_marked_unless_a_precise_error_is_there(world):
    world.status = "INGESTING"
    assert worker.mark_failed(world.ctx, REPO, "stopped: https://example/run")
    assert world.states == [("ERROR", None, None, "stopped: https://example/run")]
    world.status, world.states = "ERROR", []
    assert not worker.mark_failed(world.ctx, REPO, "generic")
    world.status, world.added = "INGESTING", False
    assert not worker.mark_failed(world.ctx, REPO, "generic")
    assert world.states == []


def test_due_lists_the_repos_kept_up_to_date(world):
    assert worker.due(world.ctx) == [REPO, "a/b"]
