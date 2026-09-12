"""
The second adversarial Cockpit session, and what it found.

The overnight run closed thirty-seven defects and its discovery curve never
flattened. This file is the narrower session that followed: fifteen turns of
one Head of Retail Risk conversation, asked in the order a person asks them,
with every figure reconciled against the Parquet before the answer was read.

**An average of the page, reported as the average of the book.** "What is the
average behavioural score for personal finance customers?" answered 694.33
points "across the 6781 groups". The book's figure is 666.99. The rows are
ordered and only the first two hundred are returned, so the mean of the
returned rows is the mean of the top of the list — biased by exactly as much
as the ordering. The same defect, on a question with more consequence: "what
is the average days past due for credit card customers?" answered **61 days**
where the book is **2.24**. A Head of Retail Risk who reads that a credit-card
book averages sixty-one days past due escalates it to a board.

**A conversation that died two turns after a composite.** "Which product
worries you most and why?" is a credit-concern ranking. A composite matches no
concept, so the turn left no measure on the conversation state, and the next
sentence that named none of its own — "show me the numbers behind that" — had
nothing to inherit. It came back "Which figure should CreditProbe measure?",
and so did every turn after it: four consecutive questions of a fifteen-turn
conversation, answered with the same menu.

**A composite asked for a series, answered at one date in silence.** "What
happened over the previous six months — is this a one-month spike or a trend?"
returned the same single-month ranking with nothing said about the window. A
composite is evaluated per customer per month and ranks customers, not months;
it cannot draw the series, and saying so is the answer.
"""

from __future__ import annotations

import glob

import pandas as pd
import pytest

from backend.orchestration import analysis_planner as ap
from backend.orchestration import composites as cmp
from backend.orchestration import conversation as cv
from backend.orchestration import orchestrator
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

LATEST = "2026-08"


@pytest.fixture(scope="module")
def book() -> pd.DataFrame:
    paths = glob.glob("data/retail/analytics/retail_facility_month/"
                      f"reporting_month={LATEST}/*.parquet")
    if not paths:
        pytest.skip("the shipped retail lake has not been built")
    return pd.read_parquet(paths[0])


def answer(question: str, *, state: cv.ConversationState | None = None):
    answered = orchestrator.answer(question, state=state)
    assert not answered.clarification, (
        f"{question!r} was refused: "
        f"{getattr(answered.clarification, 'question', answered.clarification)}")
    return answered


def values(answered) -> dict:
    from backend.orchestration import assembly
    runtime = getattr(answered, "runtime", None)
    if runtime is None:
        return {}
    return assembly._values(answered.build, runtime)


def advanced(question: str, state: cv.ConversationState | None = None
             ) -> tuple[object, cv.ConversationState]:
    """One turn, and the state a follow-up would be planned against."""
    answered = orchestrator.answer(question, state=state)
    return answered, orchestrator.remember(state or cv.ConversationState(),
                                           answered)


class TestAnAverageIsOfThePopulationNotOfThePage:
    """The returned rows are a page. The average must not be a page's."""

    def test_the_behavioural_score_average_is_the_books(self, book):
        got = values(answer("What is the average behavioural score for "
                            f"personal finance customers at {LATEST}?"))
        truth = book[book.product_label == "Personal Finance"] \
            .groupby("customer_id").behavioural_score.mean().mean()
        assert got["average"] == pytest.approx(round(float(truth), 4), abs=0.01)

    def test_the_days_past_due_average_is_the_books(self, book):
        got = values(answer("What is the average days past due for credit "
                            f"card customers at {LATEST}?"))
        truth = book[book.product_label == "Credit Card"] \
            .groupby("customer_id").dpd.mean().mean()
        assert got["average"] == pytest.approx(round(float(truth), 4), abs=0.01)
        assert got["average"] < 10, (
            "a credit-card book at two days past due must not be reported in "
            "the tens of days")

    def test_the_group_count_is_the_population_not_the_page(self):
        got = values(answer("What is the average behavioural score for "
                            f"personal finance customers at {LATEST}?"))
        assert got["groups"] == got["matching"], (
            "an average described as being across N groups must be across N")

    def test_the_population_average_is_computed_before_the_cut(self):
        answered = answer("What is the average behavioural score for "
                          f"personal finance customers at {LATEST}?")
        ops = [o for o in (answered.build.plan.get("operations") or [])
               if str(o.get("op")) == "WINDOW"
               and str((o.get("params") or {}).get("function")) == "avg"]
        assert ops, "no population average was planned"
        ids = [str(o.get("id")) for o in
               (answered.build.plan.get("operations") or [])]
        assert ids.index("population_average") < ids.index("result") \
            if "result" in ids else True

    def test_a_fully_shown_breakdown_is_unchanged(self, book):
        """Four products, four rows, nothing truncated: the old path was right."""
        got = values(answer(f"What is the average behavioural score by "
                            f"product at {LATEST}?"))
        assert got["groups"] == 4
        truth = book.groupby("product_label").behavioural_score.mean().mean()
        assert got["average"] == pytest.approx(round(float(truth), 4), abs=0.01)

    def test_a_sum_is_not_turned_into_an_average(self, book):
        got = values(answer(f"What is total ECL by product at {LATEST}?"))
        assert "average" not in got
        assert got["total"] == pytest.approx(
            round(float(book.ecl_final_sar.sum()), 4), abs=1.0)

    def test_the_population_average_column_is_not_shown_to_a_reader(self):
        from backend.orchestration import presentation
        answered = answer("What is the average behavioural score for "
                          f"personal finance customers at {LATEST}?")
        contract = presentation.contract(answered.runtime, answered.build)
        carried = [c for c in contract
                   if str(c["name"]).endswith("_population_avg")]
        assert carried, "the lineage column should be declared"
        assert all(c["hidden"] for c in carried), (
            "the same number on every row is lineage, not a column")


class TestACompositeLeavesSomethingToInherit:
    """A concern ranking matches no concept. It must still settle the thread."""

    def test_a_composite_turn_records_what_it_ranked(self):
        _, state = advanced("Which product worries you most and why?")
        assert state.composite, (
            "a turn that ranked by a composite left the thread with no measure")
        assert cmp.find(state.composite, None) is not None or state.composite

    def test_an_ordinary_measure_clears_it_again(self):
        _, state = advanced("Which product worries you most and why?")
        _, state = advanced(f"What is total ECL by product at {LATEST}?", state)
        assert not state.composite, (
            "a composite must not reach past the answer on screen")

    def test_a_measureless_follow_up_after_a_composite_is_answered(self):
        _, state = advanced("Which product worries you most and why?")
        answered = orchestrator.answer("Show me the numbers behind that.",
                                       state=state)
        assert not answered.clarification, (
            "the thread died two turns after a composite: "
            f"{getattr(answered.clarification, 'question', '')}")
        assert answered.answered

    def test_it_survives_a_second_measureless_turn(self):
        _, state = advanced("Which product worries you most and why?")
        _, state = advanced("Show me the numbers behind that.", state)
        answered = orchestrator.answer(
            "What happened over the previous six months - is this a "
            "one-month spike or a trend?", state=state)
        assert not answered.clarification
        assert answered.answered

    def test_a_continue_reads_the_settled_analysis(self):
        state = cv.ConversationState()
        _, state = advanced("Which product worries you most and why?", state)
        continuation = __import__(
            "backend.orchestration.referents", fromlist=["x"]).resolve(
                "Show me the numbers behind that.", state)
        assert continuation.action == cv.CONTINUE
        assert continuation.carries_context


class TestACompositeSaysItCannotDrawASeries:
    def test_the_window_is_named_and_declined(self):
        _, state = advanced("Which product worries you most and why?")
        answered = orchestrator.answer(
            "What happened over the previous six months - is this a "
            "one-month spike or a trend?", state=state)
        said = " ".join(answered.build.warnings)
        assert "one reporting date" in said, (
            "a single-date ranking answered a question about six months and "
            f"said nothing: {said!r}")
        assert "trend" in said.lower()

    def test_an_ordinary_measure_still_draws_the_series(self, book):
        answered = answer("What is ECL for personal finance?")
        state = orchestrator.remember(cv.ConversationState(), answered)
        following = answer("What happened over the previous six months - is "
                           "this a one-month spike or a trend?", state=state)
        months = [str(r.get("reporting_month")) for r in following.runtime.rows]
        assert len(months) == 7, f"a six-month look-back has seven ends: {months}"
        assert months == sorted(months)

    def test_a_single_date_question_gets_no_such_caveat(self):
        _, state = advanced("Which product worries you most and why?")
        answered = orchestrator.answer("Show me the numbers behind that.",
                                       state=state)
        assert not any("one reporting date" in w
                       for w in answered.build.warnings)


class TestAFollowUpIsReadAsWhatItIs:
    """Four sentences a person says, and four things the resolver called them."""

    @pytest.fixture(scope="class")
    def carried(self) -> cv.ConversationState:
        answered = orchestrator.answer(
            "Which ten customers had the largest ECL increase this month?")
        return orchestrator.remember(cv.ConversationState(), answered)

    def test_a_correction_replaces_rather_than_adds(self, carried):
        from backend.orchestration import referents
        read = referents.resolve(
            "Actually forget behavioural score - just use DPD.", carried)
        assert read.action == cv.MODIFY_PREVIOUS, (
            "a correction read as a fresh request names BOTH measures, and "
            "the answer carries the one it was told to drop")

    def test_the_dropped_measure_is_recorded_as_rejected(self):
        from backend.data_access import get_catalog
        from backend.orchestration import concepts as cx
        from backend.orchestration import context as governed_context

        text = "Actually forget behavioural score - just use days past due."
        known = {d.name: {f["name"] for f in d.fields}
                 for d in governed_context.all_datasets()}
        matches = cx.read_concepts(text, known=known,
                                   catalogue=get_catalog()).matches
        rejected = {m.phrase.lower() for m in ap._rejected_measures(text, matches)}
        assert any("behavioural" in p for p in rejected), rejected
        assert not any("past due" in p for p in rejected), rejected
        assert ap._replaces(text)

    def test_a_possessive_drill_down_points_back(self, carried):
        from backend.orchestration import referents
        read = referents.resolve("Show their facilities.", carried)
        assert read.action == cv.CONTINUE and read.carries_context

    def test_back_is_navigation_not_an_analysis(self, carried):
        from backend.orchestration import referents
        assert referents.resolve("Back.", carried).action == cv.NAVIGATE
        assert referents.resolve("Go back.", carried).action == cv.NAVIGATE

    def test_a_contribution_question_points_back(self, carried):
        from backend.orchestration import referents
        read = referents.resolve("Which ten customers contributed most?",
                                 carried)
        assert read.action == cv.CONTINUE and read.carries_context

    @pytest.mark.parametrize("question", [
        "Show me the largest customers.",
        "Show the ECL by product.",
        "What is total ECL?",
    ])
    def test_a_fresh_request_is_still_a_fresh_request(self, carried, question):
        from backend.orchestration import referents
        assert referents.resolve(question, carried).action == cv.NEW_REQUEST

    def test_forgetting_a_population_is_still_a_reset(self, carried):
        from backend.orchestration import referents
        assert referents.resolve("Forget those - show the whole book.",
                                 carried).action == cv.RESET_SCOPE


class TestBackReturnsTheAnswerItLeft:
    def test_nothing_is_recomputed(self):
        first = answer("Which ten customers had the largest ECL increase "
                       "this month?")
        state = orchestrator.remember(cv.ConversationState(), first)
        back = orchestrator.answer("Back.", state=state)
        assert back.from_memory, "Back ran a fresh analysis"
        assert getattr(back, "runtime", None) is None

    def test_the_rows_are_the_same_rows(self):
        first = answer("Which ten customers had the largest ECL increase "
                       "this month?")
        state = orchestrator.remember(cv.ConversationState(), first)
        back = orchestrator.answer("Back.", state=state)
        was = [r["customer_id"] for r in first.runtime.rows]
        now = [r["customer_id"] for r in back.result.rows]
        assert now == was, "Back returned a different population"


class TestADrillDownDrills:
    """"Show their facilities" is one row per facility of those customers."""

    @pytest.fixture(scope="class")
    def drilled(self):
        first = orchestrator.answer(
            "Which ten customers had the largest ECL increase this month?")
        state = orchestrator.remember(cv.ConversationState(), first)
        second = orchestrator.answer("Show their facilities.", state=state)
        assert not second.clarification, second.clarification
        return first, second

    def test_the_rows_are_facilities(self, drilled):
        _, second = drilled
        assert all("facility_id" in r for r in second.runtime.rows)

    def test_every_facility_of_those_customers_is_there(self, drilled, book):
        first, second = drilled
        ids = {r["customer_id"] for r in first.runtime.rows}
        truth = book[book.customer_id.isin(ids)].facility_id.nunique()
        assert len(second.runtime.rows) == truth, (
            "a drill-down cut to the previous turn's ten dropped facilities")

    def test_it_is_not_cut_to_a_default_ten(self, drilled):
        _, second = drilled
        assert second.build.top_n == 0

    def test_the_plan_summary_names_facilities_not_customers(self, drilled):
        _, second = drilled
        said = second.build.summary.lower()
        assert "facilities" in said, said
        assert "customers with the largest" not in said, (
            f"sixteen facility rows introduced as customers: {said}")

    def test_the_summary_spells_the_plural_and_counts_the_rows(self, drilled):
        _, second = drilled
        said = second.build.summary
        assert "facilitys" not in said, said
        assert "The 0 " not in said, f"a cut of zero read as a count: {said}"

    def test_the_facility_key_is_this_installations(self):
        from backend.orchestration import grain as gr
        assert gr.key_of(gr.FACILITY) == "facility_id"
        assert gr.key_of(gr.CUSTOMER) == "customer_id"

    def test_a_carried_population_still_decides_when_no_grain_is_named(self):
        from backend.orchestration import grain as gr
        got = gr.requested("Which of those are in Stage 2?",
                           population_grain="customer")
        assert got.grain == gr.CUSTOMER


class TestAClarificationSpeaksThisBook:
    def test_it_asks_for_restrictions_this_installation_holds(self):
        said = ap._which_population_clarification().lower()
        assert "customers" in said
        for corporate in ("borrower", "sector", "rating"):
            assert corporate not in said, (
                f"the retail clarification offers {corporate!r}")
