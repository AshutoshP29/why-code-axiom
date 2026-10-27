"""Fail the build if secrets are tracked by git or key-like strings appear in committable files."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

KEY_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Groq API key": re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    "GitHub token": re.compile(r"ghp_[0-9A-Za-z]{36}"),
    "GitHub fine-grained token": re.compile(r"github_pat_[0-9A-Za-z_]{22,}"),
    "Neo4j URI with password": re.compile(r"neo4j(?:\+s|\+ssc)?://[^\s/:@]+:[^\s/@]+@"),
    # Catches `NAME=value`, `export NAME=value` and YAML `NAME: value` with a literal value.
    # [ \t] not \s: an empty `NAME=` line must not match the next line's first character.
    # The value must start with a letter or digit, so `NAME: ${{ secrets.X }}` is allowed;
    # a bare `None` (Python keyword argument in tests) is not a secret either.
    "Secret assigned in env style": re.compile(
        r"(?<![A-Za-z0-9_])(?:NEO4J_PASSWORD|GEMINI_API_KEY|GROQ_API_KEY|GITHUB_TOKEN)"
        r"[ \t]*[=:][ \t]*[\"']?(?!None\b)[A-Za-z0-9]"
    ),
}


def _git_files(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", *args], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode().split("\0") if p]


def committable_files() -> list[str]:
    """Tracked files plus untracked files that are not ignored (what `git add .` would take)."""
    return _git_files("--cached", "--others", "--exclude-standard")


def find_keys(text: str) -> list[str]:
    """Names of the key patterns found. Never returns the matched text itself."""
    return [name for name, pat in KEY_PATTERNS.items() if pat.search(text)]


def test_env_and_aura_files_not_tracked():
    tracked = _git_files("--cached")
    names = [(p, Path(p).name) for p in tracked]
    bad = [p for p, n in names if n.endswith(".env") or re.fullmatch(r"Neo4j-.*\.txt", n)]
    assert not bad, f"secret files tracked by git: {bad}"


def test_env_and_aura_files_are_ignored():
    for name in [".env", "Neo4j-abc-Created-2026-01-01.txt", "local.env"]:
        result = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT)
        assert result.returncode == 0, f"{name} is not covered by .gitignore"


def test_no_key_like_strings_in_committable_files():
    hits = []
    for rel in committable_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name in find_keys(text):
            hits.append(f"{rel}: {name}")
    assert not hits, "key-like strings found (values not shown):\n" + "\n".join(hits)


# The scanner must actually catch keys; fakes are assembled at runtime so this file stays clean.
@pytest.mark.parametrize(
    "sample, expected",
    [
        ("AIza" + "A" * 35, "Google API key"),
        ("gsk_" + "b" * 40, "Groq API key"),
        ("ghp_" + "c" * 36, "GitHub token"),
        ("github_pat_" + "d" * 30, "GitHub fine-grained token"),
        ("neo4j+s://neo4j:" + "pw" * 5 + "@host.databases.neo4j.io", "Neo4j URI with password"),
        ("GROQ_API_KEY" + "=" + "x" * 10, "Secret assigned in env style"),
        ("export GITHUB_TOKEN" + "=" + "abc123", "Secret assigned in env style"),
        ("NEO4J_PASSWORD" + ': "' + "abc123" + '"', "Secret assigned in env style"),
    ],
)
def test_scanner_detects_fake_keys(sample, expected):
    assert expected in find_keys(f"prefix {sample} suffix")


@pytest.mark.parametrize(
    "clean",
    [
        "GROQ_API_KEY=",
        "GROQ_API_KEY=\nGITHUB_TOKEN=\n",
        "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}",
        'os.environ["GITHUB_TOKEN"]',
        "MY_GITHUB_TOKEN_NAME=x",
        "env(GROQ_API_KEY=None, NEO4J_PASSWORD=None)",
        "neo4j+s://host.databases.neo4j.io",
        "AIza-short",
        "gsk_",
        "see #ghp_ docs",
    ],
)
def test_scanner_ignores_clean_text(clean):
    assert find_keys(clean) == []


# Commit messages must not carry AI attribution trailers (team rule for this repo).
# Both patterns are anchored to the start of a line, where the trailer and the footer actually
# appear, so a message that merely talks about them is not flagged.
AI_ATTRIBUTION = re.compile(
    r"^co-authored-by:.*(claude|anthropic)|^\W*generated with \[?claude code",
    re.IGNORECASE | re.MULTILINE,
)


def find_ai_attribution(message: str) -> bool:
    return bool(AI_ATTRIBUTION.search(message))


def test_no_ai_attribution_in_commit_messages():
    out = subprocess.run(
        ["git", "log", "--format=%h%x00%B%x1e"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8", errors="replace")
    bad = []
    for record in out.split("\x1e"):
        sha, _, body = record.strip().partition("\x00")
        if sha and find_ai_attribution(body):
            bad.append(sha)
    assert not bad, f"commits with AI attribution lines (reword them before pushing): {bad}"


@pytest.mark.parametrize(
    "message",
    [
        "Fix x\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
        "Fix x\n\nco-authored-by: Someone <noreply@anthropic.com>",
        "Add y\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
        "Add y\n\nGenerated with Claude Code",
    ],
)
def test_attribution_detector_catches_trailers(message):
    assert find_ai_attribution(message)


@pytest.mark.parametrize(
    "message",
    [
        "Add the Claude-free parser",
        "Fix x\n\nCo-authored-by: Manas Gupta <manas@example.com>",
        "Mention claude code in the README",
        "Add a check\n\nScans for the footer that reads generated with Claude Code in PRs.",
    ],
)
def test_attribution_detector_ignores_normal_messages(message):
    assert not find_ai_attribution(message)
