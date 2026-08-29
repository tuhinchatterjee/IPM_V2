"""A question about what a regulation SAYS is not answered with an analysis.

The client-demo release-candidate brief lists among the failures that produce
NO-GO:

    "unsupported question answered with unrelated analysis"

The demonstration question set found exactly that. Asked "What does the
circular say about provisioning for Stage 2?", CreditProbe ran a
SIMPLE_ANALYSIS over `ifrs9_staging` and presented the result, with no
circular in the corpus and no active Regulatory Knowledge Release.

These tests hold both halves of the fix: the documentary question is refused,
and every ordinary analytical question that mentions a regulatory concept
still works. The second half is the one worth guarding — a detector that
swallowed "show IFRS 9 ECL by stage" would break most of the product.
"""

from __future__ import annotations

import pytest

from backend.regulatory import intent

# ------------------------------------------------------- documentary questions


@pytest.mark.parametrize("question", [
    "What does the circular say about provisioning for Stage 2?",
    "What does IFRS 9 require for Stage 2?",
    "According to SAMA, what is the minimum coverage?",
    "What are the regulatory requirements for provisioning?",
    "Under the circular, how should we treat restructured facilities?",
    "Which clause of the circular covers collateral haircuts?",
    "What does Basel say about the leverage ratio?",
])
def test_a_question_about_what_a_source_says_is_documentary(question):
    found = intent.read(question)
    assert found.documentary is True, question


# --------------------------------------------------------- analytical questions


@pytest.mark.parametrize("question", [
    "What is total EAD by sector in the latest quarter?",
    "Show IFRS 9 ECL by stage.",
    "Show IFRS 9 EAD by sector for the latest quarter.",
    "Which customers had a rating downgrade and an increase in ECL?",
    "Show the five largest Real Estate customers by EAD.",
    "For each sector, calculate Stage 2 EAD divided by total sector EAD.",
    "Review the latest portfolio and tell me what requires CRO attention.",
    "What ratings data do you have?",
])
def test_an_ordinary_analytical_question_is_untouched(question):
    """The half that matters most.

    Mentioning IFRS 9 does not make a question documentary. "Show IFRS 9 ECL
    by stage" is a request for a figure and must keep working exactly as it
    did; a detector that caught it would have broken the product to fix one
    question.
    """
    found = intent.read(question)
    assert found.documentary is False, f"{question} was read as documentary"


def test_an_empty_question_is_not_documentary():
    assert intent.read("").documentary is False
    assert intent.read("   ").documentary is False


# ------------------------------------------------------------------ the refusal


def test_the_refusal_says_what_would_make_it_answerable():
    """A refusal that says only "no" invites the user to rephrase and retry."""
    text = intent.refusal(intent.read(
        "What does the circular say about provisioning for Stage 2?"))

    assert "circular" in text.lower()
    assert "Regulatory Knowledge Release" in text
    # It must say explicitly that it will not substitute an analysis, because
    # substituting one is the defect this exists to prevent.
    assert "analytical data" in text
    assert "activate a release" in text.lower()


def test_it_may_not_answer_without_a_session():
    """Fail-closed. A regulatory answer given because the database was
    briefly unreachable is the worst possible reason to have given one."""
    assert intent.may_answer(None) is False
    assert intent.may_answer() is False


def test_a_broken_session_is_a_refusal_not_an_answer():
    class Exploding:
        def execute(self, *args, **kwargs):
            raise RuntimeError("the database went away")

    assert intent.may_answer(Exploding()) is False


# ------------------------------------------------- the whole path, end to end


def test_the_orchestrator_refuses_a_documentary_question(monkeypatch):
    """The gate, on the real path.

    `backend/regulatory/assurance.py` already made `release_active` a CRITICAL
    check. It was right and nothing routed to it; this asserts that something
    does now.
    """
    pytest.importorskip("sqlalchemy")
    from tests.conftest import database_available

    if not database_available():
        pytest.skip("this drives the real orchestration path")

    from backend.proof.probe import run_probe

    probe, _ = run_probe("What does the circular say about provisioning for "
                         "Stage 2?", label="regulatory")

    assert probe.unsupported is True, (
        "a question about what a circular says was answered anyway")
    assert probe.datasets == [], (
        f"it read {probe.datasets} to answer a question about a document")


def test_an_ifrs9_analysis_still_runs():
    """The other half, on the real path. Guarding the fix is worth as much as
    the fix."""
    from tests.conftest import database_available

    if not database_available():
        pytest.skip("this drives the real orchestration path")

    from backend.proof.probe import run_probe

    probe, _ = run_probe("Show IFRS 9 ECL by stage for the latest quarter.",
                         label="ifrs9")

    assert probe.unsupported is False, probe.error
    assert probe.executed is True
    assert probe.datasets, "it executed and read nothing"
