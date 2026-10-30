import pytest

from tests.fakes import FakeProvider, MemoryLLMCache, StatusError
from whycode.llm.cache import cache_key
from whycode.llm.client import (
    Budget,
    BudgetExceededError,
    LLMClient,
    LLMError,
    classify_error,
)
from whycode.llm.providers import IncompleteResponseError

V = "test-v1"


def make(gemini_replies=(), groq_replies=(), max_calls=10, **kw):
    gemini = FakeProvider("gemini", "gem-model", gemini_replies)
    groq = FakeProvider("groq", "groq-model", groq_replies)
    slept = []
    client = LLMClient(
        [gemini, groq], MemoryLLMCache(), Budget(max_calls), sleep=slept.append, **kw
    )
    return client, gemini, groq, slept


def ask(client, user="u", **kw):
    return client.complete_json("sys", user, prompt_version=V, **kw)


def test_second_identical_call_makes_zero_api_calls():
    client, gemini, groq, _ = make(['{"a": 1}'])
    first = ask(client)
    second = ask(client)
    assert first.text == second.text == '{"a": 1}'
    assert not first.cached and second.cached
    assert len(gemini.calls) == 1 and len(groq.calls) == 0
    assert client.api_calls == 1 and client.budget.used == 1


def test_cache_key_depends_on_version_model_and_input():
    base = cache_key("v1", "m", "x")
    assert base == cache_key("v1", "m", "x")
    assert (
        len({base, cache_key("v2", "m", "x"), cache_key("v1", "n", "x"), cache_key("v1", "m", "y")})
        == 4
    )
    assert cache_key("a", "bc", "d") != cache_key("ab", "c", "d")


def test_different_input_is_not_a_cache_hit():
    client, gemini, _, _ = make(['{"a": 1}', '{"a": 2}'])
    assert ask(client, "one").text == '{"a": 1}'
    assert ask(client, "two").text == '{"a": 2}'
    assert len(gemini.calls) == 2


@pytest.mark.parametrize("attr", ["code", "status_code"])
def test_gemini_rate_limit_falls_back_to_groq(attr):
    client, gemini, groq, slept = make([StatusError(429, attr)], ['{"from": "groq"}'])
    r = ask(client)
    assert r.provider == "groq" and r.text == '{"from": "groq"}'
    assert len(gemini.calls) == 1 and len(groq.calls) == 1
    assert slept == [] and client.budget.used == 2  # both attempts count


def test_fallback_answer_is_cached_under_the_model_that_gave_it():
    client, gemini, groq, _ = make([StatusError(503)], ['{"ok": 1}'])
    ask(client)
    again = ask(client)
    assert again.cached and again.provider == "groq"
    assert len(gemini.calls) == 1 and len(groq.calls) == 1


@pytest.mark.parametrize(
    "exc", [StatusError(503), StatusError(504), IncompleteResponseError("cut off"), TimeoutError()]
)
def test_overload_timeout_and_empty_also_fall_back(exc):
    client, _, groq, _ = make([exc], ['{"ok": 1}'])
    assert ask(client).provider == "groq"


def test_all_transient_failures_retry_whole_chain_after_backoff():
    client, gemini, groq, slept = make(
        [StatusError(429), '{"ok": 1}'], [StatusError(429)], backoff_s=5
    )
    r = ask(client)
    assert r.provider == "gemini" and slept == [5]
    assert len(gemini.calls) == 2 and len(groq.calls) == 1


def test_permanent_failures_do_not_retry_and_hide_details():
    client, _, _, slept = make([StatusError(400)], [StatusError(401)])
    with pytest.raises(LLMError) as info:
        ask(client)
    assert slept == []
    assert "bad_request" in str(info.value) and "auth" in str(info.value)


def test_redact_is_applied_to_failure_messages():
    client, _, _, _ = make(
        [StatusError(400)], [StatusError(400)], redact=lambda s: s.replace("gem-model", "***")
    )
    with pytest.raises(LLMError) as info:
        ask(client)
    assert "gem-model" not in str(info.value)


def test_budget_stops_at_max_calls():
    client, gemini, groq, _ = make(['{"a": 1}', '{"a": 2}', '{"a": 3}'], max_calls=2)
    ask(client, "1")
    ask(client, "2")
    with pytest.raises(BudgetExceededError):
        ask(client, "3")
    assert len(gemini.calls) == 2 and len(groq.calls) == 0


def test_budget_counts_failed_attempts_and_stops_mid_fallback():
    client, gemini, groq, _ = make([StatusError(429)], ['{"a": 1}'], max_calls=1)
    with pytest.raises(BudgetExceededError):
        ask(client)
    assert len(gemini.calls) == 1 and len(groq.calls) == 0


def test_cache_hit_needs_no_budget():
    client, _, _, _ = make(['{"a": 1}'], max_calls=1)
    ask(client)
    assert ask(client).cached  # budget is spent, but the cache still answers


def test_dry_run_makes_no_call_and_uses_no_budget():
    client, gemini, groq, _ = make(['{"a": 1}'])
    r = ask(client, dry_run=True)
    assert r.dry_run and r.text is None and r.model == "gem-model"
    assert gemini.calls == groq.calls == [] and client.budget.used == 0


def test_dry_run_reports_cache_hits():
    client, _, _, _ = make(['{"a": 1}'])
    ask(client)
    r = ask(client, dry_run=True)
    assert r.cached and r.text == '{"a": 1}'


@pytest.mark.parametrize(
    "exc, reason",
    [
        (StatusError(429), "rate_limit"),
        (StatusError(503, "status_code"), "unavailable"),
        (StatusError(403), "auth"),
        (StatusError(404), "bad_request"),
        (TimeoutError(), "timeout"),
        (type("APITimeoutError", (Exception,), {})(), "timeout"),
        (type("RateLimitError", (Exception,), {})(), "rate_limit"),
        (type("APIConnectionError", (Exception,), {})(), "unavailable"),
        (ValueError("x"), "other"),
    ],
)
def test_classify_error(exc, reason):
    assert classify_error(exc) == reason


def test_requires_a_provider():
    with pytest.raises(ValueError):
        LLMClient([], MemoryLLMCache(), Budget(1))


def test_truncated_json_falls_back_and_is_never_cached():
    cut_off = '{"decisions": [{"summary": "half an ans'
    client, gemini, groq, _ = make([cut_off], ['{"ok": 1}'])
    r = ask(client)
    assert r.provider == "groq" and r.text == '{"ok": 1}'
    assert all(row["response"] != cut_off for row in client.cache.rows.values())
    assert len(client.cache.rows) == 1


def test_invalid_json_from_every_provider_raises():
    client, _, _, slept = make(["not json"], ["still not json"])
    with pytest.raises(LLMError, match="invalid_json"):
        ask(client)
    assert slept == [] and client.cache.rows == {}  # not transient: no retry round, no caching


class _Resp:
    def __init__(self, headers):
        self.headers = headers


def rate_limited(after):
    exc = StatusError(429, "status_code")
    exc.response = _Resp({"retry-after": str(after)})
    return exc


def test_waits_as_long_as_the_provider_asks():
    client, _, _, slept = make([StatusError(503), '{"ok": 1}'], [rate_limited(45)], backoff_s=5)
    assert ask(client).text == '{"ok": 1}'
    assert slept == [45.0]


def test_rate_limit_longer_than_max_wait_switches_the_provider_off_for_that_long():
    now = [0.0]
    gemini = FakeProvider(
        "gemini", "g", [StatusError(503), '{"a": 1}', StatusError(503), '{"a": 2}']
    )
    groq = FakeProvider("groq", "q", [rate_limited(900), '{"back": 1}'])
    slept = []
    client = LLMClient(
        [gemini, groq],
        MemoryLLMCache(),
        Budget(10),
        backoff_s=5,
        max_wait_s=120,
        sleep=slept.append,
        clock=lambda: now[0],
    )
    assert ask(client, "1").provider == "gemini"
    assert slept == [5.0]  # the normal backoff, not 900s and not the 120s cap
    assert client.tripped == {"groq"}
    assert ask(client, "2").provider == "gemini"
    assert len(groq.calls) == 1  # no call spent on groq while it is off
    now[0] = 901.0
    assert client.tripped == set()


def test_rate_limit_within_max_wait_keeps_the_provider_on():
    client, _, _, slept = make(
        [StatusError(503), '{"ok": 1}'], [rate_limited(100)], backoff_s=5, max_wait_s=120
    )
    ask(client)
    assert slept == [100.0] and client.tripped == set()


def test_failure_message_includes_short_provider_text():
    client, _, _, _ = make([StatusError(400)], [StatusError(400)])
    with pytest.raises(LLMError, match="HTTP 400"):
        ask(client)


def test_breaker_skips_a_provider_after_repeated_outages():
    client, gemini, groq, _ = make([StatusError(503)] * 5, ['{"a": 1}', '{"a": 2}', '{"a": 3}'])
    for i in range(3):
        assert ask(client, str(i)).provider == "groq"
    assert len(gemini.calls) == 2  # third request skipped Gemini entirely
    assert client.tripped == {"gemini"} and client.budget.used == 5


def test_breaker_streak_resets_on_success():
    # gemini: fail, succeed, fail. Without the reset the two failures would trip it (trip_after=2).
    client, gemini, _, _ = make([StatusError(503), '{"ok": 1}', StatusError(503)], [])
    assert ask(client, "a").provider == "groq"
    assert ask(client, "b").provider == "gemini"
    assert ask(client, "c").provider == "groq"
    assert client.tripped == set() and len(gemini.calls) == 3


def test_rate_limits_with_successes_between_never_trip_the_breaker():
    gemini = [StatusError(429), StatusError(429), '{"ok": 1}'] * 2
    client, _, groq, _ = make(gemini, ['{"a": 1}'] * 4)
    for i in range(4):
        ask(client, str(i))
    assert client.tripped == set()


def test_used_up_quota_with_no_hint_switches_the_provider_off_after_three():
    # Gemini's "exceeded your current quota" 429 carries no retry-after.
    client, gemini, groq, _ = make([StatusError(429)] * 9, ['{"a": 1}'] * 9)
    for i in range(5):
        assert ask(client, str(i)).provider == "groq"
    assert len(gemini.calls) == 3 and client.tripped == {"gemini"}


def test_all_providers_tripped_fails_fast_without_calls():
    client, gemini, groq, _ = make([StatusError(503)] * 9, [StatusError(503)] * 9, backoff_s=0)
    with pytest.raises(LLMError):
        ask(client, "a")
    used = client.budget.used
    with pytest.raises(LLMError, match="switched off"):
        ask(client, "b")
    assert client.budget.used == used  # no further calls once everything is tripped


def test_too_large_is_reported_in_error_reasons():
    client, _, _, slept = make([StatusError(413)], [StatusError(413, "status_code")])
    with pytest.raises(LLMError) as info:
        ask(client)
    assert info.value.reasons == ("too_large", "too_large") and slept == []


def test_breaker_lets_a_provider_back_in_after_the_cooldown():
    now = [0.0]
    gemini = FakeProvider("gemini", "g", [StatusError(503), StatusError(503), '{"back": 1}'])
    groq = FakeProvider("groq", "q", ['{"a": 1}', '{"a": 2}', '{"a": 3}'])
    client = LLMClient(
        [gemini, groq], MemoryLLMCache(), Budget(20), cooldown_s=600, clock=lambda: now[0]
    )
    ask(client, "1")
    ask(client, "2")
    assert client.tripped == {"gemini"}
    ask(client, "3")  # still cooling down: gemini is not asked
    assert len(gemini.calls) == 2
    now[0] = 601.0
    assert client.tripped == set()
    assert ask(client, "4").provider == "gemini"  # recovered


def test_after_the_cooldown_one_more_failure_switches_it_off_again():
    now = [0.0]
    gemini = FakeProvider("gemini", "g", [StatusError(503)] * 3)
    client = LLMClient(
        [gemini, FakeProvider("groq", "q")], MemoryLLMCache(), Budget(20), clock=lambda: now[0]
    )
    ask(client, "1")
    ask(client, "2")
    now[0] = 601.0
    ask(client, "3")
    assert client.tripped == {"gemini"} and len(gemini.calls) == 3


def test_all_switched_off():
    client = LLMClient(
        [FakeProvider("gemini", "g", [StatusError(503)] * 9)],
        MemoryLLMCache(),
        Budget(20),
        backoff_s=0,
        sleep=lambda s: None,
    )
    assert not client.all_switched_off()
    with pytest.raises(LLMError):
        ask(client, "1")
    assert client.all_switched_off()
