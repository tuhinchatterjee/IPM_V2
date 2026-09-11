"""
Stage migration — the question IFRS 9 is about, and the product could not
answer it.

    "How many facilities migrated from Stage 1 to Stage 2 between July and
     August 2026?"                                              →  1,392

1,392 is every facility in Stage 2 at August, whether it arrived that month
or had been there all year. The right answer is 279.

    "Which customers moved from Stage 1 to Stage 2 in August 2026?"

came back as two rows — one per reporting month — each carrying
`max(ifrs9_stage) = 2`. No customers, no movement, no migration.

    "Show the stage migration between July and August 2026."

came back "Which figure should CreditProbe measure?"

    "How many facilities improved from Stage 2 to Stage 1 in August 2026?"

was planned as `ifrs9_stage_change < -2` — arithmetic that no two-to-one move
satisfies — and returned nothing.

Four causes, each a reasonable decision made about a different book.

  * `_filters` reads a transition, keeps the destination, drops the origin and
    states a limitation, "because a single row cannot hold both endpoints of a
    movement". On THIS book it can: `retail_facility_month` carries
    `previous_month_stage` on every row, and it agrees with the previous
    month's `ifrs9_stage` on every row of the published lake.
  * "moved FROM Stage 1 TO Stage 2" was not masked as a migration — only
    "moved TO" was — so the change vocabulary claimed it and the question was
    planned as a two-period comparison.
  * The destination was taken as the LAST value the resolver returned, and the
    resolver returns them sorted. "from Stage 2 to Stage 1" therefore read as
    a move INTO Stage 2. It only ever looked right because "from 1 to 2" sorts
    the way it reads.
  * "deteriorated" and "improved" were not in the transition vocabulary at
    all, though they are the words a credit officer uses for exactly this.

Every figure below is the migration matrix counted from the Parquet.
"""

from __future__ import annotations

import glob

import pandas as pd
import pytest

from backend.orchestration import dimensions as dm
from backend.orchestration import movement as mv
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


def migrated(book: pd.DataFrame, origin: int, destination: int) -> int:
    return int(book[(book.previous_month_stage == origin)
                    & (book.ifrs9_stage == destination)].facility_id.nunique())


def rows(question: str) -> list[dict]:
    answered = orchestrator.answer(question)
    assert not answered.clarification, (
        f"{question!r} was refused: "
        f"{getattr(answered.clarification, 'question', answered.clarification)}")
    runtime = getattr(answered, "runtime", None)
    return list(getattr(runtime, "rows", None) or [])


class TestTheBookHoldsTheOrigin:
    def test_the_prior_column_is_declared(self):
        assert dm.prior()["ifrs9_stage"] == "previous_month_stage"

    def test_it_is_not_a_filterable_dimension(self):
        """Making it one let the resolver attach every bare stage number to it.

        "Stage 2 and Stage 3 exposure" then acquired a restriction on LAST
        month's stage that nobody had asked for.
        """
        assert "previous_month_stage" not in profile.RETAIL_DIMENSIONS

    def test_it_agrees_with_the_previous_month(self, book):
        earlier = pd.read_parquet(
            glob.glob("data/retail/analytics/retail_facility_month/"
                      "reporting_month=2026-07/*.parquet")[0],
            columns=["facility_id", "ifrs9_stage"])
        joined = book[["facility_id", "previous_month_stage"]].merge(
            earlier, on="facility_id")
        assert (joined.previous_month_stage == joined.ifrs9_stage).all(), (
            "the exact plan rests on this column being last month's stage")


class TestAMigrationIsNotAChange:
    @pytest.mark.parametrize("said", [
        "Which customers moved from Stage 1 to Stage 2 in August 2026?",
        "How many facilities improved from Stage 2 to Stage 1?",
        "Which facilities deteriorated from Stage 1 to Stage 2?",
        "Which names migrated from Stage 2 to Stage 3?",
    ])
    def test_a_movement_between_named_states_is_masked(self, said):
        assert not mv.asks_for_change(said)

    @pytest.mark.parametrize("said", [
        "ECL moved from 5,248 to 5,313",
        "How did ECL move from July to August 2026?",
        "Show the 25-month ECL trend",
    ])
    def test_a_movement_of_a_MEASURE_keeps_its_reading(self, said):
        assert mv.asks_for_change(said)


class TestTheMigrationIsCountedExactly:
    @pytest.mark.parametrize("question,origin,destination", [
        ("How many facilities migrated from Stage 1 to Stage 2 in 2026-08?",
         1, 2),
        ("How many facilities moved from Stage 2 to Stage 3 in 2026-08?",
         2, 3),
        ("How many facilities improved from Stage 2 to Stage 1 in 2026-08?",
         2, 1),
        ("How many facilities deteriorated from Stage 1 to Stage 3 in 2026-08?",
         1, 3),
    ])
    def test_every_direction(self, book, question, origin, destination):
        got = rows(question)
        assert len(got) == 1, "a count came back as a list"
        assert int(got[0]["facility_count"]) == migrated(book, origin,
                                                         destination)

    def test_the_direction_is_read_from_the_sentence(self, book):
        """"from 2 to 1" and "from 1 to 2" are different questions.

        They resolved to the same sorted pair, and the destination was taken
        as the last of them — so one of the two was answered backwards.
        """
        up = rows("How many facilities moved from Stage 1 to Stage 2 in "
                  "2026-08?")
        down = rows("How many facilities moved from Stage 2 to Stage 1 in "
                    "2026-08?")
        assert int(up[0]["facility_count"]) == migrated(book, 1, 2)
        assert int(down[0]["facility_count"]) == migrated(book, 2, 1)
        assert up[0]["facility_count"] != down[0]["facility_count"]

    def test_the_year_does_not_decide_the_destination(self):
        """A bare `rfind` for "2" matched the 2 in "August 2026"."""
        from backend.orchestration import analysis_planner as ap

        found = ap._destinations(
            "How many facilities improved from Stage 2 to Stage 1 in August "
            "2026?", {"ifrs9_stage": ["1", "2"]})
        assert found["ifrs9_stage"] == "1"

    def test_the_migrating_customers_are_listed(self, book):
        got = rows(f"Which customers moved from Stage 1 to Stage 2 in "
                   f"{LATEST}?")
        assert len(got) > 1, "a list of customers came back as a monthly total"
        assert all("customer_id" in r for r in got)
        assert all(int(r["ifrs9_stage"]) == 2 for r in got)
        assert all(int(r["previous_month_stage"]) == 1 for r in got)

    def test_the_migrating_exposure_is_the_book_s(self, book):
        got = rows(f"What exposure moved from Stage 2 to Stage 3 in {LATEST}?")
        assert len(got) == 1
        want = float(book[(book.previous_month_stage == 2)
                          & (book.ifrs9_stage == 3)]
                     .gross_carrying_amount_sar.sum())
        assert round(float(got[0]["gross_carrying_amount_sar"]), 2) == round(
            want, 2)


class TestASETOfStagesIsStillASet:
    def test_naming_two_stages_together_restricts_neither_month(self):
        """"Stage 2 and Stage 3 exposure" names a set, not a movement."""
        got = rows(f"Show exposure at default for Stage 2 and Stage 3 at "
                   f"{LATEST}.")
        assert got
        assert all("previous_month_stage" not in r for r in got), (
            "a set acquired a restriction on last month's stage")
        assert {int(r["ifrs9_stage"]) for r in got} <= {2, 3}
