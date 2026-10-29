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
