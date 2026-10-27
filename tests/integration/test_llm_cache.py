from tests.fakes import FakeProvider
from tests.integration.conftest import TEST_REPO
from whycode.llm.cache import PgLLMCache, cache_key
from whycode.llm.client import Budget, LLMClient


def test_pg_cache_serves_second_call_without_api_call(raw_store):
    cache = PgLLMCache(raw_store.conn)
    cache.ensure_schema()
    cache.delete_repo(TEST_REPO)
    try:
        gem = FakeProvider("gemini", "gem-test", ['{"x": 1}'])
        client = LLMClient([gem], cache, Budget(5))
        first = client.complete_json("s", "u", prompt_version="it-v1", repo=TEST_REPO)
        # A fresh client (new process) with the same cache table still hits.
        client2 = LLMClient([FakeProvider("gemini", "gem-test")], cache, Budget(5))
        second = client2.complete_json("s", "u", prompt_version="it-v1", repo=TEST_REPO)
        assert not first.cached and second.cached and second.text == '{"x": 1}'
        assert client2.api_calls == 0
        assert cache.get(cache_key("it-v1", "gem-test", "s\n\nu")) == '{"x": 1}'
    finally:
        assert cache.delete_repo(TEST_REPO) == 1
