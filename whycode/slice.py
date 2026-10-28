"""One pull request end to end: fetch, extract, write to Neo4j, answer query 5a.

    python -m whycode.slice --repo psf/requests --pr 5797
    python -m whycode.slice --repo psf/requests --pr 5797 --target test --max-calls 0

Prints the current decision for the code entity the extraction linked most, with its evidence
quotes, URLs, people and date; then a refusal for code the PR changed but no decision explains;
then the repo's node count in Neo4j. LLM answers come from the cache when they exist, so a
re-run costs no calls; --max-calls caps the hosted APIs for this run.
"""

import argparse
import logging
import sys
from collections import Counter

from whycode.graph.queries import Answer, Refusal


def pick_entities(batch) -> tuple[str | None, str | None]:
    """(entity to answer about, entity to show a refusal for).

    Answer: the entity most decisions AFFECT, preferring code over whole files. Refusal: code the
    PR MODIFIED that no decision affects.
    """
    affected = Counter(
        target for (t, _, _), pairs in batch.rels.items() if t == "AFFECTS" for _, target in pairs
    )
    ranked = sorted(affected, key=lambda i: ("#file:" in i, -affected[i], i))
    modified = sorted(
        target
        for (t, _, label), pairs in batch.rels.items()
        if t == "MODIFIES" and label in ("Function", "Class", "ConfigKey")
        for _, target in pairs
    )
    unexplained = [i for i in modified if i not in affected]
    return (ranked[0] if ranked else None), (unexplained[0] if unexplained else None)


def print_answer(r: Answer | Refusal) -> None:
    if isinstance(r, Refusal):
        print(f"REFUSED for {r.entity_id}")
        print(f"  {r.reason}")
        for f in r.known_facts:
            when = f.date.date() if f.date else "?"
            print(f"  fact: {f.title} ({when}): {f.detail}  {f.url or ''}")
        if r.last_owner:
            state = "active" if r.last_owner.active else "not active in the last ~18 months"
            print(f"  last changed by: {r.last_owner.login} ({state})")
        return
    print(f"ANSWER for {r.entity_id}")
    for d in r.decisions:
        print(f"  Decision: {d.summary}")
        print(f"  Why: {d.rationale}")
        print(
            f"  Decided: {d.decided_at.date()}  ({d.evidence_kind}, confidence {d.confidence:.2f})"
        )
        for s in d.decided_in:
            print(f"  Decided in: {s.label}  {s.url or ''}")
        if d.proposed_by:
            print("  Proposed by: " + ", ".join(p.login for p in d.proposed_by))
        if d.approved_by:
            print("  Approved by: " + ", ".join(p.login for p in d.approved_by))
        for alt in d.alternatives:
            print(f"  Alternative considered: {alt}")
        for e in d.evidence:
            when = e.date.date() if e.date else "?"
            print(f'  Evidence: "{e.quote}"')
            print(f"    - {e.author or '?'}, {when}, {e.url or ''}")
        print()


def main() -> int:
    from whycode.code.affects import resolve_affects
    from whycode.code.index import build_pr_code_index
    from whycode.config import ConfigError, get_settings, redact
    from whycode.extract.extractor import extract_thread
    from whycode.extract.prompt import PROMPT_VERSION, render_code_outline
    from whycode.extract.sources import load_thread
    from whycode.graph.build import build_pr_graph
    from whycode.graph.client import aura_target, local_test_target
    from whycode.graph.queries import current_decisions, neo4j_runner
    from whycode.graph.writer import repo_counts, write_batch
    from whycode.ingest.fetch_pr import fetch_pr
    from whycode.ingest.github import GitHubClient
    from whycode.ingest.store import RawStore
    from whycode.llm.cache import PgLLMCache
    from whycode.llm.client import Budget, build_llm_client

    parser = argparse.ArgumentParser(description="One pull request end to end.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--target", choices=["aura", "test"], default="aura")
    parser.add_argument("--max-calls", type=int, help="cap hosted LLM calls below LLM_MAX_CALLS")
    parser.add_argument("--providers", help="override LLM_PROVIDERS for this run")
    parser.add_argument("--entity", help="graph id to ask about instead of the automatic pick")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        s = get_settings()
    except ConfigError as exc:
        print(f"FAIL config: {exc}")
        return 2

    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    target = aura_target(s) if args.target == "aura" else local_test_target()
    try:
        store.ensure_schema()
        print(f"[1/4] fetch {args.repo}#{args.pr}")
        with GitHubClient(s.github_token.get_secret_value()) as gh:
            fetch_pr(gh, store, args.repo, args.pr)
            print(
                f"      GitHub requests {gh.stats.requests} ({gh.stats.not_modified} not modified)"
            )

        print("[2/4] extract decisions")
        cache = PgLLMCache(store.conn)
        cache.ensure_schema()
        cap = s.llm_max_calls if args.max_calls is None else min(args.max_calls, s.llm_max_calls)
        llm = build_llm_client(s, cache, Budget(cap), order=args.providers)
        thread = load_thread(store, args.repo, args.pr)
        index = build_pr_code_index(store, args.repo, args.pr)
        result = extract_thread(thread, llm, code_outline=render_code_outline(index) or None)
        checks = [resolve_affects(d.data.affects, index) for d in result.decisions]
        print(
            f"      {len(result.decisions)} decisions, {len(result.rejections)} rejected; "
            f"LLM {llm.api_calls} calls, {llm.cache_hits} cached"
        )
        if result.stopped_early:
            print(f"      INCOMPLETE: {result.stopped_early}; writing what was extracted")

        print(f"[3/4] write to Neo4j ({target.name})")
        batch = build_pr_graph(
            store, thread, result.decisions, checks, index=index, prompt_version=PROMPT_VERSION
        )
        with target.driver() as driver:
            stats = write_batch(driver, target.database, batch)
            print(
                f"      {stats.nodes} nodes and {stats.relationships} relationships merged; "
                f"{stats.decisions_replaced} old decisions replaced"
            )

            print("[4/4] query 5a\n")
            answer_for, refuse_for = pick_entities(batch)
            run = neo4j_runner(driver, target.database)
            for entity in [args.entity] if args.entity else [answer_for, refuse_for]:
                if entity:
                    print_answer(current_decisions(run, thread.repo, entity))
                    print()
            by_label, rels = repo_counts(driver, target.database, thread.repo)
            total = sum(by_label.values())
            print(
                f"Neo4j ({target.name}) holds {total} nodes and {rels} relationships "
                f"for {thread.repo}:"
            )
            print("  " + ", ".join(f"{label} {n}" for label, n in by_label.items()))
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {redact(str(exc), s)[:300]}")
        if args.target == "aura":
            print("If Neo4j is unreachable, the free Aura instance may be paused: resume it.")
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
