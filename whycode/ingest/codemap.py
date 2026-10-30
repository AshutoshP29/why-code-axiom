"""The whole repository's code map and git history, from a local clone. No LLM, no GitHub API.

    python -m whycode.ingest.codemap --repo psf/requests [--target aura|test] [--since 2020-01-01]

Clones (or updates) https://github.com/<repo> into cache/repos/<owner>/<name>, parses every .py
file at the default branch's HEAD, and reads `git log` for commits, renames and line counts.
Everything is written with MERGE (whycode.graph.writer), so a second run changes no count, and
Decision nodes are never touched.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from whycode.code.entities import EntityKind, parse_file
from whycode.graph.build import GraphBatch
from whycode.ids import make_id, normalize_repo
from whycode.ingest.links import merge_pr_number, parse_revert, subject_pr_numbers

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
        f"--format={_RECORD}%H{_FIELD}%P{_FIELD}%at{_FIELD}%B{_FIELD}",
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
                date=datetime.fromtimestamp(int(date), UTC),
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


@dataclass(frozen=True)
class HistoryStats:
    commits: int
    references: int
    reverts: int
    modifies: int


def _modified_files(c: GitCommit, files: dict[str, str], current: dict[str, str]):
    """(file id, added, removed) for each file at HEAD this commit changed.

    A path that no longer exists is followed to its current name through the File aliases.
    When a commit touches both a file's old and new path (the rename itself), only the new
    path's counts are kept, so a pure rename is not counted as changed lines twice.
    """
    out: dict[str, tuple[int, int]] = {}
    for added, removed, path in c.numstat:
        if path in files:
            out[files[path]] = (added, removed)
    for added, removed, path in c.numstat:
        head_path = current.get(path)
        if path not in files and head_path in files and files[head_path] not in out:
            out[files[head_path]] = (added, removed)
    return out


def _revert_targets(c: GitCommit, older: list[GitCommit], repo: str) -> list[str]:
    """Shas `c` reverts among the commits read: by "This reverts commit <sha>" (a unique
    prefix is enough), else by the newest older commit whose subject is the quoted one."""
    revert = parse_revert(c.message, repo)
    if revert is None:
        return []
    targets = []
    for short in revert.shas:
        matches = [o.sha for o in older if o.sha.startswith(short)]
        if len(matches) == 1:
            targets.append(matches[0])
    if not targets and revert.subject:
        for o in older:
            if o.message.splitlines()[0] == revert.subject:
                targets.append(o.sha)
                break
    return targets


def add_history(b: GraphBatch, commits: list[GitCommit]) -> HistoryStats:
    """Commit nodes and their REFERENCES, REVERTS and MODIFIES edges, from newest-first commits.

    REFERENCES goes to the PullRequest a "(#N)" squash subject or a "Merge pull request #N"
    merge names. No PullRequest node is created: the writer MATCHes both ends, so the edge is
    written only for pull requests the PR ingest already holds, and the PR count it reports
    stays the number of PRs really ingested. REVERTS only links commits that were read.
    MODIFIES goes to File nodes at HEAD, with line counts.
    """
    repo = b.repo
    files = {props["path"]: fid for fid, props in b.nodes.get("File", {}).items()}
    current = {
        alias: props["path"]
        for props in b.nodes.get("File", {}).values()
        for alias in props.get("aliases", [])
    }
    references = reverts = modifies = 0
    for i, c in enumerate(commits):
        ref = ("Commit", make_id(repo, "commit", c.sha))
        b.node(
            *ref,
            sha=c.sha,
            message=c.message,
            date=c.date,
            url=f"https://github.com/{repo}/commit/{c.sha}",
        )
        merged = merge_pr_number(c.message)
        numbers = subject_pr_numbers(c.message) + ([merged] if merged is not None else [])
        for n in dict.fromkeys(numbers):
            b.rel("REFERENCES", ref, ("PullRequest", make_id(repo, "pr", n)))
            references += 1
        for target in _revert_targets(c, commits[i + 1 :], repo):
            b.rel("REVERTS", ref, ("Commit", make_id(repo, "commit", target)))
            reverts += 1
        for file_id, (added, removed) in _modified_files(c, files, current).items():
            b.rel("MODIFIES", ref, ("File", file_id), added=added, removed=removed)
            modifies += 1
    return HistoryStats(len(commits), references, reverts, modifies)


CACHE_DIR = Path(__file__).resolve().parents[2] / "cache" / "repos"


def run_codemap(
    repo: str, root: Path, head_sha: str | None = None, since: str | None = None
) -> tuple[GraphBatch, HistoryStats]:
    batch = build_code_map(repo, root, head_sha)
    return batch, add_history(batch, read_history(root, since))


def _target(name: str):
    from whycode.graph import client

    if name == "test":
        return client.local_test_target()
    from whycode.config import get_settings

    return client.aura_target(get_settings())


def main(argv: list[str] | None = None) -> int:
    from whycode.config import ConfigError
    from whycode.graph.writer import repo_counts, write_batch

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--target", choices=["aura", "test"], default="aura")
    parser.add_argument("--since", help="only commits after this date, e.g. 2020-01-01")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--url", help="clone from here instead of GitHub (a mirror or local path)")
    parser.add_argument("--dry-run", action="store_true", help="build and count, write nothing")
    args = parser.parse_args(argv)

    try:
        repo = normalize_repo(args.repo)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    dest = args.cache_dir / repo
    url = args.url or f"https://github.com/{repo}.git"
    try:
        print(f"Updating the clone of {repo} in {dest}")
        head = clone_or_update(url, dest)
        batch, stats = run_codemap(repo, dest, head, args.since)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    files = len(batch.nodes.get("File", {}))
    code = sum(len(batch.nodes.get(label, {})) for label in ("Class", "Function", "ConfigKey"))
    window = f" since {args.since}" if args.since else ""
    print(f"HEAD {head[:12]}: {files} .py files, {code} classes/functions/config keys")
    print(
        f"History{window}: {stats.commits} commits, {stats.references} PR references, "
        f"{stats.reverts} reverts, {stats.modifies} file changes"
    )
    nodes, rels = batch.count()
    print(f"Batch: {nodes} nodes, {rels} relationships")
    if args.dry_run:
        return 0

    try:
        target = _target(args.target)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    driver = target.driver()
    try:
        write_batch(driver, target.database, batch)
        by_label, rel_count = repo_counts(driver, target.database, repo)
    finally:
        driver.close()
    print(f"Neo4j ({target.name}) now holds for {repo}:")
    for label, n in by_label.items():
        print(f"  {label}: {n}")
    print(f"  relationships: {rel_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
