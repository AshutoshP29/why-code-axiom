# Frontend QA report

Date: 26 Oct 2026. Branch: `saanvi/frontend-qa`. Data: the built-in sample data, plus a fake
backend for the API tests. No real backend exists yet.

## Result

| Check | Where | Result |
|---|---|---|
| Unit and screen tests | Vitest, simulated browser, 12 files | **72 / 72 pass** |
| User journeys from the flow chart | Edge, Chrome, phone (Pixel 7 emulation) | **36 / 36 pass** |
| Accessibility scan, WCAG 2.1 A and AA (axe-core) | 8 pages + 5 dialogs and states, Edge and Chrome | **26 / 26 pass, 0 violations** |
| Keyboard-only use | Edge, Chrome | **16 / 16 pass** |
| Edge cases | Edge, Chrome | **20 / 20 pass** |
| Layout: no sideways scrolling, full-page screenshots | 7 pages on Edge, Chrome and phone | **21 / 21 pass** |
| Real HTTP client against a fake backend | Edge | **6 / 6 pass** |
| Type check, lint, production build | | pass |

Final browser run: 125 of 125 passed, none needed a retry.

## Bugs found and fixed

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

## Pages added in this pass

- **Evaluation** (`/evaluation`, linked from Graph health): every labelled question, the right
  response (answered, superseded or no record), and each system's result, with a filter. Until
  the real test is run, it shows 8 sample questions marked as placeholders.
- **Ingestion stopped**: when a repository's ingestion ends in an error, Home shows where it
  stopped and why, with "Run it again" and "Ask about what was read".

## What each suite covers

- **Journeys** (`e2e/flows.spec.ts`): ask from Home; an example chip leading to a refusal, a
  flag, the gap queue and Evaluation; a hotspot leading to lineage, all three "View as of" years,
  a decision, the workspace, and Back retracing; re-asking from a graph node; copying the
  maintainer message; switching repo; asking during ingestion; adding a repo and watching it
  progress; exporting the health report; re-running ingestion; reloading a deep link; bad
  addresses and unknown items.
- **Edge cases** (`e2e/edge-cases.spec.ts`): HTML and emoji in a question are shown as text and
  never run; a 2,000-character question; a blank question; double-clicks; fast "View as of"
  switching; searches with no match; pasted GitHub links; adding a repo twice; non-GitHub links;
  Back and Forward.
- **API** (`e2e/api.spec.ts`): requests carry the repo and graph ids; a 503 shows the server's
  reason and recovers on retry; an unreachable backend is explained; a slow answer shows loading;
  unknown items show the API's reason; flags send the right body.

## Not covered

- Firefox and Safari: only Chromium browsers (Edge, Chrome) are installed on this machine.
- A real screen reader (NVDA, VoiceOver): the automated scan and keyboard tests catch a lot, but
  not everything a person would notice.
- Real phones: the phone runs use Chrome's Pixel 7 emulation.
- The real backend: the screens are tested against the sample data and a fake API that follows
  `src/api/types.ts`.
- A pixel-by-pixel comparison with Figma: the screenshots in the HTML report are for a person to
  compare by eye.

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
