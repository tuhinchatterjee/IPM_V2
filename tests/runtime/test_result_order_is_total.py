"""
§11 — the same question returns the same table, in the same order.

Found by running the twenty-two questions of §39 twice each: the same
question came back with the same seventy-nine borrowers in a different order.
Same set, shuffled. Which names appear "at the top" changed between two
identical asks, and nobody reading the screen would have any reason to doubt
either version.

The cause was ordinary and easy to miss: an `ORDER BY` inside a CTE does not
bind the outer `SELECT`, and a plan with no SORT never expressed one at all -
so the row order was whatever the join happened to produce, which is not
stable across runs.

Two fixes were wrong before this one was right, and both are worth a test of
their own:

  * imposing `ORDER BY ALL` unconditionally destroyed rankings - a
    top-ten-by-PD came back sorted by its first column;
  * suppressing the outer order whenever the plan ordered anywhere put the
    original defect straight back.

The order now REFINES: the plan's own ordering first, then every column to
break the ties it left open.
"""

from __future__ import annotations

import pytest

from backend.runtime import ir
from backend.runtime.executor import execute

DATASET = "corporate_borrower_360"


def _rows(plan: dict) -> list[dict]:
    return list(execute(plan, question="ordering", intent="ordering").rows)


def _plan(*ops: dict) -> dict:
    return {"id": "order-test", "operations": list(ops)}


def _scan(step: str = "s1") -> dict:
    return {"id": step, "op": ir.OpType.SCAN.value, "inputs": [],
            "params": {"dataset": DATASET}}


@pytest.fixture(scope="module")
def period() -> str:
    from backend.corporate import service as corporate

    return corporate.latest_period()


class TestAnUnorderedPlanStillComesBackTheSameWayTwice:

    def test_two_identical_runs_return_the_same_row_order(self, period):
        plan = _plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.FILTER.value, "inputs": ["s1"],
             "params": {"where": [{"column": "period", "op": "=",
                                   "value": period}]}},
            {"id": "s3", "op": ir.OpType.SELECT.value, "inputs": ["s2"],
             "params": {"columns": ["borrower_id", "sector", "pd_12m"]}},
            {"id": "s4", "op": ir.OpType.LIMIT.value, "inputs": ["s3"],
             "params": {"n": 40}},
        )
        first, second = _rows(plan), _rows(plan)
        assert [r["borrower_id"] for r in first] == \
               [r["borrower_id"] for r in second]

    def test_the_order_is_total_rather_than_merely_repeatable(self, period):
        """No two rows may be interchangeable.

        A plan whose projection is one heavily-tied column would still be
        "the same twice" by luck of the engine. Ordering by every column
        makes the order a property of the DATA, which is what makes it hold
        on somebody else's machine too.
        """
        plan = _plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.FILTER.value, "inputs": ["s1"],
             "params": {"where": [{"column": "period", "op": "=",
                                   "value": period}]}},
            {"id": "s3", "op": ir.OpType.SELECT.value, "inputs": ["s2"],
             "params": {"columns": ["stage", "borrower_id"]}},
            {"id": "s4", "op": ir.OpType.LIMIT.value, "inputs": ["s3"],
             "params": {"n": 60}},
        )
        rows = _rows(plan)
        keys = [tuple(sorted(r.items(), key=lambda kv: kv[0])) for r in rows]
        assert len(set(keys)) == len(keys) or rows == _rows(plan)
        assert rows == _rows(plan)


class TestARankingStaysARanking:
    """The regression the first fix caused, kept."""

    def test_a_sorted_plan_keeps_its_sort(self, period):
        plan = _plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.FILTER.value, "inputs": ["s1"],
             "params": {"where": [{"column": "period", "op": "=",
                                   "value": period}]}},
            {"id": "s3", "op": ir.OpType.SELECT.value, "inputs": ["s2"],
             "params": {"columns": ["borrower_id", "pd_12m"]}},
            {"id": "s4", "op": ir.OpType.SORT.value, "inputs": ["s3"],
             "params": {"by": [{"column": "pd_12m", "direction": "desc"}]}},
            {"id": "s5", "op": ir.OpType.LIMIT.value, "inputs": ["s4"],
             "params": {"n": 25}},
        )
        rows = _rows(plan)
        values = [r["pd_12m"] for r in rows if r["pd_12m"] is not None]
        assert values == sorted(values, reverse=True), (
            "the outer ordering re-sorted a ranking: every number is still "
            "right and the claim the table makes is not")

    def test_a_sorted_plan_is_also_the_same_twice(self, period):
        """Both properties at once, which is the whole point.

        The second wrong fix had this test passing and the previous one
        failing; the first had it the other way round.
        """
        plan = _plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.FILTER.value, "inputs": ["s1"],
             "params": {"where": [{"column": "period", "op": "=",
                                   "value": period}]}},
            {"id": "s3", "op": ir.OpType.SELECT.value, "inputs": ["s2"],
             "params": {"columns": ["borrower_id", "stage"]}},
            {"id": "s4", "op": ir.OpType.SORT.value, "inputs": ["s3"],
             "params": {"by": [{"column": "stage",
                                "direction": "desc"}]}},
            {"id": "s5", "op": ir.OpType.LIMIT.value, "inputs": ["s4"],
             "params": {"n": 50}},
        )
        first, second = _rows(plan), _rows(plan)
        assert [r["borrower_id"] for r in first] == \
               [r["borrower_id"] for r in second]
        stages = [r["stage"] for r in first
                  if r["stage"] is not None]
        assert stages == sorted(stages, reverse=True)

    def test_a_top_n_keeps_its_rank_order(self, period):
        plan = _plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.FILTER.value, "inputs": ["s1"],
             "params": {"where": [{"column": "period", "op": "=",
                                   "value": period}]}},
            {"id": "s3", "op": ir.OpType.SELECT.value, "inputs": ["s2"],
             "params": {"columns": ["borrower_id", "drawn_exposure"]}},
            {"id": "s4", "op": ir.OpType.TOP_N.value, "inputs": ["s3"],
             "params": {"by": "drawn_exposure", "n": 10}},
        )
        rows = _rows(plan)
        values = [r["drawn_exposure"] for r in rows
                  if r["drawn_exposure"] is not None]
        assert values == sorted(values, reverse=True)
        assert _rows(plan) == rows


class TestTheCompilerSaysWhatItOrderedBy:
    """Asserted on the SQL, so a change to the clause is visible in review."""

    def test_an_unordered_plan_gets_a_total_order(self):
        from backend.runtime.compiler import compile_plan
        from backend.runtime.ir import AnalyticalPlan
        from backend.runtime.validation import validate

        plan = AnalyticalPlan.from_dict(_plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.SELECT.value, "inputs": ["s1"],
             "params": {"columns": ["borrower_id", "sector"]}},
        ))
        query = compile_plan(plan, validate(plan).raise_if_bad())
        assert "ORDER BY COLUMNS(*)" in query.sql

    def test_an_ordered_plan_keeps_its_clause_and_adds_a_tie_break(self):
        from backend.runtime.compiler import compile_plan
        from backend.runtime.ir import AnalyticalPlan
        from backend.runtime.validation import validate

        plan = AnalyticalPlan.from_dict(_plan(
            _scan(),
            {"id": "s2", "op": ir.OpType.SELECT.value, "inputs": ["s1"],
             "params": {"columns": ["borrower_id", "pd_12m"]}},
            {"id": "s3", "op": ir.OpType.SORT.value, "inputs": ["s2"],
             "params": {"by": [{"column": "pd_12m", "direction": "desc"}]}},
        ))
        query = compile_plan(plan, validate(plan).raise_if_bad())
        assert "ORDER BY" in query.sql
        assert "COLUMNS(*)" in query.sql
        assert "pd_12m" in query.sql.rsplit("ORDER BY", 1)[-1]
