"""Answer confidence: five weighted factors, then the verdict from the thresholds.

Weights: entity match 0.25, evidence directness 0.25 (EXPLICIT > INFERRED), independent sources
0.20, supersession resolved 0.15, citation pass 0.15. Supersession and citation only count when
there is a decision to cite, so a refusal can never score its way into an answer.
"""

from dataclasses import dataclass
from typing import Literal

from whycode.api.models import AnswerThresholds, ConfidenceFactor

THRESHOLDS = AnswerThresholds(answer=0.70, refuse=0.40)
WEIGHTS = {
    "Entity match": 0.25,
    "Evidence directness": 0.25,
    "Independent sources": 0.20,
    "Supersession resolved": 0.15,
    "Citation pass": 0.15,
}
SOURCES_NEEDED = 2
_GOOD_FROM = 0.70

Supersession = Literal["none", "resolved", "pending"]
Verdict = Literal["answered", "hedged", "refused"]


@dataclass(frozen=True)
class Signals:
    entity_match: float | None  # 0..1; None when nothing matched the question
    evidence_kind: str | None  # EXPLICIT | INFERRED; None when there is no decision
    source_count: int = 0  # distinct evidence sources behind the decision
    supersession: Supersession = "none"  # resolved: it replaced older ones; pending: refined
    citations_verified: bool = False  # every quote is a verified span of its source


def _tone(value: float) -> Literal["good", "bad"]:
    return "good" if value >= _GOOD_FROM else "bad"


def factors(s: Signals) -> list[ConfidenceFactor]:
    has_decision = s.evidence_kind is not None
    out = []
    if s.entity_match is None:
        out.append(ConfidenceFactor(label="Entity match", value=0, display="No match", tone="bad"))
    else:
        v = max(0.0, min(1.0, s.entity_match))
        out.append(
            ConfidenceFactor(label="Entity match", value=v, display=f"{v:.0%}", tone=_tone(v))
        )

    if s.evidence_kind == "EXPLICIT":
        out.append(
            ConfidenceFactor(label="Evidence directness", value=1, display="Stated", tone="good")
        )
    elif s.evidence_kind == "INFERRED":
        out.append(
            ConfidenceFactor(label="Evidence directness", value=0.5, display="Inferred", tone="bad")
        )
    else:
        out.append(
            ConfidenceFactor(
                label="Evidence directness", value=0, display="No decision", tone="bad"
            )
        )

    n = s.source_count if has_decision else 0
    v = min(1.0, n / SOURCES_NEEDED)
    display = f"{n} sources" if n >= SOURCES_NEEDED else f"{n} of {SOURCES_NEEDED} needed"
    out.append(
        ConfidenceFactor(label="Independent sources", value=v, display=display, tone=_tone(v))
    )

    if not has_decision:
        out.append(
            ConfidenceFactor(
                label="Supersession resolved", value=0, display="Not applicable", tone="neutral"
            )
        )
        out.append(
            ConfidenceFactor(label="Citation pass", value=0, display="No quotes", tone="neutral")
        )
        return out

    if s.supersession == "pending":
        sup = ConfidenceFactor(
            label="Supersession resolved", value=0.5, display="Refined, not settled", tone="bad"
        )
    elif s.supersession == "resolved":
        sup = ConfidenceFactor(label="Supersession resolved", value=1, display="Yes", tone="good")
    else:
        sup = ConfidenceFactor(
            label="Supersession resolved", value=1, display="Not applicable", tone="neutral"
        )
    out.append(sup)
    if s.citations_verified:
        out.append(ConfidenceFactor(label="Citation pass", value=1, display="Yes", tone="good"))
    else:
        out.append(ConfidenceFactor(label="Citation pass", value=0, display="No", tone="bad"))
    return out


def score(fs: list[ConfidenceFactor]) -> float:
    return round(sum(WEIGHTS[f.label] * f.value for f in fs), 2)


def verdict(confidence: float, thresholds: AnswerThresholds = THRESHOLDS) -> Verdict:
    if confidence >= thresholds.answer:
        return "answered"
    if confidence >= thresholds.refuse:
        return "hedged"
    return "refused"


def warning(fs: list[ConfidenceFactor]) -> str:
    """Why confidence is limited, from the weak factors only. Never a guess about the code."""
    weak = [f"{f.label.lower()} ({f.display})" for f in fs if f.tone == "bad"]
    if not weak:
        return "Confidence is below the answer threshold. Confirm this with the people listed."
    return (
        "Confidence is limited by " + ", ".join(weak) + ". Treat this as a lead and confirm it "
        "with the people listed."
    )
