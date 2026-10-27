"""Find issue/PR references and reverts in commit messages, PR bodies and comments.

Rules follow what GitHub itself links:
- "#123", "owner/repo#123", "GH-123" and full github.com issue/pull URLs are references.
- "fixes/closes/resolves #N" (and their tense variants, optional colon) are closing references.
- A "#" glued to a word or URL ("page#12", "/#12", "&#39;") is not a reference, and neither is
  a bare number.
- "(#6767)" in a commit subject is how squash merges name their PR.
"""

import re
from dataclasses import dataclass

from whycode.ids import normalize_repo

_REPO = r"[A-Za-z0-9][\w.-]*/[\w.-]+"

# "#N" not glued to a preceding word, path, entity or another '#'.
_HASH_REF = re.compile(rf"(?<![\w/.&#-])(?:(?P<repo>{_REPO}))?#(?P<num>\d+)\b")
_GH_REF = re.compile(r"(?<![\w/.-])GH-(?P<num>\d+)\b")
_URL_REF = re.compile(
    rf"https?://github\.com/(?P<repo>{_REPO})/(?:issues|pull)/(?P<num>\d+)\b", re.IGNORECASE
)
# A closing keyword ending exactly where a reference starts (searched with endpos = ref start).
_CLOSING_BEFORE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[ \t]*:?[ \t]*\Z", re.IGNORECASE
)
_SUBJECT_PR = re.compile(rf"\((?:{_REPO})?#(?P<num>\d+)\)")
_REVERT_SUBJECT = re.compile(r'^Revert "(?P<subject>.+)"\s*$')
_REVERTS_SHA = re.compile(r"\bThis reverts commit (?P<sha>[0-9a-f]{7,40})\b", re.IGNORECASE)
_REVERTS_REF = re.compile(rf"\breverts?[ \t]+(?:(?P<repo>{_REPO}))?#(?P<num>\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Ref:
    repo: str  # normalized "owner/name"
    number: int
    closing: bool = False


@dataclass(frozen=True)
class Revert:
    subject: str | None  # subject of the reverted commit, from 'Revert "..."'
    shas: tuple[str, ...]  # from "This reverts commit <sha>"
    refs: tuple[Ref, ...]  # from "reverts #N"


def _repo_or(default_repo: str, raw: str | None) -> str:
    return normalize_repo(raw) if raw else default_repo


def parse_refs(text: str, repo: str) -> list[Ref]:
    """All references in text, in order of first appearance, deduplicated.

    A number referenced both plainly and with a closing keyword is reported once, as closing.
    """
    repo = normalize_repo(repo)
    found: list[tuple[int, Ref]] = []
    for m in _HASH_REF.finditer(text):
        found.append((m.start(), Ref(_repo_or(repo, m["repo"]), int(m["num"]))))
    for m in _GH_REF.finditer(text):
        found.append((m.start(), Ref(repo, int(m["num"]))))
    for m in _URL_REF.finditer(text):
        found.append((m.start(), Ref(normalize_repo(m["repo"]), int(m["num"]))))

    closing = {(r.repo, r.number) for pos, r in found if _CLOSING_BEFORE.search(text, 0, pos)}

    out: dict[tuple[str, int], Ref] = {}
    for _, ref in sorted(found, key=lambda x: x[0]):
        k = (ref.repo, ref.number)
        if k not in out:
            out[k] = Ref(ref.repo, ref.number, k in closing)
    return list(out.values())


def closing_refs(text: str, repo: str) -> list[Ref]:
    return [r for r in parse_refs(text, repo) if r.closing]


def subject_pr_numbers(message: str) -> list[int]:
    """PR numbers written as "(#N)" in the first line of a commit message (squash-merge style)."""
    subject = message.splitlines()[0] if message else ""
    return [int(m["num"]) for m in _SUBJECT_PR.finditer(subject)]


def parse_revert(message: str, repo: str) -> Revert | None:
    """Describe what a commit message says it reverts, or None if it is not a revert."""
    repo = normalize_repo(repo)
    subject = message.splitlines()[0] if message else ""
    m = _REVERT_SUBJECT.match(subject)
    shas = tuple(s["sha"].lower() for s in _REVERTS_SHA.finditer(message))
    refs = tuple(
        Ref(_repo_or(repo, r["repo"]), int(r["num"])) for r in _REVERTS_REF.finditer(message)
    )
    if not (m or shas or refs):
        return None
    return Revert(m["subject"] if m else None, shas, refs)
