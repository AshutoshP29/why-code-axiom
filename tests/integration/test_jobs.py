import pytest

from tests.integration.conftest import TEST_REPO
from whycode.ingest.select import Candidate, JobStore


@pytest.fixture
def jobs(raw_store):
    store = JobStore(raw_store.conn)
    store.ensure_schema()
    store.delete_repo(TEST_REPO)
    yield store
    store.delete_repo(TEST_REPO)


def cand(n, comments):
    return Candidate(n, f"PR {n}", comments, "alice")


def test_enqueue_reports_only_new_rows_and_keeps_status(jobs):
    assert jobs.enqueue(TEST_REPO, [cand(1, 10), cand(2, 30)]) == 2
    jobs.mark(TEST_REPO, 2, "written", decisions=4, add_calls=3)
    assert jobs.enqueue(TEST_REPO, [cand(1, 12), cand(2, 30), cand(3, 5)]) == 1
    by_number = {j.number: j for j in jobs.all(TEST_REPO)}
    assert by_number[2].status == "written" and by_number[2].decisions == 4
    assert by_number[2].calls == 3 and by_number[1].comments == 12  # refreshed, not reset


def test_pending_is_most_discussed_first_and_skips_finished(jobs):
    jobs.enqueue(TEST_REPO, [cand(1, 10), cand(2, 30), cand(3, 20), cand(4, 40)])
    jobs.mark(TEST_REPO, 4, "written", decisions=1)
    jobs.mark(TEST_REPO, 3, "failed", error="404")
    jobs.mark(TEST_REPO, 2, "fetched", error="incomplete")
    assert [j.number for j in jobs.pending(TEST_REPO)] == [2, 1]
    assert jobs.counts(TEST_REPO) == {"written": 1, "failed": 1, "fetched": 1, "queued": 1}


def test_calls_accumulate_across_attempts(jobs):
    jobs.enqueue(TEST_REPO, [cand(1, 10)])
    jobs.mark(TEST_REPO, 1, "fetched", add_calls=2, error="incomplete")
    jobs.mark(TEST_REPO, 1, "written", add_calls=1, decisions=2)
    (job,) = jobs.all(TEST_REPO)
    assert job.calls == 3 and job.error is None


def test_unknown_status_is_rejected(jobs):
    with pytest.raises(ValueError):
        jobs.mark(TEST_REPO, 1, "done")
