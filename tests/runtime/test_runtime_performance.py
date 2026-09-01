"""
Does it answer fast enough to be used?

Not a benchmark. A benchmark measures how fast something is; these check that a
composed analysis over the real demonstration book stays inside the budget a
person waiting at a screen will tolerate, and that the safety limits actually
bound the work rather than being decoration.

Bounds are deliberately loose — this runs on whatever machine CI gave it, and a
test that fails because the box was busy teaches people to ignore it. What they
catch is a regression of the kind that turns two seconds into two minutes: a
join that lost its key, a scan that stopped pushing its period down, a plan that
reads every quarter to answer a question about one.
"""

from __future__ import annotations

import time

import pytest

from backend.data_access import get_data_source
from backend.runtime.executor import execute
from backend.runtime.ir import AnalyticalPlan
from backend.runtime.validation import DEFAULT_LIMITS, validate

FACILITY = "portfolio_facility"

#: What a person waiting at a screen tolerates before the product feels broken.
INTERACTIVE_BUDGET_S = 12.0
#: A composed multi-step analysis over two periods.
COMPOSED_BUDGET_S = 25.0


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built")


@pytest.fixture(scope="module")
def periods():
    return get_data_source().periods(FACILITY)


def timed(plan, **kwargs):
    started = time.perf_counter()
    result = execute(plan, **kwargs)
    return result, time.perf_counter() - started


def test_a_simple_breakdown_is_interactive(periods):
    plan = {
        "id": "ecl_by_sector",
        "operations": [
            {"id": "scan", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": periods[-1],
                        "fields": ["sector", "ead", "total_ecl"]}},
            {"id": "grouped", "op": "GROUP", "inputs": ["scan"],
             "params": {"by": ["sector"],
                        "aggregates": [
                            {"function": "sum", "column": "ead", "as": "ead"},
                            {"function": "sum", "column": "total_ecl", "as": "ecl"}]}},
        ],
    }
    result, elapsed = timed(plan, question="ECL by sector")
    assert result.row_count > 0
    assert elapsed < INTERACTIVE_BUDGET_S, f"{elapsed:.1f}s"


def test_a_two_period_join_over_the_whole_book_is_acceptable(periods):
    """The shape every dynamic cohort question takes. If this degrades, every
    composed answer degrades with it."""
    plan = {
        "id": "movement",
        "operations": [
            {"id": "opening", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": periods[-5],
                        "fields": ["account_id", "ead", "total_ecl"]}},
            {"id": "closing", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": periods[-1],
                        "fields": ["account_id", "ead", "total_ecl"]}},
            {"id": "joined", "op": "JOIN", "inputs": ["opening", "closing"],
             "params": {"kind": "inner", "on": ["account_id"],
                        "right_prefix": "closing_"}},
            {"id": "moved", "op": "DERIVE", "inputs": ["joined"],
             "params": {"columns": [{"as": "ecl_change",
                                     "expression": {"type": "function",
                                                    "function": "subtract",
                                                    "args": ["closing_total_ecl",
                                                             "total_ecl"]}}]}},
            {"id": "totals", "op": "AGGREGATE", "inputs": ["moved"],
             "params": {"aggregates": [
                 {"function": "count", "as": "facilities"},
                 {"function": "sum", "column": "ecl_change", "as": "ecl_movement"}]}},
        ],
    }
    result, elapsed = timed(plan, question="How did ECL move over the year?")
    assert result.rows[0]["facilities"] > 1000
    assert elapsed < COMPOSED_BUDGET_S, f"{elapsed:.1f}s"


def test_the_worked_dynamic_question_stays_inside_the_budget():
    from backend.orchestration.dynamic import build_plan, read_question
    from backend.orchestration.vocabulary import get_vocabulary

    vocabulary = get_vocabulary()
    request = read_question(
        "Show Real Estate customers whose ECL increased more than 20%, rating "
        "deteriorated at least two notches, and EAD did not decline over the "
        "latest year.",
        periods=vocabulary.periods, dimensions=vocabulary.dimensions)
    assert request.understood
    _, elapsed = timed(build_plan(request), question="worked example")
    assert elapsed < COMPOSED_BUDGET_S, f"{elapsed:.1f}s"


def test_a_scan_reads_one_period_not_every_period(periods):
    """A plan naming a period must not read the whole book. This is the
    regression that turns a fast question into a slow one without changing a
    single figure, so it is checked on row counts rather than on the clock."""
    source = get_data_source()
    total = source.row_count(FACILITY)

    plan = {
        "id": "one_period",
        "operations": [
            {"id": "scan", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": periods[-1],
                        "fields": ["account_id"]}},
            {"id": "count", "op": "AGGREGATE", "inputs": ["scan"],
             "params": {"aggregates": [{"function": "count", "as": "rows"}]}},
        ],
    }
    result, _ = timed(plan, question="How many facilities this quarter?")
    read = result.rows[0]["rows"]
    assert read < total, "A period-scoped scan read the whole book."
    assert read > total / (len(periods) * 2)


# ------------------------------------------------------------------- limits


def test_the_operation_limit_is_enforced():
    operations = [{"id": "scan", "op": "SCAN",
                   "params": {"dataset": FACILITY, "fields": ["ead"]}}]
    previous = "scan"
    for index in range(DEFAULT_LIMITS.max_operations + 5):
        step = f"f{index}"
        operations.append({"id": step, "op": "FILTER", "inputs": [previous],
                           "params": {"where": [{"column": "ead", "op": ">",
                                                 "value": 0}]}})
        previous = step
    report = validate(AnalyticalPlan.from_dict({"id": "long", "operations": operations}))
    assert not report.ok
    assert any("operation" in r.lower() for r in report.reasons)


def test_the_scan_limit_is_enforced():
    operations = [
        {"id": f"s{i}", "op": "SCAN",
         "params": {"dataset": FACILITY, "fields": ["ead"]}}
        for i in range(DEFAULT_LIMITS.max_scans + 3)
    ]
    report = validate(AnalyticalPlan.from_dict({"id": "many", "operations": operations}))
    assert not report.ok


def test_the_output_row_cap_is_applied(periods):
    """A question whose answer is the whole book comes back capped and says so,
    rather than returning four hundred thousand rows to a browser."""
    plan = {
        "id": "everything",
        "operations": [
            {"id": "scan", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": periods[-1],
                        "fields": ["account_id", "ead"]}},
        ],
    }
    result, _ = timed(plan, question="Show me everything")
    assert result.row_count <= DEFAULT_LIMITS.max_output_rows


def test_an_expression_nested_beyond_the_limit_is_refused():
    expression: dict = {"type": "literal", "value": 1}
    for _ in range(DEFAULT_LIMITS.max_expression_depth + 4):
        expression = {"type": "function", "function": "add",
                      "args": [expression, {"type": "literal", "value": 1}]}
    report = validate(AnalyticalPlan.from_dict({
        "id": "deep",
        "operations": [
            {"id": "scan", "op": "SCAN",
             "params": {"dataset": FACILITY, "fields": ["ead"]}},
            {"id": "derived", "op": "DERIVE", "inputs": ["scan"],
             "params": {"columns": [{"as": "x", "expression": expression}]}},
        ],
    }))
    assert not report.ok
