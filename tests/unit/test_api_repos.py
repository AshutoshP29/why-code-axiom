from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException

from tests.api_fakes import REPO, REPO_NODE, FakeGraph, client
from whycode.api import repos

NEW = "expressjs/express"
NOW = datetime(2026, 11, 21, 18, 0, tzinfo=UTC)
PUBLIC = repos.Facts(
    found=True,
    public=True,
    size_kb=10_000,
    commits=6_000,
    commits_recent=400,
    pull_requests=3_000,
    issues=2_500,
    eligible=150,
)


class FakeFacts:
    def __init__(self, facts=PUBLIC):
        self._facts, self.asked = facts, []

    def facts(self, repo, now):
        self.asked.append(repo)
        return self._facts


class FakeDispatcher:
    def __init__(self, configured=True, error=None):
        self.configured, self.error, self.started = configured, error, []

    def dispatch(self, repo):
        if self.error:
            raise self.error
        self.started.append(repo)


class RepoGraph(FakeGraph):
    """FakeGraph whose Repo nodes are created and queued by the queries under test."""

    def __init__(self, nodes=None, busy=(), added_today=0, graph_nodes=10_000, **handlers):
        self.nodes = dict(nodes or {})
        super().__init__(
            repo=lambda p: (
                [{"r": self.nodes[p["repo"]], "commits": 0, "decisions": 0}]
                if p["repo"] in self.nodes
                else []
            ),
            repos_busy=[{"id": b} for b in busy],
            repos_added_since=[{"n": added_today}],
            graph_size=[{"n": graph_nodes}],
            repo_create=self._create,
            repo_added=lambda p: (
                [{"added": "added_at" in self.nodes[p["repo"]]}] if p["repo"] in self.nodes else []
            ),
            repo_queue=lambda p: self._set(p["repo"], status="QUEUED", stage="fetch", error=None),
            repo_fail=lambda p: self._set(p["repo"], status="ERROR", error=p["error"]),
            **handlers,
        )

    def _create(self, p):
        self.nodes[p["repo"]] = {
            "id": p["repo"],
            "status": "QUEUED",
            "stage": "fetch",
            "progress_pct": 0,
            "partial": True,
            "added_at": NOW,
            "added_by": p["login"],
            "keep_updated": p["keep_updated"],
        }
        return []

    def _set(self, repo, **props):
        self.nodes[repo] = {**self.nodes[repo], **props}
        return []


def add(graph, facts=None, dispatcher=None, **kw):
    return repos.add(
        graph,
        facts or FakeFacts(),
        dispatcher or FakeDispatcher(),
        NEW,
        keep_updated=kw.pop("keep_updated", True),
        login=kw.pop("login", "saanvi"),
        now=NOW,
    )


@pytest.mark.parametrize(
    "text",
    [
        "expressjs/express",
        "github.com/expressjs/express",
        "https://github.com/ExpressJS/Express.git",
        "https://www.github.com/expressjs/express/tree/master/lib/",
        "  http://github.com/expressjs/express/pulls  ",
    ],
)
def test_links_and_names_give_owner_slash_name(text):
    assert repos.parse_repo_input(text) == NEW


@pytest.mark.parametrize(
    "text",
    [
        "",
        "express",
        "expressjs/express/lib",  # a bare name must be exactly owner/name
        "https://gitlab.com/expressjs/express",
        "expressjs/..",
        "-bad/name",
        "owner/na me",
        "owner/name;rm -rf",
        "a" * 40 + "/name",  # GitHub owners have at most 39 characters
    ],
)
def test_anything_else_is_refused(text):
    with pytest.raises(HTTPException) as err:
        repos.parse_repo_input(text)
    assert err.value.status_code == 400


def test_the_estimate_caps_a_large_repo_to_its_most_discussed_prs():
    check = repos.estimate(NEW, PUBLIC, graph_nodes=10_000)
    assert (check.found, check.is_public, check.capped) == (True, True, True)
    assert (check.commits, check.pull_requests, check.issues) == (6_000, 3_000, 2_500)
    # 20 PRs at 1.5 calls each plus 5 for supersession.
    assert check.ai_calls == 35
    assert (check.minutes_low, check.minutes_high) == (6, 24)
    assert check.fits_free_tier


def test_a_small_repo_reads_what_it_has():
    small = repos.Facts(found=True, public=True, size_kb=500, commits=80, eligible=4)
    check = repos.estimate(NEW, small, graph_nodes=0)
    assert (check.capped, check.ai_calls, check.minutes_low) == (False, 11, 3)


def test_a_repo_that_would_overflow_the_free_graph_does_not_fit():
    assert not repos.estimate(NEW, PUBLIC, graph_nodes=199_000).fits_free_tier
    huge = repos.Facts(**{**PUBLIC.__dict__, "size_kb": repos.MAX_REPO_KB + 1})
    assert not repos.estimate(NEW, huge, graph_nodes=0).fits_free_tier


@pytest.mark.parametrize("facts", [repos.Facts(found=False), repos.Facts(found=True, public=False)])
def test_missing_and_private_repos_are_not_found(facts):
    check = repos.estimate(NEW, facts, graph_nodes=0)
    assert (check.found, check.ai_calls, check.fits_free_tier) == (False, 0, False)


def test_adding_queues_the_repo_and_starts_its_run():
    graph, dispatcher = RepoGraph(), FakeDispatcher()
    repo = add(graph, dispatcher=dispatcher)
    assert (repo.id, repo.status, repo.stage, repo.partial) == (NEW, "QUEUED", "fetch", True)
    assert dispatcher.started == [NEW]
    node = graph.nodes[NEW]
    assert (node["added_by"], node["keep_updated"]) == ("saanvi", True)


def test_a_repo_already_in_the_graph_is_not_added_twice():
    graph = RepoGraph({NEW: {"id": NEW, "status": "READY"}})
    with pytest.raises(HTTPException) as err:
        add(graph)
    assert err.value.status_code == 409


def test_only_one_repo_is_read_at_a_time():
    graph = RepoGraph(busy=["someone/else"])
    with pytest.raises(HTTPException) as err:
        add(graph)
    assert err.value.status_code == 409 and "someone/else" in err.value.detail
    # The busy check only counts runs that moved recently: a dead run stops blocking.
    since = next(p["since"] for c, p in graph.calls if "q:repos_busy" in c)
    assert since == (NOW - repos.STALE_AFTER).isoformat()


def test_the_daily_limit_is_kept():
    with pytest.raises(HTTPException) as err:
        add(RepoGraph(added_today=repos.DAILY_LIMIT))
    assert err.value.status_code == 429


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        (repos.Facts(found=False), 404),
        (repos.Facts(found=True, public=False), 400),
        (repos.Facts(found=True, public=True, size_kb=100, eligible=0), 400),
        (repos.Facts(**{**PUBLIC.__dict__, "size_kb": repos.MAX_REPO_KB + 1}), 400),
    ],
)
def test_missing_private_undiscussed_and_huge_repos_are_refused_before_anything_is_written(
    facts, status
):
    graph, dispatcher = RepoGraph(), FakeDispatcher()
    with pytest.raises(HTTPException) as err:
        add(graph, FakeFacts(facts), dispatcher)
    assert err.value.status_code == status
    assert NEW not in graph.nodes and dispatcher.started == []


def test_without_a_dispatch_token_nothing_is_written():
    graph = RepoGraph()
    with pytest.raises(HTTPException) as err:
        add(graph, dispatcher=FakeDispatcher(configured=False))
    assert err.value.status_code == 503
    assert NEW not in graph.nodes


def test_a_run_github_will_not_start_marks_the_repo_failed():
    graph = RepoGraph()
    with pytest.raises(HTTPException) as err:
        add(graph, dispatcher=FakeDispatcher(error=repos.DispatchError("GitHub answered 422")))
    assert err.value.status_code == 502
    assert graph.nodes[NEW]["status"] == "ERROR"
    assert "422" in graph.nodes[NEW]["error"]


def test_a_repo_added_here_runs_again():
    graph = RepoGraph({NEW: {"id": NEW, "status": "ERROR", "error": "x", "added_at": NOW}})
    dispatcher = FakeDispatcher()
    found = repos.reads.repo(graph, NEW)
    repo = repos.rerun(graph, dispatcher, found, now=NOW)
    assert (repo.status, repo.error, dispatcher.started) == ("QUEUED", None, [NEW])


def test_a_repo_the_team_read_by_hand_is_never_rerun_from_here():
    graph = RepoGraph({REPO: REPO_NODE})
    dispatcher = FakeDispatcher()
    with pytest.raises(HTTPException) as err:
        repos.rerun(graph, dispatcher, repos.reads.repo(graph, REPO), now=NOW)
    assert err.value.status_code == 409
    assert dispatcher.started == [] and graph.nodes[REPO] == REPO_NODE


def _github(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        for (method, path), answer in routes.items():
            if request.method == method and request.url.path == path:
                return answer(request) if callable(answer) else answer
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _commits(request):
    page = 120 if "since" in request.url.params else 6_000
    last = f'<https://api.github.com/repositories/1/commits?per_page=1&page={page}>; rel="last"'
    return httpx.Response(200, json=[{}], headers={"link": last})


def _search(request):
    q = request.url.params["q"]
    n = 9 if "comments:>=5" in q else 3_000 if "is:pr" in q else 2_500
    return httpx.Response(200, json={"total_count": n, "items": []})


def test_github_facts_come_from_the_repo_searches_and_commit_pages():
    gh = repos.GitHubFacts(
        _github(
            {
                ("GET", f"/repos/{NEW}"): httpx.Response(
                    200, json={"private": False, "visibility": "public", "size": 1_234}
                ),
                ("GET", f"/repos/{NEW}/commits"): _commits,
                ("GET", "/search/issues"): _search,
            }
        ),
        token="t",
    )
    assert gh.facts(NEW, NOW) == repos.Facts(
        found=True,
        public=True,
        size_kb=1_234,
        commits=6_000,
        commits_recent=120,
        pull_requests=3_000,
        issues=2_500,
        eligible=9,
    )


def test_github_facts_for_missing_and_private_repos():
    missing = repos.GitHubFacts(_github({}))
    assert missing.facts(NEW, NOW) == repos.Facts(found=False)
    private = repos.GitHubFacts(
        _github({("GET", f"/repos/{NEW}"): httpx.Response(200, json={"private": True})})
    )
    assert private.facts(NEW, NOW) == repos.Facts(found=True, public=False)


def test_github_rate_limits_become_a_503():
    limited = httpx.Response(403, json={}, headers={"x-ratelimit-remaining": "0"})
    gh = repos.GitHubFacts(_github({("GET", f"/repos/{NEW}"): limited}))
    with pytest.raises(HTTPException) as err:
        gh.facts(NEW, NOW)
    assert err.value.status_code == 503


def test_the_dispatcher_starts_ingest_yml_with_the_repo_as_input():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    d = repos.Dispatcher(
        httpx.Client(transport=httpx.MockTransport(handler)), "tok", "team/whycode", "main"
    )
    d.dispatch(NEW)
    [req] = seen
    assert req.url.path == "/repos/team/whycode/actions/workflows/ingest.yml/dispatches"
    assert req.headers["authorization"] == "Bearer tok"
    assert req.read() == b'{"ref":"main","inputs":{"repo":"expressjs/express"}}'


def test_the_dispatcher_reports_a_refusal():
    d = repos.Dispatcher(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(422))), "t", "a/b", "x"
    )
    with pytest.raises(repos.DispatchError):
        d.dispatch(NEW)


def test_the_dispatcher_reads_its_settings_from_the_environment(monkeypatch):
    monkeypatch.delenv("WHYCODE_DISPATCH_TOKEN", raising=False)
    assert not repos.Dispatcher.from_env(httpx.Client()).configured
    monkeypatch.setenv("WHYCODE_DISPATCH_TOKEN", "tok")
    d = repos.Dispatcher.from_env(httpx.Client())
    assert (d.configured, d.where, d.ref) == (True, repos.DEFAULT_DISPATCH_REPO, "main")


def test_the_routes_check_add_and_show_progress(monkeypatch):
    monkeypatch.setattr(repos, "GitHubFacts", lambda client, token: FakeFacts())
    dispatcher = FakeDispatcher()
    monkeypatch.setattr(repos.Dispatcher, "from_env", classmethod(lambda cls, c: dispatcher))
    graph = RepoGraph(
        health_counts=[{"label": "PullRequest", "n": 0}],
        health_links=[{"links": 0, "superseded": 0}],
    )
    c = client(graph)

    res = c.post("/api/repos/check", json={"input": "https://github.com/expressjs/express"})
    assert res.status_code == 200
    assert (res.json()["repo"], res.json()["ai_calls"]) == (NEW, 35)

    res = c.post("/api/repos", json={"repo": NEW, "keep_updated": False})
    assert (res.status_code, res.json()["status"]) == (200, "QUEUED")
    assert dispatcher.started == [NEW]

    res = c.get("/api/ingestion", params={"repo": NEW})
    assert res.status_code == 200
    states = [(s["stage"], s["state"]) for s in res.json()["stages"]]
    assert states == [
        ("fetch", "running"),
        ("parse", "queued"),
        ("link", "queued"),
        ("extract", "queued"),
        ("supersession", "queued"),
    ]

    assert c.post("/api/repos/check", json={"input": "not a repo"}).status_code == 400
    assert c.post("/api/repos/sync", json={"repo": "nobody/here"}).status_code == 404


def test_sync_and_reingest_refuse_the_hand_read_repo(monkeypatch):
    monkeypatch.setattr(repos.Dispatcher, "from_env", classmethod(lambda cls, c: FakeDispatcher()))
    c = client(RepoGraph({REPO: REPO_NODE}))
    for path in ("/api/repos/sync", "/api/repos/reingest"):
        assert c.post(path, json={"repo": REPO}).status_code == 409
