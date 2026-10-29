"""The API against the local test Neo4j holding the psf/requests PR #5797 slice.

Load it first (no LLM calls):
    docker compose up -d
    uv run python -m whycode.slice --repo psf/requests --pr 5797 --target test --max-calls 0
"""

import pytest
from fastapi.testclient import TestClient

from whycode.api.app import create_app, get_gaps_or_none, get_run
from whycode.graph.queries import neo4j_runner

REPO = "psf/requests"
ANSWERED = f"{REPO}#fn:src/requests/models.py::Response.apparent_encoding"
REFUSED = f"{REPO}#fn:src/requests/__init__.py::check_compatibility"


@pytest.fixture(scope="module")
def api(neo4j_test):
    driver, database = neo4j_test
    run = neo4j_runner(driver, database)
    if not run("MATCH (r:Repo {id: $repo}) RETURN r.id AS id", {"repo": REPO}):
        pytest.fail(
            f"{REPO} is not in the test Neo4j; run: uv run python -m whycode.slice --repo "
            f"{REPO} --pr 5797 --target test --max-calls 0"
        )
    app = create_app()
    app.dependency_overrides[get_run] = lambda: run
    app.dependency_overrides[get_gaps_or_none] = lambda: None
    return TestClient(app)


def ask(api, entity_id, question="Why is it like this?"):
    res = api.post("/api/ask", json={"repo": REPO, "entity_id": entity_id, "question": question})
    assert res.status_code == 200, res.text
    return res.json()


def test_apparent_encoding_is_answered_with_evidence_quotes(api):
    a = ask(api, ANSWERED, "Why does apparent_encoding use charset_normalizer?")
    assert a["verdict"] in ("answered", "hedged")
    assert a["entity"]["id"] == ANSWERED
    assert a["decision"]["source"]["label"] == "PR #5797"
    assert a["evidence_chain"]
    assert all(step["excerpt"].strip() for step in a["evidence_chain"])
    assert all(
        step["source"]["url"].startswith("https://github.com/") for step in a["evidence_chain"]
    )
    assert a["decision"]["summary"] in a["answer_text"]


def test_check_compatibility_is_refused_with_known_facts(api):
    a = ask(api, REFUSED)
    assert a["verdict"] == "refused"
    assert a["known_facts"], "the commit that changed it should be listed"
    assert a["history_url"] == f"https://github.com/{REPO}/commits/HEAD/src/requests/__init__.py"
    assert "decision" not in a


def test_search_finds_apparent_encoding(api):
    res = api.get("/api/entities/search", params={"repo": REPO, "q": "apparent_encoding"})
    assert res.status_code == 200
    hits = res.json()
    assert ANSWERED in [h["id"] for h in hits]
    assert all(0 <= h["score"] <= 1 for h in hits)


def test_ask_without_entity_matches_by_search(api):
    a = ask(api, None, "Why does apparent_encoding use charset_normalizer?")
    assert a["matched_by"] == "search"
    assert a["entity"] is not None and a["match_score"] is not None


@pytest.mark.parametrize("path", ["/api/repos", "/api/overview", "/api/explorer", "/api/health"])
def test_screens_load(api, path):
    res = api.get(path, params={"repo": REPO})
    assert res.status_code == 200, res.text


def test_lineage_of_the_answered_function(api):
    res = api.get("/api/lineage", params={"repo": REPO, "entity_id": ANSWERED})
    assert res.status_code == 200
    body = res.json()
    assert body["decisions"]
    assert body["commit_total"] >= len(body["commits"])
