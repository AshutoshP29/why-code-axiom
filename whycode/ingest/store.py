"""Postgres raw cache of GitHub API responses: one row per (repo, kind, key).

Re-fetching an item updates its row; it never adds a second one. Lists are stored one page
per row (key "<number>:p<page>") so each page keeps its own ETag.
"""

import json
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

RAW_GITHUB_DDL = """
CREATE TABLE IF NOT EXISTS raw_github (
    repo       text        NOT NULL,
    kind       text        NOT NULL,
    key        text        NOT NULL,
    etag       text,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    payload    jsonb       NOT NULL,
    PRIMARY KEY (repo, kind, key)
)
"""


def _dumps(obj) -> str:
    # jsonb cannot hold \u0000; GitHub text occasionally contains it and it carries no meaning.
    return json.dumps(obj).replace("\\u0000", "")


@dataclass(frozen=True)
class RawRow:
    repo: str
    kind: str
    key: str
    etag: str | None
    fetched_at: datetime
    payload: object


class RawStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    @classmethod
    def connect(cls, dsn: str) -> "RawStore":
        return cls(psycopg.connect(dsn, autocommit=True, connect_timeout=10))

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.execute(RAW_GITHUB_DDL)

    def get(self, repo: str, kind: str, key: str) -> RawRow | None:
        row = self.conn.execute(
            "SELECT repo, kind, key, etag, fetched_at, payload FROM raw_github "
            "WHERE repo = %s AND kind = %s AND key = %s",
            (repo, kind, key),
        ).fetchone()
        return RawRow(*row) if row else None

    def upsert(self, repo: str, kind: str, key: str, etag: str | None, payload) -> None:
        self.conn.execute(
            "INSERT INTO raw_github (repo, kind, key, etag, fetched_at, payload) "
            "VALUES (%s, %s, %s, %s, now(), %s) "
            "ON CONFLICT (repo, kind, key) DO UPDATE SET "
            "etag = EXCLUDED.etag, fetched_at = EXCLUDED.fetched_at, payload = EXCLUDED.payload",
            (repo, kind, key, etag, Jsonb(payload, dumps=_dumps)),
        )

    def touch(self, repo: str, kind: str, key: str) -> None:
        """Mark an unchanged (304) item as checked now."""
        self.conn.execute(
            "UPDATE raw_github SET fetched_at = now() WHERE repo = %s AND kind = %s AND key = %s",
            (repo, kind, key),
        )

    def pages(self, repo: str, kind: str, number: int) -> list:
        """All items of a paginated list, pages concatenated in page order."""
        rows = self.conn.execute(
            "SELECT key, payload FROM raw_github WHERE repo = %s AND kind = %s AND key LIKE %s",
            (repo, kind, f"{number}:p%"),
        ).fetchall()
        items: list = []
        for _, payload in sorted(rows, key=lambda r: int(r[0].rsplit(":p", 1)[1])):
            items.extend(payload)
        return items

    def delete_pages_after(self, repo: str, kind: str, number: int, last_page: int) -> int:
        """Drop stored pages beyond the current last page (a list that shrank)."""
        rows = self.conn.execute(
            "SELECT key FROM raw_github WHERE repo = %s AND kind = %s AND key LIKE %s",
            (repo, kind, f"{number}:p%"),
        ).fetchall()
        stale = [k for (k,) in rows if int(k.rsplit(":p", 1)[1]) > last_page]
        for key in stale:
            self.conn.execute(
                "DELETE FROM raw_github WHERE repo = %s AND kind = %s AND key = %s",
                (repo, kind, key),
            )
        return len(stale)

    def count(self, repo: str) -> int:
        return self.conn.execute(
            "SELECT count(*) FROM raw_github WHERE repo = %s", (repo,)
        ).fetchone()[0]

    def delete_repo(self, repo: str) -> int:
        return self.conn.execute("DELETE FROM raw_github WHERE repo = %s", (repo,)).rowcount
