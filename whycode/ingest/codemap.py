"""The whole repository's code map and git history, from a local clone. No LLM, no GitHub API.

    python -m whycode.ingest.codemap --repo psf/requests [--target aura|test] [--since 2020-01-01]

Clones (or updates) https://github.com/<repo> into cache/repos/<owner>/<name>, parses every .py
file at the default branch's HEAD, and reads `git log` for commits, renames and line counts.
"""

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from whycode.code.entities import EntityKind, parse_file
from whycode.graph.build import GraphBatch
from whycode.ids import make_id, normalize_repo

LABEL_BY_KIND = {
    EntityKind.FILE: "File",
    EntityKind.CLASS: "Class",
    EntityKind.FUNCTION: "Function",
    EntityKind.CONFIG_KEY: "ConfigKey",
}

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


def module_names(paths: list[str]) -> dict[str, str]:
    """Package directory -> dotted module name, for every directory with an __init__.py.

    The name starts at the topmost directory of an unbroken chain of packages, so
    src/requests/ is "requests" (src/ has no __init__.py) and pkg/sub/ is "pkg.sub".
    """
    dirs = {
        PurePosixPath(p).parent.as_posix() for p in paths if PurePosixPath(p).name == "__init__.py"
    }
    dirs.discard(".")
    names = {}
    for d in dirs:
        parts = d.split("/")
        start = len(parts) - 1
        while start > 0 and "/".join(parts[:start]) in dirs:
            start -= 1
        names[d] = ".".join(parts[start:])
    return names


def build_code_map(repo: str, root: Path, head_sha: str | None = None) -> GraphBatch:
    """File, Class, Function, ConfigKey and Module nodes for every .py file at HEAD.

    File CONTAINS its classes, functions and config keys, a class its methods (as the PR graph
    does); Module CONTAINS the files directly in its package. A config key named in several
    files is one node (ids are repo-wide); it keeps the properties from the first file, in
    path order, and every file CONTAINS it.
    """
    repo = normalize_repo(repo)
    b = GraphBatch(repo)
    owner, name = repo.split("/")
    b.node(
        "Repo",
        repo,
        owner=owner,
        name=name,
        url=f"https://github.com/{repo}",
        last_commit_sha=head_sha,
    )
    files = python_files(root)
    aliases = rename_aliases(root)
    modules = module_names(files)
    for module in modules.values():
        b.node("Module", make_id(repo, "mod", module), name=module)

    for path in files:
        parsed = parse_file(repo, path, (root / path).read_bytes())
        file_id = parsed.entities[0].id
        earlier = aliases.get(path, [])
        b.node(
            "File",
            file_id,
            path=path,
            name=PurePosixPath(path).name,
            aliases=earlier,
            aliases_text=" ".join(earlier),
        )
        package = modules.get(PurePosixPath(path).parent.as_posix())
        if package:
            b.rel("CONTAINS", ("Module", make_id(repo, "mod", package)), ("File", file_id))
        labels = {e.id: LABEL_BY_KIND[e.kind] for e in parsed.entities}
        for e in parsed.entities[1:]:
            ref = (LABEL_BY_KIND[e.kind], e.id)
            if e.id not in b.nodes.get(ref[0], {}):
                b.node(
                    *ref,
                    name=e.name,
                    qualified_name=e.qualified_name,
                    path=e.path,
                    start_line=e.start_line,
                    end_line=e.end_line,
                    value=e.value,
                    aliases_text="",
                )
            if e.parent_id in labels:
                b.rel("CONTAINS", (labels[e.parent_id], e.parent_id), ref)
    return b
