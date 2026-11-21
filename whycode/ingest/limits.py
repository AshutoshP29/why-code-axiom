"""Limits on one Add repository run: whycode.ingest.repo enforces them, whycode.api.repos reports
them in its estimate. Kept apart so the API does not import the whole ingest pipeline."""

PR_LIMIT = 20  # the most-discussed merged PRs a run reads
MIN_COMMENTS = 5  # a PR with fewer comments has too little discussion to hold a decision
MAX_CALLS = 60  # hosted AI calls for extraction and supersession together
HISTORY_YEARS = 3  # git history the code map reads
