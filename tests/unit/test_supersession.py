import json

from tests.fakes import FakeProvider, MemoryLLMCache
from whycode.graph.supersession import (
    SYSTEM,
    DecisionInfo,
    Pair,
    build_user_prompt,
    check_verdict,
    judge_pairs,
    load_details,
    select_pairs,
)
from whycode.llm.client import Budget, LLMClient


def row(new, old, kinds, new_summary="Use Y parser", old_summary="Use X parser", shared=("e",)):
    return {
        "new_id": new,
        "old_id": old,
        "new_summary": new_summary,
        "old_summary": old_summary,
        "kinds": list(kinds),
        "shared": list(shared),
    }


# --- candidates ---------------------------------------------------------------------------


def test_sharing_a_function_is_enough():
    pairs = select_pairs([row("n", "o", ["Function"], "Totally new wording", "Nothing alike")])
    assert [(p.newer, p.older) for p in pairs] == [("n", "o")]


def test_sharing_only_a_file_needs_overlapping_summaries():
    unrelated = row("n", "o", ["File"], "Bump the tox environments", "Add a HISTORY entry")
    related = row(
        "n2",
        "o2",
        ["File"],
        "Rename the lgpl extra to use_chardet_on_py3",
        "Add the lgpl extra to install chardet",
    )
    assert [p.newer for p in select_pairs([unrelated, related])] == ["n2"]


def test_at_most_three_older_candidates_per_newer_decision_best_first():
    rows = [row("n", f"o{i}", ["File"], "use chardet extra", "use chardet extra") for i in range(5)]
    rows.append(row("n", "best", ["Function", "File"]))
    pairs = select_pairs(rows)
    assert len(pairs) == 3 and pairs[0].older == "best"


# --- verdicts ------------------------------------------------------------------------------

NEWER = DecisionInfo(
    "r/x#dec:new", "Rename the extra", "Clearer name", "2021-05-28", [5797],
    [("r/x#ev:pr:1:rc:2", "Missed the replacement there `use_chardet_on_py3`")],
)  # fmt: skip
OLDER = DecisionInfo(
    "r/x#dec:old", "Add the lgpl extra", "Escape hatch", "2021-04-22", [5797],
    [("r/x#ev:pr:1:body", "there is a new extra added, `requests[lgpl]`")],
)  # fmt: skip


def verdict(kind="replaces", evidence_id="r/x#ev:pr:1:rc:2", confidence=0.8):
    return json.dumps(
        {"kind": kind, "confidence": confidence, "evidence_id": evidence_id, "explanation": "x"}
    )


def test_link_citing_the_newer_decisions_evidence_is_accepted():
    v, rejected = check_verdict(verdict(), NEWER)
    assert v.kind == "replaces" and rejected is None


def test_link_citing_the_older_decisions_evidence_is_refused():
    v, rejected = check_verdict(verdict(evidence_id="r/x#ev:pr:1:body"), NEWER)
    assert v.kind == "unrelated" and "not the newer decision's evidence" in rejected


def test_link_citing_an_invented_id_or_nothing_is_refused():
    for eid in ("r/x#ev:made-up", None):
        v, rejected = check_verdict(verdict(evidence_id=eid), NEWER)
        assert v.kind == "unrelated" and rejected


def test_unrelated_needs_no_evidence():
    v, rejected = check_verdict(verdict(kind="unrelated", evidence_id=None), NEWER)
    assert v.kind == "unrelated" and rejected is None


def test_malformed_verdict_is_refused():
    for raw in ("not json", json.dumps({"kind": "obsoletes", "confidence": 1})):
        v, rejected = check_verdict(raw, NEWER)
        assert v.kind == "unrelated" and rejected.startswith("invalid JSON")


def test_prompt_shows_both_decisions_dates_and_evidence_ids():
    user = build_user_prompt(OLDER, NEWER, ("r/x#file:setup.py",))
    assert user.index("OLDER DECISION (2021-04-22") < user.index("NEWER DECISION (2021-05-28")
    assert "[r/x#ev:pr:1:rc:2]" in user and "Both affect: r/x#file:setup.py" in user
    assert "A wrong link is worse than a missing one" in SYSTEM


# --- judging -------------------------------------------------------------------------------

DETAILS = {NEWER.id: NEWER, OLDER.id: OLDER}
PAIR = Pair(NEWER.id, OLDER.id, ("r/x#file:setup.py",), 0.5)


def test_judge_dry_run_makes_no_call():
    gem = FakeProvider("gemini", "g", [verdict()])
    llm = LLMClient([gem], MemoryLLMCache(), Budget(5))
    judgements, stopped = judge_pairs(llm, [PAIR], DETAILS, "r/x", dry_run=True)
    assert gem.calls == [] and judgements[0].verdict is None and stopped is None


def test_judge_and_cache():
    gem = FakeProvider("gemini", "g", [verdict()])
    llm = LLMClient([gem], MemoryLLMCache(), Budget(5))
    first, _ = judge_pairs(llm, [PAIR], DETAILS, "r/x")
    again, _ = judge_pairs(llm, [PAIR], DETAILS, "r/x")
    assert first[0].verdict.kind == again[0].verdict.kind == "replaces"
    assert len(gem.calls) == 1 and again[0].cached


def test_spent_budget_stops_judging_cleanly():
    llm = LLMClient([FakeProvider("gemini", "g")], MemoryLLMCache(), Budget(0))
    judgements, stopped = judge_pairs(llm, [PAIR, PAIR], DETAILS, "r/x")
    assert judgements == [] and stopped.startswith("stopped at pair 1 of 2")


def test_load_details_cuts_quotes_from_spans():
    rows = [
        {
            "d": {"id": "r/x#dec:a", "summary": "S", "rationale": "R", "decided_at": "2021-05-28"},
            "evidence": [
                {"id": "r/x#ev:1", "text": "hello world, more", "start": 0, "end": 11},
                {"id": None, "text": None, "start": None, "end": None},  # OPTIONAL MATCH miss
            ],
            "prs": [5797, None],
        }
    ]
    info = load_details(lambda q, p: rows, "r/x", {"r/x#dec:a"})["r/x#dec:a"]
    assert info.evidence == [("r/x#ev:1", "hello world")] and info.prs == [5797]
