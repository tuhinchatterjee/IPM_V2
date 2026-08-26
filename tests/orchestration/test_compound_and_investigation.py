"""
Compound questions, corrections, and investigating what is already on screen.

Three behaviours the sealed holdout found missing, each with the same shape:
CreditProbe knew enough to answer and asked instead.
"""

from __future__ import annotations

import pytest

from backend.orchestration import conversation as cv
from backend.orchestration import investigation as iv
from backend.orchestration import memory as wm
from backend.orchestration.context import retrieve
from backend.orchestration.executor import answer_investigation
from backend.orchestration.orchestrator import remember as advance


def _thread(*questions: str):
    """Run a conversation and return every answered turn."""
    context: dict = {}
    out = []
    for question in questions:
        state, memory = cv.load(context), wm.load(context)
        investigation, answered = answer_investigation(
            question, persist=False, state=state, memory=memory)
        context = cv.save(context, advance(
            state, answered,
            headline=str(investigation.narrative.direct_answer or ""),
            run_id=None))
        context = wm.save(context, wm.observe(wm.load(context), answered,
                                              investigation))
        out.append((investigation, answered))
    return out


# ---------------------------------------------------------------------------
# Splitting a compound question
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question,count", [
    ("What fields are in the ratings data, and which of them are financial "
     "ratios?", 2),
    ("What datasets cover covenants, how many periods do they have, and how "
     "do they join to the facility book?", 2),
    ("What is total EAD and ECL by sector?", 1),
    ("Show me the five largest customers.", 1),
])
def test_only_a_second_question_splits_a_sentence(question, count):
    """"EAD and ECL" is one objective with two measures, not two objectives."""
    assert len(wm.objectives(question)) == count


def test_a_reference_to_the_same_sentence_is_not_a_dangling_referent():
    """"which of them" points at the clause before it, not a previous turn."""
    _, answered = _thread(
        "What columns are in the ratings data, and which of them are "
        "financial ratios?")[0]
    assert not answered.clarification
    assert answered.reading.intent == "DATA_DICTIONARY"


# ---------------------------------------------------------------------------
# Correcting an incomplete answer
# ---------------------------------------------------------------------------


def test_you_didnt_answer_my_second_question_answers_it():
    """The complaint names no figure; the clause it points at does.

    Read literally it used to produce a menu of governed concepts, which is a
    reasonable reply to a question nobody asked.
    """
    turns = _thread(
        "What fields are in the ratings data, and which of them are financial "
        "ratios?",
        "You didn't answer my second question.")
    investigation, answered = turns[1]

    assert investigation.status == "succeeded"
    assert answered.continuation.action == cv.CORRECT_INCOMPLETE_RESPONSE
    assert "ratio" in str(investigation.narrative.direct_answer).lower()


def test_the_outstanding_clause_is_remembered():
    _, answered = _thread(
        "What fields are in the ratings data, and which of them are financial "
        "ratios?")[0]
    memory = wm.observe(wm.WorkingMemory(), answered, None)
    assert memory.outstanding == ["which of them are financial ratios"]


# ---------------------------------------------------------------------------
# Investigating
# ---------------------------------------------------------------------------


def test_a_deterioration_question_investigates_the_whole_book():
    """"What has deteriorated?" names no measure and needs none."""
    request = iv.read("What has deteriorated over the latest year?",
                      retrieve("What has deteriorated over the latest year?"))
    assert request.subject == iv.WHOLE_BOOK
    assert request.probes
    for probe in request.probes:
        assert "  " not in probe.question, "a subject was formatted into a gap"


def test_a_pronoun_with_no_antecedent_still_asks():
    """"Investigate it." with nothing behind it is a question about "it"."""
    assert not iv.read("Investigate it.", retrieve("Investigate it.")).valid


def test_investigate_those_uses_the_population_already_on_screen():
    turns = _thread(
        "Show the five largest Mining & Metals customers by exposure at "
        "default.",
        "Investigate those.")
    investigation, answered = turns[1]
    assert investigation.status == "succeeded"
    assert answered.investigation.get("subject") == "Mining & Metals"


# ---------------------------------------------------------------------------
# Refusing rather than answering about the wrong population
# ---------------------------------------------------------------------------


def test_a_filter_that_cannot_be_applied_stops_the_answer():
    """No dataset carries a rating bucket, so "Watch customers" cannot be run.

    It used to drop the filter and return the ECL of the entire book, with a
    warning under the table that nobody reads and a headline that said nothing.
    """
    investigation, answered = _thread(
        "What is total expected credit loss for Watch customers?")[0]

    assert answered.runtime is None
    assert "Watch" in answered.clarification
    assert investigation.status == "needs_clarification"
