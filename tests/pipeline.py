"""The fixture PR run through fetch, code index, extraction (fake LLM) and the affects check.

Shared by the graph builder unit tests and the Neo4j integration tests. `repo` lets a test load
the same PR under another repo name, to prove two repos never mix.
"""

import json
from dataclasses import dataclass

from tests.fakes import (
    FakeGitHub,
    FakeProvider,
    MemoryLLMCache,
    MemoryRawStore,
    load_github_fixture,
)
from whycode.code.affects import AffectsCheck, resolve_affects
from whycode.code.index import PrCodeIndex, build_pr_code_index
from whycode.extract.extractor import ExtractionResult, extract_thread
from whycode.extract.prompt import render_code_outline
from whycode.extract.sources import Thread, load_thread
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubClient
from whycode.llm.client import Budget, LLMClient

LGPL = "We cannot ship an LGPL dependency inside an MIT library."
SWITCH = "Y is close enough in accuracy; let's switch."
FALLBACK = "Keep the old import as a fallback for one release."

SWITCH_DECISION = {
    "summary": "Switch the X parser for Y",
    "rationale": "X is LGPL and the library is MIT licensed.",
    "alternatives": ["Keep X"],
    "decided_at": "2021-06-21",
    "affects": [
        {"kind": "function", "path": "src/fixture/compat.py", "name": "Detector.detect"},
        {"kind": "config", "path": "src/fixture/compat.py", "name": "MAX_BYTES"},
        {"kind": "file", "path": "setup.py"},  # not changed by the PR: dropped by the check
    ],
    "evidence": [
        {"source_id": "pr:1565:ic:9001", "exact_quote": LGPL},
        {"source_id": "pr:1565:ic:9002", "exact_quote": SWITCH},
    ],
    "evidence_kind": "EXPLICIT",
    "confidence": 0.9,
}
FALLBACK_DECISION = {
    "summary": "Keep the old import path as a fallback for one release",
    "rationale": "Existing users keep working while they migrate.",
    "alternatives": [],
    "decided_at": "2021-06-22",
    "affects": [{"kind": "file", "path": "fixture/compat.py"}],
    "evidence": [{"source_id": "pr:1565:rc:7001", "exact_quote": FALLBACK}],
    "evidence_kind": "EXPLICIT",
    "confidence": 0.8,
}


@dataclass
class Pipeline:
    store: MemoryRawStore
    thread: Thread
    index: PrCodeIndex
    result: ExtractionResult
    checks: list[AffectsCheck]


def run_fixture(repo: str = "test/fixture", decisions=(SWITCH_DECISION, FALLBACK_DECISION)):
    routes = load_github_fixture("pr_1565.json")
    if repo != "test/fixture":
        routes = {
            k.replace("/repos/test/fixture/", f"/repos/{repo}/"): v for k, v in routes.items()
        }
    store = MemoryRawStore()
    with GitHubClient("t", transport=FakeGitHub(routes).transport()) as gh:
        fetch_pr(gh, store, repo, 1565)
    thread = load_thread(store, repo, 1565)
    index = build_pr_code_index(store, repo, 1565)
    reply = json.dumps({"decisions": list(decisions)})
    llm = LLMClient([FakeProvider("gemini", "fake-model", [reply])], MemoryLLMCache(), Budget(5))
    result = extract_thread(thread, llm, code_outline=render_code_outline(index))
    checks = [resolve_affects(d.data.affects, index) for d in result.decisions]
    return Pipeline(store, thread, index, result, checks)
