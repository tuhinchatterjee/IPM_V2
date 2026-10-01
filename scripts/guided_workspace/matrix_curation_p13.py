#!/usr/bin/env python3
"""One-off, reviewed curation of the requirement evidence map at P13.

Kept in the repository so the change from the draft is auditable: every row
this round closed or re-graded, with the test, journey or regression check
that now carries it. Run once; the generator then verifies every citation.
"""

import json
from pathlib import Path

P = Path("docs/guided_workspace/matrix/requirement_evidence.json")
E = json.loads(P.read_text(encoding="utf-8"))
R = "tests/cockpit_v4/test_gw_runs.py::"
G = "tests/cockpit_v4/test_gw_grid.py::"
T = "tests/cockpit_v4/test_gw_macro_tornado.py::"


def put(rid, claim, tests=None, journeys=None, gap="", add=False, checks=None):
    e = E[rid]
    e["claim"] = claim
    if tests is not None:
        e["tests"] = (e["tests"] if add else []) + tests
    if journeys is not None:
        e["journeys"] = (e["journeys"] if add else []) + journeys
    if checks is not None:
        e["checks"] = checks
    e["gap"] = gap


put("GRID07", "COVERED", [G + "test_grid07_every_visible_column_declares_a_filter_the_ui_can_edit"], ["GW-P13-01"])
put("GRID11", "COVERED", [G + "test_grid11_boolean_and_null_filters_partition_the_book", G + "test_grid11_through_http"], ["GW-P13-02"])
put("GRID13", "COVERED", [G + "test_grid13_server_sort_is_deterministic_across_pages", G + "test_grid13_an_unknown_sort_column_falls_back_and_says_so"], ["GW-P13-02"])
put("GRID14", "COVERED", [G + "test_paging_is_server_side_and_capped", "tests/cockpit_v4/test_gw_charts.py::test_http_aggregate_is_small_and_row_free"], ["GW-P11-01", "GW-P13-02"])
put("GRID21", "COVERED", [G + "test_grid_export_carries_the_filter_definition", G + "test_cohort_export_carries_the_cohort_definition", G + "test_a_conversation_cohort_exports_exactly_its_members"])
put("MAC07", "COVERED", [T + n for n in ("test_bars_are_the_governed_translation_exactly", "test_rows_are_ranked_by_swing_and_capped", "test_pd_and_lgd_are_explicit_and_filterable", "test_signs_are_preserved_as_fitted", "test_collateral_sign_review_is_carried_not_corrected", "test_diagnostic_only_estimates_are_listed_not_drawn", "test_hover_fields_are_all_present", "test_the_accepted_chat_path_keeps_its_tornado_substitute")] + ["frontend/src/lib/viz/tornado.test.ts::TOR01..TOR04"], ["GW-P13-03"])
put("VIZ02", "COVERED", [], ["GW-P13-05"])
put("METH05", "COVERED", [R + "test_meth05_results_carry_the_governed_method_names", "frontend/src/lib/workspace/method-labels.test.ts::MLB01"], ["GW-P13-04"], add=True)
put("UAT-08", "COVERED", [R + "test_meth05_results_carry_the_governed_method_names", "frontend/src/lib/workspace/method-labels.test.ts::MLB01"], ["GW-P13-04"], add=True)
put("UAT-05", "PARTIAL", ["frontend/src/lib/viz/format.test.ts::FMT01/FMT02/FMT10", "frontend/src/lib/viz/figures.test.ts::FIG02"], [], gap="Governed surfaces (What-If, results, comparison, preview, Lenses, Early Warning, issues) now state the scale once per column via moneyCol and keep raw SAR million for the CSV. The protected Cockpit thread renderer (components/cockpit-v4) and the legacy flags-off pages keep their own formatting; changing them needs a protected-core decision.")
put("FMT01", "COVERED", ["frontend/src/lib/viz/format.test.ts::FMT01", "frontend/src/lib/viz/format.test.ts::FMT10"])
put("SCEN12", "COVERED", [R + "test_scen12_a_stage_retest_policy_persists_into_execution"], add=True)
put("DECOMP07", "COVERED", [R + "test_scen12_a_stage_retest_policy_persists_into_execution"], add=True, gap="")
put("DECOMP12", "BLOCKED", [R + "test_scen12_a_stage_retest_policy_persists_into_execution"], add=True, gap="BLOCKED by data: neither book publishes a SICR re-test rule or a lifetime ECL curve for re-staged exposures (scenario.mappings.stages). A re-test is carried into execution and the stage components are N/A with that reason; computing migrated EAD would require inventing the staging rule.")
put("DECOMP14", "COVERED", [R + "test_decomp14_a_single_customer_scenario_decomposes_customer_then_book"], add=True)
put("DECOMP21", "COVERED", [R + "test_decomp21_selected_scope_equal_to_the_book_is_one_population", R + "test_decomp21_a_true_subset_is_never_called_the_whole_book", "frontend/src/lib/viz/decomposition.test.ts::DEC10/DEC11"], ["GW-P13-04"], add=True)
put("DECOMP24", "COVERED", [R + "test_decomp24_method_comparison_keeps_a_dual_scope_bridge_per_method"], add=True, gap="")
put("DECOMP08", "COVERED", [R + "test_decomp08_rating_and_macro_contributions_are_measured"], add=True)
put("BASE05", "COVERED", [R + "test_base05_an_assumption_before_execution_amends_the_same_run"], add=True)
put("ARCH-02", "COVERED", [R + "test_arch02_cockpit_and_whatif_build_the_identical_contract"], add=True)
put("SEC08", "COVERED", ["tests/cockpit_v4/test_gw_v4_secret_persistence.py::" + n for n in ("test_no_secret_bytes_in_the_database_wal_or_shm", "test_no_secret_on_any_logical_read_path", "test_no_secret_in_any_export", "test_reopening_makes_zero_model_calls_and_restores_nothing", "test_the_model_still_receives_the_question_as_typed")], add=True)
put("M017", "BLOCKED", ["tests/cockpit_v4/test_gw_metrics.py::test_m017_corporate_is_computed_on_its_own_grain_and_period", "tests/cockpit_v4/test_gw_metrics.py::test_m017_retail_incompatibility_is_measured_not_assumed"], add=True, gap="Retail BLOCKED by the governed data: the Retail release publishes no CCF field and its EAD equals the balance on 6,702 of 6,702 accounts, so a Retail CCF would be 0 by construction. Corporate is computed; Retail is refused (no cross-book substitution); the pinning test fails the day Retail data could support it.")
put("METH16", "COVERED", [], checks=["mutation:method selection (no silent Delta)"], add=True)
put("ARCH01", "COVERED", [], checks=["regression:accepted_browser_suite_flags_off", "regression:v4_backend_and_frontend_py_accepted"], add=True)
put("ARCH-03", "COVERED", [], checks=["regression:accepted_browser_suite_flags_off", "regression:protected_baseline_round"], add=True)
put("ARCH05", "BLOCKED", [], checks=["regression:release_fingerprints", "regression:release_report_digests"], add=True, gap="ENVIRONMENT: the accepted books reproduce their in-container P0 fingerprints and content digests (verified by lake.verify), but the earlier container's recorded byte fingerprints cannot be reproduced with the pinned pandas/pyarrow writer (BASELINE_PROVENANCE section 3); test_the_accepted_releases_are_byte_identical stays an env-bound failure. Nothing in this round writes to a published release.")
put("ARCH06", "COVERED", [], checks=["git:no_tags_moved"])
for rid, step in (("REG01", "whatif_suite_whatif_venv"), ("REG02", "v4_backend_and_frontend_py_accepted"), ("REG03", "v3_cockpit_agentic"), ("REG04", "frontend_unit"), ("REG07", "accepted_browser_suite_flags_off"), ("REG10", "protected_baseline_round")):
    put(rid, "COVERED", [], checks=[f"regression:{step}"] + (["regression:frontend_typecheck", "regression:frontend_lint_new_code"] if rid == "REG04" else []))
put("REG05", "COVERED", [], checks=["regression:gw_browser_journeys_clean_store", "regression:whatif_candidate_browser"])
put("REG06", "COVERED", [], checks=["regression:gw_browser_journeys_clean_store", "regression:whatif_candidate_browser"])
put("REG08", "COVERED", [], checks=["regression:sensitivity_libraries_reproduce", "regression:emulator_artifacts_reproduce"])
put("REG09", "BLOCKED", [], checks=["regression:release_fingerprints"], gap=E["ARCH05"]["gap"] if False else "ENVIRONMENT: in-container fingerprints verify; the earlier container's accepted byte fingerprints are not reproducible with the pinned writer (BASELINE_PROVENANCE section 3).")
put("REG11", "COVERED", [], checks=["generator:self_check"])
for rid in ("REG12", "UAT-07") + tuple(f"LAUNCH{n:02d}" for n in range(1, 13)):
    E[rid]["claim"] = "PENDING-P14"
    E[rid]["gap"] = E[rid]["gap"] or "Needs the Mac: a real install with the approved Keychain credential and live provider (P14). The launcher is prepared and dry-run here; the live run is the user's acceptance gate."
P.write_text(json.dumps(E, indent=1, ensure_ascii=False), encoding="utf-8")
print("curated")
