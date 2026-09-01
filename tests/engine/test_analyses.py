"""
Tests for the ten certified analyses.

These check the properties that make a result defensible rather than merely
plausible: distributions that sum to the whole, matrices whose rows are
conditional probabilities, a bridge that reconciles exactly, and weighted
averages that are actually weighted. A wrong number that looks reasonable is the
failure mode these exist to catch.

The suite skips itself when the analytical lake has not been built.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.contracts import Certification
from backend.engine.helpers import FACILITY, RATING_ORDER, rating_sort_key
from backend.engine.registry import get_registry
from backend.engine.runner import run_analysis

CERTIFIED_IDS = [
    "portfolio_summary", "stage_distribution", "stage_migration", "dpd_migration",
    "rating_transition_matrix", "sector_concentration", "ecl_movement",
    "top_deteriorating_borrowers", "portfolio_trend", "stress_scenario_basic",
]


@pytest.fixture(scope="module", autouse=True)
def require_data():
    source = get_data_source()
    if FACILITY not in source.datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")


@pytest.fixture(scope="module")
def periods():
    return get_data_source().periods(FACILITY)


def ok(analysis_id, **kwargs):
    run = run_analysis(analysis_id, **kwargs)
    assert run.status == "succeeded", f"{analysis_id} failed: {run.error}"
    return run


# ================================================================== registry


def test_all_ten_certified_analyses_are_registered():
    registry = get_registry()
    for analysis_id in CERTIFIED_IDS:
        contract = registry.contract(analysis_id)
        assert contract.certification is Certification.CERTIFIED, analysis_id


def test_a_user_defined_example_exists_and_carries_no_tick():
    contract = get_registry().contract("high_utilisation_watchlist")
    assert contract.certification is Certification.USER_DEFINED
    assert contract.is_certified is False  # no blue tick
    assert contract.is_runnable is True


@pytest.mark.parametrize("analysis_id", CERTIFIED_IDS)
def test_every_contract_declares_what_engine_builder_needs(analysis_id):
    """Datasets, variables, methodology, outputs with units, and validation rules."""
    c = get_registry().contract(analysis_id)
    assert c.required_datasets, analysis_id
    assert c.required_fields, analysis_id
    assert len(c.calculation_description) > 80, f"{analysis_id} methodology is too thin"
    assert c.outputs, analysis_id
    assert c.validation_rules, analysis_id
    assert c.supported_visualizations, analysis_id
    assert c.owner and c.version


# ============================================================== every analysis


@pytest.mark.parametrize("analysis_id", CERTIFIED_IDS)
def test_every_analysis_runs_and_produces_a_trace(analysis_id):
    run = ok(analysis_id)
    assert run.result is not None
    assert run.result.input_row_count > 0
    # Trace: a request node, at least one governed dataset read, the engine
    # function, and a result.
    types = {n.type.value for n in run.graph.nodes.values()}
    assert {"PLAN", "DATASET", "VARIABLE", "FILTER", "ENGINE_FUNCTION", "RESULT"} <= types
    assert len(run.node_hashes) == len(run.graph.nodes)
    run.graph.topological_order()  # raises on a cycle


@pytest.mark.parametrize("analysis_id", CERTIFIED_IDS)
def test_results_are_json_serialisable(analysis_id):
    """The API returns these directly; a NaN would produce invalid JSON."""
    import json

    json.dumps(ok(analysis_id).to_dict())


@pytest.mark.parametrize("analysis_id", CERTIFIED_IDS)
def test_analyses_are_deterministic(analysis_id):
    """Same inputs, same numbers — the property the whole product rests on."""
    first = ok(analysis_id).result
    second = ok(analysis_id).result
    assert first.rows == second.rows
    assert first.values == second.values


# =========================================================== portfolio summary


def test_portfolio_summary_stages_reconcile_to_total():
    v = ok("portfolio_summary").result.values
    stage_total = v["stage1_ead"] + v["stage2_ead"] + v["stage3_ead"]
    assert stage_total == pytest.approx(v["total_ead"], abs=0.05)


def test_portfolio_summary_coverage_is_ecl_over_ead():
    v = ok("portfolio_summary").result.values
    assert v["ecl_coverage_pct"] == pytest.approx(v["total_ecl"] / v["total_ead"] * 100, abs=0.01)


def test_weighted_lgd_is_a_realistic_percentage():
    """Guards the scale bug this caught during development: the source stores LGD
    as a fraction, and reporting 0.39% instead of 39% would be badly wrong."""
    v = ok("portfolio_summary").result.values
    assert 5.0 < v["weighted_lgd_pct"] < 95.0


def test_portfolio_summary_reports_movement_against_the_prior_period():
    v = ok("portfolio_summary").result.values
    assert v["compare_period"] and v["compare_period"] != v["period"]
    assert "total_ead" in v["movement"]


# =========================================================== stage distribution


def test_stage_distribution_shares_sum_to_100():
    rows = ok("stage_distribution").result.rows
    assert sum(r["ead_pct"] for r in rows) == pytest.approx(100.0, abs=0.1)


def test_stage_distribution_covers_all_three_stages():
    rows = ok("stage_distribution").result.rows
    assert [r["ifrs9_stage"] for r in rows] == [1, 2, 3]


def test_stage_3_coverage_exceeds_stage_1():
    """A credit-risk sanity check: impaired exposure must be better provided for."""
    rows = {r["ifrs9_stage"]: r for r in ok("stage_distribution").result.rows}
    assert rows[3]["coverage_pct"] > rows[1]["coverage_pct"]


def test_stage_distribution_can_break_down_by_sector():
    v = ok("stage_distribution", params={"group_by": "sector"}).result.values
    assert v["breakdown"]
    assert all("sector" in row for row in v["breakdown"])


# =============================================================== migrations


def test_stage_migration_rows_are_conditional_probabilities(periods):
    run = ok("stage_migration", params={"from_period": periods[0], "to_period": periods[-1]})
    totals: dict[str, float] = {}
    for row in run.result.rows:
        totals[row["from"]] = totals.get(row["from"], 0.0) + row["row_pct"]
    for origin, total in totals.items():
        if total > 0:
            assert total == pytest.approx(100.0, abs=0.1), f"stage {origin} rows sum to {total}"


def test_stage_migration_reports_entries_and_exits(periods):
    """Facilities in only one period must be reported, not silently dropped."""
    v = ok("stage_migration", params={"from_period": periods[0], "to_period": periods[-1]}).result.values
    c = v["coverage"]
    assert c["matched"] + c["exits"] == c["opening_rows"]
    assert c["matched"] + c["entries"] == c["closing_rows"]


def test_stage_migration_branches_the_trace_for_two_periods(periods):
    run = ok("stage_migration", params={"from_period": periods[0], "to_period": periods[-1]})
    datasets = [n for n in run.graph.nodes.values() if n.type.value == "DATASET"]
    assert len(datasets) == 2, "opening and closing reads should be separate trace branches"
    joins = [n for n in run.graph.nodes.values() if n.type.value == "TRANSFORMATION"]
    assert joins, "the two branches must re-join at a recorded step"


def test_stage_migration_rejects_identical_periods(periods):
    run = run_analysis("stage_migration",
                       params={"from_period": periods[-1], "to_period": periods[-1]})
    assert run.status == "failed"
    assert "different" in (run.error or "")


def test_count_basis_returns_whole_facilities(periods):
    run = ok("stage_migration",
             params={"from_period": periods[-2], "to_period": periods[-1], "basis": "count"})
    assert all(float(r["value"]).is_integer() for r in run.result.rows)


def test_dpd_migration_uses_ordered_buckets(periods):
    v = ok("dpd_migration", params={"from_period": periods[0], "to_period": periods[-1]}).result.values
    assert v["buckets"] == ["Current", "1-29", "30-59", "60-89", "90-179", "180+"]
    assert 0 <= v["movement"]["cure_rate_pct"] <= 100


# ======================================================== rating transitions


def test_rating_scale_orders_notches_correctly():
    """AA+ must rank better than AA, and BBB- worse than BBB. Without the notches
    a one-notch downgrade would be scored as an upgrade."""
    assert rating_sort_key("AA+") < rating_sort_key("AA") < rating_sort_key("AA-")
    assert rating_sort_key("BBB+") < rating_sort_key("BBB") < rating_sort_key("BBB-")
    assert rating_sort_key("AAA") < rating_sort_key("D")
    assert rating_sort_key("NOT_A_RATING") == len(RATING_ORDER)


def test_rating_transition_rows_sum_to_100(periods):
    run = ok("rating_transition_matrix",
             params={"from_period": periods[0], "to_period": periods[-1]})
    totals: dict[str, float] = {}
    for row in run.result.rows:
        totals[row["from"]] = totals.get(row["from"], 0.0) + row["row_pct"]
    for grade, total in totals.items():
        if total > 0:
            assert total == pytest.approx(100.0, abs=0.1), f"grade {grade} sums to {total}"


def test_rating_grades_are_returned_in_credit_quality_order(periods):
    v = ok("rating_transition_matrix",
           params={"from_period": periods[0], "to_period": periods[-1]}).result.values
    grades = v["grades"]
    assert grades == sorted(grades, key=rating_sort_key)


def test_rating_transition_states_it_is_not_annualised(periods):
    """An un-annualised matrix presented as annual would misstate the risk."""
    v = ok("rating_transition_matrix",
           params={"from_period": periods[0], "to_period": periods[-1]}).result.values
    assert v["annualised"] is False
    assert v["interval"]


# ============================================================== ECL movement


def test_ecl_bridge_reconciles_exactly(periods):
    """Opening plus every component must equal closing. No residual term."""
    run = ok("ecl_movement", params={"from_period": periods[-2], "to_period": periods[-1]})
    v = run.result.values
    assert abs(v["reconciliation_difference"]) < 0.01
    movement = sum(r["value"] for r in run.result.rows if r["kind"] == "movement")
    assert v["opening_ecl"] + movement == pytest.approx(v["closing_ecl"], abs=0.01)


def test_ecl_bridge_opens_and_closes_with_totals(periods):
    rows = ok("ecl_movement", params={"from_period": periods[-2],
                                      "to_period": periods[-1]}).result.rows
    assert rows[0]["component"] == "Opening ECL"
    assert rows[-1]["component"] == "Closing ECL"


# ======================================================== sector concentration


def test_concentration_shares_sum_to_100_before_truncation():
    run = ok("sector_concentration", params={"top_n": 100})
    assert sum(r["ead_pct"] for r in run.result.rows) == pytest.approx(100.0, abs=0.1)


def test_hhi_is_in_range_and_computed_over_all_groups():
    v = ok("sector_concentration", params={"top_n": 3}).result.values
    assert 0 < v["hhi"] <= 10_000
    # Truncating the returned rows must not change the index.
    assert v["hhi"] == pytest.approx(ok("sector_concentration",
                                        params={"top_n": 100}).result.values["hhi"], abs=0.1)
    assert v["truncated_to"] == 3


def test_largest_obligor_share_never_exceeds_the_group():
    for row in ok("sector_concentration").result.rows:
        assert 0 <= row["largest_obligor_pct"] <= 100.01


# ============================================================ portfolio trend


def test_trend_covers_every_period_in_order(periods):
    run = ok("portfolio_trend")
    assert [r["period"] for r in run.result.rows] == periods


def test_trend_can_be_limited_to_recent_periods():
    rows = ok("portfolio_trend", params={"n_periods": 4}).result.rows
    assert len(rows) == 4


def test_trend_latest_period_matches_portfolio_summary():
    """Two analyses computing the same figure must agree, or one of them is wrong."""
    trend_last = ok("portfolio_trend").result.rows[-1]
    summary = ok("portfolio_summary").result.values
    assert trend_last["total_ead"] == pytest.approx(summary["total_ead"], abs=0.05)
    assert trend_last["total_ecl"] == pytest.approx(summary["total_ecl"], abs=0.05)


# ==================================================== deteriorating borrowers


def test_only_genuinely_deteriorated_borrowers_are_returned(periods):
    """Padding the list with stable borrowers would make the table untrue."""
    rows = ok("top_deteriorating_borrowers",
              params={"from_period": periods[0], "to_period": periods[-1], "top_n": 25}).result.rows
    for row in rows:
        assert (row["ecl_change"] > 0 or row["stage_change"] > 0
                or row["notch_change"] > 0 or row["dpd_change"] > 0), row["customer_id"]
        assert row["reasons"]


def test_deteriorating_borrowers_are_ranked_by_score(periods):
    rows = ok("top_deteriorating_borrowers",
              params={"from_period": periods[0], "to_period": periods[-1]}).result.rows
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_min_ead_filter_is_applied(periods):
    rows = ok("top_deteriorating_borrowers",
              params={"from_period": periods[0], "to_period": periods[-1],
                      "min_ead": 50.0, "top_n": 20}).result.rows
    assert all(r["ead"] >= 50.0 for r in rows)


# ===================================================================== stress


def test_stress_base_scenario_leaves_exposure_unchanged():
    run = ok("stress_scenario_basic", params={"scenario": "base"})
    ead = next(r for r in run.result.rows if r["metric"] == "Total EAD")
    assert ead["base"] == pytest.approx(ead["stressed"], abs=0.01)


def test_stress_increases_loss_and_severity_is_monotonic():
    increases = [
        ok("stress_scenario_basic", params={"scenario": s}).result.values["ecl_increase"]
        for s in ("mild", "moderate", "severe")
    ]
    assert increases == sorted(increases), "a more severe scenario must not lose less"
    assert all(x > 0 for x in increases)


def test_stress_base_ecl_equals_the_reported_ecl():
    """The comparison must be against what was actually booked, not a model
    re-derivation of it."""
    stressed = ok("stress_scenario_basic", params={"scenario": "base"}).result.values
    reported = ok("portfolio_summary").result.values
    assert stressed["base_ecl"] == pytest.approx(reported["total_ecl"], abs=0.01)


def test_stress_labels_itself_as_a_management_scenario():
    """Presenting a management scenario as a regulatory one would be an overclaim."""
    v = ok("stress_scenario_basic").result.values
    assert "not a regulatory" in v["basis"].lower()


def test_custom_stress_accepts_explicit_shocks():
    v = ok("stress_scenario_basic",
           params={"scenario": "custom", "pd_multiplier": 3.0, "lgd_uplift_pp": 15.0}).result.values
    assert v["shocks"]["pd_multiplier"] == 3.0
    assert v["ecl_increase"] > 0


def test_stress_can_target_one_sector():
    whole = ok("stress_scenario_basic", params={"scenario": "severe"}).result.values
    one = ok("stress_scenario_basic",
             params={"scenario": "severe", "sector": "Real Estate"}).result.values
    assert one["base_ecl"] < whole["base_ecl"]
    assert one["sector"] == "Real Estate"


# ================================================================== filtering


def test_filters_narrow_every_analysis():
    unfiltered = ok("portfolio_summary").result.values["total_ead"]
    filtered = ok("portfolio_summary", filters={"sector": "Real Estate"}).result.values["total_ead"]
    assert 0 < filtered < unfiltered


def test_filters_are_recorded_in_the_trace():
    run = ok("portfolio_summary", filters={"sector": "Contracting"})
    filter_nodes = [n for n in run.graph.nodes.values() if n.type.value == "FILTER"]
    assert any(n.config.get("filters") == {"sector": "Contracting"} for n in filter_nodes)


# ============================================ ECL change decomposition (P0.4)


def test_the_ecl_decomposition_is_certified_and_registered():
    contract = get_registry().contract("ecl_change_decomposition")
    assert contract.certification is Certification.CERTIFIED
    assert contract.limitations.strip()


def test_the_ecl_decomposition_reconciles_on_the_real_book(periods):
    """The whole claim of the method. A decomposition whose components do not
    sum to the movement is a table of plausible numbers."""
    run = ok("ecl_change_decomposition",
             params={"period": periods[-1], "compare_period": periods[0]})
    values = run.result.values
    assert values["reconciles"] is True
    assert values["attributed"] == pytest.approx(values["movement"], abs=0.01)
    assert values["closing_total"] - values["opening_total"] == pytest.approx(
        values["movement"], abs=0.01)


def test_the_ecl_decomposition_names_every_governed_driver(periods):
    from backend.orchestration import decomposition as dc

    run = ok("ecl_change_decomposition",
             params={"period": periods[-1], "compare_period": periods[0]})
    shown = {row["component"] for row in run.result.rows}
    assert shown == {dc.LABELS[key] for key in dc.COMPONENTS}


def test_the_ecl_decomposition_says_what_it_does_not_prove(periods):
    """An attribution read as causation is worse than no attribution, because
    it names a culprit."""
    run = ok("ecl_change_decomposition",
             params={"period": periods[-1], "compare_period": periods[0]})
    caveats = run.result.meta["does_not_prove"]
    assert any("does not establish cause" in c for c in caveats)


def test_the_ecl_decomposition_refuses_a_single_period(periods):
    """Two periods or nothing. Comparing a period with itself would report a
    movement of zero as though it had been measured."""
    run = run_analysis("ecl_change_decomposition",
                       params={"period": periods[-1],
                               "compare_period": periods[-1]})
    assert run.status != "succeeded"
    assert "two periods" in str(run.error).lower()
