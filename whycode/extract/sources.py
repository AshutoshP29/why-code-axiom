"""Turn a PR's raw GitHub rows into Sources: one per body, comment, review or commit message.

Source ids are the Evidence id keys from schema.cypher (without the repo):
    pr:5797:body  pr:5797:ic:<id>  pr:5797:rc:<id>  pr:5797:rv:<id>
    issue:4115:body  issue:4115:ic:<id>  commit:<sha>:msg
A Source's text is exactly the stored text, so quote checks run against what is in Postgres.
"""

from dataclasses import dataclass, field

from whycode.ids import normalize_repo
from whycode.ingest.fetch_pr import linked_numbers


@dataclass(frozen=True)
class Source:
    source_id: str
    source_type: str  # pr_body | pr_comment | review_comment | issue_comment | commit_msg
    text: str
    url: str | None
    author: str | None
    date: str | None  # ISO 8601 as GitHub gives it
    path: str | None = None  # file a review comment is attached to


@dataclass
class Thread:
    repo: str
    number: int
    title: str
    pr: dict
    sources: list[Source]
    changed_files: list[dict] = field(default_factory=list)
    linked_issues: list[int] = field(default_factory=list)

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.source_id == source_id), None)


def _login(obj: dict | None) -> str | None:
    return (obj or {}).get("login")


def _is_bot(user: dict | None) -> bool:
    login = _login(user) or ""
    return login.endswith("[bot]") or (user or {}).get("type") == "Bot"


def _comment_sources(prefix: str, kind: str, comments: list, source_type: str) -> list[Source]:
    out = []
    for c in comments:
        if not (c.get("body") or "").strip() or _is_bot(c.get("user")):
            continue
        out.append(
            Source(
                source_id=f"{prefix}:{kind}:{c['id']}",
                source_type=source_type,
                text=c["body"],
                url=c.get("html_url"),
                author=_login(c.get("user")),
                date=c.get("created_at") or c.get("submitted_at"),
                path=c.get("path"),
            )
        )
    return out


def load_thread(store, repo: str, number: int) -> Thread:
    """Build the Thread for one PR from the raw cache (no GitHub calls)."""

    repo = normalize_repo(repo)
    pr_row = store.get(repo, "pr", str(number))
    if pr_row is None:
        raise LookupError(f"{repo}#{number} is not in raw_github; fetch it first")
    pr = pr_row.payload
    p = f"pr:{number}"

    sources: list[Source] = []
    if (pr.get("body") or "").strip():
        sources.append(
            Source(f"{p}:body", "pr_body", pr["body"], pr.get("html_url"), _login(pr.get("user")),
                   pr.get("created_at"))
        )  # fmt: skip
    discussion = (
        _comment_sources(p, "ic", store.pages(repo, "issue_comments", number), "pr_comment")
        + _comment_sources(p, "rc", store.pages(repo, "review_comments", number), "review_comment")
        + _comment_sources(p, "rv", store.pages(repo, "reviews", number), "review_comment")
    )
    sources += sorted(discussion, key=lambda s: s.date or "")

    commits = store.pages(repo, "pr_commits", number)
    for c in commits:
        sources.append(
            Source(
                source_id=f"commit:{c['sha']}:msg",
                source_type="commit_msg",
                text=c["commit"]["message"],
                url=c.get("html_url"),
                author=_login(c.get("author")) or c["commit"]["author"]["name"],
                date=c["commit"]["author"]["date"],
            )
        )

    timeline = store.pages(repo, "timeline", number)
    linked = [n for n, _ in linked_numbers(repo, number, pr, commits, timeline)]
    for n in linked:
        issue_row = store.get(repo, "issue", str(n))
        if issue_row is None:
            continue
        issue = issue_row.payload
        if (issue.get("body") or "").strip():
            sources.append(
                Source(f"issue:{n}:body", "issue_comment", issue["body"], issue.get("html_url"),
                       _login(issue.get("user")), issue.get("created_at"))
            )  # fmt: skip
        sources += _comment_sources(
            f"issue:{n}", "ic", store.pages(repo, "issue_comments", n), "issue_comment"
        )

    return Thread(
        repo=repo,
        number=number,
        title=pr.get("title", ""),
        pr=pr,
        sources=sources,
        changed_files=store.pages(repo, "pr_files", number),
        linked_issues=linked,
    )
