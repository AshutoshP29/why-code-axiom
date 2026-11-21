"""PR Guard: which recorded decisions a pull request touches, before anyone merges it.

Deterministic, no LLM. GitHub gives the PR's changed files and their diffs; the parser finds the
functions, classes and config keys each diff changes (as at ingestion: whycode.code.diff); the
graph then gives the decisions in force on that code (query 5a), with their evidence and the
people to ask. A decision made in this same PR, or after it was opened, is left out: the PR
cannot be undoing it.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from whycode.api import models as m
from whycode.api import reads
from whycode.api.answers import _decision, _people, _step, github
from whycode.code.diff import entities_changed
from whycode.code.entities import is_supported, parse_file
from whycode.graph.queries import Run
from whycode.graph.queries import _decision as _decision_view
from whycode.ids import make_id, normalize_repo

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
MAX_FILE_PAGES = 3  # 100 files a page
MAX_FILES_READ = 40  # Python files parsed per check
_PULL_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.IGNORECASE)
_NUMBER = re.compile(r"#?(\d{1,7})")


def parse_pull(text: str, repo: str) -> int:
    """A PR number from "1234", "#1234" or a GitHub PR link to this repo."""
    text = text.strip()
    if link := _PULL_URL.search(text):
        if normalize_repo(link.group(1)) != repo:
            raise HTTPException(400, f"That pull request is not in {repo}.")
        return int(link.group(2))
    if number := _NUMBER.fullmatch(text):
        return int(number.group(1))
    raise HTTPException(400, "Give a pull request number, like 6710, or its GitHub link.")


def _token() -> str | None:
    """A real GitHub token if the server has one; the live API may hold a placeholder."""
    token = os.environ.get("GITHUB_TOKEN", "")
    return token if token.startswith(("ghp_", "github_pat_", "gho_", "ghs_")) else None


class GitHubReader:
    """The few public GitHub reads PR Guard needs."""

    def __init__(self, client: httpx.Client, token: str | None = None):
        self.client = client
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        res = self.client.get(url, params=params, headers=self.headers, follow_redirects=True)
        if res.status_code in (403, 429):
            raise HTTPException(503, "GitHub is rate limiting WhyCode right now. Try again soon.")
        return res

    def pull(self, repo: str, number: int) -> dict:
        res = self._get(f"{API}/repos/{repo}/pulls/{number}")
        if res.status_code == 404:
            raise HTTPException(404, f"{repo} has no pull request #{number}.")
        if res.status_code != 200:
            raise HTTPException(502, "Could not read the pull request from GitHub.")
        return res.json()

    def files(self, repo: str, number: int) -> list[dict]:
        out: list[dict] = []
        for page in range(1, MAX_FILE_PAGES + 1):
            res = self._get(
                f"{API}/repos/{repo}/pulls/{number}/files", {"per_page": 100, "page": page}
            )
            if res.status_code != 200:
                raise HTTPException(502, "Could not read the pull request's files from GitHub.")
            batch = res.json()
            out.extend(batch)
            if len(batch) < 100:
                break
        return out

    def text(self, url: str) -> str | None:
        res = self._get(url)
        return res.text if res.status_code == 200 else None


def http_client() -> httpx.Client:
    return httpx.Client(timeout=15)


def _pull(data: dict, repo: str) -> m.GuardPull:
    state = "merged" if data.get("merged_at") else data.get("state", "open")
    return m.GuardPull(
        number=data["number"],
        title=data.get("title") or "",
        url=data.get("html_url") or f"{github(repo)}/pull/{data['number']}",
        state=state if state in ("open", "closed", "merged") else "open",
        author=(data.get("user") or {}).get("login"),
        opened_at=data["created_at"],
    )


# One indexed lookup per label (an unlabelled match on id would scan every node).
Q_GUARD_ENTITIES = """// q:guard_entities
MATCH (e:File) WHERE e.repo = $repo AND e.id IN $ids RETURN e
UNION ALL MATCH (e:Class) WHERE e.repo = $repo AND e.id IN $ids RETURN e
UNION ALL MATCH (e:Function) WHERE e.repo = $repo AND e.id IN $ids RETURN e
UNION ALL MATCH (e:ConfigKey) WHERE e.repo = $repo AND e.id IN $ids RETURN e
"""
# Query 5a for many items at once: the decisions in force on any of them, and which they govern.
Q_GUARD_DECISIONS = """// q:guard_decisions
UNWIND $ids AS id
MATCH (e {id: id, repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})
WHERE NOT EXISTS { MATCH (d)<-[s:SUPERSEDES]-(:Decision) WHERE s.kind IN ['reverses','replaces'] }
WITH d, collect(DISTINCT e.id) AS touched
MATCH (d)-[sb:SUPPORTED_BY]->(ev:Evidence)
OPTIONAL MATCH (d)-[:PROPOSED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:APPROVED_BY]->(a:Person)
OPTIONAL MATCH (d)-[:DECIDED_IN]->(src)
RETURN d, touched,
       collect(DISTINCT {ev: ev, start: sb.span_start, end: sb.span_end}) AS evidence,
       collect(DISTINCT p) AS proposers,
       collect(DISTINCT a) AS approvers,
       collect(DISTINCT src) AS sources
"""


def raw_url(head: dict, path: str) -> str:
    """The file as the PR's head commit has it, straight from raw.githubusercontent.com (the
    API's raw_url goes through a slow redirect). Forks are read from the fork."""
    where = (head.get("repo") or {}).get("full_name")
    return f"{RAW}/{where}/{head['sha']}/{quote(path)}"


def changed_ids(repo: str, head: dict, files: list[dict], gh: GitHubReader, notes: list[str]):
    """(ids of the code items the PR's diffs change, ids of its files, Python files read)."""
    readable = [f for f in files if f.get("status") != "removed" and is_supported(f["filename"])]
    if len(readable) > MAX_FILES_READ:
        notes.append(f"Read the first {MAX_FILES_READ} of {len(readable)} changed Python files.")
    readable = readable[:MAX_FILES_READ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        sources = list(pool.map(lambda f: gh.text(raw_url(head, f["filename"])), readable))
    code_ids: list[str] = []
    for f, source in zip(readable, sources, strict=True):
        if source is None:
            notes.append(f"Could not read {f['filename']} from GitHub.")
            continue
        for change in entities_changed(parse_file(repo, f["filename"], source), f.get("patch")):
            code_ids.append(change.entity.id)
    file_ids = [make_id(repo, "file", f["filename"]) for f in files]
    return list(dict.fromkeys(code_ids)), file_ids, len(readable)


def check(run: Run, repo: m.Repo, pull_text: str, gh: GitHubReader) -> m.GuardReport:
    number = parse_pull(pull_text, repo.id)
    data = gh.pull(repo.id, number)
    pull = _pull(data, repo.id)
    files = gh.files(repo.id, number)
    notes: list[str] = []
    code_ids, file_ids, read = changed_ids(repo.id, data["head"], files, gh, notes)

    params = {"repo": repo.id}
    known = {
        e.id: e
        for e in map(
            reads.entity,
            (r["e"] for r in run(Q_GUARD_ENTITIES, {**params, "ids": code_ids + file_ids})),
        )
    }
    changed = [known[i] for i in code_ids if i in known]
    if unknown := len(code_ids) - len(changed):
        notes.append(f"{unknown} changed item(s) are new or not in today's code map.")

    this_pr = make_id(repo.id, "pr", str(number))
    hits: list[m.GuardHit] = []
    rows = run(Q_GUARD_DECISIONS, {**params, "ids": list(known)}) if known else []
    for row in rows:
        dv = _decision_view(row)
        came_later = dv.decided_at.date() > pull.opened_at.date()
        if came_later or any(s.id == this_pr for s in dv.decided_in):
            continue
        touched = [known[i] for i in row["touched"] if i in known]
        code = [t for t in touched if t.kind != "file"]
        hits.append(
            m.GuardHit(
                decision=_decision(dv, repo.id),
                evidence=[_step(ev, github(repo.id)) for ev in dv.evidence],
                people=_people(dv),
                touched=code or touched,
                level="code" if code else "file",
            )
        )

    # Code-level hits first (the PR changes that very function), newest decision first.
    hits.sort(key=lambda h: (h.level != "code", -h.decision.decided_at.toordinal()))
    return m.GuardReport(
        repo=repo.id,
        pull=pull,
        files_changed=len(files),
        python_files_read=read,
        changed=changed,
        hits=hits,
        notes=notes,
    )
