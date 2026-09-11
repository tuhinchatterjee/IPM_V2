"""What the work list puts first, and how it says when somebody was chased.

Both claims here came out of using the running product rather than reading
the code. On the real Project Planner home page, signed in as an
administrator, the first six rows of **Needs attention** read:

    CRITICAL … D-202 Inconsistent cure dates … due to start 60 days ago
    CRITICAL … D-501 Origination score history … due to start 50 days ago
    CRITICAL … T-301 LGD workout data extraction is 12 days overdue
    CRITICAL … M-6  Month-End Posting is due in 12 days          ← ahead of
    CRITICAL … D-201 Missing default dates is 12 days overdue    ← this
    CRITICAL … M-5  CRO Sign-off is due in 10 days

Two things are wrong with that, and both mislead the person reading it:

  * something due in twelve days was ranked above something twelve days
    LATE, because the old ranking sorted on severity and then on the
    finding's number without asking what the number counted;
  * inside the due-soon group, twelve days away outranked ten days away, for
    the same reason.

And every row ended with `2026-09-11T10:01:31.754497+00:00`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.planner import control
from backend.planner.query import _urgency, _when_said


class Finding:
    """Just enough of a finding for the ranking to read."""

    def __init__(self, rule: str, severity: str, value: float | None,
                 entity_id: int = 1) -> None:
        self.rule = rule
        self.severity = severity
        self.value = value
        self.entity_id = entity_id


def order(*findings: Finding) -> list[str]:
    return [f"{f.rule}:{f.severity}:{f.value}"
            for f in sorted(findings, key=_urgency)]


# ------------------------------------------------------------- what comes first


def test_something_late_outranks_something_merely_approaching():
    """The defect as UAT saw it: "due in 12 days" above "12 days overdue"."""
    late = Finding("overdue", control.CRITICAL, 12)
    soon = Finding("due_soon", control.CRITICAL, 12)
    assert order(soon, late) == ["overdue:critical:12", "due_soon:critical:12"]


def test_the_more_overdue_item_comes_first():
    assert order(Finding("overdue", control.CRITICAL, 3),
                 Finding("overdue", control.CRITICAL, 30)) == [
        "overdue:critical:30", "overdue:critical:3"]


def test_the_sooner_due_item_comes_first_within_its_own_band():
    """Days REMAINING counts the other way round from days elapsed.

    Sorting both with the same sign is what put "due in 12 days" above "due
    in 10 days" on the real screen.
    """
    assert order(Finding("due_soon", control.WARN, 12),
                 Finding("due_soon", control.WARN, 2)) == [
        "due_soon:warn:2", "due_soon:warn:12"]


def test_the_bands_are_in_the_order_a_person_works_them():
    """Critical overdue, then schedule risk, then blocked, then the rest."""
    rows = [
        Finding("stale", control.WARN, 8),
        Finding("due_soon", control.WARN, 2),
        Finding("overdue", control.WARN, 3),
        Finding("blocked", control.CRITICAL, None),
        Finding("dependency", control.CRITICAL, 60),
        Finding("overdue", control.CRITICAL, 12),
    ]
    assert [row.split(":")[0] for row in order(*rows)] == [
        "overdue",     # critical and already late
        "dependency",  # the schedule behind it is at risk
        "blocked",     # stuck, and somebody has to unstick it
        "overdue",     # late, but not on the critical path
        "due_soon",
        "stale",
    ]


def test_two_equally_urgent_rows_do_not_swap_places():
    """A list that reorders itself between two loads cannot be worked."""
    rows = [Finding("overdue", control.CRITICAL, 5, entity_id=n)
            for n in (7, 2, 9)]
    assert order(*rows) == order(*reversed(rows))


def test_an_unknown_rule_sorts_last_rather_than_first():
    """A new rule must not silently jump the queue before anybody reviews it."""
    assert order(Finding("brand_new_rule", control.CRITICAL, 99),
                 Finding("stale", control.WARN, 1))[-1].startswith(
                     "brand_new_rule")


# ------------------------------------------------------- how the date reads


@pytest.mark.parametrize("days,expected", [
    (0, "today"),
    (1, "yesterday"),
    (3, "3 days ago"),
])
def test_a_recent_chase_is_described_the_way_people_speak(days, expected):
    assert _when_said(datetime.now(UTC) - timedelta(days=days)) == expected


def test_an_older_chase_gives_a_readable_date_and_no_machine_noise():
    said = _when_said(datetime.now(UTC) - timedelta(days=40))
    assert said.startswith("on ")
    for machine in ("T", ":", "+00:00", "."):
        assert machine not in said.replace("on ", ""), (
            f"{said!r} still reads like a timestamp")


def test_a_missing_time_says_so_rather_than_pretending():
    assert _when_said(None) == "at an unrecorded time"
