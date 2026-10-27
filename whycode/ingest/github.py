"""Minimal GitHub REST client: ETags, rate-limit aware waiting, bounded retries.

Never puts the token in an exception or log message.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class RateLimitError(GitHubError):
    """The wait GitHub asks for is longer than we are willing to sleep."""


@dataclass
class Response:
    status: int  # 200, or 304 when the ETag still matches
    data: object = None
    etag: str | None = None
    headers: dict = field(default_factory=dict)


@dataclass
class CallStats:
    requests: int = 0
    not_modified: int = 0
    retries: int = 0
    waited_seconds: float = 0.0


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_URL,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_wait: float = 900.0,
        max_retries: int = 3,
        low_water: int = 5,
        timeout: float = 30.0,
    ):
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "whycode",
            },
        )
        self._sleep, self._clock = sleep, clock
        self.max_wait, self.max_retries, self.low_water = max_wait, max_retries, low_water
        self.stats = CallStats()

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def get(self, path: str, params: dict | None = None, etag: str | None = None) -> Response:
        headers = {"If-None-Match": etag} if etag else {}
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise GitHubError(f"GET {path}: network error {type(exc).__name__}") from None
                self._backoff(attempt, f"network error on {path}")
                continue
            self.stats.requests += 1

            if resp.status_code == 304:
                self.stats.not_modified += 1
                return Response(304, None, etag, dict(resp.headers))
            if resp.status_code == 200:
                self._respect_low_water(resp)
                return Response(200, resp.json(), resp.headers.get("ETag"), dict(resp.headers))
            if resp.status_code in (403, 429) and self._is_rate_limited(resp):
                wait = self._wait_seconds(resp)
                if wait > self.max_wait:
                    raise RateLimitError(
                        f"GET {path}: rate limited; GitHub asks to wait {wait:.0f}s "
                        f"(> max_wait {self.max_wait:.0f}s)"
                    )
                log.warning("rate limited on %s; waiting %.0fs", path, wait)
                self._wait(wait)
                continue
            if resp.status_code >= 500 and attempt < self.max_retries:
                self._backoff(attempt, f"HTTP {resp.status_code} on {path}")
                continue
            raise GitHubError(f"GET {path}: HTTP {resp.status_code} {_message(resp)}")
        raise GitHubError(f"GET {path}: gave up after {self.max_retries + 1} attempts")

    # -- rate limit helpers --------------------------------------------------------------

    @staticmethod
    def _is_rate_limited(resp: httpx.Response) -> bool:
        return (
            resp.headers.get("X-RateLimit-Remaining") == "0"
            or "Retry-After" in resp.headers
            or "rate limit" in _message(resp).lower()
        )

    def _wait_seconds(self, resp: httpx.Response) -> float:
        if "Retry-After" in resp.headers:
            return float(resp.headers["Retry-After"])
        if resp.headers.get("X-RateLimit-Remaining") == "0" and "X-RateLimit-Reset" in resp.headers:
            return max(0.0, float(resp.headers["X-RateLimit-Reset"]) - self._clock()) + 1
        return 60.0  # secondary limit without a hint: GitHub says wait at least a minute

    def _respect_low_water(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")
        if remaining is None or reset is None or int(remaining) > self.low_water:
            return
        wait = max(0.0, float(reset) - self._clock()) + 1
        if wait > self.max_wait:
            raise RateLimitError(
                f"only {remaining} requests left; reset in {wait:.0f}s (> max_wait)"
            )
        log.warning("only %s requests left; waiting %.0fs for reset", remaining, wait)
        self._wait(wait)

    def _backoff(self, attempt: int, why: str) -> None:
        self.stats.retries += 1
        wait = 2.0**attempt
        log.warning("%s; retrying in %.0fs", why, wait)
        self._wait(wait)

    def _wait(self, seconds: float) -> None:
        self.stats.waited_seconds += seconds
        self._sleep(seconds)


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message", ""))[:200]
    except Exception:
        return resp.text[:200]
