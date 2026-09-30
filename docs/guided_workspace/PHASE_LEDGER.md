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
* **Status:** NOT STARTED

## P5 — What-If Analysis workspace and cohort explorer
* **Status:** NOT STARTED

## P6 — Method selection, ECL execution, universal Plotly decomposition
* **Status:** NOT STARTED

## P7 — Composition, branching, lineage and collaboration
* **Status:** NOT STARTED

## P8 — Metric Catalogue 2.0
* **Status:** NOT STARTED

## P9 — Lenses 2.0
* **Status:** NOT STARTED

## P10 — Monitoring Centre, refresh, breaches, Inbox
* **Status:** NOT STARTED

## P11 — Product-wide reactive Plotly platform
* **Status:** NOT STARTED

## P12 — Trace, exports, governance, reproducibility
* **Status:** NOT STARTED

## P13 — Full regression, security, performance, mutation
* **Status:** NOT STARTED

## P14 — Mac live-provider UAT
* **Status:** NOT STARTED

## P15 — Freeze and handoff
* **Status:** NOT STARTED

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
