"""
When CreditProbe should ask instead of answering.

The behaviour under test is a refusal, and it is the most important refusal in
the product. Asked something it could not read, CreditProbe used to run the
standard portfolio review and put a note above it — producing a correct,
certified, confidently-presented answer to a question nobody asked.

A confident answer to the wrong question is worse than no answer, because
nothing about it looks wrong.
"""

from __future__ import annotations

import pytest

from backend.orchestration import comprehension as cp
from backend.orchestration.executor import run_investigation
from backend.orchestration.vocabulary import get_vocabulary

# ------------------------------------------------------------ entity spotting


def test_a_borrower_name_is_recognised_as_a_name():
    assert "Summit Power" in cp.named_entities("What is Summit Power's outlook?")


def test_the_products_own_vocabulary_is_not_mistaken_for_a_borrower():
    """"Early Warning" and "Real Estate" are capitalised and are not borrowers."""
    for question in (
        "Open the Early Warning module",
        "How is Real Estate performing?",
        "Show me the Portfolio Summary",
    ):
        assert cp.named_entities(question) == [], question


def test_an_ordinary_question_names_no_entity():
    assert cp.named_entities("Which sectors deteriorated the most?") == []


# ------------------------------------------------------ the executor's choice


def test_an_unreadable_question_asks_rather_than_running_anything():
    run = run_investigation("How do I bake sourdough?", persist=False)
    assert run.status == "needs_clarification"
    assert run.steps == [], "Nothing may run when the question was not understood."
    assert run.clarification.kind == cp.KIND_INTENT


def test_the_clarification_offers_things_the_engine_can_actually_do():
    """Read from the registry, so the list cannot drift out of date."""
    run = run_investigation("asdfghjkl", persist=False)
    from backend.engine.registry import get_registry

    known = {c.id for c in get_registry().contracts()}
    assert run.clarification.options
    assert all(o["id"] in known for o in run.clarification.options)
    assert all(o["question"] for o in run.clarification.options)


def test_a_borrower_the_data_does_not_contain_is_reported_as_missing():
    run = run_investigation("What is Summit Power's outlook?", persist=False)
    assert run.status == "needs_clarification"
    assert run.steps == []
    assert run.clarification.kind == cp.KIND_ENTITY
    assert "could not find" in run.clarification.question
    # It explains WHY rather than only that it failed.
    assert "published" in run.clarification.detail


def test_a_known_borrower_with_no_measure_is_asked_about_rather_than_guessed():
    vocab = get_vocabulary()
    names = cp._borrower_names(vocab.latest)
    if not names:
        pytest.skip("No published book to name a borrower from")

    run = run_investigation(f"Tell me about {names[0]}", persist=False)
    assert run.status == "needs_clarification"
    assert run.steps == []
    assert run.clarification.kind == cp.KIND_ENTITY
    # Every option is a complete question the user can send straight back.
    assert len(run.clarification.options) >= 3
    assert all(names[0] in o["question"] for o in run.clarification.options)


def test_a_question_it_does_understand_still_runs():
    """The refusal must be narrow. A product that asks about everything is as
    useless as one that answers everything."""
    run = run_investigation("What is our NPL ratio?", persist=False)
    assert run.status == "succeeded"
    assert [s.analysis_id for s in run.steps] == ["portfolio_summary"]


def test_no_unmatched_question_ever_reaches_the_portfolio_summary():
    """The specific regression: the old fallback."""
    for question in ("How do I bake sourdough?", "asdfghjkl", "tell me a joke"):
        run = run_investigation(question, persist=False)
        assert run.status == "needs_clarification", question
        assert not any(s.analysis_id == "portfolio_summary" for s in run.steps), question
