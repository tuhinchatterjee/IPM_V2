"""
Seventy-six things a person says to a What-If thread, and what must happen.

The corpus is the acceptance criterion for the conversational layer. It is
deliberately answerable WITHOUT a language model: the intent classifier and the
scenario reader are regular expressions over a governed vocabulary, so the same
sentence always produces the same reading, and a change that makes one question
work by breaking another is visible here rather than in a demonstration.

What each case asserts, and why that particular thing:

* **The intent**, because it decides whether the scenario state may be touched.
  An EXPLAIN that reached the builder is how "Why did Stage 3 ECL increase?"
  became a shock nobody asked for.
* **The population**, because a filter that parsed and was then dropped is how
  "downgrade construction borrowers with exposure above SAR 100m" priced the
  whole book. Every case that states a filter asserts it survived.
* **The refusal**, because a question about the retail book is not a Corporate
  IFRS 9 What-If and answering it from this domain would be worse than saying
  no.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backend.whatif import investigate as iv
from backend.whatif import language as lg
from backend.whatif import run as rn

CASES = json.loads(
    (pathlib.Path(__file__).parent / "whatif_cases.json").read_text())["cases"]


def _id(case: dict) -> str:
    return case["question"][:60]


class TestTheCorpusItself:
    def test_it_is_large_enough_to_be_evidence(self) -> None:
        assert len(CASES) >= 75, (
            "a handful of questions is a demonstration, not an evaluation")

    def test_every_intent_is_represented(self) -> None:
        seen = {case["intent"] for case in CASES}
        assert seen == set(iv.INTENTS)
        for intent in iv.INTENTS:
            assert sum(1 for c in CASES if c["intent"] == intent) >= 10, intent

    def test_no_question_appears_twice(self) -> None:
        questions = [c["question"] for c in CASES]
        assert len(questions) == len(set(questions))


@pytest.mark.parametrize("case", CASES, ids=_id)
class TestEveryCase:
    def test_the_intent_is_read_correctly(self, case) -> None:
        reading = iv.classify(case["question"])
        assert reading.intent == case["intent"], (
            f"{case['question']!r} was read as {reading.intent}")

    def test_only_a_modification_may_change_state(self, case) -> None:
        reading = iv.classify(case["question"])
        expected = case.get("changes_state")
        if expected is None:
            return
        assert reading.changes_state is expected

    def test_the_topic_is_recognised(self, case) -> None:
        wanted = case.get("topic")
        if not wanted:
            return
        assert iv.classify(case["question"]).topic == wanted

    def test_the_dimension_is_recognised(self, case) -> None:
        wanted = case.get("dimension")
        if not wanted:
            return
        assert iv.classify(case["question"]).dimension == wanted

    def test_a_view_of_the_result_is_told_from_a_question_about_the_book(
            self, case) -> None:
        if "about_the_result" not in case:
            return
        assert (iv.classify(case["question"]).about_the_result
                is case["about_the_result"])

    def test_the_scenario_reader_agrees_about_whether_this_is_a_scenario(
            self, case) -> None:
        if "reads_as_scenario" not in case:
            return
        read = lg.read(case["question"])
        assert (read.scenario is not None) is case["reads_as_scenario"]

    def test_a_magnitude_free_what_if_is_asked_about_rather_than_guessed(
            self, case) -> None:
        if not case.get("must_ask_magnitude"):
            return
        read = lg.read(case["question"])
        assert read.scenario is None, (
            "no magnitude was stated, so no scenario may be built")
        assert getattr(read, "opens_whatif", False), (
            "but it IS a What-If, so the product must ask how big rather than "
            "route it to a profile screen")

    def test_a_report_does_not_open_a_what_if_at_all(self, case) -> None:
        """A statement about what the book already did is not an instruction.

        "Shipping has deteriorated. Show me everything." is a request for a
        segment review — a named set of ten analyses — and reading the perfect
        tense as an imperative answered it with one What-If instead.
        """
        if not case.get("must_not_open_whatif"):
            return
        read = lg.read(case["question"])
        assert read.scenario is None
        assert not getattr(read, "opens_whatif", False), (
            "the product would route this to the scenario engine and take the "
            "question away from the analysis that owns it")

    def test_an_informational_question_needs_no_methodology(self, case) -> None:
        if not case.get("informational"):
            return
        assert rn.informational(case["question"])

    def test_a_stated_filter_survives_into_the_population(self, case) -> None:
        if "expect_sectors" not in case:
            return
        scenario = lg.read(case["question"]).scenario
        assert scenario is not None
        population = scenario.population
        if case["expect_sectors"]:
            assert set(population.sectors) == set(case["expect_sectors"])
        assert len(population.thresholds) == case["expect_thresholds"]
        assert population.top_n == case["expect_top_n"]

    def test_a_narrowed_scenario_is_never_read_as_the_whole_book(self, case) -> None:
        if not case.get("must_not_be_whole_book"):
            return
        scenario = lg.read(case["question"]).scenario
        assert scenario is not None
        assert not scenario.population.is_whole_book, (
            "a filter that parsed and was then dropped is how a scenario "
            "aimed at a dozen names priced three thousand")

    def test_something_outside_the_domain_is_refused(self, case) -> None:
        """A question about another book is refused, not mapped.

        "Downgrade the retail mortgage book by two notches" resolved "retail"
        to the corporate Wholesale & Retail Trade SECTOR and priced a corporate
        scenario against it — a confident number about the wrong portfolio,
        which is worse than no answer.
        """
        if not case.get("outside_domain"):
            return
        read = lg.read(case["question"])
        assert read.scenario is None, (
            "a scenario was built for a book this engine does not read")
        assert read.notes, "and the refusal has to say why"
        assert "different book" in " ".join(read.notes)
