# Phase ledger — Guided Risk Workspace (master specification v3.1)

Branch: `claude/eager-keller-7ue2yk` (designated session branch, playing the role of
`claude/advanced-cockpit-whatif-v2-productization`; see `BASELINE_PROVENANCE.md` §1).
Parent: H2 `feb80f58982addf6e9474200b22451d1e303d276`.

Status words: NOT STARTED · IN PROGRESS · PASS · PARTIAL · BLOCKED · FAILED.
PASS means the phase's exit gate was proven by the named tests/journeys, not
that files exist. Evidence labels: every browser journey here is MODEL MOCK
(scripted analyst; no provider credential in this container).

---

## P0 — Baseline, branch, data and provenance freeze

* **Requirements:** §4, §43 P0, §40 G0 — verify H1/H2/H3, clean tree, protected
  baseline, release fingerprints, emulator artifacts, runtime prerequisites; record
  seams; inventory pages/routes/charts/grids/scheduler/Messages/Lenses/EW/What-If.
* **Inspected:** all remote branches and tags; `docs/whatif/*` (FINAL_STATUS,
  HANDOFF, BASELINE_AND_EXTENSION_MAP, KNOWN_LIMITATIONS, PROTECTED_CORE_INCOMPATIBILITY);
  `backend/cockpit_v4/{app,routes,worker,provider,service,catalog,domains}.py`;
  `backend/cockpit_v4/scenario/*`; `backend/llm/*`; `frontend/src/**` (routes,
  navigation, cockpit-v4 components, lenses, early-warning, stress); launchers;
  browser harnesses. Four read-only inventory agents + direct reading.
* **Changed:** none of the product. Added `scripts/guided_workspace/protected_baseline.py`,
  `docs/guided_workspace/{BASELINE_PROVENANCE,ARCHITECTURE,PHASE_LEDGER}.md`,
  `PROTECTED_FILES_H2.sha256`, `evidence/p0_*`.
* **Protected-core changes:** none.
* **Measured:** H1 ancestor of H2 ✔; H3 absent ✔; branch fast-forwarded to H2 ✔;
  candidate books reproduce `3b101bd4…`/`98b494ae…` exactly; accepted books do not
  reproduce the earlier container's byte fingerprints (documented, content digests
  recorded); emulator gates reproduced (Corporate all PASS; Retail G4 0.3436 FAIL);
  H2 protected manifest 171 files, 0 drift.
* **Baseline regression at H2 (isolated worktree, before any edit):** see §"Baseline counts" below.
* **Status:** PASS (exit gate: provenance, fingerprints/content digests, protected report and baseline counts recorded; parent SHA committed in `928c70bf`)

## P1 — Platform observability first: Full LLM Exchange Trace

* **Requirements:** §43 P1, §47; exit gate: byte-equivalence/sanitization, zero
  behaviour drift, reopen makes zero model calls, exports reproduce records,
  Opus/open-weight call comparison.
* **Files changed:** `backend/llm/exchange.py` (new), `backend/llm/openai_compatible.py`
  (new), `backend/llm/anthropic_provider.py` (2 passive hooks),
  `backend/workspace/{__init__,flags,access,exchange_api,api}.py` (new),
  `backend/cockpit_v4/worker.py` (protected, 1 argument), `backend/cockpit_v4/app.py`
  (protected, flag-gated mount), `frontend/src/app/cockpit/trace/[runId]/page.tsx`
  (protected, 1 link), `frontend/src/app/trace/llm-exchange/[runId]/page.tsx`,
  `frontend/src/app/ai-model-lab/page.tsx`, `frontend/src/components/llm-exchange/*`,
  `frontend/src/components/viz/*`, `frontend/src/lib/viz/*`,
  `frontend/src/lib/workspace/*`, `frontend/src/lib/navigation.ts`,
  `frontend/package.json` (plotly.js-dist-min 3.7.0).
* **Protected changes:** rows 1–3 of `PROTECTED_EXTENSION_MAP.md`.
* **Tests added:** `tests/cockpit_v4/test_gw_llm_exchange.py` (27);
  `frontend/src/lib/viz/{format,palette}.test.ts`,
  `frontend/src/lib/workspace/llm-exchange-figures.test.ts` (12);
  browser `GW-P1-01..03`.
* **Tests run / measured:** P1 backend 27/27; frontend unit 12/12; `tsc --noEmit`
  clean; seam regression (payload snapshot, provider payload/isolation/schema,
  orchestration recovery/latency, What-If routes/tenancy, `tests/llm`) 181 passed /
  2 skipped (flags off) and `tests/llm` 17/8-skipped identical to H2; browser 3/3.
* **Remaining:** a live Opus-vs-open-weight comparison needs a credential and an
  endpoint → P14 (BLOCKED here). Full-suite zero-drift proof is re-run at P13.
* **Status:** PASS (exit gate proven with MODEL MOCK + injected SDK/transport)

## P2 — Shared object model and continuity contracts

* **Entry check:** P1 exit gate proven (27 backend, 12 frontend unit, 3 browser).
* **Requirements:** §43 P2, §29, §34 — governed identities for Cohort, Finding,
  Investigation, Scenario, Scenario Result, Lens, Metric, Alert, Message
  attachment; id/version/owner/domain/release/fingerprint/period/permissions/
  lineage/trace on every object; identity preserved across modules.
* **Files:** `backend/workspace/{store,objects,service,predicates,grid,ews,cohorts,objects_api}.py`
  (new), `backend/workspace/api.py`, `frontend/src/lib/workspace/objects.ts`.
* **Design:** one INSERT-only versioned `objects` table (triggers refuse UPDATE and
  DELETE), content hash verified on every read, append-only comments/shares/
  observations/alert events. Cohorts freeze through the What-If engine's own
  `scenario.cohort.freeze` over a governed latest-period grid view (joined borrower/
  customer, prior period, collateral, covenants, IFRS 9, behaviour and the governed
  EWS rule set `gw-ews-1.0.0`), so a cohort's membership hash is exactly the one the
  scenario engine re-verifies. Filters compile to bound parameters (grid) or
  allowlisted literals (freeze); a request can never name a tenant, relation or release.
* **Protected changes:** none.
* **Tests:** `tests/cockpit_v4/test_gw_objects.py` — 28 passed (every kind round-trips
  with hash; incomplete refused; immutable/undeletable; tamper refused; revise keeps
  old version; non-owner duplicates; privacy/tenancy; lineage tree; filter injection
  refused; bound SQL carries no user text; cohorts freeze/reopen IDENTICAL on both
  books; joined-column filter; one-customer owner selection; refresh = new version;
  EW→Cockpit→What-If identity by membership hash; API round trip; tenant cannot be
  named; comments bound to versions).
* **Status:** PASS

## P3 — Guided Cockpit: Requires Attention

* **Entry check:** P2 exit gate proven (28 backend tests; cohort identity by membership hash).
* **Requirements:** §43 P3, §8–§9 (Guided Cockpit, Requires Attention cards, investigation
  path, next-best questions, no causal claims, free-form Ask preserved), §10 (Plotly
  standard for every new chart), §46 (metric catalogue depth used by issues), EWS in V4.
* **Files inspected:** `cockpit-v4-home.tsx`, `thread-view.tsx`, `attention-panel.tsx`,
  `backend/cockpit_v4/{context,investigation,store}.py` (seeded-thread mechanism),
  `scripts/whatif/whatif_stub_server.py`.
* **Files changed / added:**
  * backend (new): `backend/workspace/{metric_catalog,metrics,metrics_api,issues,issues_api,nbq,usage,grid_api}.py`;
    `api.py`, `ews.py`, `grid.py` extended.
  * frontend (new): `lib/viz/figures.ts`, `lib/workspace/guided.ts`,
    `components/guided/{requires-attention,investigation-bar,issue-detail,early-warning-v4,domain-toggle}.tsx`,
    `components/workspace/data-grid.tsx`, `app/issues/[issueId]/page.tsx`; `app/early-warning/page.tsx`
    renders the V4 Early Warning when V4 + guided are on; `plotly-chart.tsx` resize guard.
  * harness: `scripts/guided_workspace/guided_script.py` (scripted analyst for guided turns
    on either book, MODEL MOCK), `gw_stub_server.py` installs it, `browser_evidence.py` sets
    `NEXT_PUBLIC_GUIDED_WORKSPACE=1` for the UI only.
* **Design:** issues are measured, not generated: 19 governed detection patterns
  (`gw-issues-1.0.0`, 10 Corporate + 9 Retail; book/segment level, delta and excess modes)
  over the 64-metric catalogue (`gw-metrics-1.0.0`). Each card carries the rule id and
  version, the metric, current/prior values from published rows, materiality (affected
  entities/owners/EAD/ECL, share of book ECL), a fact vs measured-association split, a
  sparkline, and 2–5 next-best questions from `nbq.py` (typed, sourced, rationale stated;
  causal wording refused; answered ones suppressed until the cohort hash changes; a
  What-If chip only once a Finding exists and labelled "not a forecast"). "Investigate"
  freezes the issue population as a governed cohort, creates an Investigation object and
  opens an ordinary Cockpit thread seeded through the existing `attention_item` context
  (no orchestration change). Chips submit through the thread's own `ask`; the click is
  recorded on the Investigation with suggestion id, rationale, source and exact request.
  Issue detail: four Plotly charts, each with View data / CSV / PNG / SVG; a driver bar
  click becomes a server-side filter on the governed grid.
* **Measured:** Corporate 10 issues, Retail 8 issues (17 rules firing, 18 cards); detection
  ≈3.7 s Corporate / ≈2.9 s Retail cold, cached thereafter; all 64 metrics evaluate on both books.
* **Protected changes:** `cockpit-v4-home.tsx` (+10 lines), `thread-view.tsx` (+11 lines),
  both flag-gated; rows 4–5 of `PROTECTED_EXTENSION_MAP.md`. Lint output on both files is
  identical to H2 (2 pre-existing errors, 3 warnings in `thread-view.tsx`).
* **Tests:**
  * `tests/cockpit_v4/test_gw_guided.py` — 17 passed (full gw backend set 72 passed).
  * `frontend/src/lib/viz/figures.test.ts` — 7 passed (FIG01–FIG07); `npm test` 612/612; `tsc` clean;
    eslint clean on every new directory.
  * Browser (MODEL MOCK, real UI/API/stores/books) `GW-P3-01-CORP`, `GW-P3-01-RET`, `GW-P3-02`,
    `GW-P3-03`, `GW-P3-04` — 5/5; full suite with P1 8/8
    (`docs/guided_workspace/evidence/journeys.json`, screenshots under `evidence/journeys/`).
* **Limitations:** the Retail salary-credit rule is a stated proxy (the book has no salary
  feed); NBQ ranking is rule-based, not learned; guided turns in the browser suite are
  scripted (MODEL MOCK).
* **Status:** PASS

## P4 — Scenario Library foundation

* **Entry check:** P3 exit gate proven (17 backend, 7 figure unit tests, browser GW-P3 5/5).
* **Requirements:** §43 P4, §44 (≥36 templates, 18 per book, ≥6 combined/macro, every
  card opens a real preview), §30.1–30.3 (scenario independent of execution and method,
  component library, composition with component + overlap matrix and explicit policy),
  §6.1–6.4 (units never confused; governed macro/rating/score translation), SC-01..SC-07,
  SC-10, MSG-01/02.
* **Files inspected:** `backend/cockpit_v4/scenario/{spec,units,fields,delta,preview}.py`,
  `scenario/mappings/{ratings,scores,stages,sectors}.py`, `scenario/sensitivity/artifact.py`,
  `scenario/ml/infer.py`; candidate relations `whatif_*_{sensitivity,mev_registry,macro_*,rating_map,score_map}`.
* **Files added:** backend `backend/workspace/{scenario_seed,scenario_library,scenarios,scenarios_api}.py`
  (router mounted in `api.py`); frontend `lib/workspace/{scenarios,scenario-figures}.ts`,
  `components/scenarios/{preview-panel,scenario-library,scenario-detail,scenario-builder,guided-off}.tsx`,
  routes `/scenarios`, `/scenarios/new`, `/scenarios/[scenarioId]`; nav item "Scenario Library".
* **Design:** templates are ordinary `scenario` objects seeded per tenant, idempotently
  (`gw-scenario-seed-1.0.0`), owned by the library, tenant-visible and read-only (clone to
  change). Components are typed (parameter, utilisation, rating, score, delinquency, macro,
  collateral, overlay) and checked against the book's own field dictionary and operation
  vocabulary. Translation uses only governed artefacts: MEV sensitivities through
  `sensitivity.artifact.translate` (SUPPORTED_ESTIMATE only; DIAGNOSTIC_ONLY listed as not
  applied; ABSENT factors unsupported; bps↔pp and relative↔native conversions stated),
  the rating masterscale by `grade_rank`, and the product scorecards by band (behavioural
  and application never substituted). No governed mapping → NEEDS_USER_MAPPING, never a
  guess. Overlaps are detected per variable family on the actual intersecting population;
  macro-with-macro is the governed §7.2 linear sum; every other overlap blocks until an
  explicit policy (compound / additive where valid / max / min / priority) is recorded.
  Combining creates a NEW definition whose components carry their source object, version and
  scope; sources are never written. ML availability is read from the emulator's gates
  (Retail G4 0.3436 > 0.15 → UNAVAILABLE, shown with the reason). The preview never
  calculates ECL and no definition selects a method.
* **Measured:** 36 templates (18 CORP, 18 RET; 11 tagged macro/combined); all 36 preview on
  the candidate books in 0.05–0.5 s each. Seeded readiness (measured): 27
  READY_FOR_CONFIRMATION; 6 READY_WITH_USER_DEFINED_INPUTS (CORP-16, RET-04, RET-05,
  RET-08, RET-14, RET-17); 3 BLOCKED by design (CORP-18 and RET-18 need the composition
  choice §44 requires; RET-02 carries the unsupported Retail CCF rule; none hidden). RET-07 flags SIGN_REVIEW: the governed MEV09 slope lowers LGD when property
  prices fall on this synthetic history; shown, not corrected.
* **Protected changes:** none.
* **Tests:**
  * `tests/cockpit_v4/test_gw_scenarios.py` — 37 passed (gw backend total 109).
  * `frontend/src/lib/workspace/scenario-figures.test.ts` — 7 passed (SCN01–SCN07);
    `npm test` 619/619; `tsc` clean; eslint clean on new code.
  * Browser (MODEL MOCK not involved: no model call) `GW-P4-01`..`GW-P4-04` — 4/4; full
    suite 12/12.
* **Limitations:** execution of a definition is P6 (METHOD_SELECTION, dual-scope
  decomposition); Messages inbox/thread UI for shared scenarios is P7 (shares are stored
  now as object reference + version cards); delinquency, vehicle collateral and
  application-score components need a user-defined impact because no governed mapping exists.
* **Status:** PASS

## P5 — What-If Analysis workspace and cohort explorer

* **Entry check:** P4 exit gate proven (37 backend, 7 unit, browser GW-P4 4/4).
* **Requirements:** §43 P5, §8 (workbench composition, grid, filters, selection, export),
  §8.3 grid fields, §10.1 interaction, §29 (one cohort across modules), §30 (one engine,
  two entrances), GRID01–GRID21, SCEN13, SCEN15, CO-01/03, PV-02/03/06, SEC01/SEC04.
* **Files inspected:** `scenario/{bridge,selector,cohort,thread,delta,rules,sql,spec}.py`,
  `cockpit_v4/{context,routes,run_store}.py` (the `ui_filters` channel, thread context),
  `components/cockpit-v4/{client,thread-view,cockpit-v4-home}.tsx`, `app/stress/page.tsx`.
* **Files changed / added:**
  * engine (unprotected): `scenario/cohort_refs.py` (new resolver hook); `scenario/selector.py`
    (`{"cohort_id": ...}` selection); `scenario/bridge.py` (preview resolves a named cohort and
    refuses unless the frozen membership hash equals the saved one).
  * workspace: `whatif.py`, `whatif_api.py`, `sharing.py` (new); `cohorts.py` (stored engine
    predicate, `adopt`, `resolve_stored`, `engine_resolver`); `api.py` (mounts + registers).
  * frontend: `app/what-if/page.tsx`, `components/whatif/{whatif-workspace,portfolio-explorer,
    scenario-application}.tsx`, `lib/workspace/{whatif,whatif-filters}.ts`; `app/stress/page.tsx`
    redirects to `/what-if` when the guided flag is on; nav label "What-If Analysis" replaces
    "Stress Testing" (flag-gated; flags-off nav unchanged); `data-grid.tsx` gained
    `selectionResetKey` and content-keyed locked filters (fixes a query abort loop found here).
  * harness: `guided_script.py` answers a What-If scenario question by naming the active cohort.
* **Design:** the population is always a governed cohort. A question typed on the page is an
  ordinary Cockpit run whose `ui_filters` carry the active cohort by reference (existing
  channel, no orchestration change); the analyst's `preview_scenario` names it as
  `{"cohort_id": ...}` and the engine freezes that cohort's server-written predicate and
  verifies the membership hash. The reverse route adopts a conversation's frozen cohort as a
  governed cohort only if the hash is identical. Charts and grid share one filter state
  (server `/grid/group`); click toggles a category filter, box/lasso sets several. Apply
  Scenario binds the loaded Scenario Definition to the cohort (template untouched) and
  previews it; execution is P6.
* **Measured:** Corporate grid 2,996 facilities at 2026Q2; Retail 6,702 accounts at 2026-08;
  Construction click → 248 facilities / 100 borrowers; box-select of two sectors → 496; manual
  5-row selection → conversation cohort 5 entities with membership hash identical to the saved
  cohort (GW-P5-04 records both hashes); adopted cohort hash identical; a joined-column cohort
  (rating B/B+ in Construction) bound by reference with identical hash.
* **Protected changes:** none (the embedded conversation reuses `CockpitV4Thread` unmodified).
* **Tests:**
  * `tests/cockpit_v4/test_gw_whatif.py` — 20 passed (gw backend total 129).
  * Mutation: disabling the bridge's membership-hash check makes
    `test_a_named_cohort_whose_rows_moved_is_refused` fail; restored, it passes.
  * Engine regression: `pytest tests/cockpit_v4 -k "whatif and not gw_"` — 973 passed, 3 failed
    (the three environment-bound baseline failures recorded at P0), 2 skipped.
  * `frontend/src/lib/workspace/whatif-filters.test.ts` — 5 passed (WIF01–WIF05); `npm test`
    624/624; `tsc` clean; eslint clean on new code.
  * Browser `GW-P5-01`..`GW-P5-06` — 6/6; full suite 18/18.
* **Status:** PASS (execution of an applied scenario is P6's gate)

## P6 — Method selection, ECL execution, universal Plotly decomposition
* **Delivered:**
  * **Method gate (engine, both entrances).** SCENARIO and METHOD are separate decisions.
    `ScenarioSpec.methods` defaults to `()`; the method is no longer part of the scenario
    contract (`canonical()`), so choosing or changing it reuses the same confirmation.
    `bridge.execute_scenario` with no chosen method returns `METHOD_SELECTION_REQUIRED`
    ("Scenario confirmed — NOT executed"), offers Delta / ML / User-defined / Compare with
    availability, and computes nothing. User-defined without input → `METHOD_INPUT_REQUIRED`;
    every chosen method unavailable → `METHOD_UNAVAILABLE`; no ML→Delta fallback, no Delta
    default anywhere (parser, preview, thread, workspace).
  * **What-If runs** (`backend/workspace/runs.py`, `runs_api.py`, object kind `run`):
    `WAITING_BASELINE_CHOICE → SCENARIO_PREVIEW → SCENARIO_CONFIRMED → METHOD_SELECTION →
    [METHOD_INPUT_REQUIRED | METHOD_UNAVAILABLE] → READY_TO_EXECUTE → EXECUTED`, every
    transition a new object version with a state log. Execution rebuilds the engine contract
    from the pinned scenario version + re-frozen cohort and refuses unless it hashes to the
    confirmed digest; results persist as `scenario_result` objects. "Same scenario, another
    method" derives a new run at METHOD_SELECTION on the same confirmed contract (BASE06).
  * **One engine.** `scenario_engine.build` turns any Scenario Definition + governed cohort into
    ONE engine `ScenarioSpec` (parameter/utilisation shocks; macro and collateral via the
    governed sensitivity translation, macro merged as the §7.2 linear sum; rating and score via
    masterscale / scorecard PD ratios; member-list scoping; explicit overlap policies —
    compound declared to the engine, priority/max/min partition rows, additive merged). Runs
    execute through `bridge.compute_core`, the same object the Cockpit uses: the UAT scenario's
    Delta change is equal on both entrances to 1e-6 and the membership hashes are identical.
    All 36 seeded templates build; the 6 whose components have no governed translation for a
    method (e.g. RET-05 delinquency, RET-08 vehicle collateral, CORP-16 overlay) show that method
    `BLOCKED` by name and remain runnable under User-defined.
  * **Lineage.** A second run in a What-If session (or a second preview in a Cockpit thread) asks
    "original reported baseline, or layered on which executed scenario?" and never assumes.
    Layering reuses `scenario.layering` (overlay chain on copies of the rows, digest-verified
    ancestors, book offset); A, B, A+B, A+B+C persist their chain. Layering on a parent run
    that has no Delta row state is refused with the reason.
  * **Universal decomposition** (`scenario/decomposition.py`, contract `gw-decomposition-1.0.0`):
    20-component taxonomy (Opening, New originations, Repayment, Stage 1→2, Stage 2→3, Cures,
    New defaults, PD, LGD, CCF/EAD/utilisation, Collateral, Rating/score, Macro, Sector/segment,
    Management overlay/user-defined, Recoveries, Method effect (not attributable), Calibration
    gap, Residual, Closing). Every result carries selected scope AND total book from one
    execution; `opening + components + residual = closing` per scope and
    `selected Δ + rest-of-book Δ = total Δ` are checked before publication and re-checked in the
    browser from the published strings. Components not measured are `N/A` with the reason.
  * **Plotly contract** (`frontend/src/lib/viz/decomposition.ts`, `components/whatif/result-view.tsx`):
    per-component colour (20 distinct; palette ids/labels pinned to the server taxonomy by
    `test_gw_decomposition_palette.py`), selected and total bridges on one scale with identical
    x order and colours, click-to-highlight across both charts and the table, compact toggle for
    N/A bars, cut axis labelled "Axis does not start at zero" when movement is small against
    the level, KPI strips, cross-scope identity strip, method comparison, stage before/after,
    largest contributors; every chart with View data / CSV / PNG / SVG; the table beneath lists
    all 20 components for both scopes.
  * **Entrances.** What-If (Run panel under the applied scenario; `?run=` reopens a run where it
    stopped, a confirmed run reopens at METHOD SELECTION); Scenario Library ("Open in What-If
    (preview, confirm, choose method, run)", results list per scenario, `/what-if/result/[id]`);
    Cockpit (thread strip shows "confirmed — NOT executed" with the four methods as ordinary
    turns; an executed thread opens as a governed Scenario Result without recomputation,
    `POST /whatif/threads/{id}/adopt-result`, idempotent per run). Messages entrance is P7.
* **Engine defects found and fixed (all present before this round):**
  * Corporate CCF is DERIVED; the cohort read never supplied it, so every CCF shock raised
    `KeyError('ccf')` (Cockpit included). Derived per row as `delta.baseline_ccf` defines it.
  * Retail LGD Delta raised `KeyError('write_off_sar_mn')` (eligibility predicate column not read).
  * Whole-book ledger rejected float noise (`outside_cohort < 0` → `< -CURRENCY`).
* **Accepted tests changed (they encoded UAT-01):** `test_whatif_spec.py` (method no longer in
  the contract; default `methods == ()`), `test_whatif_preview.py` (explicit methods; new
  no-method test), `test_whatif_thread_context.py` (stored spec names its method),
  `test_whatif_bridge.py` (the "narrowing after confirmation" refusal replaced by
  `test_a_method_chosen_after_confirmation_reuses_the_same_approval`). `palette.test.ts` (P3)
  updated for the full taxonomy order.
* **P4 findings preserved:** RET-07 / CORP-03 collateral `SIGN_REVIEW` (LGD moves down when
  collateral falls) survives into the run preview and the persisted result notes, shown in red;
  the collateral bar is negative and is not corrected. Retail ML: `UNAVAILABLE — G4 0.343562 >
  0.15` on every surface; refused when chosen.
* **Tests:**
  * `test_gw_method_gate.py` 16 (13 passed + 3 ML-runtime skips on the accepted interpreter;
    16/16 on `.venv-whatif`) — includes the exact UAT reproduction (Construction, 248 facilities,
    100 borrowers, PD ×1.20, LGD ×1.10, stages frozen, confirmed, no method → not executed).
  * `test_gw_runs.py` 19/19 (workspace UAT, empty choice, parity with the Cockpit, dual-scope
    identities, Retail ML refusal + compare, UD input, BLOCKED components, SIGN_REVIEW, CCF,
    baseline question, A/B/A+B/A+B+C, refused layering, rerun, stale confirmation, owner-only,
    listing, Cockpit result adoption).
  * `test_gw_decomposition.py` 15/15; `test_gw_decomposition_palette.py` 2/2.
  * Frontend `decomposition.test.ts` DEC01–DEC08 on a real engine decomposition (CORP-18);
    `npm test` 633/633; `tsc` clean; eslint: 0 problems in new code (15 pre-existing in
    protected `components/cockpit-v4/*`, `thread-view.tsx` unchanged at 2 errors / 3 warnings).
  * Mutation proofs: (a) reinstating `_methods(None) → (DELTA,)` fails 6 gate tests;
    (b) making workspace confirm fall through to Delta fails both workspace UAT tests;
    (c) removing the CCF derivation fails `test_ccf_runs_on_the_derived_conversion_factor`.
  * Regression: `tests/cockpit_v4 -k "whatif or gw_"` accepted interpreter **1153 passed,
    3 failed (the 3 baseline env-bound), 5 skipped**; `.venv-whatif` GW + bridge + ml
    **157 passed, 8 failed (exactly the 8 baseline-known)**.
  * Browser (MODEL MOCK scripted analyst, real UI/API/stores/books) `GW-P6-01` (What-If UAT →
    METHOD SELECTION, crafted execute 409, reopen, Delta, reconciled dual-scope Plotly with 20
    components and ≥15 distinct colours), `GW-P6-02` (Retail ML refused, then Delta),
    `GW-P6-03` (baseline question; A → B on A → C on A+B, chain persisted), `GW-P6-04` (Cockpit
    UAT → METHOD SELECTION → Delta as an ordinary turn → governed decomposition → back to the
    thread) — **4/4**.
* **Protected files:** none added; check still 5 changed vs H2, all mapped (the Cockpit strip
  rides the existing P3 `InvestigationBar` hook, an unprotected component).
* **Open for P13:** accepted What-If browser journeys that preview a second scenario in one
  thread now meet the baseline question (BASE01) — to be re-run and, where they encode the
  old silent-baseline behaviour, recorded like the accepted unit tests above.
* **Status:** PASS

## P7 — Composition, branching, lineage and collaboration
* **Delivered:**
  * **Messages** (`backend/workspace/messages.py`, `messages_api.py`, `/messages`, nav "Messages"
    under Work, flag-gated): a message is an object reference (id + version + card). Inbox /
    Sent, unread count, read receipts. Recipient actions by kind — scenario definition: Open,
    Run on my cohort or book, Duplicate/branch, Comment; executed result: Open analysis, Compare
    with my results, Re-run on the latest data, Run on my cohort, Duplicate the definition, Save a
    copy, Comment (a Cockpit-executed result offers Open the conversation instead of re-run);
    cohort: Open in What-If, Investigate in Cockpit, Save a copy, Comment; comparison: Open,
    Save a copy, Comment. Only actions that work are shown.
  * **Run from a message** is the recipient's OWN run (session `msg-<share>`), still preview →
    confirm → METHOD SELECTION → method; its run and result carry `shared_from`
    (share, object, version, sender); the sender's objects are never changed. A second run from
    the same message is asked for its baseline.
  * **Permissions.** Sharing names the recipients as readers of the object and of what it needs
    to be opened or re-run (a result's scenario version and cohort, a scenario's bound cohort, a
    comparison's results) — identity only, same tenant; the card lists them. Read access is now
    object-level (`ObjectService.get` checks the latest version's permissions), so a share pinned
    to v1 stays openable after the object moves to v2; the recipient sees "newer version exists".
    Bystanders and other tenants get 404 for the message and the object; a recipient cannot
    re-share a private object (403); only the recipient acts on a message (403 for the sender).
  * **Comparison** object kind (`backend/workspace/comparisons.py`, `POST /whatif/compare`,
    `/what-if/compare/[id]`): same book and period and a method every result ran, else refused
    with the reason; KPIs of both scopes and all 20 components per result, COPIED from the
    published decompositions (nothing recomputed); grouped Plotly by component with View data /
    CSV / PNG / SVG; shareable.
  * **Scenario tree** (`GET /whatif/tree`, What-If "Scenario tree — this session"): original
    baseline at the root, scenarios and layered children, method re-runs as variants of the run
    they re-used, combined definitions marked with their parts; each node shows cohort, state,
    methods, Δ per method and links to its result or run; tick two nodes to compare; "New
    session" starts a fresh lineage context.
  * **Share** button on every result and comparison (and the existing scenario / cohort shares).
  * **First launch** (§44): the synthetic colleague `head-of-corporate-credit.synthetic` shares
    "Construction Downside Sep-26" (defined, not executed), a Delta-executed "GDP recession"
    result and the cohort "Hospitality — Stage 2 (synthetic demo)"; every message is prefixed
    `[SYNTHETIC DEMO]` and badged in the UI; seeded once per recipient.
* **Defects found by the journeys and fixed:** a method re-run lost its `rerun` lineage origin
  once revised (method chosen, executed), so the tree stopped showing it as a variant —
  `variant_of` is now in the run body (test strengthened; fails on the old logic); the tree's
  node component was defined inside its parent, remounting on every tick (checkbox detached) —
  hoisted.
* **Tests:**
  * `test_gw_messages.py` 13/13 (seeded inbox; definition → recipient's own linked run through
    the method gate; run on the recipient's cohort; duplicate/branch lineage; result → compare /
    re-run latest / save; comparison shareable with its results; incompatible comparison
    refused; comments on the shared version seen by both; pinned version openable after revision;
    bystander / other-tenant / re-share / sender-acts denials; shared cohort investigated; tree
    edges incl. a variant that ran; a private scenario's result carries what a re-run needs).
  * Mutation proofs: object-level read gate reverted → pinned-share test fails; dependency grants
    removed → comparison-sharing and private-result re-run tests fail; old variant detection →
    tree test fails.
  * `decomposition.test.ts` DEC09 (comparison figure); `npm test` 634/634; `tsc` clean; eslint 0
    problems in new code.
  * All GW backend suites (`-k gw_`, accepted interpreter): **193 passed, 3 skipped** (ML-runtime).
  * Browser `GW-P7-01` (seeded inbox; shared definition → own run → METHOD SELECTION → Delta →
    result linked to the definition), `GW-P7-02` (shared result → compare with mine → comparison
    Plotly; save copy opens; comment; open analysis), `GW-P7-03` (A, variant of A, B layered on A in
    the tree; compare from the tree; share → Sent), `GW-P7-04` (shared cohort → What-If with the
    same object; Investigate → Cockpit thread) — **4/4**.
* **Protected files:** none added (still 5, all mapped).
* **Status:** PASS

## P8 — Metric Catalogue 2.0
* **Delivered:**
  * **Persisted, versioned registry** (`backend/workspace/metric_registry.py`): each of the 64
    reviewed definitions in `metric_catalog.py` (`gw-metrics-1.0.0`) is published as a governed
    `metric` object (`met-m001`…, library-owned, tenant-visible, seeded). The catalogue API lists
    and COUNTS persisted objects; a definition whose text changes becomes a new version of the
    same object and the old version stays readable.
  * **Completeness:** every metric now carries every §46 field. 41 metrics had no
    thresholds/materiality and 14 no drill-down dimensions; each was given an explicit, labelled
    entry (change-detection materiality by unit with `basis` stating that no breach level is
    governed; explicit amber/red for freshness, refresh age, active breaches, material changes;
    scenario / sensitivity / platform drill-downs). Nothing existing was weakened.
  * **API:** `GET /metrics/{id}` (persisted object + users), `GET /metrics/{id}/lineage`
    (source relations/fields, executable SQL or evaluator, drill-down dimensions, Lenses / breach
    rules / Requires Attention detectors using it, version history), `GET /metrics/{id}/rows`
    now honours `filters` (drill from a clicked dimension to the exact rows).
  * **UI** `/metrics` (nav "Metric Catalogue" under Govern, flag-gated): search, book and family
    filters with an explicit EMPTY_BY_FILTER state; detail with every definition field, the
    executable SQL, live values on each applicable book (parts formatted in their unit), one
    trend per book (quarters and months never share an axis), breakdown by any grid drill-down
    dimension whose bar click drills to the rows, lineage, versions and users.
* **Defects found and fixed:**
  * Scenario metrics M039–M042 read a pre-P6 `headline` field that results do not have (they
    returned a count and `None` values). Rewritten over the published decomposition: M039 =
    selected-scope Δ, M040 = Δ / selected opening (null when opening ≤ 0), M041 = selected Δ /
    total Δ, M042 = the ML emulator's calibration gap (raw model baseline − observed modelled
    ECL), now persisted on every ML result (Workspace and Cockpit) so it is measured, never hidden.
  * Qualifying-population numerators (M004–M011, M014, M051, M054, M056, M062–M064) published
    NULL instead of a measured 0 when no row qualified (e.g. Stage 3 share on a book with no Stage
    3) — `ELSE 0` added; denominators and conditional weighted averages still return NULL when
    undefined. Found by the formula tests (4 failures before the fix).
* **Tests:** `test_gw_metrics.py` 14/14 — persisted count ≥ 50 equals the catalogue and is seeded
  once; all 50 §46 ids under their spec names; every field defined; a changed definition is a new
  version with the old readable; formula tests recomputed independently in Python from governed
  rows on both books (M001, M005–M007, M015, M016, M018, M020, M021, M052, M059, M060; M028/M029/
  M054 on Retail; M002/M003 as differences of M001; a filtered M001); every applicable metric
  evaluates on both books; M039–M042 against a real executed result; lineage and filtered drill
  (248 Construction rows). `metric-figures.test.ts` MET01–04; `npm test` 638/638; `tsc` clean;
  eslint 0 in new code. All GW backend suites 207 passed, 3 ML skips. Browser `GW-P8-01` 1/1.
* **Data note:** the Retail candidate book has no account at ≥ 30 DPD in any published month
  (max 28 days; all Stage 1), so M028/M029 are measured zeros there, not missing values.
* **Protected files:** none added (still 5).
* **Status:** PASS

## P9 — Lenses 2.0
* **Delivered:**
  * **Lens objects** (`backend/workspace/lenses.py`, `lenses_api.py`, `lens_seed.py`
    `gw-lens-seed-1.0.0`): identity, persona, audience, book scope and default filters, pinned
    metric ids + versions, visual specs (closed vocabulary: kpi, trend, breakdown, stage_mix,
    top_owners, scenario_results, alerts, sensitivity, table), layout, refresh default
    (cadence, timezone Asia/Riyadh, expected availability), breach rules (comparison, threshold,
    window, materiality, dedup key, cooldown, severity, recipients), delivery and lineage.
    Validation refuses any visual or rule whose metric is not a catalogue id ("no anonymous
    KPI"), a column not in the book, or a book outside the scope.
  * **Library, first launch:** LENS-01…LENS-18 exactly as §45 names them, plus LENS-19
    Hospitality & Transport Watch and LENS-20 BNPL Watch — 20 Lenses, 7–13 visuals each, every one
    with ≥1 breach rule; pairwise visual-signature overlap < 0.6 (materially distinct). Retail
    "Home Finance" is the `Mortgage` product in this book and the Lens says so. Two
    library-owned, tenant-visible, synthetic executed results (CORP-02, RET-06) are seeded so
    Scenario Impact Watch is populated on first launch.
  * **Rendering** (`POST /lenses/{id}/render`): every visual evaluated now through the metric
    engine, with the Lens's default filters plus cross-filters (applied where the column exists,
    reported as skipped where it does not), per-book period selection, KPI prior/movement and
    sparkline, and exact rows for tables. Nothing stored on the Lens goes stale.
  * **Refresh** (`POST /lenses/{id}/refresh`): an immutable observation (release/fingerprint,
    every metric value and prior, material changes against the previous successful observation
    using each metric's materiality, breach-rule evaluation, "what changed"); idempotent for a
    non-manual trigger on an unchanged release and Lens version.
  * **Creating:** one prompt → a PREVIEW (template matched with reasons, N KPIs / M charts / T
    tables / metrics / rules / refresh) that is not saved; "add …", "remove …", "weekly"
    refine it; Save creates the object. From an investigation (scoped to its governed cohort) and
    from a Cockpit thread ("Save this analysis as a Lens" on every guided thread). Editing writes
    a new version; editing a library or shared Lens makes your own copy. Lenses share through
    Messages (Open, Save my own copy, Comment).
  * **UI** (flag-gated; the legacy `/lenses` pages are served unchanged with the flag off):
    library with search and EMPTY_BY_FILTER; Lens view with active-state bar (period per book,
    "not latest" marked, Lens scope, removable cross-filter chips, reset), KPI tiles (value,
    signed movement coloured by the metric's governed direction, sparkline, metric id/version,
    click → definition), Plotly charts with View data / CSV / PNG / SVG, category click →
    cross-filter, trend point → period, box/lasso → temporary cohort with Save / Investigate /
    What-If / Share, top-owner or table-row click → investigation context (Borrower 360 reads a
    service not in this runtime, so it is not linked), breach rules with last-refresh status,
    refresh, edit, share.
* **Defects found and fixed:**
  * Scenario metrics counted every result in the tenant regardless of who was looking — a
    permission leak. They now count only results the viewer can open (`metrics.VIEWER`), and
    only tenant-visible results when no viewer is known.
  * Breakdowns of evaluator-based metrics (e.g. EWS high/critical share by product) returned no
    groups; the engine now evaluates such metrics once per dimension value.
  * The persona matcher took "dashboard" for "board" (word boundary added).
* **Tests:** `test_gw_lenses.py` 15/15 (library ≥18 with the §45 names; distinctness; every Lens
  ≥5 visuals with real values, groups, rows and series; every binding a pinned catalogue metric
  and every seeded Lens has rules; cross-filter incl. skipped-book reporting; period; default
  product scope; immutable observations, "what changed", idempotent refresh; a material move
  reported; preview not saved, refine, save; anonymous metric refused; versioning and library
  copy; investigation → Lens keeps its cohort; share through Messages; viewer-scoped scenario
  metrics). `lens-figures.test.ts` LENS01–04. All GW backend suites 222 passed, 3 ML skips;
  `npm test` 642/642; `tsc` clean; eslint 0 in new code. Browser `GW-P9-01` (library ≥18; LENS-02
  KPIs; category click → table = 248 Construction rows; trend point → earlier period marked "not
  latest"; reset; refresh; KPI → definition), `GW-P9-02` (prompt → preview not saved → refine →
  save → live Lens → edit → v2), `GW-P9-03` (box-select → temporary cohort → What-If; Cockpit
  thread → Save as Lens → saved with source `cockpit`) — **3/3**.
* **Protected files:** none added (still 5).
* **Status:** PASS

## P10 — Monitoring Centre, refresh, breaches, Inbox
* **Delivered:**
  * **Scheduling** (`backend/workspace/monitoring.py`): `tick(now)` refreshes every Lens that is
    due — daily / weekly / monthly by elapsed time, `on_publication` when a book's release
    fingerprint changed, `on_result` when a scenario result appeared, `continuous` every tick,
    `manual` never; a failed refresh is retried after 5 minutes. The loop is a daemon thread in
    the V4 runtime's own worker/supervisor model (`serve_forever` + poll interval), started once
    when `COCKPIT_V4_MONITORING_SCHEDULER=1` (off in tests; the launchers turn it on);
    "Refresh due Lenses now" runs the same step on demand. No second orchestration architecture.
  * **Alerts:** each SUCCEEDED observation's breach rules drive one governed `alert` per dedup key
    (Lens + rule + book) carrying rule id/version, Lens id/version, metric id/version and unit,
    observed, prior, threshold, comparison, window, release/fingerprint, period(s), affected
    population (the Lens scope), first/last seen and every observation id. NEW → ACTIVE (persists)
    → WORSENING (moves further past the threshold) → RESOLVED (no longer breaches); readers
    ACKNOWLEDGE / RESOLVE (note required) / assign / comment / reopen; SUPPRESS is an
    administrator's decision. Every transition is an append-only event (actor, note, observed);
    acting never changes source data. Material changes are `change` events; a failed refresh is a
    `refresh_failure` alert, resolved by the next successful refresh.
  * **Delivery:** new breaches, worsening, material changes and failed refreshes reach the Inbox
    (Messages) of the Lens owner, followers ("Follow" on every Lens) and named recipients, from
    `creditprobe-monitoring`, with Open Lens at the trigger / Open in Monitoring Centre /
    Investigate in Cockpit / What-If on the population / Comment. A rule's cooldown suppresses
    repeats; worsening is always delivered.
  * **Honesty:** a refresh whose book is unavailable records a FAILED observation ("nothing below
    is current; last successful observation at …"), raises an operational alert, marks the Lens
    STALE in the refresh-health table and shows a banner on the Lens; values are never presented
    as current from a failed refresh.
  * **First launch:** a HISTORICAL REPLAY (demo) of six seeded Lenses' rules over the previous
    published periods — closed records, labelled, never counted as live (M048 excludes them) —
    plus a live round over all 20 library Lenses on the published synthetic books.
  * **UI** `/monitoring` (nav "Monitoring Centre", flag-gated): views New today / Active /
    Worsening / Acknowledged / Resolved / Material changes / Assigned to me / Historical replay /
    All; filters by severity, Lens, book; Plotly by severity and by Lens (click to filter) with
    View data / CSV / PNG / SVG; alert panel with versions, movement-aware observed-vs-threshold
    in the metric's unit, population, status history and actions; Lens refresh-health table.
    Lenses open at an alert's triggering period and population with a banner.
  * M048 now counts live breach alerts the viewer can open, grouped by Lens.
* **Tests:** `test_gw_monitoring.py` 26/26 — exact threshold comparisons (12 cases); first launch
  (live + labelled history, seeded once); one alert per dedup key NEW → ACTIVE; worsening
  delivered through a running cooldown and recovery resolves; cooldown suppresses a duplicate;
  the full state machine (note required, invalid transition 409, suppress needs admin, assign /
  mine view, comment, reopen, historical alerts immutable); actions do not touch source data;
  follower Inbox card with Open / Investigate / What-If / Monitoring actions and working
  handoffs; opening an alert restores the Lens at its period and population; a failed refresh
  is recorded, alerted, delivered, shown stale and resolved by the next success; deterministic
  replay of a scheduled tick (no duplicate observations or alerts); cadence rules; M048; filters;
  the scheduler thread runs ticks when enabled and starts once. Mutation proofs: removing the
  dedup lookup fails the persistence and worsening tests; delivering worsening under cooldown
  fails the worsening test (strengthened after the first mutation survived).
  `test_gw_lenses.py` updated: a second refresh may move only the platform metric M048.
  All GW backend suites **248 passed, 3 skipped**; `npm test` 642/642; `tsc` clean; eslint 0 in
  new code. Browser `GW-P10-01`, `GW-P10-02`, `GW-P10-03` — **3/3**.
* **Protected files:** none added (still 5).
* **Status:** PASS

## P11 — Product-wide reactive Plotly platform
* **Delivered:**
  * **Inventory** `docs/guided_workspace/CHART_INVENTORY.md`: 66 analytical charts.
    * **Plotly on the shared contract: 31.**
    * **Recharts: 12**, all legacy.
    * **Hand SVG: 5.**
    * **CSS/div: 18.**
    * Each row carries a migrated or not-applicable rationale. The Recharts and CSS/div legacy charts are gated as follows:
      * `/lenses/[id]` swaps to the Plotly `LensView` when guided is on.
      * `/stress` redirects to `/what-if`.
      * `/lenses/cro` now redirects to the governed Plotly Lens `lens-01`.
      * Everything else is on flag-off or unrevised lab pages.
  * **Locked by `chart-inventory.test.ts` INV01–06.** It fails in any of these cases:
    * Recharts spreads beyond `components/analytics/charts.tsx` and its 5 legacy consumers.
    * Another chart library appears.
    * Plotly loads outside `plotly-chart.tsx`.
    * A Plotly chart bypasses `ChartCard` (other than the 2 sparkline files).
    * A chart file is missing from the inventory.
  * **Remaining chart types (§27):**
    * **Server-side aggregation:** `grid.grouped2` and `POST /grid/group2` aggregate two governed dimensions. They are capped at 400 cells, flag truncation, return totals, and refuse any column outside the view.
    * **What-If explorer:** heatmap (sector × rating / product × score band; VIZ12) and a stage-migration Sankey (prior → current; VIZ08). Both reconcile on screen (`data-ok`), and a cell or flow click filters the shared state.
    * **Executed results:** Pareto of Delta change by segment with cumulative share (VIZ10), and the per-exposure change distribution (VIZ11), which accounts for unmoved exposures.
  * **Shared behaviour in the one wrapper:**
    * Default `uirevision` keeps a legend-hidden series, and any zoom, across re-renders with fresh figures. This was found by the P11-02 journey.
    * `ChartData.onRowActivate` is the keyboard equivalent of a chart click: Enter or Space on a focused data row.
    * These charts gained click-to-drill: issue-detail drivers, issue-detail stage mix, and the Early Warning reasons chart.
  * **Early Warning reason cross-filter:**
    * **UI:** a rule click (or its data row) narrows the bands, segments, top list and a new underlying grid.
    * **Handoffs:** Save / Investigate / Export / What-If carry the reason.
    * **Filter safety:** the reason must be a label of the domain's own rule set. The filter matches its safe leading token, because the predicate layer (deliberately unchanged) refuses `<`, `>`, `=` and `%`, and it fails closed (422 AMBIGUOUS) if that token would match two rules.
    * **Removed:** the dead `reason_rule` field.
    * **Bug found and fixed:** the reasons loop variable shadowed the `reason` parameter.
* **Tests:**
  * **Backend:**
    * `test_gw_charts.py` (new) passes 10/10:
      * flows and heatmap reconcile to the book and to the selection summary;
      * retail shape;
      * unknown or injected dimension → 422;
      * the cell cap truncates and says so;
      * the HTTP aggregate stays under 40 kB with no row keys;
      * a reason cross-filters bands, segments, the cohort and investigate;
      * every rule of both books filters exactly (5 labels returned 422 before the token fix);
      * unknown reason → 422;
      * an ambiguous token → 422.
    * `test_gw_runs.py`: Pareto and distribution reconcile to the selected change.
  * **Mutation proofs (8):**
    * `grid.py` (3, all killed): cells ignore the filter; truncation hidden; column check removed.
    * `issues_api.py` (4, all killed): bands ignore the reason; cohort drops the reason; ambiguity guard removed (killed only after the synthetic-label test was added); free-text reason accepted.
    * `plotly-chart.tsx`: removing `uirevision` fails GW-P11-02.
    * `chart-card.tsx`: disabling the row key handler fails GW-P11-01.
    * `chart-inventory.test.ts`: a stray Recharts import plus an undeclared `PlotlyChart` fails INV01, INV04 and INV05.
  * **Frontend:** `npm test` 653/653 (VIZ08/10/11/12, WIF06, INV01–06 new); `tsc` clean; eslint 0 in new or changed code (the 15 remaining are pre-existing, in protected `cockpit-v4/*`).
  * **GW backend suites:** 259 passed, 3 skipped.
* **Browser** GW-P11-01..05 pass 5/5:
  * **Payload:** `/grid/group2` payloads measured at 381–9,150 B.
  * **Legend:** isolate makes 0 API calls and leaves the total unchanged; the series stays hidden after a re-render.
  * **Zoom:** drag-zoom, then mode-bar reset.
  * **Sankey:** a flow click filters the grid to that flow's count.
  * **Heatmap:** Enter on a cell row filters; Space clears.
  * **Export:** the CSV has release, fingerprint, period and filters, and rows equal the drawn cells (95 = 95); PNG downloads.
  * **Early Warning:** the reason filters the page, and the saved cohort is exactly the filtered population.
  * **Legacy routes:** `/lenses/cro` renders `lens-01` with 0 Recharts wrappers.
* **Cross-phase browser rerun** (P3, P5–P11 after the wrapper change): P5/P6/P11 13/13, then P3/P7/P8/P9/P10/P11 21/21.
* **Documented limits:**
  * The protected Cockpit thread renderer (`cockpit-v4/visuals.tsx` and `chart-frame.tsx`: 4 SVG and 7 CSS chart kinds) is **not migrated**. Doing so edits protected core, which the round's rules reserve for explicit approval. It already has tooltip, zoom, legend, data table and PNG. Every chart this round adds to a thread is Plotly. This is an open decision for the user.
  * On a click-to-filter chart, Plotly's double-click reset also registers the first click. The mode-bar "Reset axes" control is the unambiguous route, and the journey uses it.
* **Protected files:** none added (still 5).
* **Status:** PASS

## P12 — Trace, exports, governance, reproducibility
* **Delivered:**
  * **Hashes and immutable lineage** (`backend/workspace/store.py`):
    * **Chained ledger.** Every governed write (object version, Lens observation, alert event, comment, share) appends, in the same transaction, one entry to a per-tenant SHA-256 **hash chain** (`ledger`). The entry hashes the stored row, every column, and links to the previous entry.
    * **Triggers.** Comments, shares, observations and alert events now refuse UPDATE and DELETE; objects already did. The ledger itself is append-only.
    * **`verify_ledger`** re-walks the chain and re-hashes every record. It reports, and never repairs:
      * `CHAIN_BROKEN`;
      * `ALTERED`, which catches metadata changes such as permissions that the body hash cannot see;
      * `MISSING`;
      * `UNLEDGERED`, a row written around the module.
    * **Backfill.** Existing stores are backfilled **once** and marked `backfilled`. A later restart never legitimises a slipped-in row.
    * **Credential scrubbing.** Credential-shaped text is replaced by `[REDACTED]` before any row is written: object bodies and titles, comments, share messages, observation bodies and errors, alert notes. Hashes, ids and numbers are untouched.
  * **Governance Trace** (`trace.py`, `GET /trace/objects/{id}`, `/trace/ledger/verify`; UI `/trace/object/[id]`): for any object the viewer may open (finding, cohort, scenario, run, result, comparison, Lens, alert, metric), it shows:
    * **integrity:** every version re-hashed, and each record's chain link and row match;
    * **versions** with content hashes and ledger links;
    * **lineage:** ancestors walked to the roots (depth-capped, unreadable ancestors named but not opened), plus descendants;
    * **events:** comments, shares, the run's state log (confirmation, **method decision**, execution), **Lens refreshes** and **alert transitions**, each with its chain link;
    * **LLM exchanges:** those behind the object's Cockpit thread(s), by id and hash. These are for administrators, model-risk reviewers and auditors only; others see that they exist, not their content.
    * **Tenant check:** "Verify the whole tenant ledger" and "Verify a package" are on the page.
    * **Side effects:** none. Zero model calls; nothing changes.
  * **Export packages** (`exports.py`, `POST/GET /exports/objects/{id}`, `POST /exports/verify`): a ZIP containing:
    * `objects/`: the root and every readable ancestor, **exactly as stored**, with content hashes and ledger links;
    * `tables/`: the **exact stored values**:
      * scenario results: decomposition per method × scope (all taxonomy components with N/A reasons), reconciliation, method results, stages, top contributors, Pareto, distribution;
      * cohorts: members re-resolved and exported only when the membership hash is IDENTICAL;
      * Lenses: observations and latest KPIs/tables;
      * alerts: events;
      * runs: state log;
    * `snapshots/`: the page's own Plotly charts as **SVG plus the Plotly figure spec**, validated server-side (type, name, count ≤ 24, size ≤ 6 MB);
    * `trace.json`;
    * optional **sanitized `llm_exchange/`**, reviewer roles only (403 otherwise);
    * `manifest.json`: SHA-256 of every file, the tenant ledger head, and a redaction count (never values).

    `verify` re-hashes the files, flags unlisted files, re-hashes object bodies against the manifest and the store, and checks **reopen/export parity**:
    * tables must be byte-identical to what the stored version produces now;
    * append-only logs must still contain every exported row.
  * **UI** "Export package" (+ "incl. LLM exchange") and "Trace" on the result, comparison, Lens, scenario detail and alert panel.
  * **LLM Exchange, one recorder.** The readable view labels every part SYSTEM / USER / ASSISTANT / TOOL CALL / TOOL RESULT / **VALIDATOR** in the order sent. VALIDATOR is CreditProbe's rejected or `is_error` tool results: the repair loop made visible. It sits beside canonical → **translated** → raw → normalized. The AI Model Lab lists the same records (browser-proven); there is no second recorder.
  * **Leak fixed:** the LLM Exchange view returned the V4 run's typed question verbatim. It is now scrubbed.
* **Tests:**
  * **`test_gw_trace.py` (18):**
    * the chain across all 5 record kinds, with separate tenant chains;
    * 6 tables refuse UPDATE and DELETE;
    * trigger-bypass tampering detected (ALTERED share and object permissions, UNLEDGERED insert, MISSING delete) and still detected after a restart;
    * one-time backfill of a pre-ledger store;
    * credentials never reach any store file;
    * the result Trace (versions, ledger, digests, lineage result ← run ← scenario + cohort, method decisions in order);
    * access (stranger and unshared colleague → 404);
    * the ledger verify endpoint;
    * the full package (manifest hashes, nothing unlisted, objects as stored, decomposition values component by component, all tables, snapshots, verify OK);
    * an edited package is reported (FILE_ALTERED, TABLE_DIFFERS_FROM_STORE after re-hashing, BODY_DOES_NOT_HASH_TO_MANIFEST, UNLISTED_FILE, not-a-zip);
    * snapshot validation (wrong PNG, non-SVG, traversal name, bad format, too many);
    * cohort and Lens packages (the package still verifies after a later refresh);
    * the LLM exchange for auditors only (403 for analysts), with the exported canonical request hashing to the recorded hash and zero model calls.
  * **Secret-leak suite `test_gw_secret_leak.py` (4):**
    * **Planted canaries:** Anthropic key, OpenAI key, bearer token, password assignment, AWS key. They are planted in the environment, a Cockpit question, a finding, comments, a share message and a Lens refresh.
    * **Surfaces scanned:** every store file (workspace and exchange, including WAL); every Trace, ledger verify, LLM exchange view, Model Lab, Messages, Monitoring, comments and objects; every export (result/finding/cohort/scenario/run × with/without LLM exchange, Lens, LLM exchange ZIP, grid CSV).
    * **Result:** no canary anywhere.
    * **Pre-fix proof:** it failed before the question-scrub fix.
  * **Frontend:**
    * TRC01–02 (snapshot names, hash display);
    * EXS01–03 (six-way labelling, validator vs plain tool result);
    * `npm test` 658/658; `tsc` clean; eslint 0 in new code; ruff clean in new files.
  * **Mutation proofs (5, all killed):**
    * a write not ledgered (5 fail);
    * no scrub at write (4 fail);
    * no table parity (1);
    * backfill on every open (1);
    * exchange visible to analysts (1).
  * **Browser** GW-P12-01..03 pass 3/3:
    * result → Export package (waterfall SVG and Plotly spec attached, every file SHA-verified in the harness) → Trace integrity ✓, versions chained, lineage to run and scenario → tenant ledger ✓ → the downloaded package uploaded and verified → run Trace shows METHOD_SELECTION → "method chosen: Delta" → EXECUTED;
    * Lens export plus Lens Trace refreshes chained, and alert Trace state history;
    * LLM Exchange six-way labels plus four stages, and the Model Lab lists the same exchange ids and links to the same Trace.
  * The long-lived stub store backfilled and verified clean.
* **Cross-phase regression after P12:** GW backend suites **281 passed, 3 skipped**. The full browser journey suite
  (P1–P12, one stack, persisted store) passed **40/41** on first run. GW-P4-01 failed on a harness race: `every()`
  over an empty card list mid-refetch is vacuously true, so the count read 0. The wait now requires a non-empty,
  all-retail list, and the rerun passed. Evidence file **41/41 PASS**.
* **Finding that needs a protected-core decision:**
  * **What:** a credential typed into a Cockpit question is persisted by the **protected V4 run store** (`state.sqlite3` WAL, measured).
  * **What its own `redact()` covers:** event bodies only, not the question.
  * **What is already fixed:** every unprotected surface. The LLM Exchange record is redacted, and the view now scrubs the question.
  * **What remains:** fixing persistence needs an edit to `backend/cockpit_v4/run_store.py` (or `routes.py`/`service.py`) → **awaiting approval**, not done.
* **Protected files:** none added (still 5).
* **Status:** PASS (with the protected-core finding above recorded for decision)

## P13 — Full regression, security, performance, mutation
* **Approved protected fix (Decision 1, commit `dd59676a`):** `backend/cockpit_v4/run_store.py`.
  * **Problem.** A credential typed into a Cockpit question was persisted in clear text: `runs.question`, messages, events, turns, titles and the investigation record, in the DB and its WAL.
  * **Fix.**
    * Every INSERT/UPDATE/REPLACE string parameter is scrubbed at the store's own connection (`_SecretSafeConnection`), using the one product definition of a secret: the LLM Exchange recorder's `scrub_text` / `sanitize`.
    * JSON parameters are re-serialised only when a secret is found, so they stay valid.
    * Telemetry (`input_tokens`, `output_tokens`, `max_tokens`, `cache_read_tokens`) is untouched.
    * The typed question is kept **in memory only** and handed to the worker by `claim_next`. The active request therefore reaches the model exactly as typed, while every display and read path sees only the stored, sanitised text.
  * **Not changed:** analytics, prompt construction, the run store's design.
  * **Acceptance:** `test_gw_v4_secret_persistence.py` (9) plants fake credentials and proves their absence from:
    * DB, WAL and SHM **bytes**;
    * messages, events, run objects, the reopened investigation, Trace and exports (logical reads).

    It also proves the question stays understandable, reopening makes **zero** model calls, the model-visible text is unchanged, and telemetry is unchanged.
  * **Mutation:** boundary off → 7 fail; hand-off off → 2 fail.
  * **Recorded** as row 6 of `PROTECTED_EXTENSION_MAP.md`. No hash regenerated.
* **Gap closure (commit `c962759f`):**
  * **MAC07 — macro-sensitivity tornado** (`backend/workspace/macro_sensitivity.py`, `POST /whatif/sensitivity/tornado`, `components/whatif/macro-tornado.tsx`), interactive Plotly in the What-If workspace.
    * **Bars** are the Scenario Library's own governed translation of the published slopes at a standard shock (pp 1, bp 100, relative 10 %, index 5 pts).
    * **Hover:** MEV, series, shock, coefficient, affected parameter (PD or LGD, explicit and filterable), implied movement, sign, status, methodology, window, and the sign-review warning.
    * **Signs** are kept as fitted. Collateral factors on LGD carry SIGN_REVIEW and are **not corrected**.
    * **Diagnostic-only estimates** are listed, not drawn.
    * **Flags off:** the accepted chat path keeps its tornado substitute.
  * **Grid:**
    * GRID07: every visible column declares a filter kind the UI edits.
    * GRID11: boolean and null filters partition the book exactly.
    * GRID13: server-side sort is deterministic across pages.
    * Paging is capped server-side.
    * Exports carry the filter and cohort definition.
    * **Bug fixed:** a cohort frozen in a conversation exported the whole book; it now exports exactly its members.
  * **DECOMP21 — "Selected scope = Total book"**, decided by population identity (no chain, and either no predicate or entity count = book rows): one bridge, an equivalence panel (rest-of-book Δ = 0, selected Δ = total Δ) and every component marked identical.
  * **METH05** labels: "Method 1 — Delta", "Method 2 — ML emulator", "Method 3 — User-defined" on every workspace surface.
  * **SCEN12:** the stage re-test policy is carried into results.
  * **Money scale:** money columns state "(SAR million)" once (`moneyCol`); CSV keeps the raw value.
  * **M017:** Corporate only; Retail BLOCKED on measured data. The Retail release has no CCF field, and EAD equals balance on 6,702 of 6,702 accounts.
  * **New tests:** DECOMP08/14/24, BASE05, single-customer scenario, ARCH-02 contract digest equality (Cockpit and What-If), and GW-P13-01..05 browser journeys, including a 390 px responsive check.
* **Tooling:**
  * `regression_of_record.py`: every suite, a JUnit file per pytest/node suite, judges per step, environment-bound failures matched against the P0 record by node id.
  * `final_regression.sh`: runs it in a fresh `--no-local` clone at an exact SHA, outside the tracked worktree, and copies what the suites wrote only after they finish.
  * `mutation_gates.py`: 12 gates.
  * `requirement_matrix.py`: computed PASS / PARTIAL / BLOCKED / FAILED, bound to the final regression's SHA; it fails on any cited test, journey, check or file that does not exist.
  * `REQUIREMENT_MATRIX_DRAFT.md`, hand-drafted at P12, is removed. The generated `REQUIREMENT_MATRIX.md` supersedes it, and no count is carried over by hand.
* **Diagnostic run (NOT the regression of record).**
  * **What happened.** A full run started on `c962759f`. An interim output snapshot (`63ee364a`) was committed while it ran, which breaks the freeze rule. That run is therefore **diagnostic evidence only**, kept unaltered in `evidence/diagnostic_pre_final_c962759f/`. It also overwrote ~150 tracked accepted-evidence files in the worktree; they were restored with `git checkout`. The final run uses a clone so this cannot recur.
  * **Result:** 11 of 17 steps PASS. Each failure was diagnosed, not rerun:

    | Step | Diagnosis | Action |
    |---|---|---|
    | V4 accepted (4711 tests, 4 failures) | 3 are the P0-recorded environment-bound failures. 1 is real: `test_no_test_in_this_suite_claims_a_live_provider_measurement`. GW modules said "no model call" instead of a canonical label. The assertion stops at the first offender: 4 modules were found first, then a script found the other 11. | Labels normalised to `NO MODEL` |
    | frontend lint (new code) | Unused `sar` import in `result-view.tsx` | Removed |
    | protected baseline | Judge bug: rc 1 is the tool's normal "changes exist" exit | Judge now passes iff the changed set equals the mapped set (diagnostic log: changed 6 = mapped 6) |
    | release fingerprints | Judge bug: the compatibility release was looked up in the V4 lake; it lives in the V3 store | 4 V4 books via `lake.verify`, compatibility manifest via the V3 store |
    | emulator artifacts | Gate verdicts reproduce; pickle bytes do not. Differ: Corporate lightgbm (weight 0.000), Retail additive_log (both recorded at P0), and **Retail lightgbm (weight 0.342), not recorded at P0** | Classified `BLOCKED_ENV` only when component hashes are the sole difference; reported as measured, nothing regenerated |
    | GW journeys (45/46) | GW-P7-02 expected two bridges on a whole-book result, stale after DECOMP21 | Helper accepts the waterfall or the scope-equivalence panel; GW-P7 + GW-P13 re-run 9/9 |
* **Mutation gates** (`evidence/mutation_gates.json`, run on the candidate code before the freeze):
  * **First run: 2 of 11 survived.** Both are fixed and recorded:
    * **Tenant isolation.** It is enforced twice: a tenant-scoped store query and the tenant check in `can_read`. Mutating only `can_read` was masked by the store, and the named test only used private objects, which other rules also deny. Fix: `test_tenant_wide_objects_stay_inside_their_tenant` asserts each layer separately, and the gate is split into "access rule" and "store scope".
    * **Method selection.** The gate named a test that never sends an empty method choice. Fix: it now also names `test_an_empty_method_choice_stays_at_method_selection`, which exercises the mutated branch.
  * **Re-run: 12 of 12 KILLED; tree clean of mutations.** The gates cover tenant isolation (access rule, store scope), method selection, lineage, metric formula, breach evaluation, LLM sanitisation, cohort identity, V4 persistence boundary, ledger, tornado sign and selected scope = total.
* **Pre-freeze checks on the candidate code:**
  * GW backend suites, label rule, launcher and tenancy suites: **401 passed, 3 skipped**;
  * eslint clean on new code; `tsc` clean;
  * GW-P7 and GW-P13 journeys 9/9 (evidence restored afterwards).
* **Final regression of record — candidate `f490ab9fad8f14bea13dc0aa39a7f6e5481a5fcc`.**
  * **How it ran.** `final_regression.sh` made a `--no-local` clone detached at that SHA, outside the worktree, and found the clone clean. Before launch the worktree was clean and no writer was running. **No repository edit was made until every suite had finished.** Results were then copied unchanged into `evidence/final_regression/`; the clone's suite outputs are under `suite_outputs/`.
  * **Result:** 16 of 17 steps PASS, 1 BLOCKED_ENV, **0 unexpected failures**.

    | Step | Result |
    |---|---|
    | V4 backend + frontend-python (accepted interpreter) | 4731 tests: 3 failures, all P0-recorded environment-bound; 38 skipped → PASS |
    | What-If suite (`.venv-whatif`) | 1328 tests: 10 failures, all P0-recorded interpreter-bound; 2 skipped → PASS |
    | V3 | 590 tests: 1 failure, P0-recorded (namespace) → PASS |
    | LLM adapters | 25 tests, 0 failures, 8 skipped → PASS |
    | Frontend unit | 666 / 666 → PASS |
    | `tsc` | clean → PASS |
    | eslint, new code | 0 outside protected; 15 pre-existing in protected `cockpit-v4` → PASS |
    | ruff, round code | clean → PASS |
    | Protected baseline vs H2 | changed 6 = mapped 6 → PASS |
    | Accepted protected tool | P0-recorded set plus the mapped files → PASS |
    | Release fingerprints | 4 V4 books VERIFIED; compatibility release present → PASS |
    | Release report digests | → PASS |
    | Sensitivity libraries rebuilt | no disagreement → PASS |
    | Emulator artifacts refitted | weights, gates, verdicts, versions, seeds and splits reproduced. Only pickle hashes differ: Corporate lightgbm; Retail additive_log **and lightgbm** → **BLOCKED_ENV** (as in the diagnostic; nothing regenerated) |
    | GW journeys, clean store | **46 / 46** → PASS |
    | What-If candidate browser | Corporate 15/15, Retail 15/15 → PASS |
    | Accepted browser suite, flags off | **76 / 76** → PASS |
* **Requirement matrix** (`REQUIREMENT_MATRIX.md` / `.json`, generated from this run with 0 generator errors):
  * **Counts:** 325 ids: **251 PASS, 67 PARTIAL, 7 BLOCKED, 0 FAILED**. Every cited test ran; none is NOT RUN.
  * **BLOCKED (7):**
    * ARCH05, REG09: earlier container's byte fingerprints;
    * REG08: emulator pickles;
    * DECOMP10: `test_p9b_a_feature_never_appears_as_an_attribution_driver` passes on the accepted interpreter but is P0-recorded as failing on `.venv-whatif`. The generator classes any env-bound failure as BLOCKED_ENV and does not promote it;
    * DECOMP12: data;
    * M017: Retail data;
    * REG12: the Mac UAT approval.
  * **Where the counts come from:** the generator, not edited by hand.
* **Status:** PASS. The regression of record is green apart from the measured BLOCKED_ENV, and every limitation is stated in the matrix.

## P14 — Mac live-provider UAT
* **Package delivered (not run on a Mac):**
  * **Pinned candidate.** `guided_preflight.py` refuses unless all of these hold (there is no `--any-revision`):
    * `git rev-parse HEAD` equals `expected_guided_uat_sha` from `docs/guided_workspace/UAT_CANDIDATE.json`, read from the programme branch;
    * the tree is clean;
    * the Scenario Library, Lens and metric seed definitions hash to the manifest's digests.
  * **Other preflight checks:**
    * Python ≥ 3.12 and `pip check`;
    * Next.js installed;
    * both What-If candidate books, both Guided Workspace books (verified fingerprints) and the compatibility release `v4-saudi-20q-v1`;
    * emulator artifacts and gate verdicts, including Retail G4 FAIL, so Method 2 is UNAVAILABLE for Retail;
    * model and price card from a card **outside** the checkout, resolved without a provider call;
    * the credential in the approved Keychain item `creditprobe-cockpit-v4`, checked by name only. A shell value is accepted only with `--credential-from-shell`;
    * a dedicated runtime directory stamped with the candidate SHA. One from another build is refused; `--fresh` moves it aside.
  * **Launchers.** `start_guided_uat.py` and the START / STOP / STATUS `.command` launchers:
    * set every round flag for the child processes only;
    * place the Keychain value in the child environment, never printed;
    * hand over to the accepted `scripts/cockpit_v4/start.py` lifecycle (port stepping without killing, health before ready, owned-pid stop, status with SHA/releases/ports/model/health).
  * **Evidence collector.** `live_uat_evidence.py` collects:
    * the candidate SHA, and whether the runtime directory is this candidate's;
    * the ledger verify;
    * all LLM exchanges and per-run packages;
    * every own result packaged and verified;
    * a scan of the pack and of every runtime file for the real credential (paths only).
  * **Runbook.** `MAC_LIVE_UAT.md`: build, model and price card, Keychain, launchers, ten canonical journeys, the evidence pack, acceptance and rollback.
* **Tests:** `test_gw_uat_preflight.py` (19):
  * pinned SHA accepted;
  * any other HEAD, a dirty tree, no manifest, or moved seeds refused;
  * no `--any-revision`;
  * runtime-dir ownership and `--fresh`;
  * shell credential needs the flag;
  * the launcher drops a shell credential;
  * price card inside the checkout refused; no model refused;
  * books and compatibility release checked;
  * old Python or broken `pip check` refused;
  * hand-over arguments;
  * one dedicated runtime across START/STOP/STATUS;
  * no credential printing.
* **Dry runs in the container:**
  * **Collector**, against the mock-analyst API with one executed Delta result: PASS with a fake key and a clean runtime; FAIL (exit 1) with the key planted in a runtime file.
  * **Preflight checks** individually: books, compatibility release, emulators, model and price card with a verified scratch card; the missing-card and placeholder-card refusals.
* **Status:** PACKAGE READY. The live run on the Mac is the user's acceptance gate and a paid provider run; not run in this round (REG12 BLOCKED on that approval).

## P15 — Freeze and handoff
* **Delivered:** `HANDOFF.md`, covering:
  * what was delivered, phase by phase;
  * known limitations, each with the exact reason;
  * rollback;
  * the exact Mac commands;
  * provenance;
  * the decisions log.
* **Not done, by instruction:** no tag, no paid provider run. Freezing and tagging after the Mac UAT is the user's decision.
* **Status:** PASS for the handoff documents. The freeze itself waits on the user's UAT acceptance.

## P16 — Final gap closure, hardening and UAT candidate G
* **Branch.** `claude/guided-workspace-final-gap-closure`, from evidence commit `57e4cf4f`. Candidate F (`f490ab9f`) and its evidence are not amended.
* **Audit of the 67 PARTIAL ids at F.** `PARTIAL_CLOSURE_AUDIT.md` is generated by `partial_audit.py` from F's committed matrix, read with `git show`. It refuses to run unless its classification covers exactly the PARTIAL set.
  * **By category:**
    * B TEST_GAP 33;
    * H ENVIRONMENT_LIMITATION 11;
    * A IMPLEMENTATION_GAP 8;
    * G MODEL_LIMITATION 6;
    * F DATA_LIMITATION 2;
    * I LIVE_PROVIDER_REQUIRED 2;
    * J SPEC_CONFLICT 2;
    * K INTENTIONALLY_PARTIAL 2;
    * C BROWSER_EVIDENCE_GAP 1.
* **Read-only audits** (three, in parallel, no edits):
  * **Dead routes and decorative controls.** Found real defects, all fixed:
    * The Requires Attention card had no clickable title or driver, and no What-If handoff (`issue.actions` was never rendered).
    * Messages sent finding, investigation, issue and metric objects to `/objects/{id}`, which has no page.
    * A shared definition's `?version=N`, `/scenarios?domain=` and the object Trace's `/metrics?metric=` were all ignored by their pages.
    * "Open in What-If" from the Scenario Library was verified working.
  * **Plotly coverage.** Every analytical chart rendered with the guided flag on is Plotly. The only non-Plotly analytical charts are:
    * the accepted EWS model lab (H2, unchanged, reachable only by URL with the flag on), now recorded as LEGACY with its reason;
    * the protected Cockpit core.

    `components/trace/landscape.tsx` was added to the non-analytical list.
  * **Lens content gaps.** The audit established, column by column, what the data supports.
* **Implemented (smallest correct behaviour; no fake data):**
  * **Requires Attention card:**
    * the title opens the evidence;
    * the largest-contributor driver opens the issue already narrowed to that driver's population (`?driver=`);
    * a What-If button freezes the exact issue population and opens What-If on it;
    * the never-passed `onAsk` branch is removed.
  * **Messages "Open":** investigation → its thread; issue → its page; metric → the catalogue; anything else → the governance Trace. No link resolves to a missing page (tested for every object kind).
  * **Query parameters:** the scenario detail opens the shared version; the library opens on the linked book; Trace metric links use `m=`.
  * **Governed metrics M065–M075** (catalogue 1.1.0, 75 metrics, every one fully defined):
    * management overlay and overlay share, read from the published IFRS 9 overlay;
    * recoveries and write-offs, from published base-table columns now exposed as hidden governed grid columns;
    * EWS warning reasons, one group per governed rule using the rule's own SQL;
    * alerts by state, active breaches by metric and by owner;
    * the latest result by method, segment (Pareto) and stage.
  * **Lenses** (seed 1.1.0): a `groups` visual kind, bound into LENS-04, 05, 06, 08, 09, 12, 16 and 18.
  * **M050** returned no value ("per Lens"). It now computes hours since each Lens' last SUCCESSFUL refresh, with the oldest as the headline.
  * **DECOMP10.** The P0 "environment-bound" failure of `test_p9b_a_feature_never_appears_as_an_attribution_driver` was misclassified.
    * On the accepted interpreter Method 2 never runs, so the check passed vacuously.
    * On the candidate interpreter it found a real overlap: `pd_pit_12m` was published both as an attribution driver and as an ML model input.
    * Fixed at the publishing seam: model inputs are labelled "(model input)". `explain.py` and every number are unchanged.
    * The test is removed from the runner's known-failure list, so it must now pass.
* **Tests added:**
  * `test_gw_metric_oracles.py` (31): independent Python oracles for 26 metrics on four cuts per book (latest, prior, the stress period with the most Stage 3, a filtered cut), plus:
    * a non-vacuity test;
    * M038, measured: no account exceeds its limit in any period (max 97.9%), so the formula is also proven on synthetic breaching rows;
    * M043/M044 against the published sensitivity parquet;
    * M046 freshness.
  * `test_gw_lens_content.py` (18): overlay, reasons per rule, the salary proxy labelled as a proxy, LENS-06 ECL, recoveries per period, the LENS-16 facets read from the stored result, LENS-18 against the alert store, M049, M050, and every seeded Lens rendering every visual.
  * `test_gw_ml_decomposition.py` (3, candidate interpreter, real Corporate Method 2 result):
    * DECOMP02: booked and raw model baselines published; gap = their difference;
    * DECOMP03: the gap is not inside the scenario effect;
    * M042 per result.
  * `test_gw_p16_wiring.py` (25) and `test_gw_p16_libraries.py` (2): persisted and distinct libraries.
  * **Browser:**
    * **GW-P16-01 (GX-08):** Issue → Investigate → driver chip → stress chip → What-If on the same cohort (membership hash equal) → Ask (pre-filled) → confirm button → Delta button → reconciling decomposition, with **zero keystrokes**.
    * **GW-P16-02:** card title, driver population (server count) and What-If handoff on the exact issue population.
* **Measured first-launch state** (persisted objects, not constants):
  * **Scenario Library:** 36 templates (18 Corporate, 18 Retail), 11 with macro components. Readiness from the real preview: 27 ready for confirmation, 6 ready with user-defined inputs, 3 blocked, each block naming its reason. No duplicated definition.
  * **Lenses:** 20, across 14 personas; no two share a layout.
  * **Metrics:** 75, every definition field populated.
  * **Monitoring:** 9 live NEW breach alerts and 3 historical-replay RESOLVED.
* **Not closable, with the exact reason** (see the audit):
  * the Mac launch rows (Mac execution; live provider for the credential and price rows);
  * UAT-03 and UAT-05 (protected Cockpit renderer: needs a protected-core decision);
  * templates without a governed translation and the two fitted-sign SIGN_REVIEW templates (model facts);
  * RET-02 (no Retail CCF);
  * LENS-09 (no salary-credit feed; the governed proxy is shown and labelled);
  * LENS-16 stage migration (DECOMP12).
* **Protected files:** none added this round (still the 6 mapped).
* **Mutation gates** (`evidence/mutation_gates_p16.json`; F's record is left as it was): **14 of 14 KILLED**, tree clean of mutations. The 12 gates from P13 are joined by two P16 gates:
  * DECOMP10 label separation, run on the candidate interpreter;
  * EWS reasons use each rule's own condition.
* **Pre-freeze checks on the candidate code:**
  * **Backend:** GW suites plus label, launcher and tenancy suites: **477 passed, 4 skipped**. This round's new test files on the candidate interpreter: 99 passed.
  * **Frontend:** 666/666; `tsc` clean; eslint with no errors outside the protected `cockpit-v4` files (pre-existing).
  * **Browser, MODEL MOCK:** GW-P3, P5, P7, P9, P10 and P16 journeys all pass.
  * **GW-P16-01 first failed. The cause was the scripted analyst, not the product.**
    * The analyst added `methods: ["delta"]` to every cohort scenario preview, playing a user who had chosen Delta.
    * The guided stress suggestion names no method, so the analyst now previews it method-free, as UAT-01 requires.
  * **Evidence restored:** the evidence files those runs overwrote were restored with `git checkout`.
* **Candidate G `482d603081a3f58e888623913d415cb5c22accef`: regression run, NOT accepted.** Kept as measured in `evidence/regression_candidate_G_482d603081a3/`.
  * **Result:** 15 PASS, 1 BLOCKED_ENV, 1 FAIL.
  * **Suites:** V4 4808 tests, with only the P0-recorded failures; What-If 1407; V3 590; frontend 666/666; accepted browser 76/76; What-If browser 15/15 per book.
  * **BLOCKED_ENV:** emulator pickle bytes only, as for F.
  * **FAIL:** GW journeys 47 of 48. GW-P5-06's bar click did not narrow the grid.
  * **Diagnosis, not a rerun.** The journey and the product path were unchanged and had passed in three earlier runs. The UI log's Plotly console errors also occur in F's passing run. The cause is the harness `clickBar` helper:
    * it clicked at computed coordinates after an "if needed" scroll;
    * the What-If selection bar is sticky and z-10, so it can cover the target bar.
  * **Fixed in candidate H.** The helper centres the chart, re-reads the box after layout settles and asserts that `elementFromPoint` hits the chart before clicking. A new candidate and a new full regression follow, since repository code changed.
* **Final regression of record: candidate H `8b1592f46b06d03cec089d5b49cb93280b819993`.** H is G plus the harness click fix and the record of G's run; there is no product change.
  * **How it ran.** In a `--no-local` clone detached at H, outside the worktree. Before launch the tree was clean, no writer was running and tags were unchanged. No repository edit was made until every suite finished. Results are in `evidence/final_regression_8b1592f46b06/`, copied unchanged; F's `evidence/final_regression/` is untouched.
  * **Result:** **16 of 17 PASS, 1 BLOCKED_ENV, 0 unexpected failures.**

    | Step | Result |
    |---|---|
    | V4 backend + frontend-python | 4808 tests: 3 failures, all P0-recorded environment-bound; 39 skipped → PASS |
    | What-If suite (`.venv-whatif`) | 1407 tests: 9 failures, all P0-recorded interpreter-bound (one fewer than F: the DECOMP10 test now passes); 2 skipped → PASS |
    | V3 | 590 tests: 1 P0-recorded failure → PASS |
    | LLM adapters | 25 tests, 0 failures, 8 skipped → PASS |
    | Frontend | 666/666; `tsc` clean; eslint 0 outside the protected `cockpit-v4` files (15 pre-existing) → PASS |
    | ruff, round code | → PASS |
    | Protected baseline | changed 6 = mapped 6 → PASS |
    | Release fingerprints | 4 books VERIFIED; compatibility release present → PASS |
    | Report digests; sensitivity libraries rebuilt | → PASS |
    | Emulator artifacts refitted | only pickle hashes differ (Corporate lightgbm; Retail additive_log and lightgbm); weights, gates, verdicts, splits reproduced → **BLOCKED_ENV**, as for F; nothing regenerated |
    | GW journeys, clean store | **48 / 48** → PASS |
    | What-If candidate browser | Corporate 15/15, Retail 15/15 → PASS |
    | Accepted browser suite, flags off | **76 / 76** → PASS |
* **Requirement matrix** (`REQUIREMENT_MATRIX.md` / `.json`, generated from this run, 0 generator errors):
  * **Counts:** 325 ids: **293 PASS, 26 PARTIAL, 6 BLOCKED, 0 FAILED**. At F the counts were 251 / 67 / 7 / 0.
  * **Collection interpreter.** The generator collects the cited pytest nodes with `--python .venv-whatif/bin/python`. On the accepted interpreter, `test_gw_ml_decomposition.py` skips at import, so its nodes would read as non-existent although they ran and passed in the candidate-interpreter suite. The first generation, with the default interpreter, reported exactly those 3 citations as missing; that is how this was found. The candidate interpreter collects every cited node.
* **PARTIAL closure** (`PARTIAL_CLOSURE_AUDIT.md`): of the 67 PARTIAL at F, **41 are now PASS and 26 remain PARTIAL**, each with its stated reason:
  * 13 Mac launch rows (Mac execution; live provider for the credential and price rows);
  * UAT-03 and UAT-05 (protected Cockpit renderer: a protected-core decision);
  * SCEN07, RET-04, RET-05, RET-08, RET-14, RET-17 (no governed translation: User-defined only);
  * CORP-03 and RET-07 (fitted sign kept with SIGN_REVIEW);
  * RET-02 (no Retail CCF);
  * LENS-09 (no salary-credit feed: governed proxy shown);
  * LENS-16 (scenario stage migration not modelled: DECOMP12).
* **BLOCKED (6, measured):**
  * ARCH05 and REG09: the earlier container's byte fingerprints;
  * REG08: emulator pickle bytes;
  * DECOMP12: no governed re-test rule;
  * M017: no Retail CCF;
  * REG12: the user's Mac live-provider UAT.

  DECOMP10 left BLOCKED and is PASS.
* **Status:** PASS. Candidate H is the UAT candidate (`UAT_CANDIDATE.json`). The Mac live-provider UAT remains the acceptance gate; no tag.


## V — Exhaustive validation, integration and defect fixing

**Branch.** `claude/guided-workspace-exhaustive-validation`, from evidence commit `55bfb9a4`. Candidate H (`8b1592f4`) and its evidence are not amended. No feature was added beyond what a proven defect required, and no protected file changed.

**Baseline.** `validation/BASELINE.md`: the releases, seeds and emulator artifacts were verified at the start.

**Inventories.** `scripts/guided_workspace/validation_inventory.py` builds:
- routes;
- interactive controls (static scan, joined to the runtime click record of the browser run);
- API functions, with call sites matched against f-strings;
- cross-module handoffs, with a dead-target check and whether each carries its origin;
- the Back matrix and Plotly audit, copied from the run's records.

**Validation.**
- **Back navigation.** 22 browser journeys (`GW-BACK-01..22`) drive each path forward, then check browser Back, Forward and the in-product Back control against the origin's state read from the page. They also check that the return trip writes nothing and calls no model.
- **GOLD.** `GW-GOLD-01..10` cross modules and end on business state: membership hashes, reconciliation, lineage, alert state and stored hashes.
- **Plotly.** `GW-VAL-PLOTLY` audits every Plotly chart on ten guided pages at 1440 px and 390 px.
- **Console gate.** Validation journeys fail on any console error or uncaught page error.
- **Backend.**
  - `test_gw_validation_defects.py`: one test per backend defect, plus restart persistence through a rebuilt app with no model call.
  - `test_gw_ecl_reconciliation.py`: an independent ECL oracle over the source rows for single, multi, sub-portfolio, whole-book, Retail, reopened and comparison scopes, agreeing to 1e-6.
  - `test_gw_validation_endpoints.py`: every workspace endpoint no suite called before.
- **Mutation gates.** Four new gates (VAL-DEF-010, -012, -013, -016) break each fix on purpose; a named test must fail.

**Defects.** `validation/DEFECT_REGISTER.md` (VAL-DEF-001 … 030):
- One CRITICAL: an unrunnable scenario, with unresolved composition or retired, could be run.
- Twelve CRITICAL/HIGH in total, all fixed.
- Four LOW items remain open and are accepted or out of scope.

The first browser runs that found VAL-DEF-022, -023, -028, -029 and -030 are preserved in `validation/dev_runs/`.

**Harness corrections, each preserved as a failed run.**
- The GOLD-02 ML refusal is asserted on the run's governance record, not on the result.
- BACK-08 declares the Discard write of its Cancel.
- BACK-10 picks a What-If-entry result.

**Candidate I (`fc8754a1`) rejected.** In its regression, the accepted-interpreter step failed one test that is not on the known list: `test_multilingual_and_evidence_labels.py::test_no_test_in_this_suite_claims_a_live_provider_measurement`. The three new test modules named their evidence in words outside the allowed label vocabulary.

The fix is a docstring-only change ("NO MODEL", "INDEPENDENT ORACLE"). Because a tracked test file had to change, candidate I is rejected rather than re-run, per the round's rule. Candidate J carries the fix, and the complete accepted suite was run on the working tree before J was cut. Candidate I's regression output is kept as measured in `evidence/regression_candidate_I_fc8754a19e72/`.

**Candidate J (`84b0ca12`) rejected.** In its regression, the guided browser step ran 81/82. `GW-P5-05`, a journey that existed before this round, read the What-If application's scenario before Apply had re-bound it to the saved cohort: it waited for a preview selector that was already on screen. That is a harness race, not product behaviour.

The journey now waits for the re-bound object, and it passed three consecutive times. The inventory step's failure was derived from that journey. Candidate K carries the harness fix. Candidate J's output is kept in `evidence/regression_candidate_J_84b0ca12f140/`.

**Results.** The final regression of record is on candidate K (`62ba4dda50363b7700849ff9e11a4731d118f11b`).
- **Steps:** 17 of 18 PASS, 1 BLOCKED_ENV (emulator pickle bytes, as at H).
- **Browser journeys:** guided 82/82, What-If candidate 15/15 per book, flags-OFF accepted 76/76.
- **Validation matrix:** 32 PASS, 2 BLOCKED (emulator bytes; live provider). The verdict is READY FOR MAC LIVE UAT.
- **Requirement matrix:** unchanged at 293 PASS, 26 PARTIAL, 6 BLOCKED, 0 FAILED.

The performance smoke (`validation/perf_smoke.json`) was measured on the working tree before candidate I was cut, and the backend code is identical at K. The report, matrix and inventories are generated from K's regression output. K is pinned in `UAT_CANDIDATE.json`; there is no tag.

---

## C — Interaction-coverage closure (candidate L)

**Lineage.** Work continues on `claude/guided-workspace-exhaustive-validation` directly on K's evidence commit; nothing was rebased or force-pushed. The proof was taken before L was cut:

| Check | Result |
|---|---|
| `git merge-base --is-ancestor 62ba4dda50363b7700849ff9e11a4731d118f11b HEAD` (candidate K) | exit 0: K is an ancestor |
| `git merge-base --is-ancestor 510f5c833e872232a6384fc58c62724db8e96b54 HEAD` (K's evidence commit) | exit 0: an ancestor |
| History from K | linear: `62ba4dda` → `510f5c83` → the round's commits |

`57e4cf4f` (the P15 record on `claude/eager-keller-7ue2yk`) is an older ancestor, three branch points back; the round is not based on it. The exact output is published with the evidence (`evidence/ancestry_candidate_L.txt`).

**Scope.** Every UI control, route, integration handoff, Back/Forward path and interactive chart was executed in the browser (`GW-CTL-*`, 21 journeys) and joined to the source inventory by `scripts/guided_workspace/control_execution.py`. A control is closed only as PASS, BLOCKED_WITH_GOVERNED_REASON or NOT_APPLICABLE_WITH_PROOF. One never-rendered control (`ResultLink`, exported but used nowhere) was removed from the source, so the inventory counts 394 controls, one fewer than before.

**Defects.** VAL-DEF-024, 025 and 026 (via 032) were fixed; 027 was accepted by design; VAL-DEF-032 to 054 were found by the execution and fixed (see `validation/DEFECT_REGISTER.md`; pre-fix records in `validation/prefix_evidence/`). Each backend fix has a regression test that fails on the pre-fix code and a pytest mutation gate. The What-If Back/Forward guard (VAL-DEF-038) has a browser mutation gate: `scripts/guided_workspace/browser_mutation_gates.py` puts the pre-fix address sync back and requires `GW-CTL-HISTORY` (A → B → C, Back, Back, Forward, Forward, twice) to fail.

**Results.** The regression of record is on candidate L (`271381b6bcf0e60b4cb2e77d35f38b0b9b4099d6`), from a fresh detached clone with no repository edit while it ran.
- **Steps:** 17 of 18 PASS, 1 BLOCKED_ENV (emulator pickle bytes). Accepted V4 + frontend-py 4857 tests (the 3 known environment failures), What-If on the candidate interpreter 1456 (9 known), V3 590 (1 known), LLM adapters 25, frontend unit 670/670, TypeScript and lint clean, protected set 6 = 6 mapped, fingerprints, digests and sensitivity libraries reproduce.
- **Browser:** guided 103/103 (GW-CTL 21, BACK 22, GOLD 10), What-If 15/15 per book, flags-OFF 76/76.
- **Closure:** 394 controls = 284 PASS + 2 governed BLOCKED + 108 N/A with proof; 0 FAILED; 0 unexercised. Routes 27/27, handoffs 41/41, Back paths 109/109, Plotly contracts 44/44.
- **Gates:** pytest mutation gates 28 of 28 killed; browser mutation gate 1 of 1 killed, both on the committed candidate.
- **Matrices:** validation 32 PASS, 2 BLOCKED; requirements 293 PASS, 26 PARTIAL, 6 BLOCKED, 0 FAILED. The verdict is READY FOR MAC LIVE UAT. L is pinned in `UAT_CANDIDATE.json`; there is no tag.

---

## Baseline counts (H2 `feb80f58`, isolated worktree `/home/user/baseline_wt`, no round code)

Protocol fixed at P0 and reused at P13: the V4 + frontend suites run on the ACCEPTED
interpreter (`/home/user/.venv312`, exact `requirements.txt`), because
`test_whatif_ml.py` asserts that interpreter carries no ML library; the What-If
suite additionally runs on `.venv-whatif`, which does.

| Suite | Interpreter | Result at H2 |
|---|---|---|
| `tests/cockpit_v4` + `tests/frontend` | accepted | **4341 passed, 3 failed, 35 skipped** (17m50s) |
| `tests/cockpit_v4/test_whatif_*.py` | `.venv-whatif` | 964 passed, 10 failed, 2 skipped |
| `tests/cockpit_agentic` (V3) | accepted | 589 passed, 1 failed |
| frontend `npm test` | node 22 | 593 / 593 |
| `tsc --noEmit` | — | clean |

Every baseline failure is environment-bound and pre-exists this round:
* `test_the_accepted_releases_are_byte_identical[×2]` pin the earlier container's
  accepted byte fingerprints (`BASELINE_PROVENANCE.md` §3).
* `test_the_accepted_environment_carries_none_of_the_ml_libraries[matplotlib]`:
  `requirements.txt` itself pins `matplotlib==3.11.0`, so an exact accepted install
  carries it; the earlier container's interpreter evidently did not.
* On `.venv-whatif` the other seven `test_whatif_ml` isolation tests fail by design
  (they must run on the accepted interpreter, where they pass), and
  `test_p9b_a_feature_never_appears_as_an_attribution_driver` fails there but passes
  on the accepted interpreter.
* V3 `test_the_namespace_is_where_the_release_actually_goes` reads
  `COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4`, which the V4 protocol sets.

The first measurement (all suites on `.venv-whatif`) was 4328 passed / 16 failed /
35 skipped; the difference is exactly the interpreter-bound tests above.
