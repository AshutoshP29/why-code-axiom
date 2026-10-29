"""A tiny git repository with a known history, built in a temp dir for the code map tests.

c1  Initial commit             pkg/__init__.py, pkg/old_name.py, scripts/tool.py, README.md
c2  Rename old_name to core    pkg/old_name.py -> pkg/core.py
c3  Add Engine (#12)           class Engine with a method in pkg/core.py
c4  Break things               edits pkg/core.py
c5  Revert "Break things"      git revert c4
c6  Add sub package            on branch feature: pkg/sub/__init__.py, pkg/sub/util.py
c7  Merge pull request #7 ...  --no-ff merge of feature into main
"""

import os
import subprocess
from pathlib import Path

INIT = '"""The package."""\n'
OLD = "MAX_SIZE = 10\n\n\ndef f():\n    return 1\n"
ENGINE = (
    "MAX_SIZE = 10\n\n\ndef f():\n    return 1\n\n\n"
    "class Engine:\n    def run(self, limit=MAX_SIZE):\n        return limit\n"
)
BROKEN = ENGINE.replace("return 1", "return 2")
UTIL = "def helper():\n    return 3\n"


def _git(root: Path, *args: str, when: int = 0) -> str:
    date = f"2024-01-{when + 1:02d}T12:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": "ada@example.com",
        "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": "ada@example.com",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    cmd = ["git", "-C", str(root), "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
    return subprocess.run(
        [*cmd, *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


def make_repo(root: Path) -> dict[str, str]:
    """Build the history above in `root`; returns {"c1": sha, ...}."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    shas = {}

    def commit(label: str, message: str, when: int) -> None:
        _git(root, "add", "-A", when=when)
        _git(root, "commit", "-q", "-m", message, when=when)
        shas[label] = _git(root, "rev-parse", "HEAD")

    _write(root, "pkg/__init__.py", INIT)
    _write(root, "pkg/old_name.py", OLD)
    _write(root, "scripts/tool.py", "def main():\n    pass\n")
    _write(root, "README.md", "# tiny\n")
    commit("c1", "Initial commit", 0)

    _git(root, "mv", "pkg/old_name.py", "pkg/core.py")
    commit("c2", "Rename old_name to core", 1)

    _write(root, "pkg/core.py", ENGINE)
    commit("c3", "Add Engine (#12)", 2)

    _write(root, "pkg/core.py", BROKEN)
    commit("c4", "Break things", 3)

    _git(root, "revert", "--no-edit", shas["c4"], when=4)
    shas["c5"] = _git(root, "rev-parse", "HEAD")

    _git(root, "checkout", "-q", "-b", "feature")
    _write(root, "pkg/sub/__init__.py", "")
    _write(root, "pkg/sub/util.py", UTIL)
    commit("c6", "Add sub package", 5)

    _git(root, "checkout", "-q", "main")
    _git(
        root,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge pull request #7 from ada/feature",
        "feature",
        when=6,
    )
    shas["c7"] = _git(root, "rev-parse", "HEAD")
    return shas
