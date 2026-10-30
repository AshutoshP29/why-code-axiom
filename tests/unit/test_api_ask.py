from datetime import UTC, datetime

import pytest

from tests.api_fakes import (
    COMMIT,
    DEC,
    FN,
    GH,
    NODES,
    PERSON,
    PR,
    QUOTE_SOURCE,
    REPO,
    UNEXPLAINED,
    FakeGraph,
    assert_repo_filtered,
    client,
    evidence,
    q5a_row,
)
from whycode.api import answers
from whycode.graph import queries

QUOTE = QUOTE_SOURCE[:47]  # the span evidence() marks
QUESTION = "Why does apparent_encoding use charset_normalizer?"
FIXED_REASONS = {
    answers.NO_MATCH_REASON,
    answers.MODULE_REASON,
    answers.LOW_CONFIDENCE_REASON,
    "The graph has no recorded decision for this. The facts below say what changed it "
    "and when; they are not reasons.",
}
SEARCH_HIT = {
    "node": NODES[FN],
    "score": 3.0,  # scaled to 0.75
}


def ask(graph, entity_id=FN, question=QUESTION, repo=REPO):
    res = client(graph).post(
        "/api/ask", json={"repo": repo, "entity_id": entity_id, "question": question}
    )
    return res


def answered_graph(**kw):
    return FakeGraph(q5a=[q5a_row()], **kw)


def test_selected_entity_with_explicit_decision_is_answered():
    graph = answered_graph(
        decision_context=[{"affects": [NODES[FN], NODES[UNEXPLAINED]], "supersedes": []}]
    )
    res = ask(graph)
    assert res.status_code == 200
    a = res.json()
    assert a["verdict"] == "answered"
    assert (a["matched_by"], a["match_score"], a["confidence"]) == ("selected", None, 1.0)
    assert a["thresholds"] == {"answer": 0.7, "refuse": 0.4}
    assert a["partial_history"] is True
    assert a["entity"]["id"] == FN
    assert a["decision"] == {
        "id": DEC,
        "summary": "Replace chardet with charset_normalizer",
        "rationale": "chardet is LGPL, which is ambiguous inside an MIT library.",
        "alternatives": ["Keep chardet as an optional extra"],
        "decided_at": "2021-07-06",
        "status": "ACTIVE",
        "evidence_kind": "EXPLICIT",
        "proposed_by": "ashb",
        "reviewed_by": "nateprewitt",
        "approved_by": ["nateprewitt"],
        "source": {"id": PR, "label": "PR #5797", "url": f"{GH}/pull/5797"},
    }
    assert a["answer_text"] == (
        "Replace chardet with charset_normalizer. chardet is LGPL, which is ambiguous inside an "
        "MIT library. Decided on 2021-07-06 in PR #5797."
    )
    assert a["superseded"] == []
    assert [(s["kind"], s["title"], s["excerpt"]) for s in a["evidence_chain"]] == [
        ("discussion", "PR #5797: description", QUOTE),
        (
            "discussion",
            "PR #5797: comment by @nateprewitt",
            QUOTE,
        ),
    ]
    assert a["evidence_chain"][0]["meta"] == ["2021-04-22", "@ashb"]
    assert [(p["login"], p["role"]) for p in a["who_to_ask"]] == [
        ("ashb", "Proposed the decision"),
        ("nateprewitt", "Approved it"),
    ]
    labels = {f["label"]: f for f in a["confidence_factors"]}
    assert labels["Independent sources"]["display"] == "2 sources"
    nodes = {n["id"]: n for n in a["graph"]["nodes"]}
    assert nodes[DEC]["center"] and nodes[FN]["entity_id"] == FN
    assert nodes[PR]["kind"] == "pull_request"
    assert f"{REPO}#user:ashb" in nodes
    assert {(e["from"], e["to"], e["label"]) for e in a["graph"]["edges"]} >= {
        (DEC, FN, "AFFECTS"),
        (DEC, UNEXPLAINED, "AFFECTS"),
        (DEC, PR, "DECIDED_IN"),
        (DEC, f"{REPO}#user:ashb", "PROPOSED_BY"),
        (DEC, f"{REPO}#user:nateprewitt", "APPROVED_BY"),
    }
    assert_repo_filtered(graph)


def test_question_without_entity_is_matched_by_search():
    graph = answered_graph(search=[SEARCH_HIT])
    a = ask(graph, entity_id=None).json()
    assert a["verdict"] == "answered"
    assert (a["matched_by"], a["match_score"]) == ("search", 0.75)
    assert a["entity"]["id"] == FN
    assert a["confidence"] == round(0.25 * 0.75 + 0.75, 2)
    search = next(p for c, p in graph.calls if "q:search" in c)
    assert search["q"] == "why does apparent_encoding use charset_normalizer"
    assert_repo_filtered(graph)


def test_weak_match_on_inferred_single_source_is_hedged():
    row = q5a_row(evidence_kind="INFERRED")
    row["evidence"] = [evidence(0)]
    weak_hit = {"node": NODES[FN], "score": 1.5}  # scaled to 0.6: above the floor, not good
    graph = FakeGraph(q5a=[row], search=[weak_hit])
    a = ask(graph, entity_id=None).json()
    assert a["verdict"] == "hedged"
    assert 0.4 <= a["confidence"] < 0.7
    assert a["warning"].startswith("Confidence is limited by entity match (60%)")
    assert "evidence directness (Inferred)" in a["warning"]
    assert a["decision"]["evidence_kind"] == "INFERRED"


def test_entity_without_decision_is_refused_with_known_facts():
    graph = FakeGraph(
        exists=[{"id": UNEXPLAINED}],
        facts=[{"c": COMMIT, "m": {"added": 3, "removed": 1}, "p": PERSON}],
    )
    res = ask(graph, entity_id=UNEXPLAINED, question="Why check compatibility?")
    a = res.json()
    assert res.status_code == 200
    assert a["verdict"] == "refused"
    assert a["confidence"] == 0.25
    assert a["reason"] in FIXED_REASONS
    assert a["known_facts"] == [
        {
            "title": "Commit 0123456: Switch to charset_normalizer",
            "detail": "changed it: +3 / -1 lines",
            "meta": ["2021-07-06"],
            "source": {"id": COMMIT["url"], "label": "Commit 0123456", "url": COMMIT["url"]},
        }
    ]
    assert [(p["login"], p["role"]) for p in a["who_to_ask"]] == [("ashb", "Last changed it")]
    assert a["history_url"] == f"{GH}/commits/HEAD/src/requests/__init__.py"
    assert a["related"] == []
    assert "decision" not in a and "answer_text" not in a
    assert_repo_filtered(graph)


def test_question_matching_nothing_is_refused_with_no_entity():
    a = ask(FakeGraph(search=[]), entity_id=None, question="What about the weather?").json()
    assert a["verdict"] == "refused"
    assert (a["entity"], a["matched_by"], a["match_score"]) == (None, "search", None)
    assert a["reason"] == answers.NO_MATCH_REASON
    assert a["confidence"] == 0.0
    assert a["history_url"] == f"{GH}/commits/HEAD"


def test_module_is_refused_without_querying_decisions():
    mod = {"id": f"{REPO}#mod:requests", "name": "requests"}
    graph = FakeGraph(entity=[{"e": mod}])
    a = ask(graph, entity_id=mod["id"]).json()
    assert a["verdict"] == "refused"
    assert a["reason"] == answers.MODULE_REASON
    assert not any("SUPPORTED_BY" in c for c, _ in graph.calls)


def test_search_skips_modules():
    mod_hit = {"node": {"id": f"{REPO}#mod:requests", "name": "requests"}, "score": 9.0}
    a = ask(answered_graph(search=[mod_hit, SEARCH_HIT]), entity_id=None).json()
    assert a["entity"]["id"] == FN


def test_low_confidence_with_a_decision_is_refused_by_fixed_text(monkeypatch):
    monkeypatch.setattr(answers, "MIN_SEARCH_MATCH", 0.0)  # let a zero match reach scoring
    row = q5a_row(evidence_kind="INFERRED")
    row["evidence"] = [{**evidence(0), "end": 0}]  # empty quote: citation fails
    zero_hit = {"node": NODES[FN], "score": 0.0}
    a = ask(FakeGraph(q5a=[row], search=[zero_hit]), entity_id=None).json()
    assert a["verdict"] == "refused"
    assert a["confidence"] < 0.4
    assert a["reason"] == answers.LOW_CONFIDENCE_REASON


def test_superseded_decisions_are_listed_and_dimmed():
    older = {
        "id": f"{REPO}#dec:old",
        "summary": "Use chardet",
        "rationale": "It was the only detector.",
        "decided_at": datetime(2012, 1, 1, tzinfo=UTC),
        "status": "SUPERSEDED",
        "evidence_kind": "INFERRED",
    }
    old_pr = {"id": f"{REPO}#pr:100", "number": 100, "url": f"{GH}/pull/100"}
    graph = answered_graph(
        decision_context=[
            {
                "affects": [NODES[FN]],
                "supersedes": [
                    {"decision": older, "kind": "replaces", "source": old_pr},
                    {"decision": older, "kind": "replaces", "source": old_pr},  # duplicate row
                    {"decision": None, "kind": None, "source": None},  # OPTIONAL MATCH miss
                ],
            }
        ]
    )
    a = ask(graph).json()
    (note,) = a["superseded"]
    assert note["kind"] == "replaces"
    assert note["superseded_at"] == "2021-07-06"
    assert note["decision"]["source"]["label"] == "PR #100"
    assert note["decision"]["status"] == "SUPERSEDED"
    dimmed = [n for n in a["graph"]["nodes"] if n["dimmed"]]
    assert [n["id"] for n in dimmed] == [older["id"]]
    factor = next(f for f in a["confidence_factors"] if f["label"] == "Supersession resolved")
    assert factor["display"] == "Yes"


def test_partial_decision_is_pending_supersession():
    a = ask(FakeGraph(q5a=[q5a_row(status="PARTIAL")])).json()
    factor = next(f for f in a["confidence_factors"] if f["label"] == "Supersession resolved")
    assert (factor["value"], factor["display"]) == (0.5, "Refined, not settled")
    assert a["decision"]["status"] == "PARTIAL"
    assert a["verdict"] == "answered"  # supersession counts half: 0.925, still above 0.70


def test_unknown_selected_entity_is_404_and_bad_input_422():
    assert ask(FakeGraph(), entity_id=f"{REPO}#fn:x.py::nope").status_code == 404
    assert ask(FakeGraph(), question="").status_code == 422
    assert ask(FakeGraph(), repo="pallets/flask").status_code == 404


@pytest.mark.parametrize(
    ("evidence_id", "label"),
    [
        (f"{REPO}#ev:pr:5797:body", "PR #5797"),
        (f"{REPO}#ev:issue:812:ic:3", "Issue #812"),
        (f"{REPO}#ev:commit:0123456789:msg", "Commit 0123456"),
        (f"{REPO}#ev:doc:README.md", "Source"),
    ],
)
def test_evidence_labels(evidence_id, label):
    assert answers._evidence_label(evidence_id) == label


def test_evidence_step_kinds_and_source_kinds():
    ev = queries.EvidenceRef(id=f"{REPO}#ev:commit:abc:msg", quote="q", source_type="commit_msg")
    step = answers._step(ev, "fallback")
    assert (step.kind, step.title, step.meta, step.source.url) == (
        "commit",
        "Commit abc: commit message",
        [],
        "fallback",
    )
    assert answers._source_kind(f"{REPO}#issue:1") == "issue"
    assert answers._source_kind(f"{REPO}#commit:abc") == "commit"


def test_decision_without_source_or_people_still_maps():
    dv = queries.DecisionView(
        id=DEC,
        summary="Keep it.",
        rationale="Because the PR says so",
        decided_at=datetime(2020, 1, 1, tzinfo=UTC),
        status="weird",
        evidence_kind="INFERRED",
        confidence=0.5,
        evidence=[queries.EvidenceRef(id="e", quote="q", source_type="pr_body")],
    )
    d = answers._decision(dv, REPO)
    assert (d.status, d.proposed_by, d.reviewed_by, d.source.label) == (
        "ACTIVE",
        None,
        None,
        "Decision",
    )
    assert answers.answer_text(d) == "Keep it. Because the PR says so. Decided on 2020-01-01."


def test_older_decision_without_source():
    older = {"id": "o", "decided_at": datetime(2012, 1, 1, tzinfo=UTC)}
    note = answers._older({"decision": older, "kind": "refines"}, REPO, datetime(2020, 1, 1).date())
    assert (note.decision.source.label, note.decision.status) == ("Decision", "SUPERSEDED")


def test_context_with_no_row():
    assert answers._context(FakeGraph(), REPO, DEC) == ([], [])


def test_weak_search_match_is_refused_not_answered_with_an_unrelated_decision():
    # Seen on the real graph: "What is the capital of France? asked via requests packages"
    # matched packages.py at 0.05 and was answered at 0.76 with the chardet decision.
    weak_hit = {"node": NODES[FN], "score": 0.05}
    other = {"node": NODES[UNEXPLAINED], "score": 0.04}
    graph = answered_graph(search=[weak_hit, other])
    a = ask(graph, entity_id=None, question="What is the capital of France?").json()
    assert a["verdict"] == "refused" and a["reason"] == answers.WEAK_MATCH_REASON
    assert a["entity"] is None and a["confidence"] < 0.4
    assert [r["source"]["id"] for r in a["related"]] == [FN, UNEXPLAINED]  # pick one of these
    assert not any("SUPPORTED_BY" in c for c, _ in graph.calls)  # no decision was looked up


def test_the_same_person_quoted_twice_is_one_independent_source():
    row = q5a_row()
    row["evidence"] = [evidence(0, author="ashb"), evidence(1, kind="pr_comment", author="ashb")]
    a = ask(FakeGraph(q5a=[row])).json()
    labels = {f["label"]: f for f in a["confidence_factors"]}
    assert labels["Independent sources"]["display"] == "1 of 2 needed"
