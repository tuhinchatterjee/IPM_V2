# Guided Risk Workspace — handoff (P15, updated P16)

| Item | Value |
|---|---|
| Specification | Master specification v3.1, Guided Risk Workspace, What-If & Live Lenses |
| Branch | `claude/guided-workspace-exhaustive-validation` (exhaustive validation round; continues `claude/guided-workspace-final-gap-closure` from evidence commit `55bfb9a4`) |
| Parent | H2 `feb80f58982addf6e9474200b22451d1e303d276` |
| Candidate | The SHA in `docs/guided_workspace/UAT_CANDIDATE.json` (`expected_guided_uat_sha`): the commit the final regression of record ran on. No tag, by instruction. |
| Record | `PHASE_LEDGER.md` (per phase, measured), `REQUIREMENT_MATRIX.md` (generated, 325 ids), `PROTECTED_EXTENSION_MAP.md`, `BASELINE_PROVENANCE.md` |
| Acceptance gate still open | The Mac live-provider UAT (`MAC_LIVE_UAT.md`): a paid provider run, the user's decision |

**Final regression of record (exhaustive validation round):** candidate K `62ba4dda50363b7700849ff9e11a4731d118f11b` (`evidence/final_regression_62ba4dda5036/`).
- **Steps:** 17 of 18 PASS, 1 BLOCKED_ENV (emulator pickle bytes).
- **Guided browser suite:** 82/82, including 22 back-navigation and 10 GOLD cross-module journeys.
- **Validation matrix:** 32 PASS, 2 BLOCKED (emulator bytes; live provider).
- **Defects:** 31 found; all 10 CRITICAL/HIGH fixed; 4 LOW open.
- **Mutation gates:** 18 of 18 killed.
- **Records:** `validation/VALIDATION_REPORT.md`, `validation/DEFECT_REGISTER.md`, `validation/FINAL_UAT_READINESS.md`.
- **Rejected candidates:** I (`fc8754a1`, an evidence-label meta-test) and J (`84b0ca12`, a harness race); both runs are kept as measured.

**Previous regression of record:** candidate H `8b1592f46b06d03cec089d5b49cb93280b819993` (`evidence/final_regression_8b1592f46b06/`).
- **Steps:** 16 of 17 PASS, 1 BLOCKED_ENV (emulator pickle bytes), 0 unexpected failures. Browser journeys: Guided Workspace 48/48, What-If 15/15 per book, accepted suite 76/76 with the flags off.
- **Requirement matrix:** 325 ids; **293 PASS, 26 PARTIAL, 6 BLOCKED, 0 FAILED**.
- **Mutation gates:** 14 of 14 killed.
- **Candidate G** (`482d6030`, 1 journey FAIL, diagnosed as a harness click race) is kept as measured in `evidence/regression_candidate_G_482d603081a3/`.

**Previous candidate F:** `f490ab9f` (historical; not amended).
- **Steps:** 16 of 17 PASS.
- **Requirement matrix:** 251 PASS, 67 PARTIAL, 7 BLOCKED, 0 FAILED.
- **Evidence:** in commit `57e4cf4f`. P16 closed 41 of its 67 PARTIAL; see `PARTIAL_CLOSURE_AUDIT.md`.

Every browser journey in this round ran as MODEL MOCK, a scripted analyst. No
provider credential exists in the container and no paid call was made.

## 1. What was delivered

Measured detail, tests and journeys for each phase are in `PHASE_LEDGER.md`.

| Phase | Delivered |
|---|---|
| P0 | Baseline, provenance and data freeze. H2 protected manifest captured once; baseline suite counts; environment-bound failures recorded by node id. |
| P1 | Full LLM Exchange Trace: one passive recorder (canonical → translated → raw → normalized); the AI Model Lab lists the same records. |
| P2 | Shared governed object model: identity, versions, lineage, permissions, cohorts frozen by membership hash. |
| P3 | Guided Cockpit: Requires Attention cards beside the free Ask box; investigation path and next-best questions inside the ordinary thread. |
| P4 | Scenario Library: 36 seeded Corporate and Retail templates, governed macro translation, composition. |
| P5 | What-If workspace: server-side grid, selection, cohort explorer. |
| P6 | Method gate. Nothing runs until a method is chosen. Dual-scope ECL decomposition with a universal Plotly bridge. |
| P7 | Composition, branching, lineage, sharing, Messages. |
| P8 | Metric Catalogue 2.0: 75 metrics with versioned definitions (catalogue 1.1.0), covering the 50 specified ids M001–M050. |
| P9 | Lenses 2.0: 20 seeded Lenses, covering the 18 specified. |
| P10 | Monitoring Centre: refresh, breach rules, alerts, Inbox. |
| P11 | Product-wide reactive Plotly platform and chart inventory. |
| P12 | Governance Trace, a per-tenant hash-chained ledger, verifiable export packages, credential scrubbing at write. |
| P13 | The approved protected fix (no typed credential in V4 durable storage), the MAC07 tornado, grid, scope and label gaps closed, 12 mutation gates, the regression runner (clone at an exact SHA) and the generated requirement matrix. |
| P14 | The Mac UAT package: a preflight pinned to the candidate SHA, START/STOP/STATUS launchers and the evidence collector. Dry-run in the container; not run on a Mac. |
| P15 | This document. |
| P16 | Gap closure. Independent metric oracles; Lens content (overlay, warning reasons, recoveries, alerts by state/metric/owner, result facets); M050 computed; card and link wiring (no dead route); the DECOMP10 overlap fixed; clicks-only root cause (GX-08); candidate G and its clean regression. |

## 2. Known limitations

Each limitation is exact. The generated matrix carries the same reasons per id.

**Blocked: environment or data**
* **ARCH05 / REG09 — accepted byte fingerprints.** The accepted books reproduce their in-container P0 fingerprints and content digests (`lake.verify`). The earlier container's recorded byte fingerprints cannot be reproduced with the pinned writer (`BASELINE_PROVENANCE.md` §3). The tests that pin them fail here and are recorded as environment-bound, not fixed.
* **REG08 — emulator pickles.**
  * **Reproduces:** refitting reproduces every gate verdict and the blend weights.
  * **Does not reproduce:** the pickle bytes. Measured differences:
    * Corporate lightgbm (weight 0.000) and Retail additive_log, both recorded at P0;
    * **Retail lightgbm (weight 0.342), not recorded at P0.**
  * **Effect:** the published artifacts were not regenerated. Inference does not verify component hashes.
* **DECOMP12 — stage re-test.** Neither book publishes a SICR re-test rule or a lifetime ECL curve for re-staged exposures. A re-test request is carried into execution, and the stage components are N/A with that reason.
* **M017 — Retail CCF.** The Retail release has no CCF field, and EAD equals balance on 6,702 of 6,702 accounts. Corporate is computed; Retail is refused.
* **Retail Method 2.** Emulator gate G4 fails (0.3436 against 0.15), so Method 2 is UNAVAILABLE for Retail and says so.

**Blocked: approval**
* **REG12 — Mac live-provider UAT.** Not run. It is a paid provider run and the user's acceptance gate.

**Partial**
* **LAUNCH01–12, UAT-07 — Mac launcher.** The logic is tested in the container (`test_gw_uat_preflight.py`, `test_launcher_safety.py`). Execution on a Mac with the Keychain is pending.
* **UAT-03, UAT-05 — protected Cockpit surfaces.** The protected thread renderer (`components/cockpit-v4/visuals.tsx`) and the flags-off legacy pages keep their own stage display and money formatting. Migrating them needs a protected-core decision.
* **Templates without governed translation.**
  * SCEN07, RET-04, RET-05, RET-08, RET-14, RET-17 have components with no governed translation. They run only as User-defined.
  * RET-02's CCF component is UNSUPPORTED.
* **Signs kept as fitted (CORP-03, RET-07).** Collateral and property-value translations reduce LGD when collateral falls. They are shown with SIGN_REVIEW and are not corrected.
* **LENS-09 — salary signals.** The Retail book has no salary-credit feed. The Lens shows the governed salary-interruption PROXY (EWS rule R-SALARY), labelled as a proxy.
* **LENS-16 — stage migration.** Scenario-induced migration is not modelled (DECOMP12). The Lens shows ECL change by stage under the result's own policy, labelled "not migration". Method comparison and concentration are complete.
* **Legacy EWS model lab.** `app/early-warning/lab` (accepted at H2, unchanged) draws CSS bars. It is linked only from the legacy page and is reachable with the guided flag on only by URL.

## 3. Rollback

The round is additive behind flags. In order of increasing reach:

1. **Flags off.** Unset these flags and restart:
   * `COCKPIT_V4_GUIDED_WORKSPACE`
   * `NEXT_PUBLIC_GUIDED_WORKSPACE`
   * `COCKPIT_V4_LLM_EXCHANGE_TRACE`
   * `COCKPIT_V4_MONITORING_SCHEDULER`
   * `COCKPIT_V4_WHATIF_CORPORATE`
   * `COCKPIT_V4_WHATIF_RETAIL`

   With them off, no workspace route is mounted and the accepted Cockpit behaves as at H2. The accepted browser suite runs flags-off in the regression of record.
2. **UAT runtime.** Stop with the STOP launcher. Then remove `~/.creditprobe/guided_workspace_uat` and any `guided_workspace_uat.*` directories moved aside. Nothing else on the machine is touched.
3. **Code.** Check out H2 `feb80f58` or any accepted tag; no tag was moved (`git:no_tags_moved` in the matrix). The six protected files changed by the round are listed with their exact edits in `PROTECTED_EXTENSION_MAP.md`.
   * One of them, `run_store.py`, sanitises what it writes. Rolling it back does not un-sanitise rows already stored. It only stops scrubbing new ones.
4. **Data.** Source data is read-only. The workspace, exchange and run stores live in the runtime directory and can be deleted. The published releases were not modified (fingerprints below).

## 4. Exact Mac commands

The full runbook with pass criteria is `MAC_LIVE_UAT.md`. The short form:

```bash
git clone https://github.com/tuhinchatterjee/ipm_v2.git CreditProbe_GW_UAT && cd CreditProbe_GW_UAT
git fetch origin claude/guided-workspace-exhaustive-validation
git branch -f claude/guided-workspace-exhaustive-validation origin/claude/guided-workspace-exhaustive-validation
EXPECTED_GUIDED_UAT_SHA=$(git show origin/claude/guided-workspace-exhaustive-validation:docs/guided_workspace/UAT_CANDIDATE.json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["expected_guided_uat_sha"])')
git checkout --detach "$EXPECTED_GUIDED_UAT_SHA"
# build once: MAC_LIVE_UAT.md §2 (venv, npm ci, seed releases, train emulators, restore committed gate record)
# model + price card outside the checkout: MAC_LIVE_UAT.md §2a
security add-generic-password -s creditprobe-cockpit-v4 -a "$USER" -w
export AI_COCKPIT_REASONING_MODEL=<exact model id>
.venv-whatif/bin/python scripts/guided_workspace/guided_preflight.py
open scripts/guided_workspace/START_GUIDED_WORKSPACE_UAT.command      # or start_guided_uat.py
# run the ten journeys (MAC_LIVE_UAT.md §5), then:
.venv-whatif/bin/python scripts/guided_workspace/live_uat_evidence.py --api http://127.0.0.1:8434 --out ~/CreditProbe_UAT_evidence
open scripts/guided_workspace/STOP_GUIDED_WORKSPACE_UAT.command
```

## 5. Provenance

* **Releases served** (fingerprints, verified by `lake.verify` in the preflight and in the regression):

  | Release | Fingerprint |
  |---|---|
  | `v4-saudi-corporate-20q-v4` | `c79d0fdf8753576f391f2a6bb84f281595e7445291a558abe639f6a43e22a740` |
  | `v4-saudi-retail-20m-v5` | `c23a15d78ba88d39aeae6983e68fff2230b644f5c8f91bec5c89085399f04e5b` |
  | `v4-whatif-corporate-20q-s1` | `3b101bd41465fbe15f89d0d9563026e0f7f2e8081e9e778a90eebe553e01fce5` |
  | `v4-whatif-retail-20m-s1` | `98b494ae2721bd535f406eb6873c0b689c82da36152719e6c8e79c5da7ed92d3` |
  | `v4-saudi-20q-v1` | compatibility release in the V3 store; its manifest is checked |

* **Tags.** The six tags present at P0 are unchanged, and `whatif-candidate-h1` still resolves to `b2a05671`.
* **Protected core.** `protected_baseline.py --check` against H2: six files changed, each mapped. No hash was regenerated.
* **Regression of record.** `final_regression.sh <SHA>` clones the candidate with `--no-local`, detached at the SHA, outside the worktree. It links only the untracked runtime inputs (candidate interpreter, published lakes, emulator pickles, node_modules) and refuses a dirty tree. Results land in `evidence/final_regression/`, written by the evidence commit after the run. The earlier run on `c962759f` is diagnostic only (`evidence/diagnostic_pre_final_c962759f/`).
* **Seed definitions.** The Scenario Library, Lens and metric catalogue digests are in `UAT_CANDIDATE.json`, and the preflight re-checks them on the Mac.

## 6. Decisions log

| # | Decision | By | Where recorded |
|---|---|---|---|
| 1 | Narrow edit of the protected `run_store.py` so no typed credential is persisted in clear text. No redesign; the model-visible text is unchanged; telemetry is untouched. | User (Decision 1) | `PROTECTED_EXTENSION_MAP.md` row 6; ledger P13 |
| 2 | MAC07 is implemented as an interactive Plotly tornado on the new What-If path. Signs are kept as fitted, with RET-07's SIGN_REVIEW shown; the PD/LGD distinction is explicit. The accepted path's "no tornado" test is treated as a flags-off legacy constraint. | User (Decision 2) | Ledger P13; `test_gw_macro_tornado.py` |
| 3 | Selected scope = Total book is decided by population identity. The result shows one bridge and an equivalence panel instead of two identical bridges. | User directive | DECOMP21; ledger P13 |
| 4 | M017 is Corporate only; Retail is BLOCKED with the measured incompatibility. | User directive (data-dependent) | `metric_catalog.py`; matrix M017 |
| 5 | The run that overlapped a commit is diagnostic, not of record. The final regression runs on a clean clone at the frozen SHA, with zero edits while it runs. | User process correction | Ledger P13 |
| 6 | The UAT candidate is pinned by SHA in `UAT_CANDIDATE.json` (no tag). There is no `--any-revision`. The credential comes from the approved Keychain item only, unless `--credential-from-shell` is given. | User directive | `guided_preflight.py`; `MAC_LIVE_UAT.md` |
| 7 | No tag and no paid provider run in this round. | User directive | — |
| 9 | DECOMP10's P0 "environment-bound" failure was reclassified as a real defect: a model input shared a name with an attribution driver. It was fixed by labelling model inputs, not by changing analytics, and the test was removed from the known-failure list. | Implementation (P16) | `bridge.py`; ledger P16 |
| 10 | Recoveries and write-offs are exposed as hidden governed grid columns from the published base tables. Overlay, recovery, reasons, alert and result-facet metrics M065–M075 were added; no value is synthesised. | Implementation (P16) | `grid.py`, `metric_catalog.py`; ledger P16 |
| 8 | Two mutation gates that survived their first run were fixed by adding the missing test (tenant isolation per layer) and naming the test that exercises the branch (method selection). No gate was weakened. | Implementation | `mutation_gates.py`; ledger P13 |
