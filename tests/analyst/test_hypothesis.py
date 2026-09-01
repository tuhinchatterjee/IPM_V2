"""
Latitude to form a hypothesis, and the labels that make it safe. R2 §9, §23.

Two failures are possible here and they are opposite. An analyst that may only
restate the table is not an analyst; an analyst whose hypothesis is
indistinguishable from a fact is worse than either. So the tests come in
pairs: the reading survives, AND it stays marked as a reading.

Every test uses a scripted provider. No live call, no credits.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.analyst import session
from backend.analyst.evidence import Observation
from backend.analyst.safety import Principal
from backend.llm.base import LLMResult


class Says:
    """A provider that answers with exactly the document a test hands it."""

    name = "test"
    model = "scripted"
    configured = True

    def __init__(self, *documents: dict[str, Any]) -> None:
        self.script = list(documents)
        self.calls = 0

    def structured(self, **_: Any) -> LLMResult:
        self.calls += 1
        if not self.script:
            raise AssertionError("the loop asked for a turn the script "
                                 "does not provide")
        return LLMResult(data=self.script.pop(0), model=self.model)


def answer(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "action": "ANSWER", "why": "answering",
        "answer": "Shipping deteriorated.",
        "findings": [], "unavailable": [], "limitations": [],
    }
    base.update(over)
    return base


def gathered(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "action": "CALL_TOOL", "tool": "list_datasets", "arguments": {},
        "why": "looking",
    }
    base.update(over)
    return base


@pytest.fixture()
def analyst() -> Principal:
    return Principal(user_id=1, role="ANALYST")


class TestTheAnalystMayFormAHypothesis:
    def test_an_interpretation_reaches_the_investigation(self,
                                                         analyst: Principal
                                                         ) -> None:
        found = session.investigate("Why?", analyst, provider=Says(answer(
            interpretation="This looks like a working-capital squeeze "
                           "rather than a solvency problem.")))
        assert "working-capital squeeze" in found.interpretation

    def test_alternatives_and_what_would_settle_it_reach_it_too(
            self, analyst: Principal) -> None:
        found = session.investigate("Why?", analyst, provider=Says(answer(
            interpretation="A working-capital squeeze.",
            alternatives=["Seasonal drawdown that reverses next quarter."],
            confirm_or_refute=["The cash-flow forecast for the next two "
                               "quarters."])))
        assert found.alternatives == [
            "Seasonal drawdown that reverses next quarter."]
        assert found.confirm_or_refute == [
            "The cash-flow forecast for the next two quarters."]

    def test_external_context_reaches_it(self, analyst: Principal) -> None:
        found = session.investigate("Why?", analyst, provider=Says(answer(
            external_context=["A governed shipping-disruption scenario is "
                              "live this quarter and names this sector."])))
        assert found.external_context
        assert "shipping-disruption" in found.external_context[0]

    def test_the_hypothesis_is_published_apart_from_the_answer(
            self, analyst: Principal) -> None:
        # Apart, because a hypothesis folded into the answer text is a
        # hypothesis a reader cannot tell from a fact.
        found = session.investigate("Why?", analyst, provider=Says(answer(
            answer="Shipping deteriorated.",
            interpretation="Probably the trade route.")))
        shown = found.to_dict()
        assert shown["answer"] == "Shipping deteriorated."
        assert shown["interpretation"] == "Probably the trade route."

    def test_an_answer_with_no_hypothesis_is_still_a_complete_answer(
            self, analyst: Principal) -> None:
        # A question the figures answer on their own does not need a reading,
        # and a screen that demanded one would get invented ones.
        found = session.investigate("How many?", analyst,
                                    provider=Says(answer()))
        assert found.answered
        assert found.interpretation == ""
        assert found.alternatives == []


class TestAHypothesisMayNotInventAFigure:
    @staticmethod
    def _script(**over: Any) -> Says:
        return Says(gathered(), answer(**over))

    def test_an_untraceable_figure_is_removed_from_the_interpretation(
            self, analyst: Principal) -> None:
        provider = self._script(
            interpretation="Utilisation reached 94.7%, which reads as a "
                           "squeeze. The direction is what matters.")
        found = session.investigate("Why?", analyst, provider=provider)
        assert "94.7" not in found.interpretation

    def test_the_opinion_survives_when_the_figure_is_removed(
            self, analyst: Principal) -> None:
        # This is the pair to the test above, and it is the important one: a
        # reading run through the grounding filter whole would come out empty,
        # which is the same as never having offered a reading.
        provider = self._script(
            interpretation="Utilisation reached 94.7%, which reads as a "
                           "squeeze. The direction is what matters.")
        found = session.investigate("Why?", analyst, provider=provider)
        assert "direction is what matters" in found.interpretation

    def test_an_alternative_carrying_an_invented_figure_is_dropped(
            self, analyst: Principal) -> None:
        provider = self._script(
            alternatives=["Seasonal, as in the 12.4% swing last year.",
                          "A one-off payment timing difference."])
        found = session.investigate("Why?", analyst, provider=provider)
        assert found.alternatives == [
            "A one-off payment timing difference."]

    def test_a_reading_with_no_figures_is_left_entirely_alone(
            self, analyst: Principal) -> None:
        provider = self._script(
            interpretation="This looks like a liquidity problem, not a "
                           "solvency one.",
            alternatives=["The borrower may simply be holding cash back."])
        found = session.investigate("Why?", analyst, provider=provider)
        assert found.interpretation.startswith("This looks like")
        assert len(found.alternatives) == 1


class TestTheContractTheModelIsGiven:
    def test_the_schema_offers_all_four_fields(self) -> None:
        properties = session.DECISION_SCHEMA["properties"]
        for name in ("interpretation", "alternatives", "confirm_or_refute",
                     "external_context"):
            assert name in properties, name

    def test_the_rules_forbid_asserting_cause_from_coincidence(self) -> None:
        # §23. The wording is load-bearing: it is the only thing standing
        # between "these moved together" and "this caused that".
        assert "coincidence until something links them" in session.SYSTEM
        assert "consistent with" in session.SYSTEM

    def test_the_rules_require_an_alternative_beside_an_interpretation(
            self) -> None:
        assert "no alternative is an assertion" in session.SYSTEM


class TestGroundingStillHoldsForFacts:
    def test_a_figure_in_the_ANSWER_is_still_removed(self,
                                                     analyst: Principal
                                                     ) -> None:
        # The latitude is for the reading. The answer is still a statement of
        # fact and is still held to the evidence.
        provider = Says(gathered(),
                        answer(answer="Exposure is SAR 412.9m."))
        found = session.investigate("How much?", analyst, provider=provider)
        assert "412.9" not in found.answer
        assert found.removed

    def test_the_evidence_ledger_is_unchanged_by_any_of_this(
            self, analyst: Principal) -> None:
        provider = Says(gathered(), answer(interpretation="A view."))
        found = session.investigate("Why?", analyst, provider=provider)
        assert found.ledger.observations
        assert all(isinstance(o, Observation)
                   for o in found.ledger.observations)
