from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from tests.api_fakes import FILE, FN, NODES, PR, REPO, FakeGraph, client, q5a_row
from whycode.api import app as app_module
from whycode.api import guard

# models.py as a PR leaves it: apparent_encoding changes on line 4.
SOURCE = """class Response:
    @property
    def apparent_encoding(self):
        return charset_normalizer.detect(self.content)["encoding"]
"""
PATCH = (
    "@@ -4,1 +4,1 @@\n"
    "-        return chardet.detect(self.content)['encoding']\n"
    '+        return charset_normalizer.detect(self.content)["encoding"]'
)
PULL = {
    "number": 7000,
    "title": "Go back to chardet",
    "html_url": f"https://github.com/{REPO}/pull/7000",
    "state": "open",
    "merged_at": None,
    "user": {"login": "someone"},
    "created_at": "2026-11-01T10:00:00Z",
    "head": {"sha": "abc123", "repo": {"full_name": "someone/requests"}},
}
FILES = [
    {"filename": "src/requests/models.py", "status": "modified", "patch": PATCH},
    {"filename": "README.md", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"},
]


class FakeReader:
    def __init__(self, pull=PULL, files=FILES, source=SOURCE):
        self._pull, self._files, self.source, self.urls = pull, files, source, []

    def pull(self, repo, number):
        return {**self._pull, "number": number}

    def files(self, repo, number):
        return self._files

    def text(self, url):
        self.urls.append(url)
        return self.source


def graph(rows):
    nodes = [{"e": NODES[FN]}, {"e": NODES[FILE]}]
    return FakeGraph(
        guard_entities=lambda p: [n for n in nodes if n["e"]["id"] in p["ids"]],
        guard_decisions=rows,
    )


def decision(touched, **kw):
    return {**q5a_row(**kw), "touched": touched}


@pytest.mark.parametrize(
    ("text", "number"),
    [("7000", 7000), ("#7000", 7000), (f"https://github.com/{REPO}/pull/7000/files", 7000)],
)
def test_pull_numbers_and_links(text, number):
    assert guard.parse_pull(text, REPO) == number


@pytest.mark.parametrize("text", ["https://github.com/pallets/flask/pull/1", "seven", "70000000"])
def test_other_input_is_refused(text):
    with pytest.raises(HTTPException) as err:
        guard.parse_pull(text, REPO)
    assert err.value.status_code == 400


def test_a_pr_changing_decided_code_gets_the_decision_with_evidence_and_people():
    reader = FakeReader()
    report = guard.check(graph([decision([FN, FILE])]), repo_model(), "7000", reader)
    assert reader.urls == [
        "https://raw.githubusercontent.com/someone/requests/abc123/src/requests/models.py"
    ]
    assert [e.id for e in report.changed] == [FN]
    assert (report.files_changed, report.code_files_read, report.notes) == (2, 1, [])
    [hit] = report.hits
    assert hit.level == "code" and [t.id for t in hit.touched] == [FN]
    assert hit.decision.summary == "Replace chardet with charset_normalizer"
    assert hit.decision.source.label == "PR #5797"
    assert [p.login for p in hit.people] == ["ashb", "nateprewitt"]
    assert len(hit.evidence) == 2 and hit.evidence[0].source.url.endswith("/pull/5797")


def test_file_only_hits_come_after_code_hits():
    older = decision([FILE], id=f"{REPO}#dec:old", decided_at=datetime(2015, 1, 1, tzinfo=UTC))
    report = guard.check(graph([older, decision([FN])]), repo_model(), "7000", FakeReader())
    assert [(h.level, h.decision.id) for h in report.hits] == [
        ("code", f"{REPO}#dec:abc"),
        ("file", f"{REPO}#dec:old"),
    ]


def test_decisions_from_this_pr_or_after_it_opened_are_left_out():
    later = decision([FN], id=f"{REPO}#dec:later", decided_at=datetime(2026, 11, 2, tzinfo=UTC))
    mine = {**decision([FN], id=f"{REPO}#dec:mine"), "sources": [{"id": PR, "number": 5797}]}
    report = guard.check(graph([later, mine]), repo_model(), "5797", FakeReader())
    assert report.hits == []


def test_unknown_code_and_unreadable_files_are_reported():
    report = guard.check(graph([]), repo_model(), "7000", FakeReader(source=None))
    assert report.changed == [] and report.hits == []
    assert report.notes == ["Could not read src/requests/models.py from GitHub."]


def test_no_python_changes_means_no_hits():
    reader = FakeReader(files=[FILES[1]])
    report = guard.check(graph([]), repo_model(), "7000", reader)
    assert (report.code_files_read, report.hits, reader.urls) == (0, [], [])


def test_the_route_checks_a_pull_for_the_repo(monkeypatch):
    monkeypatch.setattr(guard, "GitHubReader", lambda client, token: FakeReader())
    g = graph([decision([FN])])
    res = client(g, {guard.http_client: lambda: _Closing()}).post(
        "/api/guard", json={"repo": "PSF/requests", "pull": "#7000"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["pull"]["number"] == 7000 and body["pull"]["state"] == "open"
    assert body["hits"][0]["touched"][0]["qualified_name"] == "Response.apparent_encoding"
    unknown = client(FakeGraph()).post("/api/guard", json={"repo": "a/b", "pull": "1"})
    assert unknown.status_code == 404


class _Closing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def repo_model():
    from whycode.api.models import Repo

    return Repo(
        id=REPO,
        status="READY",
        stage="supersession",
        progress_pct=100,
        partial=False,
        error=None,
        last_synced_at=None,
        commits_count=0,
        decisions_count=1,
    )


assert app_module  # the route under test lives on the app's router
