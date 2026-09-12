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


def _month(period: str) -> pd.DataFrame:
    """One reporting month of the shipped lake, read directly."""
    paths = glob.glob("data/retail/analytics/retail_facility_month/"
                      f"reporting_month={period}/*.parquet")
    if not paths:
        pytest.skip(f"the shipped retail lake has no {period}")
    return pd.read_parquet(paths[0])


def answer(question: str, *, state: cv.ConversationState | None = None):
    answered = orchestrator.answer(question, state=state)
    assert not answered.clarification, (
        f"{question!r} was refused: "
        f"{getattr(answered.clarification, 'question', answered.clarification)}")
    return answered


def headline(answered) -> str:
    """The sentence the API puts at the top of the answer."""
    from backend.orchestration import assembly
    if getattr(answered, "result", None) is not None:
        return str(answered.result.answer)
    built = assembly.from_analysis(
        answered.question, answered.reading, answered.build, answered.runtime,
        duration_ms=0, mode={})
    return str(getattr(built.narrative, "direct_answer", "") or "")


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
        # STEP_BACK, not NAVIGATE: navigation OPENS what the conversation is
        # about, and one word typed to return to the previous answer opened
        # the dataset and returned fifty raw rows of the book.
        assert referents.resolve("Back.", carried).action == cv.STEP_BACK
        assert referents.resolve("Go back.", carried).action == cv.STEP_BACK

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


class TestTheBookSOwnOpeningQuestion:
    """"What changed this month?" — refused, on a book that holds exactly it."""

    def test_it_is_answered_rather_than_refused(self):
        answered = answer("What changed in my retail portfolio this month "
                          "that I should actually care about?")
        assert answered.answered
        assert not getattr(answered, "unsupported", "")

    def test_the_figures_are_the_books(self, book):
        answered = answer("What changed in my retail portfolio this month "
                          "that I should actually care about?")
        got = values(answered)
        truth = float(book.ecl_final_sar.sum())
        assert got["closing_total"] == pytest.approx(truth, abs=1.0)

    def test_it_leads_with_the_movement_that_matters(self):
        """Gross carrying amount moved 2%; ECL moved 13%. Lead with the 13%."""
        answered = answer("What changed in my retail portfolio this month "
                          "that I should actually care about?")
        assert abs(float(values(answered)["change_pct"])) > 10.0, (
            "the answer opened on the smaller movement and left the larger "
            "one in the table")

    def test_the_default_is_stated_not_silent(self):
        answered = answer("What changed in my retail portfolio this month "
                          "that I should actually care about?")
        said = " ".join(answered.build.warnings)
        assert "named no figure" in said, said
        assert "Name any governed measure" in said

    def test_a_named_measure_is_not_overridden(self, book):
        """The default fires only where the sentence named no figure."""
        answered = answer("How did ECL move this month?")
        assert [m.label.lower() for m in answered.build.matches] == ["final ecl"]
        assert values(answered)["closing_total"] == pytest.approx(
            float(book.ecl_final_sar.sum()), abs=1.0)


class TestAScorecardQuestionReachesTheValidationRunner:
    """Eleven consecutive turns answered with the average origination score."""

    def test_a_performance_question_is_routed(self):
        from backend.orchestration import scorecard_route as sr
        routed = sr.read("How is our personal-finance application scorecard "
                         "performing?")
        assert routed is not None
        assert routed.model_id == "retail_app_personal_loan"

    def test_it_returns_findings_rather_than_an_average_score(self):
        answered = answer("How is our personal-finance application scorecard "
                          "performing?")
        assert answered.scorecard_model == "retail_app_personal_loan"
        said = str(answered.result.answer)
        assert "findings" in said.lower(), said
        assert "points of application score" not in said.lower(), (
            "the average origination score of the book is not how a scorecard "
            "is performing")

    def test_the_gini_is_the_runners_gini(self):
        answered = answer("What is the Gini on the personal finance "
                          "application scorecard?")
        row = answered.result.rows[0]
        assert row["test_id"] == "DISC-GINI"
        assert 0.0 < float(row["value"]) < 1.0
        assert "observations" in str(row["detail"])

    def test_the_answer_names_the_model_version_and_cohort(self):
        answered = answer("What is the Gini on the personal finance "
                          "application scorecard?")
        said = str(answered.result.answer)
        assert "Personal Finance Application Scorecard" in said
        assert "v1.0.0" in said
        assert "observations" in said

    def test_a_band_question_names_a_band(self):
        first = answer("What is the Gini on the personal finance application "
                       "scorecard?")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = answer("Which risk band is most miscalibrated?", state=state)
        said = str(answered.result.answer)
        assert "band " in said.lower(), said
        assert "observations carrying" in said, (
            "a band named without its sample is the number an auditor asks "
            "the second question about")
        assert any("evidence" in str(r.get("evidence", "")).lower()
                   for r in answered.result.rows)

    def test_the_conversation_carries_the_scorecard(self):
        first = answer("How is our personal-finance application scorecard "
                       "performing?")
        state = orchestrator.remember(cv.ConversationState(), first)
        assert state.scorecard_model == "retail_app_personal_loan"
        answered = answer("What's the Gini?", state=state)
        assert answered.result.rows[0]["test_id"] == "DISC-GINI"

    def test_an_unnamed_scorecard_is_asked_about_not_guessed(self):
        from backend.orchestration import scorecard_route as sr
        routed = sr.read("What's the Gini?")
        assert routed is not None and not routed.model_id
        assert "Which scorecard?" in routed.ask
        assert "Personal Finance Application Scorecard" in routed.ask

    @pytest.mark.parametrize("question", [
        "What is total ECL by product?",
        "What is the average application score by product?",
        "Which customers are 30+ DPD?",
    ])
    def test_an_ordinary_question_is_not_routed(self, question):
        from backend.orchestration import scorecard_route as sr
        assert sr.read(question) is None

    def test_the_route_computes_nothing_of_its_own(self):
        """Every figure comes from the validation runner, stated as such."""
        answered = answer("What is the Gini on the personal finance "
                          "application scorecard?")
        said = " ".join(answered.result.warnings)
        assert "computed by the validation runner" in said, said


class TestAPeriodMeansWhatItSays:
    """A month is a month, a quarter is three of them, a year is twelve."""

    @pytest.fixture(scope="class")
    def months(self) -> list[str]:
        import glob as _glob
        found = sorted(p.rsplit("=", 1)[1] for p in _glob.glob(
            "data/retail/analytics/retail_facility_month/reporting_month=*"))
        if not found:
            pytest.skip("the shipped retail lake has not been built")
        return found

    def window(self, question: str) -> tuple[str, str]:
        answered = answer(question)
        return answered.build.opening, answered.build.closing

    def test_move_this_month_is_a_movement_not_a_level(self):
        answered = answer("How did ECL move this month?")
        assert answered.build.shape == ap.MOVEMENT, (
            "the verb 'move' with a period after it read as an instruction, "
            "and the level was returned under a caveat saying so")

    def test_this_month_is_one_step(self, months):
        assert self.window("How did ECL move this month?") == (
            months[-2], months[-1])

    def test_a_quarter_is_three_months(self, months):
        assert self.window("How did ECL move over the last quarter?") == (
            months[-4], months[-1])

    def test_quarter_on_quarter_is_three_months(self, months):
        assert self.window("How did ECL change quarter on quarter?") == (
            months[-4], months[-1])

    def test_a_year_is_twelve_months(self, months):
        assert self.window("How did ECL change over the last year?") == (
            months[-13], months[-1])

    def test_last_month_is_still_one_step(self, months):
        assert self.window("How did ECL change since last month?") == (
            months[-2], months[-1])

    def test_the_quarter_reconciles(self, months):
        import glob as _glob
        answered = answer("How did ECL move over the last quarter?")
        got = values(answered)
        opening = pd.read_parquet(_glob.glob(
            "data/retail/analytics/retail_facility_month/"
            f"reporting_month={months[-4]}/*.parquet")[0],
            columns=["ecl_final_sar"])
        assert got["opening_total"] == pytest.approx(
            float(opening.ecl_final_sar.sum()), abs=1.0)

    def test_an_instruction_is_still_an_instruction(self):
        from backend.orchestration import movement as mv
        assert not mv.asks_for_change("Move this to the Contracting sector")


class TestAConstrainedFieldIsNotAMeasure:
    """"Stage 2" is a population. Summing the stage number answers nothing."""

    def test_stage_2_exposure_is_exposure(self, book):
        got = values(answer(f"What is the Stage 2 exposure at {LATEST}?"))
        truth = float(book[book.ifrs9_stage == 2].gross_carrying_amount_sar.sum())
        assert got["total"] == pytest.approx(truth, abs=1.0)
        assert got["total"] > 1_000_000, (
            "the stage number was summed and reported as the exposure")

    def test_a_count_still_counts_the_constrained_field(self, book):
        got = answer(f"How many facilities are in Stage 2 at {LATEST}?")
        rows = got.runtime.rows
        assert int(rows[0]["facility_count"]) == int(
            book[book.ifrs9_stage == 2].facility_id.nunique())

    def test_a_movement_with_no_measure_names_what_it_measured(self, book):
        answered = answer("Compare Stage 2 this month to three months ago.")
        said = " ".join(answered.build.warnings)
        assert "CONSTRAINS" in said, said
        assert [m.field for m in answered.build.matches] != ["ifrs9_stage"]

    def test_the_stage_rate_is_the_published_metric(self):
        answered = answer("Which subsegment has the highest Stage 2 rate?")
        said = headline(answered)
        assert "CARD" in said, said
        assert "12.70%" in said, said
        assert "IFRS 9 stage in Stage 2" not in said

    def test_the_largest_group_is_named(self, book):
        answered = answer("Which subsegment has the largest Stage 2 exposure?")
        said = headline(answered)
        assert "FIRST_HOME" in said, said
        truth = float(book[(book.ifrs9_stage == 2)
                           & (book.product_subsegment == "FIRST_HOME")]
                      .gross_carrying_amount_sar.sum())
        assert f"{truth:,.0f}" in said.replace(" SAR", ""), said

    def test_a_breakdown_that_was_not_asked_to_rank_still_totals(self):
        said = headline(answer(f"What is ECL by product at {LATEST}?"))
        assert "15,952,109" in said, said
        assert "has the largest" not in said


class TestANarrowingKeepsTheAnalysis:
    def test_it_keeps_the_movement(self, book):
        first = answer("Why did weighted ECL move this month?")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = answer("Show me personal finance.", state=state)
        assert answered.build.shape == ap.MOVEMENT, (
            "a narrowing kept the measure and lost the shape")
        got = values(answered)
        truth = float(book[book.product_label == "Personal Finance"]
                      .ecl_final_sar.sum())
        assert got["closing_total"] == pytest.approx(truth, abs=1.0)

    def test_show_me_a_product_is_a_narrowing(self):
        from backend.orchestration import referents
        first = answer("Why did weighted ECL move this month?")
        state = orchestrator.remember(cv.ConversationState(), first)
        read = referents.resolve("Show me personal finance.", state)
        assert read.action in (cv.NARROW_SCOPE, cv.CONTINUE)
        assert read.carries_context

    def test_show_me_a_measure_is_not_a_narrowing(self):
        from backend.orchestration import referents
        first = answer("Why did weighted ECL move this month?")
        state = orchestrator.remember(cv.ConversationState(), first)
        assert referents.resolve("Show me ECL by product.",
                                 state).action == cv.NEW_REQUEST


class TestAMetricSurvivesItsOwnFollowUp:
    def test_the_metric_is_remembered(self):
        answered = answer("What's happening to 30+ DPD?")
        assert answered.governed_metric == "retail.dpd30.rate" or \
            "dpd" in answered.governed_metric

    def test_which_product_is_driving_it_stays_on_the_metric(self):
        first = answer("What's happening to 30+ DPD?")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = answer("Which product is driving it?", state=state)
        said = headline(answered)
        assert "Credit Card" in said, said
        assert "3.70%" in said, said
        assert "days of days past due" not in said, (
            "the planner summed the days-past-due column")

    def test_by_rate_not_volume_keeps_the_breakdown(self):
        first = answer("What's happening to 30+ DPD?")
        state = orchestrator.remember(cv.ConversationState(), first)
        second = answer("Which product is driving it?", state=state)
        state = orchestrator.remember(state, second)
        answered = answer("By rate, not volume.", state=state)
        assert "Credit Card" in headline(answered)


class TestAPointerIsAskedAbout:
    def test_that_one_asks_which(self):
        first = answer(f"What is ECL by product at {LATEST}?")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = orchestrator.answer("that one", state=state)
        assert answered.clarification, "a bare pointer was answered by guessing"
        said = str(answered.clarification)
        assert "Which one?" in said
        assert "Personal Finance" in said and "Credit Card" in said

    def test_no_the_other_one_asks_which(self):
        first = answer(f"What is ECL by product at {LATEST}?")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = orchestrator.answer("no the other one", state=state)
        assert answered.clarification

    def test_an_ordinal_still_resolves(self, book):
        first = answer(f"What is ECL by product at {LATEST}?")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = answer("the second one", state=state)
        assert not answered.clarification
        assert "Credit Card" in headline(answered)

    def test_a_pointer_is_not_a_clarification_reply(self):
        assert not cv.answers_a_clarification("no the other one")
        assert not cv.answers_a_clarification("that one")
        assert cv.answers_a_clarification("expected credit loss")


class TestTwoMonthsCompared:
    """"August vs July" is two months of this year, not eleven of two."""

    @pytest.fixture(scope="class")
    def months(self) -> list[str]:
        import glob as _glob
        found = sorted(p.rsplit("=", 1)[1] for p in _glob.glob(
            "data/retail/analytics/retail_facility_month/reporting_month=*"))
        if not found:
            pytest.skip("the shipped retail lake has not been built")
        return found

    def test_a_comparison_resolves_each_month_independently(self, months):
        answered = answer("ECL for august vs july")
        assert (answered.build.opening, answered.build.closing) == (
            months[-2], months[-1])

    def test_a_span_still_runs_forwards(self, months):
        answered = answer("Give me the July to August ECL movement")
        assert (answered.build.opening, answered.build.closing) == (
            months[-2], months[-1])

    def test_the_months_may_be_far_apart_in_the_sentence(self, months):
        answered = answer("aug personal finance sal transfer stage2 ecl vs "
                          "jul what moved")
        assert (answered.build.opening, answered.build.closing) == (
            months[-2], months[-1])

    def test_the_shorthand_restriction_is_applied(self, book):
        answered = answer("aug personal finance sal transfer stage2 ecl vs "
                          "jul what moved")
        got = values(answered)
        truth = float(book[(book.product_label == "Personal Finance")
                           & (book.salary_transfer_flag)
                           & (book.ifrs9_stage == 2)].ecl_final_sar.sum())
        assert got["closing_total"] == pytest.approx(truth, abs=1.0), (
            "a restriction the reader stated was dropped in silence")

    def test_the_restriction_is_named_on_the_answer(self):
        answered = answer("aug personal finance sal transfer stage2 ecl vs "
                          "jul what moved")
        fields = {f for f, _ in answered.build.filters}
        assert "salary_transfer_flag" in fields
        assert "product_label" in fields


class TestTheProductsOwnWordsAreNotObligors:
    @pytest.mark.parametrize("phrase", [
        "Which customers deserve an Early Warning investigation?",
        "What is the Gini on the personal finance application scorecard?",
    ])
    def test_no_data_steward_refusal(self, phrase):
        answered = orchestrator.answer(phrase)
        said = str(answered.clarification or "") + str(
            getattr(answered, "unsupported", "") or "")
        assert "Data Steward" not in said, said
        assert "has never been given" not in said, said

    def test_the_investigation_question_is_answered_with_evidence(self):
        answered = answer("Which customers deserve an Early Warning "
                          "investigation?")
        assert answered.answered
        said = " ".join(answered.build.warnings)
        assert "signals it does carry" in said, (
            "an evidence ranking must say it is evidence, not a rule")

    def test_the_refusal_speaks_this_installations_book(self):
        from backend.orchestration import orchestrator as orc
        said = orc._unknown_borrower("What is Northwind Trading's exposure?",
                                     None)
        if said:
            assert "borrower" not in said, said


class TestASeriesIsDescribedAsASeries:
    """Twenty-five points introduced by their two ends is a series unread."""

    @pytest.fixture(scope="class")
    def trend(self):
        return answer("Show the 25-month ECL trend")

    def test_every_month_is_returned(self, trend):
        months = {str(r.get("reporting_month")) for r in trend.runtime.rows}
        assert len(months) == 25, sorted(months)

    def test_the_sentence_says_it_is_a_series(self, trend):
        said = headline(trend)
        assert "25-month series" in said, said

    def test_the_peak_and_the_trough_are_the_books(self, trend):
        import glob as _glob
        said = headline(trend)
        totals = {}
        for path in _glob.glob("data/retail/analytics/retail_facility_month/"
                               "reporting_month=*/*.parquet"):
            at = path.split("reporting_month=")[1].split("/")[0]
            totals[at] = float(pd.read_parquet(
                path, columns=["ecl_final_sar"]).ecl_final_sar.sum())
        peak = max(totals, key=lambda k: totals[k])
        trough = min(totals, key=lambda k: totals[k])
        assert peak in said, said
        assert trough in said, said

    def test_the_recent_leg_is_stated(self, trend):
        said = headline(trend)
        assert "Over the last 12 months it rose" in said, (
            "a reader told the book is falling, on a book whose last year "
            f"rose: {said}")

    def test_a_two_point_movement_is_not_padded(self):
        said = headline(answer("How did ECL change this month?"))
        assert "series" not in said, said


class TestAStatedWindowBeatsTheThreads:
    def test_the_next_question_is_not_answered_over_two_years(self):
        first = answer("Show the 25-month ECL trend")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = answer("How did ECL change this month?", state=state)
        assert (answered.build.opening, answered.build.closing) != (
            first.build.opening, first.build.closing)

    def test_the_thread_route_reads_the_window_too(self):
        """A relative window is as explicit as a named month."""
        from backend.services import threads as th
        assert th._states_its_own_window("How did ECL change this month?")
        assert th._states_its_own_window("Compare ECL with a year ago.")
        # A sentence that states only a scope inherits the thread's window,
        # which is what makes "show me personal finance" a narrowing.
        assert not th._states_its_own_window("Show me personal finance.")

    def test_a_narrowing_still_inherits_the_window(self):
        first = answer("Show the 25-month ECL trend")
        state = orchestrator.remember(cv.ConversationState(), first)
        answered = answer("Show me personal finance.", state=state)
        assert (answered.build.opening, answered.build.closing) == (
            first.build.opening, first.build.closing)


class TestNothingSaysBorrower:
    """A retail-only product, answering in the retail book's words."""

    CORPORATE = ("borrower", "obligor", "counterparty", "rating band",
                 "internal rating", "notch", "sector", "covenant",
                 "wholesale", "corporate")

    QUESTIONS = (
        "Which ten customers contributed most?",
        "Which of those customers are in Stage 3?",
        "What is the CEO's tenure?",
        "Which customers deserve an Early Warning investigation?",
        "Show me the customers.",
        "the fortieth one",
        "What's the Gini?",
        "What is Northwind Trading's exposure?",
    )

    @pytest.mark.parametrize("question", QUESTIONS)
    def test_no_answer_speaks_the_corporate_book(self, question):
        answered = orchestrator.answer(question)
        said = " ".join(str(part) for part in (
            answered.clarification or "",
            getattr(answered, "unsupported", "") or "",
            getattr(getattr(answered, "result", None), "answer", "") or "",
        )).lower()
        found = [w for w in self.CORPORATE if w in said]
        assert not found, f"{question!r} answered with {found}: {said[:220]}"


class TestABoundWrittenAfterItsNumber:
    """"90 or more days past due" — read as an either/or, dropped, whole book."""

    def test_ninety_or_more_is_a_bound(self, book):
        got = answer("How many customers are 90 or more days past due?")
        rows = got.runtime.rows
        truth = int(book[book.dpd >= 90].customer_id.nunique())
        assert int(rows[0]["customer_count"]) == truth
        assert truth < 1000, "the guard is worthless if the truth is the book"

    def test_a_percentage_or_less_is_a_bound(self, book):
        got = answer("How many customers have a debt burden ratio of 50 "
                     "percent or less?")
        assert int(got.runtime.rows[0]["customer_count"]) == int(
            book[book.debt_burden_ratio <= 0.5].customer_id.nunique())

    def test_a_percentage_or_more_is_a_bound(self, book):
        got = answer("How many facilities have utilisation of 90 percent "
                     "or more?")
        assert int(got.runtime.rows[0]["facility_count"]) == int(
            book[book.utilisation_ratio >= 0.9].facility_id.nunique())

    def test_a_real_either_or_is_still_an_either_or(self, book):
        """The rewrite must not eat the conjunction it looks like."""
        got = answer("Which customers are in Stage 2 or Stage 3?")
        stages = {int(v) for f, v in got.build.filters if f == "ifrs9_stage"}
        rows = got.runtime.rows
        assert rows, "the either/or returned nothing"
        seen = {int(r["ifrs9_stage"]) for r in rows if "ifrs9_stage" in r}
        assert seen <= {2, 3} and seen, seen
        assert stages <= {2, 3}

    def test_the_rewrite_survives_the_clause_split(self):
        from backend.orchestration import semantics as sm
        assert sm.clauses("How many customers are 90 or more days past due?") \
            == ["How many customers are at least 90 days past due"]


class TestAWholeNumberIsWrittenWhole:
    def test_a_count_carries_no_decimals(self):
        said = headline(answer("How many customers are 90 or more days past due?"))
        assert ".00" not in said and ".0 " not in said, said

    def test_a_ratio_keeps_its_decimals(self):
        from backend.orchestration import figures
        assert figures.text(0.6402) == "0.64"
        assert figures.text(96.0) == "96"
        assert figures.text(158.0) == "158"


class TestACustomerLevelRollupUsesTheUnit:
    """A score reconciled with `min` compares two different facilities."""

    def test_the_biggest_faller_is_the_books(self, book):
        import glob as _glob
        answered = answer("Which customers had the biggest fall in "
                          "behavioural score this month?")
        top = answered.runtime.rows[0]
        prior = pd.read_parquet(_glob.glob(
            "data/retail/analytics/retail_facility_month/"
            "reporting_month=2026-07/*.parquet")[0],
            columns=["customer_id", "behavioural_score"])
        now = book.groupby("customer_id").behavioural_score.mean()
        was = prior.groupby("customer_id").behavioural_score.mean()
        fall = (now - was).dropna()
        assert top["customer_id"] == fall.idxmin()
        assert float(top["behavioural_score_change"]) == pytest.approx(
            float(fall.min()), abs=0.05)

    def test_the_customer_ecl_ranking_is_exact(self, book):
        import glob as _glob
        answered = answer("Which ten customers had the largest ECL increase "
                          "this month?")
        prior = pd.read_parquet(_glob.glob(
            "data/retail/analytics/retail_facility_month/"
            "reporting_month=2026-07/*.parquet")[0],
            columns=["customer_id", "ecl_final_sar"])
        delta = (book.groupby("customer_id").ecl_final_sar.sum()
                 - prior.groupby("customer_id").ecl_final_sar.sum()).dropna()
        wanted = list(delta.sort_values(ascending=False).head(10).index)
        assert [r["customer_id"] for r in answered.runtime.rows] == wanted
        for row in answered.runtime.rows:
            assert float(row["ecl_final_sar_change"]) == pytest.approx(
                float(delta[row["customer_id"]]), abs=0.01)

    def test_a_money_measure_sums_and_a_score_averages(self):
        from backend.orchestration import multi
        from backend.orchestration import concepts as cx
        from backend.orchestration import context as governed_context
        from backend.data_access import get_catalog

        known = {d.name: {f["name"] for f in d.fields}
                 for d in governed_context.all_datasets()}
        for text, wanted in (("expected credit loss", "sum"),
                             ("behavioural score", "avg")):
            match = cx.read_concepts(text, known=known,
                                     catalogue=get_catalog()).matches[0]
            assert multi._rollup(match) == wanted, (
                f"{text} rolls up to the customer with {multi._rollup(match)}")

    def test_a_stage_still_takes_the_worse_end(self):
        from backend.orchestration import multi
        from backend.orchestration import concepts as cx
        from backend.orchestration import context as governed_context
        from backend.data_access import get_catalog

        known = {d.name: {f["name"] for f in d.fields}
                 for d in governed_context.all_datasets()}
        match = cx.read_concepts("IFRS 9 stage", known=known,
                                 catalogue=get_catalog()).matches[0]
        assert multi._rollup(match) in ("max", "any_value")


class TestAnAnswerLeadsWithWhatWasAsked:
    def test_the_lowest_question_leads_with_the_lowest(self):
        said = headline(answer("Which subsegment has the lowest Stage 2 rate?"))
        assert said.startswith("SECOND_PROPERTY has the lowest"), said

    def test_the_highest_question_still_leads_with_the_highest(self):
        said = headline(answer("Which subsegment has the highest Stage 2 rate?"))
        assert said.startswith("CARD has the highest"), said

    def test_a_cohort_by_dimension_names_its_leader(self):
        said = headline(answer("Which product had the largest ECL increase "
                               "since June 2026?"))
        assert "Personal Finance leads" in said, said

    def test_an_entity_cohort_names_its_leader(self):
        said = headline(answer("Which customers had the biggest fall in "
                               "behavioural score this month?"))
        assert "leads, at" in said, said

    def test_the_plural_is_spelled(self):
        said = headline(answer("Which city has the most Stage 3 exposure?"))
        assert "citiess" not in said, said
        assert "cities" in said, said


class TestAShareAskedForByNamingTheState:
    def test_the_secured_share_is_answered(self, book):
        said = headline(answer("What proportion of the book is secured?"))
        truth = (book[book.secured_flag].gross_carrying_amount_sar.sum()
                 / book.gross_carrying_amount_sar.sum() * 100)
        assert "Secured Share" in said, said
        assert f"{truth:.0f}" in said, said

    def test_a_plain_total_is_not_hijacked(self):
        said = headline(answer("What is total ECL?"))
        assert "Share" not in said, said


class TestAnOrdinaryWordIsNotAGovernedValue:
    def test_current_ltv_is_not_a_delinquency_bucket(self, book):
        answered = answer("What is the average current LTV for home finance?")
        fields = {f for f, _ in answered.build.filters}
        assert "dpd_bucket" not in fields, (
            "an adjective was read as a governed value and scoped the answer")
        assert "product_label" in fields

    def test_the_bucket_is_still_reachable_when_named(self, book):
        answered = answer("How many facilities are in the CURRENT DPD bucket?")
        assert int(answered.runtime.rows[0]["facility_count"]) == int(
            book[book.dpd_bucket == "CURRENT"].facility_id.nunique())

    def test_it_is_reachable_by_the_dimension_s_full_name(self, book):
        answered = answer("How many facilities are in the current delinquency "
                          "bucket?")
        assert int(answered.runtime.rows[0]["facility_count"]) == int(
            book[book.dpd_bucket == "CURRENT"].facility_id.nunique())


# ---------------------------------------------------------------------------
# The second battery: navigation, reuse, and what a series says
# ---------------------------------------------------------------------------


class TestAWorkingsRequestIsNotARepeat:
    """"Show me the evidence." is the product's own suggested follow-up."""

    def test_it_is_recognised(self):
        assert orchestrator._shows_the_workings("Show me the evidence.")
        assert orchestrator._shows_the_workings("Show the workings.")
        assert orchestrator._shows_the_workings("How was that calculated?")
        assert not orchestrator._shows_the_workings(
            "Show me ECL by region.")

    def test_the_repeat_guard_lets_it_through(self):
        continuation = cv.Continuation(action=cv.ASK_ABOUT_RESULT)
        assert continuation.carries_context
        state = cv.ConversationState(ir={"dataset": "d", "operations": []},
                                     plan_summary="the previous analysis")
        build = type("B", (), {"plan": {"dataset": "d", "operations": []},
                               "warnings": []})()
        assert orchestrator._repeats_the_previous_plan(
            build, state, continuation, "Show me the evidence.") == ""

    def test_the_workings_are_of_the_answer_on_the_table(self):
        _, state = advanced("Break the whole book down by region.")
        answered, state = advanced("Which region has the highest ECL "
                                   "coverage?", state)
        workings = orchestrator._show_the_workings(
            orchestrator.Answered(question="Show me the evidence.",
                                  reading=answered.reading,
                                  verdict=answered.verdict,
                                  continuation=answered.continuation),
            "Show me the evidence.", state)
        assert workings is not None
        said = str(workings.result.answer)
        assert "ecl coverage" in said.lower(), said
        assert "SUM(ecl_final_sar)" in said, said
        # Never the summary of an EARLIER analysis: a route composes no plan,
        # so `plan_summary` still described the breakdown before it.
        assert "by region label at" not in said, said


class TestSteppingBackIsNotNavigation:
    """"Back." opened the dataset and returned fifty raw rows of the book."""

    def test_it_is_its_own_action(self):
        from backend.orchestration import referents

        _, carried = advanced("Break the whole book down by region.")
        assert referents.resolve("Back.", carried).action == cv.STEP_BACK
        assert referents.resolve("Go back.", carried).action == cv.STEP_BACK
        assert referents.resolve("Open the latest dataset.",
                                 carried).action == cv.NAVIGATE

    def test_it_is_not_read_as_answering_a_clarification(self):
        assert not cv.answers_a_clarification("Back.")
        assert not cv.answers_a_clarification("Never mind.")
        assert cv.answers_a_clarification("expected credit loss")

    def test_it_returns_the_rows_it_left(self):
        _, state = advanced("Break the whole book down by region.")
        answered = orchestrator.answer("Back.", state=state)
        said = str(answered.result.answer)
        assert "unchanged" in said, said
        assert said.count("..") == 0, said
        assert len(answered.result.rows) == 13, said


class TestARouteLeavesItsRowsOnTheTable:
    """A governed metric answers without a plan. The rows are still on screen."""

    def test_the_state_carries_them(self):
        answered, state = advanced("Which region has the highest ECL "
                                   "coverage?")
        assert state.result.rows, "the route's rows were not remembered"
        assert state.result.question == answered.question
        assert len(state.result.rows) == 13

    def test_its_columns_say_which_is_the_measure(self):
        _, state = advanced("Which region has the highest ECL coverage?")
        by_name = {c["name"]: c for c in state.result.columns}
        assert by_name["label"]["rank"] == 0
        assert by_name["value"]["semantic"] == "percent"
        assert by_name["rows"]["rank"] == 40


class TestASeriesIsPlannedAsASeries:
    """"by month" asks for every date, not for a ranking at one."""

    def test_the_shape_is_a_movement(self):
        answered = answer("Show me ECL by month for the last 12 months.")
        assert answered.build.shape == ap.MOVEMENT
        assert len(answered.runtime.rows) == 12
        assert "reporting_month" in answered.runtime.rows[0]

    def test_a_period_phrase_is_not_a_superlative(self):
        from backend.orchestration import fidelity as fd

        assert fd.objective_of("ECL for the last 12 months") != fd.RANKING
        assert fd.objective_of("the last 5 customers") == fd.RANKING

    def test_the_measure_column_is_not_labelled_with_one_date(self):
        from backend.orchestration import presentation as pr

        answered = answer("Show me ECL by month for the last 12 months.")
        labels = {c["name"]: c["label"] for c in pr.schema(answered.runtime,
                                                           answered.build)}
        assert labels["ecl_final_sar"] == "Expected credit loss", labels


class TestAnAssessmentSpeaksOfWhatItHolds:
    """The assessment used to correlate a measure with its own denominator."""

    def test_a_row_count_is_not_a_measure(self):
        from backend.orchestration import association

        columns = [{"name": "label", "rank": 0, "semantic": "text"},
                   {"name": "value", "rank": 10, "semantic": "percent"},
                   {"name": "rows", "rank": 40, "semantic": "count"}]
        rows = [{"label": f"g{i}", "value": 10 - i, "rows": i}
                for i in range(8)]
        found = association.analyse(columns, rows)
        assert not found.pairs, "a context column was correlated as a measure"

    def test_a_share_is_not_correlated_with_its_own_measure(self):
        from backend.orchestration import association

        columns = [{"name": "region", "rank": 0, "semantic": "text"},
                   {"name": "ecl", "rank": 10, "semantic": "money"},
                   {"name": "ecl_share_pct", "rank": 30, "semantic": "percent"}]
        rows = [{"region": f"r{i}", "ecl": 100 - i, "ecl_share_pct": 10 - i / 10}
                for i in range(8)]
        found = association.analyse(columns, rows)
        assert not found.pairs, (
            "a measure was correlated with its own share of the total")

    def test_a_nominal_ranking_is_not_reported_as_a_trend(self):
        from backend.orchestration import association

        columns = [{"name": "region", "rank": 0, "semantic": "text"},
                   {"name": "ecl", "rank": 10, "semantic": "money"}]
        rows = [{"region": f"r{i}", "ecl": 100 - i} for i in range(8)]
        found = association.analyse(columns, rows)
        assert not found.trends, (
            "the sort order of a ranking was reported as a trend")
        assert "no order of their own" in found.unavailable

    def test_a_series_is_assessed_along_its_dates(self):
        from backend.orchestration import association

        columns = [{"name": "reporting_month", "rank": 5, "semantic": "period"},
                   {"name": "ecl", "rank": 10, "semantic": "money"}]
        rows = [{"reporting_month": f"2026-{m:02d}", "ecl": v}
                for m, v in enumerate([10, 9, 8, 7, 8, 9, 10, 11], start=1)]
        found = association.analyse(columns, rows)
        assert found.over_time
        assert found.trends
        assert found.trends[0].low_label == "2026-04"

    def test_a_breakdown_at_two_dates_is_one_row_per_group(self):
        from backend.orchestration import association

        columns = [{"name": "region", "rank": 0, "semantic": "text"},
                   {"name": "reporting_month", "rank": 5, "semantic": "period"},
                   {"name": "ecl", "rank": 10, "semantic": "money"}]
        rows = [{"region": f"r{i}", "reporting_month": m, "ecl": 100 - i + k}
                for i in range(8)
                for k, m in enumerate(("2025-09", "2026-08"))]
        found = association.analyse(columns, rows)
        assert found.groups == 8, "two rows per group were counted as two groups"
        assert found.pairs, "the two dates were not compared"


class TestAMessageSurvivesAValueJsonCannotHold:
    """A pandas Timestamp in a preview used to 500 the whole turn."""

    def test_the_payload_is_coerced(self):
        from backend.services import threads

        stamp = pd.Timestamp("2026-08-31")
        out = threads._stored_payload(
            {"steps": [{"result": {"rows": [{"snapshot_date": stamp}]}}]})
        import json

        json.dumps(out)  # must not raise
        assert out["steps"][0]["result"]["rows"][0]["snapshot_date"].startswith(
            "2026-08-31")


class TestAReaderSAssessmentVocabulary:
    """"Does that look consistent?" ran a second analysis of the same book."""

    @pytest.mark.parametrize("said", [
        "Does that look consistent?",
        "Does this look right?",
        "How does that look?",
        "Does that add up?",
        "Can I trust these?",
        "Anything odd about that?",
    ])
    def test_it_asks_about_the_result(self, said):
        from backend.orchestration import reuse as ru

        assert ru.wants(said), said

    def test_a_breakdown_request_still_composes(self):
        from backend.orchestration import reuse as ru

        assert not ru.wants("Break that down by region.")


class TestABreakdownHeadlineNamesTheBreakdown:
    def test_the_leading_group_is_named(self):
        _, state = advanced("Show me ECL by month for the last 12 months.")
        answered = answer("Break the whole book down by region.", state=state)
        said = headline(answered)
        assert "region" in said.lower() or any(
            r in said for r in ("Riyadh", "Makkah", "Eastern Province")), said


class TestAWhichQuestionIsComputedNotInvestigated:
    """"Which subsegment has deteriorated most on X?" names what to rank."""

    def test_it_is_not_read_as_a_request_to_look(self):
        from backend.orchestration import investigation as iv

        assert not iv.wants_investigation(
            "Which product subsegment has deteriorated most on 90+ "
            "delinquency since the start of the year?")
        # A sentence that names no measure IS a request to look.
        assert iv.wants_investigation("What has deteriorated this year?")
        assert iv.wants_investigation("Which region has deteriorated most?")

    def test_a_named_measure_beats_the_composite(self):
        answered = answer("Which product subsegment has deteriorated most on "
                          "90+ delinquency since the start of the year?")
        assert answered.build.dimension == "product_subsegment"
        assert "dpd" in {m.field for m in answered.build.matches}

    def test_the_band_is_a_level_not_a_movement(self, book):
        answered = answer("Which product subsegment has deteriorated most on "
                          "90+ delinquency since the start of the year?")
        described = [c.describe() for c in answered.build.conditions]
        assert any("rose" in d for d in described), described
        assert any("90" in d for d in described), (
            "the band the question named was dropped")

    def test_the_rows_reconcile(self):
        import pandas as pd

        answered = answer("Which product subsegment has deteriorated most on "
                          "90+ delinquency since the start of the year?")
        opening = _month(answered.build.opening)[["facility_id", "dpd"]]
        closing = _month(answered.build.closing)[
            ["facility_id", "dpd", "product_subsegment"]]
        both = closing.merge(opening, on="facility_id", suffixes=("_c", "_o"))
        kept = both[(both.dpd_c >= 90) & (both.dpd_c > both.dpd_o)].copy()
        kept["chg"] = kept.dpd_c - kept.dpd_o
        truth = kept.groupby("product_subsegment").chg.sum().sort_values(
            ascending=False)
        rows = answered.runtime.rows
        assert len(rows) == len(truth), (len(rows), len(truth))
        assert rows[0]["product_subsegment"] == truth.index[0]
        assert float(rows[0]["dpd_change"]) == pytest.approx(
            float(truth.iloc[0]), abs=0.5)

    def test_a_grouped_cohort_answers_a_which_question(self):
        from backend.orchestration import fidelity as fd

        answered = answer("Which product subsegment has deteriorated most on "
                          "90+ delinquency since the start of the year?")
        assert fd.executed_objective(answered.build) == fd.RANKING
        assert not [w for w in answered.build.warnings
                    if "one question with another" in w], answered.build.warnings


class TestTheYearSoFarIsTheYearSoFar:
    """"Since the start of the year" was answered with 25 months."""

    MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)]

    @pytest.mark.parametrize("said", [
        "since the start of the year",
        "since the beginning of the year",
        "year to date",
        "ytd",
        "so far this year",
    ])
    def test_it_opens_in_january(self, said):
        from backend.orchestration import periods as prd

        months = [m for m in self.MONTHS if "2024-08" <= m <= "2026-08"]
        found = prd.read_period_intent(said, months)
        assert (found.from_period, found.to_period) == ("2026-01", "2026-08"), (
            said, found)

    def test_the_whole_history_still_reads_as_the_whole_history(self):
        from backend.orchestration import periods as prd

        months = [m for m in self.MONTHS if "2024-08" <= m <= "2026-08"]
        found = prd.read_period_intent("since the start", months)
        assert (found.from_period, found.to_period) == ("2024-08", "2026-08")


class TestANarrowingInheritsTheSettledShape:
    """The retail book is keyed per facility, so every sentence "asked" for one."""

    def test_the_grain_guard_reads_the_sentence(self):
        assert not ap._asks_for_an_entity_grain("Show me personal finance.")
        assert ap._asks_for_an_entity_grain("Which customers drove that?")
        assert ap._asks_for_an_entity_grain("Show me the facilities.")


# ---------------------------------------------------------------------------
# The third battery: a ratio, a forecast, an appetite and a repeat
# ---------------------------------------------------------------------------


class TestARatioIsAQuotientOfSums:
    """Stage 3 coverage answered 0.64 where the book is 35.82%."""

    def test_the_plan_sums_both_halves(self):
        answered = answer("What is the stage 3 coverage ratio now versus a "
                          "year ago?")
        groups = [o for o in (answered.build.plan or {}).get("operations") or []
                  if str(o.get("op")).upper() == "GROUP"]
        functions = {str(a.get("function")) for o in groups
                     for a in (o.get("params") or {}).get("aggregates") or []}
        assert functions == {"sum"}, functions

    def test_it_reconciles_with_the_book(self, book):
        answered = answer("What is the stage 3 coverage ratio now versus a "
                          "year ago?")
        latest = [r for r in answered.runtime.rows
                  if str(r.get("reporting_month")) == LATEST][0]
        stage3 = book[book.ifrs9_stage == 3]
        truth = float(stage3.ecl_final_sar.sum()
                      / stage3.gross_carrying_amount_sar.sum())
        assert float(latest["ecl_coverage_ratio"]) == pytest.approx(truth,
                                                                   rel=1e-9)
        assert 0.3 < truth < 0.4, "the oracle itself must be the weighted ratio"

    def test_the_two_halves_are_lineage(self):
        from backend.orchestration import presentation as pr

        answered = answer("What is the stage 3 coverage ratio now versus a "
                          "year ago?")
        by_name = {c["name"]: c for c in pr.schema(answered.runtime,
                                                   answered.build)}
        assert by_name["ecl_coverage_ratio__numerator"]["hidden"] is True
        assert by_name["ecl_coverage_ratio"]["hidden"] is False

    def test_an_average_of_a_ratio_column_is_still_an_average(self, book):
        answered = answer(f"What is the average debt burden ratio at {LATEST}?")
        got = float(answered.runtime.rows[0]["debt_burden_ratio"])
        assert got == pytest.approx(float(book.debt_burden_ratio.mean()),
                                    rel=1e-9)


class TestTheRetailUnitsAreTyped:
    """Fifty-four ratio columns were typed TEXT, so no chart could use them."""

    @pytest.mark.parametrize("unit,semantic", [
        ("ratio", "ratio"), ("probability", "ratio"), ("count", "count"),
        ("months", "count"), ("points", "count"),
        ("percentage points", "percent"),
    ])
    def test_a_governed_unit_reaches_the_presentation_layer(self, unit,
                                                            semantic):
        from backend.orchestration import presentation as pr

        class _Concept:
            id = ""
            unit = ""
            is_ordinal = False

        concept = _Concept()
        concept.unit = unit
        got = pr._numeric("x", {"x": concept})
        assert got["semantic"] == semantic, (unit, got)

    def test_a_ratio_result_can_be_drawn(self):
        from backend.orchestration import visualize

        answered = answer("What is the stage 3 coverage ratio now versus a "
                          "year ago?")
        from backend.orchestration import presentation as pr

        columns = pr.schema(answered.runtime, answered.build)
        visual = visualize.choose(columns, answered.runtime.rows,
                                  requested="chart",
                                  question="Draw that as a chart.")
        assert visual.chart != "table", visual.to_dict()


class TestWhatCreditProbeWillNotDo:
    """A forecast and an appetite judgement are said, not attempted."""

    @pytest.mark.parametrize("said", [
        "If ECL keeps moving like this, where does it land in six months?",
        "Forecast ECL for next year.",
        "What will ECL be at year end?",
    ])
    def test_a_projection_is_declined(self, said):
        answered = orchestrator.answer(said)
        assert answered.clarification, said
        assert "does not project" in str(answered.clarification), answered

    def test_an_ordinary_question_is_not(self):
        assert not orchestrator._asks_for_a_projection(
            f"What is total ECL at {LATEST}?")
        assert not orchestrator._asks_for_a_projection(
            "Show the monthly ECL series.")

    @pytest.mark.parametrize("said", [
        "Is that within appetite?",
        "Are we within the limit?",
        "Is that above tolerance?",
    ])
    def test_an_appetite_question_is_declined(self, said):
        assert "no risk appetite limits" in orchestrator._asks_about_appetite(
            said), said

    def test_an_ordinary_comparison_is_not(self):
        assert not orchestrator._asks_about_appetite(
            "Is ECL higher than last month?")


class TestTheRepeatGuardReadsWhatIsNew:
    """Three consecutive questions came back as the same customers."""

    def test_the_same_warnings_are_not_novelty(self):
        continuation = cv.Continuation(action=cv.CONTINUE)
        state = cv.ConversationState(
            ir={"dataset": "d", "period": "p", "operations": [{"op": "SCAN"}]},
            plan_summary="the previous analysis",
            plan_warnings=["the same caveat"])
        build = type("B", (), {
            "plan": {"dataset": "d", "period": "p",
                     "operations": [{"op": "SCAN"}]},
            "warnings": ["the same caveat"]})()
        assert orchestrator._repeats_the_previous_plan(
            build, state, continuation, "Something else entirely?")

    def test_a_new_warning_is(self):
        continuation = cv.Continuation(action=cv.CONTINUE)
        state = cv.ConversationState(
            ir={"dataset": "d", "period": "p", "operations": [{"op": "SCAN"}]},
            plan_summary="the previous analysis",
            plan_warnings=["the same caveat"])
        build = type("B", (), {
            "plan": {"dataset": "d", "period": "p",
                     "operations": [{"op": "SCAN"}]},
            "warnings": ["something new to say"]})()
        assert orchestrator._repeats_the_previous_plan(
            build, state, continuation, "Something else entirely?") == ""


class TestAHandlerSettlesItsMeasure:
    """The ECL walkthrough left nothing for the next question to inherit."""

    def test_the_measure_is_remembered(self):
        _, state = advanced("Walk me through the ECL movement this month.")
        assert state.concepts == ["expected credit loss"], state.concepts
        assert state.periods == ["2026-07", LATEST], state.periods

    def test_the_follow_up_is_answered(self, book):
        _, state = advanced("Walk me through the ECL movement this month.")
        answered = answer("Which stage moved most?", state=state)
        assert answered.build.dimension == "ifrs9_stage"
        said = headline(answered)
        assert "Stage 2" in said, said

    def test_which_group_moved_most_continues(self):
        from backend.orchestration import referents

        _, state = advanced("Walk me through the ECL movement this month.")
        read = referents.resolve("Which stage moved most?", state)
        assert read.action == cv.CONTINUE


class TestAShareOfAState:
    """"What proportion of the book is restructured?" measured the amount."""

    def test_the_portfolio_share_reconciles(self, book):
        answered = answer("What proportion of the book is restructured?")
        assert answered.build.shape == ap.SHARE
        row = answered.runtime.rows[0]
        truth = (book[book.restructured_flag].gross_carrying_amount_sar.sum()
                 / book.gross_carrying_amount_sar.sum() * 100)
        assert float(row["share_pct"]) == pytest.approx(float(truth), rel=1e-9)

    def test_the_breakdown_reconciles(self, book):
        answered = answer("What proportion of the book is restructured, "
                          "by product?")
        got = {str(r["product_label"]): float(r["share_pct"])
               for r in answered.runtime.rows}
        for product, share in got.items():
            rows = book[book.product_label == product]
            truth = (rows[rows.restructured_flag].gross_carrying_amount_sar.sum()
                     / rows.gross_carrying_amount_sar.sum() * 100)
            assert share == pytest.approx(float(truth), rel=1e-9), product

    def test_the_denominator_is_not_the_numerator(self):
        answered = answer("What proportion of the book is restructured?")
        row = answered.runtime.rows[0]
        assert float(row["population"]) > float(row["qualified"])

    def test_a_non_additive_measure_is_not_shared(self):
        # Days past due rolls up as a maximum; a share of it means nothing.
        from backend.orchestration import analysis_planner as planner

        answered = answer("What proportion of the book is restructured?")
        assert answered.build.matches[0].concept.unit == "SAR"
        assert planner._adds_up(answered.build.matches[0])


class TestANonAdditiveTotalIsNotStated:
    """Four group maxima were added into "868 days of days past due"."""

    def test_a_max_grouped_result_leads_with_the_highest(self, book):
        said = headline(answer(f"What is days past due by region at {LATEST}?"))
        assert "highest" in said, said
        truth = float(book.groupby("region_label").dpd.max().max())
        assert f"{truth:,.0f}" in said.replace(" days", ""), said

    def test_a_summed_result_still_states_its_total(self):
        said = headline(answer(f"What is ECL by region at {LATEST}?"))
        assert "15,952,109" in said, said


class TestAConcentrationQuestionNamesItsDimension:
    def test_it_is_read_as_a_breakdown(self):
        from backend.orchestration import dimensions as dm

        assert dm.read("Is ECL concentrated in one region?").dimension == \
            "region_label"
        assert dm.read("Is it concentrated in a few products?").dimension == \
            "product_label"
        assert dm.read("Is exposure concentrated?").dimension == ""


# ---------------------------------------------------------------------------
# The fourth battery: a Head of Retail Risk typing quickly
# ---------------------------------------------------------------------------


class TestACountIsNotARate:
    """"how many custmers are 60+ dpd" answered "60+ DPD Rate is 1.06%"."""

    def test_the_route_declines_a_count(self):
        from backend.orchestration import metric_route

        assert metric_route.read("how many custmers are 60+ dpd") is None
        assert metric_route.read("what is the 60+ DPD rate?") is not None

    def test_the_count_reconciles(self, book):
        answered = answer("how many custmers are 60+ dpd")
        got = int(next(v for v in answered.runtime.rows[0].values()
                       if isinstance(v, (int, float))))
        assert got == int(book[book.dpd >= 60].customer_id.nunique())


class TestAPossessiveKeepsThePopulation:
    """"and what's their total exposure" answered for the whole book."""

    def test_the_referent_is_read(self):
        from backend.orchestration import referents

        assert referents.points_at_the_previous_population(
            "and what's their total exposure")
        assert referents.points_at_the_previous_population(
            "break it down by city pls")
        assert not referents.points_at_the_previous_population(
            "What is total exposure?")

    def test_the_condition_survives_a_named_measure(self, book):
        _, state = advanced("how many custmers are 60+ dpd")
        answered = answer("and what's their total exposure", state=state)
        described = [c.describe() for c in answered.build.conditions]
        assert any("60" in d for d in described), described
        truth = float(book[book.dpd >= 60].gross_carrying_amount_sar.sum())
        assert float(values(answered)["total"]) == pytest.approx(truth, abs=1.0)

    def test_a_breakdown_keeps_it_too(self, book):
        _, state = advanced("how many custmers are 60+ dpd")
        _, state = advanced("and what's their total exposure", state)
        answered = answer("break it down by city pls", state=state)
        rows = {str(r["city"]): float(r["gross_carrying_amount_sar"])
                for r in answered.runtime.rows}
        truth = (book[book.dpd >= 60].groupby("city")
                 .gross_carrying_amount_sar.sum())
        assert len(rows) == len(truth), (len(rows), len(truth))
        for city, amount in rows.items():
            assert amount == pytest.approx(float(truth[city]), abs=1.0), city

    def test_a_superlative_without_a_figure_keeps_it(self, book):
        _, state = advanced("how many custmers are 60+ dpd")
        _, state = advanced("and what's their total exposure", state)
        _, state = advanced("break it down by city pls", state)
        answered = answer("which city is worst", state=state)
        truth = (book[book.dpd >= 60].groupby("city")
                 .gross_carrying_amount_sar.sum().idxmax())
        assert truth in headline(answered), headline(answered)


class TestEnglishSpelling:
    def test_a_dimension_plural(self):
        from backend.orchestration import assembly as asm
        from backend.orchestration import scope as sc

        assert asm._pluralise("city") == "cities"
        assert asm._pluralise("region") == "regions"
        assert asm._pluralise("cities") == "cities"
        assert sc._plural("city") == "cities"
        assert sc._plural("customer") == "customers"

    def test_punctuation_is_not_a_misspelling(self):
        from backend.orchestration import spelling

        fixed = spelling.normalise("and what's their total exposure")
        assert not [c for c in fixed.changes if "what" in str(c).lower()], \
            fixed.changes
        assert spelling.normalise("how many custmers are 60+ dpd").changes


class TestACarriedPopulationIsScopeNotACondition:
    def test_it_is_not_named_as_a_condition(self):
        _, state = advanced("how many custmers are 60+ dpd")
        _, state = advanced("break it down by city pls", state)
        answered = answer("ok now compare that to 3 months ago", state=state)
        said = headline(answered)
        assert "restricted to the previous answer" not in said.lower(), said

    def test_a_grouped_aggregate_answers_a_which_question(self):
        from backend.orchestration import fidelity as fd

        _, state = advanced("how many custmers are 60+ dpd")
        _, state = advanced("break it down by city pls", state)
        answered = answer("show me the top 5 only", state=state)
        assert not [w for w in answered.build.warnings
                    if "one question with another" in w], answered.build.warnings
        del fd


# ---------------------------------------------------------------------------
# The fifth and sixth batteries: a scorecard, a stage and a flow
# ---------------------------------------------------------------------------


class TestAValidationQuestionIsNotOutOfScope:
    """"What's the Gini?" was refused as data the book does not hold."""

    def test_the_coverage_check_exempts_it(self):
        from backend.orchestration import scorecard_route as sr

        assert sr.is_a_validation_question("What's the Gini?")
        assert sr.is_a_validation_question(
            "Is it still fit for purpose?",
            carried_model="retail_app_personal_loan")
        assert not sr.is_a_validation_question("Is it still fit for purpose?")

    def test_the_gini_is_answered_in_the_thread(self):
        _, state = advanced("How is our personal finance application "
                            "scorecard performing?")
        answered = answer("What's the Gini?", state=state)
        assert answered.result.rows[0]["test_id"] == "DISC-GINI"
        assert "0.31" in str(answered.result.answer), answered.result.answer

    def test_a_judgement_about_the_model_reaches_the_findings(self):
        _, state = advanced("How is our personal finance application "
                            "scorecard performing?")
        for said in ("Is it still fit for purpose?",
                     "Should we redevelop it?",
                     "What would you tell the model risk committee?"):
            answered = answer(said, state=state)
            assert "findings" in str(answered.result.answer), (said,
                                                               answered.result)


class TestAConstrainedFieldIsNotTheMeasureAtOneDate:
    """"Show me the Stage 2 book" ranked facilities by the stage number."""

    def test_the_measure_is_the_exposure(self):
        answered = answer("Show me the Stage 2 book.")
        assert [m.field for m in answered.build.matches] != ["ifrs9_stage"]
        assert "ifrs9_stage" in {f for f, _ in answered.build.filters}

    def test_a_count_still_anchors_on_it(self, book):
        answered = answer("How many facilities are in Stage 2?")
        got = int(answered.runtime.rows[0]["facility_count"])
        assert got == int((book.ifrs9_stage == 2).sum())


class TestAFlowIsNotAStock:
    """"How many facilities moved into Stage 2?" answered 1,392 of 315."""

    def test_the_inflow_reconciles(self, book):
        answered = answer("How many facilities moved into Stage 2 this month?")
        got = int(answered.runtime.rows[0]["facility_count"])
        truth = int(((book.ifrs9_stage == 2)
                     & (book.previous_month_stage != 2)).sum())
        assert got == truth, (got, truth)
        assert got != int((book.ifrs9_stage == 2).sum())

    def test_the_outflow_reconciles(self, book):
        answered = answer("How many facilities moved out of Stage 2 "
                          "this month?")
        truth = int(((book.ifrs9_stage != 2)
                     & (book.previous_month_stage == 2)).sum())
        got = int(answered.runtime.rows[0]["facility_count"])
        assert got == truth, (got, truth)

    def test_the_sentence_says_it_moved(self):
        for said, phrase in (
                ("How many facilities moved into Stage 2 this month?",
                 "moved into Stage 2"),
                ("How many facilities moved out of Stage 2 this month?",
                 "moved out of Stage 2")):
            assert phrase in headline(answer(said)), said

    def test_a_stock_question_is_untouched(self):
        answered = answer("How many facilities are in Stage 2?")
        assert not answered.build.flow
        assert "moved" not in headline(answered)


class TestAPointerWithANounStillPointsBack:
    def test_on_that_population_is_read(self):
        from backend.orchestration import referents

        assert referents.points_at_the_previous_population(
            "What is the ECL coverage on that population?")
        assert not referents.points_at_the_previous_population(
            "What is the ECL coverage?")


class TestABroadLookNamesNoFigure:
    """"What's happening to 30+ DPD?" ran six probes over the whole book."""

    def test_a_named_figure_is_computed(self):
        from backend.orchestration import investigation as iv

        assert not iv.wants_investigation("What's happening to 30+ DPD?")
        assert not iv.wants_investigation("What's happening to ECL?")
        assert iv.wants_investigation("What's happening?")
        assert iv.wants_investigation("What's going on with the book?")


class TestAnExclusionRemovesRatherThanRestricts:
    """"Show ECL by product, excluding Stage 3" filtered TO Stage 3."""

    @pytest.mark.parametrize("said", [
        "Show ECL by product, excluding Stage 3.",
        "Show ECL by product, not Stage 3.",
        "Show ECL by product, other than Stage 3.",
    ])
    def test_the_stage_is_removed(self, said):
        answered = answer(said)
        assert ("ifrs9_stage", "3") not in [
            (f, str(v)) for f, v in answered.build.filters], said
        assert any(c.field == "ifrs9_stage" and c.op == "ne"
                   for c in answered.build.conditions), said

    def test_a_restriction_is_still_a_restriction(self):
        answered = answer("Show ECL by product for Stage 3.")
        assert ("ifrs9_stage", "3") in [
            (f, str(v)) for f, v in answered.build.filters]

    def test_the_rows_reconcile(self, book):
        answered = answer("Show ECL by product, excluding Stage 3.")
        got = {str(r["product_label"]): float(r["ecl_final_sar"])
               for r in answered.runtime.rows}
        truth = (book[book.ifrs9_stage != 3].groupby("product_label")
                 .ecl_final_sar.sum())
        assert len(got) == len(truth)
        for product, amount in got.items():
            assert amount == pytest.approx(float(truth[product]), abs=1.0)

    def test_a_bound_is_not_a_negation(self):
        answered = answer("Which customers have ECL not more than 100,000?")
        assert not [c for c in answered.build.conditions if c.op == "ne"]


class TestAFlowIsReadAtOneDate:
    """A flow planned across two dates never read the prior column."""

    def test_the_inflow_amount_reconciles(self, book):
        _, state = advanced("Show me the Stage 2 book.")
        answered = answer("How much of it moved in this month?", state=state)
        truth = float(book[(book.ifrs9_stage == 2)
                           & (book.previous_month_stage != 2)]
                      .ead_base_sar.sum())
        assert float(values(answered)["total"]) == pytest.approx(truth, abs=1.0)
        assert "moved into Stage 2" in headline(answered)

    def test_the_outflow_amount_reconciles(self, book):
        _, state = advanced("Show me the Stage 2 book.")
        answered = answer("And how much moved out?", state=state)
        truth = float(book[(book.ifrs9_stage != 2)
                           & (book.previous_month_stage == 2)]
                      .ead_base_sar.sum())
        assert float(values(answered)["total"]) == pytest.approx(truth, abs=1.0)
        assert "moved out of Stage 2" in headline(answered)

    def test_the_two_flows_differ(self):
        _, state = advanced("Show me the Stage 2 book.")
        one = float(values(answer("How much of it moved in this month?",
                                  state=state))["total"])
        two = float(values(answer("And how much moved out?",
                                  state=state))["total"])
        assert one != two, "the same figure for opposite flows"

    def test_an_outflow_is_anchored_on_last_month(self):
        answered = answer("How many facilities moved out of Stage 2 "
                          "this month?")
        assert ("previous_month_stage", "2") in [
            (f, str(v)) for f, v in answered.build.filters]
        assert not [c for c in answered.build.conditions
                    if c.field == "previous_month_stage"]


class TestARankingSurvivesItsOwnNarrowing:
    """"Take out anyone already in Stage 3" replaced a list with a total."""

    def test_the_shape_is_kept(self):
        _, state = advanced("Give me the worst 20 customers by expected "
                            "credit loss.")
        answered = answer("Take out anyone already in Stage 3.", state=state)
        assert answered.build.shape == ap.RANKING, answered.build.shape
        assert all("customer_id" in r for r in answered.runtime.rows)

    def test_the_twenty_reconcile(self, book):
        answered = answer("Give me the worst 20 customers by expected "
                          "credit loss.")
        got = [str(r["customer_id"]) for r in answered.runtime.rows]
        truth = (book.groupby("customer_id").ecl_final_sar.sum()
                 .sort_values(ascending=False).head(20).index)
        assert set(got) == set(truth)

    def test_the_grain_of_the_exclusion_is_stated(self):
        """"Anyone" means the customer, and the caveat says which grain ran.

        This gate first asserted the caveat that said the test had run on each
        FACILITY — which was the honest description of what the plan then did,
        and the wrong answer to the question. "Take out anyone already in
        Stage 3" is about people: a customer holding one Stage 3 facility is
        out, and nine customers survived where five should have. The plan now
        excludes the whole customer, so the sentence the reader is owed is the
        one that says so.
        """
        _, state = advanced("Give me the worst 20 customers by expected "
                            "credit loss.")
        answered = answer("Take out anyone already in Stage 3.", state=state)
        assert any("applied to the whole customer" in w
                   for w in answered.build.warnings), answered.build.warnings

    def test_a_breakdown_is_not_told_about_a_grain_it_does_not_have(self):
        answered = answer("Show ECL by product, excluding Stage 3.")
        assert not [w for w in answered.build.warnings
                    if "one row per customer" in w]

    def test_the_exclusion_is_not_reported_as_dropped(self):
        answered = answer("Show ECL by product, excluding Stage 3.")
        assert not [w for w in answered.build.warnings
                    if "could not apply the exclusion" in w]

    def test_no_python_repr_reaches_the_reader(self):
        answered = answer("Show ECL by product, excluding Stage 3.")
        for said in answered.build.warnings:
            assert "{'" not in said and "'kind'" not in said, said


# ---------------------------------------------------------------------------
# The presentation fixes. Six defects the last adversarial pass left open, each
# reproduced in a thread before it was fixed and gated here so it cannot come
# back on the morning it matters.
# ---------------------------------------------------------------------------


class TestAnExistenceQuestionIsACount:
    """"Are there any Stage 3 home-finance facilities?" answered "33"."""

    def test_the_facilities_are_counted_not_their_stage_added_up(self, book):
        answered = answer("Are there any Stage 3 home-finance facilities "
                          f"in August 2026?")
        truth = int(len(book[(book.ifrs9_stage == 3)
                             & (book.product_label == "Home Finance")]))
        assert truth == 11, f"the shipped lake has moved: {truth}"
        assert float(values(answered)["total"]) == pytest.approx(truth)
        assert str(truth) in headline(answered), headline(answered)

    def test_the_stage_is_not_the_measure(self):
        answered = answer("Are there any Stage 3 home-finance facilities "
                          "in August 2026?")
        said = headline(answered).lower()
        assert "ifrs 9 stage in" not in said, said

    def test_it_is_planned_at_the_portfolio_grain(self):
        answered = answer("Are there any Stage 3 home-finance facilities "
                          "in August 2026?")
        assert not answered.clarification


class TestACarriedFilterIsNotSomethingTheQuestionAsked:
    """A contract that absorbed the thread's scope accused the plan of losing
    a population the question never named."""

    def test_a_restated_population_replaces_the_threads(self):
        from backend.orchestration import fidelity as fd

        state = cv.ConversationState()
        for said in ("Show me August 2026 retail exposure and weighted ECL "
                     "by product.",
                     "Now only personal finance.",
                     "aug 2026 personal finance salary transfer stage2 ecl "
                     "vs jul and tell me what moved most"):
            _, state = advanced(said, state)
        asked = "Are there any Stage 3 home-finance facilities in August 2026?"
        # Read the way the planner reads it: the semantic reading is what
        # tells the contract which population the SENTENCE named.
        answered = answer(asked, state=state)
        contract = fd.read(asked, reading=answered.reading, state=state)
        assert "Personal Finance" not in contract.population, contract.population
        assert "True" not in contract.population, contract.population

    def test_no_boolean_is_offered_as_a_population(self):
        from backend.orchestration import fidelity as fd

        state = cv.ConversationState()
        state.filters = [{"field": "salary_transfer", "value": "True"}]
        contract = fd.read("What is ECL coverage?", state=state)
        assert "True" not in contract.population, contract.population

    def test_the_answer_carries_no_caveat_about_a_scope_it_replaced(self):
        state = cv.ConversationState()
        for said in ("Show me August 2026 retail exposure and weighted ECL "
                     "by product.",
                     "Now only personal finance.",
                     "aug 2026 personal finance salary transfer stage2 ecl "
                     "vs jul and tell me what moved most"):
            _, state = advanced(said, state)
        answered = answer("Are there any Stage 3 home-finance facilities "
                          "in August 2026?", state=state)
        for said in answered.build.warnings:
            assert "did not restrict to it" not in said, said


class TestABreakdownIsNotTheSettledMovement:
    """"Break ECL down by product", asked after a 25-month trend, came back
    as a two-year fall over the whole book."""

    def test_it_is_a_breakdown_at_the_settled_month(self, book):
        _, state = advanced("Show the 25-month weighted ECL trend for "
                            "credit cards.")
        answered = answer("Break ECL down by product", state=state)
        assert answered.build.shape != ap.MOVEMENT, answered.build.shape
        truth = float(book.ecl_final_sar.sum())
        assert float(values(answered)["total"]) == pytest.approx(truth, rel=1e-6)

    def test_it_does_not_read_as_a_fall(self):
        _, state = advanced("Show the 25-month weighted ECL trend for "
                            "credit cards.")
        said = headline(answer("Break ECL down by product", state=state)).lower()
        assert "fell" not in said, said

    def test_the_carried_product_is_not_asserted_against_it(self):
        _, state = advanced("Show the 25-month weighted ECL trend for "
                            "credit cards.")
        answered = answer("Break ECL down by product", state=state)
        for said in answered.build.warnings:
            assert "Credit Card" not in said or "restrict" not in said, said

    def test_a_sentence_that_refers_back_still_opens_the_movement(self):
        _, state = advanced("Compare weighted ECL for credit cards between "
                            "July 2026 and August 2026.")
        answered = answer("Break that down by product", state=state)
        assert answered.build.shape == ap.MOVEMENT, answered.build.shape


class TestAPrioritisationSaysWhatOrderedIt:
    """"What are the three numbers that matter most?" was a menu of concepts,
    and then a prioritisation with nothing said about what ordered it."""

    def test_an_open_judgement_question_runs_the_governed_review(self):
        said = headline(answer("What would you escalate to the board?"))
        assert "governed checks" in said, said

    def test_it_says_what_the_ordering_is_and_is_not(self):
        said = headline(answer("What are the three numbers that matter "
                               "most?"))
        assert "not by a judgement of importance" in said, said

    def test_the_attention_question_reads_its_own_window(self):
        said = headline(answer("What needs my attention in the retail "
                               "portfolio this month?"))
        assert "2026-07" in said and "2026-08" in said, said


class TestAReviewSettlesWhatItLedWith:
    """The turn after a governed review had nothing to inherit."""

    def test_the_follow_up_is_answered_rather_than_clarified(self):
        _, state = advanced("What needs my attention in the retail portfolio "
                            "this month?")
        answered = orchestrator.answer("Which product is driving it?",
                                       state=state)
        assert not answered.clarification, answered.clarification

    def test_it_inherits_the_measure_the_answer_led_with(self):
        _, state = advanced("What needs my attention in the retail portfolio "
                            "this month?")
        assert state.metrics, "the review settled no measure"
        answered = answer("Which product is driving it?", state=state)
        assert answered.build.dimension == "product_label", \
            answered.build.dimension
        assert str(state.metrics[0]).lower() in headline(answered).lower(), \
            (state.metrics, headline(answered))

    def test_it_inherits_the_window_the_review_measured(self):
        _, state = advanced("What needs my attention in the retail portfolio "
                            "this month?")
        assert (state.opening_period, state.closing_period) \
            == ("2026-07", "2026-08"), (state.opening_period,
                                        state.closing_period)


class TestAWhatIfNarrowingIsNotANewScenario:
    """"Only salary-transfer customers." was refused for naming no shock."""

    def test_a_bare_population_narrows_the_scenario_on_the_table(self):
        from backend.retail import whatif_language as wl

        carried = {"shocks": {"pd_relative": 0.20},
                   "filters": {"product_code": "PL"}, "month": "2026-08"}
        ask = wl.read("Only salary-transfer customers.",
                      months=["2026-07", "2026-08"], carried=carried)
        assert ask.shocks == {"pd_relative": 0.20}, ask.shocks
        assert ask.filters.get("salary_transfer_flag") is True, ask.filters
        assert ask.filters.get("product_code") == "PL", ask.filters
        assert not ask.is_neutral

    def test_a_sentence_that_merely_names_a_product_starts_fresh(self):
        """"Show me credit cards" is a request to LOOK, not to re-shock."""
        from backend.retail import whatif_language as wl

        carried = {"shocks": {"pd_relative": 0.20},
                   "filters": {"product_code": "PERSONAL_LOAN"},
                   "month": "2026-08"}
        ask = wl.read("Show me credit cards", months=["2026-08"],
                      carried=carried)
        assert ask.shocks == {}, ask.shocks

    def test_it_is_still_refused_when_there_is_nothing_to_narrow(self):
        from backend.retail import whatif_language as wl

        ask = wl.read("Only salary-transfer customers.", months=["2026-08"],
                      carried={})
        assert ask.is_neutral, "a scenario was invented out of a narrowing"

    def test_a_sentence_that_states_its_own_shock_is_not_overwritten(self):
        from backend.retail import whatif_language as wl

        carried = {"shocks": {"lgd_relative": 0.10}, "month": "2026-08"}
        ask = wl.read("Increase PD by 20% relative for stage 2.",
                      months=["2026-08"], carried=carried)
        assert ask.shocks.get("pd_relative") == pytest.approx(0.20), ask.shocks


class TestADraftIsWrittenNotRepeated:
    """"Draft the response to an auditor." returned the previous answer."""

    def test_the_word_draft_survives_the_speller(self):
        from backend.orchestration import spelling

        fixed = spelling.normalise("Draft the response to an auditor.")
        assert "draft" in fixed.text.lower(), fixed.text
        assert "drift" not in fixed.text.lower(), fixed.text

    def test_it_is_marked_as_a_draft_and_names_what_it_is_from(self):
        _, state = advanced("Has the personal-finance application scorecard "
                            "population drifted?")
        answered = orchestrator.answer("Draft the response to an auditor.",
                                       state=state)
        said = str(getattr(answered.result, "answer", "") or "")
        assert said.startswith("Draft, for review."), said[:200]
        assert "population drifted" in said, said[:300]

    def test_it_does_not_repeat_the_previous_headline(self):
        previous, state = advanced("Has the personal-finance application "
                                   "scorecard population drifted?")
        before = str(getattr(previous.result, "answer", "") or "")
        answered = orchestrator.answer("Draft the response to an auditor.",
                                       state=state)
        said = str(getattr(answered.result, "answer", "") or "")
        assert said.strip() != before.strip(), said[:200]

    def test_it_claims_no_approval(self):
        _, state = advanced("Has the personal-finance application scorecard "
                            "population drifted?")
        answered = orchestrator.answer("Draft the response to an auditor.",
                                       state=state)
        said = str(getattr(answered.result, "answer", "") or "").lower()
        assert "nothing in it has been reviewed or approved" in said, said[:400]

    def test_nothing_is_drafted_from_a_standing_start(self):
        answered = orchestrator.answer("Draft the response to an auditor.")
        said = str(getattr(answered.result, "answer", "") or "")
        assert not said.startswith("Draft, for review."), said[:200]
