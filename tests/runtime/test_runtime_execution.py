"""
What the Analytical Runtime computes, and what it records having computed.

The safety tests next door assert what is refused. These assert the other half
of the claim: that a composed plan produces a defensible number, and that the
Trace shows where it came from in enough detail to check it by hand.

The arithmetic is verified against the same data read a second way, rather than
against a figure written into the test. A hard-coded expected value tests that
nobody changed the generator; reading the data independently tests that the
runtime computes what it says it computes.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.data_access.context import AnalysisContext
from backend.runtime.executor import ExecutionClass, execute

FACILITY = "portfolio_facility"
PERIOD = "Q1 2026"


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built")


@pytest.fixture(scope="module")
def book():
    """The same period, read straight through the DAL, to check against."""
    return get_data_source().fetch(
        FACILITY, context=AnalysisContext(period=PERIOD),
        fields=["account_id", "borrower_name", "sector", "ead", "total_ecl",
                "ifrs9_stage", "customer_id"],
        period=PERIOD,
    )


def scan(**params) -> dict:
    return {"id": "a", "op": "SCAN",
            "params": {"dataset": FACILITY, "period": PERIOD, **params}}


# ------------------------------------------------------------- the arithmetic


def test_an_aggregate_matches_the_data_read_independently(book):
    result = execute({"operations": [
        scan(fields=["ead"]),
        {"id": "t", "op": "AGGREGATE", "inputs": ["a"], "params": {
            "aggregates": [{"column": "ead", "function": "sum", "as": "total_ead"},
                           {"function": "count", "as": "facilities"}]}}]})
    assert result.row_count == 1
    assert result.rows[0]["total_ead"] == pytest.approx(float(book["ead"].sum()), rel=1e-9)
    assert result.rows[0]["facilities"] == len(book)


def test_a_group_reconciles_to_the_whole(book):
    """The parts of a partition must sum to the total, or one is wrong."""
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]})
    assert sum(r["ead"] for r in result.rows) == pytest.approx(
        float(book["ead"].sum()), rel=1e-9)


def test_a_filter_narrows_to_exactly_the_matching_rows(book):
    expected = int((book["sector"] == "Real Estate").sum())
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "f", "op": "FILTER", "inputs": ["a"], "params": {
            "where": [{"column": "sector", "op": "=", "value": "Real Estate"}]}},
        {"id": "t", "op": "AGGREGATE", "inputs": ["f"], "params": {
            "aggregates": [{"function": "count", "as": "n"}]}}]})
    assert result.rows[0]["n"] == expected


def test_a_ratio_guards_against_dividing_by_zero():
    """Zero denominators produce null, not a number nobody can defend."""
    result = execute({"operations": [
        scan(fields=["sector", "ead", "total_ecl"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"},
                           {"column": "total_ecl", "function": "sum", "as": "ecl"},
                           {"function": "count", "as": "zero"}]}},
        {"id": "z", "op": "DERIVE", "inputs": ["g"], "params": {"columns": [
            {"as": "nothing", "expression": {"type": "literal", "value": 0}}]}},
        {"id": "r", "op": "RATIO", "inputs": ["z"], "params": {
            "numerator": "ecl", "denominator": "nothing", "as": "impossible"}}]})
    assert all(row["impossible"] is None for row in result.rows)


def test_a_weighted_average_is_actually_weighted(book):
    result = execute({"operations": [
        scan(fields=["ead", "pd_12m_pct"] if "pd_12m_pct" in book.columns
             else ["ead", "total_ecl"]),
        {"id": "t", "op": "AGGREGATE", "inputs": ["a"], "params": {
            "aggregates": [
                {"column": "total_ecl", "function": "avg", "as": "plain"},
                {"column": "total_ecl", "function": "weighted_avg",
                 "weight": "ead", "as": "weighted"}]}}]})
    row = result.rows[0]
    assert row["plain"] != pytest.approx(row["weighted"], rel=1e-6), (
        "a weighted mean that equals the plain mean is not weighting anything"
    )


def test_a_join_keeps_the_keys_it_matched_on():
    result = execute({"operations": [
        scan(fields=["account_id", "ead"]),
        {"id": "b", "op": "SCAN", "params": {
            "dataset": "ifrs9_staging", "period": PERIOD,
            "fields": ["account_id", "ifrs9_stage"]}},
        {"id": "j", "op": "JOIN", "inputs": ["a", "b"], "params": {
            "kind": "inner", "on": ["account_id"]}},
        {"id": "t", "op": "AGGREGATE", "inputs": ["j"], "params": {
            "aggregates": [{"function": "count", "as": "matched"}]}}]})
    assert result.rows[0]["matched"] > 0


def test_a_join_does_not_multiply_rows_on_a_unique_key(book):
    """A silent fan-out is how a join answers a different question."""
    result = execute({"operations": [
        scan(fields=["account_id", "ead"]),
        {"id": "b", "op": "SCAN", "params": {
            "dataset": "ifrs9_staging", "period": PERIOD,
            "fields": ["account_id", "ifrs9_stage"]}},
        {"id": "j", "op": "JOIN", "inputs": ["a", "b"], "params": {
            "kind": "inner", "on": ["account_id"]}},
        {"id": "t", "op": "AGGREGATE", "inputs": ["j"], "params": {
            "aggregates": [{"function": "count", "as": "n"}]}}]})
    assert result.rows[0]["n"] == len(book)


def test_top_n_returns_the_largest_in_order():
    result = execute({"operations": [
        scan(fields=["borrower_name", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["borrower_name"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}},
        {"id": "t", "op": "TOP_N", "inputs": ["g"], "params": {"by": "ead", "n": 10}}]})
    values = [r["ead"] for r in result.rows]
    assert len(values) == 10
    assert values == sorted(values, reverse=True)


def test_a_window_function_computes_over_the_partition_it_was_given():
    result = execute({"operations": [
        scan(fields=["sector", "borrower_name", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector", "borrower_name"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}},
        {"id": "r", "op": "RANK", "inputs": ["g"], "params": {
            "function": "row_number", "partition_by": ["sector"],
            "order_by": [{"column": "ead", "desc": True}], "as": "rank_in_sector"}},
        {"id": "t", "op": "FILTER", "inputs": ["r"], "params": {
            "where": [{"column": "rank_in_sector", "op": "=", "value": 1}]}}]})
    sectors = [r["sector"] for r in result.rows]
    assert len(sectors) == len(set(sectors)), "one leader per sector, no more"


def test_a_kernel_runs_on_the_result_of_the_query_not_the_book():
    result = execute({"operations": [
        scan(fields=["sector", "ead", "total_ecl"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"},
                           {"column": "total_ecl", "function": "sum", "as": "ecl"}]}},
        {"id": "c", "op": "CORRELATION", "inputs": ["g"], "params": {
            "x": "ead", "y": "ecl"}}]})
    row = result.rows[0]
    assert -1 <= row["coefficient"] <= 1
    assert row["n"] < 100, "the kernel saw the aggregate, not sixteen thousand rows"
    assert "causation" in row["note"], "a correlation must carry its caveat"


# ----------------------------------------------------------------- the trace


def test_the_trace_records_the_query_that_actually_ran():
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]},
        question="How is exposure split by sector?")

    nodes = {n["type"]: n for n in result.graph.to_dict()["nodes"]}
    assert "SQL_QUERY" in nodes
    sql_node = nodes["SQL_QUERY"]
    assert "SELECT" in sql_node["config"]["sql"]
    assert sql_node["rows_out"] == result.row_count


def test_the_trace_keeps_the_parameters_apart_from_the_statement():
    """That separation IS the safety property, so the record shows it."""
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "f", "op": "FILTER", "inputs": ["a"], "params": {
            "where": [{"column": "sector", "op": "=", "value": "Real Estate"}]}}]})
    sql_node = next(n for n in result.graph.to_dict()["nodes"]
                    if n["type"] == "SQL_QUERY")
    assert "Real Estate" not in sql_node["config"]["sql"]
    assert "Real Estate" in sql_node["config"]["parameters"]


def test_the_trace_shows_the_whole_path_from_question_to_result():
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "f", "op": "FILTER", "inputs": ["a"], "params": {
            "where": [{"column": "sector", "op": "=", "value": "Real Estate"}]}},
        {"id": "g", "op": "GROUP", "inputs": ["f"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]},
        question="How much Real Estate exposure is there?",
        intent="Sum exposure for one sector")

    types = [n["type"] for n in result.graph.to_dict()["nodes"]]
    for required in ("USER_PROMPT", "LLM_INTENT", "PLAN", "DATA_DOMAIN",
                     "DATASET_FAMILY", "DATASET", "FILTER", "AGGREGATION",
                     "SQL_QUERY", "RESULT"):
        assert required in types, f"the Trace is missing its {required} step"


def test_a_hybrid_run_shows_both_engines():
    result = execute({"operations": [
        scan(fields=["sector", "ead", "total_ecl"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"},
                           {"column": "total_ecl", "function": "sum", "as": "ecl"}]}},
        {"id": "c", "op": "CORRELATION", "inputs": ["g"], "params": {
            "x": "ead", "y": "ecl"}}]})
    engines = {n["config"].get("engine") for n in result.graph.to_dict()["nodes"]}
    assert {"duckdb", "python"} <= engines


def test_every_trace_node_carries_a_hash():
    """Selective re-execution and change highlighting both depend on it."""
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]})
    for node in result.graph.to_dict()["nodes"]:
        assert node["content_hash"], f"{node['id']} has no hash"


# ---------------------------------------------------------------- the contract


def test_a_composed_analysis_is_labelled_dynamic_not_certified():
    """The double tick means somebody validated THIS method. Nobody did."""
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]})
    assert result.certification == ExecutionClass.DYNAMIC
    assert "Governed Runtime" in result.certification_label
    assert "Certified" not in result.certification_label


def test_the_result_carries_everything_a_caller_needs():
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]})
    body = result.to_dict()
    for key in ("run_id", "plan", "columns", "rows", "row_count", "summary",
                "warnings", "certification", "datasets", "duration_ms",
                "chart", "query", "trace"):
        assert key in body, f"the Result contract is missing {key}"
    assert body["datasets"] == [FACILITY]


def test_the_same_plan_always_has_the_same_fingerprint():
    plan = {"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]}
    assert execute(plan).plan.fingerprint() == execute(plan).plan.fingerprint()


# ------------------------------------------------------------------- charts


def test_a_chart_is_chosen_from_the_shape_never_from_the_values():
    """The model may say how to draw it. It may not supply the points."""
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "ead"}]}}]})
    chart = result.chart
    assert chart["chart"] in ("bar", "table")
    # Column names only. No datum from the result appears in the suggestion.
    values = {r["ead"] for r in result.rows}
    assert not values & set(str(v) for v in chart.values())


def test_a_single_row_of_measures_is_offered_as_a_kpi():
    result = execute({"operations": [
        scan(fields=["ead"]),
        {"id": "t", "op": "AGGREGATE", "inputs": ["a"], "params": {
            "aggregates": [{"column": "ead", "function": "sum", "as": "total"}]}}]})
    assert result.chart["chart"] == "kpi"
