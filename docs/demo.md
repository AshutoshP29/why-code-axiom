# WhyCode demo script (about 4 minutes)

Every step below was checked on the live graph (psf/requests on Aura) on 2026-10-30.

## Before recording

Use PowerShell, not Git Bash: Git Bash rewrites `/api` into `C:/Program Files/Git/api` and the
screens then say they cannot reach the API.

```powershell
docker compose up -d                                         # Postgres (gap flags)
uv run uvicorn whycode.api.app:app --port 8000               # API on Aura (.env)
cd frontend; $env:VITE_API_URL="/api"; npm run dev           # http://localhost:5173
```

If a screen says the graph is not reachable, resume the free Aura instance in the Aura console.
Open http://localhost:5173 once before recording so the first load is not on camera.

## 1. The problem (20 s) - Home

"Code tells you what it does, not why. The why lives in pull request discussions nobody reads
again. WhyCode turns a repository's history into a graph of decisions, each tied to the exact
words that justify it."

Point at the counts: 181 decisions from 62 of the most discussed PRs, 261 evidence links,
1,583 code entities, 3 superseded decisions.

## 2. A real answer with its evidence (60 s)

Type: **Why does apparent_encoding use charset_normalizer instead of chardet?**

- "Matched to Response.apparent_encoding": search found the code from the question.
- The decision: chardet is LGPL, so it was replaced with MIT-licensed charset_normalizer,
  decided 2021-07-06 in PR #5797. Proposed by @ashb, approved by six maintainers.
- Chain of evidence: the PR description and the comment where the new library's ~80%
  compatibility was measured. Click one: it opens the exact GitHub comment.
- "Why 94%?": the five confidence factors. Who to ask: real people, active or not.

## 3. The newer decision wins (50 s)

Type: **Why does resolve_redirects strip the body after a redirect?**

- Active decision from PR #3757 (2016-12): strip bodies only when the method changed to GET.
- Badge "Supersedes 1 earlier" and the yellow box: the PR #3493 rule from four months earlier
  is shown as history only, never as the current answer.
- Click "Decision history": the timeline from 2014 to 2016, with ACTIVE, PARTIAL (refined) and
  SUPERSEDED (struck through) decisions, and every commit that touched the function.

## 4. It refuses instead of guessing (50 s)

Type: **Why does Response.text guess the encoding?**

- "No recorded decision", confidence 19%. It does not invent a reason.
- "What the graph does know": the commits that changed it (facts, not reasons), and the last
  person who changed it, to ask.

Then type: **What is the capital of France? asked via requests packages**

- Refused: nothing in the code clearly matches, so it will not pretend the question is about
  some file it vaguely resembles.

## 5. How we know it works (30 s) - Graph health, then docs/evaluation.md

- Graph health: the ingestion stages and counts.
- From `docs/evaluation.md` (measured with `scripts/evaluate.py`, no LLM calls):
  - 261 of 261 cited quotes found word for word in the original GitHub text.
  - 73 of 73 answers link every evidence step to its source.
  - 481 of 481 questions about code no decision explains were refused, facts only.
  - 10 of 10 off-topic questions refused.
  - 72 of 76 questions naming code matched the right item (the rest: same name in another
    file).

## 6. Close (10 s)

"The graph holds the answer, the model only words it, and when the history does not say,
WhyCode says so."

## If something goes wrong on camera

- "Could not reach the WhyCode API": the API is not running, or the page was started from Git
  Bash (see above).
- A 503 about the graph: resume Aura in its console and reload.
- Do not re-run `python -m whycode.graph.supersession` before recording: one wrong verdict was
  removed by hand and a re-run would add it back from the cache.
