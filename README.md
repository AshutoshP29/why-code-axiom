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
costs no calls. `LLM_MAX_CALLS` is a hard cap per run, counting every hosted attempt. Gemini is
tried first and Groq is the fallback. A provider that is down twice in a row is skipped for 10
minutes, and so is one whose quota is used up (three rate limits in a row with no retry hint);
one that asks for a longer wait than 120 s is skipped for as long as it asked. Shorter rate
limits are waited out. A part too large for a provider (HTTP 413) is split in two and retried. A
decision is kept only if every evidence quote is found verbatim (whitespace aside) in the source
it cites.

After extraction, each decision's `affects` is checked against the code the PR touched: the PR's
changed Python files are parsed with tree-sitter (`whycode/code/`), and a file, function, class or
config key is kept only if it really exists there. Paths are mapped to where the files live today
(`requests/compat.py` -> `src/requests/compat.py`). Dropped items are printed with a reason.

### Phase 1 slice: one PR end to end

```sh
uv run python -m whycode.slice --repo psf/requests --pr 5797                # writes to Aura
uv run python -m whycode.slice --repo psf/requests --pr 5797 --target test  # local container
```

Fetches the PR, extracts its decisions (from the LLM cache when possible), writes the graph to
Neo4j with MERGE (re-running changes nothing; re-extraction replaces a PR's decisions) and answers
query 5a: the current decision for the code the extraction linked most, with its verbatim
evidence, URLs, people and date. It also shows a refusal for code the PR changed that no decision
explains: facts only (which commit changed it, who last did), never an invented reason.

## Pipeline (Phase 2, many pull requests)

```sh
# Queue the most discussed merged PRs (dependency bumps skipped), fetch them and plan extraction.
# GitHub calls only: shows per PR how many prompt parts are needed and how many are cached.
uv run python -m whycode.ingest.run --repo psf/requests --min-comments 20 --limit 63 --dry-run

# The real run: fetch, extract, check affects and write each PR to the graph.
uv run python -m whycode.ingest.run --repo psf/requests --min-comments 20 --limit 63 --max-calls 160
```

Every PR is a row in the Postgres `jobs` table, so a run can be stopped and started again: written
PRs are skipped and cached LLM answers cost nothing (`--no-select` only resumes the queue). A PR
GitHub cannot serve is marked failed and one the LLM cannot answer stays queued; the run goes on.
It stops only when the budget is spent, every provider is switched off or GitHub's rate limit is
hit, and what was written stays written.

`--redo-fallback` sends written PRs back to the queue when any part of them was answered by the
local model, and redoes them with Gemini and Groq only (no LLM calls to decide which).

### Supersession

```sh
uv run python -m whycode.graph.supersession --repo psf/requests --dry-run   # pairs, 0 LLM calls
uv run python -m whycode.graph.supersession --repo psf/requests
```

Pairs an older decision with a newer one on the same code (or the same file with a similar
summary), asks the LLM whether the newer one replaces, refines or reverses it, and writes a
`SUPERSEDES` edge only when the verdict cites the newer decision's own evidence. Statuses are then
recomputed (SUPERSEDED or PARTIAL), so query 5a shows only what governs the code today. Running it
twice changes nothing.

## Whole-repository code map and history (no LLM)

```sh
uv run python -m whycode.ingest.codemap --repo psf/requests --dry-run           # read and count only
uv run python -m whycode.ingest.codemap --repo psf/requests --target test       # local container
uv run python -m whycode.ingest.codemap --repo psf/requests --since 2020-01-01  # bounded history
```

Clones or updates the repository in `cache/repos/<owner>/<name>` (gitignored), parses every
`.py` file at the default branch's HEAD into File, Class, Function, ConfigKey and Module nodes,
and reads `git log` into Commit nodes linked by REFERENCES (to the PR in a "(#N)" or "Merge pull
request #N" subject), REVERTS and MODIFIES `{added, removed}`. File `aliases` hold earlier paths
(`requests/sessions.py` -> `src/requests/sessions.py`), and history under an old path counts for
the file it became. Writes are MERGE only and never touch decisions, so a re-run changes no
count. psf/requests takes about 7 seconds to read: 37 files, 826 code entities, 6,496 commits.

## Local model (optional)

A model served by [Ollama](https://ollama.com) on this machine can extract too. It costs no API
calls and has no rate limits, but it is much weaker (on PR 5797 it found 1 decision where the
hosted models found 12), so it is the last resort: it answers only when no hosted provider can,
and `--redo-fallback` replaces its answers later:

```sh
ollama pull qwen2.5:7b-instruct                  # about 4.7 GB
# in .env: LOCAL_LLM_MODEL=qwen2.5:7b-instruct   and optionally LLM_PROVIDERS=local,gemini,groq
uv run python -m whycode.extract.run --repo psf/requests --pr 5797 --providers local
```

Local calls do not count against `LLM_MAX_CALLS`. When that budget is spent, the hosted APIs are
skipped and the local model still answers.

On an RTX 40-series laptop GPU, Ollama's CUDA 13 backend can crash while loading
(`exit status 0xc0000409`, "CUDA error: shared object initialization failed" in Ollama's
server.log). Setting the environment variable `OLLAMA_LLM_LIBRARY=cuda_v12` before Ollama starts
makes it use its CUDA 12 backend, which works.

## API

```sh
uv run uvicorn whycode.api.app:app --reload --port 8000                # Aura, from .env
WHYCODE_GRAPH_TARGET=test uv run uvicorn whycode.api.app:app --port 8000  # local test Neo4j
```

`WHYCODE_GRAPH_TARGET` (`aura` by default, or `test`) is read from the process environment, not
from `.env`. The test target expects the PR 5797 slice in the docker-compose Neo4j:
`uv run python -m whycode.slice --repo psf/requests --pr 5797 --target test --max-calls 0`.

Every path is under `/api` and matches `frontend/src/api/types.ts`; a unit test fails if the
models drift from it. CORS allows the Vite dev server (`http://localhost:5173`). `/ask` scores
confidence from five factors (entity match 0.25, evidence directness 0.25, independent sources
0.20, supersession resolved 0.15, citation pass 0.15) and answers at 0.70 or more, hedges from
0.40, and refuses below. A question whose best search match is below 0.5 is refused outright,
with the closest items listed to pick from, so it is never answered about the wrong code.
Flagged gaps go to the Postgres table `gaps`. `/repos/check`, `POST /repos`, `/repos/sync`,
`/repos/reingest`, `/ingestion` and `/evaluation` return 501 for now.

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
  ingest/          GitHub fetch -> Postgres raw cache; PR selection, jobs, the batch runner
  graph/           Neo4j driver wrapper, schema runner, MERGE-only writers, supersession
    schema.cypher  the graph contract (source of truth)
  code/            tree-sitter parser: files, classes, functions, config keys
  extract/         LLM decision extraction (prompt + pydantic models)
  llm/             llm_client: Gemini/Groq, cache, call budget, retries
  api/             FastAPI for the screens (the frontend contract)
  agent/           later phases
tests/  unit/  integration/  e2e/  fixtures/
scripts/
frontend/          the screens (React + Vite); see frontend/README.md
```

## Frontend

```sh
cd frontend
npm install
npm run dev        # http://localhost:5173 on sample data; set VITE_API_URL=/api to use the API
npm test
```

`frontend/README.md` lists the screens and the API endpoints they call.

Every node carries a `repo` property and every id is prefixed with the repo, so several repositories
can live in one graph without colliding.
