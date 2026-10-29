from tests.fakes import FakeGitHub, MemoryJobStore, search_route
from whycode.ingest.github import GitHubClient
from whycode.ingest.select import Candidate, eligible_prs


def pr(number, comments, login="alice", title="Fix things", type_="User"):
    return {
        "number": number,
        "title": title,
        "comments": comments,
        "user": {"login": login, "type": type_},
    }


def run(items, min_comments=5, limit=50):
    fake = FakeGitHub({"/search/issues": search_route(items)})
    with GitHubClient("t", transport=fake.transport()) as gh:
        return eligible_prs(gh, "Test/Fixture", min_comments, limit), fake


def test_query_asks_for_merged_prs_with_enough_comments():
    _, fake = run([pr(1, 9)], min_comments=20)
    q = fake.calls[0].url.params["q"]
    assert q == "repo:test/fixture is:pr is:merged comments:>=20"
    assert fake.calls[0].url.params["sort"] == "comments"


def test_bots_and_dependency_bumps_are_left_out():
    items = [
        pr(1, 30),
        pr(2, 40, login="dependabot[bot]"),
        pr(3, 50, login="renovate", type_="Bot"),
        pr(4, 60, title="Bump urllib3 from 1.26 to 2.0"),
        pr(5, 25, title="Update dependency idna to v3"),
        pr(6, 20, title="chore(deps): pin certifi"),
    ]
    found, _ = run(items)
    assert [c.number for c in found] == [1]


def test_sorted_by_comments_then_number_and_limited():
    found, _ = run([pr(7, 10), pr(3, 30), pr(5, 30), pr(9, 20)], limit=3)
    assert [(c.number, c.comments) for c in found] == [(3, 30), (5, 30), (9, 20)]


def test_pages_until_github_runs_out():
    items = [pr(n, 200 - n) for n in range(1, 151)]  # 150 results: two pages of 100
    found, fake = run(items, limit=1000)
    assert len(found) == 150 and len(fake.calls) == 2


def test_stops_paging_once_the_limit_is_reached():
    items = [pr(n, 500 - n) for n in range(1, 251)]
    found, fake = run(items, limit=60)
    assert len(found) == 60 and len(fake.calls) == 1


# --- job store behaviour (in memory; the Postgres one is tested in integration) ------------


def cand(n, comments=10):
    return Candidate(n, f"PR {n}", comments, "alice")


def test_enqueue_is_idempotent_and_keeps_progress():
    jobs = MemoryJobStore()
    assert jobs.enqueue("r/x", [cand(1), cand(2)]) == 2
    jobs.mark("r/x", 1, "written", decisions=3, add_calls=2)
    assert jobs.enqueue("r/x", [cand(1), cand(2), cand(3)]) == 1
    assert jobs.rows[("r/x", 1)].status == "written"
    assert [j.number for j in jobs.pending("r/x")] == [2, 3]
