"""«moved» is «changed» — Phase 0B.

The regression these hold shut: "How has ECL changed?" routed to the certified
ECL movement and "How has ECL moved?" came back with the level at the latest
quarter. One vocabulary, read by every layer, or the answer depends on which
synonym the user happened to reach for.
"""

from __future__ import annotations

import pytest

from backend.orchestration import capability as cap
from backend.orchestration import certified as cert
from backend.orchestration import conversation as cv
from backend.orchestration import movement as mv
from backend.orchestration import referents
from backend.orchestration.router import _operation, _period_requirement


class TestTheWordIsRead:
    """Every spelling of "this is about a change" reaches the same reading."""

    @pytest.mark.parametrize("question", [
        "How has ECL moved?",
        "How has ECL changed?",
        "How has the impairment moved?",
        "What moved?",
        "What changed?",
        "How has coverage shifted?",
        "Has provision cover moved?",
        "ECL movement since last year",
        "How has EAD risen?",
        "Which sectors deteriorated?",
        "Compare Stage 2 exposure year on year",
        "Show total ECL over the latest year",
    ])
    def test_a_change_question_is_read_as_one(self, question):
        assert mv.asks_for_change(question) is True

    @pytest.mark.parametrize("question", [
        "What is total ECL in the latest quarter?",
        "Show the five largest Real Estate customers by EAD.",
        "How many borrowers are in Stage 2?",
        "What is the average interest coverage by sector?",
        "Which borrowers have a 12-month moving average PD above 2%?",
        "Move this to the Contracting sector.",
        "Show the relationship between PD and LGD.",
    ])
    def test_a_level_question_is_not(self, question):
        assert mv.asks_for_change(question) is False


class TestMigrationIsNotAMeasureMovement:
    """"Moved to stage 3" asks which accounts crossed a line.

    Read as a measure movement it produced "Stage migration was unchanged from
    1.00 to 1.00 between Q2 2025 and Q2 2026" — the stage column averaged
    across two dates and presented as a finding. Worse than not reading the
    movement at all.
    """

    @pytest.mark.parametrize("question", [
        "Which of these moved to Stage 3?",
        "Which borrowers moved into Stage 2?",
        "Which names shifted to a worse grade?",
        "How many accounts transitioned to Stage 3?",
    ])
    def test_a_destination_is_not_a_movement(self, question):
        assert mv.asks_for_change(question) is False

    def test_the_rest_of_the_sentence_still_reads(self):
        # Blanked, not deleted: a sentence that asserts BOTH keeps its movement.
        assert mv.asks_for_change(
            "PD rose and three names moved to stage 3") is True

    def test_a_measure_movement_may_still_say_to(self):
        # "moved from X to Y" names the endpoints of a measure movement with
        # the same preposition. Masking that would lose the reading.
        assert mv.asks_for_change("ECL moved from 5,248 to 5,313") is True

    def test_to_date_is_not_a_destination(self):
        assert mv.asks_for_change("How has ECL moved to date?") is True


class TestTheRouterAgrees:
    """The layer that decides one period or two reads the same words."""

    @pytest.mark.parametrize("question", [
        "How has ECL moved?",
        "How has ECL changed?",
        "What moved?",
    ])
    def test_a_movement_question_wants_two_periods(self, question):
        assert _period_requirement(question, "ANALYSIS") == "two_period"

    def test_a_level_question_wants_one(self):
        assert _period_requirement(
            "What is total ECL in the latest quarter?",
            "ANALYSIS") == "point_in_time"

    def test_migration_phrasing_does_not_force_two_periods(self):
        assert _period_requirement(
            "Which of these moved to Stage 3?", "ANALYSIS") == "point_in_time"

    def test_a_non_computing_intent_is_untouched(self):
        assert _period_requirement("How has ECL moved?", "chit_chat") == "none"

    @pytest.mark.parametrize("question", [
        "How has ECL moved?", "How has ECL changed?",
    ])
    def test_both_spellings_pick_the_same_operation(self, question):
        assert _operation(question) == "compare"

    def test_migration_phrasing_is_not_a_comparison(self):
        assert _operation("Which of these moved to Stage 3?") != "compare"


class TestForwardLookingQuestionsAreStillProtected:
    """§3: a likelihood at one date is not a comparison across two."""

    @pytest.mark.parametrize("question", [
        "The 10 borrowers with the highest probability of credit "
        "deterioration over the next 12 months",
        "Which names have the highest likelihood of downgrade?",
    ])
    def test_a_forecast_is_point_in_time(self, question):
        assert _period_requirement(question, "ANALYSIS") == "point_in_time"

    def test_a_real_movement_beside_a_forecast_still_reads(self):
        assert _period_requirement(
            "PD rose last quarter; who is most likely to deteriorate "
            "next year?", "ANALYSIS") == "two_period"


class TestASubjectlessChangeQuestionContinues:
    """"What moved?" borrows the measure the conversation is already about.

    It came back as "Which figure should CreditProbe measure?" — asking the
    reader to repeat what they had said one sentence earlier.
    """

    @pytest.mark.parametrize("question", [
        "What moved?", "What changed?", "What has changed?",
        "What's moved?", "And what changed?", "So what has moved?",
        "What had changed?", "What shifted?",
    ])
    def test_it_is_subjectless(self, question):
        assert mv.subjectless(question) is True

    @pytest.mark.parametrize("question", [
        "What changed in Real Estate?",
        "What moved the ECL?",
        "What is total ECL?",
        "Which sectors moved?",
        "How has ECL moved?",
    ])
    def test_a_question_with_a_subject_of_its_own_is_not(self, question):
        assert mv.subjectless(question) is False

    @pytest.mark.parametrize("question", [
        "What moved?", "What changed?", "What has changed?",
    ])
    def test_the_conversation_continues(self, question):
        assert referents.read(question).action == cv.CONTINUE

    def test_a_question_with_its_own_population_does_not(self):
        assert referents.read(
            "What changed in Real Estate?").action == cv.NEW_REQUEST


class TestTheCertifiedTieBreakReadsTheSameVocabulary:
    """The two-period methodology is picked by the same words, both ways."""

    def _match(self, analysis_id, requirement, overlap=0.8):
        return cert.Match(analysis_id=analysis_id, name=analysis_id,
                          overlap=overlap, matched="", when_to_use="",
                          period_requirement=requirement)

    @pytest.mark.parametrize("question", [
        "How has ECL moved?", "How has ECL changed?",
    ])
    def test_a_tie_goes_to_the_two_period_methodology(self, question):
        found = [self._match("ecl_waterfall", "point_in_time"),
                 self._match("ecl_movement", "two_period")]
        picked = cert._pick(found, question, cap.Reading(intent="ANALYSIS"))
        assert picked is not None
        assert picked.analysis_id == "ecl_movement"

    def test_a_level_question_goes_to_the_point_in_time_one(self):
        found = [self._match("ecl_waterfall", "point_in_time"),
                 self._match("ecl_movement", "two_period")]
        picked = cert._pick(found, "Show me the ECL waterfall", cap.Reading(intent="ANALYSIS"))
        assert picked is not None
        assert picked.analysis_id == "ecl_waterfall"

    def test_the_weak_words_are_read_only_here(self):
        # "between" breaks a tie between two already-matched methodologies…
        assert mv.asks_for_change("ECL between Q1 and Q2", weak=True) is True
        # …and never decides, from nothing, that a question is a comparison.
        assert mv.asks_for_change(
            "Show the relationship between PD and LGD") is False


class TestTheContractDeclaresBothSpellings:
    """A methodology says which questions it answers. Both are questions."""

    def test_ecl_movement_declares_moved(self):
        from backend.engine.registry import get_registry

        contract = get_registry().contract("ecl_movement")
        asked = " ".join(contract.trigger_questions).lower()
        assert "moved" in asked
        assert "changed" in asked
