"""Fetch one pull request and everything around it into the raw_github cache.

    python -m whycode.ingest.fetch_pr --repo psf/requests --pr 5797

Stored kinds (key in brackets):
    pr [N], issue [N], issue_comments [N:pP], review_comments [N:pP], reviews [N:pP],
    pr_commits [N:pP], pr_files [N:pP], timeline [N:pP]
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Protocol

from whycode.ids import normalize_repo
from whycode.ingest.github import GitHubClient
from whycode.ingest.links import closing_refs, parse_refs

log = logging.getLogger(__name__)

PER_PAGE = 100
MAX_PAGES = 50  # 5000 items per list; far beyond any thread we extract from
MAX_LINKED = 15


class Store(Protocol):
    def get(self, repo: str, kind: str, key: str): ...
    def upsert(self, repo: str, kind: str, key: str, etag: str | None, payload) -> None: ...
    def touch(self, repo: str, kind: str, key: str) -> None: ...
    def delete_pages_after(self, repo: str, kind: str, number: int, last_page: int) -> int: ...


@dataclass
class LinkedIssue:
    number: int
    reason: str  # "closing", "body-ref" or "timeline"
    issue: dict
    comments: list


@dataclass
class PrFetch:
    repo: str
    number: int
    pr: dict
    issue_comments: list
    review_comments: list
    reviews: list
    commits: list
    files: list
    timeline: list
    linked: list[LinkedIssue] = field(default_factory=list)


class _Fetcher:
    def __init__(self, gh: GitHubClient, store: Store, repo: str):
        self.gh, self.store, self.repo = gh, store, repo

    def one(self, kind: str, key: str, path: str, params: dict | None = None):
        row = self.store.get(self.repo, kind, key)
        resp = self.gh.get(path, params=params, etag=row.etag if row else None)
        if resp.status == 304 and row is not None:
            self.store.touch(self.repo, kind, key)
            return row.payload
        self.store.upsert(self.repo, kind, key, resp.etag, resp.data)
        return resp.data

    def pages(self, kind: str, number: int, path: str) -> list:
        """Fetch a paginated list page by page; each page is its own row with its own ETag."""
        items: list = []
        for page in range(1, MAX_PAGES + 1):
            data = self.one(kind, f"{number}:p{page}", path, {"per_page": PER_PAGE, "page": page})
            items.extend(data)
            if len(data) < PER_PAGE:
                self.store.delete_pages_after(self.repo, kind, number, page)
                return items
        raise RuntimeError(f"{path}: more than {MAX_PAGES} pages; refusing to continue")


def linked_numbers(repo: str, number: int, pr: dict, commits: list, timeline: list):
    """Issues worth fetching with this PR, with why. Same repo only, PR itself excluded."""
    reasons: dict[int, str] = {}
    texts = [pr.get("body") or ""] + [c["commit"]["message"] for c in commits]
    for text in texts:
        for ref in closing_refs(text, repo):
            if ref.repo == repo:
                reasons.setdefault(ref.number, "closing")
    for ref in parse_refs(pr.get("body") or "", repo):
        if ref.repo == repo:
            reasons.setdefault(ref.number, "body-ref")
    for ev in timeline:
        if ev.get("event") == "connected" and ev.get("source", {}).get("issue"):
            reasons.setdefault(ev["source"]["issue"]["number"], "timeline")
    reasons.pop(number, None)
    return list(reasons.items())[:MAX_LINKED]


def fetch_pr(gh: GitHubClient, store: Store, repo: str, number: int) -> PrFetch:
    repo = normalize_repo(repo)
    f = _Fetcher(gh, store, repo)
    base = f"/repos/{repo}"
    pr = f.one("pr", str(number), f"{base}/pulls/{number}")
    result = PrFetch(
        repo=repo,
        number=number,
        pr=pr,
        issue_comments=f.pages("issue_comments", number, f"{base}/issues/{number}/comments"),
        review_comments=f.pages("review_comments", number, f"{base}/pulls/{number}/comments"),
        reviews=f.pages("reviews", number, f"{base}/pulls/{number}/reviews"),
        commits=f.pages("pr_commits", number, f"{base}/pulls/{number}/commits"),
        files=f.pages("pr_files", number, f"{base}/pulls/{number}/files"),
        timeline=f.pages("timeline", number, f"{base}/issues/{number}/timeline"),
    )
    for linked, reason in linked_numbers(repo, number, pr, result.commits, result.timeline):
        log.info("linked #%d (%s)", linked, reason)
        issue = f.one("issue", str(linked), f"{base}/issues/{linked}")
        comments = f.pages("issue_comments", linked, f"{base}/issues/{linked}/comments")
        result.linked.append(LinkedIssue(linked, reason, issue, comments))
    return result


def main() -> int:
    from whycode.config import ConfigError, get_settings
    from whycode.ingest.store import RawStore

    parser = argparse.ArgumentParser(description="Fetch one PR into the raw_github cache.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        s = get_settings()
    except ConfigError as exc:
        print(f"FAIL config: {exc}")
        return 2

    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    try:
        store.ensure_schema()
        with GitHubClient(s.github_token.get_secret_value()) as gh:
            r = fetch_pr(gh, store, args.repo, args.pr)
            print(
                f"{r.repo}#{r.number}: {r.pr['title']!r} ({r.pr['state']}, merged={r.pr['merged']})"
            )
            print(f"  issue comments   {len(r.issue_comments)}")
            print(f"  review comments  {len(r.review_comments)}")
            print(f"  reviews          {len(r.reviews)}")
            print(f"  commits          {len(r.commits)}")
            print(f"  changed files    {len(r.files)}")
            print(f"  timeline events  {len(r.timeline)}")
            for li in r.linked:
                print(f"  linked #{li.number} ({li.reason}): {len(li.comments)} comments")
            st = gh.stats
            print(
                f"  GitHub requests  {st.requests} ({st.not_modified} not modified, "
                f"{st.retries} retries, waited {st.waited_seconds:.0f}s)"
            )
            print(f"  raw_github rows for {r.repo}: {store.count(r.repo)}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
