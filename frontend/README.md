# WhyCode frontend

The screens for WhyCode, built from the Figma designs and the user-flow chart: ask why about a
code item (or just type the question), and get a page of evidence instead of a chat reply.

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

On sample data, a question asked with no entity picked is matched by the words it shares with
entity names (`src/api/mock.ts`). Three to try from the Home ask bar:

- "why does rebuild_auth strip the header?": matched to `Session.rebuild_auth`, answered
- "why is there no default timeout?": matched to `timeout`, hedged
- "why did requests drop chardet?": nothing matches, so it is refused with no entity

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
| Home | `/` | Hero ask bar (pick an entity, or just type a question), example chips, four counts, hotspots, "What you will see" with all four outcomes. Shows the ingestion screen instead while the selected repo is still being read. |
| Why Workspace | `/why?entity=<id>&q=<question>`, or `/why?q=<question>` with no entity | Verdict and confidence with both thresholds, amber banner for overridden rules, evidence chain, graph neighbourhood, who to ask, why this confidence. For a plain question, a line says which entity the API matched, with a picker to ask about a different one. |
| Hedged answer | same route | Shown when the API hedges (confidence between the two thresholds): the full answer, plus an amber warning with the backend's reason and the weak factors, a "Low confidence" badge, and the weak factors first under "Why only". |
| Refusal | same route | Shown when the API refuses (confidence below the refuse threshold): facts kept apart from reasons, related items, ask the owner, open commit history, flag as missing context. If a plain question matched nothing, there is no entity header or flag; a picker offers to ask about a specific item. |
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
| POST | `/ask` | `{repo, entity_id, question}`; `entity_id` is `null` when nothing was picked | `Answer` (`verdict: "answered"`, `"hedged"` or `"refused"`) |
| GET | `/lineage` | `repo`, `entity_id`, optional `as_of` (`YYYY-MM-DD`) | `Lineage` |
| GET | `/health` | `repo` | `Health` |
| GET | `/evaluation` | `repo` | `Evaluation` (summary plus every labelled question) |
| POST | `/gaps` | `{repo, entity_id, question}` | `Gap` |

Points worth knowing when building the backend:

- **The verdict is the API's decision.** Every answer carries `confidence` (0..1) and
  `thresholds: {answer, refuse}` (0.70 and 0.40 today). The API sets `verdict` from them:
  `answered` at or above `answer`, `hedged` from `refuse` up to `answer`, `refused` below
  `refuse`. The screens never compare the numbers themselves; they show the verdict they are given
  and mark both thresholds on the confidence meter, so changing a threshold needs no frontend change.
- **Asking without an entity.** `POST /ask` may send `entity_id: null` (sent as null, not left out).
  The backend then finds the entity itself (full-text search, then vector search over evidence) and
  says how: `matched_by: "search"` and `match_score` (0..1), or `matched_by: "selected"` and
  `match_score: null` when the user picked it. `entity` is the matched item, and is `null` only on a
  refusal where nothing matched; answered and hedged answers always have an entity. The screen shows
  "Matched to Session.rebuild_auth (score 0.82)"; picking a different entity asks again with its
  `entity_id`.
- **Hedged answers** have every field of an answered one plus `warning`: one or two plain sentences
  on why confidence is limited, written from the confidence factors. Factors with `tone: "bad"` are
  the weak ones; the screen lists them in the warning and first under "Why only 55%?".
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
  that system has been run on it. A hedged answer counts as an answer: `outcome` is `answered`,
  or `superseded` when it names the rules it replaced, as for a confident one.
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
