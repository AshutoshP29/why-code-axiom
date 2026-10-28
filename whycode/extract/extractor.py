"""Run extraction over a Thread: chunk, call the LLM, validate, check quotes, merge.

A decision is kept only if the JSON validates and EVERY evidence quote is found verbatim (under
the whitespace rule in quotes.py) in the source it names, and that source was in the chunk the
model saw. Anything else is rejected and reported with a reason; nothing is repaired.
"""

import logging
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from whycode.extract.models import EvidenceKind, ExtractedDecision, ExtractionResponse
from whycode.extract.prompt import PROMPT_VERSION, SYSTEM, build_user_prompt
from whycode.extract.quotes import Span, find_quote, normalize
from whycode.extract.sources import Source, Thread
from whycode.llm.client import LLMClient, LLMError

log = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 16_000  # per chunk of sources; roughly 4k tokens
MERGE_SIMILARITY = 0.5
ALTERNATIVE_SIMILARITY = 0.6  # two alternatives this alike in words are the same option


@dataclass(frozen=True)
class VerifiedEvidence:
    source: Source
    quote: str
    span: Span


@dataclass
class Decision:
    """A validated decision whose every quote was found in its source."""

    data: ExtractedDecision
    evidence: list[VerifiedEvidence]
    model: str
    chunks: list[int] = field(default_factory=list)


@dataclass
class Rejection:
    chunk: int
    summary: str
    reason: str


@dataclass
class ChunkPlan:
    index: int
    sources: list[Source]
    chars: int
    cached: bool = False
    label: str = ""  # "7", or "7.1"/"7.2" when part 7 had to be split


@dataclass
class ExtractionResult:
    decisions: list[Decision]
    rejections: list[Rejection]
    chunks: list[ChunkPlan]
    failed_chunks: list[tuple[int, str]]
    dry_run: bool = False
    stopped_early: str | None = None  # why later chunks were not attempted


def chunk_sources(thread: Thread, max_chars: int = DEFAULT_MAX_CHARS) -> list[list[Source]]:
    """Split sources at source boundaries. The PR body is repeated in every chunk as context.

    A single source longer than max_chars gets a chunk of its own; it is never cut.
    """
    body = [s for s in thread.sources if s.source_type == "pr_body"]
    rest = [s for s in thread.sources if s.source_type != "pr_body"]
    base = sum(len(s.text) for s in body)
    chunks: list[list[Source]] = []
    current: list[Source] = []
    size = base
    for s in rest:
        if current and size + len(s.text) > max_chars:
            chunks.append(body + current)
            current, size = [], base
        current.append(s)
        size += len(s.text)
    if current or not chunks:
        chunks.append(body + current)
    return chunks


def describe_validation_error(exc: ValidationError, limit: int = 5) -> str:
    """Field paths and error types only, e.g. "decisions.0.decided_at: date_parsing"."""
    parts = [
        f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['type']}"
        for e in exc.errors()[:limit]
    ]
    more = exc.error_count() - limit
    return "; ".join(parts) + (f"; +{more} more" if more > 0 else "")


def _split(sources: list[Source]) -> tuple[list[Source], list[Source]] | None:
    """Halve a chunk by characters at a source boundary; the PR body goes in both."""
    body = [s for s in sources if s.source_type == "pr_body"]
    rest = [s for s in sources if s.source_type != "pr_body"]
    if len(rest) < 2:
        return None
    half, size, cut = sum(len(s.text) for s in rest) / 2, 0, 1
    for k, s in enumerate(rest[:-1], start=1):
        size += len(s.text)
        cut = k
        if size >= half:
            break
    return body + rest[:cut], body + rest[cut:]


def _cached_halves(llm, thread, sources, label, parts, user, code_outline=None):
    """If this part is not cached but its split halves are, return them for the queue."""
    if llm.is_cached(SYSTEM, user, prompt_version=PROMPT_VERSION):
        return None
    halves = _split(sources)
    if not halves:
        return None
    labelled = [(f"{label}.1", halves[0]), (f"{label}.2", halves[1])]
    for sub_label, sub in labelled:
        sub_user = build_user_prompt(thread, sub, sub_label, parts, code_outline)
        if not llm.is_cached(SYSTEM, sub_user, prompt_version=PROMPT_VERSION) and not (
            _split(sub)
            and _cached_halves(llm, thread, sub, sub_label, parts, sub_user, code_outline)
        ):
            return None
    index = int(label.split(".")[0])
    return [(sub_label, index, sub) for sub_label, sub in labelled]


def _verify(d: ExtractedDecision, by_id: dict[str, Source]) -> list[VerifiedEvidence] | str:
    verified = []
    for ev in d.evidence:
        src = by_id.get(ev.source_id)
        if src is None:
            return f"unknown source_id {ev.source_id!r}"
        span = find_quote(ev.exact_quote, src.text)
        if span is None:
            return f"quote not found verbatim in {ev.source_id}"
        verified.append(VerifiedEvidence(src, ev.exact_quote, span))
    return verified


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _similar(a: Decision, b: Decision) -> bool:
    qa = {(e.source.source_id, normalize(e.quote)) for e in a.evidence}
    qb = {(e.source.source_id, normalize(e.quote)) for e in b.evidence}
    if qa & qb:
        return True
    wa, wb = _words(a.data.summary), _words(b.data.summary)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= MERGE_SIMILARITY


def dedupe_alternatives(alternatives: list[str]) -> list[str]:
    """Drop alternatives that reword one already kept ("Keep chardet as default" and "Keep
    chardet as the default detector"), keeping the first wording seen."""
    kept: list[str] = []
    kept_words: list[set[str]] = []
    for alt in alternatives:
        words = _words(alt)
        if not words:
            continue
        if any(len(words & w) / len(words | w) >= ALTERNATIVE_SIMILARITY for w in kept_words):
            continue
        kept.append(alt)
        kept_words.append(words)
    return kept


def _merge_into(base: Decision, other: Decision) -> None:
    seen = {(e.source.source_id, e.span) for e in base.evidence}
    for e in other.evidence:
        if (e.source.source_id, e.span) not in seen:
            base.evidence.append(e)
            seen.add((e.source.source_id, e.span))
    d = base.data
    alts = [*d.alternatives, *other.data.alternatives]
    affects = list(
        {(a.kind, a.path, a.name): a for a in [*d.affects, *other.data.affects]}.values()
    )
    kind = (
        EvidenceKind.EXPLICIT
        if EvidenceKind.EXPLICIT in (d.evidence_kind, other.data.evidence_kind)
        else EvidenceKind.INFERRED
    )
    base.data = d.model_copy(
        update={
            "alternatives": alts,
            "affects": affects,
            "evidence_kind": kind,
            "confidence": max(d.confidence, other.data.confidence),
        }
    )
    base.chunks = sorted(set(base.chunks + other.chunks))


def merge_decisions(decisions: list[Decision]) -> list[Decision]:
    """Fold together decisions that share a quote or have near-identical summaries.

    Similarity is checked between every pair of the original decisions and grouped transitively
    (A~B and B~C puts all three together), so the result does not depend on processing order.
    Each group keeps the most confident decision as its base.
    """
    parent = list(range(len(decisions)))

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(decisions)):
        for b in range(a + 1, len(decisions)):
            if _similar(decisions[a], decisions[b]):
                parent[root(a)] = root(b)

    groups: dict[int, list[Decision]] = {}
    for k, d in enumerate(decisions):
        groups.setdefault(root(k), []).append(d)
    merged = []
    for group in groups.values():
        group.sort(key=lambda x: -x.data.confidence)
        for other in group[1:]:
            _merge_into(group[0], other)
        merged.append(group[0])
    for d in merged:
        alternatives = dedupe_alternatives(d.data.alternatives)
        d.data = d.data.model_copy(update={"alternatives": alternatives})
    return sorted(merged, key=lambda x: (x.data.decided_at, x.data.summary))


def extract_thread(
    thread: Thread,
    llm: LLMClient,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    dry_run: bool = False,
    code_outline: str | None = None,
) -> ExtractionResult:
    chunks = chunk_sources(thread, max_chars)
    plans, raw, rejections, failed = [], [], [], []
    # Unsplit parts are labelled "1".."n" so their prompts (and cache keys) never change.
    queue = [(str(i), i, sources) for i, sources in enumerate(chunks, start=1)]
    while queue:
        label, i, sources = queue.pop(0)
        user = build_user_prompt(thread, sources, label, len(chunks), code_outline)
        halves = _cached_halves(llm, thread, sources, label, len(chunks), user, code_outline)
        if halves:  # this part was split on an earlier run; replay its halves from the cache
            queue[0:0] = halves
            continue
        try:
            result = llm.complete_json(
                SYSTEM, user, prompt_version=PROMPT_VERSION, repo=thread.repo, dry_run=dry_run
            )
        except LLMError as exc:
            halves = _split(sources) if "too_large" in exc.reasons else None
            if halves:
                log.warning("part %s is too large for the provider; splitting it", label)
                queue[0:0] = [(f"{label}.1", i, halves[0]), (f"{label}.2", i, halves[1])]
                continue
            # Providers down or budget spent: keep what we have, spend nothing more.
            failed.append((i, f"LLM unavailable: {exc}"))
            stopped = f"stopped at part {label} of {len(chunks)}: {type(exc).__name__}"
            log.warning("%s", stopped)
            return ExtractionResult(
                merge_decisions(raw), rejections, plans, failed, dry_run, stopped
            )
        plans.append(ChunkPlan(i, sources, len(SYSTEM) + len(user), result.cached, label))
        if result.text is None:  # dry run without a cached answer
            continue
        try:
            parsed = ExtractionResponse.model_validate_json(result.text)
        except ValidationError as exc:
            why = describe_validation_error(exc)
            failed.append((i, f"invalid ExtractionResponse: {why}"))
            log.warning("chunk %d: response failed validation: %s", i, why)
            continue
        by_id = {s.source_id: s for s in sources}
        for d in parsed.decisions:
            verified = _verify(d, by_id)
            if isinstance(verified, str):
                rejections.append(Rejection(i, d.summary, verified))
                log.info("chunk %d: rejected %r: %s", i, d.summary, verified)
            else:
                raw.append(Decision(d, verified, result.model, [i]))
    return ExtractionResult(merge_decisions(raw), rejections, plans, failed, dry_run)
