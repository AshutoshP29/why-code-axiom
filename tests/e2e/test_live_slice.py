"""Live: the full slice command on psf/requests#5797, written to the local test Neo4j.

Uses the real GitHub token. LLM answers come from the Postgres cache when present; otherwise it
spends at most 12 hosted calls. Run with -m live after `docker compose up -d`.
"""

import subprocess
import sys


def test_slice_command_on_pr_5797():
    out = subprocess.run(
        [sys.executable, "-m", "whycode.slice", "--repo", "psf/requests", "--pr", "5797",
         "--target", "test", "--max-calls", "12"],
        capture_output=True, text=True, encoding="utf-8", timeout=1800,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    text = out.stdout
    assert "[4/4] query 5a" in text
    assert "ANSWER for psf/requests#" in text and 'Evidence: "' in text
    assert "https://github.com/psf/requests/pull/5797" in text
    assert "REFUSED for psf/requests#" in text and "they are not reasons" in text
    assert "Neo4j (test) holds" in text and "Decision " in text
