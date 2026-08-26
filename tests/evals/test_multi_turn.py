"""
Conversations, not questions.

Why this suite exists separately from the case evals
----------------------------------------------------
Every one of the nine failures that blocked this release was a *second* turn.
The isolated-question corpus passed throughout: routing was right, planning was
right, and the product was still unusable, because a follow-up reached the
planner as a bare sentence with nothing to resolve.

So this suite tests only the thing that broke — what survives from one turn to
the next. It runs offline: the deterministic reader is the floor the live model
sits on, and a suite that needed a key would not run in CI at all.

The threads are generated from tables rather than written out one by one, so the
suite covers a hundred conversations without a hundred copies of the same nine
lines. Each generator states the property it is checking.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY

SECTORS = ("Real Estate", "Contracting", "Petrochemicals", "Healthcare",
           "Utilities", "Transport & Logistics", "Wholesale & Retail Trade")
MEASURES = ("EAD", "expected credit loss")
DIMENSIONS = ("sector", "region", "segment")
REFERENTS = ("these", "those", "them", "those five", "the previous result")


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built — run scripts/build_data_lake.py")


def _thread(*turns: str) -> tuple[str, ...]:
    return turns


def _population_threads() -> list[tuple[str, ...]]:
    """A ranking, then a question about the rows it returned.

    The property: turn 2 must be planned against the identities turn 1 returned,
    not against the whole book.
    """
    return [
        _thread(f"Show me the five largest {sector} customers by {measure}.",
                f"Which of {referent} are Stage 2 or Stage 3?")
        for sector in SECTORS
        for measure in MEASURES
        for referent in REFERENTS
    ]


def _modification_threads() -> list[tuple[str, ...]]:
    """A grouped total, then a cut, then a re-measure.

    The property: a modification edits what is on screen. The cut survives the
    next turn, and replacing the measure does not put the dropped groups back.
    """
    return [
        _thread(f"What is total {measure} by {dimension} in the latest quarter?",
                "Show only the five largest.",
                "Now show each one's percentage of the total.",
                "Replace it with the number of customers.")
        for measure in MEASURES
        for dimension in DIMENSIONS
    ]


def _period_threads() -> list[tuple[str, ...]]:
    """A window settled once, reused after.

    The property: a follow-up inherits the comparison rather than asking again.
    """
    phrasings = ("over the latest year", "over the last year", "year on year",
                 "over the last 6 months", "since last quarter",
                 "over the latest 6 months", "over the last two years")
    return [
        _thread(f"Which customers had an increase in ECL {phrase}?",
                "Only show Contracting.",
                "Rank them by EAD.")
        for phrase in phrasings
    ]


def _subject_change_threads() -> list[tuple[str, ...]]:
    """A catalogue question in the middle of an analysis.

    The property: asking what fields exist must NOT wipe the population the
    conversation was working on.
    """
    return [
        _thread(f"Show me the ten largest {sector} customers by EAD.",
                "What fields are available in the ratings data?",
                "Rank those ten by ECL instead.")
        for sector in SECTORS
    ]


def _enrichment_threads() -> list[tuple[str, ...]]:
    """Adding a column from another governed source.

    The property: the population is kept and the new measure is joined in over a
    declared relationship.
    """
    return [
        _thread(f"Show me the five largest {sector} customers by EAD.",
                "Add their latest internal rating.")
        for sector in SECTORS
    ]


def _cohort_threads() -> list[tuple[str, ...]]:
    """A cohort, narrowed twice.

    The property: the movement conditions stay in force while a filter is added.
    """
    return [
        _thread("Which customers had a rating downgrade and an increase in ECL "
                "over the latest year?",
                f"Only show {sector}.",
                "Which of those also have worsening DPD?")
        for sector in SECTORS[:5]
    ]


THREADS: list[tuple[str, ...]] = [
    *_population_threads(),
    *_modification_threads(),
    *_period_threads(),
    *_subject_change_threads(),
    *_enrichment_threads(),
    *_cohort_threads(),
]


#: Threads are re-used by several tests, and every turn is a real DuckDB read.
#: Running each conversation once and sharing the transcript keeps the suite to
#: a couple of minutes rather than ten.
_TRANSCRIPTS: dict[tuple[str, ...], list[dict[str, Any]]] = {}


def _run(thread: tuple[str, ...]) -> list[dict[str, Any]]:
    if thread not in _TRANSCRIPTS:
        _TRANSCRIPTS[thread] = _execute(thread)
    return _TRANSCRIPTS[thread]


def _execute(thread: tuple[str, ...]) -> list[dict[str, Any]]:
    from backend.orchestration import conversation as cv
    from backend.orchestration import orchestrator
    from backend.orchestration.executor import answer_investigation

    state = cv.ConversationState()
    seen: list[dict[str, Any]] = []
    for question in thread:
        investigation, answered = answer_investigation(
            question, persist=False, state=state)
        conversation = investigation.conversation or {}
        seen.append({
            "question": question,
            "status": investigation.status,
            "action": (conversation.get("continuation") or {}).get("action"),
            "population": (conversation.get("continuation") or {}).get(
                "entity_count") or 0,
            "answer": investigation.narrative.direct_answer,
            "steps": len(investigation.steps),
        })
        if answered is not None:
            state = orchestrator.remember(
                state, answered,
                headline=str(investigation.narrative.direct_answer or ""))
    return seen


def test_the_suite_covers_at_least_a_hundred_conversations():
    """The number is the point: follow-ups are where this product broke."""
    assert len(THREADS) >= 100
    assert sum(len(t) for t in THREADS) >= 230


#: The subject-change threads deliberately contain a NEW_REQUEST in the middle,
#: and have their own test. Everything else must stay in the conversation.
CONTINUING_THREADS = [t for t in THREADS
                      if t not in set(_subject_change_threads())]


@pytest.mark.parametrize("thread", CONTINUING_THREADS, ids=lambda t: t[0][:40])
def test_a_follow_up_is_never_answered_as_a_fresh_question(thread):
    """The single invariant that would have caught every reported failure.

    Every turn after the first must either be read as a continuation, or ask a
    question. What it may never do is silently become a NEW_REQUEST and answer
    about the whole book — that is what "which of these are Stage 2?" did, and
    the answer looked entirely reasonable.
    """
    turns = _run(thread)
    for index, turn in enumerate(turns[1:], start=2):
        if turn["status"] == "needs_clarification":
            continue
        assert turn["action"] != "NEW_REQUEST", (
            f"turn {index} of {thread[0][:50]!r} — {turn['question']!r} — was "
            "answered as a fresh request, losing the conversation")


@pytest.mark.parametrize("thread", _population_threads()[::5],
                         ids=lambda t: t[1][:40])
def test_a_referent_resolves_to_the_rows_the_previous_turn_returned(thread):
    turns = _run(thread)
    if turns[0]["status"] != "succeeded" or not turns[0]["steps"]:
        pytest.skip("the opening ranking returned nothing to refer back to")
    assert turns[1]["population"] > 0, (
        f"{turns[1]['question']!r} did not carry the previous population")


@pytest.mark.parametrize("thread", _period_threads(), ids=lambda t: t[0][-28:])
def test_a_settled_window_is_not_asked_about_again(thread):
    turns = _run(thread)
    for turn in turns[1:]:
        assert turn["status"] != "needs_clarification" or "period" not in str(
            turn["answer"]).lower(), (
            f"{turn['question']!r} re-asked for a window the thread had settled")


@pytest.mark.parametrize("thread", _subject_change_threads(),
                         ids=lambda t: t[0][:36])
def test_a_catalogue_question_does_not_wipe_the_population(thread):
    """Asking what fields exist is not a change of subject for the analysis."""
    turns = _run(thread)
    if turns[0]["status"] != "succeeded" or not turns[0]["steps"]:
        pytest.skip("the opening ranking returned nothing to carry")
    assert turns[1]["action"] == "NEW_REQUEST", (
        "a catalogue question mid-thread is its own request")
    assert turns[2]["population"] > 0, (
        "the population was lost when the conversation asked about the "
        "catalogue and came back")
