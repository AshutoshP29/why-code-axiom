from tests.fakes import FakeGitHub, load_github_fixture
from tests.integration.conftest import TEST_REPO
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubClient


def test_upsert_updates_instead_of_adding(raw_store):
    raw_store.upsert(TEST_REPO, "pr", "1565", '"e1"', {"title": "old"})
    first = raw_store.get(TEST_REPO, "pr", "1565")
    raw_store.upsert(TEST_REPO, "pr", "1565", '"e2"', {"title": "new"})
    row = raw_store.get(TEST_REPO, "pr", "1565")
    assert raw_store.count(TEST_REPO) == 1
    assert row.payload == {"title": "new"} and row.etag == '"e2"'
    assert row.fetched_at >= first.fetched_at


def test_touch_keeps_payload_and_moves_fetched_at(raw_store):
    raw_store.upsert(TEST_REPO, "pr", "1", '"e"', {"a": 1})
    before = raw_store.get(TEST_REPO, "pr", "1")
    raw_store.touch(TEST_REPO, "pr", "1")
    after = raw_store.get(TEST_REPO, "pr", "1")
    assert after.payload == {"a": 1} and after.fetched_at >= before.fetched_at


def test_nul_character_is_stored_without_error(raw_store):
    raw_store.upsert(TEST_REPO, "issue", "7", None, {"body": "a\u0000b"})
    assert raw_store.get(TEST_REPO, "issue", "7").payload == {"body": "ab"}


def test_same_number_in_two_repos_are_separate_rows(raw_store):
    raw_store.upsert(TEST_REPO, "pr", "1565", None, {"r": "a"})
    raw_store.upsert("test/fixture-two", "pr", "1565", None, {"r": "b"})
    try:
        assert raw_store.get(TEST_REPO, "pr", "1565").payload == {"r": "a"}
        assert raw_store.get("test/fixture-two", "pr", "1565").payload == {"r": "b"}
    finally:
        raw_store.delete_repo("test/fixture-two")


def test_fetching_the_same_pr_twice_keeps_row_count(raw_store):
    routes = load_github_fixture("pr_1565.json")

    def fetch():
        with GitHubClient("t", transport=FakeGitHub(routes).transport()) as gh:
            fetch_pr(gh, raw_store, TEST_REPO, 1565)
            return gh.stats

    fetch()
    rows = raw_store.count(TEST_REPO)
    stats = fetch()
    assert raw_store.count(TEST_REPO) == rows
    assert stats.not_modified == stats.requests  # second run is all 304s
