import pytest
from fastapi import HTTPException

from tests.api_fakes import REPO, FakeGraph, client, q5a_row
from whycode.api import limits

ASK = {"repo": REPO, "entity_id": None, "question": "Why does apparent_encoding exist?"}


def test_memory_calls_count_per_user_and_overall_in_the_window():
    calls = limits.MemoryCalls()
    calls.record("guard", "user:a")
    calls.record("guard", "user:b")
    calls.record("ask", "user:a")
    assert calls.count("guard", "user:a", 60) == (1, 2)
    assert calls.count("guard", "user:c", 60) == (0, 2)
    assert calls.count("guard", "user:a", 0) == (0, 0)


def test_enforce_refuses_over_the_user_or_overall_limit(monkeypatch):
    monkeypatch.setitem(limits.LIMITS, "guard", limits.Limit(2, 3, 60, "slow down"))
    calls = limits.MemoryCalls()
    limits.enforce(calls, "guard", "user:a")
    limits.enforce(calls, "guard", "user:a")
    with pytest.raises(HTTPException) as err:
        limits.enforce(calls, "guard", "user:a")
    assert err.value.status_code == 429 and err.value.detail == "slow down"
    limits.enforce(calls, "guard", "user:b")  # the third call overall
    with pytest.raises(HTTPException):
        limits.enforce(calls, "guard", "user:c")  # over the overall cap


def test_asking_is_limited_per_caller(monkeypatch):
    monkeypatch.setitem(limits.LIMITS, "ask", limits.Limit(2, None, 60, "too many questions"))
    calls = limits.MemoryCalls()
    graph = FakeGraph(search=[], q5a=[q5a_row()])
    c = client(graph, {limits.get_calls: lambda: calls})
    first = c.post("/api/ask", json=ASK, headers={"X-Forwarded-For": "1.1.1.1"})
    assert first.status_code == 200
    assert c.post("/api/ask", json=ASK, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    third = c.post("/api/ask", json=ASK, headers={"X-Forwarded-For": "1.1.1.1"})
    assert third.status_code == 429 and third.json()["detail"] == "too many questions"
    other = c.post("/api/ask", json=ASK, headers={"X-Forwarded-For": "2.2.2.2"})
    assert other.status_code == 200


def test_unknown_repo_is_not_counted():
    calls = limits.MemoryCalls()
    c = client(FakeGraph(), {limits.get_calls: lambda: calls})
    assert c.post("/api/ask", json={**ASK, "repo": "a/b"}).status_code == 404
    assert calls.count("ask", "ip:testclient", 60) == (0, 0)


class FakeStore:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return self

    def fetchone(self):
        return (3, 9)


def test_postgres_calls_sql():
    store = FakeStore()
    calls = limits.PgCalls(store)
    assert "CREATE TABLE IF NOT EXISTS api_calls" in store.sql[0][0]
    assert calls.count("guard", "user:a", 3600) == (3, 9)
    assert store.sql[-1][1] == ("user:a", "guard", 3600)
    calls.record("guard", "user:a")
    assert store.sql[-1][1] == ("guard", "user:a") or "DELETE" in store.sql[-1][0]
