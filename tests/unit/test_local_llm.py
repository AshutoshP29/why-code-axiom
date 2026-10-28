import json

import httpx
import pytest

from tests.fakes import FakeProvider, MemoryLLMCache, StatusError
from tests.unit.test_config import FAKE_ENV
from whycode.config import load_settings
from whycode.llm.client import (
    Budget,
    BudgetExceededError,
    LLMClient,
    build_providers,
    classify_error,
)
from whycode.llm.providers import IncompleteResponseError, LocalHTTPError, LocalProvider


def ollama(reply=None, status=200, done_reason="stop", seen=None):
    """A fake Ollama /api/chat endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": "model 'x' not found"})
        body = {"message": {"role": "assistant", "content": reply}, "done_reason": done_reason}
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def test_local_provider_sends_json_mode_chat_and_returns_content():
    seen = []
    p = LocalProvider("qwen2.5:7b-instruct", transport=ollama('{"ok": true}', seen=seen))
    assert p.complete_json("sys", "user") == '{"ok": true}'
    body = seen[0]
    assert body["model"] == "qwen2.5:7b-instruct" and body["format"] == "json"
    assert body["stream"] is False and body["options"]["temperature"] == 0
    assert body["options"]["num_ctx"] >= 16384  # a whole chunk must fit
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_local_answer_cut_off_by_length_is_incomplete():
    p = LocalProvider("m", transport=ollama('{"decisions": [', done_reason="length"))
    with pytest.raises(IncompleteResponseError, match="stopped early: length"):
        p.complete_json("s", "u")


def test_local_empty_answer_is_incomplete():
    with pytest.raises(IncompleteResponseError, match="no text"):
        LocalProvider("m", transport=ollama("")).complete_json("s", "u")


def test_local_http_error_carries_status_for_fallback():
    p = LocalProvider("m", transport=ollama(status=404))
    with pytest.raises(LocalHTTPError) as info:
        p.complete_json("s", "u")
    assert info.value.status_code == 404 and classify_error(info.value) == "bad_request"


def test_local_server_down_counts_as_unavailable():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    p = LocalProvider("m", transport=httpx.MockTransport(refuse))
    with pytest.raises(httpx.ConnectError) as info:
        p.complete_json("s", "u")
    assert classify_error(info.value) == "unavailable"


# --- budget and ordering ------------------------------------------------------------------------


class FreeProvider(FakeProvider):
    counts_against_budget = False


def test_local_calls_do_not_use_the_api_budget():
    local = FreeProvider("local", "qwen", ['{"a": 1}', '{"a": 2}', '{"a": 3}'])
    client = LLMClient([local], MemoryLLMCache(), Budget(0))
    for i in range(3):
        client.complete_json("s", str(i), prompt_version="v")
    assert len(local.calls) == 3 and client.budget.used == 0 and client.api_calls == 3


def test_apis_down_and_budget_left_falls_back_to_local():
    gem = FakeProvider("gemini", "g", [StatusError(503)])
    local = FreeProvider("local", "qwen", ['{"ok": 1}'])
    r = LLMClient([gem, local], MemoryLLMCache(), Budget(5)).complete_json(
        "s", "u", prompt_version="v"
    )
    assert r.provider == "local" and r.text == '{"ok": 1}'


def test_spent_budget_skips_paid_providers_and_uses_the_free_one():
    gem = FakeProvider("gemini", "g", ['{"a": 1}'])
    local = FreeProvider("local", "qwen", ['{"a": 2}'])
    client = LLMClient([gem, local], MemoryLLMCache(), Budget(0))
    r = client.complete_json("s", "u", prompt_version="v")
    assert r.provider == "local" and gem.calls == [] and client.budget.used == 0


def test_spent_budget_with_only_paid_providers_raises_before_any_call():
    gem = FakeProvider("gemini", "g", ['{"a": 1}'])
    groq = FakeProvider("groq", "q", ['{"a": 2}'])
    client = LLMClient([gem, groq], MemoryLLMCache(), Budget(0))
    with pytest.raises(BudgetExceededError, match="no free provider"):
        client.complete_json("s", "u", prompt_version="v")
    assert gem.calls == [] and groq.calls == []


def test_budget_runs_out_mid_run_then_local_takes_over():
    gem = FakeProvider("gemini", "g", ['{"a": 1}', '{"a": 2}'])
    local = FreeProvider("local", "qwen", ['{"b": 1}'])
    client = LLMClient([gem, local], MemoryLLMCache(), Budget(1))
    assert client.complete_json("s", "1", prompt_version="v").provider == "gemini"
    assert client.complete_json("s", "2", prompt_version="v").provider == "local"
    assert len(gem.calls) == 1 and client.budget.used == 1


def settings(monkeypatch, **extra):
    for name, value in {**FAKE_ENV, **extra}.items():
        monkeypatch.setenv(name, value)
    return load_settings(_env_file=None)


def test_default_order_is_gemini_groq_local(monkeypatch):
    s = settings(monkeypatch, LOCAL_LLM_MODEL="qwen2.5:7b-instruct")
    assert [p.name for p in build_providers(s)] == ["gemini", "groq", "local"]


def test_local_is_skipped_when_no_model_is_set(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
    assert [p.name for p in build_providers(settings(monkeypatch))] == ["gemini", "groq"]


def test_order_comes_from_settings_or_override(monkeypatch):
    s = settings(monkeypatch, LOCAL_LLM_MODEL="q", LLM_PROVIDERS="local, groq")
    assert [p.name for p in build_providers(s)] == ["local", "groq"]
    assert [p.name for p in build_providers(s, "gemini")] == ["gemini"]


def test_unknown_or_empty_provider_list_is_an_error(monkeypatch):
    s = settings(monkeypatch)
    with pytest.raises(ValueError, match="unknown LLM provider 'openai'"):
        build_providers(s, "gemini,openai")
    monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="no LLM provider configured"):
        build_providers(settings(monkeypatch), "local")
