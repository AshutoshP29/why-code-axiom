"""Thin adapters over the Gemini and Groq SDKs: one JSON-mode call, own timeout, no SDK retries.

Retries and fallback live in LLMClient, so an SDK must never retry silently on its own.
"""

from typing import Protocol

DEFAULT_TIMEOUT_S = 90
# Groq's free tier counts input + requested max_tokens against a per-minute token cap; asking
# for 8192 made a ~6k-token prompt fail with 413 "request too large". 4096 leaves room.
MAX_OUTPUT_TOKENS = 4096
# Gemini counts its internal thinking tokens against this limit, so it needs far more room than
# the answer itself: with 8192, gemini-3-flash-preview cut a ~250-token answer off mid-JSON.
GEMINI_MAX_OUTPUT_TOKENS = 32768


class IncompleteResponseError(RuntimeError):
    """The provider answered but the text is missing or was cut off (length limit, blocked)."""


class Provider(Protocol):
    name: str
    model: str
    # Hosted APIs count against LLM_MAX_CALLS; a local model costs nothing and does not.
    counts_against_budget: bool

    def complete_json(self, system: str, user: str) -> str: ...


class GeminiProvider:
    name = "gemini"
    counts_against_budget = True

    def __init__(self, api_key: str, model: str, timeout_s: int = DEFAULT_TIMEOUT_S):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_s * 1000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )

    def complete_json(self, system: str, user: str) -> str:
        resp = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=self._types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0,
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
            ),
        )
        candidate = resp.candidates[0] if resp.candidates else None
        reason = getattr(getattr(candidate, "finish_reason", None), "name", None)
        if reason not in (None, "STOP"):
            raise IncompleteResponseError(f"{self.model} stopped early: {reason}")
        if not resp.text:
            raise IncompleteResponseError(f"{self.model} returned no text")
        return resp.text


class GroqProvider:
    name = "groq"
    counts_against_budget = True

    def __init__(self, api_key: str, model: str, timeout_s: int = DEFAULT_TIMEOUT_S):
        from groq import Groq

        self.model = model
        self._client = Groq(api_key=api_key, timeout=timeout_s, max_retries=0)

    def complete_json(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        choice = resp.choices[0]
        if choice.finish_reason not in (None, "stop"):
            raise IncompleteResponseError(f"{self.model} stopped early: {choice.finish_reason}")
        text = choice.message.content
        if not text:
            raise IncompleteResponseError(f"{self.model} returned no text")
        return text


class LocalHTTPError(RuntimeError):
    """A non-200 answer from the local model server; carries the status like the SDK errors."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class LocalProvider:
    """A model served by Ollama on this machine (default http://127.0.0.1:11434).

    Uses Ollama's native /api/chat with JSON mode. No rate limits or call budget, but slower than
    the hosted APIs, so the timeout is generous. num_ctx is raised from Ollama's small default so
    a whole chunk (about 6k tokens) plus the answer fits.
    """

    name = "local"
    counts_against_budget = False

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_s: int = 600,
        num_ctx: int = 16384,
        transport=None,
    ):
        import httpx

        self.model = model
        self.num_ctx = num_ctx
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)

    def complete_json(self, system: str, user: str) -> str:
        resp = self._http.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0, "num_ctx": self.num_ctx},
            },
        )
        if resp.status_code != 200:
            try:
                message = str(resp.json().get("error", ""))[:200]
            except Exception:
                message = resp.text[:200]
            raise LocalHTTPError(resp.status_code, message)
        data = resp.json()
        if data.get("done_reason") not in (None, "stop"):
            raise IncompleteResponseError(f"{self.model} stopped early: {data.get('done_reason')}")
        text = (data.get("message") or {}).get("content")
        if not text:
            raise IncompleteResponseError(f"{self.model} returned no text")
        return text
