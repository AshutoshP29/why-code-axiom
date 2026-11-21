"""Add any public GitHub repository: check it, queue it, start its ingestion run.

Ingesting takes longer than an API call may (a Vercel function stops after 5 minutes and has no
git), so adding a repo starts the GitHub Actions workflow .github/workflows/ingest.yml, which runs
`python -m whycode.ingest.repo` and records its progress on the Repo node. GET /api/ingestion
reads that progress back (whycode.api.reads.ingestion).

Limits, enforced here rather than in the browser:
- public repositories only, named by a strict owner/name;
- one ingestion at a time; a run that has not moved for STALE_AFTER no longer blocks;
- at most DAILY_LIMIT repositories added per day;
- a run reads at most PR_LIMIT pull requests with at most MAX_CALLS AI calls (whycode.ingest.limits;
  whycode.ingest.repo enforces them, the estimate here only reports them);
- a repo the team ingested by hand (no `added_at`, such as psf/requests) is never re-run here.

    WHYCODE_DISPATCH_TOKEN  GitHub token allowed to run workflows on WHYCODE_DISPATCH_REPO
    WHYCODE_DISPATCH_REPO   where ingest.yml lives (default AshutoshP29/why-code-axiom)
    WHYCODE_DISPATCH_REF    the branch whose ingest.yml runs (default main)
    GITHUB_TOKEN            reads repository facts for the check, as PR Guard does
"""

import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException

from whycode.api import models as m
from whycode.api import reads
from whycode.graph.queries import Run
from whycode.ingest.limits import HISTORY_YEARS, MAX_CALLS, MIN_COMMENTS, PR_LIMIT

API = "https://api.github.com"
WORKFLOW = "ingest.yml"
DEFAULT_DISPATCH_REPO = "AshutoshP29/why-code-axiom"
DAILY_LIMIT = 5
STALE_AFTER = timedelta(hours=2)  # ingest.yml times out after 90 minutes
MAX_REPO_KB = 300_000  # GitHub's `size`; a bigger clone is too slow to map
AURA_FREE_NODES = 200_000  # the free Aura instance's node limit

# Estimates for the check, kept above what runs used. Measured: pallets/itsdangerous, 5 PRs, took
# 6 calls (one per PR, one supersession) and 3.4 minutes in all on GitHub Actions; psf/requests'
# much longer PRs averaged about 2.5 calls each, split into parts.
CALLS_PER_PR = 1.5
SUPERSESSION_CALLS = 5
MINUTES_SETUP = (2, 4)  # runner, install, clone
MINUTES_PER_PR = (0.2, 1.0)  # GitHub reads plus AI calls, which free tiers slow down
NODES_PER_PR = 40  # decisions, evidence, people, issues, commits around one PR
KB_PER_ENTITY = 5  # psf/requests: about 1,650 code entities

BAD_INPUT = "Paste a GitHub link like github.com/owner/name, or type owner/name."
_OWNER = r"[a-z0-9](?:[a-z0-9-]{0,38})"
_NAME = r"[a-z0-9._-]{1,100}"
_REPO = re.compile(rf"^{_OWNER}/{_NAME}$")

Q_BUSY = """// q:repos_busy
MATCH (r:Repo)
WHERE r.status IN ['QUEUED', 'INGESTING'] AND r.last_synced_at >= datetime($since)
RETURN r.id AS id
"""
Q_ADDED_SINCE = """// q:repos_added_since
MATCH (r:Repo) WHERE r.added_at >= datetime($since) RETURN count(r) AS n
"""
Q_GRAPH_SIZE = """// q:graph_size
MATCH (n) RETURN count(n) AS n
"""
Q_CREATE = """// q:repo_create
CREATE (r:Repo {id: $repo, repo: $repo, owner: $owner, name: $name, url: $url,
                added_at: datetime(), added_by: $login, keep_updated: $keep_updated,
                status: 'QUEUED', stage: 'fetch', progress_pct: 0, partial: true,
                last_synced_at: datetime()})
"""
Q_QUEUE = """// q:repo_queue
MATCH (r:Repo {id: $repo})
SET r.status = 'QUEUED', r.stage = 'fetch', r.progress_pct = 0, r.error = null,
    r.last_synced_at = datetime()
"""
Q_ADDED = """// q:repo_added
MATCH (r:Repo {id: $repo}) RETURN r.added_at IS NOT NULL AS added
"""
Q_FAIL = """// q:repo_fail
MATCH (r:Repo {id: $repo}) SET r.status = 'ERROR', r.error = $error
"""


def parse_repo_input(text: str) -> str:
    """owner/name, lowercased, from a GitHub link or a bare owner/name (as the screens parse it:
    frontend/src/lib/entity.ts parseRepoInput). Raises 400 on anything else."""
    t = re.sub(r"^https?://", "", (text or "").strip(), flags=re.IGNORECASE).rstrip("/")
    is_url = re.match(r"^(www\.)?github\.com/", t, re.IGNORECASE) is not None
    parts = re.sub(r"^(www\.)?github\.com/", "", t, flags=re.IGNORECASE).split("/")
    if len(parts) < 2 or (not is_url and len(parts) > 2):
        raise HTTPException(400, BAD_INPUT)
    owner, name = parts[0].lower(), re.sub(r"\.git$", "", parts[1], flags=re.IGNORECASE).lower()
    repo = f"{owner}/{name}"
    if not _REPO.match(repo) or name in (".", ".."):
        raise HTTPException(400, BAD_INPUT)
    return repo


@dataclass(frozen=True)
class Facts:
    """What GitHub says about a repository, for the check and the limits."""

    found: bool
    public: bool = False
    size_kb: int = 0
    commits: int = 0
    commits_recent: int = 0  # in the HISTORY_YEARS window the code map reads
    pull_requests: int = 0
    issues: int = 0
    eligible: int = 0  # merged PRs with MIN_COMMENTS or more comments: what a run can read


class GitHubFacts:
    """Reads Facts with a handful of calls: the repo, three searches and two commit counts."""

    def __init__(self, client: httpx.Client, token: str | None = None):
        self.client = client
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        res = self.client.get(f"{API}{path}", params=params, headers=self.headers)
        if res.status_code in (403, 429) and (
            res.headers.get("x-ratelimit-remaining") == "0" or res.status_code == 429
        ):
            raise HTTPException(503, "GitHub is limiting requests. Try again in a minute.")
        return res

    def _search_count(self, query: str) -> int:
        res = self._get("/search/issues", {"q": query, "per_page": 1})
        return int(res.json().get("total_count", 0)) if res.status_code == 200 else 0

    def _commit_count(self, repo: str, since: str | None = None) -> int:
        params = {"per_page": 1, **({"since": since} if since else {})}
        res = self._get(f"/repos/{repo}/commits", params)
        if res.status_code != 200:
            return 0  # an empty repository answers 409
        last = res.links.get("last", {}).get("url")
        return int(parse_qs(urlparse(last).query)["page"][0]) if last else len(res.json())

    def facts(self, repo: str, now: datetime) -> Facts:
        res = self._get(f"/repos/{repo}")
        if res.status_code == 404:
            return Facts(found=False)
        if res.status_code != 200:
            raise HTTPException(502, f"GitHub answered {res.status_code} for {repo}.")
        data = res.json()
        if data.get("private") or data.get("visibility", "public") != "public":
            return Facts(found=True, public=False)
        since = (now - timedelta(days=365 * HISTORY_YEARS)).isoformat()
        return Facts(
            found=True,
            public=True,
            size_kb=int(data.get("size") or 0),
            commits=self._commit_count(repo),
            commits_recent=self._commit_count(repo, since),
            pull_requests=self._search_count(f"repo:{repo} is:pr"),
            issues=self._search_count(f"repo:{repo} is:issue"),
            eligible=self._search_count(f"repo:{repo} is:pr is:merged comments:>={MIN_COMMENTS}"),
        )


def estimate(repo: str, facts: Facts, graph_nodes: int) -> m.RepoCheck:
    """The Add repository dialog's numbers: how much a run reads, costs and adds to the graph."""
    if not (facts.found and facts.public):
        return m.RepoCheck(
            repo=repo,
            found=False,
            is_public=facts.public,
            commits=0,
            pull_requests=0,
            issues=0,
            minutes_low=0,
            minutes_high=0,
            ai_calls=0,
            fits_free_tier=False,
            capped=False,
        )
    prs = min(PR_LIMIT, facts.eligible)
    calls = min(MAX_CALLS, math.ceil(prs * CALLS_PER_PR) + (SUPERSESSION_CALLS if prs else 0))
    nodes = facts.commits_recent + facts.size_kb // KB_PER_ENTITY + NODES_PER_PR * prs
    return m.RepoCheck(
        repo=repo,
        found=True,
        is_public=True,
        commits=facts.commits,
        pull_requests=facts.pull_requests,
        issues=facts.issues,
        minutes_low=math.ceil(MINUTES_SETUP[0] + MINUTES_PER_PR[0] * prs),
        minutes_high=math.ceil(MINUTES_SETUP[1] + MINUTES_PER_PR[1] * prs),
        ai_calls=calls,
        fits_free_tier=facts.size_kb <= MAX_REPO_KB and graph_nodes + nodes <= AURA_FREE_NODES,
        capped=facts.eligible > PR_LIMIT,
    )


def _graph_nodes(run: Run) -> int:
    rows = run(Q_GRAPH_SIZE, {})
    return rows[0]["n"] if rows else 0


def check(run: Run, gh: GitHubFacts, repo: str, now: datetime | None = None) -> m.RepoCheck:
    now = now or datetime.now(UTC)
    return estimate(repo, gh.facts(repo, now), _graph_nodes(run))


class DispatchError(RuntimeError):
    pass


class Dispatcher:
    """Starts ingest.yml for one repo through GitHub's workflow_dispatch API."""

    def __init__(self, client: httpx.Client, token: str | None, where: str, ref: str):
        self.client, self.token, self.where, self.ref = client, token, where, ref

    @classmethod
    def from_env(cls, client: httpx.Client) -> "Dispatcher":
        return cls(
            client,
            os.environ.get("WHYCODE_DISPATCH_TOKEN", "").strip() or None,
            os.environ.get("WHYCODE_DISPATCH_REPO", "").strip() or DEFAULT_DISPATCH_REPO,
            os.environ.get("WHYCODE_DISPATCH_REF", "").strip() or "main",
        )

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def dispatch(self, repo: str) -> None:
        res = self.client.post(
            f"{API}/repos/{self.where}/actions/workflows/{WORKFLOW}/dispatches",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": self.ref, "inputs": {"repo": repo}},
        )
        if res.status_code not in (200, 204):
            raise DispatchError(f"GitHub answered {res.status_code} when starting the run")


def http_client() -> httpx.Client:
    return httpx.Client(timeout=15)


def _require_idle(run: Run, now: datetime) -> None:
    busy = run(Q_BUSY, {"since": (now - STALE_AFTER).isoformat()})
    if busy:
        raise HTTPException(
            409, f"{busy[0]['id']} is being read right now. Try again when it has finished."
        )


def _require_dispatch(dispatcher: Dispatcher) -> None:
    if not dispatcher.configured:
        raise HTTPException(503, "Adding repositories is not set up on this server yet.")


def _start(run: Run, dispatcher: Dispatcher, repo: str) -> m.Repo:
    try:
        dispatcher.dispatch(repo)
    except (DispatchError, httpx.HTTPError) as exc:
        run(Q_FAIL, {"repo": repo, "error": f"Could not start the ingestion run: {exc}"})
        raise HTTPException(502, "Could not start the ingestion run. Try again later.") from None
    return reads.repo(run, repo)


def add(
    run: Run,
    gh: GitHubFacts,
    dispatcher: Dispatcher,
    repo: str,
    *,
    keep_updated: bool,
    login: str | None,
    now: datetime | None = None,
) -> m.Repo:
    """Queue a public repo and start its run. Nothing is written until every check passes."""
    now = now or datetime.now(UTC)
    if reads.repo(run, repo) is not None:
        raise HTTPException(409, f"{repo} is already added")
    _require_dispatch(dispatcher)
    _require_idle(run, now)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if run(Q_ADDED_SINCE, {"since": day.isoformat()})[0]["n"] >= DAILY_LIMIT:
        raise HTTPException(429, f"{DAILY_LIMIT} repositories were added today already.")
    facts = gh.facts(repo, now)
    if not facts.found:
        raise HTTPException(404, "We could not find a public repository at that link.")
    if not facts.public:
        raise HTTPException(400, "Only public repositories can be added.")
    if facts.eligible == 0:
        raise HTTPException(
            400,
            f"{repo} has no merged pull request with {MIN_COMMENTS} or more comments, so there "
            "is no discussion to read decisions from.",
        )
    if not estimate(repo, facts, _graph_nodes(run)).fits_free_tier:
        raise HTTPException(400, f"{repo} is too large for the free graph.")
    owner, name = repo.split("/")
    run(
        Q_CREATE,
        {
            "repo": repo,
            "owner": owner,
            "name": name,
            "url": f"https://github.com/{repo}",
            "login": login,
            "keep_updated": keep_updated,
        },
    )
    return _start(run, dispatcher, repo)


def rerun(run: Run, dispatcher: Dispatcher, r: m.Repo, now: datetime | None = None) -> m.Repo:
    """Sync or re-run a repo added here: the run reads only PRs not yet in the graph."""
    now = now or datetime.now(UTC)
    added = run(Q_ADDED, {"repo": r.id})
    if not added or not added[0]["added"]:
        raise HTTPException(
            409, f"{r.id} was read by the team's own scripts, so it is updated from there."
        )
    _require_dispatch(dispatcher)
    _require_idle(run, now)
    run(Q_QUEUE, {"repo": r.id})
    return _start(run, dispatcher, r.id)
