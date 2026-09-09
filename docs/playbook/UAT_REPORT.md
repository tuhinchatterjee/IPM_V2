# Playbook — UAT report

Everything below happened. Nothing is recorded here that did not run, and a
check that could not run is `BLOCKED` rather than a pass.

## Status

| Dimension | State |
|---|---|
| Standalone implementation | **complete** for the scope that does not need a provider |
| Deterministic demo and downloads | **passed** — 3 workspaces, 30 exports, 14 real files |
| Live Claude workflows | **BLOCKED** — no `ANTHROPIC_API_KEY` in this environment |
| Browser and artifact UAT | **passed** — 105 browser checks, 62 artifact checks |
| Cross-module integration | Cockpit, Early Warning, Scorecard Validation, Lenses **verified**; What If **DEFERRED-INTEGRATION** |
| Human UAT | **pending** — the developer cannot award the user's sign-off |
| Git handoff | committed and pushed to the feature branch; **not merged** |

## The one blocker, stated plainly

`ANTHROPIC_API_KEY` is not set in this environment and no `.env` carries one.
The authoring runtime is implemented, and everything around it — evidence
assembly, grounding, rendering, validation, versioning, idempotency — is tested
against a scripted provider. **That is not live verification and is not reported
as though it were.**

`scripts/playbook_live_slice.py` exists to close this the moment a key does.
Run without one it prints the reason and exits **2**, never 0:

```
CANNOT RUN: ANTHROPIC_API_KEY is not set. …
Live generation is therefore UNVERIFIED, not passed.
```

Six of the forty-five requirements are BLOCKED on this and only this:
PB-013, PB-015, PB-017, PB-029, PB-030, PB-043.

PB-016 is **PASS**. Deciding a numbered proposal — approving some changes and
holding others, with stable ids that survive a reload and a dependency that is
explained rather than resolved quietly — is implemented, tested at three levels
and driven through a real browser. What still needs a provider is *applying* the
resulting instruction to a document, and that is the same blocker as PB-015.

## Test counts

| Suite | Command | Result |
|---|---|---|
| Playbook backend | `pytest tests/playbook` | **318 passed** |
| Affected backend | `pytest tests/playbook tests/demo tests/api tests/services` | **830 passed** |
| Full backend | `pytest -q` | **9759 passed, 22 skipped, 0 failed** |
| Frontend units | `npm test` | **462 passed, 0 failed** |
| Frontend types | `tsc --noEmit` | clean |
| Frontend lint | `eslint` | clean |
| Frontend build | `next build` | succeeds; `/playbook`, `/playbook/[id]`, `/playbook/library` emitted |
| Python lint | `ruff check .` | clean repository-wide |

## Browser acceptance

`scripts/acceptance/playbook_browser_acceptance.py` — real Chromium, real front
end, real backend, at 1366×768 and 1600×900. **105 passed, 0 failed.**

What it proved, rather than what it looked at:

- The home screen is in §3's order — the composer above Recent Playbooks above
  Recent Exported Analyses — measured by bounding box, at both viewports.
- The plus button is inside the composer and its menu offers exactly two
  sources.
- A quick prompt fills the composer and **generates nothing**.
- A seeded thread reopens with all 14 of its messages, labelled synthetic.
- The DOCX and PDF downloads are real bytes with the right magic numbers
  (39,189 and 4,361 bytes), not renamed text.
- The picker lists 30 exported analyses; previewing one and coming back leaves
  the selection at "2 selected".
- Escape closes the dialog; no console errors at either viewport.
- A real .docx uploads through the composer, appears as a chip and can be
  removed; with no provider configured Send is refused and the reason is on
  screen, rather than a button that fails after it is pressed.
- An earlier version is restored from the files pane and the restore moves
  forward: v1 comes back as v3, v2 is still there, the change summary says
  where v3 came from, the downloaded file is byte-for-byte the file that was
  reviewed as v1 under a v3 filename, and restoring the version already current
  is refused.
- The answer arrives while it is being written: a page attached to a running
  generation shows what has been written so far, text written on the server
  afterwards appears without a reload, the state moves from "Reading the
  sources" to "Writing" as the work moves, and the Markdown is rendered rather
  than printed as source.
- A refresh mid-generation keeps the answer so far and starts no second
  generation — the same job id is still the one running — and no answer is in
  the thread while the stream is unfinished.
- Stop mid-stream marks the running generation cancelled, the screen says it
  was stopped rather than leaving the half sentence on display, and no artifact
  version was written.
- A source's kind is a control rather than a fixed label: correcting it is
  recorded as a person's decision, reaches the database, survives a reload, and
  a kind that is not one of the five is refused.
- Any version can be read in the application without downloading it, and the
  preview offers the file rather than replacing it. Escape closes it.
- A five-item proposal is decided in the interface: changes 1, 2 and 5 are
  approved and 3 and 4 held; ticking change 3 pulls in change 2, which it rests
  on, rather than accepting an approval that could not stand; the resulting
  instruction names the approved sections and names the held ones as held; and
  after a reload the panel still says the same thing.
- The API refuses an id that was never exported (404), a foreign workspace
  (404), a greeting as an export (422) and Project Planner as a module (422).
- The monitoring Playbooks feature still answers 200.

Screenshots: `docs/playbook/screenshots/`. Evidence:
`docs/playbook/browser_acceptance.json`.

## Artifact verification

`scripts/acceptance/verify_playbook_artifacts.py` — **14 files, 62 checks, 0
failed.**

Every file was reopened with the same parsers Playbook uses on user uploads and
checked against the document it was rendered from. Every PDF page was rasterised
and inspected for blankness, collapse, content past the margin, and missing
fonts. Rendered pages: `docs/playbook/artifact-pages/`.

## The demonstration

| | |
|---|---|
| Workspaces | 3 — IFRS 9 Committee Report, Application Scorecard Model Development Report, Behavioural Scorecard Validation Report |
| Messages | 12, 14 and 14 |
| Input files per workspace | 3, all parsed through the real ingestion |
| Attached analyses | 5, 4 and 5 |
| Versions per report | 2, with different content hashes and a parent link |
| Generated files | 14 (DOCX, PDF, PPTX) |
| Exported analyses | 30 — six each from Cockpit, Early Warning, What If, Scorecard Validation and Lenses |

The IFRS 9 thread carries a five-item change proposal with **four applied and
one held back**, and version 2 does not contain the held change.

## Journeys

| Journey | State |
|---|---|
| 1 — Home and seeded history | **passed** (browser acceptance) |
| 2 — Picker and export boundary | **passed** (browser acceptance + API boundary) |
| 3 — Prior report + methodology + new results | **partial** — sources with correctable roles, the gap manifest and partial approval all verified in the browser; the coverage framing sent to the author is asserted; running the review is BLOCKED |
| 4 — No-template report | **BLOCKED** — needs the live path |
| 5 — Continue, revise, present | **partial** — versions, lineage, restore, the in-app preview and a real PPTX verified; the scoped-edit framing and the current document sent with every revision are asserted; performing the revision is BLOCKED |
| 6 — Fail safely | **passed** — provider-not-configured, validation failure, stale base, duplicate send, cancellation |
| 7 — Authorization and untrusted content | **passed** — 29 security tests plus the API boundary |
| 8 — Regression and fresh state | **passed** — isolated database, idempotent reseed, edited thread preserved |

## Defects found and fixed during verification

1. **Thirty exports collapsed into five.** With no source identifier, every
   export in a module resolved to the same identity and became a *revision* of
   its predecessor. Found by writing the status check. Fixed: the title is now
   the fallback discriminator.
2. **AUC below 0.5.** The first scorecard fixture used a hand-rolled binary
   search that was wrong, making Gini negative. Found by its own test. Fixed by
   using the standard library.
3. **Source locators read as reported figures.** `fixture://…@1.0.0` put "0"
   into the figure set, so every references appendix failed validation. Fixed:
   locators are stripped before figures are extracted, on both sides.
4. **Live verification call estimates.** Adding the AUTHOR role moved quick mode
   from 15 provider calls to 16; the PowerShell mirror still said 15. Caught by
   `test_the_cost_table_matches_the_python_side`.
5. **Test isolation.** The first Playbook DB fixture committed. Now each test
   runs in a rolled-back transaction, and the API tests remove what they create.
   Two consecutive full runs leave zero rows.
6. **A test suite that wiped the demonstration.** The API tests shared the
   developer's database with the seeded workspaces and cleaned up by truncating
   the Playbook tables, so running them destroyed the demonstration they were
   testing against. Found when the browser acceptance reported nought seeded
   playbooks. Fixed: the tests record a high-water mark and delete only above
   it.
7. **A stale acceptance assertion.** The browser check looked for the word
   "Demo" on the thread page. The product-copy rule forbids that word, so the
   label a user sees is "Synthetic data" — the check was asserting the copy the
   repository bans. Fixed to assert both the badge and the per-message note that
   the reply was not written by a model.

## What is genuinely not done

1. **Every live behaviour.** No `ANTHROPIC_API_KEY` in this environment.
   Six requirements BLOCKED on it and nothing else.
2. **Nothing about streaming.** Implemented end to end and verified in a real
   browser. Still no percentage anywhere, because there is still no honest
   basis for one.
3. **What If.** DEFERRED-INTEGRATION — the module does not exist here.
4. **CI.** GitHub Actions has never run on this repository, before or after any
   push on this branch. Everything above was run locally.

## What streaming is proven with, and what it is not

The browser journey drives a real SSE connection, the real parser and the real
incremental rendering, against events a fixture writes on the server. That
proves the **transport** and everything around it — replay, reconnect, refresh
safety, cancellation, the refusal to show a partial answer as an answer.

It is not a live generation, and is not recorded as one. With no credential in
this environment no model can be asked for anything; what a real provider adds
to the path above is `text_delta` events instead of fixture ones. The filter
that decides which of the provider's events may be forwarded is asserted
directly in `tests/playbook/test_streaming.py`, and the live slice exercises the
whole path the moment a key exists.

## Known limitation, stated rather than discovered later

**Grounding proves traceability, not truth.** A figure survives because it
appears in the evidence — and an uploaded document is evidence. A source
asserting "coverage is 41.5 per cent" makes that figure quotable, and a report
citing it is behaving correctly even if the source is wrong. What grounding
removes is the figure that came from nowhere. This is asserted by a test rather
than left implicit.
