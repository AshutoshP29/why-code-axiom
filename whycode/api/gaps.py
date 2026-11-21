"""Gaps users flag ("this answer is missing context"), kept in Postgres table `gaps`.

One row per flag; the Graph health screen shows them grouped per entity with the count, the
latest question and when it was last flagged.
"""

import contextlib
from dataclasses import dataclass
from datetime import datetime

import psycopg

GAPS_DDL = (
    """
CREATE TABLE IF NOT EXISTS gaps (
    id         bigserial   PRIMARY KEY,
    repo       text        NOT NULL,
    entity_id  text        NOT NULL,
    question   text        NOT NULL,
    flagged_at timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX IF NOT EXISTS gaps_repo_entity ON gaps (repo, entity_id)",
)
_SUMMARY = """
SELECT entity_id, count(*), (array_agg(question ORDER BY flagged_at DESC, id DESC))[1],
       max(flagged_at)
FROM gaps WHERE repo = %s{entity}
GROUP BY entity_id ORDER BY max(flagged_at) DESC
"""


@dataclass(frozen=True)
class GapSummary:
    entity_id: str
    flags: int
    last_question: str
    last_flagged_at: datetime


class GapStore:
    """One connection, kept between requests. A serverless Postgres (Neon) closes idle
    connections, so a query that finds it closed reconnects once and runs again."""

    def __init__(self, conn: psycopg.Connection, dsn: str | None = None):
        self.conn = conn
        self.dsn = dsn  # None: no reconnecting (tests)

    @staticmethod
    def _open(dsn: str) -> psycopg.Connection:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=10)

    @classmethod
    def connect(cls, dsn: str) -> "GapStore":
        store = cls(cls._open(dsn), dsn)
        store.ensure_schema()
        return store

    def close(self) -> None:
        self.conn.close()

    def execute(self, sql: str, params: tuple = ()):
        try:
            return self.conn.execute(sql, params)
        except psycopg.OperationalError:
            if self.dsn is None:
                raise
            with contextlib.suppress(psycopg.Error):
                self.conn.close()
            self.conn = self._open(self.dsn)  # every statement is autocommit: safe to rerun
            return self.conn.execute(sql, params)

    def ensure_schema(self) -> None:
        for ddl in GAPS_DDL:
            self.execute(ddl)

    def add(self, repo: str, entity_id: str, question: str) -> None:
        self.execute(
            "INSERT INTO gaps (repo, entity_id, question) VALUES (%s, %s, %s)",
            (repo, entity_id, question),
        )

    def summaries(self, repo: str, entity_id: str | None = None) -> list[GapSummary]:
        if entity_id is None:
            rows = self.execute(_SUMMARY.format(entity=""), (repo,)).fetchall()
        else:
            sql = _SUMMARY.format(entity=" AND entity_id = %s")
            rows = self.execute(sql, (repo, entity_id)).fetchall()
        return [GapSummary(*row) for row in rows]

    def delete_repo(self, repo: str) -> int:
        return self.execute("DELETE FROM gaps WHERE repo = %s", (repo,)).rowcount
