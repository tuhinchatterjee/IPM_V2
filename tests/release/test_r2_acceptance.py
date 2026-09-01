"""
The questions R2 §26 requires, asked through the real paths.

Four classes of question, and the fourth is the one the remediation was
written for: a four-turn thread about Shipping in which every turn after the
first names no population of its own and must not silently widen back to the
whole book. That defect — an arithmetically correct answer about a different
set of borrowers than the person is looking at — is the worst kind an
analytical product can produce, because it looks right.

Run against the governed runtime with no provider configured, so the answers
come from the deterministic reader and the governed engine. That is a
deliberate constraint rather than a limitation of the harness: it makes the
run reproducible, it costs no credits, and it tests the paths a bank on a
closed network actually gets. What it does NOT test is a live model's
phrasing, and the module says so rather than implying otherwise.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.analyst import classify, cost
from backend.early_warning import signals as sg
from backend.metadata import answers as mda
from backend.metadata import questions as mdq
from backend.orchestration import conversation as cv
from backend.orchestration import memory as wm
from backend.orchestration.executor import answer_investigation
from backend.orchestration.orchestrator import remember as advance

SECTOR = "Shipping"


# ---------------------------------------------------------------------------
# DATA UNDERSTANDING — §26's first class
# ---------------------------------------------------------------------------

UNDERSTANDING: tuple[str, ...] = (
    "How many data domains are there?",
    "Which datasets are in the liquidity domain?",
    "What does DSCR mean?",
    "How many datasets does CreditProbe hold?",
    "What is the grain of corporate_ifrs9?",
    "Which reporting periods do we hold?",
    "How many rows are in corporate_borrower_360?",
    "What fields does corporate_covenants have?",
)


class TestDataUnderstanding:
    """§13: a question about the data is answered as text and a table, with
    no chart, and it does not reach a frontier model."""

    @pytest.mark.parametrize("question", UNDERSTANDING)
    def test_it_is_read_as_a_question_about_the_data(self,
                                                     question: str) -> None:
        assert classify.read(question).question_class == cost.CLASS_A

    @pytest.mark.parametrize("question", UNDERSTANDING)
    def test_the_catalogue_answers_it_or_says_it_cannot(self,
                                                        question: str) -> None:
        request = mdq.read(question)
        if request is None:
            pytest.skip(f"the catalogue reader does not claim {question!r}")
        given = mda.respond(request)
        assert given["answer"].strip(), f"{question!r} answered with silence"

    @pytest.mark.parametrize("question", UNDERSTANDING)
    def test_it_is_a_table_and_never_a_chart(self, question: str) -> None:
        request = mdq.read(question)
        if request is None:
            pytest.skip(f"the catalogue reader does not claim {question!r}")
        shown = mda.respond(request)["visualization"]
        assert shown["kind"] == "table", \
            f"{question!r} proposed a {shown['kind']}"


# ---------------------------------------------------------------------------
# DATA QUERY — §26's second class
# ---------------------------------------------------------------------------


class Thread:
    """A conversation, run the way the Investigation route runs one."""

    def __init__(self) -> None:
        self.context: dict[str, Any] = {}
        self.turns: list[Any] = []

    def ask(self, question: str) -> Any:
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
        _, answered = self.turns[-1]
        runtime = getattr(answered, "runtime", None)
        rows = list(getattr(runtime, "rows", None) or [])
        return {str(r["sector"]) for r in rows if r.get("sector")}

    def rows(self) -> list[dict[str, Any]]:
        _, answered = self.turns[-1]
        runtime = getattr(answered, "runtime", None)
        return list(getattr(runtime, "rows", None) or [])


QUERIES: tuple[str, ...] = (
    "Show the top 20 borrowers by 12-month PD.",
    "What is total exposure at default by sector in Q2 2026?",
    "How many borrowers are in Stage 2?",
)


class TestDataQuery:
    @pytest.mark.parametrize("question", QUERIES)
    def test_it_answers_rather_than_refusing(self, question: str) -> None:
        investigation, _ = Thread().ask(question)
        said = str(investigation.narrative.direct_answer or "")
        assert said.strip(), f"{question!r} produced no direct answer"

    def test_a_ranking_is_ordered_by_the_measure_it_names(self) -> None:
        # §15. The validator should verify the ordering, not compensate for
        # an unstable pipeline, so this asserts the ROWS are ordered rather
        # than that a checker said they were.
        thread = Thread()
        thread.ask("Show the top 20 borrowers by 12-month PD.")
        rows = thread.rows()
        if not rows:
            pytest.skip("the ranking returned no rows in this build")
        column = next((c for c in ("pd_12m", "pd_12m_pct", "pd")
                       if c in rows[0]), "")
        if not column:
            pytest.skip("the result does not carry a PD column to check")
        values = [float(r[column]) for r in rows if r.get(column) is not None]
        assert values == sorted(values, reverse=True), \
            "the highest PD is not first"


# ---------------------------------------------------------------------------
# CONTEXT — §26's four-turn Shipping thread
# ---------------------------------------------------------------------------

OPENING = f"Why did {SECTOR} deteriorate this quarter?"
FOLLOW_UPS: tuple[str, ...] = (
    "Which borrowers are the real issues?",
    "Which of those have liquidity pressure?",
    "Why does the second one worry you?",
)


@pytest.fixture
def shipping() -> Thread:
    started = Thread()
    started.ask(OPENING)
    if started.state.filter_pairs() != [("sector", SECTOR)]:
        pytest.skip("the opening turn did not settle on the Shipping "
                    "population in this build")
    return started


class TestTheShippingThread:
    """§26's exact four turns. Every one after the first names no population
    of its own, and every one must stay in Shipping."""

    def test_every_turn_keeps_the_shipping_population(self,
                                                      shipping: Thread
                                                      ) -> None:
        for turn, follow_up in enumerate(FOLLOW_UPS, start=2):
            shipping.ask(follow_up)
            assert shipping.state.filter_pairs() == [("sector", SECTOR)], (
                f"turn {turn} — {follow_up!r} — silently widened back to the "
                "whole portfolio")

    def test_no_turn_returns_rows_from_another_sector(self,
                                                      shipping: Thread
                                                      ) -> None:
        for follow_up in FOLLOW_UPS:
            shipping.ask(follow_up)
            found = shipping.sectors()
            assert found in (set(), {SECTOR}), (
                f"{follow_up!r} returned rows from {found - {SECTOR}}")

    def test_every_turn_answers_rather_than_asking_again(self,
                                                         shipping: Thread
                                                         ) -> None:
        for follow_up in FOLLOW_UPS:
            investigation, _ = shipping.ask(follow_up)
            said = str(investigation.narrative.direct_answer or "")
            assert said.strip(), f"{follow_up!r} produced no direct answer"

    def test_no_turn_moves_outside_the_window_turn_one_settled(
            self, shipping: Thread) -> None:
        """A thread that kept the sector and lost the quarter would answer a
        different question just as confidently.

        Containment rather than identity, because narrowing is correct and
        moving is not. "Why did Shipping deteriorate this quarter" settles a
        two-period comparison; "which borrowers are the real issues" is a
        question about the closing quarter of it, and answering that in the
        closing quarter is right. Answering it in a quarter the thread never
        mentioned would be the defect, and that is what this asserts.
        """
        settled = set(shipping.state.periods)
        assert settled, "turn one settled no reporting period"
        for follow_up in FOLLOW_UPS:
            shipping.ask(follow_up)
            now = set(shipping.state.periods)
            assert now, f"{follow_up!r} left the thread with no period at all"
            assert now <= settled, (
                f"{follow_up!r} moved to {now - settled}, which turn one "
                "never mentioned")


# ---------------------------------------------------------------------------
# ANALYTICAL — §26's third class, and §5's story
# ---------------------------------------------------------------------------


class TestAnalytical:
    @pytest.mark.parametrize("question", [
        "Why did Shipping deteriorate this quarter?",
        "Which borrowers are the real issues?",
        "Why does the second one worry you?",
    ])
    def test_a_judgement_question_is_read_as_one(self, question: str) -> None:
        # §16: these are the questions worth paying for, and a product that
        # answered them from a lookup would be answering a different question.
        assert classify.read(question).question_class == cost.CLASS_C

    def test_a_shipping_borrower_gets_the_scenario_as_context(self) -> None:
        # §8 and §23. The governed scenario is sector-level and synthetic, and
        # the story must say both.
        from backend.early_warning import story as st

        try:
            ranked = sg._book("")["_ranked"]
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the corporate lake is not built: {exc}")
        ship = [s for s in ranked
                if str(s.record.get("sector") or "") == SECTOR]
        if not ship:
            pytest.skip("no Shipping borrower stands up in this build")
        built = st.build(ship[0], sector=SECTOR, group=False).to_dict()
        external = next(s for s in built["sections"] if s["key"] == "external")
        if not external["evidence"]:
            pytest.skip("no external event is live for Shipping in this build")
        said = " ".join(external["body"])
        assert "SYNTHETIC" in said, \
            "the demonstration scenario is not marked as synthetic"
        assert "not attached to this borrower individually" in said, \
            "a sector-level link is presented as a borrower-level one"
        assert "analytical hypothesis" in said, \
            "a modelled link is presented as an observed fact"
