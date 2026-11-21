"""Ingest one repository end to end for the Add repository flow (run by GitHub Actions).

    python -m whycode.ingest.repo --repo expressjs/express             # one repo, every stage
    python -m whycode.ingest.repo --due                                # repos kept up to date
    python -m whycode.ingest.repo --repo expressjs/express --failed "why"  # mark it ERROR

POST /api/repos queues the repo and starts .github/workflows/ingest.yml, which runs this. Each
stage is recorded on the Repo node, in the order the screens show them:

    fetch         the PR_LIMIT most-discussed merged PRs (MIN_COMMENTS or more), downloaded
    parse         clone the repo and map its code at HEAD
    link          HISTORY_YEARS of git history: commits to the code they changed
    extract       decisions from each PR not yet in the graph, at most MAX_CALLS AI calls
    supersession  only when this run added decisions

A PR already in the graph is skipped, so running again reads only new PRs. Only repos added
through the flow (they carry `added_at`) are touched: a repo the team ingested by hand, such as
psf/requests, is refused, so its hand-checked data cannot be overwritten.
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from whycode.graph.queries import Run
from whycode.graph.writer import set_repo_state
from whycode.ids import make_id, normalize_repo
from whycode.ingest import codemap
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubError, RateLimitError
from whycode.ingest.limits import HISTORY_YEARS, MAX_CALLS, MIN_COMMENTS, PR_LIMIT
from whycode.ingest.run import Neo4jSink, ingest
from whycode.ingest.select import eligible_prs

log = logging.getLogger(__name__)


Q_REPO_STATE = """// q:repo_state
MATCH (r:Repo {id: $repo})
RETURN r.added_at IS NOT NULL AS added, r.status AS status, r.error AS error
"""
Q_KNOWN_PRS = """// q:known_prs
MATCH (p:PullRequest {repo: $repo}) RETURN p.id AS id
"""
Q_DECISIONS = """// q:decision_count
MATCH (d:Decision {repo: $repo}) RETURN count(d) AS n
"""
Q_DUE = """// q:repos_due
MATCH (r:Repo)
WHERE r.added_at IS NOT NULL AND r.keep_updated = true AND r.status = 'READY'
RETURN r.id AS id ORDER BY r.id
"""


class NotAddedError(RuntimeError):
    """The repo was not added through the Add repository flow, so it is not ours to re-run."""


@dataclass
class Context:
    """What a run needs; built by main() from the settings, by tests from fakes."""

    run: Run
    driver: object
    database: str
    gh: object
    store: object
    jobs: object
    llm: object
    cache_dir: Path = codemap.CACHE_DIR


class _RunSink(Neo4jSink):
    """Neo4jSink for the extract stage. ingest() marks the repo READY when its PRs are done, but
    supersession still follows, so READY is recorded as INGESTING and its error kept for the end."""

    error: str | None = None

    def progress(self, *, status, stage, pct, partial, error=None):
        if status == "READY":
            self.error = error
            status, pct = "INGESTING", 100
        super().progress(status=status, stage=stage, pct=pct, partial=partial, error=error)


def _state(ctx: Context, repo: str, status: str, stage: str, pct: float, error=None) -> None:
    set_repo_state(
        ctx.driver,
        ctx.database,
        repo,
        status=status,
        stage=stage,
        progress_pct=round(pct, 1),
        partial=True,
        error=error,
    )


def _known_prs(ctx: Context, repo: str) -> set[int]:
    prefix = make_id(repo, "pr", 1)[:-1]  # "<repo>#pr:"
    rows = ctx.run(Q_KNOWN_PRS, {"repo": repo})
    return {int(r["id"].removeprefix(prefix)) for r in rows if r["id"].startswith(prefix)}


def _decisions(ctx: Context, repo: str) -> int:
    return ctx.run(Q_DECISIONS, {"repo": repo})[0]["n"]


def fetch_stage(ctx: Context, repo: str) -> str | None:
    """Queue the most-discussed PRs, skip those already in the graph, download the rest.
    Returns why the stage stopped early, or None."""
    _state(ctx, repo, "INGESTING", "fetch", 0)
    ctx.jobs.enqueue(repo, eligible_prs(ctx.gh, repo, MIN_COMMENTS, PR_LIMIT))
    known = _known_prs(ctx, repo)
    for job in ctx.jobs.pending(repo):
        if job.number in known:
            ctx.jobs.mark(repo, job.number, "written")
    todo = ctx.jobs.pending(repo)
    for i, job in enumerate(todo, 1):
        try:
            fetch_pr(ctx.gh, ctx.store, repo, job.number)
            ctx.jobs.mark(repo, job.number, "fetched")
        except RateLimitError as exc:
            return f"GitHub rate limit while fetching #{job.number}: {exc}"
        except GitHubError as exc:
            ctx.jobs.mark(repo, job.number, "failed", error=str(exc))
            log.warning("#%d failed to fetch: %s", job.number, exc)
        _state(ctx, repo, "INGESTING", "fetch", 100 * i / len(todo))
    return None


def code_stages(ctx: Context, repo: str, now: datetime) -> None:
    """parse: clone and map the code at HEAD. link: the history window, then write it all."""
    _state(ctx, repo, "INGESTING", "parse", 0)
    dest = ctx.cache_dir / repo
    head = codemap.clone_or_update(f"https://github.com/{repo}.git", dest)
    batch = codemap.build_code_map(repo, dest, head)
    _state(ctx, repo, "INGESTING", "link", 0)
    since = (now - timedelta(days=365 * HISTORY_YEARS)).date().isoformat()
    codemap.add_history(batch, codemap.read_history(dest, since))
    codemap.write_code_map(ctx.driver, ctx.database, batch)


def run_repo(ctx: Context, repo: str, now: datetime | None = None) -> str | None:
    """Every stage for one repo; the Repo node ends READY (partial: a sample of its PRs) with
    the reason it stopped early, if any. Returns that reason."""
    from whycode.graph.supersession import supersede

    repo = normalize_repo(repo)
    now = now or datetime.now(UTC)
    state = ctx.run(Q_REPO_STATE, {"repo": repo})
    if not state or not state[0]["added"]:
        raise NotAddedError(f"{repo} was not added through Add repository; not re-running it")

    stopped = fetch_stage(ctx, repo)
    code_stages(ctx, repo, now)

    before = _decisions(ctx, repo)
    sink = _RunSink(ctx.driver, ctx.database, repo)
    report = ingest(repo, ctx.jobs, ctx.gh, ctx.store, ctx.llm, sink)
    stopped = stopped or report.stopped_early or sink.error

    if _decisions(ctx, repo) > before:
        _state(ctx, repo, "INGESTING", "supersession", 0)
        result = supersede(ctx.run, ctx.driver, ctx.database, ctx.llm, repo)
        stopped = stopped or result.stopped_early
    _state(ctx, repo, "READY", "supersession", 100, error=stopped)
    return stopped


def mark_failed(ctx: Context, repo: str, message: str) -> bool:
    """Mark a flow-added repo ERROR, unless the run already recorded a more precise error."""
    repo = normalize_repo(repo)
    state = ctx.run(Q_REPO_STATE, {"repo": repo})
    if not state or not state[0]["added"] or state[0]["status"] == "ERROR":
        return False
    set_repo_state(ctx.driver, ctx.database, repo, status="ERROR", error=message[:500])
    return True


def due(ctx: Context) -> list[str]:
    return [r["id"] for r in ctx.run(Q_DUE, {})]


def _fail(ctx: Context, repo: str, exc: Exception, settings) -> None:
    from whycode.config import redact

    message = f"{type(exc).__name__}: {redact(str(exc), settings)}"[:500]
    try:
        set_repo_state(ctx.driver, ctx.database, repo, status="ERROR", error=message)
    except Exception:  # the graph itself may be what failed; the workflow marks it then
        log.exception("could not record the error on %s", repo)


def main(argv: list[str] | None = None) -> int:
    from whycode.config import ConfigError, get_settings
    from whycode.graph.client import aura_target, local_test_target
    from whycode.graph.queries import neo4j_runner
    from whycode.ingest.github import GitHubClient
    from whycode.ingest.select import JobStore
    from whycode.ingest.store import RawStore
    from whycode.llm.cache import PgLLMCache
    from whycode.llm.client import Budget, build_llm_client

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--repo", help="owner/name")
    which.add_argument("--due", action="store_true", help="every repo kept up to date")
    parser.add_argument("--failed", metavar="MESSAGE", help="only mark --repo as ERROR")
    parser.add_argument("--target", choices=["aura", "test"], default="aura")
    parser.add_argument("--max-calls", type=int, help="cap AI calls below MAX_CALLS (0: none)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    if args.failed is not None and not args.repo:
        parser.error("--failed needs --repo")
    try:
        repos = [normalize_repo(args.repo)] if args.repo else None
        s = get_settings()
    except (ValueError, ConfigError) as exc:
        print(f"FAIL {exc}")
        return 2

    target = aura_target(s) if args.target == "aura" else local_test_target()
    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    try:
        store.ensure_schema()
        jobs = JobStore(store.conn)
        jobs.ensure_schema()
        cache = PgLLMCache(store.conn)
        cache.ensure_schema()
        cap = min(MAX_CALLS, s.llm_max_calls)
        cap = cap if args.max_calls is None else min(cap, max(0, args.max_calls))
        llm = build_llm_client(s, cache, Budget(cap))
        with target.driver() as driver, GitHubClient(s.github_token.get_secret_value()) as gh:
            ctx = Context(
                neo4j_runner(driver, target.database), driver, target.database, gh, store, jobs, llm
            )
            if args.failed is not None:
                marked = mark_failed(ctx, repos[0], args.failed)
                print(f"{repos[0]}: {'marked ERROR' if marked else 'left as it was'}")
                return 0
            failures = 0
            for repo in repos if repos is not None else due(ctx):
                try:
                    stopped = run_repo(ctx, repo)
                    print(f"{repo}: READY" + (f" (stopped early: {stopped})" if stopped else ""))
                except NotAddedError as exc:
                    print(f"FAIL {exc}")
                    failures += 1
                except Exception as exc:
                    _fail(ctx, repo, exc, s)
                    print(f"FAIL {repo}: {type(exc).__name__}")
                    failures += 1
            print(f"LLM: {llm.api_calls} call(s), {llm.cache_hits} cache hit(s)")
            return 1 if failures else 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
