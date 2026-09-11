# Retail full-functionality acceptance — honest status

> **This is the Revision 2 report. It is superseded in three places by
> `docs/RETAIL_REVISION_3_ACCEPTANCE.md`:**
>
> * **CP-10 / Customer 360 is no longer BLOCKED.** The screen reads the retail
>   book and the full Early Warning → customer → facilities/history → Back
>   journey passes in a browser (C360-01…C360-10).
> * **The SAR 0.52 What-If residual is closed, and the explanation below is
>   wrong.** The rebuild was rounding the weighted allowance where the build
>   does not; the residual is now exactly zero and the tolerance is unchanged.
> * **Coverage is larger.** 164 browser cases across 10 suites, reconciled by
>   operation class rather than by control count. The matrix is now 190 rows —
>   189 PASS, 1 N/A, **0 BLOCKED** — and the corporate surfaces this report did
>   not reach have been found and retired.
>
> Everything else below stands as written.

Branch `claude/funny-dirac-6n8f0o`. Every figure below was
produced by running the thing it describes; nothing is estimated.

## The answer to the question that was asked

**Both chat boxes work through the running application.** Not through an API
test: through Chromium, signed in, clicking the same controls a credit officer
clicks, against the frontend and backend the retail launcher serves.

Neither of them worked when this closeout began.

* The **Cockpit** chat could not plan a single retail question. Its concept
  registry, its dimensions, its periods and its default dataset all still
  pointed at the corporate book this conversion retired, so every question came
  back as "Which figure should CreditProbe measure?" — offering "internal
  rating".
* The **What-If** chat was the corporate module: its landing endpoint reported
  "CORPORATE IFRS 9" with an empty period list, and its prompts offered rating
  notches and BBB borrowers. There was no retail What-If screen at all.
* And before either could be reached, the application was unusable in a
  browser: the launcher pointed the page at a different host from the one it
  opened, so the session cookie was withheld and every authenticated call
  answered 401 while the backend was perfectly healthy.

## What was run, and what it found

| Suite | Result | Time | Evidence |
|---|---|---|---|
| Route and control inventory (RUI-001…RUI-025) | 26 passed | 111s | `inventory.json`, `inventory_controls.json` |
| Cockpit chat CHAT-01…CHAT-18 | **19 passed, 0 failed** | 120s | `cockpit_chat.json` |
| Cockpit journeys CP-01…CP-15 + the five-turn conversation | **16 passed, 1 BLOCKED** | 162s | `cockpit_journeys.json` |
| What-If chat CHAT-01…CHAT-18 equivalents, WI-01…WI-08, WI-15, WI-17 | **14 passed, 0 failed** | 78s | `whatif_chat.json` |
| What-If journeys WI-09…WI-14, WI-16, WI-18…WI-20 | **12 passed, 0 failed** | 112s | `whatif_journeys.json` |
| Navigation NAV-01…NAV-10 | **10 passed, 1 N/A** | 101s | `navigation.json` |
| End-to-end, fresh and resumed sessions | **3 passed** | 78s | `end_to_end.json` |
| Acceptance gates RET-001…RET-060 plus the closeout regressions | **416 passed, 0 failed, 0 errors** | ~9 min | `docs/evidence/gates.log` |
| — of which, regressions added by this closeout | 56 | — | `tests/retail/test_ret_chat_regressions.py`, `test_ret_034_038_ews.py` |
| Frontend unit suite | 573 passed | 9s | `npm test` |

All evidence is under `docs/evidence/retail_functionality/`, with a screenshot
for every case in `screens/`.

**Thirty-seven defects** were found this way. Thirty-five are fixed, each with
a regression test and a re-run of the browser journey that found it; one is open
with its tolerance declared and stated on screen; one is blocked. They are
listed individually, with what the user saw, in
`docs/RETAIL_FUNCTIONAL_DEFECTS.md`.

## Coverage, counted honestly

`docs/RETAIL_FUNCTIONALITY_MATRIX.csv` — 127 rows: **125 PASS, 1 BLOCKED,
1 NOT APPLICABLE**. Twenty-five routes were opened and read in the browser;
they carry 342 buttons, 11 inputs, 6 selects, 37 tabs and 1 table.

What that does and does not mean:

* Every route the navigation offers was **opened and inventoried**, and its
  controls recorded from the rendered DOM rather than from the source.
* Every control on the **Cockpit**, the **What-If** screen, the **conversation**
  and the **Trace** was exercised in a journey — including the ones that write:
  save, export in both formats, compare, delete, clear.
* Controls on modules outside the retail demonstration path — Projects,
  Delivery, Documents, Playbook, Lenses, Agent Operations, AI Studio — were
  **inventoried but not individually exercised**. They are counted as
  inventoried, not as tested, and this document does not claim otherwise.

## The deterministic reader — a NOT RUN that must stay stated

This installation reports **"No AI provider is configured"**. Every question in
every suite was read by the deterministic governed semantic reader and every
figure computed in the governed runtime. Per §10.4 that is an honest test of the
production fallback and **it is not a live-provider pass**. The model-written
half of an answer — the prose and the interpretation — is **NOT RUN**.

## Blocked, and not passed some other way

* **CP-10 — Customer 360.** The route renders the previous module's layout and
  offers no retail customer to open. The retail position exists at
  `GET /api/v1/retail/customer/{id}`; passing the case against that endpoint
  would be answering a different question.
* **The frozen 5318 and 5308 installations.** Nothing in this work touched
  them: no file outside this worktree was written, and the retail backend runs
  on its own port, its own database and its own lake
  (`data/retail/analytics`, `metadata/retail`, PostgreSQL on 55432).
* **A local Mac.** This ran on Linux in a container. The launcher
  `launchers/retail/start-retail.command` is a macOS double-click script and
  was **not executed on a Mac**; its two defects were found by reproducing its
  environment exactly. Running it on the user's machine is NOT RUN.

## Alert usability

RET-EWS-011 named 3,377 of 14,251 customers — 23.7% of the book — at HIGH
severity, because it compared today's debt burden against the burden at
origination. Every alert was true and none was a deterioration. It now compares
against the prior month: **386 customers, 2.7%**. The full before-and-after,
at every threshold worth considering, is in `docs/RETAIL_EWS_011_REVIEW.md`.

## The one-time setup

`.venv/bin/python scripts/bootstrap_retail_installation.py` is guarded — it
refuses any database or metadata directory that is not this installation's — and
idempotent. Run twice in succession during this closeout; the second run changed
nothing and exited 0.

## Numerical reconciliation

Every figure asserted in a browser case was reconciled independently against
the Parquet lake first:

| Figure | Product | Independent read |
|---|---|---|
| Gross carrying amount, whole book at 2026-08 | SAR 2,082,852,856 | SAR 2,082,852,855.82 |
| Facilities / customers at 2026-08 | 19,745 / 14,251 | identical |
| Personal finance GCA, 2026-07 → 2026-08 | 453,309,241 → 463,168,890 | identical |
| Final ECL, whole book, 2026-07 → 2026-08 | 14,069,608 → 15,952,109, +13.38% | identical |
| Personal finance ECL movement | +981,593.19 | decomposition attributed 981,593.19 — exact |
| PD +20% relative on personal finance | 8,994,012 → 10,161,669, +12.98% | matches the turn-1 engine evidence |
| PD +2pp on personal finance | → 15,088,559, +67.76% | a different operation, as it must be |
| Neutral What-If parity | residual SAR 0.52 on SAR 8,994,011.87 | 5.8×10⁻⁸, inside the declared tolerance |

## Final acceptance status

**ACCEPTED FOR DEMONSTRATION, with one blocked case and one declared
tolerance.**

The two things §10.1 called release gates — the Cockpit chat and the What-If
chat, working through the running application — are met, with separate evidence
for each and a screenshot per case. Return navigation is complete: no screen in
the retail path traps a reader, browser Back and Forward behave, and the month,
filters, conversation, result and scenario survive a return.

What this is **not**: it is not SAMA compliant, not ANB approved, not auditor
certified, and not an independent model validation. The data is synthetic, the
scorecards are not any real institution's models, and every threshold is a
demonstration setting. No claim in this document depends on a test that was not
run, and every test that was not run is named above.
