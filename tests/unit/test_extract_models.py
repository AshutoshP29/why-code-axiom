import json

import pytest
from pydantic import ValidationError

from whycode.extract.models import EvidenceKind, ExtractionResponse

GOOD = {
    "summary": "Replace chardet with charset_normalizer",
    "rationale": "chardet is LGPL and cannot be bundled in an MIT library.",
    "alternatives": ["Keep chardet as an optional extra"],
    "decided_at": "2021-07-13",
    "affects": [{"kind": "file", "path": "requests/compat.py"}],
    "evidence": [{"source_id": "pr:5797:ic:1", "exact_quote": "cannot ship an LGPL dependency"}],
    "evidence_kind": "EXPLICIT",
    "confidence": 0.9,
}


def parse(decision):
    return ExtractionResponse.model_validate_json(json.dumps({"decisions": [decision]}))


def without(field):
    return {k: v for k, v in GOOD.items() if k != field}


def test_good_decision_parses():
    d = parse(GOOD).decisions[0]
    assert d.evidence_kind is EvidenceKind.EXPLICIT and str(d.decided_at) == "2021-07-13"


def test_empty_decision_list_is_valid():
    assert ExtractionResponse.model_validate_json('{"decisions": []}').decisions == []


@pytest.mark.parametrize(
    "field", ["summary", "rationale", "decided_at", "evidence", "evidence_kind", "confidence"]
)
def test_missing_required_field_rejected(field):
    with pytest.raises(ValidationError):
        parse(without(field))


@pytest.mark.parametrize(
    "patch",
    [
        {"evidence_kind": "PROBABLY"},  # wrong enum
        {"evidence_kind": "explicit"},  # enum is case-sensitive
        {"evidence": []},  # zero evidence
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"decided_at": "last summer"},
        {"summary": "short"},
        {"evidence": [{"source_id": "", "exact_quote": "a long enough quote"}]},
        {"evidence": [{"source_id": "x", "exact_quote": "tiny"}]},
        {"affects": [{"kind": "module", "path": "a.py"}]},
        {"surprise": "extra fields are not allowed"},
    ],
)
def test_malformed_decision_rejected(patch):
    with pytest.raises(ValidationError):
        parse({**GOOD, **patch})


@pytest.mark.parametrize("text", ["not json", '{"decisions": "none"}', "[]", '{"decision": []}'])
def test_malformed_response_rejected(text):
    with pytest.raises(ValidationError):
        ExtractionResponse.model_validate_json(text)
