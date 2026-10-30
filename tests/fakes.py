"""Test doubles for unit and integration tests: a fake GitHub API, an in-memory raw store."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from whycode.ingest.store import RawRow

FIXTURES = Path(__file__).parent / "fixtures"


def load_github_fixture(name: str) -> dict:
    data = json.loads((FIXTURES / "github" / name).read_text(encoding="utf-8"))
    data.pop("_about", None)
    return data


class FakeGitHub:
    """Serves fixture responses by path, paginates lists like GitHub, and honours ETags."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path not in self.routes:
            return httpx.Response(404, json={"message": "Not Found"})
        body = self.routes[path]
        if callable(body):  # a route can compute its answer, e.g. a search endpoint
            return body(request)
        if isinstance(body, list):
            per_page = int(request.url.params.get("per_page", 30))
            page = int(request.url.params.get("page", 1))
            body = body[(page - 1) * per_page : page * per_page]
        etag = '"' + hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest() + '"'
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        return httpx.Response(200, json=body, headers={"ETag": etag})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class MemoryRawStore:
    """Same interface as RawStore, backed by a dict."""

    def __init__(self):
        self.rows: dict[tuple[str, str, str], RawRow] = {}
        self.writes = 0
        self.touches = 0

    def get(self, repo, kind, key):
        return self.rows.get((repo, kind, key))

    def upsert(self, repo, kind, key, etag, payload):
        self.writes += 1
        self.rows[(repo, kind, key)] = RawRow(repo, kind, key, etag, datetime.now(UTC), payload)

    def touch(self, repo, kind, key):
        self.touches += 1

    def pages(self, repo, kind, number):
        keys = [k for k in self.rows if k[:2] == (repo, kind) and k[2].startswith(f"{number}:p")]
        items = []
        for k in sorted(keys, key=lambda k: int(k[2].rsplit(":p", 1)[1])):
            items.extend(self.rows[k].payload)
        return items

    def delete_pages_after(self, repo, kind, number, last_page):
        stale = [
            k
            for k in self.rows
            if k[:2] == (repo, kind)
            and k[2].startswith(f"{number}:p")
            and int(k[2].rsplit(":p", 1)[1]) > last_page
        ]
        for k in stale:
            del self.rows[k]
        return len(stale)

    def count(self, repo):
        return sum(1 for k in self.rows if k[0] == repo)


class FakeProvider:
    """LLM provider that returns scripted replies (or raises scripted errors) and counts calls."""

    def __init__(self, name, model, replies=()):
        self.name, self.model = name, model
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        reply = self.replies.pop(0) if self.replies else '{"decisions": []}'
        if callable(reply):
            reply = reply(system, user)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class StatusError(Exception):
    """Mimics SDK errors that carry an HTTP status as .status_code (Groq) or .code (Gemini)."""

    def __init__(self, status, attr="code"):
        super().__init__(f"HTTP {status}")
        setattr(self, attr, status)


class MemoryLLMCache:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get(self, key):
        row = self.rows.get(key)
        return row["response"] if row else None

    def put(self, key, **fields):
        self.rows[key] = fields


class MemoryJobStore:
    """Same interface as whycode.ingest.select.JobStore, backed by a dict."""

    def __init__(self):
        from whycode.ingest.select import Job

        self._Job = Job
        self.rows: dict[tuple[str, int], Job] = {}

    def enqueue(self, repo, candidates):
        added = 0
        for c in candidates:
            key = (repo, c.number)
            if key in self.rows:
                self.rows[key].title, self.rows[key].comments = c.title, c.comments
            else:
                self.rows[key] = self._Job(
                    repo, c.number, c.title, c.comments, "queued", None, 0, None
                )
                added += 1
        return added

    def _sorted(self, repo):
        return sorted(
            (j for (r, _), j in self.rows.items() if r == repo),
            key=lambda j: (-j.comments, j.number),
        )

    def pending(self, repo):
        return [j for j in self._sorted(repo) if j.status in ("queued", "fetched")]

    def all(self, repo):
        return self._sorted(repo)

    def mark(self, repo, number, status, *, decisions=None, add_calls=0, error=None):
        job = self.rows[(repo, number)]
        job.status, job.error = status, error
        job.calls += add_calls
        if decisions is not None:
            job.decisions = decisions

    def counts(self, repo):
        out = {}
        for j in self.all(repo):
            out[j.status] = out.get(j.status, 0) + 1
        return out


def search_route(items):
    """A fake /search/issues: pages `items` like GitHub (total_count + items per page)."""

    def handler(request):
        per_page = int(request.url.params.get("per_page", 30))
        page = int(request.url.params.get("page", 1))
        chunk = items[(page - 1) * per_page : page * per_page]
        return httpx.Response(200, json={"total_count": len(items), "items": chunk})

    return handler
