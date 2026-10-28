"""Extract decisions for one PR already in raw_github.

python -m whycode.extract.run --repo psf/requests --pr 5797 --dry-run   # no LLM calls
python -m whycode.extract.run --repo psf/requests --pr 5797             # spends LLM calls
"""

import argparse
import logging
import sys

from whycode.extract.extractor import DEFAULT_MAX_CHARS, ExtractionResult, extract_thread


def print_result(r: ExtractionResult, llm, checks: list | None = None) -> None:
    """checks[i] is the AffectsCheck for r.decisions[i], when the PR's code is indexed."""
    print(f"chunks: {len(r.chunks)}")
    for c in r.chunks:
        state = "cached" if c.cached else ("would call LLM" if r.dry_run else "called LLM")
        print(f"  part {c.label or c.index}: {len(c.sources)} sources, {c.chars:,} chars, {state}")
    if r.dry_run:
        print(f"dry run: 0 API calls; {sum(not c.cached for c in r.chunks)} chunk(s) would call")
        return
    print(f"\naccepted decisions: {len(r.decisions)}")
    if checks is not None:
        kept = sum(len(c.kept) for c in checks)
        dropped = sum(len(c.dropped) for c in checks)
        print(f"affects checked against the PR's code: {kept} kept, {dropped} dropped")
    for n, d in enumerate(r.decisions, 1):
        x = d.data
        print(f"\n[{n}] {x.summary}")
        print(f"    decided {x.decided_at}  {x.evidence_kind}  confidence {x.confidence:.2f}")
        print(f"    why: {x.rationale}")
        for alt in x.alternatives:
            print(f"    alternative: {alt}")
        if checks is None:
            for a in x.affects:
                print(
                    f"    affects {a.kind} (unchecked): {a.path}{'::' + a.name if a.name else ''}"
                )
        else:
            for k in checks[n - 1].kept:
                note = f"  ({k.note})" if k.note else ""
                print(f"    affects {k.kind.value}: {k.id}{note}")
            for drop in checks[n - 1].dropped:
                a = drop.item
                print(
                    f"    dropped {a.kind} {a.path}{'::' + a.name if a.name else ''}: {drop.reason}"
                )
        for e in d.evidence:
            print(f'    "{e.quote}"')
            print(f"      - {e.source.author or '?'}, {(e.source.date or '')[:10]}, {e.source.url}")
    if r.stopped_early:
        print(f"\nINCOMPLETE: {r.stopped_early}; re-run to continue (finished parts are cached)")
    print(f"\nrejected decisions: {len(r.rejections)}")
    for rej in r.rejections:
        print(f"  part {rej.chunk}: {rej.summary!r}: {rej.reason}")
    for i, why in r.failed_chunks:
        print(f"  part {i} failed: {why}")
    print(
        f"\nLLM: {llm.api_calls} API call(s), {llm.cache_hits} cache hit(s), "
        f"budget {llm.budget.used}/{llm.budget.max_calls}"
    )


def main() -> int:
    from whycode.code.affects import resolve_affects
    from whycode.code.index import build_pr_code_index
    from whycode.config import ConfigError, get_settings
    from whycode.extract.prompt import render_code_outline
    from whycode.extract.sources import load_thread
    from whycode.ingest.store import RawStore
    from whycode.llm.cache import PgLLMCache
    from whycode.llm.client import Budget, build_llm_client

    parser = argparse.ArgumentParser(description="Extract decisions for one PR.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true", help="show what would be sent; no calls")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--max-calls", type=int, help="cap this run below LLM_MAX_CALLS")
    parser.add_argument(
        "--providers", help="override LLM_PROVIDERS for this run, e.g. 'local' or 'gemini,local'"
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows defaults to cp1252
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        s = get_settings()
    except ConfigError as exc:
        print(f"FAIL config: {exc}")
        return 2

    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    try:
        cache = PgLLMCache(store.conn)
        cache.ensure_schema()
        cap = s.llm_max_calls if args.max_calls is None else min(args.max_calls, s.llm_max_calls)
        llm = build_llm_client(s, cache, Budget(cap), order=args.providers)
        print("providers: " + " -> ".join(f"{p.name}/{p.model}" for p in llm.providers))
        thread = load_thread(store, args.repo, args.pr)
        print(f"{thread.repo}#{thread.number}: {thread.title}")
        print(
            f"sources: {len(thread.sources)} ({sum(len(x.text) for x in thread.sources):,} chars)"
        )
        try:
            index = build_pr_code_index(store, args.repo, args.pr)
        except LookupError:
            index = None
        outline = render_code_outline(index) if index and index.parsed else None
        if outline is None:
            print("note: no parsed code for this PR; the prompt has no code outline")
        result = extract_thread(
            thread, llm, max_chars=args.max_chars, dry_run=args.dry_run, code_outline=outline
        )
        checks = None
        if not args.dry_run and result.decisions:
            if index is None:
                print("affects not checked: the PR's code is not indexed; run fetch_pr")
            else:
                if index.missing_code:
                    print(f"note: code not fetched for {index.missing_code}; run fetch_pr again")
                checks = [resolve_affects(d.data.affects, index) for d in result.decisions]
        print_result(result, llm, checks)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
