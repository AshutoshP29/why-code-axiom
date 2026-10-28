"""Ingest many pull requests: choose them, then fetch, extract, check and write each one.

    python -m whycode.ingest.run --repo psf/requests --min-comments 20 --limit 63 --dry-run
    python -m whycode.ingest.run --repo psf/requests --min-comments 20 --limit 63 --max-calls 160

Resumable: every PR is a row in the jobs table; written PRs are skipped on the next run and
cached LLM answers cost nothing. A PR GitHub cannot serve is marked failed and the run goes on.
When the LLM budget is spent or every provider is down, the run stops cleanly: what was written
stays written, the stopped PR stays pending.

--dry-run fetches the PRs (GitHub only) and shows, per PR, how many prompt parts extraction
needs and how many are already cached. It makes no LLM call and writes nothing to the graph.
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Protocol

from whycode.code.affects import resolve_affects
from whycode.code.index import build_pr_code_index
from whycode.extract.extractor import extract_thread
from whycode.extract.prompt import PROMPT_VERSION, render_code_outline
from whycode.extract.sources import load_thread
from whycode.graph.build import GraphBatch, build_pr_graph
from whycode.ids import normalize_repo
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubError, RateLimitError

log = logging.getLogger(__name__)


class GraphSink(Protocol):
    def write(self, batch: GraphBatch): ...
    def progress(
        self, *, status: str, stage: str, pct: float, partial: bool, error: str | None = None
    ) -> None: ...


@dataclass
class PrOutcome:
    number: int
    title: str
    status: str  # written | failed | incomplete | dry-run
    parts: int = 0
    cached_parts: int = 0
    calls: int = 0
    decisions: int = 0
    error: str | None = None


@dataclass
class RunReport:
    outcomes: list[PrOutcome] = field(default_factory=list)
    stopped_early: str | None = None
    dry_run: bool = False

    @property
    def would_call(self) -> int:
        return sum(o.parts - o.cached_parts for o in self.outcomes)


def _pct(jobs, repo: str) -> float:
    all_jobs = jobs.all(repo)
    done = sum(j.status in ("written", "failed") for j in all_jobs)
    return round(100 * done / len(all_jobs), 1) if all_jobs else 100.0


def ingest(repo, jobs, gh, store, llm, sink: GraphSink | None, *, dry_run=False, now=None):
    """Process every pending job for `repo`, most discussed first. See the module docstring."""
    repo = normalize_repo(repo)
    report = RunReport(dry_run=dry_run)
    if not dry_run:
        sink.progress(status="INGESTING", stage="extract", pct=_pct(jobs, repo), partial=True)

    for job in jobs.pending(repo):
        out = PrOutcome(job.number, job.title, "written")
        report.outcomes.append(out)
        try:
            fetch_pr(gh, store, repo, job.number)
        except RateLimitError as exc:
            out.status, out.error = "incomplete", str(exc)
            report.stopped_early = f"GitHub rate limit at #{job.number}"
            break
        except GitHubError as exc:
            out.status, out.error = "failed", str(exc)
            jobs.mark(repo, job.number, "failed", error=str(exc))
            log.warning("#%d failed to fetch: %s", job.number, exc)
            continue

        thread = load_thread(store, repo, job.number)
        index = build_pr_code_index(store, repo, job.number)
        outline = render_code_outline(index) or None
        calls_before = llm.api_calls
        result = extract_thread(thread, llm, code_outline=outline, dry_run=dry_run)
        out.calls = llm.api_calls - calls_before
        out.parts = len(result.chunks)
        out.cached_parts = sum(c.cached for c in result.chunks)

        if dry_run:
            out.status = "dry-run"
            jobs.mark(repo, job.number, "fetched")
            continue
        if result.stopped_early:
            out.status, out.error = "incomplete", result.stopped_early
            jobs.mark(repo, job.number, "fetched", add_calls=out.calls, error=result.stopped_early)
            # One PR the providers could not answer is skipped (it stays pending for the next
            # run). Stop only when nothing more can be done: budget spent or every provider off.
            if "BudgetExceededError" in result.stopped_early or llm.all_switched_off():
                report.stopped_early = f"#{job.number}: {result.stopped_early}"
                break
            log.warning("#%d incomplete (%s); continuing", job.number, result.stopped_early)
            continue

        checks = [resolve_affects(d.data.affects, index) for d in result.decisions]
        batch = build_pr_graph(
            store,
            thread,
            result.decisions,
            checks,
            index=index,
            prompt_version=PROMPT_VERSION,
            now=now,
        )
        sink.write(batch)
        out.decisions = len(result.decisions)
        jobs.mark(repo, job.number, "written", decisions=out.decisions, add_calls=out.calls)
        sink.progress(status="INGESTING", stage="extract", pct=_pct(jobs, repo), partial=True)

    if not dry_run:
        # A tier of PRs is a sample of the history, so the repo stays `partial` (answers warn).
        sink.progress(
            status="READY",
            stage="extract",
            pct=_pct(jobs, repo),
            partial=True,
            error=report.stopped_early,
        )
    return report


def requeue_fallback(repo, jobs, store, hosted_llm) -> list[int]:
    """Send written PRs back to the queue if any prompt part has no hosted answer cached.

    Those parts were answered by the local fallback model, which finds far fewer decisions.
    `hosted_llm` must hold only hosted providers: its dry run then counts a part as cached only
    when Gemini or Groq answered it. Re-running a requeued PR replaces its decisions.
    """
    repo = normalize_repo(repo)
    redo = []
    for job in jobs.all(repo):
        if job.status != "written":
            continue
        thread = load_thread(store, repo, job.number)
        index = build_pr_code_index(store, repo, job.number)
        outline = render_code_outline(index) or None
        plan = extract_thread(thread, hosted_llm, code_outline=outline, dry_run=True)
        if not all(c.cached for c in plan.chunks):
            jobs.mark(
                repo, job.number, "queued", error="redo: a part was answered by the local model"
            )
            redo.append(job.number)
    return redo


class Neo4jSink:
    def __init__(self, driver, database: str, repo: str):
        self.driver, self.database, self.repo = driver, database, normalize_repo(repo)

    def write(self, batch: GraphBatch):
        from whycode.graph.writer import write_batch

        return write_batch(self.driver, self.database, batch)

    def progress(self, *, status, stage, pct, partial, error=None):
        from whycode.graph.writer import set_repo_state

        set_repo_state(
            self.driver,
            self.database,
            self.repo,
            status=status,
            stage=stage,
            progress_pct=pct,
            partial=partial,
            error=error,
        )


def print_report(report: RunReport, llm, jobs, repo: str) -> None:
    head = "dry run: " if report.dry_run else ""
    print(f"\n{head}{len(report.outcomes)} PR(s) processed")
    print(
        f"  {'PR':>6}  {'status':<10} {'parts':>5} {'cached':>6} "
        f"{'calls':>5} {'decisions':>9}  title"
    )
    for o in report.outcomes:
        print(
            f"  #{o.number:<5}  {o.status:<10} {o.parts:>5} {o.cached_parts:>6} {o.calls:>5} "
            f"{o.decisions:>9}  {o.title[:60]}"
        )
        if o.error:
            print(f"          error: {o.error[:160]}")
    if report.dry_run:
        print(f"\nwould call the LLM for {report.would_call} part(s); 0 calls made")
    else:
        print(
            f"\nLLM: {llm.api_calls} call(s) ({llm.budget.used} hosted, budget "
            f"{llm.budget.max_calls}), {llm.cache_hits} cache hit(s)"
        )
    if report.stopped_early:
        print(f"STOPPED: {report.stopped_early}; run again to continue")
    print("jobs: " + ", ".join(f"{k} {v}" for k, v in sorted(jobs.counts(repo).items())))


def main() -> int:
    from whycode.config import ConfigError, get_settings, redact
    from whycode.graph.client import aura_target, local_test_target
    from whycode.ingest.github import GitHubClient
    from whycode.ingest.select import JobStore, eligible_prs
    from whycode.ingest.store import RawStore
    from whycode.llm.cache import PgLLMCache
    from whycode.llm.client import Budget, build_llm_client

    parser = argparse.ArgumentParser(description="Ingest many pull requests.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--min-comments", type=int, default=20)
    parser.add_argument("--limit", type=int, default=63, help="most discussed PRs to queue")
    parser.add_argument("--no-select", action="store_true", help="only resume queued jobs")
    parser.add_argument("--dry-run", action="store_true", help="fetch and plan; no LLM, no writes")
    parser.add_argument("--max-calls", type=int, help="cap hosted LLM calls below LLM_MAX_CALLS")
    parser.add_argument("--providers", help="override LLM_PROVIDERS for this run")
    parser.add_argument("--target", choices=["aura", "test"], default="aura")
    parser.add_argument(
        "--redo-fallback",
        action="store_true",
        help="requeue written PRs that the local fallback model answered (no LLM calls)",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        s = get_settings()
    except ConfigError as exc:
        print(f"FAIL config: {exc}")
        return 2

    repo = normalize_repo(args.repo)
    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    try:
        store.ensure_schema()
        jobs = JobStore(store.conn)
        jobs.ensure_schema()
        cache = PgLLMCache(store.conn)
        cache.ensure_schema()
        cap = s.llm_max_calls if args.max_calls is None else min(args.max_calls, s.llm_max_calls)
        llm = build_llm_client(s, cache, Budget(cap), order=args.providers)
        print("providers: " + " -> ".join(f"{p.name}/{p.model}" for p in llm.providers))
        with GitHubClient(s.github_token.get_secret_value()) as gh:
            if not args.no_select:
                chosen = eligible_prs(gh, repo, args.min_comments, args.limit)
                added = jobs.enqueue(repo, chosen)
                print(
                    f"selected {len(chosen)} merged PRs with >= {args.min_comments} comments "
                    f"({added} new in the job list)"
                )
            if args.redo_fallback:
                hosted = build_llm_client(s, cache, Budget(1), order="gemini,groq")
                redo = requeue_fallback(repo, jobs, store, hosted)
                print(f"requeued {len(redo)} PR(s) the local model had answered: {redo}")
            if args.dry_run:
                report = ingest(repo, jobs, gh, store, llm, None, dry_run=True)
            else:
                target = aura_target(s) if args.target == "aura" else local_test_target()
                with target.driver() as driver:
                    sink = Neo4jSink(driver, target.database, repo)
                    report = ingest(repo, jobs, gh, store, llm, sink)
            print(f"GitHub requests {gh.stats.requests} ({gh.stats.not_modified} not modified)")
        print_report(report, llm, jobs, repo)
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {redact(str(exc), s)[:300]}")
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
