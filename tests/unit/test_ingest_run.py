import json

import pytest

from tests.fakes import (
    FakeGitHub,
    FakeProvider,
    MemoryJobStore,
    MemoryLLMCache,
    MemoryRawStore,
    load_github_fixture,
    search_route,
)
from tests.pipeline import SWITCH_DECISION
from whycode.ingest.github import GitHubClient
from whycode.ingest.run import ingest
from whycode.ingest.select import Candidate, eligible_prs
from whycode.llm.client import Budget, LLMClient

R = "test/fixture"
REPLY = json.dumps({"decisions": [SWITCH_DECISION]})


class FakeSink:
    def __init__(self):
        self.batches, self.states = [], []

    def write(self, batch):
        self.batches.append(batch)

    def progress(self, **state):
        self.states.append(state)


class Setup:
    """The fixture PR #1565 plus #9999, which GitHub does not have (404)."""

    def __init__(self, replies=(REPLY,), budget=10):
        routes = load_github_fixture("pr_1565.json")
        routes["/search/issues"] = search_route(
            [
                {"number": 9999, "title": "Gone", "comments": 50, "user": {"login": "x"}},
                {"number": 1565, "title": "Switch X for Y", "comments": 9, "user": {"login": "a"}},
            ]
        )
        self.fake = FakeGitHub(routes)
        self.gh = GitHubClient("t", transport=self.fake.transport())
        self.store, self.jobs, self.sink = MemoryRawStore(), MemoryJobStore(), FakeSink()
        self.provider = FakeProvider("gemini", "fake-model", list(replies))
        self.llm = LLMClient([self.provider], MemoryLLMCache(), Budget(budget))
        self.jobs.enqueue(R, eligible_prs(self.gh, R, 5, 50))

    def run(self, **kw):
        return ingest(R, self.jobs, self.gh, self.store, self.llm, self.sink, **kw)


def test_writes_good_prs_and_marks_missing_ones_failed_without_stopping():
    s = Setup()
    report = s.run()
    by_number = {o.number: o for o in report.outcomes}
    assert [o.number for o in report.outcomes] == [9999, 1565]  # most discussed first
    assert by_number[9999].status == "failed" and "404" in by_number[9999].error
    assert by_number[1565].status == "written" and by_number[1565].decisions == 1
    assert by_number[1565].calls == 1 and report.stopped_early is None
    assert len(s.sink.batches) == 1
    assert s.jobs.counts(R) == {"failed": 1, "written": 1}


def test_a_second_run_resumes_and_redoes_nothing():
    s = Setup()
    s.run()
    report = s.run()
    assert report.outcomes == [] and len(s.provider.calls) == 1 and len(s.sink.batches) == 1


def test_dry_run_plans_without_llm_calls_or_writes():
    s = Setup()
    report = s.run(dry_run=True)
    (o,) = [o for o in report.outcomes if o.number == 1565]
    assert o.status == "dry-run" and o.parts == 1 and o.cached_parts == 0
    assert report.would_call == 1
    assert s.provider.calls == [] and s.sink.batches == [] and s.sink.states == []
    assert s.jobs.rows[(R, 1565)].status == "fetched"  # fetched, still pending
    # The real run afterwards picks it up.
    s.run()
    assert s.jobs.rows[(R, 1565)].status == "written"


def test_spent_budget_stops_cleanly_and_leaves_the_pr_pending():
    s = Setup(budget=0)
    report = s.run()
    (o,) = [o for o in report.outcomes if o.number == 1565]
    assert o.status == "incomplete" and "BudgetExceededError" in o.error
    assert report.stopped_early.startswith("#1565")
    assert s.sink.batches == [] and s.provider.calls == []
    assert s.jobs.rows[(R, 1565)].status == "fetched"
    assert s.sink.states[-1]["error"].startswith("#1565")  # the repo shows why it stopped


def test_progress_moves_from_ingesting_to_ready_at_100_percent():
    s = Setup()
    s.run()
    assert s.sink.states[0]["status"] == "INGESTING"
    assert s.sink.states[-1] == {
        "status": "READY",
        "stage": "extract",
        "pct": 100.0,
        "partial": True,
        "error": None,
    }


@pytest.mark.parametrize("status", [429, 403])
def test_github_rate_limit_stops_the_run_instead_of_failing_every_pr(status):
    s = Setup()
    limited = {"Retry-After": "99999"}  # longer than the client will wait

    def rate_limited(request):
        import httpx

        return httpx.Response(status, headers=limited, json={"message": "rate limit"})

    s.fake.routes["/repos/test/fixture/pulls/9999"] = rate_limited
    report = s.run()
    assert report.stopped_early.startswith("GitHub rate limit")
    assert s.jobs.counts(R) == {"queued": 2}  # nothing marked failed


def test_one_pr_the_llm_cannot_answer_is_skipped_and_the_run_continues():
    from tests.fakes import StatusError

    s = Setup(replies=(StatusError(400), REPLY))
    # A second real PR, #1566, more discussed than #1565 so it runs first.
    routes = s.fake.routes
    for key in [k for k in routes if "/1565" in k]:
        routes[key.replace("/1565", "/1566")] = routes[key]
    s.jobs.enqueue(
        R,
        [Candidate(1566, "Other", 30, "a")],
    )
    report = s.run()
    by_number = {o.number: o for o in report.outcomes}
    assert by_number[1566].status == "incomplete"  # the 400 answer
    assert by_number[1565].status == "written"  # the run went on
    assert report.stopped_early is None
    assert s.jobs.rows[(R, 1566)].status == "fetched"  # retried by the next run
