from datetime import UTC, datetime

import pytest

from whycode.graph.queries import Answer, Refusal, current_decisions, label_for

FN = "psf/requests#fn:src/requests/models.py::Response.apparent_encoding"
TEXT = "By changing out this dependency for one under MIT we remove all license ambiguity. More."


class FakeRun:
    """Stands in for Neo4j: answers by which query it is given, records every call."""

    def __init__(self, decisions=(), entity_exists=True, facts=()):
        self.decisions, self.entity_exists, self.facts = list(decisions), entity_exists, list(facts)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, cypher: str, params: dict) -> list[dict]:
        self.calls.append((cypher, params))
        if "AFFECTS" in cypher:
            return self.decisions
        if "MODIFIES" in cypher:
            return self.facts
        return [{"id": params["entityId"]}] if self.entity_exists else []


def decision_row():
    return {
        "d": {
            "id": "psf/requests#dec:abc",
            "summary": "Replace chardet with charset_normalizer",
            "rationale": "Remove LGPL ambiguity.",
            "alternatives": ["Keep chardet"],
            "decided_at": datetime(2021, 7, 6, tzinfo=UTC),
            "status": "ACTIVE",
            "evidence_kind": "EXPLICIT",
            "extraction_confidence": 0.97,
        },
        "evidence": [
            {
                "ev": {
                    "id": "psf/requests#ev:pr:5797:body",
                    "text": TEXT,
                    "source_type": "pr_body",
                    "url": "https://github.com/psf/requests/pull/5797",
                    "author": "ashb",
                    "date": datetime(2021, 4, 22, tzinfo=UTC),
                },
                "start": 0,
                "end": 82,
            }
        ],
        "proposers": [{"login": "ashb", "active": False, "last_seen": None}],
        "approvers": [{"login": "sigmavirus24", "active": False}, None],
        "sources": [
            {
                "id": "psf/requests#pr:5797",
                "number": 5797,
                "url": "https://github.com/psf/requests/pull/5797",
            }
        ],
    }


def test_answer_has_decision_quotes_people_and_source():
    r = current_decisions(FakeRun([decision_row()]), "psf/requests", FN)
    assert isinstance(r, Answer) and r.verdict == "answered"
    d = r.decisions[0]
    assert d.summary.startswith("Replace chardet") and d.confidence == 0.97
    assert d.evidence[0].quote == TEXT[:82] and d.evidence[0].author == "ashb"
    assert [p.login for p in d.proposed_by] == ["ashb"]
    assert [p.login for p in d.approved_by] == [
        "sigmavirus24"
    ]  # the None from OPTIONAL MATCH is dropped
    assert d.decided_in[0].label == "PR #5797"


def test_query_uses_the_entity_label_and_always_filters_by_repo():
    run = FakeRun([decision_row()])
    current_decisions(run, "PSF/Requests", FN)
    cypher, params = run.calls[0]
    assert "(e:Function {id: $entityId, repo: $repo})" in cypher
    assert "d:Decision {repo: $repo}" in cypher
    assert params == {"repo": "psf/requests", "entityId": FN}


def test_refusal_for_an_entity_with_no_decision_is_built_from_facts_only():
    facts = [
        {
            "c": {
                "sha": "3e798b94717918",
                "message": "Switch chardet\n\nbody",
                "date": datetime(2021, 7, 6, tzinfo=UTC),
                "url": "u",
            },
            "m": {"added": 3, "removed": 1},
            "p": {"login": "ashb", "active": False},
        }
    ]
    r = current_decisions(FakeRun(facts=facts), "psf/requests", FN)
    assert isinstance(r, Refusal) and r.verdict == "refused" and r.entity_found
    assert "no recorded decision" in r.reason and "not reasons" in r.reason
    assert r.known_facts[0].title == "Commit 3e798b9: Switch chardet"
    assert r.known_facts[0].detail == "changed it: +3 / -1 lines"
    assert r.last_owner.login == "ashb"
    assert not hasattr(r, "decisions")  # nothing invented


def test_refusal_for_an_unknown_entity():
    r = current_decisions(FakeRun(entity_exists=False), "psf/requests", FN)
    assert isinstance(r, Refusal) and not r.entity_found and r.known_facts == []
    assert "is not in the graph" in r.reason


def test_refusal_without_any_facts_has_no_owner():
    r = current_decisions(FakeRun(), "psf/requests", FN)
    assert (
        isinstance(r, Refusal) and r.entity_found and r.known_facts == [] and r.last_owner is None
    )


@pytest.mark.parametrize(
    "entity_id, label",
    [
        ("r/x#file:a.py", "File"),
        ("r/x#cls:a.py::A", "Class"),
        ("r/x#fn:a.py::f", "Function"),
        ("r/x#cfg:MAX", "ConfigKey"),
    ],
)
def test_label_for(entity_id, label):
    assert label_for(entity_id) == label


@pytest.mark.parametrize("bad", ["r/x#pr:1", "r/x#dec:abc", "nonsense", "r/x#fn) DETACH DELETE"])
def test_label_for_rejects_non_code_ids(bad):
    with pytest.raises(ValueError):
        label_for(bad)
