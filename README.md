# WhyCode

WhyCode answers "why is the code like this?" for a real codebase, with evidence on every answer.
It ingests a repository's commits, pull request discussions and issues, builds a Neo4j graph that
links code entities to the decisions, people and incidents behind them, and answers questions with
a chain of evidence: the decision, the discussion that produced it, the person to ask, and the date.

The graph holds the answer; the LLM only words it. When the graph has no answer, WhyCode says so.

Team AXIOM, hackFront India 2026 ("AI and Developer Tools").

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker (for local Postgres and the Neo4j test container)
- A Neo4j AuraDB instance, a GitHub token, Gemini and Groq API keys

## Setup

```sh
uv sync                       # creates .venv with Python 3.12 and installs everything
cp .env.example .env          # then fill in every value; never commit .env
docker compose up -d          # Postgres 16 (raw cache) + Neo4j 5 (integration tests only)
```

Postgres is exposed on host port 5433 (not 5432) so it does not clash with a locally installed Postgres.

```sh
uv run python scripts/check_connections.py                # OK/FAIL per service, lists usable LLM models
uv run python scripts/check_connections.py --no-llm-call  # same, but zero LLM generation calls
uv run python scripts/apply_schema.py --target test       # schema -> local Neo4j test container
uv run python scripts/apply_schema.py --target aura       # schema -> Aura (refuses a non-empty graph)
```

Configuration is read by `whycode/config.py`. A missing or invalid variable stops the program with a
message that names the variable and never prints any value.

The free Aura instance pauses when idle. If Neo4j checks fail, resume it in the Aura console.

## Pipeline (Phase 1, one pull request)

```sh
# 1. Fetch the PR, its comments, reviews, commits, files, timeline and linked issues into Postgres.
#    Re-running sends ETags; unchanged items come back 304 and cost no rate limit.
uv run python -m whycode.ingest.fetch_pr --repo psf/requests --pr 5797

# 2. Extract decisions with the LLM. --dry-run shows what would be sent and makes no call.
uv run python -m whycode.extract.run --repo psf/requests --pr 5797 --dry-run
uv run python -m whycode.extract.run --repo psf/requests --pr 5797 --max-calls 10
```

Every LLM answer is cached in Postgres by `sha256(prompt_version + model + input)`, so a re-run
costs no calls. `LLM_MAX_CALLS` is a hard cap per run. Gemini is tried first and Groq is the
fallback; a provider that keeps failing is skipped for the rest of the run. A decision is kept
only if every evidence quote is found verbatim (whitespace aside) in the source it cites.

## Tests

```sh
uv run pytest                     # unit tests only (default): no network, no databases
uv run pytest -m integration      # needs `docker compose up -d`; uses repo "test/fixture" only
uv run pytest -m live             # real GitHub + LLM calls; costs API calls; never in CI
uv run pytest --cov=whycode       # with coverage
uv run ruff check .
```

## Layout

```
whycode/
  config.py        settings from .env
  ids.py           make_id(repo, kind, key) -> "psf/requests#pr:1565"
  ingest/          GitHub fetch -> Postgres raw cache
  graph/           Neo4j driver wrapper, schema runner, MERGE-only writers
    schema.cypher  the graph contract (source of truth)
  extract/         LLM decision extraction (prompt + pydantic models)
  llm/             llm_client: Gemini/Groq, cache, call budget, retries
  agent/ api/      later phases
tests/  unit/  integration/  e2e/  fixtures/
scripts/
```

Every node carries a `repo` property and every id is prefixed with the repo, so several repositories
can live in one graph without colliding.
