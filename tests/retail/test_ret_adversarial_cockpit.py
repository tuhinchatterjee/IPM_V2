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
