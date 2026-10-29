from datetime import UTC, datetime

import psycopg
import pytest

from tests.api_fakes import CFG, FN, REPO, FakeGraph, assert_repo_filtered, client
from whycode.api import app as app_module
from whycode.api import reads
from whycode.api.gaps import GapStore, GapSummary
from whycode.api.models import Repo

FLAGGED = datetime(2026, 10, 28, 9, tzinfo=UTC)
LABEL_COUNTS = [
    {"label": "Repo", "n": 1},
    {"label": "Commit", "n": 3},
    {"label": "PullRequest", "n": 1},
    {"label": "Issue", "n": 2},
    {"label": "Decision", "n": 2},
    {"label": "Person", "n": 7},
    {"label": "File", "n": 4},
    {"label": "Class", "n": 5},
    {"label": "Function", "n": 100},
    {"label": "ConfigKey", "n": 1},
]


class FakeGaps:
    def __init__(self):
        self.rows: list[tuple[str, str, str, datetime]] = []

    def add(self, repo, entity_id, question):
        self.rows.append((repo, entity_id, question, FLAGGED))

    def summaries(self, repo, entity_id=None):
        out = {}
        for r, e, q, at in self.rows:
            if r == repo and entity_id in (None, e):
                prev = out.get(e)
                out[e] = GapSummary(e, (prev.flags if prev else 0) + 1, q, at)
        return list(out.values())


def health_graph():
    return FakeGraph(health_counts=LABEL_COUNTS, health_links=[{"links": 12, "superseded": 0}])


def test_health_counts_stages_gaps_and_evaluation():
    gaps = FakeGaps()
    gaps.add(REPO, FN, "Why apparent_encoding?")
    gaps.add(REPO, FN, "Why charset_normalizer?")
    gaps.add(REPO, f"{REPO}#fn:gone.py::x", "Gone from the graph")
    gaps.add("pallets/flask", CFG, "Other repo")
    graph = health_graph()
    res = client(graph, {app_module.get_gaps_or_none: lambda: gaps}).get(
        "/api/health", params={"repo": REPO}
    )
    assert res.status_code == 200
    h = res.json()
    assert h["last_ingest_at"] == "2026-10-28T12:00:00Z"
    assert h["counts"] == {
        "commits": 3,
        "issues": 2,
        "entities": 110,
        "pull_requests": 1,
        "decisions": 2,
        "people": 7,
    }
    assert [(s["stage"], s["state"], s["headline"]) for s in h["stages"]] == [
        ("fetch", "done", "1 PRs"),
        ("parse", "done", "110 entities"),
        ("link", "done", "12 links"),
        ("extract", "done", "2 decisions"),
        ("supersession", "queued", "0 found"),
    ]
    assert [(g["entity"]["id"], g["flags"], g["last_question"]) for g in h["gap_queue"]] == [
        (FN, 2, "Why charset_normalizer?")
    ]
    assert h["evaluation"]["measured"] is False
    assert all(r["whycode"] is None for r in h["evaluation"]["rows"])
    assert_repo_filtered(graph)


def test_health_without_postgres_has_an_empty_gap_queue():
    res = client(health_graph(), {app_module.get_gaps_or_none: lambda: None}).get(
        "/api/health", params={"repo": REPO}
    )
    assert res.status_code == 200
    assert res.json()["gap_queue"] == []


def repo(**kw):
    base = {
        "id": REPO,
        "status": "READY",
        "stage": "extract",
        "progress_pct": 100,
        "partial": False,
        "error": None,
        "last_synced_at": None,
        "commits_count": 0,
        "decisions_count": 0,
    }
    return Repo(**{**base, **kw})


HEADLINES = dict.fromkeys(("fetch", "parse", "link", "extract", "supersession"), "")


@pytest.mark.parametrize(
    ("kw", "states"),
    [
        (
            {"status": "INGESTING", "stage": "link", "progress_pct": 40},
            ["done", "done", "running", "queued", "queued"],
        ),
        (
            {"status": "ERROR", "stage": "fetch", "progress_pct": 5},
            ["error", "queued", "queued", "queued", "queued"],
        ),
        ({"status": "READY", "stage": None}, ["done"] * 5),
        ({"status": "QUEUED", "stage": None, "progress_pct": 0}, ["queued"] * 5),
    ],
)
def test_stage_states(kw, states):
    out = reads.stages(repo(**kw), HEADLINES)
    assert [s.state for s in out] == states
    running = [s for s in out if s.state in ("running", "error")]
    assert all(s.progress_pct == kw["progress_pct"] for s in running)


def test_flag_gap_stores_it_and_returns_the_entity_summary():
    gaps = FakeGaps()
    c = client(FakeGraph(), {app_module.get_gaps: lambda: gaps})
    body = {"repo": "PSF/requests", "entity_id": FN, "question": "Missing context?"}
    first = c.post("/api/gaps", json=body)
    second = c.post("/api/gaps", json={**body, "question": "Still missing"})
    assert first.status_code == second.status_code == 200
    assert gaps.rows[0][:3] == (REPO, FN, "Missing context?")
    assert second.json() == {
        "entity": {
            "id": FN,
            "kind": "function",
            "name": "apparent_encoding",
            "qualified_name": "Response.apparent_encoding",
            "path": "src/requests/models.py",
        },
        "flags": 2,
        "last_question": "Still missing",
        "last_flagged_at": "2026-10-28T09:00:00Z",
    }


def test_flag_gap_on_unknown_entity_stores_nothing():
    gaps = FakeGaps()
    res = client(FakeGraph(), {app_module.get_gaps: lambda: gaps}).post(
        "/api/gaps", json={"repo": REPO, "entity_id": f"{REPO}#fn:a.py::x", "question": "q"}
    )
    assert res.status_code == 404
    assert gaps.rows == []


def test_flag_gap_when_postgres_is_down_is_503():
    def down():
        raise psycopg.OperationalError("connection to server at secret failed")

    res = client(FakeGraph(), {app_module.get_gaps: down}).post(
        "/api/gaps", json={"repo": REPO, "entity_id": FN, "question": "q"}
    )
    assert res.status_code == 503
    assert res.json()["detail"] == "The gap store (Postgres) is not reachable."


class FakeCursor:
    def __init__(self, rows, rowcount=0):
        self.rows, self.rowcount = rows, rowcount

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows=()):
        self.sql: list[tuple[str, tuple]] = []
        self.rows, self.closed = list(rows), False

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return FakeCursor(self.rows, rowcount=len(self.rows))

    def close(self):
        self.closed = True


def test_gap_store_sql():
    conn = FakeConn(rows=[(FN, 2, "latest", FLAGGED)])
    store = GapStore(conn)
    store.ensure_schema()
    store.add(REPO, FN, "q")
    assert store.summaries(REPO) == [GapSummary(FN, 2, "latest", FLAGGED)]
    store.summaries(REPO, FN)
    assert store.delete_repo(REPO) == 1
    store.close()
    statements = [s for s, _ in conn.sql]
    assert "CREATE TABLE IF NOT EXISTS gaps" in statements[0]
    assert conn.sql[2][1] == (REPO, FN, "q")
    assert "WHERE repo = %s\n" in statements[3] and conn.sql[3][1] == (REPO,)
    assert "AND entity_id = %s" in statements[4] and conn.sql[4][1] == (REPO, FN)
    assert conn.closed


def test_gap_store_connect_creates_the_table(monkeypatch):
    conn = FakeConn()
    seen = {}

    def connect(dsn, **kw):
        seen.update(dsn=dsn, **kw)
        return conn

    monkeypatch.setattr(psycopg, "connect", connect)
    GapStore.connect("postgresql://x")
    assert seen == {"dsn": "postgresql://x", "autocommit": True, "connect_timeout": 10}
    assert "CREATE TABLE" in conn.sql[0][0]


def test_gap_store_dsn_per_target(monkeypatch):
    dsns = []
    monkeypatch.setattr(GapStore, "connect", classmethod(lambda cls, dsn: dsns.append(dsn) or "s"))
    monkeypatch.setenv(app_module.TARGET_ENV, "test")
    monkeypatch.delenv("WHYCODE_TEST_POSTGRES_DSN", raising=False)
    app_module._gap_store.cache_clear()
    assert app_module.get_gaps() == "s"
    app_module._gap_store.cache_clear()

    class Settings:
        class postgres_dsn:  # noqa: N801 - mimics SecretStr
            @staticmethod
            def get_secret_value():
                return "postgresql://aura-side"

    monkeypatch.setenv(app_module.TARGET_ENV, "aura")
    monkeypatch.setattr("whycode.config.get_settings", lambda: Settings)
    assert app_module.get_gaps_or_none() == "s"
    app_module._gap_store.cache_clear()
    assert dsns == [app_module.TEST_POSTGRES_DSN, "postgresql://aura-side"]


def test_gaps_or_none_swallows_connection_errors(monkeypatch):
    def fail(cls, dsn):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(GapStore, "connect", classmethod(fail))
    monkeypatch.setenv(app_module.TARGET_ENV, "test")
    app_module._gap_store.cache_clear()
    assert app_module.get_gaps_or_none() is None
    app_module._gap_store.cache_clear()


def test_lifespan_closes_the_gap_store(monkeypatch):
    closed = []

    class Store:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(GapStore, "connect", classmethod(lambda cls, dsn: Store()))
    monkeypatch.setenv(app_module.TARGET_ENV, "test")
    app_module._gap_store.cache_clear()
    app_module.get_gaps()
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()):
        pass
    assert closed == [True]
