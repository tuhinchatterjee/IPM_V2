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
* **Status:** IN PROGRESS (baseline re-measure on the accepted interpreter running)

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
* **Status:** NOT STARTED

## P3 — Guided Cockpit: Requires Attention
* **Status:** NOT STARTED

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

| Suite | Interpreter | Result |
|---|---|---|
| `tests/cockpit_v4` + `tests/frontend` | `.venv-whatif` (ML libs present) | 4328 passed, 16 failed, 35 skipped (19m35s) — the 16 are environment-bound, see below |
| `tests/cockpit_agentic` (V3) | `.venv-whatif` | 589 passed, 1 failed |
| frontend `npm test` | node 22 | 593 / 593 |
| `tsc --noEmit` | — | clean |

Of the 16: 7 `test_whatif_ml` tests assert the ACCEPTED interpreter carries no ML
library (they must run on the accepted interpreter); 6 Saudi/India-label and
provisioning tests pass on the accepted interpreter (47/47 re-run); 2
`test_the_accepted_releases_are_byte_identical` pin the earlier container's accepted
fingerprints (environmental, §3 of the provenance); 1 `test_p9b_…` passes on the
accepted interpreter. Re-measure on the accepted interpreter is recorded below when
it completes.
