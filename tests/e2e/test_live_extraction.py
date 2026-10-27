"""Live: one real LLM extraction on the short fixture thread. Costs 1 call (2 if Gemini fails).

The answer must validate against ExtractionResponse and pass the exact-quote check.
"""

from tests.fakes import FakeGitHub, MemoryRawStore, load_github_fixture
from whycode.config import get_settings
from whycode.extract.extractor import extract_thread
from whycode.extract.sources import load_thread
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubClient
from whycode.ingest.store import RawStore
from whycode.llm.cache import PgLLMCache
from whycode.llm.client import Budget, build_llm_client


def test_real_llm_extracts_a_verified_decision_from_fixture_thread():
    store = MemoryRawStore()
    routes = load_github_fixture("pr_1565.json")
    with GitHubClient("t", transport=FakeGitHub(routes).transport()) as gh:
        fetch_pr(gh, store, "test/fixture", 1565)
    thread = load_thread(store, "test/fixture", 1565)

    # Postgres cache: a paid answer is kept, so re-running this test costs nothing.
    settings = get_settings()
    store_pg = RawStore.connect(settings.postgres_dsn.get_secret_value())
    try:
        cache = PgLLMCache(store_pg.conn)
        cache.ensure_schema()
        llm = build_llm_client(settings, cache, Budget(3))
        result = extract_thread(thread, llm)
    finally:
        store_pg.close()

    assert result.failed_chunks == [], result.failed_chunks
    assert result.decisions, f"no verified decision; rejections: {result.rejections}"
    for d in result.decisions:
        assert d.evidence  # every kept decision has at least one verified quote
        for e in d.evidence:
            assert e.source.text[e.span.start : e.span.end].split() == e.quote.split()
