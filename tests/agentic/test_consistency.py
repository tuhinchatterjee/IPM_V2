"""
P0.9 — a Trace that says what actually happened.

The defect: a Trace showing 0 governed analyses, no assurance pass, a FAILED
Result stage, and — at the same time — "VALIDATED · 4 of 4 checks passed".
Every statement came from a different piece of code reading a different thing,
and none of them asked whether an analysis had happened.

    SKIPPED IS NOT PASS.
    FAILURE ROLLS UP.
"""

from __future__ import annotations

import pytest

from backend.agentic import consistency as cy


def _stage(stages, name):
    return next((s for s in stages if s.stage == name), None)


# ------------------------------------------------------------- derived status


def test_a_run_that_computed_nothing_is_not_analysed():
    stages = cy.derive(cy.Evidence())
    assert _stage(stages, cy.ANALYSED).state == cy.NOT_RUN


def test_a_check_that_did_not_run_is_not_a_check_that_passed():
    """The exact sentence on the screenshot. There were no checks."""
    validated = _stage(cy.derive(cy.Evidence(analyses=1, results=1)),
                       cy.VALIDATED)
    assert validated.state == cy.NOT_RUN
    assert "no validation check ran" in validated.because.lower()


def test_a_failed_step_fails_its_stage():
    """A green summary over a red step is what makes a Trace worse than no
    Trace: it is confidently wrong."""
    stages = cy.derive(cy.Evidence(failures=2))
    assert _stage(stages, cy.ANALYSED).state == cy.FAIL
    assert cy.failed(stages)


def test_a_declared_no_analysis_is_not_the_same_as_nothing_happening():
    """A metadata lookup legitimately runs no analysis. Saying so is a
    different fact from leaving the stage empty, and the two must not read the
    same on screen."""
    stages = cy.derive(cy.Evidence(results=1, no_analysis_declared=True))
    assert _stage(stages, cy.ANALYSED).state == cy.NOT_APPLICABLE


def test_a_failing_check_fails_validation_rather_than_reducing_the_count():
    stages = cy.derive(cy.Evidence(analyses=1, results=1, checks_run=4,
                                   checks_passed=3, checks_failed=1))
    assert _stage(stages, cy.VALIDATED).state == cy.FAIL


# ----------------------------------------------------------------- the ceiling


def test_the_ceiling_lowers_a_claim_the_evidence_does_not_support():
    broken = cy.Evidence(failures=1)
    status, why = cy.permit("HIGH ASSURANCE", broken)
    assert status == "NEEDS REVIEW"
    assert "failed" in why.lower()


def test_a_run_with_no_checks_cannot_claim_validation():
    """SKIPPED is not PASS, as a ceiling rather than as a label."""
    status, why = cy.permit("HIGH ASSURANCE",
                            cy.Evidence(analyses=1, results=1))
    assert status == "LIMITED EVIDENCE"
    assert "did not run" in why.lower() or "no validation" in why.lower()


@pytest.mark.parametrize("claim", ["HIGH ASSURANCE", "VALIDATED", "PASS",
                                   "GREEN", "anything at all", ""])
def test_an_unrecognised_claim_is_lowered_rather_than_waved_through(claim):
    """The ceiling ranked an unknown status as the WEAKEST, so it compared as
    already-lower than any ceiling and passed through untouched: a caller who
    invented a label bypassed the check entirely, which is the exact opposite
    of safe.

    Found by the P0.16 thread that forces an agent task failure — the one case
    where the ceiling matters most was the one it did not cover."""
    assert cy.permit(claim, cy.Evidence(failures=1))[0] == "NEEDS REVIEW"


def test_an_honest_claim_is_untouched():
    """A ceiling that lowered every claim would be a constant. A component
    whose own reasoning was already honest has to see no change."""
    sound = cy.Evidence(analyses=2, results=2, checks_run=3, checks_passed=3,
                        conclusion_grounded=True, actions=1, answer_only=False)
    assert cy.permit("VALIDATED", sound) == ("VALIDATED", "")
    assert cy.permit("HIGH ASSURANCE", sound) == ("HIGH ASSURANCE", "")


def test_the_ceiling_never_raises_a_claim():
    """It is a ceiling, not a dial. Promoting a modest claim would make the
    check a source of confidence rather than a limit on it."""
    sound = cy.Evidence(analyses=2, results=2, checks_run=3, checks_passed=3,
                        conclusion_grounded=True, actions=1, answer_only=False)
    assert cy.permit("LIMITED EVIDENCE", sound)[0] == "LIMITED EVIDENCE"
    assert cy.permit("NEEDS REVIEW", sound)[0] == "NEEDS REVIEW"


# ------------------------------------------------------------ what it reports


def test_the_parts_describe_what_actually_ran():
    said = cy.parts(cy.Evidence(analyses=1, results=1, checks_run=3,
                                checks_passed=3))
    joined = " ".join(said).lower()
    assert "1 calculation" in joined
    assert "3 checks" in joined


def test_the_parts_never_claim_a_check_that_did_not_run():
    joined = " ".join(cy.parts(cy.Evidence(analyses=1, results=1))).lower()
    assert "passed" not in joined
