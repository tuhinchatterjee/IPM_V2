"""The conversation keeps the population it settled. §6.

The defect
----------
Turn 1: "Show total exposure at default for Financial Services in Q2 2026."
Turn 2: "Which borrowers are the real issues?"

The second sentence carries no referent word — no "those", no "them" — so
every reader in the pipeline called it a new request, and the analysis ran
over the whole portfolio. The answer was arithmetically correct and about a
different set of borrowers than the person was looking at, which is the worst
kind of wrong an analytical product can be: it looks right.

The state was never lost. `filters` carried "sector = Financial Services"
through the whole thread. Nothing read it, because reading it was conditional
on a referent phrase that a natural second question does not contain.

What holds now
--------------
A mid-thread question that names no population of its OWN continues the one
the conversation settled. The narrowness is the safety: a sentence naming a
sector, a stage, a rating band or the whole book states its own scope and is
left alone.
"""

from __future__ import annotations

import pytest

from backend.orchestration import composites as cmp
from backend.orchestration import conversation as cv
from backend.orchestration import memory as wm
from backend.orchestration import referents as rf
from backend.orchestration.executor import answer_investigation
from backend.orchestration.orchestrator import remember as advance
from backend.orchestration.vocabulary import get_vocabulary

SECTOR = "Financial Services"
OPENING = f"Show total exposure at default for {SECTOR} in Q2 2026."


class Thread:
    """A conversation, run the way the Investigation route runs one."""

    def __init__(self) -> None:
        self.context: dict = {}
        self.turns: list = []

    def ask(self, question: str):
        state, memory = cv.load(self.context), wm.load(self.context)
        investigation, answered = answer_investigation(
            question, persist=False, state=state, memory=memory)
        self.context = cv.save(self.context, advance(
            state, answered,
            headline=str(investigation.narrative.direct_answer or ""),
            run_id=None))
        self.context = wm.save(
            self.context, wm.observe(wm.load(self.context), answered,
                                     investigation))
        self.turns.append((investigation, answered))
        return investigation, answered

    @property
    def state(self) -> cv.ConversationState:
        return cv.load(self.context)

    def sectors(self) -> set[str]:
        """The sectors the last result actually covers."""
        _, answered = self.turns[-1]
        runtime = getattr(answered, "runtime", None)
        rows = list(getattr(runtime, "rows", None) or [])
        return {str(r["sector"]) for r in rows if r.get("sector")}


@pytest.fixture
def thread() -> Thread:
    started = Thread()
    started.ask(OPENING)
    assert started.state.filter_pairs() == [("sector", SECTOR)], (
        "the opening turn did not establish the population these tests are "
        "about")
    return started


class TestTheSettledPopulationIsKept:
    def test_the_acceptance_thread_stays_in_one_sector(self, thread: Thread):
        """Turn 1 sector, turn 2 the names in it, turn 3 the worst of those."""
        thread.ask("Which borrowers are the real issues?")
        assert thread.state.filter_pairs() == [("sector", SECTOR)]

        thread.ask("Which of those have the highest ECL?")
        assert thread.state.filter_pairs() == [("sector", SECTOR)]
        assert thread.sectors() in (set(), {SECTOR}), (
            "the third turn widened back to the whole book")

    @pytest.mark.parametrize("follow_up", [
        "Which borrowers are the real issues?",
        "Which names worry you most?",
        "Which borrowers require the most attention?",
        "Who are the worst names?",
        "Which borrowers have liquidity pressure?",
        "Show the ten largest by expected credit loss.",
    ])
    def test_a_follow_up_naming_no_population_keeps_this_one(
            self, thread: Thread, follow_up: str):
        thread.ask(follow_up)
        assert thread.state.filter_pairs() == [("sector", SECTOR)], (
            f"{follow_up!r} silently widened back to the whole portfolio")


class TestASentenceThatStatesItsOwnScopeIsLeftAlone:
    def test_naming_another_sector_replaces_the_population(self,
                                                           thread: Thread):
        thread.ask("Show total exposure at default for Real Estate.")
        assert thread.state.filter_pairs() == [("sector", "Real Estate")]

    def test_a_breakdown_by_the_filtered_field_drops_the_filter(
            self, thread: Thread):
        """"Total ECL by sector" wants every sector, not a table with one row."""
        thread.ask("Show total ECL by sector.")
        assert thread.state.filter_pairs() == []
        assert len(thread.sectors()) > 1

    def test_a_breakdown_reports_the_measure_that_was_asked_for(
            self, thread: Thread):
        """The guardrail carries the POPULATION, never the measure.

        Carrying the previous turn's measure as well answered "show total ECL
        by sector" with exposure at default — the right shape, the wrong
        figure, and no sign on screen that it had happened.
        """
        investigation, _ = thread.ask("Show total ECL by sector.")
        said = str(investigation.narrative.direct_answer or "").lower()
        assert "expected credit loss" in said
        assert "exposure at default" not in said

    def test_asking_for_the_whole_book_widens(self, thread: Thread):
        thread.ask("Now show me the whole portfolio's total ECL.")
        assert thread.state.filter_pairs() == []

    def test_a_catalogue_question_neither_inherits_nor_disturbs(
            self, thread: Thread):
        """Asking what data exists mid-investigation changes nothing. §12."""
        investigation, answered = thread.ask("What datasets do you have?")
        assert answered.reading.source == "catalogue"
        assert thread.state.filter_pairs() == [("sector", SECTOR)]
        assert "46" in str(investigation.narrative.direct_answer or "")


class TestTheScopeReader:
    @pytest.mark.parametrize("question", [
        "Show total exposure for Real Estate.",
        "Which Stage 2 borrowers are in arrears?",
        "Across the whole portfolio, what is total ECL?",
        "The whole book's exposure, please.",
        "List all borrowers with a covenant breach.",
    ])
    def test_these_sentences_state_their_own_scope(self, question: str):
        assert rf.states_its_own_scope(question, get_vocabulary()) is True

    @pytest.mark.parametrize("question", [
        "Which borrowers are the real issues?",
        "Which names worry you?",
        "Show the ten largest by ECL.",
        "What is the average DSCR?",
    ])
    def test_these_do_not(self, question: str):
        assert rf.states_its_own_scope(question, get_vocabulary()) is False


class TestTheCreditConcernComposite:
    """"The real issues" is a credit judgement, not a missing measure."""

    @pytest.mark.parametrize("question", [
        "Which borrowers are the real issues?",
        "Which names worry you?",
        "Which borrowers require the most attention?",
        "Who are the worst names?",
        "Which are the problem accounts?",
    ])
    def test_it_is_recognised(self, question: str):
        found = cmp.find(question)
        assert found is not None
        assert found.composite.key == "credit_concern"

    @pytest.mark.parametrize("question", [
        "Which borrowers are in Contracting?",
        "Show total EAD by sector.",
        "List the 20 borrowers with the highest PD.",
    ])
    def test_an_ordinary_question_is_not_captured(self, question: str):
        assert cmp.find(question) is None

    def test_a_liquidity_question_still_gets_the_liquidity_reading(self):
        """Both patterns match "liquidity problems"; the specific one wins."""
        found = cmp.find("Which borrowers have liquidity problems?")
        assert found is not None
        assert found.composite.key == "liquidity_stress"

    def test_it_ranks_borrowers_rather_than_reporting_one_figure(
            self, thread: Thread):
        _, answered = thread.ask("Which borrowers are the real issues?")
        rows = list(getattr(answered.runtime, "rows", None) or [])
        assert len(rows) > 1
        assert "customer_id" in rows[0]
        assert "credit_concern_signals" in rows[0]
        counts = [int(r["credit_concern_signals"]) for r in rows]
        assert counts == sorted(counts, reverse=True)
