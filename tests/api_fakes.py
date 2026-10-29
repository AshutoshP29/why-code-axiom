"""A stand-in for Neo4j behind the API: answers each query by its "// q:<name>" tag.

The three untagged queries come from whycode.graph.queries (5a, entity check, facts) and are
told apart by their text. Every call is recorded so tests can check the repo filter.
"""

import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from whycode.api.app import create_app, get_run

REPO = "psf/requests"
GH = f"https://github.com/{REPO}"
FN = f"{REPO}#fn:src/requests/models.py::Response.apparent_encoding"
CLS = f"{REPO}#cls:src/requests/models.py::Response"
FILE = f"{REPO}#file:src/requests/models.py"
CFG = f"{REPO}#cfg:DEFAULT_RETRIES"
UNEXPLAINED = f"{REPO}#fn:src/requests/__init__.py::check_compatibility"
DEC = f"{REPO}#dec:abc"
PR = f"{REPO}#pr:5797"
QUOTE_SOURCE = "By changing out this dependency for one under MIT we remove all license ambiguity."

REPO_NODE = {
    "id": REPO,
    "status": "READY",
    "stage": "extract",
    "partial": True,
    "last_synced_at": datetime(2026, 10, 28, 12, tzinfo=UTC),
}
NODES = {
    FILE: {"id": FILE, "repo": REPO, "path": "src/requests/models.py", "name": "models.py"},
    CLS: {
        "id": CLS,
        "repo": REPO,
        "name": "Response",
        "qualified_name": "Response",
        "path": "src/requests/models.py",
    },
    FN: {
        "id": FN,
        "repo": REPO,
        "name": "apparent_encoding",
        "qualified_name": "Response.apparent_encoding",
        "path": "src/requests/models.py",
    },
    CFG: {
        "id": CFG,
        "repo": REPO,
        "name": "DEFAULT_RETRIES",
        "qualified_name": "DEFAULT_RETRIES",
        "path": "src/requests/adapters.py",
        "value": "0",
    },
    UNEXPLAINED: {
        "id": UNEXPLAINED,
        "repo": REPO,
        "name": "check_compatibility",
        "qualified_name": "check_compatibility",
        "path": "src/requests/__init__.py",
    },
}
DECISION_NODE = {
    "id": DEC,
    "summary": "Replace chardet with charset_normalizer",
    "rationale": "chardet is LGPL, which is ambiguous inside an MIT library.",
    "alternatives": ["Keep chardet as an optional extra"],
    "decided_at": datetime(2021, 7, 6, tzinfo=UTC),
    "status": "ACTIVE",
    "evidence_kind": "EXPLICIT",
    "extraction_confidence": 0.95,
}
PR_NODE = {
    "id": PR,
    "number": 5797,
    "url": f"{GH}/pull/5797",
    "merged_at": DECISION_NODE["decided_at"],
}
PERSON = {"login": "ashb", "active": True, "last_seen": datetime(2025, 1, 2, tzinfo=UTC)}
APPROVER = {"login": "nateprewitt", "active": True, "last_seen": datetime(2026, 1, 2, tzinfo=UTC)}
COMMIT = {
    "id": f"{REPO}#commit:0123456789abcdef",
    "sha": "0123456789abcdef",
    "message": "Switch to charset_normalizer\n\nBody",
    "date": datetime(2021, 7, 6, tzinfo=UTC),
    "url": f"{GH}/commit/0123456789abcdef",
}


def evidence(i: int, kind: str = "pr_body", author: str = "ashb") -> dict:
    return {
        "ev": {
            "id": f"{REPO}#ev:pr:5797:{'body' if i == 0 else f'ic:{i}'}",
            "text": QUOTE_SOURCE,
            "source_type": kind,
            "url": f"{GH}/pull/5797",
            "author": author,
            "date": datetime(2021, 4, 22 + i, tzinfo=UTC),
        },
        "start": 0,
        "end": 47,
    }


def q5a_row(**decision) -> dict:
    return {
        "d": {**DECISION_NODE, **decision},
        "evidence": [evidence(0), evidence(1, "pr_comment", "nateprewitt")],
        "proposers": [PERSON],
        "approvers": [APPROVER],
        "sources": [PR_NODE],
    }


class FakeGraph:
    def __init__(self, **handlers):
        self.handlers = {
            "repos": [{"r": REPO_NODE, "commits": 3, "decisions": 1}],
            "repo": lambda p: (
                [{"r": REPO_NODE, "commits": 3, "decisions": 1}] if p["repo"] == REPO else []
            ),
            "entity": lambda p: [{"e": NODES[p["id"]]}] if p["id"] in NODES else [],
            **handlers,
        }
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, cypher: str, params: dict) -> list[dict]:
        self.calls.append((cypher, params))
        tag = re.match(r"// q:(\w+)", cypher.lstrip())
        if tag:
            key = tag.group(1)
        elif "SUPPORTED_BY" in cypher:
            key = "q5a"
        elif "MODIFIES" in cypher:
            key = "facts"
        else:
            key = "exists"
        handler = self.handlers.get(key, [])
        return handler(params) if callable(handler) else handler

    def tags(self) -> list[str]:
        """Tags of the tagged queries run so far, in order."""
        return [t.group(1) for c, _ in self.calls if (t := re.match(r"// q:(\w+)", c.lstrip()))]


def client(graph: FakeGraph, **overrides) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_run] = lambda: graph
    for dep, value in overrides.items():
        app.dependency_overrides[dep] = value
    return TestClient(app)
