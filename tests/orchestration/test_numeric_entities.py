"""
A number in a question is usually a quantity.

IFRS 9 stages are the values "1", "2" and "3", and the entity matcher resolved
them out of any digit it could find a word boundary around. "Which borrowers
have a DSCR below 1.2?" came back filtered to stage 1 AND stage 2, because `.`
is a non-word character and `\\b1\\b` matches inside "1.2" — an answer about a
different population, correctly computed, with nothing on screen to say so.

Found by the P0.8 presentability gate: the invariant check reported that 16 of
136 rows did not satisfy the stage filter the question was recorded as carrying.
"""

from __future__ import annotations

import pytest

from backend.orchestration import entities as en

STAGES = {"ifrs9_stage": ["1", "2", "3"]}


def _matched(question: str) -> list[str]:
    return sorted(m.value for m in en.match_all(question, STAGES))


@pytest.mark.parametrize("question", [
    "Which borrowers have a DSCR below 1.2?",
    "Show customers with an interest cover under 1.35x.",
    "Exposure above 1,200 SAR mn",
    "Which facilities have an LTV over 0.85?",
])
def test_a_digit_inside_a_number_is_not_a_stage(question):
    """The defect. Every one of these resolved a stage filter out of a
    threshold and answered a different question."""
    assert _matched(question) == []


@pytest.mark.parametrize("question", [
    "Which borrowers have a DSCR of 2?",
    "a DSCR between 1 and 2",
    "Show me the 3 largest exposures.",
])
def test_a_bare_digit_is_not_a_stage_either(question):
    """The governed vocabulary already refuses to infer these dimensions from
    free text — AMBIGUOUS_DIMENSIONS exists for exactly this — and the entity
    matcher was the reader that did not honour it. A stage has to be named."""
    assert _matched(question) == []


@pytest.mark.parametrize("question, expected", [
    ("Which customers are in Stage 2?", ["2"]),
    ("Customers in Stage 2.", ["2"]),
    ("Show ECL for stage 2 and stage 3.", ["2", "3"]),
    ("IFRS 9 stage 2 exposure", ["2"]),
    ("stages 2 and 3", ["2", "3"]),
    ("stage 1, 2 or 3", ["1", "2", "3"]),
    ("stage 1 exposure above 1,200", ["1"]),
])
def test_a_named_stage_still_resolves(question, expected):
    """The fix must not cost the thing it guards. A trailing full stop is a
    sentence and a trailing comma is a list; neither is 1,200, and the noun is
    shared across a coordination."""
    assert _matched(question) == expected


def test_a_named_value_is_unaffected():
    """Only numeric values needed a numeric boundary. A sector is a word."""
    matched = en.match_all("Show stage 3 customers in Contracting",
                           {**STAGES, "sector": ["Contracting"]})
    assert sorted((m.kind, m.value) for m in matched) == [
        ("ifrs9_stage", "3"), ("sector", "Contracting")]
