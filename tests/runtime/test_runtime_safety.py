"""
What the Analytical Runtime refuses.

This is the module that decides whether the pivot is safe. CreditProbe now
composes analyses rather than choosing from a list, which means a language model
is producing the shape of a query against the credit book. The claim that this
is safe rests on one thing: the model's output is DATA until the runtime turns it
into SQL, and the runtime will not do that for anything the governed catalogue
has not confirmed.

So these tests are adversarial. They are written as the things somebody would
try, not as coverage of the happy path — that lives in test_runtime_execution.py.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.runtime.executor import execute
from backend.runtime.ir import AnalyticalPlan, PlanError
from backend.runtime.validation import validate

FACILITY = "portfolio_facility"


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built")


def refuse(raw: dict) -> str:
    """Run a plan that must be refused, and return the reason."""
    with pytest.raises(PlanError) as raised:
        execute(raw)
    return str(raised.value)


def scan(**params) -> dict:
    return {"id": "a", "op": "SCAN", "params": {"dataset": FACILITY,
                                                "period": "Q1 2026", **params}}


# ------------------------------------------------------------ ungoverned data


def test_a_dataset_nobody_published_cannot_be_read():
    reason = refuse({"operations": [
        {"id": "a", "op": "SCAN", "params": {"dataset": "payroll"}}]})
    assert "not a governed dataset" in reason


def test_a_field_nobody_governed_cannot_be_read():
    reason = refuse({"operations": [
        scan(fields=["ead"]),
        {"id": "b", "op": "FILTER", "inputs": ["a"],
         "params": {"where": [{"column": "salary", "op": ">", "value": 1}]}}]})
    assert "not a column available" in reason


def test_a_path_cannot_be_smuggled_in_as_a_dataset_name():
    """The dataset name is a catalogue key, never a location on disk."""
    for attempt in ("../../etc/passwd", "/etc/passwd",
                    "data/analytics/portfolio_facility"):
        reason = refuse({"operations": [
            {"id": "a", "op": "SCAN", "params": {"dataset": attempt}}]})
        assert "not a governed dataset" in reason


def test_a_column_name_cannot_carry_sql():
    """Identifiers are checked, then quoted. Neither step is optional."""
    reason = refuse({"operations": [
        scan(fields=["ead"]),
        {"id": "b", "op": "SORT", "inputs": ["a"],
         "params": {"by": ['ead"; DROP TABLE facilities; --']}}]})
    assert "not a column available" in reason


# --------------------------------------------------------------- injection


def test_a_filter_value_is_bound_and_never_becomes_sql():
    """The safety property, asserted on the compiled artefact itself."""
    from backend.runtime.compiler import compile_plan

    nasty = "Real Estate'; DROP TABLE facilities; --"
    plan = AnalyticalPlan.from_dict({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "b", "op": "FILTER", "inputs": ["a"],
         "params": {"where": [{"column": "sector", "op": "=", "value": nasty}]}}]})
    query = compile_plan(plan, validate(plan))

    assert nasty not in query.sql, "a user value reached the statement text"
    assert nasty in query.params, "the value should have been bound as a parameter"
    assert query.sql.count("?") == len(query.params)


def test_a_value_shaped_like_sql_simply_matches_nothing():
    """End to end: it is compared, not executed."""
    result = execute({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "b", "op": "FILTER", "inputs": ["a"],
         "params": {"where": [{"column": "sector", "op": "=",
                               "value": "x' OR '1'='1"}]}}]})
    assert result.row_count == 0


def test_every_literal_in_an_expression_is_bound():
    from backend.runtime.compiler import compile_plan

    plan = AnalyticalPlan.from_dict({"operations": [
        scan(fields=["ead"]),
        {"id": "b", "op": "DERIVE", "inputs": ["a"], "params": {"columns": [
            {"as": "big", "expression": {"type": "function", "function": "gt",
                                         "args": ["ead", {"type": "literal",
                                                          "value": 99999}]}}]}}]})
    query = compile_plan(plan, validate(plan))
    assert "99999" not in query.sql
    assert 99999 in query.params


# ------------------------------------------------------------- no arbitrary code


def test_the_runtime_has_no_way_to_run_supplied_code():
    """There is no operation that takes code, in any form."""
    from backend.runtime.ir import OpType

    for attempt in ("PYTHON", "EXEC", "EVAL", "SQL", "SHELL", "SCRIPT",
                    "RAW_SQL", "CODE"):
        with pytest.raises(ValueError):
            OpType(attempt)


def test_a_kernel_not_on_the_list_is_refused():
    reason = refuse({"operations": [
        scan(fields=["ead"]),
        {"id": "k", "op": "REGRESSION", "inputs": ["a"],
         "params": {"kernel": "run_this_python", "target": "ead",
                    "features": ["ead"]}}]})
    assert "not a numerical operation CreditProbe provides" in reason


def test_a_scalar_function_not_on_the_list_is_refused():
    reason = refuse({"operations": [
        scan(fields=["ead"]),
        {"id": "b", "op": "DERIVE", "inputs": ["a"], "params": {"columns": [
            {"as": "x", "expression": {"type": "function",
                                       "function": "system", "args": ["ead"]}}]}}]})
    assert "not a function the runtime provides" in reason


def test_an_aggregate_not_on_the_list_is_refused():
    reason = refuse({"operations": [
        scan(fields=["sector", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"],
         "params": {"by": ["sector"],
                    "aggregates": [{"column": "ead", "function": "eval", "as": "x"}]}}]})
    assert "not an aggregate the runtime provides" in reason


# ------------------------------------------------------------------ cost


def test_a_join_with_no_keys_is_refused():
    """Every row against every row is never what somebody meant."""
    reason = refuse({"operations": [
        scan(fields=["account_id", "ead"]),
        {"id": "b", "op": "SCAN", "params": {"dataset": "ifrs9_staging",
                                             "period": "Q1 2026",
                                             "fields": ["account_id"]}},
        {"id": "j", "op": "JOIN", "inputs": ["a", "b"], "params": {"kind": "inner"}}]})
    assert "pairs every row with every row" in reason


def test_an_output_larger_than_the_cap_is_refused():
    reason = refuse({"operations": [
        scan(), {"id": "l", "op": "LIMIT", "inputs": ["a"], "params": {"n": 999_999}}]})
    assert "returns at most" in reason


def test_a_result_is_capped_even_without_an_explicit_limit():
    """The backstop, not the plan's own limit."""
    from backend.runtime.compiler import compile_plan
    from backend.runtime.validation import DEFAULT_LIMITS

    plan = AnalyticalPlan.from_dict({"operations": [scan()]})
    query = compile_plan(plan, validate(plan))
    assert f"LIMIT {DEFAULT_LIMITS.max_output_rows}" in query.sql


def test_too_many_operations_is_refused():
    operations = [scan(fields=["ead"])]
    for index in range(80):
        operations.append({
            "id": f"f{index}", "op": "FILTER",
            "inputs": [operations[-1]["id"]],
            "params": {"where": [{"column": "ead", "op": ">", "value": 0}]}})
    reason = refuse({"operations": operations})
    assert "operations" in reason and "allows" in reason


def test_a_plan_that_refers_to_itself_is_refused():
    reason = refuse({"operations": [
        {"id": "a", "op": "FILTER", "inputs": ["b"],
         "params": {"where": [{"column": "x", "op": "=", "value": 1}]}},
        {"id": "b", "op": "FILTER", "inputs": ["a"],
         "params": {"where": [{"column": "x", "op": "=", "value": 1}]}}]})
    assert "loop" in reason


# ---------------------------------------------------------------- governance


def test_a_dataset_in_an_archived_domain_is_not_readable_by_the_runtime():
    from backend.data_access.catalog import get_catalog

    domain = get_catalog().dataset(FACILITY).domain
    plan = AnalyticalPlan.from_dict({"operations": [scan(fields=["ead"])]})

    report = validate(plan, archived_domains=frozenset({domain}))
    assert not report.ok
    assert "archived" in " ".join(report.reasons)


def test_an_ordered_function_without_an_order_is_refused():
    """A LAG with no ORDER BY returns a different answer on each run."""
    reason = refuse({"operations": [
        scan(fields=["ead"]),
        {"id": "l", "op": "LAG", "inputs": ["a"], "params": {"column": "ead"}}]})
    assert "order" in reason.lower()


def test_a_weighted_average_must_say_what_it_weights_by():
    reason = refuse({"operations": [
        scan(fields=["sector", "pd_12m_pct"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "pd_12m_pct", "function": "weighted_avg",
                            "as": "pd"}]}}]})
    assert "weight" in reason


def test_a_column_dropped_by_a_group_cannot_be_used_after_it():
    """Schema is carried step by step, exactly as the compiler will."""
    reason = refuse({"operations": [
        scan(fields=["sector", "borrower_name", "ead"]),
        {"id": "g", "op": "GROUP", "inputs": ["a"], "params": {
            "by": ["sector"],
            "aggregates": [{"column": "ead", "function": "sum", "as": "e"}]}},
        {"id": "s", "op": "SORT", "inputs": ["g"], "params": {"by": ["borrower_name"]}}]})
    assert "borrower_name" in reason


def test_a_refusal_lists_every_problem_not_only_the_first():
    plan = AnalyticalPlan.from_dict({"operations": [
        {"id": "a", "op": "SCAN", "params": {"dataset": "nope"}},
        {"id": "b", "op": "SCAN", "params": {"dataset": "also_nope"}}]})
    report = validate(plan)
    assert len(report.reasons) >= 2, "fixing them one round trip at a time is hostile"


def test_a_refusal_suggests_the_nearest_governed_name():
    """Self-service beats a support ticket."""
    reason = refuse({"operations": [
        scan(fields=["ead"]),
        {"id": "b", "op": "FILTER", "inputs": ["a"],
         "params": {"where": [{"column": "eadd", "op": ">", "value": 1}]}}]})
    assert "Did you mean" in reason and "ead" in reason
