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
