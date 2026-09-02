"""«Why Shipping?» keeps the analysis and changes the book. §4, §5, §9, §11.

The defect
----------
    Turn 1: "Which sectors concern you most?"  → a ranking of borrowers
    Turn 2: "Why Shipping?"                    → "Which figure should
                                                  CreditProbe measure?"

Three words that name a governed sector and no measure. Read as a new request
they name no figure at all, so the planner asked for one — the product asking
the reader to restate the analysis it had just run — and because a
clarification settles nothing, every turn after it ran over the whole book.

The three inheritances this covers
----------------------------------
**Scope.** A sentence that names only a dimension value narrows the analysis
that just ran to that value, replacing whatever was settled for the same
dimension and carrying none of the previous result's rows.

**Measure.** A sentence that points back and names no figure means the figure
the conversation settled.

**A pending question.** A reply to a clarification is merged with the question
that provoked it rather than read as a fresh request.

And what must NOT be inherited: a question about the catalogue, a question that
names its own measure, and a sentence that deliberately widens back out.
"""

from __future__ import annotations

import pytest

from backend.orchestration import conversation as cv
from backend.orchestration import referents as rf

SETTLED = cv.ConversationState(
    subject="borrowers ranked by credit concern",
    metrics=["expected credit loss"],
    concepts=["expected credit loss"],
    ir={"operations": [{"op": "SCAN", "params": {}}]},
    plan_summary="Borrowers ranked by governed credit concern signals.",
    result=cv.ResultShape(entity_key="customer_id",
                          entity_ids=["SA-1", "SA-2"], row_count=2,
                          question="Which sectors concern you most?"),
    turns=[cv.Turn(question="Which sectors concern you most?")],
)


class TestASentenceThatNamesOnlyAScope:
    @pytest.mark.parametrize("question,dimension,value", [
        ("Why Shipping?", "sector", "Shipping"),
        ("And Contracting?", "sector", "Contracting"),
        ("What about Real Estate?", "sector", "Real Estate"),
        ("How about Riyadh?", "region", "Riyadh"),
        ("Shipping", "sector", "Shipping"),
        ("Why is it Healthcare?", "sector", "Healthcare"),
    ])
    def test_the_governed_value_is_read_in_the_catalogue_spelling(
            self, question: str, dimension: str, value: str):
        assert rf.names_only_a_scope(question) == (dimension, value)

    @pytest.mark.parametrize("question", [
        "Show total exposure at default for Shipping.",
        "Why is Shipping the worst sector this quarter?",
        "Which borrowers are the real issues?",
        "Why?",
        "What fields does the ratings data have?",
    ])
    def test_a_sentence_that_says_more_names_no_bare_scope(self,
                                                           question: str):
        assert rf.names_only_a_scope(question) is None

    def test_it_narrows_the_analysis_that_just_ran(self):
        carried = rf.resolve("Why Shipping?", SETTLED)
        assert carried.action == cv.NARROW_SCOPE
        assert carried.carries_context
        assert "Shipping" in carried.inherited["scope"]

    def test_it_carries_no_rows_from_the_previous_answer(self):
        """Shipping is a book, not the intersection of Shipping with a list."""
        carried = rf.resolve("Why Shipping?", SETTLED)
        assert carried.entity_ids == []
        assert "none" in carried.inherited["population"]

    def test_an_opening_sentence_narrows_nothing(self):
        """There is no analysis to keep, so this is an ordinary request."""
        carried = rf.resolve("Why Shipping?", cv.ConversationState())
        assert carried.action == cv.NEW_REQUEST


class TestTheMeasureIsInheritedWhenTheSentenceNamesNone:
    def test_a_question_pointing_back_with_no_measure_continues(self):
        carried = rf.resolve("Which borrowers drove that?", SETTLED)
        assert carried.action == cv.CONTINUE
        assert "expected credit loss" in carried.inherited.get("measure", "")

    @pytest.mark.parametrize("question,named", [
        ("Which borrowers drove that?", False),
        ("Break that down by sector.", False),
        ("Show total ECL by sector.", True),
        ("Rank those by exposure at default.", True),
    ])
    def test_whether_the_sentence_names_its_own_measure(self, question: str,
                                                        named: bool):
        assert rf.names_a_measure(question) is named

    def test_a_sentence_that_names_its_own_measure_does_not_inherit_one(self):
        carried = rf.resolve("Show total ECL by sector.", SETTLED)
        assert "measure" not in carried.inherited

    def test_nothing_is_inherited_before_an_analysis_has_run(self):
        carried = rf.resolve("Which borrowers drove that?",
                             cv.ConversationState())
        assert carried.action == cv.NEW_REQUEST


class TestAReplyToAClarification:
    @pytest.mark.parametrize("reply", [
        "Expected credit loss.",
        "The 12-month PD",
        "Yes, since last quarter",
        "Shipping",
        "exposure at default",
    ])
    def test_a_short_fragment_answers_the_question_that_was_asked(
            self, reply: str):
        assert cv.answers_a_clarification(reply)

    @pytest.mark.parametrize("reply", [
        "Which borrowers drove that?",
        "Show me the ten largest customers by exposure at default.",
        "How has expected credit loss changed since last year?",
        "",
    ])
    def test_a_question_of_its_own_is_not_a_reply(self, reply: str):
        assert not cv.answers_a_clarification(reply)

    def test_the_pending_question_survives_serialisation(self):
        state = cv.ConversationState(pending="How has it changed?")
        assert cv.ConversationState.from_dict(state.to_dict()).pending == (
            "How has it changed?")


class TestWhatMustNotBeInherited:
    def test_a_catalogue_question_keeps_no_population(self):
        """A dataset's schema does not vary by sector."""
        scoped = cv.ConversationState(
            subject="exposure in Shipping",
            filters=[{"kind": "sector", "value": "Shipping"}],
            ir={"operations": []},
            result=cv.ResultShape(entity_key="customer_id",
                                  entity_ids=["SA-1"], row_count=1))
        carried = rf.resolve("What fields does the ratings data have?", scoped)
        assert carried.action != cv.NARROW_SCOPE
        assert not carried.entity_ids

    def test_widening_back_out_drops_what_was_carried(self):
        scoped = cv.ConversationState(
            subject="exposure in Shipping",
            filters=[{"kind": "sector", "value": "Shipping"}],
            ir={"operations": []},
            result=cv.ResultShape(entity_key="customer_id",
                                  entity_ids=["SA-1"], row_count=1))
        carried = rf.resolve(
            "Now across the whole portfolio, what is total exposure at "
            "default?", scoped)
        assert carried.action == cv.RESET_SCOPE
        assert carried.entity_ids == []
