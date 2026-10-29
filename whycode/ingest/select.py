"""Choose which pull requests are worth extracting, and keep a resumable job list for them.

Eligible: merged, at least N comments, not opened by a bot, not a dependency bump. Most
discussed first. Each chosen PR is a row in the Postgres `jobs` table, so a run that stops
(budget spent, provider down, crash) resumes where it left off and never redoes finished work.
"""

import re
from dataclasses import dataclass
from datetime import datetime

import psycopg

from whycode.ids import normalize_repo
from whycode.ingest.github import GitHubClient

SEARCH_PAGE = 100
SEARCH_MAX = 1000  # GitHub search never returns more than 1000 results
# Word boundaries only after words: "chore(deps):" ends in punctuation, where \b cannot match.
_BUMP = re.compile(r"^(?:bump\b|update dependency\b|chore\(deps\))", re.IGNORECASE)

JOB_STATUSES = ("queued", "fetched", "written", "failed")

JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    repo       text        NOT NULL,
    kind       text        NOT NULL,
    number     integer     NOT NULL,
    title      text,
    comments   integer     NOT NULL DEFAULT 0,
    status     text        NOT NULL DEFAULT 'queued',
    decisions  integer,
    calls      integer     NOT NULL DEFAULT 0,
    error      text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo, kind, number)
)
"""


@dataclass(frozen=True)
class Candidate:
    number: int
    title: str
    comments: int
    author: str | None


def _is_bot(user: dict | None) -> bool:
    user = user or {}
    return user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")


def eligible_prs(gh: GitHubClient, repo: str, min_comments: int, limit: int) -> list[Candidate]:
    """Merged PRs with >= min_comments comments, most discussed first, bots and bumps left out."""
    repo = normalize_repo(repo)
    query = f"repo:{repo} is:pr is:merged comments:>={min_comments}"
    found: list[Candidate] = []
    for page in range(1, SEARCH_MAX // SEARCH_PAGE + 1):
        data = gh.get(
            "/search/issues",
            params={
                "q": query,
                "sort": "comments",
                "order": "desc",
                "per_page": SEARCH_PAGE,
                "page": page,
            },
        ).data
        items = data.get("items", [])
        for item in items:
            if _is_bot(item.get("user")) or _BUMP.match(item.get("title", "")):
                continue
            found.append(
                Candidate(
                    item["number"],
                    item.get("title", ""),
                    item.get("comments", 0),
                    (item.get("user") or {}).get("login"),
                )
            )
        if len(items) < SEARCH_PAGE or len(found) >= limit:
            break
    # GitHub's comment sort is not strictly by the comments field; order it ourselves.
    found.sort(key=lambda c: (-c.comments, c.number))
    return found[:limit]


@dataclass
class Job:
    repo: str
    number: int
    title: str
    comments: int
    status: str
    decisions: int | None
    calls: int
    error: str | None
    updated_at: datetime | None = None


class JobStore:
    """The `jobs` table. One row per (repo, kind, number); kind is "pr" for now."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def ensure_schema(self) -> None:
        self.conn.execute(JOBS_DDL)

    def enqueue(self, repo: str, candidates: list[Candidate]) -> int:
        """Add new PRs as queued. Existing rows keep their status. Returns how many were new."""
        added = 0
        for c in candidates:
            cur = self.conn.execute(
                "INSERT INTO jobs (repo, kind, number, title, comments) "
                "VALUES (%s, 'pr', %s, %s, %s) "
                "ON CONFLICT (repo, kind, number) DO UPDATE SET title = EXCLUDED.title, "
                "comments = EXCLUDED.comments "
                "RETURNING (xmax = 0) AS inserted",  # xmax = 0 only for a freshly inserted row
                (repo, c.number, c.title, c.comments),
            )
            added += bool(cur.fetchone()[0])
        return added

    def pending(self, repo: str) -> list[Job]:
        """Jobs not yet written (or failed), most discussed first."""
        return self._select(repo, "AND status IN ('queued', 'fetched')")

    def all(self, repo: str) -> list[Job]:
        return self._select(repo, "")

    def _select(self, repo: str, where: str) -> list[Job]:
        rows = self.conn.execute(
            "SELECT repo, number, title, comments, status, decisions, calls, error, updated_at "
            f"FROM jobs WHERE repo = %s AND kind = 'pr' {where} ORDER BY comments DESC, number",
            (repo,),
        ).fetchall()
        return [Job(*r) for r in rows]

    def mark(
        self,
        repo: str,
        number: int,
        status: str,
        *,
        decisions: int | None = None,
        add_calls: int = 0,
        error: str | None = None,
    ) -> None:
        if status not in JOB_STATUSES:
            raise ValueError(f"unknown job status {status!r}")
        self.conn.execute(
            "UPDATE jobs SET status = %s, decisions = COALESCE(%s, decisions), "
            "calls = calls + %s, error = %s, updated_at = now() "
            "WHERE repo = %s AND kind = 'pr' AND number = %s",
            (status, decisions, add_calls, error, repo, number),
        )

    def counts(self, repo: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, count(*) FROM jobs WHERE repo = %s GROUP BY status", (repo,)
        ).fetchall()
        return {status: n for status, n in rows}

    def delete_repo(self, repo: str) -> int:
        return self.conn.execute("DELETE FROM jobs WHERE repo = %s", (repo,)).rowcount
