from datetime import UTC, datetime

import pytest

from tests.gitrepo import make_repo
from whycode.ingest import codemap


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    root = tmp_path_factory.mktemp("tiny") / "repo"
    return root, make_repo(root)


def test_python_files_at_head(tiny):
    root, _ = tiny
    assert codemap.python_files(root) == [
        "pkg/__init__.py",
        "pkg/core.py",
        "pkg/sub/__init__.py",
        "pkg/sub/util.py",
        "scripts/tool.py",
    ]


def test_rename_aliases(tiny):
    root, _ = tiny
    assert codemap.rename_aliases(root) == {"pkg/core.py": ["pkg/old_name.py"]}


def test_history_newest_first_with_line_counts(tiny):
    root, shas = tiny
    commits = codemap.read_history(root)
    by_sha = {c.sha: c for c in commits}
    assert commits[0].sha == shas["c7"]
    assert len(commits) == 7
    assert by_sha[shas["c7"]].parents == (shas["c5"], shas["c6"])
    assert by_sha[shas["c7"]].numstat == ()  # merges list no files
    assert by_sha[shas["c3"]].message == "Add Engine (#12)"
    assert by_sha[shas["c3"]].date == datetime(2024, 1, 3, 12, tzinfo=UTC)
    assert by_sha[shas["c3"]].numstat == ((5, 0, "pkg/core.py"),)
    # a rename shows as a delete plus an add
    assert sorted(by_sha[shas["c2"]].numstat) == [(0, 5, "pkg/old_name.py"), (5, 0, "pkg/core.py")]
    assert by_sha[shas["c5"]].message.startswith('Revert "Break things"')


def test_history_since_a_date(tiny):
    root, shas = tiny
    recent = codemap.read_history(root, since="2024-01-05T00:00:00+00:00")
    assert {c.sha for c in recent} == {shas["c5"], shas["c6"], shas["c7"]}


def test_clone_then_update(tiny, tmp_path):
    root, shas = tiny
    dest = tmp_path / "cache" / "owner" / "name"
    assert codemap.clone_or_update(root.as_uri(), dest) == shas["c7"]
    assert codemap.python_files(dest) == codemap.python_files(root)
    (dest / "pkg" / "core.py").write_text("local edit")  # the cache is ours: reset wipes it
    assert codemap.clone_or_update(root.as_uri(), dest) == shas["c7"]
    assert (dest / "pkg" / "core.py").read_bytes() == (root / "pkg" / "core.py").read_bytes()


def test_git_errors_are_short_and_typed(tmp_path):
    with pytest.raises(codemap.GitError, match="git log failed"):
        codemap.git(tmp_path, "log")


R = "test/tiny"
CORE = f"{R}#file:pkg/core.py"


@pytest.fixture(scope="module")
def code(tiny):
    root, shas = tiny
    return codemap.build_code_map(R, root, shas["c7"])


def rels(batch, type_):
    return {
        (a_label, a, b_label, b)
        for (t, a_label, b_label), pairs in batch.rels.items()
        if t == type_
        for a, b in pairs
    }


def test_repo_node_records_head(code, tiny):
    _, shas = tiny
    assert code.nodes["Repo"][R] == {
        "repo": R,
        "owner": "test",
        "name": "tiny",
        "url": "https://github.com/test/tiny",
        "last_commit_sha": shas["c7"],
    }


def test_files_with_aliases(code):
    files = code.nodes["File"]
    assert sorted(files) == [
        f"{R}#file:pkg/__init__.py",
        CORE,
        f"{R}#file:pkg/sub/__init__.py",
        f"{R}#file:pkg/sub/util.py",
        f"{R}#file:scripts/tool.py",
    ]
    assert files[CORE] == {
        "repo": R,
        "path": "pkg/core.py",
        "name": "core.py",
        "aliases": ["pkg/old_name.py"],
        "aliases_text": "pkg/old_name.py",
    }
    assert files[f"{R}#file:scripts/tool.py"]["aliases"] == []


def test_modules_contain_their_files(code):
    assert sorted(code.nodes["Module"]) == [f"{R}#mod:pkg", f"{R}#mod:pkg.sub"]
    assert rels(code, "CONTAINS") >= {
        ("Module", f"{R}#mod:pkg", "File", CORE),
        ("Module", f"{R}#mod:pkg", "File", f"{R}#file:pkg/__init__.py"),
        ("Module", f"{R}#mod:pkg.sub", "File", f"{R}#file:pkg/sub/util.py"),
    }
    assert not any(b == f"{R}#file:scripts/tool.py" for _, _, _, b in rels(code, "CONTAINS"))


def test_code_entities_and_containment(code):
    engine = f"{R}#cls:pkg/core.py::Engine"
    run = f"{R}#fn:pkg/core.py::Engine.run"
    assert code.nodes["Class"][engine]["start_line"] == 8  # MAX_SIZE, f, then the class
    assert code.nodes["Function"][run]["qualified_name"] == "Engine.run"
    assert code.nodes["ConfigKey"][f"{R}#cfg:MAX_SIZE"]["value"] == "10"
    assert code.nodes["ConfigKey"][f"{R}#cfg:limit"]["value"] == "MAX_SIZE"
    assert rels(code, "CONTAINS") >= {
        ("File", CORE, "Class", engine),
        ("Class", engine, "Function", run),
        ("File", CORE, "Function", f"{R}#fn:pkg/core.py::f"),
        ("File", CORE, "ConfigKey", f"{R}#cfg:MAX_SIZE"),
        ("Function", run, "ConfigKey", f"{R}#cfg:limit"),
    }


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["src/requests/__init__.py", "src/requests/sessions.py"], {"src/requests": "requests"}),
        (
            ["a/__init__.py", "a/b/__init__.py", "a/b/c/__init__.py"],
            {"a": "a", "a/b": "a.b", "a/b/c": "a.b.c"},
        ),
        (["a/b/__init__.py"], {"a/b": "b"}),  # a/ is not a package
        (["__init__.py", "x.py"], {}),  # the repo root is never a module
    ],
)
def test_module_names(paths, expected):
    assert codemap.module_names(paths) == expected


def test_config_key_in_two_files_keeps_the_first(tmp_path):
    from tests.gitrepo import _git, _write

    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, "a.py", "TIMEOUT = 1\n")
    _write(root, "b.py", "\n\nTIMEOUT = 2\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "two files")
    b = codemap.build_code_map(R, root)
    assert b.nodes["ConfigKey"][f"{R}#cfg:TIMEOUT"]["path"] == "a.py"
    assert b.nodes["ConfigKey"][f"{R}#cfg:TIMEOUT"]["value"] == "1"
    assert {(a, x) for _, a, _, x in rels(b, "CONTAINS")} == {
        (f"{R}#file:a.py", f"{R}#cfg:TIMEOUT"),
        (f"{R}#file:b.py", f"{R}#cfg:TIMEOUT"),
    }
    assert "last_commit_sha" not in b.nodes["Repo"][R]


@pytest.fixture(scope="module")
def full(tiny):
    root, shas = tiny
    b = codemap.build_code_map(R, root, shas["c7"])
    stats = codemap.add_history(b, codemap.read_history(root))
    return b, stats, shas


def cid(sha):
    return f"{R}#commit:{sha}"


def test_commit_nodes(full):
    b, stats, shas = full
    assert stats.commits == len(b.nodes["Commit"]) == 7
    c3 = b.nodes["Commit"][cid(shas["c3"])]
    assert (c3["sha"], c3["message"], c3["url"]) == (
        shas["c3"],
        "Add Engine (#12)",
        f"https://github.com/{R}/commit/{shas['c3']}",
    )
    assert c3["date"] == datetime(2024, 1, 3, 12, tzinfo=UTC)


def test_references_from_squash_and_merge_subjects(full):
    b, stats, shas = full
    assert rels(b, "REFERENCES") == {
        ("Commit", cid(shas["c3"]), "PullRequest", f"{R}#pr:12"),
        ("Commit", cid(shas["c7"]), "PullRequest", f"{R}#pr:7"),
    }
    assert b.nodes["PullRequest"][f"{R}#pr:7"] == {
        "repo": R,
        "number": 7,
        "url": f"https://github.com/{R}/pull/7",
    }
    assert stats.references == 2


def test_revert_links_to_the_reverted_commit(full):
    b, stats, shas = full
    assert rels(b, "REVERTS") == {("Commit", cid(shas["c5"]), "Commit", cid(shas["c4"]))}
    assert stats.reverts == 1


def test_modifies_current_files_with_line_counts(full):
    b, stats, shas = full
    core = f"{R}#file:pkg/core.py"
    pairs = {
        (a, x): props
        for (t, _, _), ps in b.rels.items()
        if t == "MODIFIES"
        for (a, x), props in ps.items()
    }
    assert pairs[(cid(shas["c1"]), core)] == {"added": 5, "removed": 0}  # as pkg/old_name.py
    assert pairs[(cid(shas["c2"]), core)] == {"added": 5, "removed": 0}  # the rename, once
    assert pairs[(cid(shas["c3"]), core)] == {"added": 5, "removed": 0}
    assert pairs[(cid(shas["c4"]), core)] == {"added": 1, "removed": 1}
    assert pairs[(cid(shas["c6"]), f"{R}#file:pkg/sub/util.py")] == {"added": 2, "removed": 0}
    assert not any(a == cid(shas["c7"]) for a, _ in pairs)  # merges list no files
    assert not any(x.endswith("README.md") for _, x in pairs)  # only .py files are nodes
    assert stats.modifies == len(pairs)


def test_history_window_links_only_commits_it_read(full, tiny):
    root, shas = tiny
    b = codemap.build_code_map(R, root)
    recent = codemap.read_history(root, since="2024-01-05T00:00:00+00:00")
    stats = codemap.add_history(b, recent)
    assert stats.commits == 3
    assert stats.reverts == 0  # c4 is outside the window
    assert rels(b, "REVERTS") == set()


def commit(sha, message, numstat=()):
    return codemap.GitCommit(sha, (), datetime(2024, 1, 1, tzinfo=UTC), message, tuple(numstat))


def test_revert_by_short_sha_and_by_subject():
    older = [commit("abcdef1234", "Do it"), commit("abd0000000", "Other")]
    short = commit("f" * 10, 'Revert "Do it"\n\nThis reverts commit abcdef1.')
    assert codemap._revert_targets(short, older, R) == ["abcdef1234"]
    ambiguous = commit("e" * 10, "This reverts commit ab.")  # too short to parse as a sha
    assert codemap._revert_targets(ambiguous, older, R) == []
    by_subject = commit("d" * 10, 'Revert "Other"')
    assert codemap._revert_targets(by_subject, older, R) == ["abd0000000"]
    not_revert = commit("c" * 10, "Plain change")
    assert codemap._revert_targets(not_revert, older, R) == []


def test_cli_dry_run_reports_counts(tiny, tmp_path, capsys):
    root, shas = tiny
    code = codemap.main(
        ["--repo", R, "--url", root.as_uri(), "--cache-dir", str(tmp_path), "--dry-run"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert f"HEAD {shas['c7'][:12]}: 5 .py files" in out
    assert "7 commits, 2 PR references, 1 reverts" in out
    assert (tmp_path / "test" / "tiny" / ".git").exists()


def test_cli_writes_with_the_writer(tiny, tmp_path, monkeypatch, capsys):
    root, _ = tiny
    written, closed = [], []

    class Driver:
        def close(self):
            closed.append(True)

    class Target:
        name, database = "test", "neo4j"

        def driver(self):
            return Driver()

    monkeypatch.setattr("whycode.graph.client.local_test_target", lambda: Target())
    monkeypatch.setattr(
        "whycode.graph.writer.write_batch", lambda d, db, batch: written.append(batch)
    )
    monkeypatch.setattr(
        "whycode.graph.writer.repo_counts", lambda d, db, repo: ({"File": 5, "Commit": 7}, 40)
    )
    args = ["--repo", R, "--url", root.as_uri(), "--cache-dir", str(tmp_path), "--target", "test"]
    assert codemap.main(args) == 0
    (batch,) = written
    assert batch.repo == R and not batch.replaces_decisions_of  # never touches decisions
    assert "Decision" not in batch.nodes
    assert closed == [True]
    out = capsys.readouterr().out
    assert "Neo4j (test) now holds for test/tiny:" in out and "relationships: 40" in out


def test_cli_errors(tmp_path, monkeypatch, capsys):
    assert codemap.main(["--repo", "not-a-repo"]) == 2
    missing = (tmp_path / "nowhere").as_uri()
    assert codemap.main(["--repo", R, "--url", missing, "--cache-dir", str(tmp_path)]) == 1
    assert "git clone failed" in capsys.readouterr().err


def test_cli_without_aura_settings(tiny, tmp_path, monkeypatch, capsys):
    from whycode.config import ConfigError

    root, _ = tiny

    def no_settings():
        raise ConfigError("Configuration error (missing: NEO4J_URI).")

    monkeypatch.setattr("whycode.config.get_settings", no_settings)
    args = ["--repo", R, "--url", root.as_uri(), "--cache-dir", str(tmp_path)]
    assert codemap.main(args) == 2
    assert "NEO4J_URI" in capsys.readouterr().err
