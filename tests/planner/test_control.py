"""The deterministic engine, on its own.

Everything else in this package reaches `control.py` through a database, an
HTTP route or a browser. This file reaches it directly, because it is 884
lines of pure functions of a plan and a date, and that is exactly the shape
that deserves fast table-driven tests rather than a fixture and a session.

It is also the module a steering committee's trust rests on. A colour that
cannot be explained is a colour nobody acts on, so most of what follows
asserts the SENTENCE as well as the verdict.

No database, no principal, no clock. `today` is always passed in.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.planner import control

TODAY = date(2026, 6, 15)


def task(**kw) -> control.TaskView:
    """A task with sensible defaults, so each test states only what it means."""
    base = {
        "id": kw.pop("id", 1),
        "code": kw.pop("code", "T-1"),
        "title": kw.pop("title", "A task"),
        "status": kw.pop("status", "IN_PROGRESS"),
        "percent_complete": kw.pop("percent_complete", 50),
    }
    return control.TaskView(**base, **kw)


def plan(**kw) -> control.Plan:
    return control.Plan(project_id=kw.pop("project_id", 1),
                        code=kw.pop("code", "P-1"), **kw)


# ============================================================ lateness


class TestLateness:
    def test_a_task_due_yesterday_is_one_day_overdue(self):
        assert control.days_overdue(
            task(due_date=TODAY - timedelta(days=1)), TODAY) == 1

    def test_a_task_due_today_is_not_overdue(self):
        """The boundary, which is where this kind of rule always breaks.

        Somebody with a task due today has until the end of today. Calling it
        overdue at one minute past midnight is how a product loses the benefit
        of the doubt it needs to be believed about the genuinely late ones.
        """
        assert control.days_overdue(task(due_date=TODAY), TODAY) == 0
        assert control.days_until_due(task(due_date=TODAY), TODAY) == 0

    def test_a_closed_task_is_never_overdue(self):
        """A task finished late is finished. Its lateness is history, and
        keeping it on the overdue list forever means the list is never
        actionable."""
        for status in ("COMPLETED", "CANCELLED"):
            assert control.days_overdue(
                task(status=status, due_date=TODAY - timedelta(days=30)),
                TODAY) == 0

    def test_a_task_with_no_date_is_not_overdue(self):
        assert control.days_overdue(task(due_date=None), TODAY) == 0
        assert control.days_until_due(task(due_date=None), TODAY) is None


class TestStaleness:
    def test_silence_on_a_near_term_task_is_stale(self):
        quiet = task(due_date=TODAY + timedelta(days=3),
                     last_update_at=datetime(2026, 6, 1, tzinfo=UTC))
        assert control.is_stale(quiet, TODAY)

    def test_a_recently_updated_task_is_not_stale(self):
        fresh = task(due_date=TODAY + timedelta(days=3),
                     last_update_at=datetime(2026, 6, 14, tzinfo=UTC))
        assert not control.is_stale(fresh, TODAY)

    def test_progress_with_no_update_row_is_not_silence(self):
        """The fix for a real defect in this engine.

        A plan imported from a workbook arrives with progress on it and no
        update rows at all. Calling a task at 90% "never updated" tells its
        owner off for somebody else's spreadsheet.
        """
        imported = task(percent_complete=90, due_date=TODAY + timedelta(days=3),
                        last_update_at=None)
        assert not control.is_stale(imported, TODAY)

        untouched = task(percent_complete=0,
                         due_date=TODAY + timedelta(days=3),
                         last_update_at=None)
        assert control.is_stale(untouched, TODAY)

    def test_a_far_off_task_is_not_chased_for_silence(self):
        """Staleness is about NEAR-TERM work. Nagging somebody about a task
        due in four months is how people learn to ignore the product."""
        far = task(due_date=TODAY + timedelta(days=120), last_update_at=None,
                   percent_complete=0)
        assert not control.is_stale(far, TODAY)

    def test_the_project_can_widen_its_own_window(self):
        quiet = task(due_date=TODAY + timedelta(days=3),
                     last_update_at=datetime(2026, 6, 5, tzinfo=UTC))
        assert control.is_stale(quiet, TODAY, window=7)
        assert not control.is_stale(quiet, TODAY, window=30)


# ============================================================ progress


class TestProgress:
    def test_it_is_weighted_by_the_weights(self):
        assert control.progress([
            task(id=1, weight=3, percent_complete=100),
            task(id=2, weight=1, percent_complete=0),
        ]) == 75

    def test_a_cancelled_task_leaves_the_denominator(self):
        """Not zero-scored — removed.

        Scoring a cancelled task at 0% punishes a project for work it was
        correctly decided not to do, which is the opposite of the signal.
        Two done out of three, with a fourth cancelled, is 100%.
        """
        assert control.progress([
            task(id=1, weight=1, status="COMPLETED", percent_complete=100),
            task(id=2, weight=1, status="COMPLETED", percent_complete=100),
            task(id=3, weight=5, status="CANCELLED", percent_complete=0),
        ]) == 100

    def test_a_completed_task_counts_as_whole_however_its_percent_reads(self):
        assert control.progress([
            task(status="COMPLETED", percent_complete=40)]) == 100

    def test_an_empty_or_weightless_plan_is_zero_not_an_error(self):
        assert control.progress([]) == 0
        assert control.progress([task(weight=0)]) == 0

    def test_a_negative_weight_cannot_drag_the_total(self):
        """Defence in depth: the service refuses a negative weight, but the
        engine also runs over workbook rows that have not been through it."""
        assert control.progress([
            task(id=1, weight=1, percent_complete=100),
            task(id=2, weight=-10, percent_complete=0),
        ]) == 100

    def test_workstreams_are_scored_separately(self):
        scored = control.workstream_progress([
            task(id=1, workstream_id=7, percent_complete=100),
            task(id=2, workstream_id=7, percent_complete=0),
            task(id=3, workstream_id=8, percent_complete=60),
        ])
        assert scored == {7: 50, 8: 60}


# ============================================================ the graph


class TestCycles:
    def _dep(self, a: int, b: int) -> control.DependencyView:
        return control.DependencyView("TASK", a, "TASK", b)

    def test_a_straight_chain_is_not_a_cycle(self):
        assert control.cycle([self._dep(1, 2), self._dep(2, 3)]) == []

    def test_a_loop_is_found_and_its_path_returned(self):
        """The path, not a boolean.

        "Cycle detected" makes somebody hunt through forty links. Naming them
        makes it a ten-second fix, and that difference is the whole reason
        this returns a list.
        """
        found = control.cycle([self._dep(1, 2), self._dep(2, 3),
                               self._dep(3, 1)])
        assert found
        assert {node for _kind, node in found} == {1, 2, 3}

    def test_a_self_link_is_a_cycle(self):
        assert control.cycle([self._dep(1, 1)])

    def test_a_diamond_is_not_a_cycle(self):
        """Two paths to the same place is a normal plan, and a naive
        visited-set implementation calls it a loop."""
        assert control.cycle([self._dep(1, 2), self._dep(1, 3),
                              self._dep(2, 4), self._dep(3, 4)]) == []

    def test_a_deep_chain_does_not_exhaust_the_stack(self):
        """Iterative, not recursive. A thousand-task chain is unusual and a
        RecursionError in a health calculation is a 500 on a dashboard."""
        chain = [self._dep(i, i + 1) for i in range(2000)]
        assert control.cycle(chain) == []


class TestBlocking:
    def test_it_reports_what_a_task_holds_up(self):
        graph = plan(
            tasks=[task(id=1, code="T-1"), task(id=2, code="T-2"),
                   task(id=3, code="T-3")],
            dependencies=[control.DependencyView("TASK", 1, "TASK", 2),
                          control.DependencyView("TASK", 1, "TASK", 3)])
        assert sorted(control.blocking(graph)[1]) == [2, 3]

    def test_downstream_follows_the_chain(self):
        graph = plan(
            tasks=[task(id=i, code=f"T-{i}") for i in (1, 2, 3)],
            dependencies=[control.DependencyView("TASK", 1, "TASK", 2),
                          control.DependencyView("TASK", 2, "TASK", 3)])
        assert set(control.downstream(graph, "TASK", 1)) == {("TASK", 2),
                                                             ("TASK", 3)}


# ============================================================ health


class TestHealth:
    def test_a_plan_with_no_dates_is_unknown_not_green(self):
        """The most important line in the engine.

        Green says "nothing is wrong". A project where nobody has written down
        what is meant to happen is not a project where nothing is wrong — it
        is one nobody can tell, and saying so is the only honest answer.
        """
        verdict = control.health(
            plan(tasks=[task(due_date=None)]), TODAY)
        assert verdict.status == "UNKNOWN"
        assert "not enough of a plan" in verdict.reason

    def test_an_empty_plan_is_unknown(self):
        assert control.health(plan(), TODAY).status == "UNKNOWN"

    def test_a_plan_on_track_is_green_and_says_so(self):
        verdict = control.health(plan(tasks=[
            task(id=1, due_date=TODAY + timedelta(days=30),
                 last_update_at=datetime(2026, 6, 14, tzinfo=UTC)),
        ]), TODAY)
        assert verdict.status == "GREEN"
        assert verdict.reason

    def test_one_overdue_critical_task_is_red(self):
        verdict = control.health(plan(tasks=[
            task(id=1, code="T-1", critical=True,
                 due_date=TODAY - timedelta(days=2)),
        ]), TODAY)
        assert verdict.status == "RED"
        assert "critical" in verdict.reason.lower()

    def test_a_single_ordinary_overdue_task_is_not_red(self):
        """Amber has to mean something. A product that goes red on one late
        task is one where everything is red and nobody looks."""
        verdict = control.health(plan(tasks=[
            task(id=1, due_date=TODAY - timedelta(days=1)),
            task(id=2, due_date=TODAY + timedelta(days=30)),
        ]), TODAY)
        assert verdict.status == "AMBER"

    def test_volume_alone_can_turn_it_amber(self):
        verdict = control.health(plan(tasks=[
            task(id=i, code=f"T-{i}", due_date=TODAY - timedelta(days=1))
            for i in range(1, 5)
        ]), TODAY)
        assert verdict.status in ("AMBER", "RED")
        assert "overdue" in verdict.reason

    def test_the_reason_does_not_count_the_same_task_twice(self):
        """A defect this engine had.

        A task that is overdue AND silent produced "1 task overdue ... 3
        near-term tasks without a recent update", making three tasks look like
        four problems — as misleading as making it look better.
        """
        overdue_and_quiet = [
            task(id=i, code=f"T-{i}", due_date=TODAY - timedelta(days=2),
                 last_update_at=None, percent_complete=0)
            for i in range(1, 4)
        ]
        verdict = control.health(plan(tasks=overdue_and_quiet), TODAY)
        counted = [int(word) for word in verdict.reason.replace(",", " ").split()
                   if word.isdigit()]
        assert all(n <= 3 for n in counted), verdict.reason

    def test_a_critical_open_raid_item_is_reported(self):
        verdict = control.health(plan(
            tasks=[task(id=1, due_date=TODAY + timedelta(days=30),
                        last_update_at=datetime(2026, 6, 14, tzinfo=UTC))],
            raid=[("CRITICAL", "OPEN", "The vendor has withdrawn")]), TODAY)
        assert verdict.status in ("AMBER", "RED")
        assert "vendor has withdrawn" in verdict.reason

    def test_a_closed_raid_item_is_not_reported(self):
        verdict = control.health(plan(
            tasks=[task(id=1, due_date=TODAY + timedelta(days=30),
                        last_update_at=datetime(2026, 6, 14, tzinfo=UTC))],
            raid=[("CRITICAL", "CLOSED", "Already dealt with")]), TODAY)
        assert "Already dealt with" not in verdict.reason

    def test_every_verdict_carries_its_findings(self):
        verdict = control.health(plan(tasks=[
            task(id=1, code="T-1", due_date=TODAY - timedelta(days=2)),
        ]), TODAY)
        assert verdict.findings
        assert all(f.detail for f in verdict.findings)

    def test_the_thresholds_are_policy_not_magic_numbers(self):
        """Changing the policy must change the VERDICT, not just the wording.

        This test found a real defect. `amber_overdue_count` used to select
        between two branches that both produced amber and nearly the same
        sentence, so the field was decoration — somebody tuning it would have
        seen nothing change and concluded the engine ignored them. It now
        governs when volume alone escalates to red, which is what its own
        docstring always claimed.
        """
        late = [task(id=i, code=f"T-{i}", due_date=TODAY - timedelta(days=1))
                for i in range(1, 4)]
        strict = control.health(plan(tasks=late), TODAY,
                                policy=control.Policy(amber_overdue_count=1))
        lenient = control.health(plan(tasks=late), TODAY,
                                 policy=control.Policy(amber_overdue_count=99))
        assert strict.status == "RED"
        assert lenient.status == "AMBER"

    def test_one_late_task_is_amber_whatever_the_threshold(self):
        """The floor under the threshold above.

        A product that stays green with a late commitment on it is one nobody
        believes about the second one. The threshold decides when volume
        becomes red; it never buys silence about a single miss.
        """
        one = [task(id=1, code="T-1", due_date=TODAY - timedelta(days=1)),
               task(id=2, code="T-2", due_date=TODAY + timedelta(days=30),
                    last_update_at=datetime(2026, 6, 14, tzinfo=UTC))]
        for count in (1, 3, 99):
            verdict = control.health(
                plan(tasks=one), TODAY,
                policy=control.Policy(amber_overdue_count=count))
            assert verdict.status in ("AMBER", "RED"), count
            assert "1 task overdue" in verdict.reason


# ============================================================ chasing


class TestChasing:
    def test_an_overdue_silent_task_produces_one_chase(self):
        chases = control.chase_findings(plan(tasks=[
            task(id=1, code="T-1", owner_id=9,
                 due_date=TODAY - timedelta(days=6),
                 last_update_at=datetime(2026, 6, 5, tzinfo=UTC)),
        ]), TODAY)
        assert len(chases) == 1
        assert chases[0].owner_id == 9
        assert "overdue" in chases[0].reason

    def test_a_task_with_no_owner_produces_no_chase(self):
        """There is nobody to ask. A chase addressed to nobody is a line on a
        list that never clears."""
        assert control.chase_findings(plan(tasks=[
            task(id=1, owner_id=None, due_date=TODAY - timedelta(days=6),
                 last_update_at=None)]), TODAY) == []

    def test_a_recently_updated_overdue_task_is_not_chased(self):
        """Somebody has just told you where it is. Asking again the same day
        is the behaviour that gets a notification channel muted."""
        assert control.chase_findings(plan(tasks=[
            task(id=1, owner_id=9, due_date=TODAY - timedelta(days=6),
                 last_update_at=datetime(2026, 6, 15, tzinfo=UTC))]),
            TODAY) == []

    def test_each_task_produces_at_most_one_chase(self):
        chases = control.chase_findings(plan(tasks=[
            task(id=1, code="T-1", owner_id=9, blocked=True,
                 blocker_reason="Waiting on Finance",
                 due_date=TODAY - timedelta(days=6), last_update_at=None),
        ]), TODAY)
        assert len(chases) == 1

    def test_a_closed_task_is_never_chased(self):
        assert control.chase_findings(plan(tasks=[
            task(id=1, status="COMPLETED", owner_id=9,
                 due_date=TODAY - timedelta(days=30),
                 last_update_at=None)]), TODAY) == []


# ============================================================ milestones


class TestMilestones:
    def milestone(self, **kw):
        base = {"id": kw.pop("id", 1), "code": kw.pop("code", "M-1"),
                "name": kw.pop("name", "A milestone"),
                "status": kw.pop("status", "PENDING")}
        return control.MilestoneView(**base, **kw)

    def test_a_missed_milestone_is_reported(self):
        findings = control.milestone_findings(plan(
            milestones=[self.milestone(
                target_date=TODAY - timedelta(days=3))]), TODAY)
        assert findings
        assert any("M-1" in f.entity_code for f in findings)

    def test_an_achieved_milestone_is_not_reported(self):
        assert control.milestone_findings(plan(
            milestones=[self.milestone(
                status="ACHIEVED", actual_date=TODAY - timedelta(days=3),
                target_date=TODAY - timedelta(days=5))]), TODAY) == []

    def test_a_milestone_with_no_date_is_not_late(self):
        """It cannot be. Reporting it as late would be inventing a
        commitment nobody made."""
        assert control.milestone_findings(plan(
            milestones=[self.milestone(target_date=None)]), TODAY) == []


# ============================================================ time itself


@pytest.mark.parametrize("day", [
    date(2026, 1, 1), date(2026, 2, 28), date(2028, 2, 29),
    date(2026, 12, 31),
])
def test_the_engine_has_no_opinion_about_the_calendar(day):
    """Month ends, year ends and a leap day.

    Nothing here does date arithmetic by hand, and this is what keeps it that
    way: the first person to write `day + 30` instead of a timedelta breaks
    one of these.
    """
    verdict = control.health(plan(tasks=[
        task(id=1, due_date=day - timedelta(days=1)),
        task(id=2, due_date=day + timedelta(days=1)),
    ]), day)
    assert verdict.status in ("GREEN", "AMBER", "RED")
    assert verdict.reason
