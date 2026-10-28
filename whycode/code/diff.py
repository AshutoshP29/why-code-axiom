"""Which code entities a pull request changed, from GitHub's unified diff of each file.

Deterministic, no LLM: the `patch` GitHub gives for a changed file is matched against the line
ranges the parser found in the same file as the PR left it, so both use the same line numbers.
"""

import re
from collections import Counter
from dataclasses import dataclass

from whycode.code.entities import CodeEntity, EntityKind, ParsedFile

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_CODE_KINDS = (EntityKind.CLASS, EntityKind.FUNCTION, EntityKind.CONFIG_KEY)


@dataclass(frozen=True)
class LineChange:
    line: int  # line in the file as the PR left it
    added: bool  # True for an added line; False marks where lines were removed


def changed_lines(patch: str | None) -> list[LineChange]:
    """Added lines, plus one marker per removed line on a new-side line:
    - removals followed by additions (a replacement) are marked on the line that replaced them;
    - a pure deletion is marked on the line just before it (the hunk start at the very top).
    Binary files have no patch: no changes."""
    out: list[LineChange] = []
    new_line = hunk_start = pending_removed = 0

    def flush_as_deletion() -> None:
        nonlocal pending_removed
        out.extend([LineChange(max(hunk_start, new_line - 1), False)] * pending_removed)
        pending_removed = 0

    for raw in (patch or "").splitlines():
        m = _HUNK.match(raw)
        if m:
            flush_as_deletion()
            new_line = hunk_start = int(m.group(1))
            continue
        if not hunk_start or raw.startswith("\\"):  # before the first hunk, "\ No newline"
            continue
        if raw.startswith("-"):
            pending_removed += 1
        elif raw.startswith("+"):
            out.extend([LineChange(new_line, False)] * pending_removed)  # replaced here
            pending_removed = 0
            out.append(LineChange(new_line, True))
            new_line += 1
        else:
            flush_as_deletion()
            new_line += 1
    flush_as_deletion()
    return out


@dataclass(frozen=True)
class EntityChange:
    entity: CodeEntity
    added: int
    removed: int


def entities_changed(parsed: ParsedFile, patch: str | None) -> list[EntityChange]:
    """The innermost class, function or config key around each changed line, with counts.

    A changed line inside a method counts for the method, not also for its class; a line in a
    class body outside any method counts for the class.
    """
    code = [e for e in parsed.entities if e.kind in _CODE_KINDS]
    added: Counter = Counter()
    removed: Counter = Counter()
    for change in changed_lines(patch):
        around = [e for e in code if e.start_line <= change.line <= e.end_line]
        if not around:
            continue
        inner = min(
            around, key=lambda e: (e.end_line - e.start_line, e.kind != EntityKind.CONFIG_KEY)
        )
        (added if change.added else removed)[inner.id] += 1
    by_id = {e.id: e for e in code}
    ids = list(dict.fromkeys([*added, *removed]))
    return [EntityChange(by_id[i], added[i], removed[i]) for i in ids]
