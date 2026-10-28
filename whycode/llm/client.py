"""llm_client: the only way WhyCode talks to an LLM.

- Providers are tried in order (Gemini, then Groq); any provider error falls through to the next.
- Every response is cached by sha256(prompt_version + model + input); a hit costs no call.
- A hard budget (LLM_MAX_CALLS) counts every hosted-API attempt, successful or not. Once it
  is spent, hosted providers are skipped and a free local provider (if any) still answers;
  with none left, BudgetExceededError is raised before any call.
- A reply that is cut off or is not valid JSON counts as a failed attempt: it is never cached,
  and the next provider is tried.
- Circuit breaker: a provider that is unavailable or times out trip_after times in a row is
  skipped for the rest of the run, so a dead provider stops costing a call per request.
- If every provider failed for a transient reason (rate limit, overload, timeout, cut-off reply),
  the whole chain is retried after a backoff, up to max_rounds.
- dry_run returns what would be sent and makes no call.
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from whycode.llm.cache import cache_key
from whycode.llm.providers import Provider

log = logging.getLogger(__name__)

TRANSIENT = {"rate_limit", "unavailable", "timeout", "empty"}
TRIPS_BREAKER = {"unavailable", "timeout"}  # not rate_limit: that one says when to come back


class LLMError(RuntimeError):
    def __init__(self, message: str, reasons: Sequence[str] = ()):
        super().__init__(message)
        self.reasons = tuple(reasons)  # classify_error() reason of every failed attempt


class BudgetExceededError(LLMError):
    pass


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, **fields) -> None: ...


@dataclass
class Budget:
    max_calls: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.used)

    def take(self) -> None:
        if self.used >= self.max_calls:
            raise BudgetExceededError(f"LLM call budget of {self.max_calls} is used up")
        self.used += 1


@dataclass(frozen=True)
class LLMResult:
    text: str | None  # None only for dry runs
    provider: str | None
    model: str
    cached: bool
    dry_run: bool = False


def classify_error(exc: BaseException) -> str:
    """Map SDK exceptions to a small set of reasons, without depending on SDK classes."""
    name = type(exc).__name__
    if name == "IncompleteResponseError":
        return "empty"
    if name == "JSONDecodeError":
        return "invalid_json"
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(code, int):
        if code == 429:
            return "rate_limit"
        if code in (500, 502, 503, 504):
            return "unavailable"
        if code == 413:
            return "too_large"  # the request itself exceeds a provider limit; splitting helps
        if code in (401, 403):
            return "auth"
        return "bad_request"
    if "RateLimit" in name:
        return "rate_limit"
    if "Timeout" in name:
        return "timeout"
    if "Connect" in name:  # ConnectionError, APIConnectionError, httpx.ConnectError
        return "unavailable"
    return "other"


def retry_after_seconds(exc: BaseException) -> float | None:
    """The provider's own retry-after hint, if the SDK exposes the HTTP response."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        return float(headers.get("retry-after")) if headers else None
    except (TypeError, ValueError):
        return None


def _short(exc: BaseException, limit: int = 160) -> str:
    return " ".join(str(exc).split())[:limit]


class LLMClient:
    def __init__(
        self,
        providers: Sequence[Provider],
        cache: Cache,
        budget: Budget,
        *,
        max_rounds: int = 3,
        backoff_s: float = 20.0,
        max_wait_s: float = 120.0,
        trip_after: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        redact: Callable[[str], str] = lambda s: s,
    ):
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers, self.cache, self.budget = list(providers), cache, budget
        self.max_rounds, self.backoff_s, self.max_wait_s = max_rounds, backoff_s, max_wait_s
        self._sleep, self._redact = sleep, redact
        self.trip_after = trip_after
        self._down_streak: dict[str, int] = {}
        self.tripped: set[str] = set()
        self.api_calls = 0
        self.cache_hits = 0

    def is_cached(self, system: str, user: str, *, prompt_version: str) -> bool:
        """True if any provider's answer to this exact request is cached. Never calls an API."""
        prompt_input = f"{system}\n\n{user}"
        return any(
            self.cache.get(cache_key(prompt_version, p.model, prompt_input)) is not None
            for p in self.providers
        )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        prompt_version: str,
        repo: str | None = None,
        dry_run: bool = False,
    ) -> LLMResult:
        prompt_input = f"{system}\n\n{user}"
        for p in self.providers:  # a cached answer from any provider is good enough
            hit = self.cache.get(cache_key(prompt_version, p.model, prompt_input))
            if hit is not None:
                self.cache_hits += 1
                return LLMResult(hit, p.name, p.model, cached=True, dry_run=dry_run)
        if dry_run:
            return LLMResult(None, None, self.providers[0].model, cached=False, dry_run=True)

        failures: list[str] = []
        all_reasons: list[str] = []
        for round_no in range(self.max_rounds):
            reasons, hints = [], []
            live = [p for p in self.providers if p.name not in self.tripped]
            if not live:
                failures.append("every provider is switched off for this run (unavailable)")
                break
            attempted = 0
            for p in live:
                if getattr(p, "counts_against_budget", True):
                    if self.budget.remaining == 0:
                        continue  # spent: skip hosted providers, a free local one may still answer
                    self.budget.take()
                attempted += 1
                self.api_calls += 1
                try:
                    text = p.complete_json(system, user)
                    json.loads(text)  # a truncated or chatty reply must not be cached
                except Exception as exc:
                    reason = classify_error(exc)
                    reasons.append(reason)
                    all_reasons.append(reason)
                    hints.append(retry_after_seconds(exc) or 0.0)
                    msg = self._redact(
                        f"{p.name}/{p.model}: {reason} ({type(exc).__name__}: {_short(exc)})"
                    )
                    failures.append(msg)
                    log.warning("LLM call failed: %s; trying next provider", msg)
                    self._note_failure(p.name, reason)
                    continue
                self._down_streak[p.name] = 0
                self.cache.put(
                    cache_key(prompt_version, p.model, prompt_input),
                    response=text,
                    provider=p.name,
                    model=p.model,
                    prompt_version=prompt_version,
                    repo=repo,
                )
                return LLMResult(text, p.name, p.model, cached=False)
            if attempted == 0:
                raise BudgetExceededError(
                    f"LLM call budget of {self.budget.max_calls} is used up "
                    "and no free provider is available"
                )
            if not set(reasons) <= TRANSIENT or round_no == self.max_rounds - 1:
                break
            # Wait as long as the providers asked (Groq says exactly), within max_wait_s.
            wait = min(self.max_wait_s, max(self.backoff_s * (2**round_no), *hints))
            log.warning("all providers failed transiently; retrying in %.0fs", wait)
            self._sleep(wait)
        raise LLMError("all LLM providers failed: " + "; ".join(failures), all_reasons)

    def _note_failure(self, name: str, reason: str) -> None:
        if reason not in TRIPS_BREAKER:
            self._down_streak[name] = 0
            return
        self._down_streak[name] = self._down_streak.get(name, 0) + 1
        if self._down_streak[name] >= self.trip_after and name not in self.tripped:
            self.tripped.add(name)
            log.warning(
                "%s unavailable %d times in a row; skipping it for this run",
                name,
                self._down_streak[name],
            )


PROVIDER_NAMES = ("gemini", "groq", "local")


def build_providers(settings, order: str | None = None) -> list:
    """Providers in the order given (default LLM_PROVIDERS). "local" is skipped when
    LOCAL_LLM_MODEL is not set; an unknown name is an error."""
    from whycode.llm.providers import GeminiProvider, GroqProvider, LocalProvider

    providers = []
    for name in (n.strip().lower() for n in (order or settings.llm_providers).split(",")):
        if not name:
            continue
        if name == "gemini":
            key = settings.gemini_api_key.get_secret_value()
            providers.append(GeminiProvider(key, settings.gemini_model))
        elif name == "groq":
            key = settings.groq_api_key.get_secret_value()
            providers.append(GroqProvider(key, settings.groq_model))
        elif name == "local":
            if settings.local_llm_model:
                providers.append(LocalProvider(settings.local_llm_model, settings.local_llm_url))
        else:
            raise ValueError(f"unknown LLM provider {name!r}; use {', '.join(PROVIDER_NAMES)}")
    if not providers:
        raise ValueError("no LLM provider configured (check LLM_PROVIDERS and LOCAL_LLM_MODEL)")
    return providers


def build_llm_client(
    settings, cache: Cache, budget: Budget | None = None, order: str | None = None
) -> LLMClient:
    """Providers from settings (or `order`), budget from LLM_MAX_CALLS."""
    from whycode.config import redact

    providers = build_providers(settings, order)
    return LLMClient(
        providers,
        cache,
        budget or Budget(settings.llm_max_calls),
        redact=lambda s: redact(s, settings),
    )
