# WhyCode frontend

The screens for WhyCode, built from the Figma designs and the user-flow chart: pick a code item,
ask why, and get a page of evidence instead of a chat reply.

React 19, TypeScript, Vite, Tailwind CSS 4, React Router, TanStack Query. Tests use Vitest and
Testing Library.

## Run it

```sh
cd frontend
npm install
npm run dev            # http://localhost:5173, on sample data
```

With no API configured, the app runs on **sample data** (`src/api/sample.ts`) and shows a
"Sample data" badge in the top bar. Every flow in the user journey works this way, including
flagging gaps and adding a repository (a simulated 45-second ingestion).

To use the real backend, start the FastAPI app on port 8000 and point the frontend at it:

```sh
VITE_API_URL=/api npm run dev                  # macOS / Linux / Git Bash
$env:VITE_API_URL="/api"; npm run dev          # Windows PowerShell
```

`/api` goes through the Vite dev proxy to `http://localhost:8000`, so no CORS setup is needed in
development. An absolute URL such as `http://localhost:8000/api` also works.

```sh
npm test               # unit and screen tests (no network)
npm run e2e            # browser tests in Edge, Chrome and a phone emulation (see QA.md)
npm run e2e:report     # HTML report of the last browser run, with page screenshots
npm run lint           # oxlint
npm run typecheck      # tsc
npm run build          # production build in dist/
```

`QA.md` has the latest QA results, what was fixed, and what is not covered yet.

## Screens and routes

| Screen | Route | Notes |
|---|---|---|
| Home | `/` | Hero ask bar, example chips, four counts, hotspots, "What you will see". Shows the ingestion screen instead while the selected repo is still being read. |
| Why Workspace | `/why?entity=<id>&q=<question>` | Verdict and confidence, amber banner for overridden rules, four-step evidence chain, graph neighbourhood, who to ask, why this confidence. |
| Refusal | same route | Shown when the API refuses (confidence below the threshold): facts kept apart from reasons, related items, ask the owner, open commit history, flag as missing context. |
| Decision lineage | `/lineage?entity=<id>&asof=<year>` | Superseded, partial and active decisions in order, with "View as of" time travel and every commit linked to a decision or marked as having none. |
| Graph health | `/health` | The five ingestion stages, graph contents, evaluation table, gap queue, export and re-run. |
| Evaluation | `/evaluation?expected=<outcome>` | Every labelled question, its right response, and each system's result. Not in the designs; it backs "How we will prove it" in the architecture doc. |
| Explore | `/explore?file=<id>` | File tree plus search. Not in the designs yet, so it reuses the Explorer sidebar. |
| Repo switcher, Add repository, Ingestion | top bar and Home | Switch repos, check a GitHub link before ingesting, follow progress. If ingestion stops with an error, Home says where and why and offers a re-run. |

All state is in the URL, so any answer can be shared as a link.

## The API the screens expect

The contract is `src/api/types.ts`; `src/api/http.ts` is the client. In short:

- JSON field names are **snake_case**, as FastAPI returns them.
- Every call is **scoped to one repo** (`repo=psf/requests`), matching the graph rule that every
  query filters on `repo`.
- Ids are the graph ids from `whycode/ids.py`, for example
  `psf/requests#fn:src/requests/sessions.py::Session.rebuild_auth`. They are URL-encoded in query
  strings.
- Errors return an HTTP error status with a FastAPI `{"detail": "..."}` body; the detail is shown
  to the user, so it must never contain secrets.

| Method | Path | Input | Returns |
|---|---|---|---|
| GET | `/repos` | | `Repo[]` |
| POST | `/repos/check` | `{input}`: a GitHub link or `owner/name` | `RepoCheck` |
| POST | `/repos` | `{repo, keep_updated}` | `Repo` |
| POST | `/repos/sync` | `{repo}` | `Repo` |
| POST | `/repos/reingest` | `{repo}` | `Repo` |
| GET | `/ingestion` | `repo` | `Ingestion` |
| GET | `/overview` | `repo` | `Overview` |
| GET | `/explorer` | `repo` | `Explorer` |
| GET | `/entities/search` | `repo`, `q` | `EntityMatch[]` |
| GET | `/entities` | `repo`, `id` | `Entity` |
| POST | `/ask` | `{repo, entity_id, question}` | `Answer` (`verdict: "answered"` or `"refused"`) |
| GET | `/lineage` | `repo`, `entity_id`, optional `as_of` (`YYYY-MM-DD`) | `Lineage` |
| GET | `/health` | `repo` | `Health` |
| GET | `/evaluation` | `repo` | `Evaluation` (summary plus every labelled question) |
| POST | `/gaps` | `{repo, entity_id, question}` | `Gap` |

Points worth knowing when building the backend:

- **Refusal is the API's decision.** The screens never guess: `verdict: "refused"` brings up the
  refusal screen, with `threshold` (0.4 in the designs) shown next to the score.
- **The LLM only words `answer_text`.** Everything else on the Why Workspace comes from the graph:
  the decision, its `source`, each evidence step's `source.url`, people, and confidence factors.
- **Lineage time travel:** `/lineage?as_of=2016-12-31` returns only decisions and commits on or
  before that date. Each decision lists the older decisions it `supersedes` with a kind
  (`reverses`, `replaces`, `refines`). The page works out each card's status *as of that date*
  from those edges (`src/lib/lineage.ts`), using the same rules as `whycode/graph/schema.cypher`:
  `reverses` and `replaces` retire the older decision, `refines` keeps it partly in force.
- **Graph neighbourhood:** set `center` on the node the drawing should hang from (normally the
  current decision), `entity_id` on code items (clicking one asks about it), and `url` on PRs,
  issues and commits (clicking opens them).
- **Evaluation numbers:** send `measured: false` until the 40-question test has really run; the
  pages then mark the numbers as placeholders. A question's result per system is `null` until
  that system has been run on it.
- **Failed ingestion:** set the repo's `status` to `ERROR`, `stage` to where it stopped, and
  `error` to a plain sentence for the user (it is shown as is, so never include secrets).
- **Unreachable API:** the client reports "Could not reach the WhyCode API" itself; other errors
  show the `detail` from the response.

## Layout

```
src/
  api/          types.ts (the contract), http.ts (real API), mock.ts + sample.ts (sample data),
                queries.ts (TanStack Query hooks), context.ts (which API is in use)
  state/        the selected repository, shared by every screen
  components/   top bar, ask bar, repo switcher, dialogs, evidence chain, graph, shared UI
  pages/        one file per screen
  lib/          formatting, routes, lineage status rules, colour roles
  index.css     design tokens from Figma (colours, fonts); change values here, not in components
```
