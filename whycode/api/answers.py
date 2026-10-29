"""POST /api/ask: find the entity, run query 5a, score it, and shape the contract's Answer.

Everything comes from the graph. answer_text is a fixed sentence pattern over the decision's own
summary, rationale, date and source until an LLM words it; refusal reasons are fixed texts or the
query's own, never generated. Nothing here guesses why code is the way it is.
"""

from whycode.api import models as m
from whycode.api import reads
from whycode.api.confidence import THRESHOLDS, Signals, factors, score, verdict, warning
from whycode.graph.queries import Answer as GraphAnswer
from whycode.graph.queries import DecisionView, EvidenceRef, PersonRef, Run, current_decisions
from whycode.graph.queries import Fact as GraphFact
from whycode.ids import make_id

ASK_SEARCH_LIMIT = 5
# Below this, a search hit is too weak to say the question is about that item: the other four
# factors alone reach 0.75, so without this floor any hit on a decided item would be answered.
MIN_SEARCH_MATCH = 0.5
NO_MATCH_REASON = (
    "No file, class, function or config key in the graph matches this question, so WhyCode "
    "cannot tell which code it is about and will not guess. Pick an item and ask again."
)
MODULE_REASON = (
    "Decisions are recorded on files, classes, functions and config keys, not on modules. "
    "Pick one of the files in this module and ask again."
)
WEAK_MATCH_REASON = (
    "Nothing in the graph clearly matches this question; the closest items below match it only "
    "weakly, so WhyCode will not assume which code it is about. Pick an item and ask again."
)
LOW_CONFIDENCE_REASON = (
    "The graph has a decision for this, but the evidence behind it is too weak to answer. "
    "The people below can confirm it."
)

Q_DECISION_CONTEXT = """// q:decision_context
MATCH (d:Decision {id: $id, repo: $repo})
OPTIONAL MATCH (d)-[:AFFECTS]->(e {repo: $repo})
WITH d, collect(DISTINCT e) AS affects
OPTIONAL MATCH (d)-[s:SUPERSEDES]->(o:Decision {repo: $repo})
OPTIONAL MATCH (o)-[:DECIDED_IN]->(src {repo: $repo})
RETURN affects, collect(DISTINCT {decision: o, kind: s.kind, source: src}) AS supersedes
"""

_STEP_KIND: dict[str, m.EvidenceKind] = {
    "pr_body": "discussion",
    "pr_comment": "discussion",
    "review_comment": "discussion",
    "pr_review": "discussion",
    "issue_body": "issue",
    "issue_comment": "issue",
    "commit_msg": "commit",
    "doc": "code",
}
_STEP_WHAT = {
    "pr_body": "description",
    "pr_comment": "comment",
    "review_comment": "review comment",
    "pr_review": "review",
    "issue_body": "issue description",
    "issue_comment": "issue comment",
    "commit_msg": "commit message",
    "doc": "documentation",
}


def github(repo: str) -> str:
    return f"https://github.com/{repo}"


def history_url(repo: str, path: str | None) -> str:
    """GitHub's commit history of a file; HEAD is the default branch, whatever it is called."""
    return f"{github(repo)}/commits/HEAD/{path}" if path else f"{github(repo)}/commits/HEAD"


def _base(question, entity, matched_by, match_score, fs, repo: m.Repo, people) -> dict:
    return {
        "question": question,
        "entity": entity,
        "matched_by": matched_by,
        "match_score": match_score,
        "confidence": score(fs),
        "thresholds": THRESHOLDS,
        "partial_history": repo.partial,
        "who_to_ask": people,
        "confidence_factors": fs,
    }


def _person(p: PersonRef, role: str) -> m.Person:
    return m.Person(
        login=p.login,
        role=role,
        active=bool(p.active),
        last_seen=p.last_seen,
        url=f"https://github.com/{p.login}",
    )


def _source_kind(source_id: str) -> m.GraphNodeKind:
    if "#issue:" in source_id:
        return "issue"
    if "#commit:" in source_id:
        return "commit"
    return "pull_request"


def _evidence_label(evidence_id: str) -> str:
    """ "psf/requests#ev:pr:5797:ic:1" -> "PR #5797"; commit evidence -> "Commit 0123456"."""
    key = evidence_id.split("#ev:", 1)[-1].split(":")
    if len(key) >= 2 and key[0] == "pr":
        return f"PR #{key[1]}"
    if len(key) >= 2 and key[0] == "issue":
        return f"Issue #{key[1]}"
    if len(key) >= 2 and key[0] == "commit":
        return f"Commit {key[1][:7]}"
    return "Source"


def _decision(dv: DecisionView, repo: str) -> m.Decision:
    src = dv.decided_in[0] if dv.decided_in else None
    approvers = list(dict.fromkeys(p.login for p in dv.approved_by))
    return m.Decision(
        id=dv.id,
        summary=dv.summary,
        rationale=dv.rationale,
        alternatives=dv.alternatives,
        decided_at=dv.decided_at.date(),
        status=dv.status if dv.status in ("ACTIVE", "SUPERSEDED", "PARTIAL") else "ACTIVE",
        evidence_kind="EXPLICIT" if dv.evidence_kind == "EXPLICIT" else "INFERRED",
        proposed_by=dv.proposed_by[0].login if dv.proposed_by else None,
        reviewed_by=approvers[0] if approvers else None,
        approved_by=approvers,
        source=m.SourceRef(id=src.id, label=src.label, url=src.url or github(repo))
        if src
        else m.SourceRef(id=dv.id, label="Decision", url=github(repo)),
    )


def _step(ev: EvidenceRef, fallback_url: str) -> m.EvidenceStep:
    label = _evidence_label(ev.id)
    what = _STEP_WHAT.get(ev.source_type, "source")
    by = f" by @{ev.author}" if ev.author and ev.source_type != "pr_body" else ""
    meta = [ev.date.date().isoformat()] if ev.date else []
    if ev.author:
        meta.append(f"@{ev.author}")
    return m.EvidenceStep(
        kind=_STEP_KIND.get(ev.source_type, "discussion"),
        title=f"{label}: {what}{by}",
        excerpt=ev.quote,
        meta=meta,
        source=m.SourceRef(id=ev.id, label=label, url=ev.url or fallback_url),
    )


def answer_text(d: m.Decision) -> str:
    """The decision in its own words: summary, rationale, when and where. No added claims."""
    text = f"{d.summary.strip().rstrip('.')}. {d.rationale.strip()}"
    if not text.endswith((".", "!", "?")):
        text += "."
    where = f" in {d.source.label}" if d.source.label != "Decision" else ""
    return f"{text} Decided on {d.decided_at.isoformat()}{where}."


def _people(dv: DecisionView) -> list[m.Person]:
    people: dict[str, m.Person] = {}
    for p in dv.proposed_by:
        people.setdefault(p.login, _person(p, "Proposed the decision"))
    for p in dv.approved_by:
        people.setdefault(p.login, _person(p, "Approved it"))
    return list(people.values())


def _context(run: Run, repo: str, decision_id: str) -> tuple[list[dict], list[dict]]:
    rows = run(Q_DECISION_CONTEXT, {"repo": repo, "id": decision_id})
    if not rows:
        return [], []
    seen, supersedes = set(), []
    for s in rows[0]["supersedes"]:
        o = s.get("decision")
        if o and o["id"] not in seen and s.get("kind"):
            seen.add(o["id"])
            supersedes.append(s)
    return [e for e in rows[0]["affects"] if e], supersedes


def _older(s: dict, repo: str, superseded_at) -> m.SupersededNote:
    o, src = s["decision"], s.get("source")
    source = (
        m.SourceRef(
            id=src["id"],
            label=f"PR #{src['number']}" if "#pr:" in src["id"] else src["id"].split("#", 1)[-1],
            url=src.get("url") or github(repo),
        )
        if src
        else m.SourceRef(id=o["id"], label="Decision", url=github(repo))
    )
    return m.SupersededNote(
        decision=m.Decision(
            id=o["id"],
            summary=o.get("summary", ""),
            rationale=o.get("rationale", ""),
            alternatives=list(o.get("alternatives") or []),
            decided_at=reads.native(o["decided_at"]).date(),
            status=o.get("status") if o.get("status") in ("ACTIVE", "PARTIAL") else "SUPERSEDED",
            evidence_kind="EXPLICIT" if o.get("evidence_kind") == "EXPLICIT" else "INFERRED",
            proposed_by=None,
            reviewed_by=None,
            source=source,
        ),
        kind=s["kind"],
        superseded_at=superseded_at,
    )


def _graph(dv, decision, entity, affects, supersedes, people, repo) -> m.AnswerGraph:
    nodes = [
        m.GraphNode(
            id=dv.id, kind="decision", label=dv.summary, center=True, url=decision.source.url
        )
    ]
    edges = []
    affected = [reads.entity(e) for e in affects]
    if entity.id not in {e.id for e in affected}:
        affected.insert(0, entity)
    for e in affected:
        nodes.append(m.GraphNode(id=e.id, kind="entity", label=e.qualified_name, entity_id=e.id))
        edges.append(m.GraphEdge(from_=dv.id, to=e.id, label="AFFECTS"))
    for s in dv.decided_in:
        nodes.append(m.GraphNode(id=s.id, kind=_source_kind(s.id), label=s.label, url=s.url))
        edges.append(m.GraphEdge(from_=dv.id, to=s.id, label="DECIDED_IN"))
    for p in people:
        pid = make_id(repo, "user", p.login)
        nodes.append(m.GraphNode(id=pid, kind="person", label=p.login, url=p.url))
        rel = "PROPOSED_BY" if p.role == "Proposed the decision" else "APPROVED_BY"
        edges.append(m.GraphEdge(from_=dv.id, to=pid, label=rel))
    for s in supersedes:
        o = s["decision"]
        nodes.append(
            m.GraphNode(id=o["id"], kind="decision", label=o.get("summary", ""), dimmed=True)
        )
        edges.append(m.GraphEdge(from_=dv.id, to=o["id"], label="SUPERSEDES"))
    return m.AnswerGraph(nodes=nodes, edges=edges)


def _refused(base: dict, reason: str, facts: list[m.Fact], url: str) -> m.RefusedAnswer:
    return m.RefusedAnswer(**base, reason=reason, known_facts=facts, related=[], history_url=url)


def _related(hit: m.EntityMatch, repo: str) -> m.RelatedItem:
    return m.RelatedItem(
        title=hit.qualified_name,
        match_score=hit.score,
        source=m.SourceRef(id=hit.id, label=hit.kind, url=history_url(repo, hit.path)),
    )


def _independent_sources(dv: DecisionView) -> int:
    """People quoted in the evidence: two comments by the same person are one source."""
    return len({ev.author or ev.id for ev in dv.evidence})


def _fact(f: GraphFact, entity_id: str, url: str) -> m.Fact:
    return m.Fact(
        title=f.title,
        detail=f.detail,
        meta=[f.date.date().isoformat()] if f.date else [],
        source=m.SourceRef(id=f.url or entity_id, label=f.title.split(":", 1)[0], url=f.url or url),
    )


def ask(run: Run, repo: m.Repo, question: str, selected: m.Entity | None) -> m.Answer:
    if selected is not None:
        entity, matched_by, match, match_score = selected, "selected", 1.0, None
    else:
        hits = [
            h for h in reads.search(run, repo.id, question, ASK_SEARCH_LIMIT) if h.kind != "module"
        ]
        if not hits:
            fs = factors(Signals(None, None))
            base = _base(question, None, "search", None, fs, repo, [])
            return _refused(base, NO_MATCH_REASON, [], history_url(repo.id, None))
        top = hits[0]
        if top.score < MIN_SEARCH_MATCH:
            fs = factors(Signals(top.score, None))
            base = _base(question, None, "search", top.score, fs, repo, [])
            refused = _refused(base, WEAK_MATCH_REASON, [], history_url(repo.id, None))
            refused.related = [_related(h, repo.id) for h in hits]
            return refused
        entity = m.Entity(**top.model_dump(exclude={"score"}))
        matched_by, match, match_score = "search", top.score, top.score

    url = history_url(repo.id, entity.path)
    if entity.kind == "module":
        fs = factors(Signals(match, None))
        base = _base(question, entity, matched_by, match_score, fs, repo, [])
        return _refused(base, MODULE_REASON, [], url)

    result = current_decisions(run, repo.id, entity.id)
    if not isinstance(result, GraphAnswer):
        fs = factors(Signals(match, None))
        people = [_person(result.last_owner, "Last changed it")] if result.last_owner else []
        base = _base(question, entity, matched_by, match_score, fs, repo, people)
        facts = [_fact(f, entity.id, url) for f in result.known_facts]
        return _refused(base, result.reason, facts, url)

    dv = result.decisions[0]  # newest first: the current governing decision
    affects, supersedes = _context(run, repo.id, dv.id)
    if dv.status == "PARTIAL":
        supersession = "pending"
    elif supersedes:
        supersession = "resolved"
    else:
        supersession = "none"
    fs = factors(
        Signals(
            entity_match=match,
            evidence_kind=dv.evidence_kind,
            source_count=_independent_sources(dv),
            supersession=supersession,
            citations_verified=all(ev.quote.strip() for ev in dv.evidence),
        )
    )
    people = _people(dv)
    base = _base(question, entity, matched_by, match_score, fs, repo, people)
    outcome = verdict(base["confidence"])
    if outcome == "refused":
        return _refused(base, LOW_CONFIDENCE_REASON, [], url)

    decision = _decision(dv, repo.id)
    full = {
        **base,
        "entity": entity,
        "answer_text": answer_text(decision),
        "decision": decision,
        "superseded": [_older(s, repo.id, decision.decided_at) for s in supersedes],
        "evidence_chain": [_step(ev, decision.source.url) for ev in dv.evidence],
        "graph": _graph(dv, decision, entity, affects, supersedes, people, repo.id),
    }
    if outcome == "hedged":
        return m.HedgedAnswer(**full, warning=warning(fs))
    return m.AnsweredAnswer(**full)
