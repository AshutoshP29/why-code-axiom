"""The API models must have exactly the fields of the TypeScript contract the screens use."""

import re
from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel, TypeAdapter

from whycode.api import models as m
from whycode.config import PROJECT_ROOT

TYPES_TS = PROJECT_ROOT / "frontend" / "src" / "api" / "types.ts"

# Fields the API sends on top of types.ts (Saanvi adds them to the contract at the same time).
ADDED = {
    "Decision": {"alternatives", "approved_by"},
    "LineageDecision": {"alternatives", "approved_by"},
}

# TypeScript interface -> model. Inline object types map to their own models.
MODELS: dict[str, type[BaseModel]] = {
    "Repo": m.Repo,
    "StageProgress": m.StageProgress,
    "Entity": m.Entity,
    "EntityMatch": m.EntityMatch,
    "ExplorerItem": m.ExplorerItem,
    "Explorer": m.Explorer,
    "SourceRef": m.SourceRef,
    "Person": m.Person,
    "Decision": m.Decision,
    "SupersededNote": m.SupersededNote,
    "EvidenceStep": m.EvidenceStep,
    "ConfidenceFactor": m.ConfidenceFactor,
    "GraphNode": m.GraphNode,
    "GraphEdge": m.GraphEdge,
    "Fact": m.Fact,
    "RelatedItem": m.RelatedItem,
    "AnswerThresholds": m.AnswerThresholds,
    "AnsweredAnswer": m.AnsweredAnswer,
    "HedgedAnswer": m.HedgedAnswer,
    "RefusedAnswer": m.RefusedAnswer,
    "Hotspot": m.Hotspot,
    "ExampleQuestion": m.ExampleQuestion,
    "ShowcaseItem": m.ShowcaseItem,
    "Overview": m.Overview,
    "LineageDecision": m.LineageDecision,
    "LineageCommit": m.LineageCommit,
    "Lineage": m.Lineage,
    "Gap": m.Gap,
    "EvalRow": m.EvalRow,
    "EvaluationSummary": m.EvaluationSummary,
    "Health": m.Health,
}
INLINE = {
    ("Overview", "counts"): m.OverviewCounts,
    ("Health", "counts"): m.HealthCounts,
    ("AnsweredAnswer", "graph"): m.AnswerGraph,
}

_HEAD = re.compile(r"^(?:export )?interface (\w+)(?: extends ([^{]+))? \{$")
_FIELD = re.compile(r"^  (\w+)\??:")
_INNER = re.compile(r"^    (\w+)\??:")


def parse_interfaces(text: str) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    own: dict[str, set[str]] = {}
    parents: dict[str, str] = {}
    inline: dict[tuple[str, str], set[str]] = {}
    current, field = None, None
    for line in text.splitlines():
        if head := _HEAD.match(line):
            current = head.group(1)
            own[current] = set()
            if head.group(2):
                parents[current] = head.group(2).strip()
        elif current and line == "}":
            current = None
        elif current and (f := _FIELD.match(line)):
            field = f.group(1)
            own[current].add(field)
            # `graph: { nodes: GraphNode[]; edges: GraphEdge[] }` on one line
            if one_line := re.search(r":\s*\{(.+)\}", line):
                names = re.findall(r"(\w+)\??:", one_line.group(1))
                inline[(current, field)] = set(names)
        elif current and field and (f := _INNER.match(line)):
            inline.setdefault((current, field), set()).add(f.group(1))

    def all_fields(name: str) -> set[str]:
        parent = parents.get(name, "")
        if omit := re.match(r"Omit<(\w+), '(\w+)'>", parent):
            return (all_fields(omit.group(1)) - {omit.group(2)}) | own[name]
        return (all_fields(parent) if parent else set()) | own[name]

    return {name: all_fields(name) for name in own}, inline


def model_fields(model: type[BaseModel]) -> set[str]:
    return {f.serialization_alias or name for name, f in model.model_fields.items()}


@pytest.fixture(scope="module")
def contract():
    return parse_interfaces(TYPES_TS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_has_exactly_the_contract_fields(contract, name):
    interfaces, _ = contract
    assert model_fields(MODELS[name]) == interfaces[name] | ADDED.get(name, set())


@pytest.mark.parametrize("key", sorted(INLINE))
def test_inline_objects_match(contract, key):
    _, inline = contract
    assert model_fields(INLINE[key]) == inline[key]


def test_graph_edge_serialises_from_not_from_():
    assert m.GraphEdge(from_="a", to="b", label="AFFECTS").model_dump(by_alias=True) == {
        "from": "a",
        "to": "b",
        "label": "AFFECTS",
    }


def test_answer_union_picks_the_model_by_verdict():
    base = {
        "question": "q",
        "entity": None,
        "matched_by": "search",
        "match_score": None,
        "confidence": 0.1,
        "thresholds": {"answer": 0.7, "refuse": 0.4},
        "partial_history": True,
        "who_to_ask": [],
        "confidence_factors": [],
    }
    refused = {
        **base,
        "verdict": "refused",
        "reason": "r",
        "known_facts": [],
        "related": [],
        "history_url": "u",
    }
    parsed = TypeAdapter(m.Answer).validate_python(refused)
    assert isinstance(parsed, m.RefusedAnswer)


def test_dates_serialise_as_iso_strings():
    d = m.LineageCommit(
        sha="abc", message="m", date=datetime(2021, 7, 6, tzinfo=UTC), url="u", decision_id=None
    )
    assert d.model_dump(mode="json")["date"] == "2021-07-06T00:00:00Z"
    lineage_as_of = m.Lineage.model_fields["as_of"]
    assert TypeAdapter(lineage_as_of.annotation).dump_python(date(2016, 12, 31), mode="json") == (
        "2016-12-31"
    )
