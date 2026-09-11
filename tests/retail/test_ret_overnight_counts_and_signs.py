"""
"How many customers …" and "negative disposable income".

Two question shapes a Head of Retail Risk uses constantly, and neither worked.

**A count returned the population it counts.** Every "how many customers …"
question in the product came back as a LIST — one row per customer, each
carrying `customer_count: 1` — under a question asking for a single figure.
The grain reader saw the noun "customers" and asked for one row per customer,
which is right for "show me the customers in Stage 2" and wrong for "how
many". The reader had to count the rows themselves, and the table was
truncated long before they could.

Fixing the shape exposed the refusal underneath it. With the plan correctly
rolled up to one row, the grain contract compared the requested grain
(customer) against the plan's (portfolio) and refused the question outright:

    "CreditProbe read this as a question about one row per customer — the
     question names customers, so each row is a customer — but the governed
     data behind it can only be reported as one row for the whole book."

A plain, answerable question, refused. The same refusal met "How many
facilities have days past due above 30?"

**A sign was not a bound.** "How many customers have NEGATIVE disposable
income?" carried no bound word and no digit, so the threshold reader saw
nothing: the condition was dropped silently and the answer was a ranking of
the HIGHEST POSITIVE values — 59,187 SAR at the top — under a question asking
for the negative ones. "below zero" failed the same way, because the bound's
value had to be digits. "below 0" worked. Three ways of writing one condition,
one of which the product could read.

Every figure below is counted from the Parquet, not from the product.
"""

from __future__ import annotations

import glob

import pandas as pd
import pytest

from backend.orchestration import grain as gr
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
    assert not answered.unsupported, f"{question!r}: {answered.unsupported}"
    runtime = getattr(answered, "runtime", None)
    return list(getattr(runtime, "rows", None) or [])


class TestHowManyIsAnswerdWithANumber:
    def test_the_grain_of_a_count_is_the_count(self):
        want = gr.requested("How many customers are in Stage 2?")
        assert want.grain == gr.PORTFOLIO
        assert want.explicit
        assert want.source == "count"

    def test_a_count_with_a_breakdown_is_one_row_per_group(self):
        want = gr.requested("How many facilities are in each IFRS 9 stage?",
                            dimension="ifrs9_stage")
        assert want.grain == gr.SEGMENT
        assert want.dimension == "ifrs9_stage"

    def test_listing_the_same_population_is_still_a_list(self):
        want = gr.requested("Show me the customers in Stage 2.")
        assert want.grain == gr.CUSTOMER

    def test_customers_in_a_stage_are_counted(self, book):
        got = rows(f"How many customers are in Stage 2 at {LATEST}?")
        assert len(got) == 1, "a count came back as a list of what it counts"
        assert int(got[0]["customer_count"]) == int(
            book[book.ifrs9_stage == 2].customer_id.nunique())

    def test_facilities_over_a_threshold_are_counted(self, book):
        got = rows(f"How many facilities have days past due above 30 at "
                   f"{LATEST}?")
        assert len(got) == 1
        assert int(got[0]["facility_count"]) == int(
            book[book.dpd > 30].facility_id.nunique())

    def test_a_count_by_a_dimension_is_one_row_per_group(self, book):
        got = rows(f"How many facilities are in each IFRS 9 stage at "
                   f"{LATEST}?")
        counted = {int(r["ifrs9_stage"]): int(r["facility_count"])
                   for r in got}
        want = {int(k): int(v) for k, v in
                book.groupby("ifrs9_stage").facility_id.nunique().items()}
        assert counted == want


class TestASignIsABound:
    @pytest.mark.parametrize("said,op,value", [
        ("disposable income below zero", "lt", 0.0),
        ("disposable income below nil", "lt", 0.0),
        ("negative disposable income", "lt", 0.0),
        ("positive disposable income", "gt", 0.0),
        ("disposable income is negative", "lt", 0.0),
        ("disposable income below 0", "lt", 0.0),
        ("days past due above 30", "gt", 30.0),
    ])
    def test_every_way_of_writing_it_is_read(self, said, op, value):
        found = sm.find_threshold(said)
        assert found is not None, f"no bound read from {said!r}"
        assert (found.op, found.value) == (op, value)

    def test_a_sentence_with_a_number_keeps_the_number(self):
        """A sign must never displace a bound the sentence wrote down."""
        found = sm.find_threshold("negative disposable income below -500")
        assert found is not None
        assert (found.op, found.value) == ("lt", -500.0)

    def test_a_sentence_with_no_bound_states_none(self):
        assert sm.find_threshold("expected credit loss by product") is None

    @pytest.mark.parametrize("question", [
        "How many customers have negative disposable income at 2026-08?",
        "How many customers have disposable income below zero at 2026-08?",
        "How many customers have disposable income below 0 at 2026-08?",
    ])
    def test_all_three_phrasings_count_the_same_customers(self, book,
                                                          question):
        got = rows(question)
        assert len(got) == 1
        assert int(got[0]["customer_count"]) == int(
            book[book.disposable_income_sar < 0].customer_id.nunique())

    def test_the_listed_customers_are_the_negative_ones(self):
        got = rows(f"Which customers have a negative affordability buffer at "
                   f"{LATEST}?")
        assert got, "no rows came back"
        assert all(float(r["disposable_income_sar"]) < 0 for r in got), (
            "the answer listed the HIGHEST POSITIVE values under a question "
            "asking for the negative ones")
