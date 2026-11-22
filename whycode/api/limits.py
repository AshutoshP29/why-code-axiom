"""Per-user limits on the calls that cost something.

PR Guard spends the server's GitHub token (5,000 requests an hour, up to about 45 a check), so
one signed-in user could exhaust it for everyone; asking is cheap but unbounded. Calls are counted
in Postgres table api_calls, shared by every API instance (in memory if Postgres is down), per
user and overall, over a sliding window.
"""

import random
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException


@dataclass(frozen=True)
class Limit:
    per_user: int
    overall: int | None  # None: no overall cap
    seconds: int
    message: str


LIMITS = {
    "ask": Limit(60, None, 60, "That is a lot of questions in a minute. Try again shortly."),
    "guard": Limit(20, 80, 3600, "PR Guard has been used a lot in the last hour. Try again later."),
}


class Calls(Protocol):
    def count(self, kind: str, who: str, seconds: int) -> tuple[int, int]:
        """(this user's calls, everyone's calls) of this kind in the last `seconds`."""

    def record(self, kind: str, who: str) -> None: ...


class MemoryCalls:
    def __init__(self):
        self._lock = threading.Lock()
        self._log: list[tuple[str, str, float]] = []

    def count(self, kind: str, who: str, seconds: int) -> tuple[int, int]:
        since = time.time() - seconds
        with self._lock:
            mine = everyone = 0
            for k, w, at in self._log:
                if k == kind and at > since:
                    everyone += 1
                    mine += w == who
            return mine, everyone

    def record(self, kind: str, who: str) -> None:
        with self._lock:
            cutoff = time.time() - 86_400
            self._log = [e for e in self._log if e[2] > cutoff]
            self._log.append((kind, who, time.time()))


CALLS_DDL = (
    """
CREATE TABLE IF NOT EXISTS api_calls (
    id      bigserial   PRIMARY KEY,
    kind    text        NOT NULL,
    who     text        NOT NULL,
    called  timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX IF NOT EXISTS api_calls_kind_called ON api_calls (kind, called)",
)


class PgCalls:
    """`store` is anything with execute(sql, params): the GapStore, which reconnects."""

    def __init__(self, store):
        self.store = store
        for ddl in CALLS_DDL:
            store.execute(ddl)

    def count(self, kind: str, who: str, seconds: int) -> tuple[int, int]:
        row = self.store.execute(
            "SELECT count(*) FILTER (WHERE who = %s), count(*) FROM api_calls "
            "WHERE kind = %s AND called > now() - make_interval(secs => %s)",
            (who, kind, seconds),
        ).fetchone()
        return int(row[0]), int(row[1])

    def record(self, kind: str, who: str) -> None:
        self.store.execute("INSERT INTO api_calls (kind, who) VALUES (%s, %s)", (kind, who))
        if random.random() < 0.02:  # now and then, not on every call
            self.store.execute("DELETE FROM api_calls WHERE called < now() - interval '1 day'")


_memory = MemoryCalls()


def get_calls() -> Calls:
    """Overridden by the app with the Postgres store when it is reachable."""
    return _memory


def enforce(calls: Calls, kind: str, who: str) -> None:
    """Count this call, or refuse it with 429 when the user or everyone is over the limit."""
    limit = LIMITS[kind]
    mine, everyone = calls.count(kind, who, limit.seconds)
    if mine >= limit.per_user or (limit.overall is not None and everyone >= limit.overall):
        raise HTTPException(429, limit.message)
    calls.record(kind, who)
