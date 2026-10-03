# Defect register: exhaustive validation round

Branch `claude/guided-workspace-exhaustive-validation`. The round started on evidence commit `55bfb9a4` on top of candidate H (`8b1592f4`). VAL-DEF-001 to 031 were found and fixed in candidates I to K. VAL-DEF-032 to 054 were found by the interaction-coverage closure, which executed every UI control, route, handoff and chart contract in the browser (`GW-CTL-*` journeys), on top of evidence commit `510f5c83` (candidate K). VAL-DEF-035 is not used.

**Severity:**
- CRITICAL: wrong data, security, tenant leakage, wrong ECL or cohort, silent method execution, corruption.
- HIGH: a broken primary journey, a dead route or control, or a persistence, share or reopen failure.
- MEDIUM: a secondary interaction, back-state, filter or export inconsistency.
- LOW: presentation, accessibility or non-blocking polish.

**Protected-file status:** no defect in this register required a change to a protected file. `scripts/guided_workspace/protected_baseline.py --check` reports the same six files the PROTECTED_EXTENSION_MAP already records. A lint finding was fixed in no protected file; those findings are counted, not fixed.

**How each result was measured:**
- **Pre-fix proof:** for every defect from VAL-DEF-032 on, the failing browser record or pytest output from BEFORE the fix is kept in `prefix_evidence/` next to this file (named by defect). A backend fix also has a regression test that fails on the pre-fix code (shown in its `*_prefix_pytest.txt`) and a mutation gate that restores the pre-fix code and must be KILLED (`mutation_gates.json`).
- **Targeted retest:** the named test or journey on the working tree after the fix.
- **Regression:** the regression of record on the final candidate, run from a fresh detached clone (see `VALIDATION_REPORT.md`); every fix is covered by a step that ran there.

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
| VAL-DEF-031 | LOW | What-If | An unknown `?domain=` was forwarded to the API (HTTP 400 shown as an error) instead of being ignored | FIXED |
| VAL-DEF-024 | LOW | Workspace API | Pydantic validation errors are returned as raw lists, not the product's error envelope | FIXED |
| VAL-DEF-025 | LOW | Workspace API | No `GET /lenses/{id}`: a direct read was a bare 404 | FIXED |
| VAL-DEF-026 | LOW | Legacy Trace | `/trace/[runId]` parses the id as a number | FIXED (by VAL-DEF-032) |
| VAL-DEF-027 | LOW | Run records | The run body's contract carries the engine predicate (SQL) to its authorised reader | ACCEPTED_BY_DESIGN |
| VAL-DEF-032 | HIGH | Navigation (legacy surfaces) | Under V4 + guided, the sidebar and four legacy routes opened V3 pages whose API the V4 runtime does not serve | FIXED |
| VAL-DEF-033 | MEDIUM | Navigation (Back) | Four destinations reached with an origin had no in-product Back; the Model Lab link dropped the origin | FIXED |
| VAL-DEF-034 | MEDIUM | Early Warning | Book and rule filter were component state only: Back from any Early Warning handoff restored the wrong population | FIXED |
| VAL-DEF-036 | MEDIUM | What-If runs | Execute and re-run blocked the server's event loop: every other request stalled during an execution | FIXED |
| VAL-DEF-037 | HIGH | Workspace data access | A workspace read during a Cockpit question shared one database connection with the run's thread and returned another query's rows (HTTP 500) | FIXED |
| VAL-DEF-038 | MEDIUM | What-If session tree | "Open run" changed the address but did not open the run | FIXED |
| VAL-DEF-039 | MEDIUM | Address state (What-If, Scenario Library, Monitoring, Lenses) | Two quick state changes lost one in the address; Back or refresh restored a cleared state | FIXED |
| VAL-DEF-040 | LOW | Metric Catalogue | Search, book and family filters were lost on Back | FIXED |
| VAL-DEF-041 | MEDIUM | Metric Catalogue | Switching the breakdown book kept the other book's dimension (HTTP 422; the breakdown vanished) | FIXED |
| VAL-DEF-042 | LOW | What-If | Reopening a run briefly dropped `run=` from the address; Forward or refresh then lost the run | FIXED |
| VAL-DEF-043 | LOW | What-If macro sensitivity | A filter matching nothing was refused (HTTP 422, a red error and a console error) where the grid and explorer show an empty state | FIXED |
| VAL-DEF-044 | MEDIUM | Navigation (Back origin) | A link rendered while the page's own address write was in flight carried the previous address as its origin; its Back restored a state already left | FIXED |
| VAL-DEF-045 | MEDIUM | Lenses (and seven guided action helpers) | Double-clicking "Save as a new version" wrote two Lens versions; the same state-only guard sat in seven other helpers | FIXED |
| VAL-DEF-046 | MEDIUM | Messages | "Opens my copy" after Duplicate/Save carried no origin: the copy's Back went to the Scenario Library | FIXED |
| VAL-DEF-047 | MEDIUM | Lens Library | Browser Forward to an unsaved Lens proposal (from a conversation or an investigation) showed the library without the proposal | FIXED |
| VAL-DEF-048 | MEDIUM | Lens charts | Clear removed the selection but the chart kept the box and highlighted bars; selecting the same bars again deselected them | FIXED |
| VAL-DEF-049 | MEDIUM | What-If / Lenses | Adopting a conversation's cohort again (a second click, a re-made Lens proposal) minted another cohort object for the same population | FIXED |
| VAL-DEF-050 | HIGH | Sharing (recipient actions) | An administrator recipient changed the sender's object: opening a shared definition on their cohort revised the sender's scenario; Save on a shared Lens renamed the sender's Lens | FIXED |
| VAL-DEF-051 | MEDIUM | What-If / Scenario Library | A link labelled with a scenario version (a result's scenario, What-If's applied scenario, a lineage ancestor) opened the latest version instead | FIXED |
| VAL-DEF-052 | MEDIUM | Lenses | A library Lens customised as my copy opened without its origin: the copy's in-product Back went to the Lens Library, not the Lens it came from | FIXED |
| VAL-DEF-053 | MEDIUM | Guided investigation | Answered next-best questions were never suppressed: each was re-offered as if the cohort had changed, and lower-ranked actions (Monitor in a Lens) never reached the chips shown | FIXED |
| VAL-DEF-054 | HIGH | Scenario Library | "Used by" on a scenario linked its runs to the scenario page, which failed with HTTP 500 (a run read as a scenario); the scenario routes returned 500 for any non-scenario id | FIXED |
Found: 53 (1 CRITICAL, 13 HIGH, 27 MEDIUM, 12 LOW). Fixed: 52. Every CRITICAL, HIGH and MEDIUM defect is fixed, as are 11 of the 12 LOW. Open: 1 LOW, VAL-DEF-027, accepted by design (below).

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

### VAL-DEF-031: Unknown `?domain=` forwarded to the API (LOW)

| Field | Detail |
|---|---|
| Reproduction | Open `/what-if?domain=xyz` |
| Expected | The Corporate book opens; the unknown value is ignored |
| Actual | `GET /whatif/context?domain=xyz` returned 400, and the page showed the refusal |
| Files | `components/whatif/whatif-workspace.tsx` |
| Test | `GW-VAL-ROUTES` (invalid parameters). The first run failed and is preserved; the rerun passed. |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-024: Validation errors outside the error envelope (LOW)

| Field | Detail |
|---|---|
| Reproduction | `POST /grid/query` with `limit: "x"` |
| Expected | HTTP 422 with `{"detail": {"error_code", "message"}}`, as every other refusal |
| Actual | FastAPI's raw list of field errors; the UI showed a generic message |
| Root cause | Request validation ran before the product's error handling |
| Files | `backend/workspace/errors.py` (new: `GovernedRoute`), every `backend/workspace/*_api.py` router uses it |
| Protected | No (the protected V4 app is unchanged; only the workspace routers opt in) |
| Test | `test_gw_validation_defects.py::test_val_def_024_a_malformed_request_is_the_governed_envelope`; mutation gate |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-025: No direct Lens read (LOW)

| Field | Detail |
|---|---|
| Reproduction | `GET /lenses/lens-02` |
| Expected | The Lens and its card; another tenant refused without leaking it |
| Actual | Bare 404; the UI read Lenses through `/objects/{id}` |
| Files | `backend/workspace/lenses.py` (`read`), `lenses_api.py` (`GET /lenses/{object_id}`, optional `version`) |
| Test | `test_val_def_025_a_lens_reads_directly_by_id` (owner reads it; another tenant gets 403/404 and nothing of the Lens); mutation gate |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-026: Legacy Trace route (LOW)

Fixed by VAL-DEF-032: under the enabled configuration `/trace/<id>` hands over to `/cockpit/trace/<id>` (keeping the query), and `/trace` to the Cockpit. The route is no longer misleading. Proven in `GW-CTL-NA` and `GW-CTL-ROUTES`.

### VAL-DEF-027: The run contract carries the engine predicate (LOW, ACCEPTED_BY_DESIGN)

A run's stored contract holds the engine predicate that defines its population, so the run can be audited and reproduced. It is returned only to the run's authorised reader (owner, or a recipient of a share). Tenant isolation was re-tested and holds (`test_gw_objects.py`, `test_gw_secret_leak.py`). No secret, credential or other tenant's data is involved, and removing it would break the audit trail. Accepted by design.

### VAL-DEF-032: Legacy surfaces reachable under V4 + guided (HIGH)

| Field | Detail |
|---|---|
| Reproduction | V4 + guided; sidebar "Trace" or "Signals"; or open `/trace`, `/trace/<id>`, `/early-warning/lab`, `/early-warning/signals` |
| Expected | Only governed surfaces; legacy routes hand over to their governed equivalent |
| Actual | V3 pages rendered, calling APIs the V4 runtime does not serve: empty or erroring panels |
| Files | `components/workspace/legacy-redirect.tsx` (new), the four legacy pages, `lib/navigation.ts` (entries hidden when handed over) |
| Test | `GW-CTL-NA` (each legacy route lands on its governed equivalent, the legacy surface is absent, Back does not loop); `GW-CTL-ROUTES` |
| Retest | PASS |
| Disposition | FIXED (supersedes VAL-DEF-026) |

### VAL-DEF-033: Destinations without an in-product Back (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Lens alert chart → Monitoring; Messages → comparison; export package → object Trace; LLM Exchange → Model Lab |
| Expected | "← Back to <origin>" on each destination |
| Actual | None; the Model Lab link also dropped the origin |
| Files | `monitoring-centre.tsx`, `comparison-view.tsx`, `object-trace.tsx`, `app/ai-model-lab/page.tsx` (OriginBackLink); `llm-exchange-view.tsx`, `requires-attention.tsx`, `result-view.tsx`, `session-tree.tsx`, `scenario-lineage`, `lab-trace-link` (`withBack`) |
| Test | `GW-CTL-MON`, `-MSG`, `-TRACE`, `-LAB` (in-product Back to the exact origin state) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-034: Early Warning state lost on Back (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Early Warning → Corporate → rule "Covenant breach" → segment What-If → Back |
| Expected | Corporate with the rule |
| Actual | Retail, no rule |
| Evidence | `prefix_evidence/VAL-DEF-034_ew_back_state.json` |
| Root cause | Book and rule held in component state only |
| Files | `components/guided/early-warning-v4.tsx` (`?domain=`, `?reason=`), `app/early-warning/page.tsx` |
| Test | `GW-CTL-EW` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-036: An execution stalled every other request (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Execute a Compare run, watch the header's health poll |
| Expected | Other requests answered while the run computes |
| Actual | The health poll aborted after 8 s; the badge said the backend was unreachable |
| Evidence | `prefix_evidence/VAL-DEF-036_execute_blocks_event_loop.json` |
| Root cause | `async def` handlers running CPU-bound work on the event loop |
| Files | `backend/workspace/runs_api.py` (sync handlers on the thread pool, serialised on their own lock) |
| Test | `test_val_def_036_a_long_execution_does_not_stall_other_requests` (fails on the pre-fix code); mutation gate |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-037: Shared database connection race (HIGH)

| Field | Detail |
|---|---|
| Reproduction | Ask in What-If (a Cockpit run) while the scenario preview loads |
| Expected | Both answer correctly |
| Actual | HTTP 500 `KeyError 'entities'`: the workspace read received the run thread's rows |
| Evidence | `prefix_evidence/VAL-DEF-037_browser_api_traceback.log`, `VAL-DEF-037_prefix_pytest.txt` |
| Root cause | The workspace and the V4 run worker used one cached connection per book concurrently |
| Files | `backend/workspace/access.py` (each read on its own cursor of the same in-memory database, under the session lock) |
| Protected | No (the protected V4 run path is unchanged) |
| Test | `test_val_def_037_workspace_reads_survive_a_concurrent_cockpit_query` (60 reads under a concurrent writer; fails on the pre-fix code); mutation gate |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-038: Session tree "open run" did nothing (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | What-If → session tree → open another run of the session; then browser Back and Forward |
| Expected | That run opens; Back returns to the previous run; Forward reopens the opened run |
| Actual | The address changed; the page kept the current run |
| Evidence | `prefix_evidence/VAL-DEF-038_tree_open_run.json`. The fix was refined three times before any candidate, each time on a failing browser record: it first reopened the previous run while the page's own address write was in flight (`VAL-DEF-038_selfwrite_reopen.json`); then browser Forward to an opened run did not reopen it (`VAL-DEF-038_forward_not_reopened.json`); then Back followed quickly by Forward ended on the run Back had started, because the page wrote its previous run's state onto the entry being opened before the new run's load was visible to the address sync, and a replaced run panel's late read made its run active again (`VAL-DEF-038_forward_race_journey.json`, `VAL-DEF-038_forward_history_tail.json`, `VAL-DEF-038_forward_trace.json`, with the page's own history writes and the source of each active-run change). |
| Root cause | The page read `?run=` once per mount; and, once it followed the address, its address sync could write stale state during a navigation |
| Files | `components/whatif/whatif-workspace.tsx`: every change of the address's run opens that run unless the page wrote it; a later change supersedes a load in flight; the address sync writes only a changed state, never while a run is being opened or while the browser's address and React's view of it differ; a run panel's update counts only for the application it belongs to |
| Test | `GW-CTL-METHODS` (tree open run with Back, Forward and in-product Back; CORP-03 started after CORP-02 stays on CORP-03); `GW-CTL-WHATIF` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-039: Address-sync race (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | What-If: load a scenario, clear it at once; then refresh |
| Expected | No scenario |
| Actual | The scenario came back (3 of 6 runs) |
| Evidence | `prefix_evidence/VAL-DEF-039_prefix_race.txt` |
| Root cause | Each write compared with `window.location`, which lags an in-flight `router.replace` |
| Files | `lib/workspace/address.ts` (new), used by What-If, Scenario Library, Monitoring, Lens view, Lens Library, Metric Catalogue |
| Test | `GW-CTL-WHATIF`, `-SCN`, `-MON`, `-LENS`, `-METRICS` (address equals state after every control) |
| Retest | PASS (6 of 6) |
| Disposition | FIXED |

### VAL-DEF-040: Metric Catalogue filters lost on Back (LOW)

| Field | Detail |
|---|---|
| Evidence | `prefix_evidence/VAL-DEF-040_041_metrics_prefix.json` |
| Files | `components/metrics/metric-catalogue.tsx` (`q`, `domain`, `family` in the address) |
| Test | `GW-CTL-METRICS` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-041: Breakdown book switch sent an invalid dimension (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | A metric on both books → breakdown book Corporate → Retail |
| Expected | Retail broken down by a Retail dimension |
| Actual | `POST /metrics/evaluate` 422 INVALID_DIMENSION (sector on Retail); the breakdown vanished |
| Evidence | `prefix_evidence/VAL-DEF-040_041_metrics_prefix.json` |
| Files | `components/metrics/metric-catalogue.tsx` (dimensions filtered to the book's grid schema) |
| Test | `GW-CTL-METRICS` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-042: `run=` dropped while a run reopened (LOW)

| Field | Detail |
|---|---|
| Evidence | `prefix_evidence/VAL-DEF-042_run_param_dropped.json` |
| Files | `components/whatif/whatif-workspace.tsx` (the reopened run is the active run as soon as it is read) |
| Test | `GW-CTL-METHODS` (result → open run: Forward and refresh keep the run) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-043: An empty population refused by the macro-sensitivity panel (LOW)

| Field | Detail |
|---|---|
| Reproduction | What-If grid: filter "prior PD is empty" (no rows) |
| Expected | The panel says no exposure matches, as the grid and explorer do |
| Actual | `POST /whatif/sensitivity/tornado` 422 EMPTY_POPULATION, shown in red, plus a browser console error |
| Evidence | `prefix_evidence/run_all1_ctl_prefix.json` (`grid-filter-nulls`), `VAL-DEF-043_prefix_pytest.txt` |
| Files | `backend/workspace/macro_sensitivity.py` (200 with no bars and `empty: EMPTY_BY_FILTER`), `components/whatif/macro-tornado.tsx` (neutral notice) |
| Test | `test_val_def_043_an_empty_population_is_a_tornado_state_not_a_refusal`; `test_gw_macro_tornado.py` (contract updated: invalid parameters still refused); mutation gate; `GW-CTL-GRID` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-044: A link's origin lagged the page's own address (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | What-If → Ask → "Use this conversation's cohort" → "Open full conversation" → Back to What-If |
| Expected | What-If on the adopted cohort |
| Actual | What-If on the cohort active before adopting (`back=` carried the previous address) |
| Evidence | `prefix_evidence/VAL-DEF-044_whatif_stale_origin.json` (reproduced twice) |
| Root cause | `withBack` read `window.location` during render; the render that follows a state change precedes the address commit, and nothing re-renders the link after it |
| Files | `lib/workspace/nav.ts` (`currentAddress`: the address in flight, else the committed one), `lib/workspace/address.ts` (publishes and settles it) |
| Test | `nav.test.ts` NAV04; `GW-CTL-WHATIF` (`whatif-open-thread` Back) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-045: Lens "Save as a new version" double-submitted (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Lens → Edit → double-click "Save as a new version" |
| Expected | One new version |
| Actual | Two `POST /lenses/{id}/revise` 200: two versions |
| Evidence | `prefix_evidence/run_all1_ctl_prefix.json` (`lens-edit-form`) |
| Root cause | A `busy` state flag disables the button only after the next render; a double-click fires twice before it. The same helper pattern was in the Lens Library, Monitoring (alert actions and the scheduler step), scenario builder, overlap resolve, run panel, Messages and the export package |
| Files | `lens-view.tsx`, `lens-library.tsx`, `monitoring-centre.tsx`, `scenario-builder.tsx`, `preview-panel.tsx`, `run-panel.tsx`, `messages-center.tsx`, `export-package.tsx` (a synchronous in-flight ref, as `useSingleFlight`) |
| Test | `GW-CTL-IDEMPOTENCY` (each mutating family double-clicked: exactly one write) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-046: "Opens my copy" had no origin (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Messages → shared definition → Duplicate → "opens my copy" → in-product Back |
| Expected | Back to the message |
| Actual | The Scenario Library |
| Evidence | `prefix_evidence/run_all1_ctl_prefix.json` (`message-note-link`) |
| Files | `components/messages/messages-center.tsx` |
| Test | `GW-CTL-MSG` |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-047: Forward lost an unsaved Lens proposal (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Thread → "Save this analysis as a Lens" → browser Back → Forward |
| Expected | The same proposal |
| Actual | The library without it: the page removed `from_thread` from its own history entry once it proposed |
| Evidence | `prefix_evidence/run_all1_ctl_prefix.json` (`thread-save-as-lens`) |
| Files | `components/lenses/lens-library.tsx` (the origin stays in the address until the Lens is saved; saving drops it from that entry before opening the Lens, so Back never re-proposes a saved Lens, as VAL-DEF-019 requires) |
| Test | `GW-CTL-THREAD` (Back, Forward, in-product Back; no write on the return trip) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-048: A cleared Lens selection stayed on the chart (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Lens breakdown → box-select two bars → Clear → box-select the same bars |
| Expected | The chart clears; the second selection selects |
| Actual | The box and highlighted bars stayed; the second drag deselected them and no selection was made |
| Evidence | `prefix_evidence/VAL-DEF-048_probe.txt`, `VAL-DEF-048_lens_reselect.json` |
| Root cause | `uirevision` keeps reader state (zoom, legend) across re-renders, selections included |
| Files | `components/lenses/lens-view.tsx` (a `selectionrevision` that changes on Clear) |
| Test | `GW-CTL-LENS` (`lens-selection-clear` asserts panel, address and chart cleared; the next box-select selects) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-049: Re-adopting a conversation's cohort made another cohort (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | What-If conversation → "Use this conversation's cohort" twice; or a Lens proposal from that conversation re-made |
| Expected | The same governed cohort |
| Actual | A new cohort object each time |
| Evidence | `prefix_evidence/VAL-DEF-049_prefix_pytest.txt` |
| Files | `backend/workspace/whatif.py` (`adopt_thread_cohort` returns the cohort already adopted for the same conversation, run, release and membership) |
| Test | `test_gw_whatif.py::test_val_def_049_adopting_a_conversation_cohort_again_is_the_same_cohort`; mutation gate |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-050: An administrator recipient changed the sender's object (HIGH)

| Field | Detail |
|---|---|
| Reproduction | As an administrator, receive a shared definition → "Run on my cohort" (What-If binds it to the cohort); receive a shared Lens → Save |
| Expected | The recipient gets their own copy; the sender's object is unchanged |
| Actual | A new version of the SENDER's scenario ("bound to cohort …", authored by the recipient); the sender's Lens renamed "(my copy)" in place |
| Evidence | `prefix_evidence/VAL-DEF-050_prefix_pytest.txt`; the browser run showed version 3 of the sender's scenario written by the recipient |
| Root cause | Recipient-side use actions decided "edit in place" with `can_edit`, which grants administrators edit rights on any object |
| Files | `backend/workspace/scenarios.py` (`bind`: in place only for the owner or a named editor), `lenses.py` (`revise(copy=True)`), `messages.py` (Save always copies) |
| Test | `test_gw_messages.py::test_val_def_050_an_administrator_recipient_never_changes_the_senders_object`; two mutation gates; `GW-CTL-MSG` (the sender's version unchanged across "run on my cohort") |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-051: A version-labelled scenario link opened the latest version (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Run a scenario, revise it, open the result → "Scenario … v1" |
| Expected | The scenario at v1, the version that ran |
| Actual | v2 (the link had no version) |
| Evidence | `prefix_evidence/VAL-DEF-051_probe.txt` (label v1, detail version 2) |
| Files | `components/whatif/result-page.tsx`, `components/whatif/scenario-application.tsx`, `components/scenarios/scenario-detail.tsx` (`?version=N`, which the detail page already honours for shared definitions) |
| Test | `GW-CTL-METHODS` (a scenario revised after its run: the result's link opens the version that ran); `whatif-bound-scenario` (the version shown) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-052: A Lens copy opened without its origin (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | LENS-01 → Edit → rename → "Save as a new version" (a library Lens becomes my copy) → in-product Back |
| Expected | Back to LENS-01 |
| Actual | The Lens Library |
| Evidence | `prefix_evidence/VAL-DEF-052_lens_copy_origin.json` |
| Files | `components/lenses/lens-view.tsx` (the copy opens with `withBack`, as every other navigation from the Lens view) |
| Test | `GW-CTL-LENS` (`lens-edit-form` as a Back trip with the copy's identity) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-053: Answered next-best questions came back (MEDIUM)

| Field | Detail |
|---|---|
| Reproduction | Investigate an issue → click the first suggested question → read the chips again |
| Expected | The answered question is not offered again; the next suggestion moves up |
| Actual | The same question, re-labelled "Re-offered: the active cohort changed since it was asked" although the investigation's cohort is fixed; "Monitor in a Lens" never reached the five chips shown |
| Evidence | `prefix_evidence/VAL-DEF-053_prefix_pytest.txt`; found by `GW-CTL-THREAD`, whose save/share/monitor chip never appeared |
| Root cause | The investigation passed the questions asked but not the cohort they were asked under; the ranking read the unknown scope as a changed cohort |
| Files | `backend/workspace/issues_api.py` (`_state`: every asked question is under the investigation's fixed cohort) |
| Test | `test_gw_guided.py::test_val_def_053_a_question_asked_in_the_investigation_is_not_offered_again`; mutation gate; `GW-CTL-THREAD` (the Lens Library hand-off from the investigation) |
| Retest | PASS |
| Disposition | FIXED |

### VAL-DEF-054: A run opened as a scenario (HIGH)

| Field | Detail |
|---|---|
| Reproduction | A template with runs → its page → "Used by" → a run |
| Expected | The run opens in What-If |
| Actual | `/scenarios/<run id>`: `GET /scenarios/<run id>` and its preview failed with HTTP 500 (`KeyError 'name'`, a run read as a scenario); the response had no CORS headers, so the page showed a failed fetch |
| Evidence | `prefix_evidence/VAL-DEF-054_browser.json` (`GW-CTL-SCN` on a fresh store, where the first descendant was a run); `VAL-DEF-054_prefix_pytest.txt` |
| Root cause | The descendant link assumed every descendant is a scenario; the scenario operations read objects without checking their kind |
| Files | `backend/workspace/scenarios.py` (`get_scenario`: another kind is a governed 422 NOT_A_SCENARIO in read, preview, revise, clone, combine, resolve, bind, results, retire and share), `scenarios_api.py`; `components/scenarios/scenario-detail.tsx` (a descendant opens by its kind: scenario, run in What-If, result), `lib/workspace/scenarios.ts` |
| Test | `test_val_def_054_a_non_scenario_id_on_a_scenario_route_is_refused` (seven routes; fails on the pre-fix code); mutation gate; `GW-CTL-SCN` (the first descendant of each kind, with its identity and Back) |
| Retest | PASS |
| Disposition | FIXED |
