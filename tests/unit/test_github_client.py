import httpx
import pytest

from whycode.ingest.github import GitHubClient, GitHubError, RateLimitError

TOKEN = "fake-token-tok123"


class Script:
    """Returns queued responses in order and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(script, now=1000.0, **kw):
    slept = []
    gh = GitHubClient(
        TOKEN,
        transport=httpx.MockTransport(script),
        sleep=slept.append,
        clock=lambda: now,
        **kw,
    )
    return gh, slept


def ok(json=None, **headers):
    return httpx.Response(200, json=json if json is not None else {}, headers=headers)


def test_sends_auth_and_api_headers():
    s = Script(ok({"a": 1}))
    gh, _ = client(s)
    assert gh.get("/x").data == {"a": 1}
    h = s.requests[0].headers
    assert h["Authorization"] == f"Bearer {TOKEN}"
    assert h["X-GitHub-Api-Version"] == "2022-11-28"


def test_etag_round_trip_and_304():
    s = Script(ok({"v": 1}, ETag='"e1"'), httpx.Response(304))
    gh, _ = client(s)
    first = gh.get("/x")
    assert first.status == 200 and first.etag == '"e1"'
    second = gh.get("/x", etag=first.etag)
    assert second.status == 304 and second.data is None
    assert s.requests[1].headers["If-None-Match"] == '"e1"'
    assert gh.stats.not_modified == 1


def test_primary_rate_limit_waits_until_reset_then_retries():
    limited = httpx.Response(
        403,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1100"},
    )
    s = Script(limited, ok({"done": True}))
    gh, slept = client(s, now=1000.0)
    assert gh.get("/x").data == {"done": True}
    assert slept == [101.0]  # reset - now + 1


def test_secondary_rate_limit_honours_retry_after():
    s = Script(httpx.Response(429, headers={"Retry-After": "7"}), ok())
    gh, slept = client(s)
    gh.get("/x")
    assert slept == [7.0]


def test_secondary_limit_without_hint_waits_a_minute():
    s = Script(
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}), ok()
    )
    gh, slept = client(s)
    gh.get("/x")
    assert slept == [60.0]


def test_wait_longer_than_max_raises_instead_of_sleeping():
    limited = httpx.Response(
        403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "999999"}
    )
    gh, slept = client(Script(limited), max_wait=60)
    with pytest.raises(RateLimitError):
        gh.get("/x")
    assert slept == []


def test_low_remaining_budget_pauses_before_next_call():
    s = Script(ok({}, **{"X-RateLimit-Remaining": "2", "X-RateLimit-Reset": "1030"}))
    gh, slept = client(s, now=1000.0, low_water=5)
    gh.get("/x")
    assert slept == [31.0]


def test_server_errors_retry_with_backoff():
    s = Script(httpx.Response(502), httpx.Response(503), ok({"ok": 1}))
    gh, slept = client(s)
    assert gh.get("/x").data == {"ok": 1}
    assert slept == [1.0, 2.0] and gh.stats.retries == 2


def test_network_error_retries_then_gives_up():
    err = httpx.ConnectError("boom")
    gh, slept = client(Script(err, err, err, err), max_retries=3)
    with pytest.raises(GitHubError, match="network error"):
        gh.get("/x")
    assert len(slept) == 3


def test_not_found_raises_without_token():
    gh, _ = client(Script(httpx.Response(404, json={"message": "Not Found"})))
    with pytest.raises(GitHubError) as info:
        gh.get("/repos/a/b/pulls/1")
    assert "404" in str(info.value) and TOKEN not in str(info.value)


def test_forbidden_without_rate_limit_is_not_retried():
    gh, slept = client(Script(httpx.Response(403, json={"message": "Resource not accessible"})))
    with pytest.raises(GitHubError, match="403"):
        gh.get("/x")
    assert slept == []
