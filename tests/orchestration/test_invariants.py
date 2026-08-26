"""
The check that makes the covenant contradiction impossible.

A release shipped an answer to

    "Which large Real Estate customers have worsening DPD, increasing ECL, a
     rating downgrade and covenant headroom below 15%?"

with a borrower at 16.17% headroom in it. One parse had gone wrong. The parse
is fixed — and a product whose correctness depends on every parse being right
will print this again next quarter under a different heading, so the claim is
now checked against the result before anybody sees it.

These tests are mostly about the negative case. A check that has never been
seen to fail is a check nobody should trust, so each rule is given a result
that violates it and asserted to block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.orchestration import invariants as inv

# --------------------------------------------------------------- fake results


@dataclass
class FakeRuntime:
    rows: list[dict[str, Any]]
    columns: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0

    def __post_init__(self) -> None:
        if not self.columns and self.rows:
            self.columns = [{"name": k} for k in self.rows[0]]
        if not self.row_count:
            self.row_count = len(self.rows)


@dataclass
class FakeConcept:
    id: str
    label: str = ""
    higher_is_worse: bool = True
    is_ordinal: bool = False


@dataclass
class FakeMatch:
    concept: FakeConcept
    field: str


@dataclass
class FakeCondition:
    column: str
    kind: str
    op: str
    value: float
    field: str = ""


@dataclass
class FakeBuild:
    shape: str = "cohort"
    top_n: int = 0
    filters: list[tuple[str, str]] = field(default_factory=list)
    conditions: list[FakeCondition] = field(default_factory=list)
    matches: list[FakeMatch] = field(default_factory=list)
    grain: str = "customer"
    plan: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ the cases


def test_the_covenant_contradiction_is_blocked():
    """The exact failure, reproduced as a result and refused.

    A threshold of 15% and a row at 16.17. The figures may all be correctly
    computed; the answer still does not match the question, and a table whose
    rows contradict its own heading must not reach a credit officer.
    """
    build = FakeBuild(
        filters=[("sector", "Real Estate")],
        conditions=[FakeCondition(column="headroom_pct", kind="level",
                                  op="lt", value=15.0)])
    runtime = FakeRuntime(rows=[
        {"customer_id": "SA-1", "sector": "Real Estate", "headroom_pct": 13.81},
        {"customer_id": "SA-2", "sector": "Real Estate", "headroom_pct": 16.17},
    ])

    report = inv.check_result(build, runtime, "…headroom below 15%?")

    assert not report.ok
    failure = report.failures[0]
    assert failure.check.rule == "condition"
    assert "16.17" in failure.detail
    assert failure.example["customer_id"] == "SA-2"
    assert "not showing it" in report.sentence()


def test_a_result_that_matches_the_question_is_not_blocked():
    build = FakeBuild(
        filters=[("sector", "Real Estate")],
        conditions=[FakeCondition(column="headroom_pct", kind="level",
                                  op="lt", value=15.0)])
    runtime = FakeRuntime(rows=[
        {"customer_id": "SA-1", "sector": "Real Estate", "headroom_pct": 13.81},
        {"customer_id": "SA-3", "sector": "Real Estate", "headroom_pct": 6.34},
    ])

    report = inv.check_result(build, runtime, "…headroom below 15%?")

    assert report.ok
    assert report.checks, "a passing report must still say what it checked"
    assert report.sentence() == ""


def test_a_filter_that_did_not_hold_is_caught():
    """"Only Real Estate" with a Contracting row in it."""
    build = FakeBuild(filters=[("sector", "Real Estate")])
    runtime = FakeRuntime(rows=[
        {"customer_id": "SA-1", "sector": "Real Estate"},
        {"customer_id": "SA-2", "sector": "Contracting"},
    ])

    report = inv.check_result(build, runtime, "Real Estate customers")

    assert not report.ok
    assert report.failures[0].check.rule == "filter_equality"
    assert "Contracting" in report.failures[0].detail


def test_more_rows_than_the_question_asked_for_is_caught():
    build = FakeBuild(top_n=5)
    runtime = FakeRuntime(
        rows=[{"customer_id": f"SA-{i}"} for i in range(8)], row_count=8)

    report = inv.check_result(build, runtime, "the five largest")

    assert not report.ok
    assert report.failures[0].check.rule == "row_limit"
    assert "5" in report.failures[0].detail and "8" in report.failures[0].detail


def test_a_movement_that_went_the_other_way_is_caught():
    """"ECL rose" with a row where it fell."""
    build = FakeBuild(conditions=[
        FakeCondition(column="total_ecl_change", kind="change_abs", op="gt",
                      value=0.0, field="total_ecl")])
    runtime = FakeRuntime(rows=[
        {"customer_id": "SA-1", "total_ecl_change": 0.62},
        {"customer_id": "SA-2", "total_ecl_change": -0.10},
    ])

    report = inv.check_result(build, runtime, "an increase in ECL")

    assert not report.ok
    assert report.failures[0].example["customer_id"] == "SA-2"


def test_a_share_larger_than_its_own_total_is_caught():
    build = FakeBuild(shape="share_movement")
    runtime = FakeRuntime(rows=[{
        "sector": "Contracting",
        "opening_qualified": 200.0, "opening_total": 100.0,
        "closing_qualified": 50.0, "closing_total": 100.0,
        "opening_share_pct": 200.0, "closing_share_pct": 50.0,
    }])

    report = inv.check_result(build, runtime, "Stage 2 EAD over total EAD")

    rules = {f.check.rule for f in report.failures}
    assert "numerator_within_denominator" in rules
    assert "share_bounds" in rules


def test_a_negative_exposure_is_caught():
    build = FakeBuild(matches=[FakeMatch(FakeConcept(id="ecl"), "total_ecl")])
    runtime = FakeRuntime(rows=[{"customer_id": "SA-1", "total_ecl": -4.2}])

    report = inv.check_result(build, runtime, "expected credit loss")

    assert not report.ok
    assert report.failures[0].check.rule == "non_negative"


def test_a_rating_outside_the_governed_scale_is_caught():
    build = FakeBuild(matches=[
        FakeMatch(FakeConcept(id="rating", is_ordinal=True), "internal_grade")])
    runtime = FakeRuntime(rows=[{"customer_id": "SA-1", "internal_grade": 14}])

    report = inv.check_result(build, runtime, "internal rating")

    assert not report.ok
    assert report.failures[0].check.rule == "ordinal_range"


def test_a_check_whose_column_is_absent_is_skipped_not_failed():
    """A missing column is a limit on what could be verified, not a failure.

    Failing here would block correct answers whenever a plan reports a
    condition under a different column name — which turns the gate from a
    safeguard into an outage.
    """
    build = FakeBuild(filters=[("region", "Riyadh")])
    runtime = FakeRuntime(rows=[{"customer_id": "SA-1", "sector": "Real Estate"}])

    report = inv.check_result(build, runtime, "in Riyadh")

    assert report.ok
    assert report.skipped and "region" in report.skipped[0]


def test_duplicate_identities_are_caught_where_the_question_promised_one_row():
    build = FakeBuild(grain="customer")
    runtime = FakeRuntime(rows=[
        {"customer_id": "SA-1", "ead": 10.0},
        {"customer_id": "SA-1", "ead": 12.0},
    ])

    report = inv.check_result(build, runtime, "one row per customer")

    assert not report.ok
    assert report.failures[0].check.rule == "unique_key"


def test_floating_point_noise_does_not_block_a_correct_answer():
    """14.999999999999998 is below 15, and a gate that says otherwise is worse
    than no gate: it blocks right answers and teaches people to override it."""
    build = FakeBuild(conditions=[
        FakeCondition(column="headroom_pct", kind="level", op="lt", value=15.0)])
    runtime = FakeRuntime(rows=[{"headroom_pct": 14.999999999999998}])

    assert inv.check_result(build, runtime, "below 15%").ok


# ----------------------------------------------------------- through the path


@pytest.fixture(scope="module")
def require_data():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


def test_the_covenant_thread_now_satisfies_its_own_threshold(require_data):
    """The regression case, end to end through the real path."""
    from backend.orchestration.executor import answer_investigation

    question = ("Which large Real Estate customers have worsening DPD, "
                "increasing ECL, a rating downgrade and covenant headroom "
                "below 15%?")
    investigation, answered = answer_investigation(question, persist=False)

    assert investigation.status == "succeeded", answered.failure
    rows = (investigation.steps[0].result or {}).get("rows") or []
    assert rows, "the case is only meaningful if it returns rows"
    for row in rows:
        assert float(row["covenant_tests_headroom_pct"]) < 15.0
        assert row["sector"] == "Real Estate"

    report = answered.invariants
    assert report is not None and report.ok
    assert any("headroom" in c.claim for c in report.checks), (
        "the threshold has to be among the things actually checked")


def test_every_answer_records_what_it_checked(require_data):
    """Including the ones where everything held.

    A node that appears only on failure teaches users that its presence is bad
    news, which makes its absence — the thing they would need to notice —
    invisible.
    """
    from backend.orchestration.executor import answer_investigation

    investigation, answered = answer_investigation(
        "Show me the ten largest customers by exposure at default.",
        persist=False)

    assert investigation.status == "succeeded"
    assert answered.invariants is not None
    assert answered.invariants.checks
    recorded = investigation.conversation.get("invariants") or {}
    assert recorded.get("ok") is True
    assert recorded.get("checked")
