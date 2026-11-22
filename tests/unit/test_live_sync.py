import hashlib
import hmac
import json

import pytest

from tests.api_fakes import FakeGraph, client
from whycode.api import app as app_module
from whycode.api import repos
from whycode.ingest import live

REPO = "ashutoshp29/whycode-demo"
SECRET = "hook-secret"
SHA = "a" * 40
BEFORE = """def greet(name):
    return "Hello " + name


def farewell(name):
    return "Bye " + name
"""
AFTER = """def greet(name):
    return f"Hello, {name}!"


def farewell(name):
    return "Bye " + name


LIMIT = 3
"""
PATCH = """@@ -1,6 +1,9 @@
 def greet(name):
-    return "Hello " + name
+    return f"Hello, {name}!"


 def farewell(name):
     return "Bye " + name
+
+
+LIMIT = 3"""
COMMIT = {
    "sha": SHA,
    "html_url": f"https://github.com/{REPO}/commit/{SHA}",
    "commit": {"message": "Friendlier greeting\n", "author": {"date": "2026-11-22T04:00:00Z"}},
    "author": {"login": "AshutoshP29"},
    "files": [
        {
            "filename": "app.py",
            "status": "modified",
            "additions": 4,
            "deletions": 1,
            "patch": PATCH,
        },
        {"filename": "README.md", "status": "modified", "additions": 1, "deletions": 0},
        {"filename": "old.py", "status": "removed", "additions": 0, "deletions": 3},
    ],
}


def push(ref="refs/heads/main", commits=(SHA,)):
    return {
        "ref": ref,
        "repository": {"full_name": "AshutoshP29/whycode-demo", "default_branch": "main"},
        "commits": [{"id": c, "distinct": True} for c in commits],
    }


class FakeReader:
    def __init__(self, commit=COMMIT, text=AFTER):
        self._commit, self._text, self.calls = commit, text, []

    def commit(self, repo, sha):
        self.calls.append(("commit", repo, sha))
        return self._commit

    def text(self, repo, sha, path):
        self.calls.append(("text", repo, sha, path))
        return self._text


def sign(body: bytes, secret=SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signatures():
    body = b'{"a": 1}'
    assert live.signature_ok(SECRET, body, sign(body))
    assert not live.signature_ok(SECRET, body, sign(body, "other"))
    assert not live.signature_ok(SECRET, b'{"a": 2}', sign(body))
    for bad in (None, "", "sha1=abc", sign(body)[:-1]):
        assert not live.signature_ok(SECRET, body, bad)
    assert not live.signature_ok("", body, sign(body, ""))


def test_a_push_writes_the_commit_its_author_and_the_code_it_changed():
    batch, report = live.build_push_batch(REPO, [COMMIT], {(SHA, "app.py"): AFTER})
    commit_id = f"{REPO}#commit:{SHA}"
    assert batch.nodes["Commit"][commit_id]["message"] == "Friendlier greeting"
    person = f"{REPO}#user:AshutoshP29"
    assert batch.nodes["Person"][person]["active"] is True
    assert (person, commit_id) in batch.rels[("AUTHORED", "Person", "Commit")]
    functions = batch.nodes["Function"]
    assert {f["qualified_name"] for f in functions.values()} == {"greet", "farewell"}
    assert f"{REPO}#cfg:LIMIT" in batch.nodes["ConfigKey"]  # a new code item appears
    modified = {
        target: props
        for (kind, _, _), rels in batch.rels.items()
        if kind == "MODIFIES"
        for (_, target), props in rels.items()
    }
    assert modified[f"{REPO}#file:app.py"] == {"added": 4, "removed": 1}
    assert f"{REPO}#fn:app.py::greet" in modified
    assert f"{REPO}#fn:app.py::farewell" not in modified  # untouched by the diff
    assert (report.commits, report.files) == (1, 1)  # README and the removed file skipped
    assert report.code_items_changed == len(modified) - 1


def test_sync_reads_github_writes_once_and_records_the_sync():
    written, reader = [], FakeReader()
    graph = FakeGraph(live_repo=[{"added": True}], live_synced=[])
    report = live.sync_push(graph, written.append, reader, push())
    assert report.repo == REPO and report.commits == 1 and report.skipped is None
    assert len(written) == 1 and "Commit" in written[0].nodes
    assert ("text", REPO, SHA, "app.py") in reader.calls
    assert ("text", REPO, SHA, "README.md") not in reader.calls
    assert graph.tags() == ["live_repo", "live_synced"]
    assert graph.calls[-1][1] == {"repo": REPO, "sha": SHA}


@pytest.mark.parametrize(
    ("payload", "added", "why"),
    [
        (push(ref="refs/heads/feature"), True, "not the default branch (main)"),
        (push(), False, "not a repository added from the screens"),
    ],
)
def test_other_branches_and_the_teams_own_repos_are_not_synced(payload, added, why):
    written = []
    graph = FakeGraph(live_repo=[{"added": added}])
    report = live.sync_push(graph, written.append, FakeReader(), payload)
    assert report.skipped == why and written == []


def test_a_commit_github_cannot_find_writes_nothing():
    written = []
    report = live.sync_push(
        FakeGraph(live_repo=[{"added": True}]), written.append, FakeReader(commit=None), push()
    )
    assert report.skipped == "no commit could be read from GitHub" and written == []


class _Closing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def hook(event, payload, *, signature=None, graph=None, written=None):
    body = json.dumps(payload).encode()
    overrides = {
        repos.http_client: lambda: _Closing(),
        app_module.get_writer: lambda: (written if written is not None else []).append,
    }
    return client(graph or FakeGraph(), overrides).post(
        "/api/hooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": signature or sign(body),
            "Content-Type": "application/json",
        },
    )


def test_the_hook_needs_its_secret_and_a_valid_signature(monkeypatch):
    monkeypatch.delenv(app_module.WEBHOOK_SECRET_ENV, raising=False)
    assert hook("ping", {"zen": "hi"}).status_code == 503
    monkeypatch.setenv(app_module.WEBHOOK_SECRET_ENV, SECRET)
    assert hook("ping", {"zen": "hi"}, signature="sha256=00").status_code == 401
    res = hook("ping", {"zen": "hi"})
    assert res.status_code == 200 and res.json() == {"event": "ping", "ok": True}


def test_the_hook_needs_no_session_when_sign_in_is_on(monkeypatch):
    monkeypatch.setenv(app_module.WEBHOOK_SECRET_ENV, SECRET)
    monkeypatch.setenv("WHYCODE_AUTH", "github")
    monkeypatch.setenv("SESSION_SECRET", "s")
    assert hook("ping", {"zen": "hi"}).status_code == 200


def test_a_push_event_syncs_the_commits(monkeypatch):
    monkeypatch.setenv(app_module.WEBHOOK_SECRET_ENV, SECRET)
    monkeypatch.setattr(live, "CommitReader", lambda client, token: FakeReader())
    written = []
    graph = FakeGraph(live_repo=[{"added": True}], live_synced=[])
    res = hook("push", push(), graph=graph, written=written)
    assert res.status_code == 200
    assert res.json() == {
        "event": "push",
        "repo": REPO,
        "commits": 1,
        "files": 1,
        "code_items_changed": 2,
        "skipped": None,
    }
    assert len(written) == 1


def test_a_merged_pull_request_restarts_the_run_and_others_are_ignored(monkeypatch):
    monkeypatch.setenv(app_module.WEBHOOK_SECRET_ENV, SECRET)
    started = []

    class Dispatcher:
        configured = True

        def dispatch(self, repo):
            started.append(repo)

    monkeypatch.setattr(repos.Dispatcher, "from_env", classmethod(lambda cls, client: Dispatcher()))
    merged = {
        "action": "closed",
        "pull_request": {"merged": True},
        "repository": {"full_name": "psf/requests"},
    }
    graph = FakeGraph(repo_added=[{"added": True}], repos_busy=[], repo_queue=[])
    res = hook("pull_request", merged, graph=graph)
    assert res.status_code == 200 and res.json()["event"] == "pull_request"
    assert started == ["psf/requests"]
    closed = {**merged, "pull_request": {"merged": False}}
    assert hook("pull_request", closed).json()["skipped"] == "not handled"
    assert hook("issues", {"action": "opened"}).json()["skipped"] == "not handled"
