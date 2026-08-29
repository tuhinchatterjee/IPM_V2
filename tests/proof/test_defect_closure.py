"""
§3: the defects that were OPEN at `e967c6a`, asserted closed.

One test per defect, named after it, so a regression names the defect it
brought back rather than reporting an anonymous assertion failure. Each drives
the real governed path; none asserts on a regex.

The rule this phase works under:

    "Do not clear a defect merely because an invariant blocks the answer.
     Containment is not the same as correction."

So every assertion here is about the CORRECTED behaviour — the review reports
its datasets, the officer level matches the work, the risk class has cases —
rather than about a gate having caught something.
"""

from __future__ import annotations

import pytest

from backend.proof.probe import assert_no_provider_calls, run_probe
from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="closing these defects needs the platform database")


def _lake() -> bool:
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    try:
        return FACILITY in get_data_source().datasets()
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def _needs_the_lake():
    if not _lake():
        pytest.skip("these probes need the analytical lake")


def _probe(question: str):
    with assert_no_provider_calls():
        return run_probe(question, user_id=1)


@pytest.fixture(scope="module")
def review():
    with assert_no_provider_calls():
        return run_probe("Review the latest portfolio and tell me everything "
                         "that matters.", user_id=1)


# ------------------------------------------------------------------ D4 / D19


def test_d4_a_broad_investigation_executes_governed_analyses(review):
    """D4: both broad investigations reported `executed = false`,
    `datasets = 0`, `plan_steps = 0`.

    They were running six governed probes the whole time. Nothing recorded it,
    because the composed answer kept the headline of each sub-answer and threw
    the sub-answer away.
    """
    probe, answered = review

    assert probe.error == "", probe.error
    composition = answered.answered.composition
    assert composition is not None, (
        "a broad investigation left no composition record")
    assert composition.ran >= 3, composition.to_dict()
    assert composition.ran == composition.attempted or composition.ran > 0
    assert probe.executed is True, (
        "a review that ran governed analyses still reports executing nothing")


def test_d19_the_review_reports_what_its_sub_analyses_read(review):
    """D19: the Trace for a portfolio review could not say which data it
    read."""
    probe, answered = review
    composition = answered.answered.composition

    assert composition.datasets, "the review reports no datasets"
    assert composition.periods, "the review reports no periods"
    assert composition.grains, "the review reports no grains"
    assert probe.datasets == sorted(composition.datasets)


def test_d19_every_sub_analysis_went_through_the_governed_path(review):
    """A composition that counted analyses without counting how they ran
    would be a bigger claim on the same absence of evidence."""
    _, answered = review
    composition = answered.answered.composition

    assert composition.ir_validated == composition.ran
    assert composition.queries_compiled == composition.ran
    assert composition.governed_reads == composition.ran


def test_d20_the_review_registers_evidence_facts(review):
    """D20: a coordinated review registered zero evidence facts, so nothing
    in its synthesis was grounded against a fact."""
    _, answered = review
    composition = answered.answered.composition
    judgment = answered.answered.judgment or {}

    assert composition.facts_registered > 0
    assert judgment.get("facts", {}).get("registered", 0) > 0, (
        "the judgment layer still reports no facts for a composed answer")
    assert judgment["facts"].get("composed_from") == composition.ran


# ------------------------------------------------------------------ D5 / D7


def test_d5_a_catalogue_answer_says_which_catalogue_it_read():
    """D5: "what ratings data do you have?" reported zero datasets, so it was
    filed as a conversational turn and could not be checked against the
    catalogue."""
    from backend.proof import flows as fl

    probe, _ = _probe("What ratings data do you have?")

    assert probe.error == "", probe.error
    assert probe.datasets, "a catalogue answer names no catalogue"
    assert probe.flow == fl.METADATA
    # It consulted metadata; it did not read rows, and says neither more nor
    # less than that.
    assert probe.rows_returned is None
    assert probe.executed is False


def test_d7_an_executed_analysis_reports_whether_its_invariants_held():
    """D7: invariants passed on none of the executed analyses — reported as
    0%, over runs where five checks had been compiled and all five held.

    The report says `ok`. The probe read `passed`, which is on no invariant
    report anywhere.
    """
    probe, answered = _probe("Show IFRS 9 ECL by sector for the latest "
                             "quarter.")

    report = answered.answered.invariants
    assert report is not None and report.checks, (
        "no invariants were compiled for an executed analysis")
    assert report.ok is True, [f.detail for f in report.failures]
    assert probe.invariants_passed is True


def test_d7_a_turn_that_checked_nothing_reports_none_not_false():
    """A check that did not run is not a check that failed. Collapsing the
    two is how "0% invariants passed" was true and meaningless at once."""
    probe, _ = _probe("What ratings data do you have?")

    assert probe.invariants_passed is None


# ------------------------------------------------------------------ D6 / D17


def test_d6_a_borrower_grain_comparison_is_a_senior_credit_officer():
    """D6: this came out as a Portfolio Risk Lead. It scores 10 — three
    datasets, four concepts, two periods, a migration, two domains, two
    specialists — and 10 clears the level-3 floor. None of that makes it
    portfolio work."""
    probe, _ = _probe("Which customers had a rating downgrade and an increase "
                      "in ECL over the latest year?")

    assert probe.error == "", probe.error
    assert probe.officer_level == 2, probe.officer_reason


def test_d6_a_segment_investigation_is_still_a_portfolio_risk_lead():
    """The ceiling must not demote the level the grain earns."""
    probe, _ = _probe("Something seems wrong with Contracting. Investigate "
                      "it.")

    assert probe.error == "", probe.error
    assert (probe.officer_level or 0) >= 3, probe.officer_reason


def test_d6_a_coordinated_review_is_still_a_chief_orchestrator(review):
    probe, _ = review

    assert probe.officer_level == 4, probe.officer_reason


@pytest.mark.parametrize("question", [
    "Show IFRS 9 ECL by sector for the latest quarter.",
    "Show the ten largest customers by IFRS 9 EAD at the latest quarter.",
    "List the facilities in Stage 3 at the latest quarter.",
    "Which customers had a rating downgrade and an increase in ECL over the "
    "latest year?",
])
def test_d17_columns_reach_the_reader_in_governed_rank_order(question):
    """D17 failed on every two-period cohort — because the check read
    `presentation.contract`, which returns the RUNTIME's order by design, and
    called the difference a presentation fault."""
    from backend.assurance import signals as sg

    _, answered = _probe(question)
    ctx = sg.Ctx.of(answered.investigation, answered.answered)
    signal = sg.read("table_column_ordering", ctx)

    assert signal is not None
    assert signal.outcome == "PASS", signal.detail


# ----------------------------------------------------------------------- D21


def test_d21_every_review_pack_risk_class_has_cases():
    """D21: nine of §18's fifteen risk classes had no cases at all, so a
    pack that looked complete showed a reviewer nothing about permissions,
    injection, officer selection, agent selection, proactive review, Risk
    Cases or workflow approval.

    Asserted over the CORPUS the factory offers rather than over whatever the
    database happens to hold. The suite truncates `teaching_cases`, so a test
    that queried the table would pass or fail on the order the suite ran in —
    which is the test-isolation defect this phase already had to fix once.
    The corpus is the claim: `seed` writes every case in it, so a corpus that
    covers every class is a seeded library that covers every class.
    """
    from backend.teaching import review_pack as rp
    from scripts.seed_teaching_library import corpus

    counted: dict[str, int] = {}
    for case in corpus():
        name = rp.classify(case)
        counted[name] = counted.get(name, 0) + 1

    empty = [name for name, _, _ in rp.CLASSES if not counted.get(name)]
    assert not empty, f"risk classes with no teaching case at all: {empty}"

    thin = [name for name, _, _ in rp.CLASSES
            if counted.get(name, 0) < rp.PER_CLASS]
    assert not thin, (
        f"risk classes with fewer cases than the pack asks for: {thin}")


def test_d21_a_case_may_declare_its_own_risk_class():
    """The classifier is not loosened to a substring match — that would file
    every agent_selection case under agentic_cockpit. A case declares."""
    from backend.teaching import review_pack as rp

    class _Case:
        family_id = "AGENTIC_ORCHESTRATION"
        tags = ["agent_selection", "safety", "agentic_orchestration"]
        expected_failure_categories: list[str] = []

    assert rp.classify(_Case()) == "agent_selection"


def test_d21_the_safety_curriculum_covers_every_empty_class():
    """Nine classes, eight cases each, none of them duplicates."""
    from intelligence_factory.teaching import safety

    report = safety.report()
    assert report["total"] == 72
    for blueprint in safety.BLUEPRINTS:
        assert report[blueprint.risk_class] == safety.PER_CLASS, report

    fingerprints = {c.fingerprint for c in safety.cases()}
    assert len(fingerprints) == 72, "the safety corpus contains duplicates"


def test_d21_the_safety_cases_approve_nothing():
    """§6 stays true: seeding writes cases, it does not review them."""
    from backend.teaching import status as st
    from intelligence_factory.teaching import safety

    for case in safety.cases():
        assert case.review_status != st.APPROVED
        assert case.authoring_method == st.BLUEPRINT
