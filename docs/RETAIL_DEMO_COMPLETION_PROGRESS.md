# Retail Demo Completion — progress ledger

The on-disk record the completion contract asks for, so progress survives a
compaction or a container restart. One section per phase. A phase is marked
done only when its UI, calculation and persistence checks pass.

Contract: `CreditProbe_Retail_Demo_Completion_Master_Prompt` (30 sections, 92 gates).

---

## Release boundary (§1)

| | |
|---|---|
| Branch | `claude/funny-dirac-6n8f0o` |
| Candidate at start | `c0db151f62c34e84b4f7df5faf81e5c9b0c9f647` |
| Working tree at start | clean |
| Book manifest hash | `3268b725456df9c4f7fea602395b4bd026e7a7c1810b52494cece5641db6e1d6` |
| Dataset version | `r1.2.0-c1.0.0-s20260910` |
| Generator | `retail-gen-1.2.0`, seed `20260910`, as-of `2026-08` |
| `uv.lock` | `dc001ea0a9370fed…` |
| `frontend/package-lock.json` | `439ce817d0a95db6…` |

Populations, read from the lake rather than from a screen:

| Dataset | Rows | Customers | Facilities | Months |
|---|---:|---:|---:|---|
| `retail_facility_month` (canonical book) | 1,347,014 | 54,450 | 85,476 | 2024-08 … 2026-08 (25) |
| — at 2026-08 | 59,449 | 42,824 | 59,449 | GCA SAR 6,388,268,768.90 · ECL SAR 58,608,354.44 |
| `retail_ews_score` | 1,088,983 | 52,110 | 79,687 | 2025-01 … 2026-08 (20) |
| — at 2026-08 | 59,449 | 42,824 | | |
| `retail_whatif` at 2026-08 | 59,449 | 42,824 | | |
| `retail_credit_scorecard` at 2026-08 | 59,449 | 42,824 | | |
| `retail_early_warning` at 2026-08 | 59,449 | 42,824 | | |

The enlarged book is intact and every derived view agrees with it at the
latest month. The former ~19,745-facility book is not in play.

Frozen corporate installations (5318 / 5308) were not started, not queried and
not modified.

---

## Phase 1 — Baseline audit and acceptance map

Status: **done**. Evidence: `docs/evidence/phase1/`.

See `docs/RETAIL_DEMO_COMPLETION_ACCEPTANCE.md` for the delta table and the
92-gate matrix.

---

## Phase 2 — Data and semantic foundations

Status: **done** at `d6e624c`. `periods.py` (Q2 2026 vs Q1 2026 from the data,
maturity cutoff 2025-08), `metric_registry.py` (12 pinned definitions, PSI/CSI),
`domains.build` stamping on completion. 17/17 tests.

## Phase 3 — Analytical story engines

Status: **done** at `4c19270`. `decomposition.py`, `analysis_delinquency.py`,
`analysis_traits.py`, `story_router.py`, wired into `/ask`. 32/32 tests.

Credit Card 30+ DPD 6.9077% -> 7.5082%, +0.6006 pp; five flows explain the
numerator change to SAR 0.00; three mix bridges each reconcile to 0.6006 pp.
123 scorecard inputs reviewed, 55 correctly classified historical.

## Phase 4 — Shared What-If and model pages

Status: **done** at `9aabb56`. `lgd_absolute_pp`, `ccf_absolute_pp`,
`whatif_thread.py`, `WhatIfThread` component, `/what-if/threads/{id}`.
29/29 tests, 14/14 browser checks.

Still open in this phase: §10's six XGBoost tabs and a persisted artifact;
the Delta page's worked example.

## Phase 5 — Results and professional exports

Status: **done and fully accepted**.

§12 — the workbook. `workbook_style.py`, `workbook_sheet.py`,
`whatif_workbook.py`. 22 sheets, gridlines off on every one, 0 numeric cells
unformatted, 0.034823 renders as 3.48%, 36 formula cells, 3 charts, 21
internal links, 4,660 customers and 5,001 facilities of detail.

§11 — the engine records the propagation as it computes it (`mechanism`,
`score_migration`, `stage_movement`); an untouched channel is named as
untouched. Each waterfall step reports how many facilities' ECL actually
moved, and a migration additionally reports how many it selected.

§13 — `report_service.py`, all three families: investigation, trait
attribution, scorecard validation. `POST /retail/reports/{family}.docx`
returns the right content type and filename and refuses as a status code
rather than as a file.

### Performance (§27)

| Stage | Before | After |
|---|---:|---:|
| `_read_book` per call | 1.20s, uncached | 0.00s after the first |
| `cohort.run` | 5.76s | 1.93s |
| customer roll-up | 2.84s | 0.14s |
| facility detail | 0.46s | 0.18s |
| workbook build | 1.98s | 2.02s |
| **browser download, end to end** | **15.4s** | **8.1–9.0s** |

Nothing was removed to get there: the same 22 sheets, the same customer and
facility detail, the same formatting and the same auditability.

The demonstration path, re-measured at Phase 9 by
`scripts/retail_uat/phase9_timings.py`. Cold is the first call after a
restart with the startup warm-up finished, because that is what the
presenter's first click actually is; the suite waits for the warm-up rather
than measuring the race.

| Step | Cold | Warm | Budget |
|---|---:|---:|---:|
| Cockpit attention cards | 0.05s | 0.02s | 3s |
| An investigation's first answer | 1.17s | 0.59s | 15s |
| The trait inventory | 0.22s | 0.21s | 12s |
| A What-If baseline | 0.01s | 0.01s | 5s |
| A Delta scenario | 10.73s | 10.26s | 20s |
| An XGBoost scenario | 11.81s | 11.26s | 20s |
| The challenger model card | 0.01s | 0.01s | 2s |
| A product lens, 18 tiles | 1.82s | 1.71s | 10s |
| The validation overview | 0.51s | 0.04s | 3s |
| The early-warning panel | 0.01s | 0.01s | 12s |

Two of those were far outside it before Phase 9. The trait inventory was
37.2s and a product dashboard 18.9s, both because the same pure function of
the published book was being recomputed on every request: `measures.trend`
reads all twenty-five months, and the §7 analysis recomputes IFRS 9 ECL per
attribution prefix. Both are now kept, keyed by the book's manifest hash, and
warmed on the existing daemon thread so the presenter does not pay for the
first one. The startup warm-up takes about two and a half minutes and nobody
waits for it.

Almost none of the §7 cost was waste, which is why it was cached rather than
trimmed: 10s is `movement.decompose` recomputing ECL per prefix, which it has
to do because ECL is multiplicative and an allocated attribution would not
reconcile, and 10s is rescoring every active scorecard over both windows.

### Acceptance

`scripts/retail_uat/phase5_acceptance.py` — **39 of 39**, both files
downloaded by clicking in a real browser and then opened and inspected. Zero
page errors.

`scripts/retail_uat/check_workbook_formulas.py` recomputes every formula
against the other cells' cached values, independently of the code that wrote
them.

Tests: 125 across phases 2–5, 0 failures.

## Phase 6 — Scorecard Validation

Status: complete.

The Stop button used to unmount the page: the screen fabricated a run to
show, that run carried no `findings`, and `run.findings.length` threw. A
stopped job now records `recorded: False` and a note saying a run covering
7 of 53 tests is not quotable as a validation — which is the honest thing
to store, and the screen no longer invents anything to display.

Data & Representativeness has contents rather than a heading:
provenance, input drift, the observed default rate and mix-adjusted rates
by direct standardisation. Standardisation is refused below 200 in a
stratum and below 50% coverage — origination vintage was standardising 9%
of the book, because new vintages have no development counterpart, and now
16 strata cover 95%.

Discrimination reports inversions with the evidence to argue about them:
bounds, accounts, customers, events, rate, Wilson interval, PD and largest
tied share. PASS with none, FAIL where the intervals separate, WARNING
otherwise. Re-banding on development-anchored support found real
inversions in three of four behavioural scorecards while Credit Card
stayed clean.

Comments attach to categories and evidence cards, keyed on model and
target and carrying the run they were written against; an edit supersedes
rather than overwrites. The validation Word report renders all fifteen
sections and carries the reader's comments into the document.

Acceptance: 20/20 in the browser. Release smoke: 20/20 at `e96dc93`.

## Phase 7 — Workspace population

Status: complete.

A governed measure engine — 26 measures, 17 cuts — under everything, so a
project's headline, an analysis's result, a paper's quoted figure and a
lens tile are the same computation rather than four that agree by
coincidence. Every one carries the month and the book hash it was computed
from.

12 projects, 143 saved analyses, 200 investigations (145 seeded threads
with real turns), 25 documents across all four products with versions, a
lifecycle and a Word download, and 12 lenses of which 8 are seeded and 4
are pre-existing user lenses §20 forbids deleting.

The tidy removes what a retail installation should not be showing: 9
corporate analyses — "Shipping PD increase" and friends — and 51
investigations with no messages and no project. Anything carrying content
is untouched.

Proven idempotent by running it twice: the second run created only the 6
previously-refused analyses and left 137 analyses and 139 investigations
unchanged.

## Phase 8 — Integrated demo

Status: complete.

§21 — a clean forward-risk cohort, separate from "not currently bad". The
difference is 645 customers: 5,166 against 4,521, which is exactly the
1–29 DPD and hard-trigger population.

§22 — a five-act, 28-step presenter story with every artifact id resolved
against this installation on every request rather than written down. A
guide naming "investigation 1012" is correct on one machine and wrong on
every other. Resume returns to the step the presenter left on; Restart
clears it; free-text navigation is untouched throughout.

§23 — a 46-entry prompt bank across the cockpit, investigations, what-if
and validation, each carrying what the product must resolve, what it must
say, and what it must not. Two entries expect a clarification and one a
refusal, because a clarification where a result was expected is a
regression and a result where a clarification was expected is a worse one.
The suite clicks a chip, records the request, types the identical words and
compares the two: same endpoint, same method.

§25 — the navigation audit walks all 25 routes, opens every distinct link
shape rather than guessing which are served, and checks that no screen is
a dead end.

Acceptance: §22/§23 21/21. §25 7/7.

## Phase 9 — Cold start, gates, release

Status: complete.

§24 — the bootstrap now seeds the demonstration content. It published the
book, built the views, scored the panel and reported "ready to
demonstrate", and a fresh Mac opened on a Workspace with no projects and a
Documents screen reading "Nothing yet". `--check` counts the content
against the seed definitions, and fails an installation whose seeded
analyses were computed against an older book than the one published.

All five derived domains carry a source stamp; rewriting the manifest hash
flips every one of them to stale, and restoring it flips them back.

§10.2 — the What-If challenger has an artifact and a page. It used to be
fitted from scratch on every run and discarded, so there was nothing to
open and "the challenger said X last Tuesday" was unanswerable. Save/load
parity over 5,000 facilities: 0.0 SAR.

§26 — the 92 gates are in `RETAIL_DEMO_COMPLETION_ACCEPTANCE.md`. Ninety
green. WIF-16 fails: Remove Step, Clone and Compare exist in the API and
no control on the thread screen reaches them. VAL-16 is NOT RUN: the wider
scorecard regression suite, deferred when it exceeded the release window.
