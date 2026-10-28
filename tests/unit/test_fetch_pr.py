from tests.fakes import FakeGitHub, MemoryRawStore, load_github_fixture
from whycode.ingest.fetch_pr import PER_PAGE, fetch_pr
from whycode.ingest.github import GitHubClient

REPO = "test/fixture"


def run(routes, store=None):
    fake = FakeGitHub(routes)
    store = store or MemoryRawStore()
    with GitHubClient("t", transport=fake.transport(), sleep=lambda s: None) as gh:
        result = fetch_pr(gh, store, REPO, 1565)
    return result, store, fake, gh


def test_fetches_pr_thread_and_stores_every_part():
    r, store, _, _ = run(load_github_fixture("pr_1565.json"))
    assert r.pr["title"] == "Switch the X parser for Y"
    assert [c["id"] for c in r.issue_comments] == [9001, 9002]
    assert len(r.review_comments) == 1 and len(r.reviews) == 1
    assert len(r.commits) == 1 and r.files[0]["previous_filename"] == "fixture/compat.py"
    kinds = {k[1] for k in store.rows}
    assert kinds == {
        "pr", "issue", "issue_comments", "review_comments", "reviews",
        "pr_commits", "pr_files", "timeline", "blob", "tree",
    }  # fmt: skip
    assert all(k[0] == REPO for k in store.rows)


def test_changed_python_files_are_fetched_as_blobs():
    r, store, fake, _ = run(load_github_fixture("pr_1565.json"))
    # README.md is not Python and fixture/old.py was removed: neither is fetched.
    assert r.blobs == {"src/fixture/compat.py": "c0ffee01", "fixture/utils.py": "c0ffee02"}
    assert store.get(REPO, "blob", "c0ffee01").payload["encoding"] == "base64"
    assert not any(c.url.path.endswith("/blobs/c0ffee03") for c in fake.calls)


def test_blobs_are_never_fetched_twice():
    routes = load_github_fixture("pr_1565.json")
    _, store, _, _ = run(routes)
    _, _, fake, _ = run(routes, store)
    assert not any("/git/blobs/" in c.url.path for c in fake.calls)


def test_current_tree_of_the_default_branch_is_fetched():
    r, store, fake, _ = run(load_github_fixture("pr_1565.json"))
    assert r.tree_branch == "main"
    tree_call = next(c for c in fake.calls if c.url.path.endswith("/git/trees/main"))
    assert tree_call.url.params["recursive"] == "1"
    paths = {e["path"] for e in store.get(REPO, "tree", "main").payload["tree"]}
    assert "lib/fixture/utils.py" in paths


def test_no_default_branch_skips_the_tree_but_keeps_the_rest():
    routes = load_github_fixture("pr_1565.json")
    del routes["/repos/test/fixture/pulls/1565"]["base"]
    r, store, _, _ = run(routes)
    assert r.tree_branch is None and r.blobs and store.get(REPO, "tree", "main") is None


def test_linked_issues_from_body_commits_and_timeline():
    r, _, _, _ = run(load_github_fixture("pr_1565.json"))
    linked = {li.number: li.reason for li in r.linked}
    assert linked == {1500: "closing", 1501: "closing", 1400: "body-ref", 1502: "timeline"}
    assert [c["id"] for c in next(li for li in r.linked if li.number == 1500).comments] == [8001]


def test_url_fragment_in_body_is_not_fetched():
    r, _, fake, _ = run(load_github_fixture("pr_1565.json"))
    assert 12 not in {li.number for li in r.linked}
    assert not any(c.url.path.endswith("/issues/12") for c in fake.calls)


def test_refetch_uses_etags_and_rewrites_nothing():
    routes = load_github_fixture("pr_1565.json")
    _, store, _, _ = run(routes)
    rows_before, writes_before = dict(store.rows), store.writes
    r2, store, _, gh = run(routes, store)
    assert store.writes == writes_before  # every request came back 304
    assert gh.stats.not_modified == gh.stats.requests
    assert store.rows.keys() == rows_before.keys()
    assert [c["id"] for c in r2.issue_comments] == [9001, 9002]  # served from the cache


def test_changed_item_is_updated_in_place():
    routes = load_github_fixture("pr_1565.json")
    _, store, _, _ = run(routes)
    n_rows = len(store.rows)
    routes["/repos/test/fixture/pulls/1565"] = {
        **routes["/repos/test/fixture/pulls/1565"],
        "title": "New",
    }
    r2, store, _, _ = run(routes, store)
    assert r2.pr["title"] == "New"
    assert store.get(REPO, "pr", "1565").payload["title"] == "New"
    assert len(store.rows) == n_rows


def test_pagination_walks_all_pages_with_one_row_each():
    routes = load_github_fixture("pr_1565.json")
    comments = [{"id": i, "body": f"c{i}"} for i in range(PER_PAGE * 2 + 30)]
    routes["/repos/test/fixture/issues/1565/comments"] = comments
    r, store, _, _ = run(routes)
    assert [c["id"] for c in r.issue_comments] == list(range(len(comments)))
    pages = sorted(
        k[2] for k in store.rows if k[1] == "issue_comments" and k[2].startswith("1565:")
    )
    assert pages == ["1565:p1", "1565:p2", "1565:p3"]


def test_exact_multiple_of_page_size_fetches_one_empty_page():
    routes = load_github_fixture("pr_1565.json")
    routes["/repos/test/fixture/issues/1565/comments"] = [{"id": i} for i in range(PER_PAGE)]
    r, store, _, _ = run(routes)
    assert len(r.issue_comments) == PER_PAGE
    assert store.get(REPO, "issue_comments", "1565:p2").payload == []


def test_shrunken_list_drops_stale_pages():
    routes = load_github_fixture("pr_1565.json")
    routes["/repos/test/fixture/issues/1565/comments"] = [{"id": i} for i in range(PER_PAGE + 5)]
    _, store, _, _ = run(routes)
    assert store.get(REPO, "issue_comments", "1565:p2") is not None
    routes["/repos/test/fixture/issues/1565/comments"] = [{"id": 1}]
    r, store, _, _ = run(routes, store)
    assert len(r.issue_comments) == 1
    assert store.get(REPO, "issue_comments", "1565:p2") is None
