"""The critical path, checked against arithmetic done by hand.

A CPM implementation that is only tested against itself is a CPM
implementation that is confidently wrong. Every network here has its expected
early/late dates and float worked out in the docstring, so a failure says
which number moved rather than that something changed.

No database: the engine takes a `control.Plan`, which is why that structure
exists.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.planner import control
from backend.planner import schedule as sch

JAN = date(2026, 1, 1)


def day(n: int) -> date:
    """1 → 1 Jan 2026. Keeps the expected dates readable."""
    return date(2026, 1, n)


def task(code: str, *, start: int | None = None, due: int | None = None,
         effort: int | None = None, critical: bool = False,
         status: str = "IN_PROGRESS") -> control.TaskView:
    return control.TaskView(
        id=abs(hash(code)) % 100000, code=code, title=code, status=status,
        percent_complete=0, start_date=day(start) if start else None,
        due_date=day(due) if due else None, effort_days=effort,
        critical=critical)


def stone(code: str, *, target: int | None = None,
          critical: bool = False) -> control.MilestoneView:
    return control.MilestoneView(
        id=abs(hash(code)) % 100000, code=code, name=code, status="PENDING",
        target_date=day(target) if target else None, critical=critical)


def link(pred, succ, kind: str = "FS", lag: int = 0) -> control.DependencyView:
    def kind_of(node):
        return "MILESTONE" if isinstance(node, control.MilestoneView) else "TASK"

    return control.DependencyView(
        predecessor_type=kind_of(pred), predecessor_id=pred.id,
        successor_type=kind_of(succ), successor_id=succ.id,
        dependency_type=kind, lag_days=lag)


def plan_of(tasks, deps, milestones=()) -> control.Plan:
    return control.Plan(project_id=1, tasks=list(tasks),
                        milestones=list(milestones),
                        dependencies=list(deps))


# ============================================================ the arithmetic


class TestASingleChain:
    """A → B → C, three days each, starting 1 January.

        A  1 Jan – 3 Jan
        B  4 Jan – 6 Jan
        C  7 Jan – 9 Jan

    Everything is critical: there is nowhere for slack to be.
    """

    @pytest.fixture()
    def result(self):
        a, b, c = (task("A", start=1, due=3), task("B", effort=3),
                   task("C", effort=3))
        return sch.compute(plan_of([a, b, c], [link(a, b), link(b, c)]))

    def test_it_computes(self, result):
        assert result.computed, result.cannot_because

    def test_the_forward_pass(self, result):
        assert result.by_code("A").early_finish == day(3)
        assert result.by_code("B").early_start == day(4)
        assert result.by_code("B").early_finish == day(6)
        assert result.by_code("C").early_start == day(7)
        assert result.by_code("C").early_finish == day(9)

    def test_the_project_finishes_when_the_last_thing_does(self, result):
        assert result.project_finish == day(9)

    def test_nothing_has_slack(self, result):
        assert [p.total_float for p in result.placed] == [0, 0, 0]

    def test_the_path_is_the_whole_chain(self, result):
        assert result.critical_path == ["A", "B", "C"]


class TestTwoParallelPaths:
    """One long branch and one short one, meeting at D.

        A  1 Jan – 2 Jan   (2 days)
        B  3 Jan – 8 Jan   (6 days)   long branch
        C  3 Jan – 4 Jan   (2 days)   short branch
        D  9 Jan – 9 Jan   (1 day)

    The path is A → B → D. C may start as late as 7 Jan, so it has four
    days of float — the difference between the two branches.
    """

    @pytest.fixture()
    def result(self):
        a = task("A", start=1, due=2)
        b, c, d = task("B", effort=6), task("C", effort=2), task("D", effort=1)
        deps = [link(a, b), link(a, c), link(b, d), link(c, d)]
        return sch.compute(plan_of([a, b, c, d], deps))

    def test_the_long_branch_is_the_path(self, result):
        assert result.critical_path == ["A", "B", "D"]

    def test_the_short_branch_carries_the_difference(self, result):
        assert result.by_code("C").total_float == 4
        assert result.by_code("C").late_start == day(7)

    def test_the_finish_follows_the_long_branch(self, result):
        assert result.project_finish == day(9)


class TestEqualLengthPaths:
    """When both branches are the same length, both are critical.

    A tie is not an error and must not be broken arbitrarily: two paths with
    no slack both determine the end date, and a screen that showed one of them
    would tell a manager the other could slip.
    """

    def test_both_branches_are_on_the_path(self):
        a = task("A", start=1, due=2)
        b, c, d = task("B", effort=3), task("C", effort=3), task("D", effort=1)
        deps = [link(a, b), link(a, c), link(b, d), link(c, d)]
        result = sch.compute(plan_of([a, b, c, d], deps))
        assert result.critical_path == ["A", "B", "C", "D"]
        assert result.by_code("B").total_float == 0
        assert result.by_code("C").total_float == 0


class TestLagsAndKinds:
    def test_a_positive_lag_pushes_the_successor_out(self):
        """A finishes 3 Jan; a two-day lag starts B on 6 Jan, not 4 Jan."""
        a, b = task("A", start=1, due=3), task("B", effort=2)
        result = sch.compute(plan_of([a, b], [link(a, b, lag=2)]))
        assert result.by_code("B").early_start == day(6)
        assert result.by_code("B").early_finish == day(7)

    def test_start_to_start_lets_them_run_together(self):
        """SS with no lag: B starts the same day A does, not after it."""
        a, b = task("A", start=1, due=5), task("B", effort=2)
        result = sch.compute(plan_of([a, b], [link(a, b, kind="SS")]))
        assert result.by_code("B").early_start == day(1)

    def test_finish_to_finish_holds_the_successor_open(self):
        """FF: B cannot finish before A does, so a one-day B waits."""
        a, b = task("A", start=1, due=5), task("B", effort=1)
        result = sch.compute(plan_of([a, b], [link(a, b, kind="FF")]))
        assert result.by_code("B").early_finish == day(5)
        assert result.by_code("B").early_start == day(5)

    def test_start_to_finish(self):
        """SF: B cannot finish before A starts."""
        a, b = task("A", start=5, due=8), task("B", effort=1)
        result = sch.compute(plan_of([a, b], [link(a, b, kind="SF")]))
        assert result.by_code("B").early_finish >= day(5)


class TestMilestones:
    def test_a_milestone_takes_no_time_and_lands_after_its_predecessor(self):
        a = task("A", start=1, due=4)
        m = stone("M-1", target=10)
        result = sch.compute(plan_of([a], [link(a, m)], milestones=[m]))
        assert result.computed, result.cannot_because
        placed = result.by_code("M-1")
        assert placed.node.duration == 0
        assert placed.early_start == day(5)
        assert placed.early_finish == day(5)


class TestMarkedVersusCalculated:
    """The two concepts are reported side by side and never merged."""

    def test_a_marker_the_arithmetic_does_not_agree_with_is_named(self):
        a = task("A", start=1, due=2)
        b = task("B", effort=6)
        c = task("C", effort=2, critical=True)  # somebody ticked the slack one
        d = task("D", effort=1)
        deps = [link(a, b), link(a, c), link(b, d), link(c, d)]
        result = sch.compute(plan_of([a, b, c, d], deps))
        assert result.marked_not_calculated == ["C"]
        assert "B" in result.calculated_not_marked
        assert result.by_code("C").node.marked_critical is True
        assert result.by_code("C").critical is False
        assert result.by_code("C").to_dict()["disagrees"] is True


# ============================================================ the refusals


class TestItRefusesRatherThanGuesses:
    def test_no_dependencies_means_no_network(self):
        result = sch.compute(plan_of([task("A", start=1, due=3)], []))
        assert result.computed is False
        assert "No dependencies" in result.cannot_because[0]

    def test_a_missing_duration_is_named_by_task(self):
        a = task("A", start=1, due=3)
        b = task("B")  # no dates, no effort
        result = sch.compute(plan_of([a, b], [link(a, b)]))
        assert result.computed is False
        assert "B" in result.cannot_because[0]
        assert "effort estimate" in result.cannot_because[0]

    def test_a_cycle_is_named_as_a_path(self):
        a, b = task("A", start=1, due=2), task("B", effort=2)
        result = sch.compute(plan_of([a, b], [link(a, b), link(b, a)]))
        assert result.computed is False
        assert "circle" in result.cannot_because[0]

    def test_no_date_anywhere_means_no_fixed_point(self):
        a, b = task("A", effort=2), task("B", effort=2)
        result = sch.compute(plan_of([a, b], [link(a, b)]))
        assert result.computed is False
        assert "fixed point" in result.cannot_because[0]

    def test_a_completed_task_still_has_a_duration(self):
        """A finished task is still part of the chain that produced the date."""
        a = task("A", start=1, due=3, status="COMPLETED")
        b = task("B", effort=2)
        result = sch.compute(plan_of([a, b], [link(a, b)]))
        assert result.computed, result.cannot_because
        assert result.by_code("A").node.complete is True

    def test_an_unlinked_task_without_a_duration_does_not_block_the_path(self):
        """Only nodes in the network need durations. Refusing to compute a
        perfectly computable path because of an unrelated task would be a
        refusal nobody could act on."""
        a, b = task("A", start=1, due=3), task("B", effort=2)
        loose = task("LOOSE")
        result = sch.compute(plan_of([a, b, loose], [link(a, b)]))
        assert result.computed, result.cannot_because
        assert result.by_code("LOOSE") is None


# ======================================================= downstream impact


class TestIfThisSlips:
    """A → B → D long branch; C is the slack branch with four days.

    Slipping B by two days moves D by two and the project finish by two.
    Slipping C by two is absorbed entirely: it has four days of float.
    """

    @pytest.fixture()
    def plan(self):
        a = task("A", start=1, due=2)
        b, c, d = task("B", effort=6), task("C", effort=2), task("D", effort=1)
        return plan_of([a, b, c, d],
                       [link(a, b), link(a, c), link(b, d), link(c, d)])

    def test_a_slip_on_the_path_moves_the_finish(self, plan):
        found = sch.slip(plan, "B", 2)
        assert found is not None
        assert found.finish_moves_by == 2
        assert found.absorbed is False
        assert [m["code"] for m in found.moved] == ["D"]
        assert found.moved[0]["days"] == 2

    def test_a_slip_inside_float_is_absorbed(self, plan):
        found = sch.slip(plan, "C", 2)
        assert found is not None
        assert found.absorbed is True
        assert found.finish_moves_by == 0
        assert found.moved == []

    def test_a_slip_bigger_than_the_float_is_not_absorbed(self, plan):
        found = sch.slip(plan, "C", 6)
        assert found is not None
        assert found.absorbed is False
        assert found.finish_moves_by == 2  # 6 days of slip, 4 days of float

    def test_the_what_if_does_not_change_the_plan(self, plan):
        before = [t.due_date for t in plan.tasks]
        sch.slip(plan, "B", 5)
        assert [t.due_date for t in plan.tasks] == before

    def test_no_slip_analysis_where_there_is_no_schedule(self):
        assert sch.slip(plan_of([task("A", start=1, due=2)], []), "A", 2) is None
