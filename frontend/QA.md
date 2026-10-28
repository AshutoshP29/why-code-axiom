# Frontend QA report

Date: 28 Oct 2026. Branch: `saanvi/ask-and-hedged`. Data: the built-in sample data, plus a fake
backend for the API tests. No real backend exists yet.

This pass covers two contract changes: asking without picking an entity, and the hedged answer
(a full answer under a warning, between the refuse and answer thresholds). The first QA pass,
from 26 Oct, is further down.

## Result

| Check | Where | Result |
|---|---|---|
| Unit and screen tests | Vitest, simulated browser, 12 files | **92 / 92 pass** |
| User journeys from the flow chart | Edge, Chrome, phone (Pixel 7 emulation) | **45 / 45 pass** |
| Accessibility scan, WCAG 2.1 A and AA (axe-core) | 11 pages and answer states + 7 dialogs and open lists, Edge and Chrome | **36 / 36 pass, 0 violations** |
| Keyboard-only use | Edge, Chrome | **20 / 20 pass** |
| Edge cases | Edge, Chrome | **26 / 26 pass** |
| Layout: no sideways scrolling, full-page screenshots | 10 pages and answer states on Edge, Chrome and phone | **30 / 30 pass** |
| Real HTTP client against a fake backend | Edge | **8 / 8 pass** |
| Type check, lint, production build | | pass |

Full browser run: 165 of 165 passed. 160 passed first time. The other 5 were accessibility scans
at the start of the run that hit the 30-second limit (one of them was the Chrome page-load hang
described below), and all 5 passed on retry with no violations. The scans now have 60 seconds,
and a second run of all 36 scans with retries turned off passed.

## What was checked in this pass

- **Asking with nothing picked.** Trace is enabled once there is a question. The request sends
  `entity_id: null`, not a missing field (unit test of the HTTP client, and the fake backend
  checks the body). A blank question with nothing picked cannot be sent. A picked entity can be
  cleared, by mouse or keyboard.
- **Matched by search.** The page says "Matched to Session.rebuild_auth (score 0.90) from your
  question". "Pick a different entity" asks the same question about another item, and Back
  returns to the matched answer. A picked entity shows no match line.
- **Nothing matched.** The refusal still shows the reason and related items, with no breadcrumb,
  no gap flag and no owner, and offers a picker to ask about a specific item.
- **Hedged answer.** Everything a confident answer has (decision, evidence chain, graph, who to
  ask), plus the amber warning with the backend's text and the weak factors, a "Low confidence"
  badge, an amber card and meter, "Why only 55%?" with the weak factors first, and a maintainer
  message that carries the caveat. A test checks a confident answer has none of these.
- **Thresholds from the response.** The meter marks both thresholds and spells them out. With
  other thresholds in the response (unit test, and through the real HTTP client), the page shows
  those numbers. An 87% answer under a 90% answer line still shows as answered, because the
  verdict is the API's.
- **Markup in a plain question** is shown as text and never run.

## Bugs found and fixed in this pass

1. **The hedged answer's amber card border did not show.** `Card` always set the line colour,
   and a border colour passed in competed with it. Tailwind happened to write the amber rule
   first, so the line colour won. The existing teal and red borders only won through the same
   ordering. `Card` now takes a `tone`, which replaces the line colour instead of competing.
2. **A browser test could start before the app had loaded.** `ready()` waited for the repo
   switcher, which is on screen while the repo list is still loading. The focus check then tabbed
   off the end of a page that was still loading and failed. `ready()` now waits for the switcher
   to name a repo.
3. **Accessibility scans timed out on a busy laptop.** The page had loaded fully; the scan itself
   took more than 30 seconds. The limit for scans is now 60 seconds, and the checks are unchanged.

## Not covered

- Firefox and Safari: only Chromium browsers (Edge, Chrome) are installed on this machine.
- A real screen reader (NVDA, VoiceOver): the automated scan and keyboard tests catch a lot, but
  not everything a person would notice.
- Real phones: the phone runs use Chrome's Pixel 7 emulation.
- The real backend, and real search: the screens are tested against the sample data and a fake
  API that follows `src/api/types.ts`. The mock matches a plain question by shared words only,
  not by full-text or vector search, so match quality is not tested here.
- A pixel-by-pixel comparison with Figma: the hedged answer and the match line are not in the
  designs, and the screenshots in the HTML report are for a person to check by eye.

## Running it

```sh
cd frontend
npm test              # unit and screen tests
npm run e2e           # browser tests; needs Edge and Chrome installed, starts its own servers
npm run e2e:report    # open the HTML report with screenshots of every page
```

Browser tests run 4 at a time with one retry. More than 4 browsers at once overloaded a laptop
and made Chrome time out on page loads, which had nothing to do with the app. A test that only
passes on its retry is listed as "flaky" in the report, so it is never hidden.

## First QA pass (26 Oct 2026)

Branch `saanvi/frontend-qa`: 72 unit tests and 125 browser tests, all passing. It also added the
Evaluation page and the "ingestion stopped" state.

Bugs found and fixed then:

1. **Small grey text failed colour contrast on every page** (2.99:1, the rule is 4.5:1). The grey
   is now 4.8:1 on every background, including tinted badges, and red badge text went from 4.2:1
   to 5.0:1. Superseded lineage cards were dimmed with transparency, which also failed; they now
   use a darker background instead.
2. **Screen readers heard different words from what is on screen** on the logo, hotspot links,
   repo switcher and "Who to ask" cards (WCAG 2.5.3). The spoken name now contains the visible text.
3. **Links inside sentences were shown only by colour.** They are now underlined.
4. **The Graph contents list was malformed HTML** for screen readers. Fixed.
5. **Double-clicking "Flag as missing context" sent two flags.** It now sends one.
6. **"Skip to content" did not move keyboard focus.** It now does.
7. **Escape in the repo switcher dropped keyboard focus.** Focus now returns to the switcher button.
8. **"View as of" and the Evaluation filter ignored the arrow keys.** They now work as standard
   radio groups: one Tab stop; arrows, Home and End move the choice.
9. **Graph health and Evaluation scrolled sideways on phones.** Fixed on every two-column page.
10. **An unreachable backend showed the browser's raw "Failed to fetch".** It now says the WhyCode
    API could not be reached and to check the backend is running.
11. **If the repository list failed to load there was no way to retry**, and a failed background
    refresh would have replaced the whole page with an error. There is now a "Try again" button,
    and a failed refresh keeps the list already shown.
