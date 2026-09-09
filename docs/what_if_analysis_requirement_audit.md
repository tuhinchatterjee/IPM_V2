# What-If Analysis — requirement audit

Every requirement, what satisfies it, and how that was verified. A requirement
is only marked **DONE** where something can be run to check it: a test, a
browser journey, a measured figure or an endpoint. Where a requirement was met
in a form different from the one asked for, the adaptation is stated in the row
rather than left for a reader to notice.

**Branch:** `claude/what-if-analysis-rebuild` · **Not merged. No pull request.**

Verification keys used below:

| Key | Means |
|---|---|
| `T` | A Python test that fails if the requirement stops being met |
| `J` | A browser journey driving real Chromium against a real backend |
| `M` | A figure measured while writing this, not remembered |
| `E` | An endpoint that serves the evidence |

---

## 1. Product knowledge and conversation

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 8–11 | Product-aware chat: the feature can explain itself, its data, its fields and its methods | `backend/whatif/product.py` — answers composed from live configuration, never from a written page | DONE | `T` `TestProductKnowledge` · `E` `POST /whatif/product/ask` |
| 12 | An answer about the product reads no book and prices nothing | `ASKS` family cannot reach the scenario builder | DONE | `T` `test_only_a_scenario_change_may_move_the_thread` |
| 13 | It answers from what the product IS, not from what it was documented to be | `fields()`, `methodologies()`, `capabilities()` read the live registries | DONE | `T` `test_it_answers_from_the_live_configuration_not_a_written_page` |
| 16 | 13+ intent classes | **14** — help, data, fields, methodology, plausibility, macro_analysis, explain, view, comparison, explainability, export, scenario, modify, macro_config | DONE | `T` 179-case corpus, 2,513 assertions |
| 17 | Intent is state-aware: the same sentence means different things | `classify(q, has_result, has_steps)`; a scenario OPENS in an empty thread and MODIFIES one that has steps | DONE | `T` `test_a_sentence_with_neither_signal_but_a_magnitude_is_a_scenario` |
| 18 | A question never changes a number | Three families; only `CHANGES` may write state | DONE | `T` asserted on every one of the 179 cases |

## 2. Scenario building and the engine

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 20–24 | Scenario steps, layered, removable, reproducible | `backend/whatif/steps.py` — `ScenarioState`, immutable, `to_dict`/`from_dict` round-trip | DONE | `T` `TestTheScenarioState` · `J` 2, 10, 11 |
| 25 | Shocks applied in a fixed order so a scenario is reproducible | `RATING → MACRO → FINANCIAL → PD → LGD → COLLATERAL → EAD` | DONE | `T` `test_the_same_scenario_twice_returns_the_same_figures` |
| 26 | Attribution is order-neutral | Exact Shapley in `backend/whatif/attribution.py` | DONE | `T` `test_it_is_order_neutral` |
| 27 | A scenario never cures a stage or manufactures a default | `np.maximum(stressed, baseline)`; Stage 3 is a fact about the borrower | DONE | `T` red team `test_no_scenario_cures_a_stage` |
| 28 | No provision exceeds the exposure it provides against | `policy.bounded()`, re-applied where both methodologies land | DONE | `T` red team, and a reconciliation check in the workbook |
| 29 | The reported book is never touched | Baseline column is `final_ecl`, untouched | DONE | `T` `test_the_reported_book_is_never_touched` |

## 3. Staging

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 30–34 | Two rule sets, named separately, both versioned on every result | `backend/whatif/staging.py`; reported-book and What-If policies stamped on every figure | DONE | `J` 11 · `T` `TestTheStagingCriteria` |
| 35 | Thread-level criteria: add, remove, re-threshold, AND/OR | `StagingPolicy.with_rule`, composed on screen | DONE | `J` 10, 11 |
| 36 | One governed source of truth for SICR | `backend/ifrs9/policy.py`, imported rather than duplicated | DONE | `T` `test_the_generator_and_the_engine_share_the_constants` |

## 4. Methodologies

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 40–44 | Two approaches: Delta Model and ML | `backend/whatif/delta.py`, `backend/whatif/ml/` | DONE | `T` `TestTheDeltaModel`, `TestTheMlMethodologyIsAnchored` |
| 45 | The product never chooses a methodology quietly | The gate, asked once per thread before the first ECL figure | DONE | `J` every journey checks no result is on screen while the gate is open |
| 46 | XGBoost, not a substituted linear model | Per-Stage XGBoost ensemble, native JSON artifact | DONE | `T` `TestTheStoredModel` |
| 47 | The ML model can never restate the reported book | Anchored: it estimates a relative effect | DONE | `T` `TestTheMlMethodologyIsAnchored` |
| 48 | No security control weakened for the ML stack | Native JSON is already on the allowlist; `.pkl`/`.joblib`/`.pt` remain refused | DONE | `T` `TestWhatTheModelMaySee` |
| 56–58 | Model comparison **in both directions**, with an LLM explanation | `backend/whatif/comparison.py` — one object, direction follows the reader, figures do not | DONE | `T` `test_the_figures_do_not_depend_on_the_direction_asked_from` · `J` 14 |
| 59 | The comparison does not recommend | Forbidden in the prompt; the prose is read back for the words that would amount to picking | DONE | `T` `test_it_never_recommends_a_methodology_in_the_prose` |

## 5. Macro

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 60 | Ten named MEVs | `backend/whatif/macro.py` — all ten, names matching the specification exactly | DONE | `T` `test_it_carries_the_ten_v1_variables` |
| 61–63 | An MEV card per variable, with status, observed level and history | `macro.describe()`; all ten report an observed series over 16 quarters | DONE | `M` all ten `observed`, 16 observations · `J` 12 |
| 64–67 | Empirical analysis: measure the variable against the book | `backend/whatif/macrolab.estimate()` — changes against changes | DONE | `T` `test_every_governed_variable_can_be_estimated` · `J` 12 |
| 68 | The small sample is stated, never hidden | `SMALL_SAMPLE` on every fit; shown on the card | DONE | `J` 12 `the small sample is stated rather than hidden` |
| 69–71 | User-defined sensitivity, in force for the thread only | `Sensitivity(source=USER)`; the governed matrix is never edited | DONE | `T` `TestAnOverrideCannotPassForGoverned` · `J` 12 |
| 72 | An override is labelled wherever the number appears | On the step, the provenance line, the saved What-If and the workbook | DONE | `T` `test_an_override_is_on_the_provenance_line_not_only_the_step` |
| 73 | Never a silent substitution | `recommend()` returns the configured sensitivity in every case, with the reasoning | DONE | `T` `test_an_estimate_is_never_silently_substituted_for_the_configured_one` |

## 6. Interpretation and plausibility

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 74–76 | LLM interpretation after every successful calculation | `narrative.interpret()`, wired into `POST /whatif/execute` | DONE | `J` 13 · `E` `interpretation` on every result |
| 77 | The engine calculates; the model explains | The model is given a packet, no tools and no book | DONE | `T` `test_the_evidence_is_the_only_thing_the_writer_knows` |
| 78 | If a number is not in evidence, the model must not state it | `narrative.check()` re-reads the prose; a paragraph carrying one is discarded | DONE | `T` `TestAFigureThatWasNeverComputed`, six attacks |
| 81–86 | Scenario plausibility from historical evidence | `backend/whatif/plausibility.py` — six controlled labels over the book's own movement | DONE | `T` `test_a_small_shock_and_a_large_one_are_not_read_the_same` |
| 87 | Never a forecast and never a probability | Forbidden in the prompt; every verdict read back for the words | DONE | `T` `TestPlausibilityPromisesNothing` |
| 88 | Severity is monotonic in the size of the shock | Ordered thresholds on observed share | DONE | `T` `test_a_bigger_shock_is_never_read_as_more_ordinary` |

## 7. Export

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 91–93 | Audit-grade detailed Excel export | `backend/whatif/workbook.py` — eleven sheets | DONE | `T` `TestTheWorkbookIsComplete` · `J` 15 |
| 94 | Borrower grain, every field before and after | `BORROWER DETAIL`, 19 columns | DONE | `T` `test_the_borrower_sheet_carries_before_and_after_for_every_parameter` |
| 95 | Facility / account grain | `FACILITY DETAIL` — **adapted**: staging here is assessed on the obligor, so there is no facility-level measurement to export. The sheet carries the borrower movement ALLOCATED by IFRS 9 EAD share, says so in its own heading and in a column, and sums back exactly | DONE, adapted | `T` `test_the_allocation_sums_back_to_the_borrower_figure` |
| 96 | Attribution in the workbook | `ATTRIBUTION` — the exact Shapley split and anything unexplained, named | DONE | `T` `TestTheWorkbookIsComplete` |
| 97 | Reconciliation tests | `RECONCILIATION` — nine tie-outs recomputed from the workbook's own figures | DONE | `T` `TestTheReconciliationIsEvidenceNotAClaim` |
| 98 | A saved scenario reproduces | `REPRODUCE` carries the exact state | DONE | `T` `test_the_reproduce_sheet_carries_the_state_that_reruns_it` |
| 99 | Both methodologies exportable | The workbook is built from whichever result was priced; the methodology is stamped on the cover and in `METHOD` | DONE | `T` `test_the_cover_carries_the_provenance_a_reader_will_be_asked_for` |
| 100–101 | Export security: user/workspace access control, no cross-user leakage | A held result is readable only by the account that produced it; every download audited with hash, size and rows | DONE | `T` `TestSomebodyElsesBook` · `J` 15 |

## 8. Integration

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 5, 115 | Ready for a canonical IFRS 9 domain to replace this dataset | `backend/whatif/integration.py` — a contract, and an assessment that says what would break and what each break costs | DONE | `T` `TestTheIntegrationContract` · `E` `GET /whatif/integration/{contract,readiness}` |
| — | The grain is the thing that must not be got wrong | Blocked rather than warned: a facility-grain book read as obligor-grain multiplies every figure and looks plausible | DONE | `T` `test_a_finer_grain_book_is_blocked_not_warned` |
| — | The report does not overclaim | It states that it does not check whether the numbers are right | DONE | `T` `test_it_says_what_it_does_not_check` |

## 8b. Economic coherence of the book

The section this audit did not have, and the reason the previous pass could not
claim READY FOR UAT: schema, ranges and reconciliation say nothing about
whether the book behaves like a credit portfolio.

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| E1 | 19-point rating economics: monotonic risk, no inversions | `scripts/whatif_economic_validation.py` §1 | DONE | `M` every measure rises; ordinal tolerance = 2 standard errors |
| E2 | TTC / PIT / lifetime are genuinely different concepts | §2 | DONE | `T` TTC constant per grade in all 16 quarters; PIT tracks the cycle at −0.85 against TTC's −0.77 |
| E3 | Stage economics plausible; Stage 3 genuinely impaired | §3 | DONE | `T` 0.29% / 6.59% / 61.03%; Stage 3 audited in every quarter |
| E4 | Stage migration economics | §4 | DONE | `T` S2→S1 cure 20.9%, was 36% |
| E5 | Rating migration economics, QoQ and YoY | §5 | DONE | `T` 86.5% stable, was 25.8% |
| E6 | ECL economics; Downside ≥ Base ≥ Upside | §6 | DONE | `M` by construction from the governed weights; weighted rebuild ties to machine precision |
| E7 | LGD / collateral economics | §7 | DONE | `M` Spearman −0.66; 62.4% → 35.0% across coverage bands |
| E8 | CCF / EAD economics | §8 | DONE | `M` identity holds; flat CCF by stage reported as methodology |
| E9 | Quarter-to-quarter continuity | §9 | DONE | `M` percentiles reported; median notch movement 0 |
| E10 | ≥20 random borrowers reviewed | §10 | DONE | `M` 20 stratified-random, 8 quarters each, no incoherent trajectory |
| E11 | Sector economics, differential cyclicality | §11 | DONE | `M` 172× ECL spread; cycle correlation −0.97 to −0.75 |
| E12 | Segment economics | §12 | DONE | `M` 1.6× spread, held to its own documented bound |
| E13 | Macro / PIT relationship, cycle not double-counted | §13 | DONE | `M` PIT tracks the cycle harder than TTC |
| E14 | Default / Stage 3 logic audited both directions | §14 | DONE | `T` every quarter |
| E15 | What-If economic sanity, six scenarios | `scripts/whatif_scenario_economics.py` | DONE | **50/50**, each against an expectation written first |
| E16 | Delta vs XGB economic comparison | same | DONE | direction, amplification, boundary and training support |
| E17 | Bounds derived, not imported | §7 of the report | DONE | 3 external bounds named as such; everything else ordinal or an identity |
| E18 | Generator fixed rather than tests loosened | six findings, six fixes | DONE | `T` `tests/corporate/test_economic_coherence.py` |
| E19 | Economic validation report | `docs/what_if_ifrs9_economic_validation.md` + 2 JSON artifacts | DONE | — |
| E20 | The gate | ECONOMIC VALIDATION: **PASS** | DONE | re-run every readiness cycle |

---

## 9. Verification

| # | Requirement | Satisfied by | Status | Verified |
|---|---|---|---|---|
| 108 | ≥100 AI eval cases | **179**, across all fourteen intents, each carrying the thread state it is read in | DONE | `T` 2,513 assertions |
| 109 | The manual-failure journeys still hold | `scripts/acceptance/whatif_manual_failures.mjs` | DONE | `J` 8/8 journeys, 71/71 checks |
| 110 | Performance measured | `scripts/whatif_performance.py` → `docs/whatif_performance.json` | DONE | `M` every interaction inside budget |
| 111 | Three readiness cycles | `scripts/whatif_readiness_cycle.sh` → `docs/readiness/` | DONE | Six run; the last three clean, each including both economic harnesses |
| 112 | Red-teamed | `tests/whatif/test_whatif_red_team.py` — eleven shapes of attack | DONE | `T` 54 tests |
| 113 | Full regression | the whole suite | DONE | 15,811 passed; 6 pre-existing failures, none in What-If |
| 114 | Documentation | `docs/WHATIF.md`, rewritten against what the feature now is | DONE | Every figure in it measured while writing |
| 116 | Final UAT report | `docs/what_if_analysis_uat_report.md` | DONE | — |
| 117 | The READY FOR UAT gate | Only after every row above | DONE | See the UAT report |

---

## Adaptations, stated

Two requirements were met in a form different from the one asked for. Both are
recorded here rather than in a footnote, because a requirement quietly
reinterpreted is a requirement dropped.

**Facility / account grain in the export (§95).** IFRS 9 staging in this domain
is assessed on the obligor — a book that stages one facility of a borrower
differently from another is describing a bank that does not exist — so there is
no facility-level measurement to export. The sheet carries the borrower's
movement allocated across their facilities by IFRS 9 EAD share, labelled an
allocation in the sheet's own heading and in a column of its own, and summing
back to the borrower figure exactly. Presenting an allocation as a measurement
is the one thing that sheet must not do.

**The empirical macro relationships (§64–67).** They are computed, shown and
offered — and `recommend()` returns the configured sensitivity in every one of
the ten cases. That is not the analysis failing; it is the analysis being read
honestly. `corporate_macro` is generated from a single latent cycle factor, so
every observed series is a linear function of it plus noise: a regression on
this data recovers the generator's own arithmetic. Sixteen quarters give fifteen
changes at most, which is enough to see whether a relationship runs in the
direction the configured sensitivity assumes and roughly how hard, and is not a
calibration. Both facts are stated on the card, in the fit, and in the
recommendation. A canonical domain with genuinely independent series would make
those estimates mean what they appear to mean.

---

## Not claimed

- **The economics of the shipped book are not validated by any of this.** The
  integration report can establish that a column called `pd_12m` exists, is
  numeric and lies between 0 and 100. It cannot establish that it is the
  twelve-month probability of default.
- **Re-scoping a step that already exists is not supported.** Recorded as a
  known gap in the evaluation corpus, with a test that it still behaves as
  recorded and does not silently change the scenario.
- **Covenant re-testing under stress is reported, not re-evaluated.**
- **The macro sensitivities are declared assumptions**, and every screen that
  shows one says so.
