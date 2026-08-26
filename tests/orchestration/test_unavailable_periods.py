"""
A period the question names and the data does not hold.

The failure this covers is the quietest one the product can make: every figure
in the answer correct, and about a different quarter than the one asked for.
"""

from __future__ import annotations

import pytest

from backend.orchestration import periods as pd

PERIODS = [f"Q{q} {y}" for y in range(2023, 2026) for q in (1, 2, 3, 4)]


@pytest.mark.parametrize("question,named", [
    ("What was total exposure at default in Q1 2015?", "Q1 2015"),
    ("What was total EAD in 2011?", "2011"),
    ("What was total EAD in FY2019?", "2019"),
    ("What was total exposure at default in Q3 2031?", "Q3 2031"),
])
def test_a_period_outside_the_history_is_named_back(question, named):
    assert pd.unavailable(question, PERIODS) == named


@pytest.mark.parametrize("question", [
    "What was total exposure at default in Q4 2024?",
    "What was total EAD in 2024?",
    "What was total EAD in March 2024?",
    "How has ECL moved over the latest year?",
    "Which customers have covenant headroom below 15%?",
    "Show me the five largest Real Estate customers by EAD.",
    "Which customers had ECL rise more than 50% over the latest year?",
])
def test_an_available_or_unstated_period_is_not_flagged(question):
    assert pd.unavailable(question, PERIODS) == ""


def test_a_bare_year_is_covered_by_its_quarters():
    """The data has no row labelled "2024", and it can still answer about it."""
    assert pd.unavailable("What was total EAD in 2024?", PERIODS) == ""


def test_nothing_is_flagged_when_no_periods_are_known():
    """A catalogue that failed to load must not become "we do not have 2024"."""
    assert pd.unavailable("What was total EAD in Q1 2015?", []) == ""


def test_the_orchestrator_asks_rather_than_answering_about_another_quarter():
    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.executor import answer_investigation

    investigation, answered = answer_investigation(
        "What was total exposure at default in Q1 2015?", persist=False,
        state=cv.load({}), memory=wm.load({}))

    assert answered.runtime is None, "it computed a figure for another quarter"
    assert "Q1 2015" in answered.clarification
    assert investigation.status == "needs_clarification"
