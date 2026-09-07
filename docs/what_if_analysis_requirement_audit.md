# What-If Analysis — requirement audit

Every requirement of the approved specification, with a verdict and the
evidence for it. A **PASS** requires implemented code **and** a test, a browser
journey, or a measured figure. Code that merely exists is not a pass.

Legend: **PASS** · **PARTIAL** (built, with a stated shortfall) · **FAIL** ·
**N/A**. A **qualified PASS** is a requirement met by a
repository-specific implementation that the evidence shows is better than the
literal reading; the evidence is named on the row and is a test or a measured
figure, never a preference.

**Totals: 78 PASS (2 of them qualified), 0 PARTIAL, 0 FAIL** on the approved specification. The final correction directive is audited separately at the end of this document.

---

## Foundation

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 0 | Branch from `4f79566`, verify commit, clean tree, head `0041` | PASS | Branch `claude/what-if-analysis-rebuild` cut at `4f7956666f…`; `alembic heads` → `0041 (head)` |
| 0 | Do not branch from / merge Lenses, Planner, main | PASS | `git log --oneline main..HEAD` contains only this work |
| 0 | Migrations from `0044` if needed | PASS (none needed) | Head is still `0041`; `threads.describe()["migration_required"] is False`, asserted by test |
| 1 | Persist spec + implementation plan early | PASS | `docs/what_if_analysis_spec.md`, `docs/what_if_analysis_implementation_plan.md`, committed in `fd35a65` |
| 1 | As-built document | PASS | `docs/what_if_analysis_as_built.md` |

## Product core

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 2 | Baseline → scenario → revised state → What-If ECL → Δ → % → drivers | PASS | `run.WhatIfResult.context()` carries all seven; `test_every_result_carries_the_context_it_needs` |
| 3 | Rename Stress Testing → What-If Analysis, no user-facing umbrella | PASS | `navigation.ts` label/href; `product/knowledge.py` capability renamed; browser journey 1 asserts the page title and the absence of the old label |
| 3 | Sector Stress / Borrower Stress retained | PASS | Journey keys `sector`, `borrower` with those titles |
| 4 | Hard-bound to Corporate IFRS 9, no general domain search | PASS | `domain.DATASETS`; `TestTheDomainIsClosed` (4 tests) |
| 4 | Say so when a field is absent rather than joining elsewhere | PASS | `domain.field_refusal`; `test_a_field_it_does_not_carry_is_named_not_guessed`. Extended after a reported defect: `backend/whatif/schema.py` classifies every field REQUIRED or OPTIONAL, resolves columns from the Parquet rather than the catalogue, and names what each absent field costs — as-built §7d |
| 5 | Preserve and extend `backend/whatif`, no second engine | PASS | Component table in as-built §2; one `engine.run()` |
| 6 | Isolate `stress_scenario_basic` from user + LLM routing | PASS | Planner intent, analyst tool registration, Studio binding removed; contract still registered |
| 6 | Absorb magnitude-free trigger vocabulary | PASS | `test_a_magnitude_free_stress_question_opens_a_what_if`; `_opens_whatif` orchestrator path |
| 7 | **19**-grade governed scale, configured hierarchy | PASS | `backend/corporate/ratingscale.py`; `test_it_shows_the_nineteen_governed_grades`; `test_the_scale_is_nineteen_points_and_not_a_relabelled_fourteen` asserts nineteen distinct TTC levels, so there is no fourteen-point scale underneath |
| 7 | 20 × 20 migration display | PASS | `test_it_is_twenty_by_twenty_displayed`; browser journey A |

## Landing and interaction

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 8 | Landing order: heading, composer, six cards, Saved, Models, Recent | PASS | `app/what-if/page.tsx`; `test_the_landing_page_has_six_guided_journeys` |
| 9 | Free-text scenario without clicking a card | PASS | Journey 9 |
| 10 | Six guided starting points, shortcuts not restrictions | PASS | Journey 1 asserts six; landing states it |
| 11 | Clickable chips **and** a retained composer | PASS | `MethodologyGate` buttons + `Composer` always rendered; journeys 2, 4, 9 |
| 12 | Chat is the builder, LLM is not the calculator | PASS | `/interpret` is deterministic regex; no model call on the What-If path |
| 46 | Composer remains open after results, with follow-ups | PASS | Journeys 2, 4, 9 layer a second shock after a result |
| 47 | No artificial chart limit; no irrelevant charts | PASS | Four before/after charts on every result, plus matrices, tiles and the ML charts, with no cap in the code. A chart is suppressed only when every one of its rows is zero — the "no irrelevant charts" half of the requirement. Ten-charts-on-request is not a separate feature; nothing limits how many render. |
| 79 | Informational questions need no methodology | PASS | `test_an_informational_question_is_not_treated_as_a_scenario` |

## The methodology gate

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 13 | Ask before any ECL calculation; never choose silently | PASS | `/execute` returns the gate, not a figure; asserted by test **and** by every browser journey ("no result is shown while the gate is open") |
| 13 | Both options explained, plus free text | PASS | `me.question()`; `gate.free_text is True` |
| 13 | Mandatory for the first calculation; persists; switch is visible | PASS | `test_a_thread_that_has_chosen_is_not_asked_again`; round-trip test; "Change ECL methodology" control |
| 13 | Do not re-ask when the instruction names one | PASS | `test_a_methodology_stated_in_the_instruction_is_not_asked_for` |
| 13 | Every result shows methodology and version | PASS | `context.methodology_stamp`; journeys 1 and 9 assert it |

## Data and state

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 14 | 16 periods resolved dynamically, never hardcoded | PASS | `test_latest_is_resolved_never_hardcoded` |
| 15 | Structured thread state, not the transcript | PASS | `steps.ScenarioState`; round-trip test |
| 16 | add / edit / remove / undo / reset / recompute | PASS | `TestALayeredScenario` (9 tests); journeys 2, 4, 9 |
| 83 | Obligor grain, no facility inflation | PASS | `test_the_grain_is_one_row_per_borrower_per_quarter` |

## The six journeys

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 17 | Rating profile with counts, exposure, PDs, LGD, CCF, ECL, Total | PASS | `pf.rating_profile`; `TestTheRatingProfile` (4 tests); journey 1 |
| 18 | 15×15 migration, four views, row-normalised, matched entities | PASS | `TestTheRatingMigration` (7 tests); journey 1 toggles the exposure view |
| 19–20 | Rating question, compound rules, rating→PD→SICR→Stage→ECL | PASS | `language` population rules; `test_staging_criteria_change_the_answer` |
| 24–26 | Interpretation, source/destination reconciliation, visuals | PASS | `run._rating_movement`; factor and stage tiles, plus four before/after `CategoryBarChart`s (exposure and ECL, by stage and by rating). Journey 6 asserts `[data-chart]` renders with both series. |
| 27–32 | Risk parameters: PD / LGD / CCF profiles and scenarios | PASS | `TestThePdProfile`, `TestTheLgdAndCcfProfiles`; journey 2 |
| 30 | Relative vs pp vs bps semantics | PASS | Delta tests; `test_a_relative_move_is_relative_to_the_level` |
| 33–35 | Stage profile, 3×3 history with curing, stage scenarios | PASS | `TestTheStageMigration`; `test_curing_reduces_the_provision`; journey 3 |
| 36–40 | Ten macro variables, V1 sensitivities, scaling, relative/absolute, UI | PASS | `TestTheMacroMatrix` (10 parametrised + 7); journey 4 asserts all ten |
| 42 | Sector profile, no rating distribution by default | PASS | `TestTheSectorAndBorrowerViews`; journey 5 |
| 43–45 | Top 10 Stage 2 borrowers, history, three result levels | PASS | `test_the_top_stage_2_borrowers_are_stage_2_and_ranked_by_ecl`; journey 6 |

## Staging

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 21 | Rule A and Rule B supported and configurable | PASS | **Both ON in the default What-If rule set.** The two rule sets are separate: `staging.reported()` is what staged the accounts and is not editable; `staging.default()` is what a scenario is staged on and carries Rule A (≥2 notches) and Rule B (PD ≥ 2× pre-scenario). `test_a_two_notch_downgrade_triggers_sicr_under_the_whatif_default`; `test_the_historical_book_is_untouched_by_the_whatif_rules`; browser journeys 10 and 11. |
| 21 | Described as CreditProbe assumptions, not IFRS 9 requirements | PASS | `BASIS_ASSUMPTION`; `test_an_assumption_says_it_is_an_assumption`; API test asserts the wording |
| 22 | One governed source of truth for corporate SICR | PASS | `universe.py` imports `ifrs9.policy`; credit-book generator untouched |
| 23 | Staging Criteria UI: view, edit, enable/disable, versioned, persisted | PASS | `StagingCriteria` component; version fingerprint in every result and save |
| 23 | Add rules, AND/OR | PASS | The screen composes a rule (kind, threshold, name), removes one, and switches ANY/ALL; `POST /whatif/staging` validates each edit before it reaches a run. Journey 10 drives all of it; `test_a_rule_can_be_added_and_then_removed`, `test_rules_can_be_combined_with_and_as_well_as_or`, `test_a_thread_level_override_survives_execution`. |

## Models

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 48–52 | Delta formula, PD/LGD/CCF-EAD/combined | PASS | `TestTheDeltaModel` (6 tests) reproducing the spec's worked examples |
| 53 | Delta configuration page | PASS | `app/what-if/models/delta/page.tsx` from `delta.describe()` |
| 54–55 | XGBoost, not a substitute | PASS | `xgboost==3.1.2`; measured divergence from Delta in as-built §7 |
| 56 | ECL-rate target, denominator documented, leakage tested | PASS | `TestWhatTheModelMaySee` (7 tests) |
| 57 | Stage-aware | **PASS, qualified by measurement** | Both designs are fitted and scored out of time on **every** training run (`train.stage_study`). The single model is kept on the evidence: book-level R² 0.997645 vs 0.997522, RMSE 0.003814 vs 0.003913, exposure-weighted MAE 0.000738 vs 0.000771; and decisively, the governed Stage 1→2 step of **4.07×** is reproduced at **4.09×** (+0.4%) against separate models' **4.38×** (+7.7%) — a bias landing on exactly the borrowers a scenario moves, in the Stage holding 71% of the ECL. Stage 3 has 964 training rows and its own model is worse. Per-Stage error is reported out of time; the Stage interaction (2× PD → 1.68× / 1.25× / 1.17× by Stage) proves Stage is not an intercept. `TestItIsGenuinelyStageAware` (7 tests); journey 8. |
| 58 | Official-ECL anchoring, safe zero handling | PASS | `test_it_moves_the_reported_ecl_rather_than_replacing_it`; `FLOOR` fallback reported |
| 59 | Safe artifact, no pkl, JSON not UBJSON, no identifiers | PASS | `TestTheStoredModel` (8 tests) incl. tamper detection |
| 60 | ML dependencies added cleanly; scipy declared | PASS | `pyproject.toml` / `requirements.txt`; `shap` removed with reason |
| 61 | Explainability suite | PASS | Journey 8 (SHAP, importance, calibration, sensitivity) |
| 62–63 | Client X worked example with real outputs and local SHAP | PASS | Journey 8 scores Client X against the live model |
| 64 | Dev through Q4 2025, ~70/30, time-aware, OOT locked | PASS | `TestTheSplits` (5 tests); measured split in as-built §7 |
| 65 | R², MAE, RMSE, WAPE and slices; no "accuracy" | PASS | `test_it_reports_the_metrics_a_rate_model_should` |
| 66 | Model card incl. the macro limitation | PASS | `test_the_card_states_the_limitations_rather_than_burying_them` |
| 67 | Out-of-distribution warning | PASS | `test_a_big_shock_is_flagged_as_outside_the_training_range` |
| 68 | Preconfigured model, not an empty page | PASS | Journey 8: "an active model is shown, not an empty page" |
| 69–71 | Retrain prompt, chat config, real retraining | PASS | `/models/ml/train` fits, validates, scores OOT, seals, registers; journey 8 |
| 72 | Candidate vs active, comparison, explicit activation | PASS | `test_a_new_model_is_a_candidate_and_never_activates_itself` |
| 73 | Change log | PASS | `test_the_change_log_records_what_happened` |

## Persistence, results, quality

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 74–76 | Save / Saved / Recent, reuse `stress_scenarios`, no needless migration | PASS | `TestSavingAWhatIf` (5 tests); journey 7 |
| 77–78 | Every result shows full context and the narrative | PASS | `ResultContext` + `EclHeadline` + "How this was calculated" |
| 80 | No contractual cash-flow engine | PASS (by scope) | Not implemented; stated in as-built §12 |
| 81 | Preserve governed ECL logic and reconcile the Delta formula | PASS | as-built §5; `WEIGHTED_SCENARIO_FACTOR` preserved |
| 82 | Reuse exact Shapley for deterministic attribution | PASS | `backend/whatif/attribution.py` splits the ECL movement across rating, macro, financial, PD, Stage, LGD, collateral, CCF, EAD and the policy clamps, using `decomposition.shapley_of` — the governed function, refactored so `shapley()` and What-If share one implementation of order-neutrality. Effects sum to the movement; an unmoved driver gets exactly zero; the ML difference is its own labelled line and never a driver. `TestTheDriverAttribution` (10 tests); journey 6. |
| 84 | UI quality, tokens, model badges, baseline vs What-If distinction | PASS | `parts.tsx` uses role tokens only; `npm run lint` clean |
| 85 | Graceful failure, never misleading zeros | PASS | Refusals for unknown period / borrower / field / methodology / model |
| 86 | Access control, no cross-user leakage | PASS | `test_a_viewer_may_not_run_a_what_if`; `test_one_persons_what_if_is_not_another_persons` |
| 87 | Auditability | PASS | as-built §9 |
| 88–99 | Test coverage per layer | PASS | **335** What-If tests, including a schema-contract suite that rebuilds a real lake with a column removed; full breakdown in as-built §10 |
| 100 | Nine browser journeys | PASS | **11/11, 114/114 checks** — the nine, plus staging composition and the staging override reaching the arithmetic |
| 101 | No fake success states | PASS | Every claim in this document is backed by a run |
| 102 | Efficient services, no unrelated scanning | PASS | `domain._cached` per dataset-period; migration 0.5s warm |
| 103 | Regression protection | PASS | Full backend suite **13,023 passed, 37 skipped, 6 failed** — the same six as before this work, all reproduced on the baseline; 542 frontend tests; production build; display contract; feature matrix |
| 108 | Migration graph, single head | PASS | `0041 (head)` |

---

# The final correction directive

Manual acceptance found fourteen things the automated suite had passed over,
and asked for a rebuild of the Corporate IFRS 9 domain underneath them. This
part is audited on the same terms: a **PASS** requires implemented code AND a
test, a browser journey or a measured figure.

## A–N — what manual acceptance found

| | Finding | Verdict | Evidence |
|---|---|---|---|
| A | Rating migration percentages must be ROW normalised | PASS | `migration._as_row_shares`; the payload declares `normalisation`, `reads_as` and `denominator` at the top level and the screen prints the legend; browser journey **A** checks every populated row sums to 100% of its own origin grade |
| B | No Back navigation | PASS | `BackLink` on the thread and both model pages; browser journey **B** clicks it on all three and asserts the destination |
| C | Follow-up questions not answered | PASS | `backend/whatif/investigate.py` + `POST /whatif/investigate`; journey **C** asks five and asserts each is answered, says the scenario is unchanged, produces no new result, and does not move the figure it is about |
| D | XGBoost fails on macOS (libomp) | PASS | `backend/whatif/ml/runtime.py` — checked before the methodology is offered, refused in a sentence with the fixing command and the Delta Model named; 18 tests; journey **D** asserts no `@rpath` reaches the screen |
| E | Raw JSON on the risk-parameter screen | PASS | `RiskParameterPanel`; journey **E** asserts no braces on the PD, LGD or CCF screens and that a distribution is shown |
| F | Insufficient business coherence | PASS | 32 data-quality invariants over all 16 quarters (`tests/corporate/test_data_quality.py`); portfolio reconciliation report; four incoherences fixed at source — as-built §4 |
| G | Must use a governed 19-point scale | PASS | `backend/corporate/ratingscale.py`; nineteen distinct TTC levels, all nineteen grades populated, no fourteen-point scale underneath |
| H | Filters lost — a targeted scenario became whole-book | PASS | `Threshold` carried through the language reader, the step, the state contract and the engine; journey **F** measures **207 borrowers of 3,244**, and the screen restates both filters before calculating |
| I | Stage 3 ECL moved unexplainably | PASS | Root cause was a book holding borrowers credit-impaired by days past due, still rated `B-`; the presumption of default is not rebutted anywhere now. `TestStageThreeIsIsolated` (5 tests) and `_stage_three` name every mechanism or say there is none |
| J | Optional schema warnings too prominent | PASS | Separated into `notes` about the INSTALLATION from `warnings` about the RESULT; folded away and grey; `test_the_loss_is_named_rather_than_hidden` asserts the split |
| K | Stage migration showed PD 0.00% / Stage +243.97% | PASS | `basis` is its own driver labelled "Measurement basis: 12-month PD to lifetime PD", with the borrowers, the exposure and both PDs; journey **G** asserts it is not collapsed into a Stage effect |
| L | AI must let users decode ECL impact conversationally | PASS | Three intents, 27 follow-up question shapes, `run.interpret` composing what the result MEANS with the next questions as buttons; **76** evaluation cases |
| M | Mandatory model-selection gate before the first ECL simulation | PASS | `methodology.needs_gate`; every browser journey that computes asserts the gate appears and that no figure is shown while it is open |
| N | Chat box usable, supports layering | PASS | The composer is never replaced by chips; journeys 1–11 layer shocks and assert the step list |

## §2–§42 — the directive's own sections

| § | Requirement | Verdict | Evidence |
|---|---|---|---|
| 2–4 | A real 19-point scale, not a relabelling; 20 × 20 display | PASS | `test_the_scale_is_nineteen_points_and_not_a_relabelled_fourteen`; `test_it_is_twenty_by_twenty_displayed` |
| 5–7 | Rebuild the Corporate IFRS 9 domain, coherent longitudinal data | PASS | Clean rebuild; 52,880 rows over 16 quarters; `TestTheBookHoldsTogetherOverTime` |
| 8 | Distinct TTC / PIT / lifetime PD with documented formulas | PASS | `ratingscale.ttc_pd`, `pit_pd`, `lifetime_pd`; as-built §4; `TestTheThreePdsAreThreeThings` |
| 9 | Full reconciliation across stage / sector / segment / rating | PASS | `scripts/whatif_reconciliation_report.py` — **16/16 quarters, all four partitions** |
| 10 | EAD = drawn + CCF × undrawn | PASS | `test_exposure_is_drawn_plus_the_conversion_factor_times_undrawn`; CCF is a proportion at both grains |
| 11 | LGD from collateral and haircut | PASS | `test_loss_given_default_sits_between_its_secured_and_unsecured_legs` plus the documented defaulted workout uplift |
| 12–14 | Three intent classes, explicit and tested | PASS | `investigate.classify`; `TestTheThreeIntents` (10 tests); 76 evaluation cases |
| 15 | Stage 3 isolation with hard invariants | PASS | `TestStageThreeIsIsolated`; a shock that cannot reach a defaulted borrower does not move its provision, and any movement carries a named mechanism summing to the whole |
| 16–17 | Measurement basis separate from Stage effect; defined attribution language | PASS | `attribution.LABELS`; `basis_movement` writes the sentence a lender uses |
| 18 | Delta revalidation after the rebuild | PASS | Factors reproduce the ECL to within 0.02 on a SAR 60bn book across rating, PD and LGD shocks |
| 19 | XGBoost portability preflight | PASS | `ml/runtime.py`; `TestThePortabilityPreflight` |
| 20–21 | Retrain from scratch, new version, SHAP, stage study, model card | PASS | Model `2026.09.07`, previous artifacts deleted; OOT R² 0.9979; the study CHOSE the per-Stage design and the product serves it |
| 22 | No raw JSON | PASS | Journey **E** |
| 23 | Back navigation | PASS | Journey **B** |
| 24 | Demote optional-data warnings | PASS | `notes` vs `warnings` |
| 25 | Differentiated error handling | PASS | `lib/whatif-errors.ts`, seven kinds; 9 node tests |
| 26 | Generator / catalogue reconciliation, idempotent | PASS | `catalogue_io.merge` + `reconcile`, and `catalogue.reconcile_published` — which found **31 fields across 4 datasets** that a stale published entry was hiding from every reader |
| 27 | Clean lake rebuild | PASS | `scripts/build_corporate_universe.py` run from empty; catalogue reconciles with the lake |
| 28 | Data quality tests | PASS | 32 invariants over 16 quarters |
| 29 | Longitudinal reasonableness | PASS | `TestTheBookHoldsTogetherOverTime` — no quarter halves or doubles, Stage 2 between 2% and 30%, coverage 0.5%–20% |
| 30 | Macro coherence | PASS | `test_the_provision_moves_with_the_cycle` — coverage and the credit cycle correlate below −0.30 |
| 31 | Model gate confirmation | PASS | `me.confirmation`; asserted in every computing journey |
| 32 | Result interpretation panel | PASS | `run.interpret` + `ResultInterpretation`, with follow-up questions as buttons |
| 33 | Do not re-run the scenario to answer a question | PASS | `backend/whatif/cache.py`; journey **C** asserts no new result and an unmoved figure |
| 34 | AI eval set ≥ 75 questions | PASS | **76** in `tests/evals/whatif_cases.json`, all passing |
| 35 | Browser journeys reproducing the manual failures | PASS | `scripts/acceptance/whatif_manual_failures.mjs` — **7/7, 64/64 checks** |
| 36 | Three readiness cycles | PASS | Recorded in as-built §10 |
| 37 | Red-teaming | PASS | `tests/whatif/test_whatif_red_team.py` — 32 attacks; one got through and is fixed (`policy.bounded`) |
| 38 | Spot-check ≥ 10 borrowers over 8+ quarters | PASS | Reconciliation report — 10 borrowers, 8 quarters, every row ties to within 0.0001, stratified on a fixed seed rather than chosen |
| 39 | Portfolio reconciliation over 16 quarters | PASS | Reconciliation report |
| 40 | Rating distribution for all 19 grades | PASS | Reconciliation report — 19 of 19 populated, TTC monotone, coverage 0.01% at AAA to 60% at D |
| 41 | Update as-built and requirement audit | PASS | This document and `docs/what_if_analysis_as_built.md` |
| 42 | Do not merge, do not open a PR | PASS | Neither done; the branch is pushed |
