"""The whole repository's code map and git history, from a local clone. No LLM, no GitHub API.

    python -m whycode.ingest.codemap --repo psf/requests [--target aura|test] [--since 2020-01-01]

Clones (or updates) https://github.com/<repo> into cache/repos/<owner>/<name>, parses every .py
file at the default branch's HEAD, and reads `git log` for commits, renames and line counts.
"""

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_RECORD, _FIELD = "\x1e", "\x1f"


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    """Run git in `root` and return stdout. Paths stay unquoted; output is read as UTF-8."""
    cmd = ["git", "-C", str(root), "-c", "core.quotepath=off", *args]
    try:
        done = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except subprocess.CalledProcessError as exc:
        raise GitError(f"git {args[0]} failed: {exc.stderr.strip()[:500]}") from None
    return done.stdout


def clone_or_update(url: str, dest: Path) -> str:
    """Make `dest` a full clone of `url` at its default branch's latest commit; return its sha.

    `dest` is a cache owned by this command: an existing clone is reset to origin's HEAD.
    Bytes are kept as committed (no CRLF conversion), so line numbers match the repository.
    """
    if (dest / ".git").exists():
        git(dest, "fetch", "--quiet", "--prune", "origin")
        git(dest, "remote", "set-head", "origin", "--auto")
        git(dest, "reset", "--hard", "--quiet", "origin/HEAD")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        git(dest.parent, "clone", "--quiet", "--config", "core.autocrlf=false", url, str(dest))
    return git(dest, "rev-parse", "HEAD").strip()


def python_files(root: Path) -> list[str]:
    """Tracked .py files at HEAD, repo-relative with forward slashes, sorted."""
    out = git(root, "ls-files", "-z", "--", "*.py")
    return sorted(p for p in out.split("\0") if p)


def rename_aliases(root: Path) -> dict[str, list[str]]:
    """Earlier paths of each file, oldest first, from every rename in the history.

    One `git log -M --diff-filter=R` pass replays renames oldest first, so a file renamed
    twice (a.py -> b.py -> c.py) ends with c.py: [a.py, b.py]. Same result as `git log
    --follow` per file for renames, in one git call instead of one per file.
    """
    out = git(root, "log", "--reverse", "-M", "--diff-filter=R", "--name-status", "--format=")
    aliases: dict[str, list[str]] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            old, new = parts[1], parts[2]
            earlier = [p for p in [*aliases.pop(old, []), old] if p != new]
            aliases[new] = list(dict.fromkeys(earlier))
    return aliases


@dataclass(frozen=True)
class GitCommit:
    sha: str
    parents: tuple[str, ...]
    date: datetime
    message: str
    numstat: tuple[tuple[int, int, str], ...]  # (added, removed, path); binary files count 0


def read_history(root: Path, since: str | None = None) -> list[GitCommit]:
    """Every commit reachable from HEAD (or since a date), newest first, with line counts.

    Merge commits list no files (git shows no diff for them by default); renames show as a
    delete plus an add, so counts always name a path that existed at that commit.
    """
    args = [
        "log",
        "--no-renames",
        "--numstat",
        f"--format={_RECORD}%H{_FIELD}%P{_FIELD}%aI{_FIELD}%B{_FIELD}",
    ]
    if since:
        args.append(f"--since={since}")
    commits = []
    for record in git(root, *args, "HEAD").split(_RECORD)[1:]:
        sha, parents, date, message, rest = record.split(_FIELD, 4)
        numstat = []
        for line in rest.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                added, removed, path = parts
                numstat.append(
                    (
                        int(added) if added.isdigit() else 0,
                        int(removed) if removed.isdigit() else 0,
                        path,
                    )
                )
        commits.append(
            GitCommit(
                sha=sha,
                parents=tuple(parents.split()),
                date=datetime.fromisoformat(date),
                message=message.strip(),
                numstat=tuple(numstat),
            )
        )
    return commits
