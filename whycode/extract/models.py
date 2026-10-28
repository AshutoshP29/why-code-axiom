"""What the LLM must return. Anything that does not validate is rejected, never repaired."""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceKind(StrEnum):
    EXPLICIT = "EXPLICIT"  # the rationale is stated in the text
    INFERRED = "INFERRED"  # reconstructed from what was done, not stated


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceQuote(_Strict):
    source_id: str = Field(min_length=1)
    exact_quote: str = Field(min_length=8, max_length=1000)


class Affected(_Strict):
    kind: Literal["file", "class", "function", "config"]
    path: str = Field(min_length=1)  # file path as it appears in the PR
    name: str | None = None  # qualified class/function name or config key; None for files


class ExtractedDecision(_Strict):
    summary: str = Field(min_length=10, max_length=300)
    rationale: str = Field(min_length=10, max_length=2000)
    alternatives: list[str] = Field(default_factory=list)
    decided_at: date
    affects: list[Affected] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(min_length=1)
    evidence_kind: EvidenceKind
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionResponse(_Strict):
    decisions: list[ExtractedDecision]
