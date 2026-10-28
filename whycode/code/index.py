"""The code one pull request touched, parsed: what a decision's `affects` is checked against.

Built from the raw cache only (fetch_pr stores the blobs and the tree), so it costs no GitHub
calls. Each changed file is mapped from its PR-era path to where it lives on the default branch
today (requests/compat.py -> src/requests/compat.py), because graph ids use the current path.
"""

import base64
import logging
from dataclasses import dataclass, field

from whycode.code.entities import ParsedFile, is_supported, parse_file
from whycode.ids import make_id, normalize_repo
from whycode.ingest.fetch_pr import default_branch

log = logging.getLogger(__name__)


def map_to_current(path: str, current_paths: set[str]) -> str | None:
    """Where a PR-era path lives today: the same path, or the one current path ending in it."""
    if path in current_paths:
        return path
    matches = [p for p in current_paths if p.endswith("/" + path)]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class ChangedFile:
    pr_path: str  # as the PR named it
    previous_path: str | None  # set when the PR itself renamed the file
    status: str  # added | modified | renamed | removed | ...
    current_path: str | None  # on the default branch today; None if gone or unknown

    @property
    def graph_path(self) -> str:
        """The path graph ids use: today's path when known, else the PR's."""
        return self.current_path or self.pr_path


@dataclass
class PrCodeIndex:
    repo: str
    number: int
    files: list[ChangedFile]
    parsed: dict[str, ParsedFile]  # keyed by pr_path; Python files only
    tree_known: bool  # False when the current tree was not fetched: paths stay as in the PR
    missing_code: list[str] = field(default_factory=list)  # Python files whose blob is not stored

    def file_id(self, f: ChangedFile) -> str:
        return make_id(self.repo, "file", f.graph_path)

    def find_file(self, path: str) -> ChangedFile | None:
        """Resolve a path as an LLM might write it: PR path, old name, today's path, or a unique
        tail such as "compat.py"."""
        p = path.strip().replace("\\", "/").removeprefix("./").lstrip("/")
        if not p:
            return None
        for f in self.files:
            if p in (f.pr_path, f.previous_path, f.current_path):
                return f
        tails = [
            f
            for f in self.files
            if any(c and (c == p or c.endswith("/" + p)) for c in (f.pr_path, f.current_path))
        ]
        return tails[0] if len(tails) == 1 else None


def build_pr_code_index(store, repo: str, number: int) -> PrCodeIndex:
    repo = normalize_repo(repo)
    pr_row = store.get(repo, "pr", str(number))
    if pr_row is None:
        raise LookupError(f"{repo}#{number} is not in raw_github; fetch it first")

    branch = default_branch(pr_row.payload)
    tree_row = store.get(repo, "tree", branch) if branch else None
    current = (
        {e["path"] for e in tree_row.payload.get("tree", []) if e.get("type") == "blob"}
        if tree_row is not None
        else None
    )
    if current is None:
        log.warning("no current tree for %s; keeping PR-era paths", repo)

    index = PrCodeIndex(repo, number, [], {}, tree_known=current is not None)
    for changed in store.pages(repo, "pr_files", number):
        f = ChangedFile(
            pr_path=changed["filename"],
            previous_path=changed.get("previous_filename"),
            status=changed.get("status", ""),
            current_path=map_to_current(changed["filename"], current) if current else None,
        )
        index.files.append(f)
        sha = changed.get("sha")
        if f.status == "removed" or not sha or not is_supported(f.pr_path):
            continue
        blob = store.get(repo, "blob", sha)
        if blob is None:
            index.missing_code.append(f.pr_path)
            continue
        source = base64.b64decode(blob.payload["content"])
        index.parsed[f.pr_path] = parse_file(repo, f.graph_path, source)
    return index
