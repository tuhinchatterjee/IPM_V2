# Defect register: exhaustive validation round

Branch `claude/guided-workspace-exhaustive-validation`. The base is evidence commit `55bfb9a4` on top of candidate H (`8b1592f4`).

**Severity:**
- CRITICAL: wrong data, security, tenant leakage, wrong ECL or cohort, silent method execution, corruption.
- HIGH: a broken primary journey, a dead route or control, or a persistence, share or reopen failure.
- MEDIUM: a secondary interaction, back-state, filter or export inconsistency.
- LOW: presentation, accessibility or non-blocking polish.

**Protected-file status:** no defect in this register required a change to a protected file. `scripts/guided_workspace/protected_baseline.py --check` reports the same six files the PROTECTED_EXTENSION_MAP already records. A lint finding was fixed in no protected file; those findings are counted, not fixed.

**How each result was measured:**
- **Targeted retest:** the named test on the working tree after the fix. For the backend defects it is also the same test run against the pre-fix backend, where it fails: 19 of the 20 tests in `test_gw_validation_defects.py` fail on the pre-fix backend. The one that passes is the restart validation, which is not a defect test.
- **Regression:** the final regression of record on candidate I (see `VALIDATION_REPORT.md`).

## Summary

| ID | Sev | Module | Defect | Disposition |
|---|---|---|---|---|
| VAL-DEF-001 | HIGH | Sharing (all modules) | Double-clicking Send shared the object twice | FIXED |
| VAL-DEF-002 | HIGH | Scenario Library | Double-clicking Clone/Branch made two copies | FIXED |
| VAL-DEF-003 | MEDIUM | Scenario Library | Combine-save double-submit; a failed card Clone was an unhandled rejection | FIXED |
| VAL-DEF-004 | HIGH | Guided Cockpit / Early Warning | Save cohort, What-If and Export each froze the same population again; export ignored HTTP errors | FIXED |
| VAL-DEF-005 | MEDIUM | What-If grid | Switching book showed the previous book's rows until the refetch landed | FIXED |
| VAL-DEF-006 | MEDIUM | Plotly (all charts) | Draw/resize/purge race raised console errors on fast navigation | FIXED |
| VAL-DEF-007 | LOW | What-If grid | Rows with a null key collided; grid export failure unhandled | FIXED |
| VAL-DEF-008 | LOW | Monitoring | Assigning an alert to its current assignee wrote a new version and event | FIXED |
| VAL-DEF-009 | HIGH | Navigation (all modules) | Browser Back lost view state; no in-product Back to the origin module | FIXED |
| VAL-DEF-010 | CRITICAL | What-If runs | A scenario with unresolved overlaps, or a retired one, could be run | FIXED |
| VAL-DEF-011 | MEDIUM | Scenario Library | Retire not idempotent; a retired scenario could be revised | FIXED |
| VAL-DEF-012 | MEDIUM | Grid / cohorts | Wrong-type filter → HTTP 500; cohort error echoed engine SQL; huge offset → 500 | FIXED |
| VAL-DEF-013 | HIGH | Lenses | A breach rule with no threshold, a bad severity or an out-of-scope book was saved; the next refresh failed with a 500 | FIXED |
| VAL-DEF-014 | LOW | Lenses / Monitoring / runs | Unknown listing parameters silently accepted; error text named Python classes or misled | FIXED |
| VAL-DEF-015 | MEDIUM | Scenario Library | A policy for a non-existent overlap was written as a new version | FIXED |
| VAL-DEF-016 | HIGH | What-If | Binding was not idempotent: every remount (Back, refresh) cloned the template again | FIXED |
| VAL-DEF-017 | MEDIUM | Messages | A share of a since-retired scenario still offered Run | FIXED |
| VAL-DEF-018 | LOW | Exports | An unexecuted run's package carried no caveat | FIXED |
| VAL-DEF-019 | MEDIUM | Lenses | Back to the Lens Library re-proposed the Cockpit/investigation Lens (duplicate-save risk) | FIXED |
| VAL-DEF-020 | MEDIUM | Scenario Library | No Cancel for Clone/Branch or for the builder | FIXED |
| VAL-DEF-021 | MEDIUM | What-If / LLM Exchange | Unhandled promise rejections (load cohort, exchange export) | FIXED |
| VAL-DEF-022 | HIGH | Cockpit thread | A thread opened from a Lens, an alert, Early Warning or What-If had no way back to its origin | FIXED |
| VAL-DEF-023 | HIGH | Lenses / What-If | The URL-state `replace` could overtake a navigation `push` and cancel it (Lens → What-If did nothing) | FIXED |
| VAL-DEF-028 | MEDIUM | Scenario detail | Binding your own scenario left the page on the old version, with a Back link pointing to itself | FIXED |
| VAL-DEF-029 | HIGH | Cockpit thread → What-If | A conversation opened on a governed cohort (Lens, alert, Early Warning, What-If) had no click path to What-If on that population | FIXED |
| VAL-DEF-030 | MEDIUM | Navigation chain | A chain of in-product Backs lost a level: the Scenario Library, its result links and the Lens Library rebuilt their address without their own origin; long origin chains were dropped above 1,500 characters | FIXED |
| VAL-DEF-024 | LOW | Workspace API | Pydantic validation errors are returned as raw lists, not the product's error envelope | OPEN (accepted, LOW) |
| VAL-DEF-025 | LOW | Workspace API | No `GET /lenses/{id}`: the UI reads Lenses through `/objects/{id}`; a direct call is a bare 404 | OPEN (accepted, LOW) |
| VAL-DEF-026 | LOW | Legacy Trace | `/trace/[runId]` parses the id as a number; reached only from legacy V3 surfaces, never from a guided flow | OPEN (out of guided scope) |
| VAL-DEF-027 | LOW | Run records | The run body's contract carries the engine predicate (SQL) to its authorised reader | OPEN (by design: auditability) |

CRITICAL and HIGH: 12 found and 12 fixed. MEDIUM and LOW: 13 fixed. Open items: 4, all LOW, none a regression.

## Details

### VAL-DEF-001: Share sent twice on double-click (HIGH)

| Field | Detail |
|---|---|
| Module | Sharing: `ShareButton`, used by results, Lenses, cohorts and comparisons |
| Reproduction | Open a result → Share → type a recipient → double-click Send |
| Expected | One message |
| Actual | Two messages and two `shared` versions |
| Evidence | Idempotency audit (agent probe of every mutating control) |
| Root cause | No in-flight guard on the async send |
| Files | `frontend/src/lib/workspace/single-flight.ts` (new), `components/workspace/share-button.tsx` |
| Protected | No |
| Test | `GW-BACK-11` and `GW-GOLD-01` share once and assert exactly one sent message for the object |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-002: Clone/Branch double-click made two copies (HIGH)

| Field | Detail |
|---|---|
| Module | Scenario detail |
| Reproduction | Scenario detail → double-click Clone |
| Expected | One copy |
| Actual | Two DRAFT copies |
| Root cause | `act()` had no single-flight guard |
| Files | `components/scenarios/scenario-detail.tsx` (`useSingleFlight`; Clone and Branch disabled while busy) |
| Test | `GW-BACK-08` (one copy, then discarded) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-003: Library combine-save double-submit; card Clone unhandled rejection (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Library → tick two → Combine → double-click Save; or Clone a card while the API refuses |
| Expected | One combination; the refusal shown in plain words |
| Actual | Two combinations; an unhandled rejection in the console |
| Files | `components/scenarios/scenario-library.tsx` (single-flight; `cloneCard` with the visible error `scenario-library-error`) |
| Test | `GW-BACK-09`; `GW-GOLD-03` (one combination) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-004: Population frozen repeatedly from the same issue/segment (HIGH)

| Field | Detail |
|---|---|
| Module | Requires Attention card, Issue detail, Early Warning |
| Reproduction | Save cohort, then What-If, then Export on the same population |
| Expected | One governed cohort object reused |
| Actual | A new cohort per click; Early Warning export ignored a non-OK response |
| Files | `components/guided/requires-attention.tsx`, `components/guided/issue-detail.tsx`, `components/guided/early-warning-v4.tsx` (memoised freeze, single-flight, `response.ok` checked, segment buttons given test ids) |
| Test | `GW-GOLD-06`: export and What-If reuse the saved cohort id; the export holds exactly the cohort's rows |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-005: Grid showed the previous book after a book switch (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | What-If → switch Corporate → Retail quickly |
| Expected | Rows clear until the Retail page arrives |
| Actual | Corporate rows under Retail columns until the refetch landed |
| Root cause | The page state was kept across the domain change |
| Files | `components/workspace/data-grid.tsx` |
| Test | Browser suites `GW-P5-01`, `GW-BACK-06` (retail book state) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-006: Plotly draw/resize/purge race (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Navigate away while charts are still drawing (fast Back/Forward) |
| Expected | No console error |
| Actual | Plotly errors on a purged or missing `_fullLayout` from a pending draw or resize |
| Root cause | Concurrent draws, and a purge before pending draws had settled |
| Files | `components/viz/plotly-chart.tsx` (chained draws, a disposed flag, resize skipped after dispose, purge after pending draws; layout `transition` removed) |
| Test | Every `GW-BACK-*`, `GW-GOLD-*` and `GW-VAL-PLOTLY` journey now fails on any console error |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-007: Null-key row collisions; grid export rejection (LOW)

| Field | Detail |
|---|---|
| Files | `components/workspace/data-grid.tsx` (the row key falls back to its offset; export `.catch` shows the error) |
| Test | The browser grid suites |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-008: Repeated assign wrote new versions (LOW)

| Field | Detail |
|---|---|
| Reproduction | Monitoring → alert → Assign to me, twice |
| Expected | One version and one "assigned to" event |
| Actual | Two |
| Files | `backend/workspace/monitoring.py` |
| Test | `test_gw_validation_defects.py::test_val_def_008_repeated_assign_is_a_no_op` |
| Retest | PASS (fails on the pre-fix backend) |
| Disposition | FIXED |

### VAL-DEF-009: Back navigation lost state; no in-product Back to the origin (HIGH)

**Module:** every guided module.

**Reproduction.** For example, Scenario Library filtered by search, owner and severity → open a scenario → browser Back.

**Expected.** The same filtered library. The same holds for What-If (book, filters, cohort, scenario, run), the Lens Library filter, Lens cross-filters and selection, Monitoring view and filters, the Result method tab, the Messages box and open message, and the LLM Exchange tab and open call. Every destination offers "Back to <origin>".

**Actual.**
- State was held only in React state, so it was lost on remount.
- Detail pages linked to a fixed parent.
- What-If re-posted a bind on remount.

**Root cause.** Next.js 16 remounts client components on history navigation; only URL or session state survives.

**Files.**
- New: `lib/workspace/nav.ts`, `components/workspace/origin-back.tsx`.
- URL-held state in: `whatif-workspace.tsx`, `scenario-library.tsx` (session-held combine selection), `scenario-detail.tsx`, `scenario-builder.tsx`, `result-page.tsx` / `result-view.tsx`, `lens-library.tsx`, `lens-view.tsx`, `monitoring-centre.tsx`, `messages-center.tsx`, `metric-catalogue.tsx`, `llm-exchange-view.tsx`, `issue-detail.tsx`.
- Every cross-module handoff now carries `back=`.
- Suspense boundaries added to the detail pages.

**Tests.**
- `nav.test.ts` NAV01–NAV03.
- `GW-BACK-01..22`: browser Back, Forward and the in-product control, each asserting the origin's state read from the page, with no write or model call on the return trip.
- `GW-GOLD-10`: the full stack, in-product and then browser Back.

**Retest:** PASS. **Disposition:** FIXED.

### VAL-DEF-010: An unrunnable scenario could reach a run (CRITICAL)

**Module:** What-If runs (workspace, Messages and Cockpit entries share `runs.create`).

**Reproduction.**
- `POST /whatif/runs` with seeded conflict template CORP-18, or an unresolved A+B combination, then confirm, choose Delta and execute.
- Or retire a scenario and run it.

**Expected.**
- Refused before a run exists.
- The library already marks the definition BLOCKED, with "none is assumed".

**Actual.** A run was created and executed. Overlapping rules were applied with no chosen composition policy, and a retired definition still ran.

**Root cause.** `runs.create` never consulted the library's readiness or the scenario's retirement.

**Files.**
- `backend/workspace/runs.py` (`_refuse_unrunnable`: 409 `COMPOSITION_POLICY_REQUIRED`, 409 `SCENARIO_RETIRED`).
- `tests/cockpit_v4/test_gw_runs.py`: one existing test ran CORP-18 directly. It now chooses a policy for each overlap on the analyst's copy before running, which is what the template's own note requires. Its reconciliation assertions are unchanged.

**Tests.**
- `test_val_def_010_a_conflict_template_is_refused_before_a_run_exists`
- `test_val_def_010_an_unresolved_combination_is_refused` (and, once resolved, runs and reconciles)
- `test_val_def_010_a_retired_scenario_is_not_run`
- `GW-GOLD-03` (three-way combination resolved, then run)

**Retest:** PASS; all fail on the pre-fix backend. **Disposition:** FIXED.

### VAL-DEF-011: Retire not idempotent; retired scenario revisable (MEDIUM)

| Field | Detail |
|---|---|
| Files | `backend/workspace/scenarios.py` |
| Test | `test_val_def_011_retire_twice_writes_one_version` |
| Retest | PASS (fails pre-fix) |
| Disposition | FIXED |

### VAL-DEF-012: Grid/cohort negative states (MEDIUM)

**Reproduction.**
- `POST /grid/query` with `{"column":"sector","op":"gt","value":5}`.
- `POST /cohorts` with the same filter.
- `POST /grid/query` with `offset=2**63`.

**Expected.**
- 422 `INVALID_FILTER` in plain words.
- No SQL echoed.
- An offset beyond the book returns empty; an absurd offset returns 422.

**Actual.** 500 (DuckDB binder error); `COHORT_UNRESOLVED` echoing the engine SQL; 500.

**Files.**
- `backend/workspace/grid.py`: `_rows` maps DuckDB binder, conversion and input errors to 422; `OFFSET_MAX` added.
- `grid_api.py`: offset bound.
- `cohorts.py`: engine errors are replaced by a plain message.

**Tests.**
- `test_a_wrong_type_filter_value_is_422_in_plain_words`
- `test_a_cohort_on_an_unresolvable_filter_names_no_sql`
- `test_paging_beyond_the_book_is_empty_and_a_huge_offset_is_refused`

**Retest:** PASS (fails pre-fix). **Disposition:** FIXED.

### VAL-DEF-013: An unevaluable Lens breach rule was accepted (HIGH)

| Field | Detail |
|---|---|
| Reproduction | Revise `lens-02` with a rule missing `threshold` (or `severity: "urgent"`, or `domain: "mars"`), then refresh |
| Expected | 422 `INVALID_RULE` on save; the Lens keeps refreshing |
| Actual | Saved; the next refresh raised `KeyError` (HTTP 500) and the Lens stopped refreshing |
| Files | `backend/workspace/lenses.py` (`_check_rule`) |
| Test | `test_an_unevaluable_lens_rule_is_refused_on_save[5 cases]` (each also refreshes successfully afterwards) |
| Retest | PASS (fails pre-fix) |
| Disposition | FIXED |

### VAL-DEF-014: Silent unknown parameters; misleading messages (LOW)

**Actual.**
- `/lenses?domain=xyz` and `/monitoring?view=bogus|severity=bogus|domain=xyz` returned 200, with unfiltered or empty lists.
- A non-numeric user assumption returned `user_assumption: [<class 'decimal.ConversionSyntax'>]`.
- Execute at METHOD_INPUT_REQUIRED said "a confirmed scenario runs only after a method is chosen", although one had been chosen.

**Files.** `lenses_api.py`, `monitoring_api.py` (vocabulary patterns → 422), `runs.py` (plain messages).

**Tests.**
- `test_listing_parameters_outside_their_vocabulary_are_refused`
- `test_a_non_numeric_assumption_is_explained_without_python_names`
- `test_execute_refusal_says_why_at_method_input_required`

**Retest:** PASS (fails pre-fix). **Disposition:** FIXED.

### VAL-DEF-015: Resolve accepted unknown overlap ids (MEDIUM)

| Field | Detail |
|---|---|
| Files | `backend/workspace/scenarios.py` (422 `UNKNOWN_OVERLAP`; overlap rows without an id are skipped) |
| Test | `test_val_def_015_unknown_overlap_id_is_refused` |
| Retest | PASS (fails pre-fix) |
| Disposition | FIXED |

### VAL-DEF-016: Bind not idempotent (HIGH)

| Field | Detail |
|---|---|
| Reproduction | What-If with `?cohort=X&scenario=<template>` → Scenario Library → browser Back |
| Expected | The same bound copy |
| Actual | A new scenario copy on every remount; for an own scenario, a new version on every remount |
| Root cause | `scenarios.bind` always revised or cloned |
| Files | `backend/workspace/scenarios.py` (`_bound_to`: re-binding to the same cohort version returns the existing binding, `reused: true`) |
| Test | `test_val_def_016_rebinding_reuses_the_binding`; `GW-BACK-06` (no new object on the return trip) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-017: Stale share of a retired scenario still offered Run (MEDIUM)

| Field | Detail |
|---|---|
| Files | `backend/workspace/messages.py` (`retired`, `latest_status`; Run actions removed), `messages-center.tsx` (`message-retired` notice), `lib/workspace/messages.ts` |
| Test | `test_a_share_of_a_since_retired_scenario_says_so_and_offers_no_run` (Run is refused with 409 `SCENARIO_RETIRED` too) |
| Retest | PASS (fails pre-fix) |
| Disposition | FIXED |

### VAL-DEF-018: Unexecuted run export without caveat (LOW)

| Field | Detail |
|---|---|
| Files | `backend/workspace/exports.py` (`caveats` in the manifest and a CAVEAT line in the README) |
| Test | `test_an_unexecuted_run_export_carries_a_caveat` (an executed run's package has none) |
| Retest | PASS (fails pre-fix) |
| Disposition | FIXED |

### VAL-DEF-019: Lens Library re-proposed the origin Lens on Back (MEDIUM)

| Field | Detail |
|---|---|
| Files | `components/lenses/lens-library.tsx` (`from_thread`/`from_investigation` consumed with `replace`; the filter kept in the URL) |
| Test | `GW-P9-03` now asserts the origin parameter is consumed; `GW-BACK-14` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-020: No Cancel for Clone/Branch or the builder (MEDIUM)

| Field | Detail |
|---|---|
| Files | `scenario-detail.tsx` ("Discard this copy" on a fresh DRAFT copy retires it and returns to the origin), `scenario-builder.tsx` (Cancel and Back link) |
| Test | `GW-BACK-08` (Detail → Clone → Back / Discard; Library → New → Cancel writes nothing) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-021: Unhandled promise rejections (MEDIUM)

| Field | Detail |
|---|---|
| Files | `whatif-workspace.tsx` (Load cohort pick), `llm-exchange-view.tsx` (export fetch) |
| Test | The console gate on all validation journeys |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-022: A thread had no way back to its origin (HIGH)

| Field | Detail |
|---|---|
| Reproduction | Lens selection → Investigate (or alert → Investigate) |
| Expected | "Back to the Lens / Monitoring Centre" |
| Actual | Only the protected thread header's fixed "Back to Cockpit"; the guided investigation bar rendered nothing for these threads |
| Root cause | The Back link sat inside the investigation-only section |
| Files | `components/guided/investigation-bar.tsx` (unprotected; rendered by the protected thread view). The `?ask=` hand-off keeps `back=`. All Investigate hand-offs carry their origin. |
| Test | `GW-BACK-02`, `-16`, `-20` (the in-product Back from the thread) |
| Retest | PASS. The first run failed and is preserved in this round's evidence log. |
| Disposition | FIXED |

### VAL-DEF-023: URL-state replace overtook navigation push (HIGH)

| Field | Detail |
|---|---|
| Reproduction | Lens with a selection → What-If |
| Expected | What-If opens on the frozen cohort |
| Actual | The page stayed on the Lens. Freezing the selection updated the URL (`replace`), which landed after and cancelled the `push` to What-If. |
| Root cause | Concurrent `router.replace` (state sync) and `router.push` (navigation) |
| Files | `lens-view.tsx`, `whatif-workspace.tsx` (a `leaving` guard: state sync stops once the page navigates away) |
| Test | `GW-BACK-17`. The first run failed and is preserved; the rerun passed. |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-028: Bind left the detail page stale, with a self-referencing Back (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Your own scenario → Bind to a cohort → choose |
| Expected | The page shows the new version (bound scope); Back still returns to the library |
| Actual | The page re-navigated to its own URL with `back=` set to itself and kept showing version 1 (same id, so no refetch) |
| Root cause | The bind handler always pushed the bound object's URL |
| Files | `components/scenarios/scenario-detail.tsx` (same object: re-read in place; a new object: push with Back) |
| Test | `GW-GOLD-03`. The first run failed and is preserved; the rerun passed. |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-029: No What-If from a cohort-seeded conversation (HIGH)

| Field | Detail |
|---|---|
| Reproduction | Lens → box-select → Investigate → ask the root-cause question |
| Expected | "What-If on this population" opens What-If on the same governed cohort (GOLD-04: Lens → … → Investigate → root cause → Run What-If) |
| Actual | Only issue investigations carry the next-best-question chips; a cohort-seeded thread offered no What-If control until a scenario preview was typed |
| Root cause | `whatif.thread_cohort` reported only a scenario-frozen cohort, not the governed cohort the thread was seeded with |
| Files | `backend/workspace/whatif.py` (`seed_cohort_id`), `frontend/src/lib/workspace/whatif.ts`, `components/guided/thread-whatif.tsx` (`thread-whatif-on-cohort`) |
| Test | `test_gw_validation_endpoints.py::test_an_alert_cohort_and_investigation_carry_the_alert_population` (the seeded id); `GW-GOLD-04`, `GW-GOLD-06` |
| Retest | PASS. The first run failed and is preserved; the rerun passed. |
| Disposition | FIXED |

### VAL-DEF-030: The in-product Back chain lost a level (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Home → issue → thread → What-If → Library (search) → scenario → result → Messages, then in-product Back repeatedly |
| Expected | Each Back lands on the previous level with its state |
| Actual | Library → What-If was lost: the library's card links and the scenario's result links carried an origin without its own `back=`; the Lens Library had no Back link at all; `safeBack` dropped chains longer than 1,500 characters |
| Files | `scenario-library.tsx` (`here` keeps `back`), `scenario-detail.tsx` (result links use the full current address), `lens-library.tsx` (Back link; origin kept), `lib/workspace/nav.ts` (6,000-character limit), `nav.test.ts` (NAV01 long chain) |
| Test | `GW-GOLD-10` (in-product then browser Back through all eight levels). The first run failed and is preserved; the rerun passed. NAV01. |
| Retest | PASS |
| Disposition | FIXED |

### Open items (all LOW)

- **VAL-DEF-024.** FastAPI/Pydantic 422 bodies are lists of field errors, not `{"error_code","message"}`. The UI shows a generic message for them. Accepted for this round: a shape change across every endpoint is not a defect fix.
- **VAL-DEF-025.** Lenses are read through `GET /objects/{id}` and rendered through `POST /lenses/{id}/render`. There is no `GET /lenses/{id}`. Accepted: no product surface calls it.
- **VAL-DEF-026.** The legacy V3 Trace page `/trace/[runId]` expects a numeric analysis-run id. Guided flows use `/cockpit/trace/<id>` and `/trace/llm-exchange/<id>`. Out of the guided scope; recorded.
- **VAL-DEF-027.** A run's stored contract holds the engine predicate for audit, and it is visible to the run's authorised reader only. Tenant isolation was re-tested and holds. By design.
