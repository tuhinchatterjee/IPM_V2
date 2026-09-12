"""
A false premise is a claim to test. It is not a scenario to simulate.

The live certification asked "Given every Contracting obligor improved last
month, which one improved most?". The model read "given" as a supposition,
routed the request to What-If, and Early Warning ran nothing: no plan, no
sufficiency review, no interpretation, no answer. Contracting deteriorated
that month, and saying so was the answer.

The gate had one asymmetry — a model may close it, never open it — and routing
OUT was treated as always safe because nothing analytical runs. That is true of
the controls and false of the reader. So there is now a second governed test in
the outward direction: a question about a condition the book already carries,
with no stipulated change, stays here.

The test is not the word "if". These both contain one:

    If Contracting deteriorated, what drove it?        observed
    Recalculate ECL if the rating falls two notches.   hypothetical

Only the second replaces a value and asks what would follow.
"""

from __future__ import annotations

import pytest

from backend.early_warning import functionality as fn
from backend.early_warning.conversation import seam as seam_mod
from backend.early_warning.conversation import select as sel

# ---------------------------------------------------------------- the tests

OBSERVED = [
    # false premise — the case the certification failed
    "Given every Contracting obligor improved last month, which one improved most?",
    "Given nothing deteriorated this quarter, why is the watchlist longer?",
    "Assuming Contracting improved last month, who improved most?",
    # conditional factual
    "If Contracting deteriorated, what drove it?",
    "If any obligor moved into High last month, which one?",
    # plain observed deterioration
    "Why has Contracting deteriorated?",
    "Did Contracting deteriorate?",
    "Has this borrower worsened?",
    "Which names deteriorated most over the last six months?",
    # observed improvement
    "Which obligors improved out of High last quarter?",
    "Who improved most since December?",
]

HYPOTHETICAL = [
    "What happens to ECL if oil falls 30%?",
    "Shock PD by 20%.",
    "Assume oil drops to $50.",
    "Recalculate ECL if the rating falls two notches.",
    "Run a scenario where property values halve.",
    "Stress the book for a 200bp rate rise.",
    "What if the rating deteriorated two notches — what would ECL be?",
    "Simulate a 30% fall in oil and reprice the portfolio.",
]


@pytest.mark.parametrize("question", OBSERVED)
def test_an_observed_state_question_belongs_to_early_warning(question):
    assert fn.belongs_to_early_warning(question), question
    assert not fn.stipulates_a_hypothetical(question), question


@pytest.mark.parametrize("question", HYPOTHETICAL)
def test_a_stipulated_change_does_not(question):
    assert fn.stipulates_a_hypothetical(question), question
    assert not fn.belongs_to_early_warning(question), question


def test_the_word_if_decides_nothing_on_its_own():
    conditional = "If Contracting deteriorated, what drove it?"
    hypothetical = "Recalculate ECL if the rating falls two notches."
    assert "if" in conditional.lower() and "if" in hypothetical.lower()
    assert fn.belongs_to_early_warning(conditional)
    assert not fn.belongs_to_early_warning(hypothetical)


# ------------------------------------------------------------- the control

def reply(**data) -> seam_mod.Outcome:
    return seam_mod.Outcome(stage="opus_functionality_selection",
                            engine=seam_mod.MODEL, data=dict(data))


def reconcile(question: str, proposed: str, confidence: float = 0.9):
    deterministic = fn.select(question, active=fn.EARLY_WARNING)
    return deterministic, sel._reconcile(
        deterministic,
        reply(selected_functionality=proposed, confidence=confidence,
              ownership_rationale="the model's reading"),
        fn.EARLY_WARNING, question)


@pytest.mark.parametrize("question", OBSERVED)
def test_the_model_may_not_route_an_observed_question_out(question):
    deterministic, held = reconcile(question, fn.WHAT_IF)
    assert deterministic.selected == fn.EARLY_WARNING, question
    assert held.selected == fn.EARLY_WARNING, question
    assert held.model_call["accepted"] is False
    assert "observed-state" in held.model_call["reason"]


def test_the_refusal_names_what_the_model_proposed():
    _, held = reconcile(OBSERVED[0], fn.WHAT_IF)
    assert "What-If" in held.rationale or "what_if" in held.rationale
    assert held.model_call["proposed"] == fn.WHAT_IF


def test_the_model_may_still_route_a_genuine_scenario_out():
    """LIVE-6 must keep working exactly as it does."""
    question = "What happens to ECL if oil falls 30%?"
    deterministic, out = reconcile(question, fn.WHAT_IF)
    assert out.selected == fn.WHAT_IF
    assert out.model_call["accepted"] is True


def test_a_scenario_the_patterns_missed_can_still_be_routed_out():
    question = "Recalculate ECL if the rating falls two notches."
    deterministic, out = reconcile(question, fn.WHAT_IF)
    # The patterns keep it; the model spots the scenario; the gate lets it go.
    assert deterministic.selected == fn.EARLY_WARNING
    assert out.selected == fn.WHAT_IF
    assert out.model_call["accepted"] is True


def test_a_model_still_may_not_open_the_gate():
    """The original asymmetry is untouched."""
    question = "What happens to ECL if oil falls 30%?"
    deterministic = fn.select(question, active=fn.EARLY_WARNING)
    assert deterministic.selected == fn.WHAT_IF
    held = sel._reconcile(
        deterministic,
        reply(selected_functionality=fn.EARLY_WARNING, confidence=0.95,
              ownership_rationale="it mentions the book"),
        fn.EARLY_WARNING, question)
    assert held.selected == fn.WHAT_IF
    assert held.model_call["accepted"] is False
    assert held.model_call["reason"] == "a model may not open the gate"


def test_agreement_is_still_agreement():
    question = "Why has Contracting deteriorated?"
    _, out = reconcile(question, fn.EARLY_WARNING)
    assert out.selected == fn.EARLY_WARNING
    assert out.model_call["accepted"] is True
    assert out.model_call["agreed_with_patterns"] is True


def test_a_cockpit_question_the_model_spots_still_leaves():
    """The guard fires on observed EWS conditions, not on everything."""
    question = "Show total exposure by sector."
    deterministic = fn.select(question, active=fn.EARLY_WARNING)
    out = sel._reconcile(
        deterministic,
        reply(selected_functionality=fn.COCKPIT, confidence=0.9,
              ownership_rationale="portfolio composition"),
        fn.EARLY_WARNING, question)
    assert out.selected == fn.COCKPIT


def test_the_false_premise_question_is_answered_rather_than_handed_over():
    """End to end: it stays here, and the deterministic answer contradicts it."""
    from backend.early_warning.conversation import pipeline as pl

    turn = pl.answer(OBSERVED[0], thread_id="premise-ownership").to_dict()
    assert turn["functionality_selection"]["selected_functionality"] \
        == fn.EARLY_WARNING
    answer = turn["answer"]
    assert answer.get("answered") is True
    said = (answer.get("direct") or "").lower()
    assert "deteriorated" in said or "did not improve" in said
