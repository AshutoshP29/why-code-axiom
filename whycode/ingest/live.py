"""Live sync: a push to a repository added from the screens is in the graph within seconds.

GitHub calls POST /api/hooks/github (whycode/api/app.py) on every push. For each commit pushed to
the default branch this reads the commit from GitHub, parses the code files it changed as that
commit left them, and writes with MERGE, as the PR ingest does for a PR's commit:

    Commit                 sha, message, date, url
    Person AUTHORED it     the GitHub login, marked active
    Commit MODIFIES        each changed File, and the functions, classes and config keys the
                           diff changed (whycode.code.diff), with added/removed line counts
    File CONTAINS          the code items in each changed file; new ones appear as nodes

No AI call: decisions come from pull request discussions, which the ingestion run reads (a merged
pull request restarts it, see the hook). Writing twice changes nothing. Only repositories added
through Add repository are synced; the team's own (psf/requests) never are.
"""

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx

from whycode.code.diff import entities_changed
from whycode.code.entities import EntityKind, is_supported, parse_file
from whycode.graph.build import GraphBatch
from whycode.ids import make_id, normalize_repo

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
MAX_COMMITS = 20  # GitHub puts at most 20 commits in one push payload
MAX_FILES = 40  # code files parsed per commit

_LABEL = {
    EntityKind.CLASS: "Class",
    EntityKind.FUNCTION: "Function",
    EntityKind.CONFIG_KEY: "ConfigKey",
}

Q_ADDED = """// q:live_repo
MATCH (r:Repo {id: $repo}) RETURN r.added_at IS NOT NULL AS added
"""
Q_SYNCED = """// q:live_synced
MATCH (r:Repo {id: $repo})
SET r.last_synced_at = datetime(), r.last_commit_sha = $sha
"""


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    """GitHub's X-Hub-Signature-256: "sha256=" + HMAC-SHA256 of the raw body with the secret."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


class CommitReader:
    """The GitHub reads live sync needs: one commit with its files, and a file at a commit."""

    def __init__(self, client: httpx.Client, token: str | None = None):
        self.client = client
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def commit(self, repo: str, sha: str) -> dict | None:
        res = self.client.get(f"{API}/repos/{repo}/commits/{sha}", headers=self.headers)
        return res.json() if res.status_code == 200 else None

    def text(self, repo: str, sha: str, path: str) -> str | None:
        res = self.client.get(f"{RAW}/{repo}/{sha}/{quote(path)}", follow_redirects=True)
        return res.text if res.status_code == 200 else None


@dataclass
class PushReport:
    repo: str
    commits: int = 0
    files: int = 0
    code_items_changed: int = 0
    skipped: str | None = None  # why nothing was written, if so


def _date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def build_push_batch(repo: str, commits: list[dict], sources: dict[tuple[str, str], str]):
    """The graph for pushed commits, from GitHub's commit objects (oldest first) and the text of
    each changed code file as its commit left it, keyed by (sha, path). Returns (batch, report)."""
    repo = normalize_repo(repo)
    b = GraphBatch(repo)
    report = PushReport(repo)
    for c in commits:
        sha = c["sha"]
        info = c.get("commit") or {}
        when = _date((info.get("author") or {}).get("date"))
        ref = ("Commit", make_id(repo, "commit", sha))
        b.node(
            *ref,
            sha=sha,
            message=(info.get("message") or "").strip(),
            date=when,
            url=c.get("html_url") or f"https://github.com/{repo}/commit/{sha}",
        )
        report.commits += 1
        login = (c.get("author") or {}).get("login")
        if login:
            person = ("Person", make_id(repo, "user", login))
            b.node(*person, login=login, last_seen=when, active=True)
            b.rel("AUTHORED", person, ref)
        for f in (c.get("files") or [])[:MAX_FILES]:
            path = f["filename"]
            if f.get("status") == "removed" or not is_supported(path):
                continue
            source = sources.get((sha, path))
            if source is None:
                continue
            parsed = parse_file(repo, path, source)
            file_ref = ("File", parsed.entities[0].id)
            b.node(*file_ref, path=parsed.path, name=PurePosixPath(parsed.path).name)
            labels = {e.id: _LABEL.get(e.kind, "File") for e in parsed.entities}
            for e in parsed.entities[1:]:
                b.node(
                    labels[e.id],
                    e.id,
                    name=e.name,
                    qualified_name=e.qualified_name,
                    path=e.path,
                    start_line=e.start_line,
                    end_line=e.end_line,
                    value=e.value,
                )
                if e.parent_id in labels:
                    b.rel("CONTAINS", (labels[e.parent_id], e.parent_id), (labels[e.id], e.id))
            b.rel(
                "MODIFIES",
                ref,
                file_ref,
                added=f.get("additions", 0),
                removed=f.get("deletions", 0),
            )
            report.files += 1
            for ch in entities_changed(parsed, f.get("patch")):
                b.rel(
                    "MODIFIES",
                    ref,
                    (_LABEL[ch.entity.kind], ch.entity.id),
                    added=ch.added,
                    removed=ch.removed,
                )
                report.code_items_changed += 1
    return b, report


def sync_push(run, write, reader: CommitReader, payload: dict) -> PushReport:
    """Write the commits of one push event. `write` takes a GraphBatch (whycode.graph.writer)."""
    repo = normalize_repo(payload["repository"]["full_name"])
    report = PushReport(repo)
    default = payload["repository"].get("default_branch") or "main"
    if payload.get("ref") != f"refs/heads/{default}":
        report.skipped = f"not the default branch ({default})"
        return report
    added = run(Q_ADDED, {"repo": repo})
    if not added or not added[0]["added"]:
        report.skipped = "not a repository added from the screens"
        return report
    shas = [c["id"] for c in payload.get("commits", []) if c.get("distinct", True)][:MAX_COMMITS]
    commits = [c for c in (reader.commit(repo, sha) for sha in shas) if c]
    wanted = [
        (c["sha"], f["filename"])
        for c in commits
        for f in (c.get("files") or [])[:MAX_FILES]
        if f.get("status") != "removed" and is_supported(f["filename"])
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(lambda w: reader.text(repo, *w), wanted))
    sources = {w: t for w, t in zip(wanted, texts, strict=True) if t is not None}
    batch, report = build_push_batch(repo, commits, sources)
    if not commits:
        report.skipped = "no commit could be read from GitHub"
        return report
    write(batch)
    run(Q_SYNCED, {"repo": repo, "sha": commits[-1]["sha"]})
    return report
