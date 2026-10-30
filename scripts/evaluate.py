"""Measure WhyCode on the graph it holds. Reads Neo4j and Postgres only; makes no LLM call.

    uv run python scripts/evaluate.py --repo psf/requests   # prints; writes docs/evaluation.*
    uv run python scripts/evaluate.py --repo psf/requests --no-write

Questions go through the same code as POST /api/ask (whycode.api.answers.ask), with no item
picked, so search has to find the code from the question text:

- Named code: "Why does <qualified name> work this way?" for every code item that has a
  decision (expect: matched to that item and answered with linked evidence) and for code that
  commits changed but no decision explains (expect: matched and refused, facts only).
- Off-topic questions (expect: refused with no item).
- Citations: every quote a decision cites must appear verbatim (whitespace aside) in the
  original GitHub text kept in Postgres, not only in the copy the graph holds.
- Supersession: every SUPERSEDES link is listed for a person to check, and code whose current
  decision replaced an older one must be answered with that older one named.

docs/evaluation.md is the report; docs/evaluation.json holds the same results for the API's
health and evaluation screens (GET /api/evaluation).
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

OFF_TOPIC = [
    "What is the capital of France?",
    "What is the capital of France? asked via requests packages",
    "How do I make pasta?",
    "Who won the 2018 football world cup?",
    "Why is the sky blue?",
    "What is the stock price of Apple today?",
    "Explain quantum computing in simple terms",
    "Write me a poem about the sea",
    "how do I bake bread at home",
    "requests OR",
]
Q_DECIDED = """
MATCH (e {repo: $repo})<-[:AFFECTS]-(:Decision {repo: $repo})
WHERE e:Class OR e:Function OR e:ConfigKey
RETURN DISTINCT e.id AS id ORDER BY id
"""
Q_SUPERSEDING = """
MATCH (e {repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})-[:SUPERSEDES]->(:Decision)
WHERE (e:Class OR e:Function OR e:ConfigKey) AND d.status <> 'SUPERSEDED'
RETURN DISTINCT e.id AS id
"""
Q_UNEXPLAINED = """
MATCH (:Commit {repo: $repo})-[:MODIFIES]->(e {repo: $repo})
WHERE (e:Class OR e:Function) AND NOT EXISTS { MATCH (e)<-[:AFFECTS]-(:Decision) }
RETURN DISTINCT e.id AS id ORDER BY id
"""
Q_CITATIONS = """
MATCH (d:Decision {repo: $repo})-[s:SUPPORTED_BY]->(e:Evidence)
MATCH (d)-[:DECIDED_IN]->(pr:PullRequest)
RETURN d.id AS decision, e.id AS evidence, e.text AS text, s.span_start AS start,
       s.span_end AS end, pr.number AS pr
"""
Q_LINKS = """
MATCH (n:Decision {repo: $repo})-[s:SUPERSEDES]->(o:Decision {repo: $repo})
RETURN s.kind AS kind, s.confidence AS confidence, n.summary AS newer, o.summary AS older,
       toString(date(n.decided_at)) AS newer_at, toString(date(o.decided_at)) AS older_at
ORDER BY kind, newer_at
"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def judge(expected, answer, matched):
    """One question's result, as the evaluation screen shows it."""
    if answer.verdict == "refused":
        outcome, cited = "refused", False
    else:
        outcome = "superseded" if answer.superseded else "answered"
        cited = bool(answer.evidence_chain) and all(s.source.url for s in answer.evidence_chain)
    correct = outcome == expected and (expected == "refused" or (matched and cited))
    return {"outcome": outcome, "correct": correct, "cited_source": cited}


def record(questions, question, entity, expected, answer, matched):
    result = judge(expected, answer, matched)
    questions.append(
        {
            "id": f"q{len(questions) + 1:03d}",
            "question": question,
            "entity": entity.model_dump() if entity else None,
            "expected": expected,
            "results": {"llm_only": None, "vector_rag": None, "whycode": result},
        }
    )
    return result


def ask_named(run, repo, ids, questions, expected_for):
    """Ask about each item by name, recording each question. Returns (counts, misses)."""
    from whycode.api import answers, reads

    out = Counter()
    misses = []
    for eid in ids:
        e = reads.get_entity(run, repo.id, eid)
        if e is None:
            continue
        q = f"Why does {e.qualified_name} work this way?"
        a = answers.ask(run, repo, q, None)
        out["asked"] += 1
        matched = a.entity is not None and a.entity.id == eid
        out["matched"] += matched
        out[a.verdict] += 1
        expected = expected_for(eid)
        result = record(questions, q, e, expected, a, matched)
        out[f"{expected}_asked"] += 1
        out[f"{expected}_correct"] += result["correct"]
        if a.verdict != "refused":
            out["with_evidence"] += result["cited_source"]
        if not matched:
            got = a.entity
            same = got is not None and got.qualified_name == e.qualified_name
            where = f"{got.qualified_name} in {got.path}" if got else "nothing"
            note = " (same name, another file)" if same else ""
            misses.append((q, f"{where}, not {e.path}{note}"))
    return out, misses


def citations(run, store, repo_id):
    from whycode.extract.sources import load_thread

    threads, ok, bad = {}, 0, []
    for r in run(Q_CITATIONS, {"repo": repo_id}):
        quote = (r["text"] or "")[r["start"] : r["end"]] if r["start"] is not None else ""
        if r["pr"] not in threads:
            t = load_thread(store, repo_id, r["pr"])
            threads[r["pr"]] = {s.source_id: s.text for s in t.sources}
        source_id = r["evidence"].split("#ev:", 1)[1]
        original = threads[r["pr"]].get(source_id)
        if quote.strip() and original is not None and _norm(quote) in _norm(original):
            ok += 1
        else:
            bad.append((r["decision"], r["evidence"], "missing source" if original is None else ""))
    return ok, bad


def main() -> int:
    from whycode.api import answers, reads
    from whycode.config import get_settings
    from whycode.graph.client import aura_target, local_test_target
    from whycode.graph.queries import neo4j_runner
    from whycode.ingest.store import RawStore

    parser = argparse.ArgumentParser(description="Measure WhyCode; no LLM calls.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--target", choices=["aura", "test"], default="aura")
    parser.add_argument("--no-write", action="store_true", help="print only")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    s = get_settings()
    target = aura_target(s) if args.target == "aura" else local_test_target()
    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    with target.driver() as driver:
        run = neo4j_runner(driver, target.database)
        repo = reads.repo(run, args.repo)
        decided = [r["id"] for r in run(Q_DECIDED, {"repo": repo.id})]
        superseding = {r["id"] for r in run(Q_SUPERSEDING, {"repo": repo.id})}
        unexplained = [r["id"] for r in run(Q_UNEXPLAINED, {"repo": repo.id})]
        questions = []
        d, d_miss = ask_named(
            run,
            repo,
            decided,
            questions,
            lambda eid: "superseded" if eid in superseding else "answered",
        )
        u, u_miss = ask_named(run, repo, unexplained, questions, lambda eid: "refused")
        off = Counter()
        for q in OFF_TOPIC:
            a = answers.ask(run, repo, q, None)
            off[a.verdict] += 1
            off["refused_correct"] += record(questions, q, None, "refused", a, True)["correct"]
        cited_ok, cited_bad = citations(run, store, repo.id)
        links = run(Q_LINKS, {"repo": repo.id})
    store.close()

    cited = cited_ok + len(cited_bad)
    lines = [
        f"# WhyCode evaluation: {repo.id}",
        "",
        f"Measured {date.today().isoformat()} with `scripts/evaluate.py` on the graph as it is "
        f"({repo.decisions_count} decisions). No LLM calls; every question goes through the same "
        "code as `POST /api/ask`, with no item picked.",
        "",
        "| What | Result |",
        "|---|---|",
        "| Named code with a decision: matched to the right item | "
        f"{_pct(d['matched'], d['asked'])} |",
        f"| ... and answered | {_pct(d['answered'] + d['hedged'], d['asked'])} |",
        "| ... answers whose every evidence step links to its source | "
        f"{_pct(d['with_evidence'], d['answered'] + d['hedged'])} |",
        "| ... whose decision replaced an older one: answered naming the older one | "
        f"{_pct(d['superseded_correct'], d['superseded_asked'])} |",
        f"| Named code no decision explains: matched | {_pct(u['matched'], u['asked'])} |",
        f"| ... refused (facts only, no reason given) | {_pct(u['refused'], u['asked'])} |",
        f"| Off-topic questions refused | {_pct(off['refused'], len(OFF_TOPIC))} |",
        f"| Cited quotes found verbatim in the original GitHub text | {_pct(cited_ok, cited)} |",
        f"| Supersession links (checked by hand below) | {len(links)} |",
        "",
        "Not measured: the LLM-only and vector-RAG baselines (they need LLM calls).",
        "",
        "## Supersession links",
        "",
        "| Kind | Newer decision | Older decision |",
        "|---|---|---|",
    ]
    lines += [
        f"| {r['kind']} ({r['confidence']:.2f}) | {r['newer_at']}: {r['newer'][:90]} | "
        f"{r['older_at']}: {r['older'][:90]} |"
        for r in links
    ]
    misses = d_miss + u_miss
    if misses:
        lines += [
            "",
            "## Named questions matched to a different item",
            "",
            "Most are a different item with the very same name in another file: the question",
            "alone cannot say which one is meant (picking the item in the UI does).",
            "",
        ]
        lines += [f"- {q} -> {got}" for q, got in misses]
    if cited_bad:
        lines += ["", "## Citations not found in the original text", ""]
        lines += [f"- {dec} cites {ev} {why}" for dec, ev, why in cited_bad]
    report = "\n".join(lines) + "\n"
    print(report)
    if not args.no_write:
        out = Path("docs/evaluation.md")
        out.parent.mkdir(exist_ok=True)
        out.write_text(report, encoding="utf-8", newline="\n")
        print(f"wrote {out}")
        named = d["matched"] + u["matched"], d["asked"] + u["asked"]
        refusals = (
            u["refused_correct"] + off["refused_correct"],
            u["refused_asked"] + len(OFF_TOPIC),
        )
        answered = d["answered"] + d["hedged"]
        rows = [
            ("Citation accuracy", cited_ok, cited),
            ("Supersession detected correctly", d["superseded_correct"], d["superseded_asked"]),
            ("Correct refusals", *refusals),
            ("Answers with evidence links", d["with_evidence"], answered),
            ("Right code found from the question", *named),
        ]
        write_json(Path("docs/evaluation.json"), repo.id, questions, rows)
    return 0


def write_json(path, repo_id, questions, rows):
    """Keep other repos' results; replace this repo's."""
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    saved[repo_id] = {
        "question_count": len(questions),
        "rows": [
            {"metric": name, "llm_only": None, "vector_rag": None, "whycode": n / d if d else None}
            for name, n, d in rows
        ],
        "questions": questions,
    }
    path.write_text(json.dumps(saved, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    sys.exit(main())
