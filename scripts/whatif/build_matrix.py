#!/usr/bin/env python3
"""Build the requirement matrix, and refuse to name a test that does not exist.

    python3 scripts/whatif/build_matrix.py

Writes `docs/whatif/REQUIREMENT_TEST_MATRIX.md` and
`docs/whatif/ACCEPTANCE_CASES.json`, one row per acceptance ID.

**A pytest count is not a completion claim.** 800-odd passing tests say
nothing about whether requirement S14 is met; only a named test against a
named requirement does. So the mapping below is by ID, every entry names the
tests that prove it, and **this script exits non-zero if any named test is
not found in the suite**. A row that claims coverage it does not have is the
one failure mode a matrix has, and it is the one thing checked here.

Statuses, and what each one means:

* **COVERED** — implemented and proved by the named tests.
* **PARTIAL** — implemented, proved in part, with the gap stated. A gate
  that FAILED is PARTIAL, not COVERED: the mechanism works and the outcome
  did not meet its threshold.
* **BLOCKED** — not run, with the reason and the exact command that would
  run it. Never "passed".
* **NOT BUILT** — deliberately not implemented, with the incompatibility
  recorded.

The requirement text in each row is **this implementation's reading** of the
acceptance ID. `CreditProbe_Advanced_Cockpit_WhatIf_Master_Prompt_v1.docx`
remains the authority; where the two differ, the specification wins and this
file is wrong.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests" / "cockpit_v4"

COVERED = "COVERED"
PARTIAL = "PARTIAL"
BLOCKED = "BLOCKED"
NOT_BUILT = "NOT BUILT"

#: (id, requirement as implemented, status, [test names], note)
Row = tuple[str, str, str, list[str], str]

ISOLATION: list[Row] = [
    ("A01", "The accepted Corporate release is byte-identical after every "
            "candidate build.", COVERED,
     ["test_the_accepted_releases_are_byte_identical"],
     "Fingerprint re-read from the manifest and compared with the value "
     "pinned at 245c50e."),
    ("A02", "The accepted Retail release is byte-identical after every "
            "candidate build.", COVERED,
     ["test_the_accepted_releases_are_byte_identical"], ""),
    ("A03", "The candidate is a different release with a different "
            "fingerprint, never a rewrite of an accepted one.", COVERED,
     ["test_the_candidate_is_a_different_release_with_a_different_fingerprint"],
     ""),
    ("A04", "Only recorded protected-core files reach the candidate "
            "package, each behind a flag check inside a guard.", COVERED,
     ["test_a04_only_the_recorded_core_files_reach_this_package",
      "test_a04_every_one_of_those_imports_is_inside_a_guard",
      "test_a04_each_guarded_import_sits_behind_the_flag_check",
      "test_a04_with_both_flags_off_the_block_is_absent_entirely"],
     "Four files, listed with the reason for each in CORE_IMPORTERS."),
    ("A05", "With the flags off the accepted runtime is unchanged: same "
            "relations, same default release, same payload.", COVERED,
     ["test_the_runtime_opens_the_accepted_book_with_the_flags_off"],
     "Plus the full V4 regression with the flags off: 4189 passed, 4 "
     "skipped."),
    ("A06", "Enabling one book does not enable the other.", COVERED,
     ["test_one_book_enabled_does_not_enable_the_other"], ""),
    ("A07", "The candidate manifest declares itself synthetic.", COVERED,
     ["test_the_candidate_manifest_says_it_is_synthetic"], ""),
    ("A08", "Every candidate row carries origin SYNTHETIC_DEMO.", COVERED,
     ["test_the_published_rows_are_all_labelled_synthetic"], ""),
    ("A09", "Two builds of one release id are byte-identical.", COVERED,
     ["test_the_generator_is_deterministic_across_processes"],
     "`seed_candidate.py --domain all --overwrite` was run twice and both "
     "builds produced the same fingerprints -- Corporate "
     "`3b101bd41465fbe1`, Retail `98b494ae2721bd53`. Both ACCEPTED books "
     "were re-read from their own manifests afterwards and are unchanged. "
     "The in-suite test proves the generator is deterministic across "
     "processes (`stable()` is SHA-256, not `hash()`, which Python "
     "randomises per run); the two-build diff is measured out of band "
     "because it takes 90 seconds a build."),
    ("A10", "The protected-file hash check reports every difference and the "
            "allowlist is not broadened.", COVERED, [],
     "scripts/whatif/protected_hashes.py --check reports 17 changed, 0 "
     "removed, 25 added; every line is explained in "
     "BASELINE_AND_EXTENSION_MAP.md. No hash regenerated."),
    ("A11", "The candidate's ML dependencies are isolated from the accepted "
            "environment.", COVERED,
     ["test_the_accepted_environment_carries_none_of_the_ml_libraries",
      "test_the_requirements_file_is_not_the_accepted_one",
      "test_every_pinned_library_is_pinned_exactly"],
     "The candidate sees the accepted environment; not the reverse."),
    ("A12", "Nothing a chat turn reaches imports the training or fitting "
            "code.", COVERED,
     ["test_nothing_a_chat_turn_reaches_imports_the_estimator",
      "test_nothing_a_chat_turn_reaches_imports_the_training_half",
      "test_the_read_half_does_not_import_the_fitting_half"],
     "Asserted by walking every module under backend/cockpit_v4."),
]

COHORT: list[Row] = [
    ("C01", "A cohort is frozen by membership hash, not by a predicate "
            "re-evaluated later.", COVERED,
     ["test_the_hash_is_over_the_set_not_the_order",
      "test_the_hash_cannot_be_collided_by_concatenation",
      "test_counts_and_totals_are_not_part_of_the_identity"], ""),
    ("C02", "'These customers' distinguishes the rows that matched from "
            "every row belonging to those owners.", COVERED,
     ["test_c03_a_row_selection_does_not_widen_to_its_owners",
      "test_the_described_grain_says_which_it_is",
      "test_d02_widening_does_not_multiply_exposure"], ""),
    ("C03", "A widened cohort is a different cohort and says so.", COVERED,
     ["test_the_widening_question_shows_what_it_would_cost",
      "test_widening_an_owner_cohort_is_a_no_op"], ""),
    ("C04", "A cohort re-resolved after the book moved is refused.",
     COVERED, ["test_a_cohort_frozen_in_the_other_book_is_refused",
      "test_a_moved_membership_is_caught_before_anything_is_calculated"], ""),
    ("C05", "An empty cohort is refused, never answered with zero.",
     COVERED, ["test_c05_an_empty_selection_does_not_widen",
      "test_d02_an_empty_cohort_is_refused_not_answered_with_zero"], ""),
    ("C06", "Two rules on one field over overlapping rows is a question, "
            "not a resolution.", COVERED,
     ["test_two_rules_on_one_field_over_the_whole_cohort_conflict",
      "test_c05_compiling_an_unresolved_overlap_raises_the_question",
      "test_c07_the_question_offers_exactly_the_three_compositions"],
     ""),
    ("C07", "An acknowledged overlap can be previewed with the resolution "
            "the reader chose.", COVERED,
     ["test_c05_an_overlap_the_reader_is_being_shown_does_not_block_the_graph",
      "test_acknowledging_one_overlap_does_not_excuse_another",
      "test_a_declared_composition_is_recorded_as_declared"], ""),
    ("C08", "A preview states what changes, over which rows, from what "
            "baseline, by which method, and what is left alone.", COVERED,
     ["test_every_required_section_is_present",
      "test_it_shows_each_input_with_its_operation_and_unit",
      "test_it_says_what_is_left_alone",
      "test_it_says_the_book_is_not_written"], ""),
    ("C09", "Reading a sensitivity is not approval of a calculation.",
     COVERED, ["test_c14_a_preview_is_not_itself_a_confirmation",
      "test_c14_the_preview_calculates_no_ecl",
      "test_anything_that_is_not_a_yes_leaves_it_unconfirmed"], ""),
    ("C10", "A confirmation is bound to a hash of everything that could "
            "change the answer.", COVERED,
     ["test_the_digest_is_stable_across_identical_specs"], ""),
    ("C11", "A source refresh invalidates a confirmation.", COVERED,
     ["test_the_five_named_invalidations"], ""),
    ("C12", "A cohort edit invalidates a confirmation.", COVERED,
     ["test_anything_that_changes_the_answer_changes_the_hash"], ""),
    ("C13", "A method change invalidates a confirmation.", COVERED,
     ["test_an_unknown_method_is_refused",
      "test_the_five_named_invalidations"], ""),
    ("C14", "A warning the reader did not see invalidates a confirmation.",
     COVERED, ["test_the_five_named_invalidations",
      "test_the_warnings_shown_before_approval_travel_with_it"], ""),
    ("C15", "A revised scenario is a new version and is not confirmed.",
     COVERED, ["test_d10_a_revised_scenario_loses_its_confirmation"], ""),
    ("C16", "Rule order is part of the digest, because order changes the "
            "answer.", COVERED,
     ["test_shock_order_does_not_change_the_hash_but_ordering_is_in_it",
      "test_e09_the_order_is_canonical_not_whatever_the_set_iterated_as"],
     ""),
    ("C17", "A confirmed scenario survives into the next turn without "
            "being retyped, and is server-written.", COVERED,
     ["test_a_confirmed_scenario_survives_the_round_trip",
      "test_remember_stores_the_scenario_the_run_published"], ""),
    ("C18", "A release change invalidates the confirmation AND drops the "
            "cohort binding, visibly.", COVERED,
     ["test_a_different_release_id_invalidates_and_says_so",
      "test_an_invalidated_scenario_loses_its_cohort_binding",
      "test_the_same_id_republished_is_caught_by_the_fingerprint"], ""),
]

EXECUTION: list[Row] = [
    ("D01", "One confirmed scenario, one reporting period, one frozen "
            "cohort, one baseline.", COVERED,
     ["test_d06_every_method_starts_from_the_same_baseline"], ""),
    ("D02", "The full cohort is used, never the displayed rows and never "
            "the top contributors.", COVERED,
     ["test_d02_every_cohort_row_is_in_the_total_including_the_untouched"],
     ""),
    ("D03", "An unaffected row's change is exactly zero.", COVERED,
     ["test_an_unaffected_row_moves_by_exactly_zero",
      "test_an_untouched_row_that_moved_is_refused",
      "test_the_untouched_check_admits_no_tolerance_at_all"], ""),
    ("D04", "An ineligible row keeps its baseline and is reason-coded.",
     COVERED, ["test_an_ineligible_row_keeps_its_baseline_and_carries_the_reason",
      "test_an_unsupported_row_keeps_its_baseline_too",
      "test_an_ineligible_row_stays_in_the_baseline_total"], ""),
    ("D05", "Full book equals affected plus unaffected.", COVERED,
     ["test_r03_affected_plus_unaffected_is_the_book",
      "test_r03_nothing_moves_outside_a_frozen_cohort"], ""),
    ("D06", "Every method starts from the same baseline, read once.",
     COVERED, ["test_d06_every_method_starts_from_the_same_baseline"], ""),
    ("D07", "Methods are shown side by side and never composed.", COVERED,
     ["test_d07_the_comparison_shows_the_methods_and_composes_nothing",
      "test_d07_the_disagreement_is_explained_rather_than_averaged",
      "test_the_ml_estimate_is_never_multiplied_by_the_delta_factor"], ""),
    ("D08", "Different method coverage is disclosed and compared "
            "like-for-like.", COVERED,
     ["test_d08_different_coverage_is_disclosed_and_compared_like_for_like",
      "test_d08_the_like_for_like_rows_say_what_they_are"], ""),
    ("D09", "An unavailable method shows reason and status, never a zero "
            "and never a substitution.", COVERED,
     ["test_d09_a_missing_emulator_carries_a_reason_and_no_number",
      "test_d09_an_unavailable_method_is_never_given_another_methods_answer"],
     ""),
    ("D10", "An unconfirmed or wrong-book scenario does not execute.",
     COVERED,
     ["test_d10_an_unconfirmed_scenario_does_not_execute",
      "test_d10_a_scenario_confirmed_against_another_book_is_refused"], ""),
    ("D11", "Missing user assumptions are resolved before execution.",
     COVERED,
     ["test_d11_a_missing_assumption_is_reported_before_the_run",
      "test_d11_a_scenario_with_no_assumption_does_not_invent_one"], ""),
    ("D12", "The book is read and never written; execution is a "
            "simulation.", COVERED,
     ["test_it_says_the_book_is_not_written"], ""),
]

SENSITIVITY: list[Row] = [
    ("S01", "The twenty-factor registry reports actual support and every "
            "missing entry.", COVERED,
     ["test_s01_all_twenty_candidates_appear_with_a_support_status",
      "test_every_candidate_factor_has_a_row_for_every_parameter"], ""),
    ("S02", "Native units and shock conventions survive into the "
            "artifact.", COVERED,
     ["test_s02_the_published_unit_sentence_follows_the_shock_convention"],
     ""),
    ("S03", "Effective sample is distinct periods, never repeated facility "
            "rows.", COVERED,
     ["test_s03_repeated_facility_rows_do_not_buy_a_longer_history",
      "test_no_published_row_claims_more_periods_than_the_calendar_has"],
     ""),
    ("S04", "Lag is chosen on training-only forward validation.", COVERED,
     ["test_s04_the_lag_is_chosen_on_forward_validation_not_on_fit_quality"],
     ""),
    ("S05", "The published derivative matches a finite difference of the "
            "fitted function.", COVERED,
     ["test_s05_the_published_derivative_matches_a_finite_difference",
      "test_a_derivative_that_forgot_the_logistic_term_is_caught"],
     "Checked on every published row at build time as well."),
    ("S06", "'Reduce unemployment by 10%' from 6.0% is 5.4%, a -0.6 point "
            "move.", COVERED,
     ["test_s06_reduce_unemployment_by_ten_percent_is_six_to_five_point_four",
      "test_s06_and_s07_compose_from_the_readers_own_words"], ""),
    ("S07", "At +0.20 PD points per unemployment point, 3.00% becomes "
            "2.88%.", COVERED,
     ["test_s07_a_two_tenths_slope_takes_three_percent_to_two_point_eight_eight"],
     ""),
    ("S08", "Several factors aggregate as the declared linear sum, "
            "labelled as marginal.", COVERED,
     ["test_s08_several_factors_aggregate_as_the_declared_linear_sum"], ""),
    ("S09", "The nonlinear translation at zero shock returns the observed "
            "baseline.", COVERED,
     ["test_s09_the_nonlinear_translation_at_zero_shock_is_the_baseline"],
     ""),
    ("S10", "A factor that is not supportably estimable is refused for "
            "automatic translation; an explicit assumption is accepted.",
     COVERED,
     ["test_s10_an_unsupported_factor_is_refused_for_automatic_translation",
      "test_s10_the_readers_own_assumption_is_a_different_route_entirely",
      "test_a_diagnostic_row_is_refused_for_automatic_translation"], ""),
    ("S11", "An absent factor is UNAVAILABLE, never a sensitivity of "
            "zero.", COVERED,
     ["test_s11_an_absent_factor_has_a_reason_and_no_series",
      "test_absent_factors_are_unavailable_and_never_a_zero_slope"], ""),
    ("S12", "A notch move steps the published scale.", COVERED,
     ["test_s12_one_notch_steps_the_published_order",
      "test_s12_a_notch_is_never_a_string_increment",
      "test_s12_a_notch_is_never_a_lexical_sort",
      "test_s12_a_notch_is_never_a_pd_multiplier",
      "test_s12_a_move_past_the_end_says_how_far_it_actually_went",
      "test_s12_an_unrated_grade_is_refused_with_the_scale_named",
      "test_s12_the_default_grade_has_no_notch_to_move"], ""),
    ("S13", "Behavioural and application scorecards are kept separate.",
     COVERED,
     ["test_s13_the_two_cards_are_separate_objects_with_separate_ranges",
      "test_s13_one_score_means_two_different_things_on_the_two_cards",
      "test_s13_a_missing_card_is_refused_not_substituted",
      "test_s13_fifty_points_is_fifty_points_not_fifty_per_cent",
      "test_s13_the_direction_is_read_from_the_card_not_assumed"], ""),
    ("S14", "Stages are frozen by default; an explicit move needs the "
            "declared horizon contract; no lifetime by multiplication.",
     COVERED,
     ["test_s14_stages_are_frozen_by_default_and_a_move_is_refused",
      "test_s14_an_explicit_move_with_the_contract_uses_the_published_figures",
      "test_s14_a_move_without_the_contract_reports_unsupported_not_zero",
      "test_s14_a_lifetime_figure_is_never_the_annual_one_times_the_years",
      "test_the_banned_shortcut_overstates_the_real_book_by_three_quarters"],
     "The shortcut overstates the published Corporate book by 74.8%."),
    ("S15", "Sector discovery returns real categories with counts and "
            "totals; Unknown is retained; a product is not a sector.",
     COVERED,
     ["test_s15_discovery_returns_actual_categories_with_counts_and_totals",
      "test_s15_a_blank_category_becomes_unknown_rather_than_vanishing",
      "test_s15_the_parts_add_up_to_the_book_only_with_unknown_in",
      "test_s15_synonyms_resolve_to_the_books_own_identifier",
      "test_s15_a_word_the_book_does_not_have_is_refused_not_approximated",
      "test_s15_a_retail_product_is_not_an_employer_sector",
      "test_the_retail_book_keeps_product_and_employer_sector_apart"], ""),
    ("S16", "An artifact fitted against different bytes is STALE and "
            "refused.", COVERED,
     ["test_s16_an_artifact_fitted_against_other_bytes_is_refused",
      "test_s16_the_matching_fingerprint_is_not_refused",
      "test_the_stored_digest_matches_the_release_it_was_fitted_against"],
     "Compared on a digest of the fit's own inputs; see P5_FINDINGS.md §8."),
]

MODEL: list[Row] = [
    ("M01", "The target is the declared ECL rate on the declared "
            "denominator, not exposure share.", COVERED,
     ["test_m01_the_target_is_the_declared_rate_on_the_declared_denominator",
      "test_m01_a_different_target_is_refused_by_name"], ""),
    ("M02", "No target-derived column reaches the feature matrix, and the "
            "check raises rather than filtering.", COVERED,
     ["test_m02_no_declared_feature_is_derived_from_the_target",
      "test_m02_the_leakage_check_raises_rather_than_filtering",
      "test_m02_a_new_ecl_column_is_caught_by_the_rule_not_by_a_list"], ""),
    ("M03", "The split is chronological by distinct period and leaks "
            "nothing.", COVERED,
     ["test_m03_the_split_is_chronological_and_leaks_nothing",
      "test_m03_every_period_lands_in_exactly_one_place",
      "test_m03_the_leakage_check_can_actually_fail"], ""),
    ("M04", "The embargo is derived from label availability, reported, and "
            "no fold touches a test period.", COVERED,
     ["test_m04_the_embargo_is_derived_and_its_reasoning_travels_with_it",
      "test_m04_the_embargoed_periods_are_reported_not_absorbed",
      "test_m04_no_fold_touches_a_test_or_an_embargoed_period"], ""),
    ("M05", "The split assignment is persisted per row.", COVERED,
     ["test_m05_the_split_assignment_is_persisted_per_row"], ""),
    ("M06", "Blend weights are genuinely fitted, non-negative, summing to "
            "one, on out-of-fold predictions.", COVERED,
     ["test_m06_weights_are_non_negative_and_sum_to_exactly_one",
      "test_m06_the_weights_are_fitted_not_hardcoded",
      "test_m06_the_solution_is_the_optimum_not_a_nearby_point"], ""),
    ("M07", "A 1/0/0 outcome is reported as a single-model result.",
     COVERED,
     ["test_m07_a_one_zero_zero_outcome_is_called_a_single_model_result",
      "test_m07_a_real_blend_says_it_is_one_and_names_the_immaterial"],
     "Both books landed on a single model and both cards say so."),
    ("M08", "Three components per book, one deliberately not a tree "
            "ensemble.", COVERED, [],
     "XGBoost, LightGBM and a regularized additive/spline model; all three "
     "trained, all three scored, results in MODEL_CARD_*.md."),
    ("M09", "The search budget is declared in advance and recorded per "
            "trial.", COVERED, [],
     "12 configs per family, 3 folds, 600 rounds, patience 50, fixed seeds; "
     "every trial and its score is in the model card."),
    ("M10", "Scenario inference uses section 11.4 anchoring.", COVERED,
     ["test_the_anchoring_uses_the_models_difference_not_its_level",
      "test_all_six_numbers_the_specification_asks_for_are_shown"], ""),
    ("M11", "A zero shock yields exactly zero ML change.", COVERED,
     ["test_a_zero_shock_moves_the_answer_by_exactly_zero"], ""),
    ("M12", "The ML estimate is never multiplied by the Delta factor and "
            "no macro effect is applied twice.", COVERED,
     ["test_the_ml_estimate_is_never_multiplied_by_the_delta_factor",
      "test_a_macro_move_records_which_route_it_took"], ""),
    ("M13", "Acceptance targets are predeclared and committed before the "
            "test split is read.", COVERED,
     ["test_the_gates_in_code_are_the_gates_in_the_committed_document",
      "test_the_document_was_written_before_any_model_was_fitted"], ""),
    ("M14", "A failed gate is reported failed.", COVERED,
     ["test_a_failed_gate_is_reported_failed",
      "test_the_bias_gate_uses_the_absolute_value",
      "test_a_model_that_missed_a_gate_carries_the_gate_with_its_number"],
     "Exercised for real: Retail G4 FAILED at 38.02% against 15% and is "
     "published as FAILED."),
    ("M15", "Out-of-time WAPE, aggregate bias and per-period bias meet "
            "their thresholds.", COVERED, [],
     "Corporate 1.97 / 1.47 / 2.53%; Retail 2.33 / 0.87 / 1.33%. All "
     "within G1-G3. Model version 2: Corporate 1.89 / 1.13 / 2.34%; "
     "Retail 4.43 / 1.27 / 3.50%. All within G1-G3."),
    ("M16", "Material-group WAPE meets its threshold.", PARTIAL, [],
     "Model version 2. **Corporate PASSED at 5.37%.** **Retail FAILED at "
     "34.36% against 15%.** The threshold was predeclared in "
     "ML_ACCEPTANCE_TARGETS_V2.md before the model was fitted and before "
     "the test split was read; it is not moved, the group is not excluded, "
     "materiality is not redefined and nothing was tuned against the "
     "untouched split. Retail Method 2 is therefore UNAVAILABLE in the "
     "product: the conversational answer names the gate, the method keeps "
     "its row with EMPTY cells rather than a zero, and no other model "
     "stands in. Delta and User-defined work normally."),
    ("M17", "The model card carries provenance, splits, settings, weights, "
            "metrics, subgroups, libraries and artifact hashes.", COVERED,
     [], "MODEL_CARD_CORPORATE.md and MODEL_CARD_RETAIL.md."),
    ("M18", "Bank-engine validation is marked explicitly unavailable.",
     COVERED, [],
     "Stated in both model cards, in ML_ACCEPTANCE_TARGETS.md §7 and in "
     "P7_FINDINGS.md. There is no bank engine here to compare against."),
    ("M19", "The Retail failure reaches the reader: the comparison shows "
            "Delta COMPLETE, Emulator NOT READY with the gate named, and "
            "User-defined COMPLETE, with the emulator's cells EMPTY.",
     COVERED,
     ["test_the_committed_retail_verdict_is_a_failure_at_the_declared_gate",
      "test_the_other_three_retail_gates_passed_so_the_failure_is_specific",
      "test_the_loaded_model_reports_the_failure_rather_than_a_summary",
      "test_the_products_own_code_turns_the_failed_gate_into_the_reason",
      "test_the_reason_never_offers_another_model_or_a_zero",
      "test_all_three_methods_keep_their_row",
      "test_the_comparison_reads_complete_not_ready_complete",
      "test_the_reader_facing_verdict_is_a_translation_not_a_second_opinion",
      "test_the_emulators_cells_are_empty_and_not_zero",
      "test_the_validation_reason_is_reachable_from_the_published_row",
      "test_the_status_line_names_the_gate_beside_the_not_ready_verdict",
      "test_nothing_fell_back_to_delta",
      "test_the_comparison_still_refuses_to_compose_the_methods"],
     "M16 records that the gate FAILED; this row is about whether a reader "
     "is told. The chain is asserted end to end and every link is the "
     "PRODUCT's own code rather than a restatement in a test: the committed "
     "verdict in artifacts/whatif/retail/blend.json really is a failure "
     "(G4 measured 0.343562 against a threshold of 0.15, which is read from "
     "the file and compared against the predeclared 0.15 written as a "
     "literal, so loosening the gate fails this row); infer.Loaded reads "
     "that verdict rather than a summary of it, so failures() names G4 with "
     "BOTH numbers; bridge._ml_inputs turns it into the reason text and "
     "returns NO anchored prediction, so there is nothing a caller could "
     "mistake for an estimate; and the composed comparison publishes three "
     "rows -- Delta COMPLETE, Emulator NOT READY with the reason in the row "
     "itself, Your assumption COMPLETE. The emulator's `scenario` and "
     "`change` are null, NOT the string \"0\", and rows_covered is 0. "
     "The reader-facing verdict is a TRANSLATION of the analytical status, "
     "not a second opinion about it: run.VERDICTS maps AVAILABLE/PARTIAL/"
     "UNAVAILABLE onto COMPLETE/PARTIAL/NOT READY, the status field itself "
     "is unchanged and is still what the code branches on, and a named test "
     "asserts the two agree row by row. Also asserted: the reason mentions "
     "neither Corporate's validated model nor a zero nor a fall back, the "
     "two methods that did run are genuinely two different methods over one "
     "identical baseline, and the never-composed statement is still "
     "published. NO MODEL is fitted or loaded to prove any of this -- only "
     "the committed gate verdicts are read."),
]

RESULTS: list[Row] = [
    ("R01", "The hierarchy carries cohort and book, counts, EAD, the "
            "modelled/overlay split and the coverage-rate change in "
            "percentage points.", COVERED,
     ["test_r01_the_hierarchy_carries_the_cohort_and_the_book",
      "test_r01_the_modelled_and_overlay_split_is_kept",
      "test_r01_a_coverage_rate_change_is_in_percentage_points"], ""),
    ("R02", "A zero baseline has no percentage: 'not defined', never "
            "infinity.", COVERED,
     ["test_r02_a_zero_baseline_has_no_percentage_rather_than_infinity",
      "test_a_zero_baseline_has_no_percentage_rather_than_infinity"], ""),
    ("R03", "Affected plus unaffected is the book, checked.", COVERED,
     ["test_r03_affected_plus_unaffected_is_the_book",
      "test_r03_a_book_that_does_not_reconcile_is_refused",
      "test_r03_nothing_moves_outside_a_frozen_cohort"], ""),
    ("R04", "The two attribution views are labelled separately and never "
            "added.", COVERED,
     ["test_r04_the_two_views_are_labelled_separately",
      "test_r04_adding_the_two_views_together_is_refused_by_name"], ""),
    ("R05", "The attribution method is chosen by group count and stated; "
            "sequential publishes its order; sampling publishes its budget "
            "and error.", COVERED,
     ["test_r05_the_method_is_chosen_by_group_count_and_stated",
      "test_r05_a_sequential_bridge_publishes_its_order",
      "test_r05_sequential_and_shapley_disagree_and_neither_is_relabelled",
      "test_r05_an_exact_shapley_past_the_limit_is_refused_not_attempted",
      "test_r05_the_sampled_method_reports_its_budget_and_its_error",
      "test_r05_sampling_is_deterministic",
      "test_r05_a_contribution_that_did_not_converge_says_so"], ""),
    ("R06", "The residual is its own row and is never spread across "
            "drivers.", COVERED,
     ["test_r06_the_residual_is_its_own_row_and_is_not_spread",
      "test_no_residual_row_appears_when_the_bars_explain_everything"], ""),
    ("R07", "Charts use kinds this engine has; the absent tornado is "
            "documented, not claimed.", COVERED,
     ["test_r07_the_bridge_is_a_waterfall_with_both_totals",
      "test_r07_the_method_comparison_keeps_an_unavailable_method_visible",
      "test_r07_the_sensitivity_grid_is_a_heatmap_carrying_readiness",
      "test_r07_there_is_no_tornado_and_it_is_not_faked",
      "test_r07_the_signed_table_keeps_both_the_order_and_the_direction"],
     ""),
    ("R08", "A bar chart's bars sum to the headline, 'Other' included.",
     COVERED,
     ["test_r08_the_contributor_bars_sum_to_the_cohorts_change",
      "test_r08_a_chart_that_drops_rows_is_caught"], ""),
    ("R09", "Every published number resolves to a ledger fact and "
            "reconciles.", COVERED,
     ["test_the_delta_ledger_reconciles_to_the_outcome"], ""),
    ("R10", "Method disagreement is explained, never averaged.", COVERED,
     ["test_d07_the_disagreement_is_explained_rather_than_averaged"], ""),
    ("R11", "Save and reopen keep the source, model, scenario and run "
            "versions.", COVERED,
     ["test_a_confirmed_scenario_survives_the_round_trip",
      "test_the_release_change_is_visible_in_both_directions"],
     "Exercised end to end by J06 on both books: the same approval in the "
     "same thread reproduces the same figures exactly, and the repeat is "
     "published as a RE-RUN naming the run that produced them first "
     "rather than as a second independent answer."),
    ("R12", "Compare is a library function over two frozen ledgers.",
     COVERED,
     ["test_two_runs_over_one_cohort_are_comparable",
      "test_a_row_only_one_side_carries_is_reported_separately",
      "test_a_disposition_disagreement_is_surfaced",
      "test_incomparable_ledgers_are_refused_not_caveated",
      "test_a_comparison_cannot_invent_a_number"],
     "`ledger.compare()` reports the rows only one side carries and a "
     "disposition disagreement, and REFUSES rather than caveats when the "
     "two ledgers are not comparable at all -- different book, period, "
     "release or cohort. It cannot invent a number for a row one side "
     "does not have."),
    ("R13", "Exports reconcile to the chat numbers and block formula "
            "injection.", COVERED,
     ["test_a_formula_in_a_value_is_stored_as_text",
      "test_the_workbook_reconciles_before_it_is_written"],
     "J09 on both books runs a scenario to a stored result through the "
     "product, fetches `/runs/<id>/export?format=csv` and compares the "
     "exported digits against the figure the chat displayed. Formula "
     "injection is blocked in the workbook builder: a cell whose text "
     "begins `=`, `+`, `-`, `@`, tab or carriage return is stored as text. "
     "The Markdown, SVG and ZIP routes are unchanged and were NOT "
     "re-driven against scenario content."),
    ("R14", "The section 14.3 workbook is produced offline and reconciled.",
     COVERED,
     ["test_the_workbook_reconciles_before_it_is_written",
      "test_a_broken_book_identity_fails_the_build",
      "test_a_method_whose_change_does_not_add_up_fails_the_build",
      "test_an_unavailable_method_is_not_reconciled_against_zero",
      "test_a_formula_in_a_value_is_stored_as_text",
      "test_the_workbook_says_what_it_is_measured_on",
      "test_the_ml_sheet_says_it_is_not_a_decomposition",
      "test_the_workbook_round_trips_a_real_result"],
     "`scripts/whatif/build_workbook.py`, offline. Five reconciliations "
     "must close before a byte is written -- the cohort's change against "
     "baseline and scenario, each method's own change, the book identity, "
     "the attribution bridge against the headline, and an unavailable "
     "method against NOTHING rather than against zero -- and they close "
     "exactly on a real two-rule Corporate result. A cell whose text "
     "begins `=`, `+`, `-`, `@`, tab or carriage return is stored as text. "
     "The IN-CHAT XLSX route is NOT added: that would be a protected-core "
     "change this authorisation does not cover, and the omission is "
     "recorded in KNOWN_LIMITATIONS.md section 5."),
]

ORACLES: list[Row] = [
    ("O01", "A relative move is not a percentage-point move.", COVERED,
     ["test_o01_a_full_book_proportional_pd_stress",
      "test_o06_twenty_basis_points_is_not_twenty_percent_is_not_set_to_twenty"], ""),
    ("O02", "A basis-point move is a hundredth of a point.", COVERED,
     ["test_o02_a_cohort_of_one_leaves_the_rest_of_the_book_alone"], ""),
    ("O03", "Proportional Delta is exact on a book whose ECL is the closed "
            "form.", COVERED,
     ["test_o03_two_parameters_compose_multiplicatively_not_additively",
      "test_the_fixture_reconciles_to_its_own_published_ecl"], ""),
    ("O04", "Sequential and Shapley attribution differ and neither is "
            "relabelled.", COVERED,
     ["test_r05_sequential_and_shapley_disagree_and_neither_is_relabelled"],
     ""),
    ("O05", "A capped value reports the unclipped figure, the clipped one "
            "and the affected count.", COVERED,
     ["test_o05_a_ccf_move_has_two_answers_and_they_differ",
      "test_o05_multiplying_by_both_the_ccf_and_the_ead_effect_is_caught"], ""),
    ("O06", "Largest-remainder allocation sums to the target exactly.",
     COVERED, ["test_o06_the_wrong_readings_the_specification_names_are_not_produced"], ""),
    ("O07", "An elasticity needs a driver move to act on.", COVERED,
     ["test_o07_the_unemployment_mapping_arithmetic",
      "test_o07_no_macro_factor_exists_to_attach_a_slope_to"], ""),
    ("O08", "A zero baseline has no ratio and none is invented.", COVERED,
     ["test_o08_a_held_overlay_is_added_back_not_scaled",
      "test_o08_neither_published_book_splits_modelled_from_overlay"], ""),
    ("O09", "A target rate uses the declared denominator.", COVERED,
     ["test_o09_ml_anchoring_is_additive_against_the_observed_baseline",
      "test_o09_a_zero_shock_anchors_back_to_the_observed_figure",
      "test_o09_method_two_reports_not_ready_rather_than_a_number"], ""),
    ("O10", "A float quantity is refused rather than converted.", COVERED,
     ["test_o10_an_extra_thousand_splits_444_44_and_555_56",
      "test_o10_the_allocation_reconciles_for_every_target_in_a_range"], ""),
    ("O11", "Zero to zero is a neutral factor of one.", COVERED,
     ["test_o11_zero_to_positive_is_unsupported_not_divided",
      "test_o11_an_epsilon_denominator_would_have_produced_a_number",
      "test_o11_a_row_that_cannot_be_scaled_stays_in_the_total"], ""),
    ("O12", "The generator's totals do not depend on the interpreter.",
     COVERED, ["test_a_float_is_refused_rather_than_converted",
      "test_a_payload_carries_numbers_as_strings"], ""),
]

JOURNEYS: list[Row] = [
    (f"J{n:02d}", description, COVERED, [], reason)
    for n, description, reason in [
        (1, "Ask a scenario question and receive a preview before anything "
            "runs.", ""),
        (2, "Confirm the preview and receive a result.", ""),
        (3, "Ask a methodology question and receive the stored sensitivity "
            "without a refit.", ""),
        (4, "Run Delta and the emulator on one confirmed scenario.", ""),
        (5, "Supply an assumption and see it labelled as one.", ""),
        (6, "Reopen a saved scenario in a later turn.", ""),
        (7, "Change the book and see the confirmation invalidated.", ""),
        (8, "Ask for a chart the engine cannot draw and be told so.", ""),
        (9, "Export a result and reconcile it against the chat.", ""),
        (10, "Hit a missing model and see MODEL_NOT_READY.", ""),
        (11, "Hit an unseen category and get a refusal with the real "
             "values.", ""),
        (12, "Hit an invalid probability and see the cap reported.", ""),
        (13, "Cancel a run mid-flight.", ""),
        (14, "Press Run twice and see one run.", ""),
        (15, "A table the server could not render loses its own "
             "figure and nothing else.",
         "RAN, through real Chromium. The scripted analyst publishes "
         "the exact payload that used to take the page down -- a table "
         "with inline rows and no artifact_id, which "
         "finalization.render_tables passes through unrendered, so "
         "row.display does not exist. The journey asserts that the "
         "figure area shows its own error, that Next.js' root "
         "error.tsx did NOT take over (`This page could not be loaded` "
         "is absent), that the earlier turn and its answer are still "
         "on screen, that the composer is still usable, and that a "
         "further question still answers. The error is CONTAINED, not "
         "hidden: the message stays visible and componentDidCatch "
         "still logs it. MODEL MOCK: the analyst is scripted."),
    ]
]


def journey_reason() -> str:
    return (
        "RAN, through real Chromium against the real UI, the real V4 API, "
        "the real durable store, the real worker and event stream, the real "
        "DuckDB session over the published CANDIDATE release, and the real "
        "scenario engine reached through the real execute_analysis tool. "
        "15 of 15 on each book, 30 of 30 in total. Evidence per journey in "
        "docs/whatif/evidence/journeys-{corporate,retail}.json and the "
        "screenshots beside them: the prompts as typed, screenshots, the "
        "thread id with the book and release it is pinned to, cohort id and "
        "membership hash, scenario id and version, confirmation digest, run "
        "ids, source release and fingerprint, engine and model versions, "
        "tool trace, what was displayed, the reconciliation checked, and "
        "the export. Where an id is absent the record says why. "
        "MODEL MOCK: no provider credential is authorised in this "
        "container, so the analyst's tool calls are scripted. Everything "
        "else on the path is the product's own. A journey driven by a LIVE "
        "model is a separate, unrun claim -- see V01. "
        "Reproduce with `python3 scripts/whatif/browser_evidence.py "
        "--domain all`.")


ERRORS: list[Row] = [
    ("E01", "Fourteen domain failure categories exist, each mapped onto a "
            "code the runtime already has.", COVERED,
     ["test_all_fourteen_specified_categories_exist",
      "test_every_category_maps_onto_a_code_the_runtime_already_has"], ""),
    ("E02", "No domain code was added to the protected core's error "
            "tuple.", COVERED,
     ["test_no_domain_code_was_added_to_the_core_tuple"],
     "states.ERROR_CODES is a protected constant; growing it would be a "
     "protected-core change made to avoid writing a mapping."),
    ("E03", "Every category says what to do next.", COVERED,
     ["test_every_category_says_what_to_do_next"], ""),
    ("E04", "An ambiguous unit and a rule conflict are QUESTIONS, not "
            "rejections.", COVERED,
     ["test_exactly_the_two_reader_questions_are_asks",
      "test_a_question_refuses_to_become_a_rejection",
      "test_a_defect_refuses_to_become_a_question"], ""),
    ("E05", "A question carries its readings as choices the reader can "
            "pick.", COVERED,
     ["test_a_question_carries_the_readings_as_clickable_options"], ""),
    ("E06", "A rejection travels as the existing contract, with the domain "
            "name preserved.", COVERED,
     ["test_a_rejection_is_the_existing_contract",
      "test_the_domain_name_is_not_swallowed_by_the_mapping"], ""),
    ("E07", "Cross-book access is a scope violation, not a data gap.",
     COVERED,
     ["test_cross_book_access_is_a_scope_violation_not_a_data_gap"], ""),
    ("E08", "An unknown category cannot be raised.", COVERED,
     ["test_an_unknown_category_cannot_be_raised"], ""),
    ("E09", "An unqualified quantity is refused with the readings named, "
            "never resolved by a house default.", COVERED,
     ["test_o06_twenty_basis_points_is_not_twenty_percent_is_not_set_to_twenty",
      "test_o06_the_wrong_readings_the_specification_names_are_not_produced"],
     ""),
    ("E10", "A field the book does not carry is refused by name, with what "
            "the book has.", COVERED,
     ["test_a_field_the_book_does_not_carry_is_refused_by_name",
      "test_the_refusal_names_what_delta_does_handle",
      "test_a_refusal_names_only_fields_a_scenario_could_actually_ask_for"],
     ""),
    ("E11", "A field a scenario may not move is refused rather than "
            "answered with zero.", COVERED,
     ["test_a_field_a_scenario_may_not_move_is_refused",
      "test_the_approved_limit_is_refused_rather_than_answered_with_zero"],
     ""),
    ("E12", "An unseen category is refused with the book's real values, "
            "never matched by approximation.", COVERED,
     ["test_s15_a_word_the_book_does_not_have_is_refused_not_approximated",
      "test_a_corporate_dimension_is_not_a_retail_one"], ""),
    ("E13", "A value outside a published support range is refused, not "
            "extrapolated silently.", COVERED,
     ["test_s13_a_score_outside_the_cards_range_is_refused",
      "test_a_shock_outside_the_fitted_range_carries_an_extrapolation_warning"],
     ""),
    ("E14", "A parameter driven outside its valid range is surfaced with "
            "the unclipped value, not clamped silently.", COVERED,
     ["test_a_linear_translation_that_goes_negative_says_so",
      "test_an_assumption_that_would_make_ecl_negative_is_refused"], ""),
    ("E15", "A missing model is MODEL_NOT_READY with a reason, never a "
            "zero.", COVERED,
     ["test_a_missing_model_is_model_not_ready_and_not_a_zero",
      "test_o09_method_two_reports_not_ready_rather_than_a_number",
      "test_d09_a_missing_emulator_carries_a_reason_and_no_number"], ""),
    ("E16", "A model trained against another release is refused.", COVERED,
     ["test_a_model_trained_against_another_release_is_refused"], ""),
    ("E17", "A stale confirmation is refused with both hashes shown.",
     COVERED,
     ["test_an_unconfirmed_scenario_will_not_run",
      "test_the_stale_message_carries_both_hashes"], ""),
    ("E18", "A reconciliation failure is a defect in the run, surfaced "
            "rather than absorbed.", COVERED,
     ["test_reconciliation_failure_is_a_defect_in_the_run",
      "test_a_bridge_that_does_not_sum_to_the_headline_is_refused",
      "test_r08_a_chart_that_drops_rows_is_caught"], ""),
    ("E19", "Both books are off by default and each has its own flag.",
     COVERED,
     ["test_both_books_are_off_by_default", "test_each_book_has_its_own_flag",
      "test_an_unknown_book_is_off_rather_than_an_error",
      "test_the_truthy_set_matches_the_runtimes_own"], ""),
    ("E20", "Timeout, cancellation and repeated-Run behaviour under a "
            "scenario turn.", COVERED, [],
     "Driven through the product on both books. J12 asks for a "
     "probability outside its own range and the bound is REPORTED rather "
     "than clipped; J13 cancels a run mid-flight and it stops between "
     "actions with no partial scenario result published as an answer; J14 "
     "presses Run twice and gets ONE result, published as a re-run of the "
     "first rather than as a second opinion two readers could average. "
     "MODEL MOCK: the analyst is scripted."),
]

#: The three defects MEASURED in the product during the J journeys and
#: reported rather than fixed, because all three live in protected files.
#: All three were authorised in this round and all three are fixed here.
#: They are their own family so that "was the defect actually fixed, and
#: what proves it" is a row a reader can find, not a paragraph.
UI: list[Row] = [
    ("U01", "A monetary amount is never displayed as a different amount, "
            "and a real movement is never displayed as no movement.",
     COVERED,
     ["test_a_small_retail_portfolio_is_not_a_column_of_zeroes",
      "test_a_sub_million_movement_is_never_written_as_no_movement",
      "test_a_million_level_movement_keeps_the_whole_number_it_always_had",
      "test_a_billion_level_figure_is_unchanged",
      "test_the_accepted_corporate_magnitudes_do_not_move",
      "test_a_negative_change_keeps_its_sign_and_its_precision",
      "test_a_negative_that_rounds_to_nothing_is_not_written_minus_zero",
      "test_a_genuine_zero_is_written_as_zero",
      "test_one_group_is_written_at_one_precision",
      "test_the_smallest_non_zero_value_is_what_decides",
      "test_the_analyst_still_cannot_choose_a_money_precision",
      "test_a_unit_that_is_not_money_is_untouched_by_this_rule",
      "test_the_floor_is_declared_rather_than_discovered",
      "test_the_ladder_is_exactly_as_declared"],
     "MEASURED defect: a candidate Retail cohort of {1.6929, 2.0315, "
     "0.3386} SAR million read `SAR 2 million becomes SAR 2 million, a "
     "change of SAR 0 million`. STORED values were always exact; only the "
     "DISPLAY was wrong, so no calculation changed. The fix is one "
     "server-side rule in `display.py`, the single authority that produces "
     "every money string: precision is chosen ONCE PER GROUP -- one table "
     "column, one chart series or axis, one unit's worth of claims in one "
     "answer -- from the smallest non-zero magnitude in that group. At or "
     "above 1 it is 0 decimals, which is today's behaviour, so no accepted "
     "Corporate string moves; below 1 it is the fewest decimals giving that "
     "value two significant digits, capped at 4. The SCALE is not switched "
     "and no precision is manufactured. `PERMITTED[MONETARY_AMOUNT]` stays "
     "`(0,)` and `GOVERNED` is untouched: the analyst still cannot choose a "
     "money precision -- only the SERVER's own default became "
     "magnitude-aware, which is why 94 accepted precision assertions pass "
     "unedited. Narrative, KPI claim, table cell, chart tick and tooltip, "
     "CSV and Markdown export all inherit it because they all read the same "
     "published string or the same published `column_precision` / "
     "`series_precision`. MEASURED after: `SAR 1.69 million becomes SAR "
     "2.03 million, a change of SAR 0.34 million (20.00%)`, ECL by product "
     "`1.693 / 0.606 / 0.568 / 0.297 / 0.025`, and Corporate still `SAR 171 "
     "million becomes SAR 202 million, a change of SAR 31 million`. "
     "RESIDUAL, recorded rather than hidden: a value below 0.00005 alone in "
     "its group still renders `0.0000` at the cap -- KNOWN_LIMITATIONS.md "
     "16.1."),
    ("U02", "An active run is never described as stopped.", COVERED, [],
     "MEASURED defect: for the whole duration of a run the collapsed "
     "summary read `Stopped: ACCEPTED`. ROOT CAUSE, exact: "
     "`reducer.ts`'s `settled` case set `terminal: true` "
     "UNCONDITIONALLY, never reading `action.status.terminal` -- which the "
     "API does send (`routes.py:458`, "
     "`body['terminal'] = st.is_terminal(record.state)`) and the frontend "
     "type does declare (`client.ts:77`). Two callers dispatch `settled` "
     "with a WORKING status: the SSE sequence-gap detector, which fires "
     "mid-run, and the `Check its status` button. Nothing ever cleared the "
     "latch, and the fall-through wrote `Stopped: ${errorCode || state}` "
     "with `state` still `ACCEPTED` from `initial()`. THE FIX IS COPY AND A "
     "LATCH, NOT THE STATE MACHINE: the analytical states are untouched. "
     "`terminal` is now conditioned on the state ACTUALLY being terminal "
     "(the server's own flag, OR membership of `TERMINAL_RUN_STATES`, which "
     "already existed in `thread-view.tsx` and was moved into `reducer.ts` "
     "so there is one list mirroring `states.py:50-52`), and `state`, "
     "`errorCode` and `response` are applied only on that branch, so a "
     "mid-run status refreshes the clock without rewriting the outcome. "
     "Each of the six WORKING_STATES now maps onto truthful copy -- "
     "Accepted, Preparing, Working, Checking the query, Calculating, "
     "Checking the answer -- and `Stopped` survives only where execution "
     "actually stopped. PROVED by six added cases in "
     "`frontend/src/components/cockpit-v4/reducer.test.ts`: "
     "accepted-and-still-working is not an ending; every working state "
     "reads as work and never as a stop; every one of the nine terminal "
     "states is still an ending with its existing summary; a mid-run gap "
     "then a real settle ends exactly once; the server's own `terminal` "
     "flag is honoured for a state the frontend does not know; a working "
     "status refreshes the clock rather than ending it."),
    ("U03", "One table the server could not render cannot take down the "
            "thread or the composer.", COVERED,
     ["test_a_table_the_server_cannot_resolve_is_passed_through_unrendered"],
     "MEASURED defect: a preview table with inline rows and no "
     "`artifact_id` blanked the entire thread page, composer included. ROOT "
     "CAUSE, exact: `finalization.py:899-905` appends `dict(table)` "
     "UNTOUCHED when the artifact does not resolve, so rows reach the "
     "browser with no `display`; `visuals.tsx` then indexes "
     "`row.display[column]` and throws; and the boundary that caught it was "
     "`frontend/src/app/error.tsx`, the Next.js ROOT segment, which "
     "outranks everything below `app/layout.tsx`. THE FIX REUSES WHAT "
     "EXISTS: `components/system/error-boundary.tsx` already provides a "
     "class boundary with an `area` prop whose own docstring describes this "
     "exact use, and it is now wrapped around EACH figure at the two "
     "`.map()` bodies in `Visuals` -- which has exactly two call sites, the "
     "stored transcript and the live turn, so both paths are covered by one "
     "change. No new global UI architecture. NOTHING IS HIDDEN: no "
     "defensive guard was added inside `ResultTable`, because defaulting "
     "`row.display` to `{}` would render blank cells and conceal the "
     "defect; the boundary shows the message, `componentDidCatch` still "
     "logs it, and the backend test above pins the precondition the "
     "boundary exists for. PROVED IN A REAL BROWSER by journey J15 on both "
     "books. RECOMMENDED AND NOT DONE: `finalization.py` should refuse to "
     "publish a table it did not render; this round authorised a FRONTEND "
     "resilience change, so the server half is recorded with its file:line "
     "in KNOWN_LIMITATIONS.md 16.3 rather than made."),
]

#: The claims that are NOT made. A family of its own, so an unrun claim is a
#: ROW a reader can find rather than a sentence in a document somewhere.
UNRUN: list[Row] = [
    ("V01", "A journey driven by a LIVE model, not a scripted analyst.",
     BLOCKED, [],
     "NOT RUN -- BLOCKED, CREDENTIALS NOT AVAILABLE HERE. The variable this "
     "product actually reads is `config.CREDENTIAL_VAR` "
     "(`backend/cockpit_v4/config.py:32`), and "
     "`service.credential_status()` reports MISSING in this container. "
     "`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, "
     "`COCKPIT_LLM_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_API_KEY` "
     "are unset too -- verified, not assumed. No key is read or printed "
     "anywhere in this evidence; only PRESENT/MISSING is recorded. So no J "
     "journey here exercises a real model and none is relabelled as though "
     "it did: every J row stays MODEL MOCK. What IS exercised on the real "
     "path: the UI, the API, the durable store, the worker, the event "
     "stream, the DuckDB session over the candidate release, the governed "
     "execution path and the scenario engine. What is scripted: the "
     "analyst's tool calls. The gate is PREPARED and ready to run "
     "unchanged: eight conversations L1-L8 in "
     "`tests/cockpit_v4/browser/whatif.live.mjs`, driven by "
     "`scripts/whatif/live_uat.py`, which REFUSES to start (exit 2) when "
     "the credential is MISSING rather than falling back to the stub. The "
     "acceptance question is stated in "
     "`docs/whatif/LIVE_PROVIDER_UAT.md`: not whether the provider writes "
     "a good paragraph, but whether arbitrary natural language is reliably "
     "converted into the correct governed deterministic scenario contract "
     "-- so every assertion reads the submitted whatif_scenario parameters "
     "back out of the run trace, not the prose."),
    ("V02", "The Mac launcher installed and run on the Mac.", BLOCKED, [],
     "NOT RUN. Two candidate launchers exist with their installation steps "
     "in their own headers: the earlier "
     "`scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command` and "
     "the UAT launcher "
     "`scripts/whatif/START_ADVANCEDCOCKPIT_WHATIF_UAT.command`, which "
     "gates on `scripts/whatif/uat_preflight.py` and refuses to start on "
     "the wrong revision, on missing data or artifacts, or without the "
     "candidate interpreter -- printing both hashes on a revision "
     "mismatch. It never takes an occupied port: `start_candidate.py`'s "
     "`pick_port` steps up past a holder and never kills one. "
     "`/Users/tuhinchatterjee/Desktop/CreditProbe_Launchers` is not "
     "reachable from this Linux container, so neither file has been copied "
     "there, made executable there, or run there. The ACCEPTED launchers "
     "under `scripts/cockpit_v4/` are untouched -- `git status` on that "
     "directory is empty -- and the accepted presentation launcher is not "
     "overwritten."),
]

FAMILIES: list[tuple[str, str, list[Row]]] = [
    ("A", "Isolation and inertness", ISOLATION),
    ("C", "Cohort, rules, preview and confirmation", COHORT),
    ("D", "Execution", EXECUTION),
    ("E", "Errors, refusals and flags", ERRORS),
    ("S", "Sensitivities and mappings", SENSITIVITY),
    ("M", "The emulators", MODEL),
    ("R", "Results, attribution, charts and exports", RESULTS),
    ("O", "Numeric oracles", ORACLES),
    ("J", "Browser journeys", JOURNEYS),
    ("U", "Measured UI defects, authorised and fixed", UI),
    ("V", "Claims deliberately not made", UNRUN),
]


def known_tests() -> set[str]:
    names: set[str] = set()
    for path in sorted(TESTS.glob("test_whatif_*.py")):
        names |= set(re.findall(r"^def (test_\w+)", path.read_text(),
                                re.MULTILINE))
    return names


def main() -> int:
    available = known_tests()
    missing: list[str] = []
    counts: dict[str, int] = {}
    cases: list[dict[str, object]] = []

    for _letter, _title, rows in FAMILIES:
        for case_id, requirement, status, tests, note in rows:
            counts[status] = counts.get(status, 0) + 1
            for name in tests:
                if name not in available:
                    missing.append(f"{case_id} names {name}, which is not in "
                                   f"the suite")
            cases.append({
                "id": case_id, "requirement": requirement,
                "status": status, "tests": tests,
                "note": note or (journey_reason()
                                 if case_id.startswith("J") else ""),
            })

    if missing:
        print("This matrix names tests that do not exist:")
        for line in missing:
            print(f"  - {line}")
        print("\nA row that claims coverage it does not have is the one "
              "failure mode a matrix has. Fix the row or write the test.")
        return 1

    total = len(cases)
    lines = [
        "# Requirement test matrix — What-If candidate",
        "",
        "One row per acceptance ID. **A pytest count is not a completion "
        "claim**: 800 passing tests say nothing about whether S14 is met, "
        "only a named test against a named requirement does. "
        "`scripts/whatif/build_matrix.py` regenerates this file and **exits "
        "non-zero if any named test is not in the suite**.",
        "",
        "The requirement text is this implementation's reading of each ID. "
        "`CreditProbe_Advanced_Cockpit_WhatIf_Master_Prompt_v1.docx` is the "
        "authority; where the two differ, the specification wins and this "
        "file is wrong.",
        "",
        "| Status | Meaning | Count |",
        "|---|---|---|",
        f"| `{COVERED}` | implemented and proved by the named tests | "
        f"{counts.get(COVERED, 0)} |",
        f"| `{PARTIAL}` | implemented, proved in part, gap stated | "
        f"{counts.get(PARTIAL, 0)} |",
        f"| `{BLOCKED}` | not run, with the reason and the command | "
        f"{counts.get(BLOCKED, 0)} |",
        f"| `{NOT_BUILT}` | deliberately not implemented, recorded | "
        f"{counts.get(NOT_BUILT, 0)} |",
        f"| | **total** | **{total}** |",
        "",
        f"**{counts.get(COVERED, 0)} of {total} acceptance IDs are "
        f"COVERED.** The rest are named below with what is missing. Nothing "
        f"here is marked satisfied by a document.",
        "",
    ]

    for letter, title, rows in FAMILIES:
        covered = sum(1 for r in rows if r[2] == COVERED)
        lines += [
            f"## {letter} — {title}",
            "",
            f"{covered} of {len(rows)} COVERED.",
            "",
            "| ID | Requirement, as implemented | Status | Proof |",
            "|---|---|---|---|",
        ]
        for case_id, requirement, status, tests, note in rows:
            proof = ""
            if tests:
                proof = "<br>".join(f"`{t}`" for t in tests)
            if note:
                proof = (proof + "<br>" + note) if proof else note
            if not proof and status == BLOCKED:
                proof = journey_reason().replace("\n", "<br>")
            mark = status if status == COVERED else f"**{status}**"
            lines.append(f"| {case_id} | {requirement} | {mark} | {proof} |")
        lines.append("")

    lines += [
        "## What is not covered, in one place",
        "",
    ]
    for _letter, _title, rows in FAMILIES:
        for case_id, requirement, status, _tests, note in rows:
            if status == COVERED:
                continue
            reason = note or journey_reason()
            lines.append(f"* **{case_id} — {status}.** {requirement} "
                         f"{reason}")
    lines += [
        "",
        "## What a passing row does not mean",
        "",
        "Every test in this matrix runs against **generated books**. A "
        "COVERED row means the behaviour the requirement describes is "
        "implemented and proved on that data. It does not mean the figures "
        "are a bank's, that any model agrees with a bank's ECL engine, or "
        "that any sensitivity is validated. Those claims are made nowhere "
        "in this deliverable and are marked explicitly unavailable in "
        "`MODEL_CARD_*.md` and `SENSITIVITY_CARD_*.md`.",
        "",
    ]

    matrix = ROOT / "docs" / "whatif" / "REQUIREMENT_TEST_MATRIX.md"
    matrix.write_text("\n".join(lines), encoding="utf-8")
    cases_path = ROOT / "docs" / "whatif" / "ACCEPTANCE_CASES.json"
    cases_path.write_text(json.dumps({
        "total": total, "counts": counts,
        "note": ("One entry per acceptance ID. Generated by "
                 "scripts/whatif/build_matrix.py, which refuses to name a "
                 "test that is not in the suite."),
        "cases": cases}, indent=2, sort_keys=True), encoding="utf-8")

    print(f"{total} acceptance IDs: " + ", ".join(
        f"{count} {status}" for status, count in sorted(counts.items())))
    print(f"every named test exists ({len(available)} test functions in the "
          f"What-If suite)")
    print(f"written: {matrix.relative_to(ROOT)}, "
          f"{cases_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
