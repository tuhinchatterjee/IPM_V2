"""
A question must be answered as asked: the same conditions, the same period,
the same kind of answer.

Three live defects, one theme
-----------------------------
    "…had expected credit loss rise in Q1 2026"   ->  total_ecl_change > 2026
    "…rising utilisation, worsening liquidity…"   ->  a sector EAD movement
    "…were downgraded…"                           ->  rows not showing a downgrade

All three produce a plan that runs, a query that succeeds and invariants that
pass. The first returns an empty population that reads as a finding; the second
returns a real analysis of a different question; the third returns rows a reader
cannot check. None of them looks like a failure from the inside, which is why
each needs a test that looks from the outside.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.orchestration import analysis_planner as ap
from backend.orchestration import context as gc
from backend.orchestration import fidelity as fid
from backend.orchestration import invariants as inv
from backend.orchestration import semantics as sm
from backend.orchestration import temporal as tm


def _planned(question: str) -> ap.AnalysisBuild:
    from backend.orchestration import router

    context = gc.retrieve(question)
    reading = router.read(question).reading
    return ap.plan(reading, context, question=question)


# ==========================================================================
# A period is a type, not a number
# ==========================================================================


class TestTimeIsNeverAMagnitude:
    """The live defect: "ECL rise in Q1 2026" became "ECL rose > 2026"."""

    @pytest.mark.parametrize("said,expected", [
        ("Q1 2026", ("Q1 2026",)),
        ("q3 2025", ("q3 2025",)),
        ("2026", ("2026",)),
        ("FY2026", ("FY2026",)),
        ("CY 2025", ("CY 2025",)),
        ("March 2026", ("March 2026",)),
        ("2026-03", ("2026-03",)),
        ("H1 2026", ("H1 2026",)),
        ("between Q1 2026 and Q2 2026", ("between Q1 2026 and Q2 2026",)),
        ("the last four quarters", ("the last four quarters",)),
        ("year on year", ("year on year",)),
        ("over the next 12 months", ("over the next 12 months",)),
        ("this quarter", ("this quarter",)),
        ("since 2024", ("since 2024",)),
    ])
    def test_a_period_is_read_as_a_period(self, said: str,
                                          expected: tuple[str, ...]) -> None:
        assert tm.read(said).texts() == expected

    @pytest.mark.parametrize("said", [
        "exposure above 2500",
        "12-month PD above 5%",
        "leverage above 3x",
        "headroom below 15%",
        "more than 250 borrowers",
        "IFRS 9 stage 2",
        "days past due above 90",
    ])
    def test_a_quantity_is_not_read_as_a_period(self, said: str) -> None:
        assert not tm.read(said).any, (
            f"{said!r} had part of it read as a date, which would remove it "
            "from the threshold the question actually set")

    def test_the_live_defect_no_longer_reproduces(self) -> None:
        found = sm.find_movement("had expected credit loss rise in Q1 2026")
        assert found is not None
        assert found.value == 0.0, (
            "the reporting period became the size of the movement — the "
            "question asked for any rise in Q1 2026 and the plan asked for a "
            "rise of more than two thousand and twenty-six")

    def test_a_real_magnitude_beside_a_period_survives(self) -> None:
        # The pair to the test above. Masking time must not eat the threshold.
        found = sm.find_movement("ECL rose more than 20% in Q1 2026")
        assert found is not None
        assert found.value == 20.0
        assert found.unit == "pct"

    def test_a_threshold_beside_a_period_survives(self) -> None:
        found = sm.find_threshold("covenant headroom below 15% in Q1 2026")
        assert found is not None
        assert (found.op, found.value) == ("lt", 15.0)

    def test_a_period_alone_sets_no_threshold(self) -> None:
        assert sm.find_threshold("ECL above 2026") is None, (
            "a bare year was read as a level to compare a measure against"
        )

    def test_the_planned_condition_carries_no_year(self) -> None:
        build = _planned("Which customers were downgraded and had expected "
                         "credit loss rise in Q1 2026?")
        for condition in build.conditions:
            assert abs(float(condition.value)) < 1900, (
                f"{condition.field} was given a threshold of {condition.value}, "
                "which is a calendar year rather than a size of movement")

    def test_the_named_quarter_becomes_the_window(self) -> None:
        build = _planned("Which customers were downgraded and had expected "
                         "credit loss rise in Q1 2026?")
        assert build.closing == "Q1 2026", (
            "the question named a quarter and the analysis measured a "
            "different one")


# ==========================================================================
# The objective may not change
# ==========================================================================


class TestTheObjectiveIsPreserved:
    @pytest.mark.parametrize("question,objective", [
        ("Which Shipping borrowers have rising utilisation, worsening "
         "liquidity, and increasing 12-month PD?", fid.POPULATION),
        ("Which customers were downgraded?", fid.POPULATION),
        ("What is total exposure at default by sector?", fid.AGGREGATE),
        ("How did ECL move between Q1 2026 and Q2 2026?", fid.MOVEMENT),
        ("Is utilisation correlated with days past due?", fid.ASSOCIATION),
    ])
    def test_the_question_declares_what_kind_of_answer_it_wants(
            self, question: str, objective: str) -> None:
        assert fid.objective_of(question) == objective

    def test_a_population_question_is_not_answered_with_a_movement(self) -> None:
        """The Shipping defect, tested at the mechanism.

        An exposure-at-default movement for Transport & Logistics is a real
        analysis and a correct one; it is simply not the answer to "which
        Shipping borrowers meet these three conditions". Nothing in the
        predicate machinery can see the difference, because a plan that
        abandoned the question has no predicates to be missing.
        """
        contract = fid.read("Which Shipping borrowers have rising "
                            "utilisation, worsening liquidity, and increasing "
                            "12-month PD?")

        class Substituted:
            shape = "movement"
            conditions: list[Any] = []
            filters = [("sector", "Transport & Logistics")]
            opening = "Q2 2025"
            closing = "Q2 2026"
            period = ""

        verdict = fid.compare(contract, Substituted())
        assert not verdict.faithful
        kinds = {d.kind for d in verdict.divergences}
        assert fid.OBJECTIVE_CHANGED in kinds
        assert fid.POPULATION_LOST in kinds
        assert "does not answer one question with another" in verdict.sentence

    def test_a_ranking_of_the_right_population_is_not_a_substitution(
            self) -> None:
        # A ranked list of the borrowers meeting the conditions is still those
        # borrowers. Ordering is presentation, and flagging it would make the
        # gate cry wolf on the ordinary case.
        contract = fid.read("Which borrowers were downgraded?")

        class Ranked:
            shape = "ranking"
            conditions: list[Any] = []
            filters: list[Any] = []
            opening = ""
            closing = ""
            period = "Q2 2026"

        assert fid.compare(contract, Ranked()).faithful

    def test_the_shipping_question_is_answered_as_asked(self) -> None:
        build = _planned("Which Shipping borrowers have rising utilisation, "
                         "worsening liquidity, and increasing 12-month PD?")
        assert build.fidelity is not None
        assert build.fidelity.faithful, build.fidelity.sentence
        assert build.fidelity.contract.objective == fid.POPULATION
        assert build.fidelity.executed_objective == fid.POPULATION
        assert ("sector", "Shipping") in build.filters, (
            "the question is about Shipping and the plan did not restrict to "
            "it")

    def test_every_predicate_of_the_shipping_question_is_enforced(self) -> None:
        from backend.orchestration import gate

        build = _planned("Which Shipping borrowers have rising utilisation, "
                         "worsening liquidity, and increasing 12-month PD?")
        tested = gate.enforced_columns(build.plan)
        for wanted in ("utilisation_pct", "liquidity_coverage_months",
                       "pd_12m_pct", "sector"):
            assert any(wanted in column for column in tested), (
                f"{wanted} is not filtered on, so the answer is wider than "
                "the question")

    def test_the_contract_is_recorded_on_the_build(self) -> None:
        build = _planned("Which customers were downgraded and had expected "
                         "credit loss rise in Q1 2026?")
        recorded = build.to_dict()["fidelity"]
        assert recorded is not None
        assert recorded["contract"]["question"]
        assert recorded["contract"]["objective"] == fid.POPULATION
        assert recorded["contract"]["period"] == ["Q1 2026"]
        assert recorded["faithful"] is True


# ==========================================================================
# The rows must prove the predicate
# ==========================================================================


class TestRowsProveTheirPredicates:
    QUESTION = ("Which customers were downgraded and had expected credit "
                "loss rise in Q1 2026?")

    @pytest.fixture(scope="class")
    @classmethod
    def answered(cls) -> Any:
        from backend.orchestration.executor import answer_investigation

        try:
            _, found = answer_investigation(cls.QUESTION, persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the governed runtime is not available: {exc}")
        if getattr(found, "runtime", None) is None:
            pytest.skip("the question did not reach the runtime in this build")
        return found

    def test_a_movement_predicate_is_checked_on_its_own_positions(
            self, answered: Any) -> None:
        checks = inv.compile_checks(answered.build, self.QUESTION)
        positions = [c for c in checks if c.rule == "position_movement"]
        assert positions, (
            "no check compares the opening and closing positions, so a row "
            "claiming a downgrade is only ever checked against the derived "
            "change column it was filtered on")
        assert any("downgrad" in c.params.get("label", "") for c in positions)

    def test_every_returned_row_shows_the_downgrade(self, answered: Any) -> None:
        rows = list(answered.runtime.rows)
        if not rows:
            pytest.skip("the cohort is empty in this build")
        opening = "customer_ratings_internal_grade"
        closing = f"closing_{opening}"
        assert opening in rows[0] and closing in rows[0], (
            "the answer does not carry the two ratings, so a reader cannot "
            "check the predicate it claims")
        offending = [r for r in rows
                     if not (r.get(closing) is not None
                             and r.get(opening) is not None
                             and float(r[closing]) > float(r[opening]))]
        assert not offending, (
            f"{len(offending)} rows claim a downgrade without showing one — "
            f"the first is {offending[0].get('customer_id')} at "
            f"{offending[0].get(opening)} -> {offending[0].get(closing)}")

    def test_the_evidence_columns_are_visible(self, answered: Any) -> None:
        from backend.orchestration import presentation as pres

        labels = [c["label"] for c in
                  pres.contract(answered.runtime, answered.build)
                  if not c["hidden"]]
        for wanted in ("Internal rating at", "Change in Internal rating",
                       "Expected credit loss at",
                       "Change in Expected credit loss"):
            assert any(wanted in label for label in labels), (
                f"{wanted!r} is not shown, so the predicate cannot be checked "
                "from the table")

    def test_the_invariants_pass_on_the_real_result(self, answered: Any) -> None:
        report = inv.verify(
            inv.compile_checks(answered.build, self.QUESTION),
            answered.runtime)
        assert report.ok, [f.detail for f in report.failures]


class TestThePositionCheckCatchesAContradiction:
    """The check has to be able to FAIL, or it proves nothing."""

    @staticmethod
    def _check() -> inv.Check:
        return inv.Check(
            rule="position_movement",
            claim="every row shows the downgrade",
            columns=("grade", "closing_grade"),
            params={"opening": "grade", "closing": "closing_grade",
                    "op": "gt", "label": "internal rating was downgraded"})

    def test_a_row_whose_positions_agree_passes(self) -> None:
        rows = [{"grade": 3.0, "closing_grade": 4.0}]
        assert inv._position_movement(self._check(), rows, None) is None

    def test_a_row_whose_positions_do_not_move_fails(self) -> None:
        rows = [{"grade": 4.0, "closing_grade": 4.0}]
        found = inv._position_movement(self._check(), rows, None)
        assert found is not None
        assert "internal rating was downgraded" in found.detail

    def test_a_row_that_improved_fails(self) -> None:
        rows = [{"grade": 5.0, "closing_grade": 3.0}]
        assert inv._position_movement(self._check(), rows, None) is not None

    def test_a_result_missing_the_positions_is_not_a_row_failure(self) -> None:
        # A missing column is a presentation gap, not a wrong row, and
        # reporting it here would withhold a correct answer over a display
        # decision.
        rows = [{"something_else": 1.0}]
        assert inv._position_movement(self._check(), rows, None) is None
