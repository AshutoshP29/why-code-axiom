import pytest
from neo4j.exceptions import ServiceUnavailable

from tests.api_fakes import CFG, CLS, FILE, FN, REPO, FakeGraph, assert_repo_filtered, client
from whycode.api import app as app_module
from whycode.api import reads
from whycode.config import ConfigError


def test_repos_lists_repo_nodes_with_counts():
    res = client(FakeGraph()).get("/api/repos")
    assert res.status_code == 200
    assert res.json() == [
        {
            "id": REPO,
            "status": "READY",
            "stage": "extract",
            "progress_pct": 100,
            "partial": True,
            "error": None,
            "last_synced_at": "2026-10-28T12:00:00Z",
            "commits_count": 3,
            "decisions_count": 1,
        }
    ]


def test_repo_defaults_for_missing_fields():
    graph = FakeGraph(repos=[{"r": {"id": "a/b", "stage": "weird"}, "commits": 0, "decisions": 0}])
    (repo,) = client(graph).get("/api/repos").json()
    assert (repo["status"], repo["stage"], repo["progress_pct"], repo["partial"]) == (
        "READY",
        None,
        100,
        False,
    )


@pytest.mark.parametrize(
    ("entity_id", "kind", "name", "qualified", "path"),
    [
        (
            FN,
            "function",
            "apparent_encoding",
            "Response.apparent_encoding",
            "src/requests/models.py",
        ),
        (CLS, "class", "Response", "Response", "src/requests/models.py"),
        (FILE, "file", "models.py", "models.py", "src/requests/models.py"),
        (CFG, "config", "DEFAULT_RETRIES", "DEFAULT_RETRIES", "src/requests/adapters.py"),
    ],
)
def test_get_entity(entity_id, kind, name, qualified, path):
    graph = FakeGraph()
    res = client(graph).get("/api/entities", params={"repo": REPO, "id": entity_id})
    assert res.status_code == 200
    assert res.json() == {
        "id": entity_id,
        "kind": kind,
        "name": name,
        "qualified_name": qualified,
        "path": path,
    }
    assert_repo_filtered(graph)


def test_module_entity_has_no_path():
    node = {"id": f"{REPO}#mod:requests", "name": "requests", "path": "src/requests"}
    assert reads.entity(node).model_dump() == {
        "id": f"{REPO}#mod:requests",
        "kind": "module",
        "name": "requests",
        "qualified_name": "requests",
        "path": None,
    }


@pytest.mark.parametrize(
    "entity_id",
    [
        f"{REPO}#fn:src/requests/models.py::nope",  # not in the graph
        "pallets/flask#fn:src/flask/app.py::Flask",  # another repo's id
        f"{REPO}#pr:5797",  # not a code entity
        "garbage",
    ],
)
def test_unknown_entity_is_404(entity_id):
    graph = FakeGraph()
    res = client(graph).get("/api/entities", params={"repo": REPO, "id": entity_id})
    assert res.status_code == 404
    assert_repo_filtered(graph)


def test_bad_repo_is_400_and_unknown_repo_404():
    c = client(FakeGraph())
    assert c.get("/api/entities/search", params={"repo": "nope", "q": "x"}).status_code == 400
    res = c.get("/api/entities/search", params={"repo": "pallets/flask", "q": "x"})
    assert res.status_code == 404
    assert res.json()["detail"] == "pallets/flask is not in the graph"


def test_repo_is_normalised():
    graph = FakeGraph()
    res = client(graph).get("/api/entities", params={"repo": "PSF/Requests", "id": FN})
    assert res.status_code == 200
    assert_repo_filtered(graph)


def test_search_scales_scores_and_filters_by_repo():
    hits = [
        {
            "node": {
                "id": FN,
                "name": "apparent_encoding",
                "qualified_name": "Response.apparent_encoding",
            },
            "score": 3.0,
        },
        {"node": {"id": CLS, "name": "Response"}, "score": 1.0},
        {"node": {"id": f"{REPO}#pr:1", "number": 1}, "score": 9.0},  # not code: dropped
    ]
    graph = FakeGraph(search=hits)
    res = client(graph).get(
        "/api/entities/search", params={"repo": REPO, "q": "apparent_encoding?"}
    )
    assert res.status_code == 200
    body = res.json()
    assert [(h["id"], h["kind"], h["score"]) for h in body] == [
        (FN, "function", 0.75),
        (CLS, "class", 0.5),
    ]
    search_params = [p for c, p in graph.calls if "q:search" in c][0]
    assert search_params == {"repo": REPO, "q": "apparent_encoding", "limit": 10}
    assert "WHERE node.repo = $repo" in [c for c, _ in graph.calls if "q:search" in c][0]
    assert_repo_filtered(graph)


def test_search_with_no_words_sends_no_query():
    graph = FakeGraph()
    res = client(graph).get("/api/entities/search", params={"repo": REPO, "q": "?? !!"})
    assert res.json() == []
    assert "search" not in graph.tags()


@pytest.mark.parametrize(
    ("text", "query"),
    [
        (
            "Why does Response.apparent_encoding use it?",
            "Why does Response.apparent_encoding use it",
        ),
        ('a:b (c) "d" ~e* -f', "a b c d e f"),
        ("...", ""),
    ],
)
def test_lucene_query_drops_operators(text, query):
    assert reads.lucene_query(text) == query


def test_scale_is_monotonic_and_bounded():
    assert reads.scale(0) == 0.0
    assert reads.scale(1) == 0.5
    assert 0 < reads.scale(0.1) < reads.scale(5) < reads.scale(50) <= 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/repos/check"),
        ("post", "/api/repos"),
        ("post", "/api/repos/sync"),
        ("post", "/api/repos/reingest"),
        ("get", "/api/ingestion"),
        ("get", "/api/evaluation"),
    ],
)
def test_not_implemented_stubs(method, path):
    res = getattr(client(FakeGraph()), method)(path, params={"repo": REPO})
    assert res.status_code == 501
    assert res.json() == {"detail": "not implemented yet"}


def test_cors_allows_the_dev_server():
    res = client(FakeGraph()).get("/api/repos", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client(FakeGraph()).get("/api/repos", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_graph_down_is_503_with_a_plain_message():
    def down(_cypher, _params):
        raise ServiceUnavailable("connection refused to secret-host")

    res = client(down).get("/api/repos")
    assert res.status_code == 503
    assert "not reachable" in res.json()["detail"]
    assert "secret-host" not in res.text


def test_config_error_is_503_naming_variables_only(monkeypatch):
    app_module._graph.cache_clear()
    monkeypatch.setenv(app_module.TARGET_ENV, "mars")
    from fastapi.testclient import TestClient

    res = TestClient(app_module.create_app()).get("/api/repos")
    assert res.status_code == 503
    assert res.json()["detail"] == "WHYCODE_GRAPH_TARGET must be 'aura' or 'test'"
    app_module._graph.cache_clear()


def test_target_test_uses_the_local_container(monkeypatch):
    made = []

    class FakeTarget:
        database = "neo4j"

        def driver(self):
            made.append(self)
            return "driver"

    monkeypatch.setenv(app_module.TARGET_ENV, "test")
    monkeypatch.setattr("whycode.graph.client.local_test_target", lambda: FakeTarget())
    app_module._graph.cache_clear()
    try:
        assert app_module._graph() == ("driver", "neo4j")
        assert callable(app_module.get_run())
    finally:
        app_module._graph.cache_clear()
    assert len(made) == 1


def test_target_aura_reads_settings(monkeypatch):
    monkeypatch.delenv(app_module.TARGET_ENV, raising=False)

    def no_settings():
        raise ConfigError("Configuration error (missing: NEO4J_URI).")

    monkeypatch.setattr("whycode.config.get_settings", no_settings)
    app_module._graph.cache_clear()
    with pytest.raises(ConfigError, match="NEO4J_URI"):
        app_module._graph()
    app_module._graph.cache_clear()


def test_lifespan_closes_the_driver(monkeypatch):
    closed = []

    class Driver:
        def close(self):
            closed.append(True)

    class FakeTarget:
        database = "neo4j"

        def driver(self):
            return Driver()

    monkeypatch.setenv(app_module.TARGET_ENV, "test")
    monkeypatch.setattr("whycode.graph.client.local_test_target", lambda: FakeTarget())
    app_module._graph.cache_clear()
    app_module._graph()
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()):
        pass
    assert closed == [True]
    assert app_module._graph.cache_info().currsize == 0
