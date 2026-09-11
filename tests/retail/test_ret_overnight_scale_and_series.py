"""
Three questions a Head of Retail Risk asks in the first ten minutes, and the
three different ways they were wrong.

**A percentage bound against a decimal column.** "How many customers have a
debt burden ratio above 50 percent?" compiled to `debt_burden_ratio > 50`. The
retail book holds that ratio as a DECIMAL — 0.598, not 59.8 — so no row in the
book satisfied it and the answer was empty. Nothing said the bound had been
read on a different scale from the column. The true answer is 6,608 customers.

**A measure's own name read as a population.** "What is the average LOAN to
value for home finance?" was REFUSED: "CreditProbe read this as a question
about one row per facility … but the governed data behind it can only be
reported as one row for the whole book." `\\bloans?\\b` is a facility noun, and
it sits inside the name of the measure. A measure the reader named is not a
population they asked for.

**A ratio averaged across facilities.** "Show the ECL coverage trend for the
last 12 months" came back as the mean of nineteen thousand per-facility
coverage ratios — 2.17%, where the book's coverage is 0.77% — over TWO points
where twelve were asked for. A coverage ratio is SUM(ECL) over SUM(gross
carrying amount); only the metric definition knows that, and the metric route
declined every trend along with every other movement.

**And a composition enumerated rather than named.** "Break August 2026
exposure into Stage 1, Stage 2 and Stage 3" read the three stages as a SET —
which is the whole book — and answered with ONE row: 2,082,852,856 SAR
labelled stage 3.
"""

from __future__ import annotations

import glob

import pandas as pd
import pytest

from backend.orchestration import dimensions as dm
from backend.orchestration import metric_route
from backend.orchestration import orchestrator
from backend.orchestration import semantics as sm
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


def rows(question: str) -> list[dict]:
    answered = orchestrator.answer(question)
    assert not answered.clarification, (
        f"{question!r} was refused: "
        f"{getattr(answered.clarification, 'question', answered.clarification)}")
    runtime = getattr(answered, "runtime", None)
    if runtime is not None and getattr(runtime, "rows", None):
        return list(runtime.rows)
    result = getattr(answered, "result", None)
    return list(getattr(result, "rows", None) or [])


class TestABoundIsReadOnTheColumnSScale:
    def test_a_percentage_against_a_decimal_ratio_is_converted(self, book):
        got = rows(f"How many customers have a debt burden ratio above 50 "
                   f"percent at {LATEST}?")
        assert len(got) == 1
        assert int(got[0]["customer_count"]) == int(
            book[book.debt_burden_ratio > 0.5].customer_id.nunique())

    def test_a_percentage_against_a_utilisation_ratio_is_converted(self, book):
        got = rows(f"How many facilities have utilisation above 90% at "
                   f"{LATEST}?")
        assert len(got) == 1
        assert int(got[0]["facility_count"]) == int(
            book[book.utilisation_ratio > 0.9].facility_id.nunique())

    def test_a_bound_with_no_percentage_is_left_alone(self, book):
        got = rows(f"How many facilities have days past due above 30 at "
                   f"{LATEST}?")
        assert int(got[0]["facility_count"]) == int(
            book[book.dpd > 30].facility_id.nunique())

    def test_the_conversion_is_stated_on_the_condition(self):
        from backend.orchestration import concepts as cx
        from backend.orchestration import context as governed_context
        from backend.data_access import get_catalog

        text = "debt burden ratio above 50 percent"
        known = {d.name: {f["name"] for f in d.fields}
                 for d in governed_context.all_datasets()}
        match = cx.read_concepts(text, known=known,
                                 catalogue=get_catalog()).matches[0]
        condition = sm.threshold_condition(match, sm.find_threshold(text))
        assert condition.value == 0.5
        assert "decimal fraction" in condition.phrase, (
            "a silently rescaled bound is a silently different question")


class TestAMeasureIsNotAPopulation:
    def test_a_measure_whose_name_holds_an_entity_noun_is_answerable(
            self, book):
        got = rows(f"What is the average loan to value for home finance at "
                   f"{LATEST}?")
        assert len(got) == 1
        want = float(book[book.product_label == "Home Finance"]
                     .ltv_current_ratio.mean())
        assert float(got[0]["ltv_current_ratio"]) == pytest.approx(want,
                                                                   rel=1e-9)

    def test_a_real_request_for_facilities_still_lists_them(self):
        got = rows(f"Show me the facilities with the highest ECL at {LATEST}.")
        assert len(got) > 1
        assert all("facility_id" in r for r in got)


class TestAGovernedTrendComesFromTheMetric:
    def test_a_trend_is_routed_to_the_metric_engine(self):
        routed = metric_route.read("Show the ECL coverage trend for the last "
                                   "12 months.")
        assert routed is not None, "a trend fell through to the composer"
        assert routed.trend
        assert routed.dimension == "reporting_month"

    def test_a_comparison_between_two_dates_still_falls_through(self):
        assert metric_route.read(
            "How has ECL coverage changed since July 2026?") is None

    def test_a_single_figure_is_still_a_single_figure(self):
        routed = metric_route.read(f"What is ECL coverage at {LATEST}?")
        assert routed is not None and not routed.trend

    def test_the_series_is_the_ratio_of_sums_not_the_mean_of_ratios(self):
        got = rows("Show the ECL coverage trend.")
        latest = [r for r in got if r["label"] == LATEST]
        assert latest, "the series does not reach the latest month"
        assert float(latest[0]["value"]) == pytest.approx(0.7658778579, abs=1e-6), (
            "the mean of per-facility coverage ratios is 2.17%; the book's "
            "coverage is 0.77%")

    def test_the_series_reads_in_date_order(self):
        got = rows("Show the ECL coverage trend.")
        labels = [str(r["label"]) for r in got]
        assert labels == sorted(labels)
        assert len(labels) == 25

    def test_a_window_is_honoured(self):
        got = rows("Show the ECL coverage trend for the last 12 months.")
        assert len(got) == 13, (
            "twelve months of movement is thirteen observations; twenty-five "
            "is an honest superset and still not the answer")


class TestACompositionEnumeratedIsStillAComposition:
    def test_the_dimension_is_read_from_the_values_listed(self):
        found = dm.read("Break August 2026 exposure into Stage 1, Stage 2 and "
                        "Stage 3.")
        assert found.dimension == "ifrs9_stage"
        assert found.rule == "breakdown"

    def test_two_named_products_are_a_breakdown_by_product(self):
        found = dm.read("Split exposure between Credit Card and Personal "
                        "Finance")
        assert found.dimension == "product_label"

    def test_a_set_is_not_an_enumerated_breakdown(self):
        assert dm.read("Show Stage 2 and Stage 3 exposure at "
                       "2026-08").dimension == ""

    def test_the_stage_composition_has_three_bars(self, book):
        got = rows(f"Break {LATEST} exposure into Stage 1, Stage 2 and Stage "
                   f"3.")
        assert len(got) == 3, "the composition came back as one row"
        shown = {int(r["ifrs9_stage"]):
                 round(float(r["gross_carrying_amount_sar"]), 2) for r in got}
        want = {int(k): round(float(v), 2) for k, v in
                book.groupby("ifrs9_stage").gross_carrying_amount_sar.sum()
                .items()}
        assert shown == want


class TestARankingSumsTheSubjectSFacilities:
    """"Show me the worst 10 customers by expected credit loss" ranked each
    customer by their LARGEST FACILITY. The true top customer by ECL —
    199,719.56 SAR across two facilities — never appeared, and the share
    column was computed against 14,781,702 rather than the book's
    15,952,109.
    """

    def test_the_top_customer_is_the_top_customer(self, book):
        got = rows(f"Show me the worst 10 customers by expected credit loss "
                   f"at {LATEST}.")
        assert len(got) == 10
        want = book.groupby("customer_id").ecl_final_sar.sum().sort_values(
            ascending=False)
        assert got[0]["customer_id"] == want.index[0]
        assert round(float(got[0]["ecl_final_sar"]), 2) == round(
            float(want.iloc[0]), 2)

    def test_the_share_is_against_the_whole_book(self, book):
        got = rows(f"Show me the worst 10 customers by expected credit loss "
                   f"at {LATEST}.")
        population = float(got[0]["ecl_final_sar_population"])
        assert round(population, 2) == round(float(book.ecl_final_sar.sum()), 2)

    def test_the_order_is_the_book_s_order(self, book):
        got = rows(f"Show me the worst 10 customers by expected credit loss "
                   f"at {LATEST}.")
        want = list(book.groupby("customer_id").ecl_final_sar.sum()
                    .sort_values(ascending=False).index[:10])
        assert [r["customer_id"] for r in got] == want


class TestATrendIsTheWholeSeries:
    """"Show the 25-month weighted ECL trend for credit cards" — §22's first
    named visual, and one of §5's questions — was answered with TWO points,
    2025-08 and 2026-08, under the sentence "final ECL fell from 3,110,069 to
    3,061,762 between 2025-08 and 2026-08". The reader asked for twenty-five
    months, got two, and the two were not even the ends of the window they
    named.

    And the period column was typed TEXT, because only `period` and `*_period`
    were recognised as reporting-date spellings — so the visualisation gate,
    which draws a LINE over an ordered period axis, never saw one. A monthly
    series was drawn as a horizontal bar ranking.
    """

    def _result(self, question: str) -> dict:
        from backend.orchestration.executor import answer_investigation

        inv, _ = answer_investigation(question, persist=False)
        return inv.to_dict()["steps"][0]["result"]

    def test_a_twenty_five_month_trend_has_twenty_five_points(self, book):
        res = self._result("Show the 25-month weighted ECL trend for credit "
                           "cards.")
        rows = res["rows"]
        assert len(rows) == 25
        months = [r["reporting_month"] for r in rows]
        assert months == sorted(months), "a series must read in date order"
        assert months[0] == "2024-08" and months[-1] == "2026-08"

    def test_a_named_length_is_honoured(self):
        assert len(self._result("Show the 12-month ECL trend.")["rows"]) == 12

    def test_the_figures_are_the_book_s(self):
        import glob

        rows = self._result("Show the 25-month weighted ECL trend for credit "
                            "cards.")["rows"]
        got = {r["reporting_month"]: round(float(r["ecl_final_sar"]), 2)
               for r in rows}
        want = {}
        for path in sorted(glob.glob(
                "data/retail/analytics/retail_facility_month/"
                "reporting_month=*/*.parquet")):
            month = path.split("reporting_month=")[1].split("/")[0]
            frame = pd.read_parquet(path,
                                    columns=["ecl_final_sar", "product_label"])
            want[month] = round(float(
                frame[frame.product_label == "Credit Card"]
                .ecl_final_sar.sum()), 2)
        assert got == want

    def test_a_two_period_comparison_is_still_two_periods(self):
        res = self._result("How did ECL move between July and August 2026?")
        assert len(res["rows"]) == 2

    def test_a_period_axis_is_drawn_as_a_line(self):
        res = self._result("Show the 25-month weighted ECL trend for credit "
                           "cards.")
        assert res["visual"]["chart"] == "line", (
            "a monthly series drawn as a horizontal bar ranking puts the "
            "months in order of size")
        assert res["visual"]["chart_first"] is True

    def test_the_period_column_is_typed_as_a_period(self):
        res = self._result("Show the 25-month weighted ECL trend for credit "
                           "cards.")
        period = [c for c in res["columns"]
                  if c["name"] == "reporting_month"][0]
        assert period["semantic"] == "period", (
            "typed as text, the visualisation gate never sees a period axis")
