"""«the second one» binds to one row of the answer already on screen.

The defect
----------
    Turn 4: "Which of those have rising 12-month PD?"  → 23 borrowers
    Turn 5: "Why does the second one worry you?"       → the whole ranking

Nothing read the fifth sentence as a reference, so it was planned from its own
words: "worry" resolved to the composite credit concern signals, the ranking
was recomputed over the whole population, and twenty-five names came back under
a question about one. Arithmetically correct, and about a different subject.

What holds now
--------------
An ordinal reads the STORED order by position. It re-ranks nothing, it never
widens back to the whole population when it cannot bind, and what it bound to
is on the Trace either way.
"""

from __future__ import annotations

import pytest

from backend.orchestration import conversation as cv
from backend.orchestration import nth
from backend.orchestration import referents as rf

RANKED = {"operations": [{"op": "SORT", "params": {
    "by": [{"column": "pd_12m_pct", "direction": "desc"}]}}]}


def _state(ids: list[str], *, labels: dict[str, str] | None = None,
           ir: dict | None = None) -> cv.ConversationState:
    return cv.ConversationState(
        subject="the borrowers already on screen",
        ir=dict(ir if ir is not None else RANKED),
        result=cv.ResultShape(entity_key="customer_id", entity_ids=list(ids),
                              entity_labels=dict(labels or {}),
                              row_count=len(ids),
                              question="Which of those have rising PD?"))


THREE = ["SA-1", "SA-2", "SA-3"]
NAMED = {"SA-1": "Alpha Shipping", "SA-2": "Beta Marine", "SA-3": "Gamma Lines"}


class TestReadingTheReference:
    @pytest.mark.parametrize("question,index", [
        ("Why does the second one worry you?", 1),
        ("Why is the second one a concern?", 1),
        ("Tell me about the first one.", 0),
        ("What about the third?", 2),
        ("Why the fourth name?", 3),
        ("Show me the 2nd one.", 1),
        ("What is row 5?", 4),
        ("Why #3?", 2),
        ("And the last one?", -1),
        ("Why the final one?", -1),
    ])
    def test_an_ordinal_names_a_position(self, question: str, index: int):
        read = nth.read(question)
        assert read is not None, f"{question!r} named no position"
        assert read.index == index

    @pytest.mark.parametrize("question", [
        "Show me the first five.",
        "The second largest customer by exposure at default.",
        "Bridge the movement in ECL over the last year.",
        "What happened in the first quarter of 2025?",
        "Compare the last two quarters.",
        "Show the last twelve months.",
        "Which of those have rising 12-month PD?",
        "Circular number 4 says exposures must be reported quarterly.",
        "Who are the worst names?",
    ])
    def test_a_slice_a_ranking_or_a_period_is_not_a_position(self,
                                                            question: str):
        assert nth.read(question) is None, (
            f"{question!r} was read as a reference to one row")


class TestBindingToTheStoredOrder:
    def test_the_second_one_is_the_second_row_of_the_previous_answer(self):
        bound = nth.resolve(nth.read("Why does the second one worry you?"),
                            _state(THREE, labels=NAMED))
        assert bound.resolved
        assert bound.entity_id == "SA-2"
        assert bound.label == "Beta Marine"
        assert (bound.position, bound.of) == (2, 3)

    def test_the_last_one_counts_from_the_end(self):
        bound = nth.resolve(nth.read("And the last one?"), _state(THREE))
        assert bound.entity_id == "SA-3"

    def test_the_worst_one_reads_the_direction_of_the_stored_sort(self):
        """PD descending puts the worst first; interest cover does not."""
        worst_first = nth.resolve(nth.read("Why the worst one?"),
                                  _state(THREE, ir=RANKED))
        assert worst_first.entity_id == "SA-1"

        cover = {"operations": [{"op": "SORT", "params": {
            "by": [{"column": "interest_coverage", "direction": "desc"}]}}]}
        assert nth.resolve(nth.read("Why the worst one?"),
                           _state(THREE, ir=cover)).entity_id == "SA-3"

    def test_an_ordering_that_says_nothing_leaves_worst_unresolved(self):
        blank = {"operations": [{"op": "SCAN", "params": {}}]}
        bound = nth.resolve(nth.read("Why the worst one?"),
                            _state(THREE, ir=blank))
        assert not bound.resolved
        assert "which end" in bound.because

    def test_a_position_past_the_end_is_asked_about_not_rounded(self):
        bound = nth.resolve(nth.read("What about the ninth one?"),
                            _state(THREE))
        assert not bound.resolved
        assert "does not reach" in bound.because
        assert "ninth" in nth.clarification(bound)

    def test_nothing_on_screen_binds_nothing(self):
        bound = nth.resolve(nth.read("And the first one?"),
                            cv.ConversationState())
        assert not bound.resolved


class TestWhatTheContinuationCarries:
    def test_the_continuation_carries_exactly_one_identity(self):
        carried = rf.resolve("Why does the second one worry you?",
                             _state(THREE, labels=NAMED))
        assert carried.entity_ids == ["SA-2"]
        assert carried.entity_key == "customer_id"
        assert carried.referent == "the second one"
        assert carried.ordinal["resolved"] is True
        assert carried.ordinal["label"] == "Beta Marine"

    def test_an_unbound_ordinal_never_falls_back_to_the_population(self):
        """The failure this exists to prevent, arriving by the polite route."""
        carried = rf.resolve("What about the ninth one?", _state(THREE))
        assert carried.entity_ids == [], (
            "an ordinal that could not bind widened to the whole population")
        assert carried.ordinal["resolved"] is False

    def test_an_unbound_ordinal_is_asked_about(self):
        asked = rf.unresolved("What about the ninth one?", _state(THREE))
        assert "Which row do you mean" in asked

    def test_a_bound_ordinal_is_not_asked_about(self):
        assert rf.unresolved("Why the second one?", _state(THREE)) == ""

    def test_the_ordinal_survives_a_presentation_change(self):
        """"Show the second one as a chart" changes the drawing, not the row."""
        read = rf.read("Show the second one as a chart.")
        assert read.action == cv.MODIFY_PRESENTATION
        assert read.ordinal is not None and read.ordinal.index == 1
