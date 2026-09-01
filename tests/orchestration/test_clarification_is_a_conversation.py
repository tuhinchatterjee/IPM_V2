"""A clarification is a question, not a menu of other questions. §5, §6.

What was observed
-----------------
"Identify the 10 borrowers with the highest probability of credit
deterioration over the next 12 months..." came back as a card. Beside it, four
buttons:

    exposure at default by sector
    largest exposures
    expected credit loss movement
    what data is available

None of them answers the question that was asked. Each is a DIFFERENT
question, and a person who presses one has abandoned the one they came with —
which is the definition of a dead end, dressed up as helpfulness.

The rule §6 states, and this suite holds
-----------------------------------------
A suggested response may be offered only when it DIRECTLY ANSWERS the
clarification. "Did you mean market value or net realisable value?" has two
answers and both belong on buttons. "Which figure do you want?" has no closed
set of answers, so it gets none, and the chat box — which was always there —
is where the reply goes.
"""

from __future__ import annotations

import pytest

from backend.orchestration import executor


class _Reading:
    reasoning = "The request did not name a governed measure."


class _Answered:
    question = "Tell me about the book."
    clarification = "Which figure should CreditProbe measure?"
    reading = _Reading()
    ambiguity: dict = {}


class TestAnOpenQuestionGetsNoMenu:

    def test_the_reading_clarification_offers_no_options(self):
        found = executor._reading_clarification(_Answered.question, _Answered())
        assert found is not None
        assert found.options == [], (
            f"still offering a menu: {found.options}")

    def test_it_still_says_what_to_do(self):
        """Removing the menu must not leave the reader with nothing.

        The counter-test: a clarification with no options and no guidance is
        the same dead end by subtraction.
        """
        found = executor._reading_clarification(_Answered.question, _Answered())
        assert found.question
        assert "Name the figure" in found.detail
        assert found.allow_custom is True

    def test_it_names_real_governed_measures_as_examples_not_buttons(self):
        """An example in prose reads as "the kind of thing to name". The same
        text on a button reads as "press this instead"."""
        found = executor._reading_clarification(_Answered.question, _Answered())
        assert "catalogue carries measures such as" in found.detail
        assert found.options == []

    @pytest.mark.parametrize("banned", [
        "by sector", "largest exposures", "What data is available",
    ])
    def test_the_four_observed_offers_are_gone(self, banned):
        found = executor._reading_clarification(_Answered.question, _Answered())
        labels = " ".join(str(o) for o in found.options)
        assert banned.lower() not in labels.lower()


class TestAClosedQuestionKeepsItsAnswers:
    """The counter-rule. §6 removes irrelevant options, not all options.

    "Market value or net realisable value?" is a question with exactly two
    answers, and making somebody type one of them back is worse than a button.
    """

    def test_an_ambiguity_offers_the_measures_it_is_between(self):
        class Ambiguous:
            question = "What is the exposure of the Contracting book?"
            ambiguity = {
                "question": "Which exposure measure?",
                "concept": "exposure",
                "business_name": "Exposure",
                "definition": "Two governed measures carry this name.",
                "options": [
                    {"label": "Exposure at default", "field": "ead",
                     "note": "post-CCF"},
                    {"label": "Drawn balance", "field": "drawn",
                     "note": "outstanding today"},
                ],
            }

        found = executor._ambiguity_clarification(Ambiguous())
        assert found is not None
        assert len(found.options) == 2
        labels = {o["label"] for o in found.options}
        assert labels == {"Exposure at default", "Drawn balance"}

    def test_each_option_is_the_users_own_question_with_one_word_settled(self):
        """An option that posts a DIFFERENT question is the §6 defect again."""
        class Ambiguous:
            question = "What is the exposure of the Contracting book?"
            ambiguity = {
                "question": "Which exposure measure?",
                "options": [{"label": "Exposure at default", "field": "ead"}],
            }

        found = executor._ambiguity_clarification(Ambiguous())
        asked = found.options[0]["question"]
        assert "Contracting" in asked, (
            "the option abandoned the population that was asked about")

    def test_no_ambiguity_means_no_card_at_all(self):
        class Plain:
            question = "q"
            ambiguity: dict = {}

        assert executor._ambiguity_clarification(Plain()) is None
