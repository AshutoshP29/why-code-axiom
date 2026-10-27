"""Live: real GitHub fetch of psf/requests#5797 into the local Postgres. Run with -m live."""

from whycode.config import get_settings
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubClient
from whycode.ingest.store import RawStore


def test_fetch_pr_5797_from_github():
    s = get_settings()
    store = RawStore.connect(s.postgres_dsn.get_secret_value())
    try:
        store.ensure_schema()
        with GitHubClient(s.github_token.get_secret_value()) as gh:
            r = fetch_pr(gh, store, "psf/requests", 5797)
        assert r.pr["merged"] is True
        assert "charset_normalizer" in r.pr["title"]
        assert len(r.issue_comments) >= 100  # about 105 when written
        assert len(r.review_comments) >= 20  # about 25 when written
        assert any(f["filename"].endswith(".py") for f in r.files)
        assert store.get("psf/requests", "pr", "5797").payload["number"] == 5797
    finally:
        store.close()
