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

_CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "whatif_cases.json").read_text())
CASES = _CORPUS["cases"]
#: Questions the product does not yet read the way it should, kept in the file
#: rather than deleted. A corpus containing only what the classifier already
#: gets right measures nothing.
GAPS = _CORPUS.get("known_gaps", [])


def _read(case: dict):
    """Classify a case in the thread state the case describes.

    The same sentence is a different intent depending on what is on screen:
    "increase PD by 20%" OPENS a scenario in an empty thread and MODIFIES one
    in a thread that already has steps. A corpus that ignored that would be
    testing half the classifier.
    """
    return iv.classify(case["question"],
                       has_result=bool(case.get("has_result")),
                       has_steps=bool(case.get("has_steps")))


def _id(case: dict) -> str:
    return case["question"][:60]


class TestTheCorpusItself:
    def test_it_is_large_enough_to_be_evidence(self) -> None:
        assert len(CASES) >= 100, (
            "a handful of questions is a demonstration, not an evaluation")

    def test_every_intent_is_represented(self) -> None:
        seen = {case["intent"] for case in CASES}
        assert seen == set(iv.INTENTS)
        for intent in iv.INTENTS:
            assert sum(1 for c in CASES if c["intent"] == intent) >= 10, intent

    def test_no_question_appears_twice(self) -> None:
        questions = [c["question"] for c in CASES]
        assert len(questions) == len(set(questions))

    def test_every_intent_is_exercised_in_the_state_it_needs(self) -> None:
        """An intent that only exists after a result must be tested after one,
        and one that opens a thread must be tested from an empty one."""
        after = {iv.EXPLAIN, iv.VIEW, iv.MODIFY, iv.COMPARISON,
                 iv.EXPLAINABILITY, iv.EXPORT}
        for case in CASES:
            if case["intent"] in after:
                assert case.get("has_result"), case["question"]
            if case["intent"] == iv.SCENARIO:
                assert not case.get("has_steps"), case["question"]


class TestTheKnownGaps:
    """What the product does NOT do, written down where it can be checked.

    A gap that is only in somebody's head gets fixed by accident or not at
    all. Each of these says what happens today and what should — so when one
    is closed, this test fails and the record is updated with the fix.
    """

    def test_each_gap_names_what_happens_and_what_should(self) -> None:
        for gap in GAPS:
            assert gap["question"] and gap["why"], gap
            assert gap["reads_as"] in iv.INTENTS, gap
            assert gap["should_be"] in iv.INTENTS, gap

    def test_each_gap_still_reads_the_way_it_is_recorded(self) -> None:
        """The record is only useful while it is true."""
        for gap in GAPS:
            found = iv.classify(gap["question"], has_result=True,
                                has_steps=True)
            assert found.intent == gap["reads_as"], (
                f"{gap['question']!r} now reads as {found.intent}, not "
                f"{gap['reads_as']}. If that is the fix, remove the gap.")

    def test_no_gap_silently_changes_the_scenario(self) -> None:
        """A capability the product lacks must fail safe: answering the wrong
        question is recoverable, quietly moving a number is not."""
        for gap in GAPS:
            found = iv.classify(gap["question"], has_result=True,
                                has_steps=True)
            if found.intent != gap["should_be"]:
                assert not found.changes_state, gap["question"]


@pytest.mark.parametrize("case", CASES, ids=_id)
class TestEveryCase:
    def test_the_intent_is_read_correctly(self, case) -> None:
        reading = _read(case)
        assert reading.intent == case["intent"], (
            f"{case['question']!r} was read as {reading.intent}")

    def test_the_family_follows_the_intent(self, case) -> None:
        reading = _read(case)
        assert reading.family == iv.FAMILY[case["intent"]]

    def test_only_a_scenario_change_may_move_the_thread(self, case) -> None:
        """The invariant the whole taxonomy exists to protect: a question
        never changes a number."""
        reading = _read(case)
        assert reading.changes_state is (reading.family == iv.CHANGES)

    def test_only_a_modification_may_change_state(self, case) -> None:
        reading = _read(case)
        expected = case.get("changes_state")
        if expected is None:
            return
        assert reading.changes_state is expected

    def test_the_topic_is_recognised(self, case) -> None:
        wanted = case.get("topic")
        if not wanted:
            return
        assert _read(case).topic == wanted

    def test_the_dimension_is_recognised(self, case) -> None:
        wanted = case.get("dimension")
        if not wanted:
            return
        assert _read(case).dimension == wanted

    def test_a_view_of_the_result_is_told_from_a_question_about_the_book(
            self, case) -> None:
        if "about_the_result" not in case:
            return
        assert _read(case).about_the_result is case["about_the_result"]

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
