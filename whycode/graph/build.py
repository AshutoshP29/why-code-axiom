"""Turn one fetched, extracted pull request into graph nodes and relationships.

Pure: reads the raw cache and the extraction result, touches no database. The writer MERGEs
what this returns. Every node carries `repo` and an id from whycode/ids.py, as schema.cypher says.

What is linked to what:
- PullRequest CONTAINS its commits; the commit that MODIFIES files and code is the PR's only
  commit, or its merge commit when there are several (the net change that landed).
- PullRequest CLOSES issues it closes ("fixes #N"), REFERENCES the other linked issues.
- Person AUTHORED the PR, commits, issues and evidence; REVIEWED the PR.
- File CONTAINS its classes, functions and config keys; a class CONTAINS its methods.
- Every source (body, comment, review, commit message) becomes Evidence.
- Decision DECIDED_IN the PR, SUPPORTED_BY its evidence (with the quote's span), AFFECTS the
  checked code entities, PROPOSED_BY the PR author, APPROVED_BY the merger and approvers.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from whycode.code.affects import AffectsCheck
from whycode.code.diff import entities_changed
from whycode.code.entities import EntityKind
from whycode.code.index import PrCodeIndex
from whycode.extract.extractor import Decision
from whycode.extract.sources import Thread
from whycode.ids import decision_id, make_id, normalize_repo
from whycode.ingest.fetch_pr import linked_numbers

SCHEMA_VERSION = "v4"
ACTIVE_WITHIN = timedelta(days=548)  # about 18 months, as schema.cypher defines `active`

NODE_LABELS = frozenset(
    {
        "Repo",
        "PullRequest",
        "Commit",
        "Issue",
        "Person",
        "Evidence",
        "Decision",
        "File",
        "Class",
        "Function",
        "Module",
        "ConfigKey",
    }
)
REL_TYPES = frozenset(
    {
        "CONTAINS",
        "CLOSES",
        "REFERENCES",
        "MODIFIES",
        "AUTHORED",
        "REVIEWED",
        "AFFECTS",
        "DECIDED_IN",
        "SUPPORTED_BY",
        "PROPOSED_BY",
        "APPROVED_BY",
    }
)
_LABEL_BY_KIND = {
    EntityKind.FILE: "File",
    EntityKind.CLASS: "Class",
    EntityKind.FUNCTION: "Function",
    EntityKind.CONFIG_KEY: "ConfigKey",
}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class GraphBatch:
    repo: str
    nodes: dict[str, dict[str, dict]] = field(default_factory=dict)  # label -> id -> props
    rels: dict[tuple[str, str, str], dict[tuple[str, str], dict]] = field(default_factory=dict)
    replaces_decisions_of: list[tuple[str, str]] = field(default_factory=list)  # (label, id)

    def node(self, label: str, id_: str, **props) -> str:
        if label not in NODE_LABELS:
            raise ValueError(f"unknown node label {label!r}")
        existing = self.nodes.setdefault(label, {}).setdefault(id_, {"repo": self.repo})
        existing.update({k: v for k, v in props.items() if v is not None})
        return id_

    def rel(self, type_: str, from_: tuple[str, str], to: tuple[str, str], **props) -> None:
        if type_ not in REL_TYPES:
            raise ValueError(f"unknown relationship type {type_!r}")
        key = (type_, from_[0], to[0])
        self.rels.setdefault(key, {}).setdefault((from_[1], to[1]), {}).update(props)

    def count(self) -> tuple[int, int]:
        return (
            sum(len(v) for v in self.nodes.values()),
            sum(len(v) for v in self.rels.values()),
        )


class _People:
    """Person nodes with first/last seen dates gathered from everything they did here."""

    def __init__(self, batch: GraphBatch, now: datetime):
        self.batch, self.now = batch, now
        self.seen: dict[str, list[datetime]] = {}

    def ref(self, login: str | None, when: str | datetime | None = None) -> tuple[str, str] | None:
        if not login:
            return None
        when = parse_time(when) if isinstance(when, str) else when
        self.seen.setdefault(login, [])
        if when:
            self.seen[login].append(when)
        return ("Person", make_id(self.batch.repo, "user", login))

    def write(self) -> None:
        for login, dates in self.seen.items():
            last = max(dates) if dates else None
            self.batch.node(
                "Person",
                make_id(self.batch.repo, "user", login),
                login=login,
                first_seen=min(dates) if dates else None,
                last_seen=last,
                active=bool(last and self.now - last <= ACTIVE_WITHIN),
            )


def _login(obj: dict | None) -> str | None:
    return (obj or {}).get("login")


def build_pr_graph(
    store,
    thread: Thread,
    decisions: list[Decision],
    checks: list[AffectsCheck] | None,
    *,
    index: PrCodeIndex | None,
    prompt_version: str,
    now: datetime | None = None,
) -> GraphBatch:
    repo, number = normalize_repo(thread.repo), thread.number
    now = now or datetime.now(UTC)
    b = GraphBatch(repo)
    people = _People(b, now)
    pr = thread.pr
    owner, name = repo.split("/")

    b.node(
        "Repo",
        repo,
        owner=owner,
        name=name,
        url=f"https://github.com/{repo}",
        # status, stage, progress_pct and partial belong to whoever runs the ingestion
        # (writer.set_repo_state); one PR's batch must not overwrite a run's progress.
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        last_synced_at=now,
    )

    pr_ref = ("PullRequest", make_id(repo, "pr", number))
    b.node(
        *pr_ref,
        number=number,
        title=pr.get("title"),
        state=pr.get("state"),
        merged=bool(pr.get("merged")),
        merged_at=parse_time(pr.get("merged_at")),
        merge_commit_sha=pr.get("merge_commit_sha"),
        url=pr.get("html_url"),
        comment_count=(pr.get("comments") or 0) + (pr.get("review_comments") or 0),
        updated_at=parse_time(pr.get("updated_at")),
    )
    author = people.ref(_login(pr.get("user")), pr.get("created_at"))
    if author:
        b.rel("AUTHORED", author, pr_ref)
    for review in store.pages(repo, "reviews", number):
        reviewer = people.ref(_login(review.get("user")), review.get("submitted_at"))
        if reviewer:
            b.rel("REVIEWED", reviewer, pr_ref)

    # Commits, and which one carries the PR's net change.
    commits = store.pages(repo, "pr_commits", number)
    for c in commits:
        ref = ("Commit", make_id(repo, "commit", c["sha"]))
        b.node(
            *ref,
            sha=c["sha"],
            message=c["commit"]["message"],
            date=parse_time(c["commit"]["author"]["date"]),
            url=c.get("html_url"),
        )
        b.rel("CONTAINS", pr_ref, ref)
        who = people.ref(_login(c.get("author")), c["commit"]["author"]["date"])
        if who:
            b.rel("AUTHORED", who, ref)
    change_commit = None
    if len(commits) == 1:
        change_commit = ("Commit", make_id(repo, "commit", commits[0]["sha"]))
    elif pr.get("merged") and pr.get("merge_commit_sha"):
        sha = pr["merge_commit_sha"]
        change_commit = ("Commit", make_id(repo, "commit", sha))
        b.node(*change_commit, sha=sha, url=f"https://github.com/{repo}/commit/{sha}")
        b.rel("CONTAINS", pr_ref, change_commit)

    # Files and code.
    files_by_path = {f["filename"]: f for f in store.pages(repo, "pr_files", number)}
    if index is not None:
        for f in index.files:
            fref = ("File", index.file_id(f))
            aliases = [
                p for p in dict.fromkeys([f.pr_path, f.previous_path]) if p and p != f.graph_path
            ]
            b.node(
                *fref,
                path=f.graph_path,
                name=f.graph_path.rsplit("/", 1)[-1],
                aliases=aliases,
                aliases_text=" ".join(aliases),
            )
            raw = files_by_path.get(f.pr_path, {})
            if change_commit and f.status != "removed":
                b.rel(
                    "MODIFIES",
                    change_commit,
                    fref,
                    added=raw.get("additions", 0),
                    removed=raw.get("deletions", 0),
                )
            parsed = index.parsed.get(f.pr_path)
            if parsed is None:
                continue
            labels = {e.id: _LABEL_BY_KIND[e.kind] for e in parsed.entities}
            for e in parsed.entities:
                if e.kind is EntityKind.FILE:
                    continue
                ref = (_LABEL_BY_KIND[e.kind], e.id)
                b.node(
                    *ref,
                    name=e.name,
                    qualified_name=e.qualified_name,
                    path=e.path,
                    start_line=e.start_line,
                    end_line=e.end_line,
                    value=e.value,
                    aliases_text="",
                )
                if e.parent_id in labels:
                    b.rel("CONTAINS", (labels[e.parent_id], e.parent_id), ref)
            if change_commit:
                for ch in entities_changed(parsed, raw.get("patch")):
                    b.rel(
                        "MODIFIES",
                        change_commit,
                        (_LABEL_BY_KIND[ch.entity.kind], ch.entity.id),
                        added=ch.added,
                        removed=ch.removed,
                    )

    # Linked issues.
    timeline = store.pages(repo, "timeline", number)
    for n, reason in linked_numbers(repo, number, pr, commits, timeline):
        row = store.get(repo, "issue", str(n))
        if row is None:
            continue
        issue = row.payload
        iref = ("Issue", make_id(repo, "issue", n))
        b.node(
            *iref,
            number=n,
            title=issue.get("title"),
            state=issue.get("state"),
            url=issue.get("html_url"),
            created_at=parse_time(issue.get("created_at")),
            closed_at=parse_time(issue.get("closed_at")),
            updated_at=parse_time(issue.get("updated_at")),
        )
        b.rel("CLOSES" if reason == "closing" else "REFERENCES", pr_ref, iref)
        who = people.ref(_login(issue.get("user")), issue.get("created_at"))
        if who:
            b.rel("AUTHORED", who, iref)

    # Evidence: every source, so later search can find any of it.
    for s in thread.sources:
        eref = ("Evidence", make_id(repo, "ev", s.source_id))
        b.node(
            *eref,
            source_type=s.source_type,
            source_id=s.source_id,
            text=s.text,
            url=s.url,
            date=parse_time(s.date),
            author=s.author,
        )
        who = people.ref(s.author, s.date)
        if who:
            b.rel("AUTHORED", who, eref)

    # Decisions. Ids come from the source, prompt version and position, never from LLM text.
    b.replaces_decisions_of.append(pr_ref)
    approvers = [_login(pr.get("merged_by"))] + [
        _login(r.get("user"))
        for r in store.pages(repo, "reviews", number)
        if r.get("state") == "APPROVED"
    ]
    for i, d in enumerate(decisions):
        dref = ("Decision", decision_id(repo, pr_ref[1], prompt_version, i))
        x = d.data
        b.node(
            *dref,
            summary=x.summary,
            rationale=x.rationale,
            alternatives=list(x.alternatives),
            decided_at=datetime(
                x.decided_at.year, x.decided_at.month, x.decided_at.day, tzinfo=UTC
            ),
            status="ACTIVE",
            evidence_kind=x.evidence_kind.value,
            extraction_confidence=x.confidence,
            model=d.model,
            prompt_version=prompt_version,
        )
        b.rel("DECIDED_IN", dref, pr_ref)
        for ev in d.evidence:
            b.rel(
                "SUPPORTED_BY",
                dref,
                ("Evidence", make_id(repo, "ev", ev.source.source_id)),
                span_start=ev.span.start,
                span_end=ev.span.end,
            )
        for k in checks[i].kept if checks else []:
            b.rel("AFFECTS", dref, (_LABEL_BY_KIND[k.kind], k.id))
        if author:
            b.rel("PROPOSED_BY", dref, author)
        for login in dict.fromkeys(a for a in approvers if a):
            b.rel("APPROVED_BY", dref, people.ref(login))

    people.write()
    return b
