"""Part 12. The rows that come back are the rows that should come back.

The existing fidelity and multi-condition suites prove the PLAN carries every
condition the question asked for. That is necessary and it is not sufficient: a
plan can be faithful, compile, run, and return the wrong borrowers — or none —
and nothing inside the system looks like a failure.

So this file does the one thing those suites do not. It runs each question
through the real path, executes the plan against the real book, and then
recomputes the answer INDEPENDENTLY from the parquet with pandas: a second
implementation, written from the question rather than from the plan. Where the
two disagree, one of them is wrong, and the test says which borrowers.

The empty answer that is not a finding
--------------------------------------
    "Which borrowers had a PD increase and were downgraded in Q2 2026?"

returns nothing. Every condition reached the FILTER; the query succeeded. But
`customer_ratings` is annual and its latest completed cycle is 2025, so Q1 2026
and Q2 2026 both read that same cycle — the internal grade is the same row on
both sides and the difference is identically zero for every borrower on the
book. The empty result is a fact about the calendar. A reader who takes it as
"nothing on this book was downgraded while its PD rose" has been misled by a
correct query, which is the worst kind.
"""

from __future__ import annotations

import glob
from typing import Any

import pandas as pd
import pytest

from backend.orchestration import analysis_planner as ap
from backend.orchestration import collapse, ordinal, router
from backend.orchestration import context as gc
from backend.runtime import executor as rx

LATEST = "Q2 2026"
PRIOR = "Q1 2026"


# ---------------------------------------------------- the independent reader
#
# Deliberately pandas over the parquet rather than the product's own catalogue
# or its DuckDB compiler. A second implementation that shares the first one's
# machinery agrees with it about the things the machinery gets wrong.


def _read(dataset: str) -> pd.DataFrame:
    files = sorted(glob.glob(f"data/**/{dataset}/**/*.parquet", recursive=True))
    if not files:
        pytest.skip(f"{dataset} is not published in this deployment")
    frames = []
    for path in files:
        frame = pd.read_parquet(path)
        if "period" not in frame.columns:
            # Hive-partitioned by period: the value is in the path.
            part = [p for p in path.split("/") if p.startswith("period=")]
            if part:
                frame["period"] = part[0].split("=", 1)[1]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def facilities() -> pd.DataFrame:
    return _read("portfolio_facility")


@pytest.fixture(scope="module")
def staging() -> pd.DataFrame:
    return _read("ifrs9_staging")


@pytest.fixture(scope="module")
def ratings() -> pd.DataFrame:
    return _read("customer_ratings")


def _customer_pd(facilities: pd.DataFrame, staging: pd.DataFrame,
                 period: str) -> pd.Series:
    """The worst 12-month PD per customer at one reporting date.

    `max`, because that is the roll-up the plan uses when it reconciles the
    facility grain to the customer grain, and a comparison against a different
    roll-up would be a comparison of two different questions.
    """
    book = facilities.loc[facilities["period"].astype(str) == period,
                          ["account_id", "customer_id"]]
    stage = staging.loc[staging["period"].astype(str) == period,
                        ["account_id", "pd_12m_pct"]]
    # Only the columns the comparison needs. Both datasets publish `sector`,
    # `segment` and `ead`, and a merge that carries them suffixes the
    # collisions, which is how the read silently loses the column it came for.
    joined = book.merge(stage, on="account_id", how="inner")
    return joined.groupby("customer_id")["pd_12m_pct"].max()


def _ran(question: str) -> tuple[Any, Any]:
    """The plan and the result, through the real path."""
    build = ap.plan(router.read(question).reading, gc.retrieve(question),
                    question=question)
    return build, rx.execute(build.plan)


def _names(result: Any) -> list[str]:
    """The result's column names, whether it publishes strings or descriptors."""
    out = []
    for column in result.columns or []:
        if isinstance(column, dict):
            out.append(str(column.get("name") or column.get("column") or ""))
        else:
            out.append(str(column))
    return [name for name in out if name]


def _where(plan: Any) -> list[dict[str, Any]]:
    """Every predicate the plan's FILTER steps actually apply."""
    out: list[dict[str, Any]] = []
    for op in plan.get("operations") or []:
        if op.get("op") == "FILTER":
            out.extend(op.get("params", {}).get("where") or [])
    return out


def _returned(result: Any) -> set[str]:
    return {str(row.get("customer_id")) for row in (result.rows or [])
            if row.get("customer_id") is not None}


# ==========================================================================
# The comparison that cannot come out non-zero
# ==========================================================================


class TestACollapsedComparisonIsSaidRatherThanReturnedEmpty:

    QUESTION = "Which borrowers had a PD increase and were downgraded in Q2 2026?"

    @pytest.fixture(scope="class")
    @classmethod
    def ran(cls):
        return _ran(cls.QUESTION)

    def test_the_data_really_does_collapse(self, ratings) -> None:
        # The premise, verified independently. If the ratings cycle ever
        # becomes quarterly this test fails first and tells the next reader
        # that the whole section below is about a condition that no longer
        # holds.
        cycles = sorted(str(p) for p in ratings["period"].unique())
        assert all(len(c) == 4 and c.isdigit() for c in cycles), (
            f"customer_ratings is no longer annual: {cycles[:5]}")
        assert "2026" not in cycles, (
            "the 2026 rating cycle now exists, so a Q2 2026 question no "
            "longer has to read 2025 on both sides")

    def test_the_plan_still_carries_both_conditions(self, ran) -> None:
        # The collapse is not an excuse to drop the condition: it is carried,
        # tested, and reported as untestable.
        build, _result = ran
        fields = {c.field for c in build.conditions}
        assert "pd_12m_pct" in fields
        assert "internal_grade" in fields

    def test_the_plan_declares_the_collapse(self, ran) -> None:
        build, _result = ran
        assert build.collapsed is not None and build.collapsed.any, (
            "the plan compares two quarters that read the same annual rating "
            "cycle and does not say so")
        assert any("customer_ratings" == entry.dataset
                   for entry in build.collapsed.collapsed)

    def test_the_reason_reaches_the_warnings(self, ran) -> None:
        build, _result = ran
        said = " ".join(build.warnings).lower()
        assert "2025 cycle" in said
        assert "cannot be tested" in said

    def test_it_names_the_field_that_does_record_the_movement(self,
                                                              ran) -> None:
        # Saying "I cannot" and stopping is honest and useless. The rating
        # cycle records the movement itself.
        build, _result = ran
        assert any(entry.instead for entry in build.collapsed.collapsed)

    def test_the_result_is_empty_for_the_reason_given(self, ran,
                                                      ratings) -> None:
        # Independently: across the 2025 cycle read on both sides, no borrower
        # has a different internal grade from itself.
        _build, result = ran
        assert _returned(result) == set()
        cycle = ratings[ratings["period"].astype(str) == "2025"]
        assert cycle["customer_id"].is_unique, (
            "one customer has two rows in the 2025 cycle, so the two sides of "
            "the comparison are not guaranteed to be the same row")


# ==========================================================================
# A movement that CAN be measured: verified borrower by borrower
# ==========================================================================


class TestASingleConditionReturnsExactlyTheRightBorrowers:

    QUESTION = "Which borrowers had a PD increase in Q2 2026?"

    @pytest.fixture(scope="class")
    @classmethod
    def ran(cls):
        return _ran(cls.QUESTION)

    @pytest.fixture(scope="class")
    @classmethod
    def expected(cls, facilities, staging) -> set[str]:
        opening = _customer_pd(facilities, staging, PRIOR)
        closing = _customer_pd(facilities, staging, LATEST)
        both = pd.concat([opening.rename("was"), closing.rename("now")],
                         axis=1, join="inner")
        return set(both.index[both["now"] - both["was"] > 0].astype(str))

    def test_the_plan_does_not_collapse(self, ran) -> None:
        build, _result = ran
        assert not (build.collapsed and build.collapsed.any)

    def test_something_came_back(self, ran) -> None:
        _build, result = ran
        assert _returned(result), (
            "no borrower's PD rose on a book where the independent read says "
            "several hundred did")

    def test_every_borrower_returned_really_had_a_pd_increase(
            self, ran, expected) -> None:
        _build, result = ran
        wrong = sorted(_returned(result) - expected)[:10]
        assert not wrong, (
            f"{len(wrong)} borrowers came back whose PD did not rise between "
            f"{PRIOR} and {LATEST}: {wrong}")

    def test_no_borrower_who_qualified_was_left_out(self, ran,
                                                    expected) -> None:
        _build, result = ran
        returned = _returned(result)
        # The plan limits the rows it returns. A borrower missing from a
        # LIMITED result is not a defect; a borrower missing from an unlimited
        # one is. Compare only when everything fits.
        if result.truncated or len(returned) >= 500:
            pytest.skip("the result is limited, so absence proves nothing")
        missing = sorted(expected - returned)[:10]
        assert not missing, (
            f"{len(missing)} borrowers whose PD rose did not come back: "
            f"{missing}")

    def test_the_rows_carry_the_evidence_for_the_claim(self, ran) -> None:
        # A reader has to be able to check a row without leaving the screen.
        _build, result = ran
        rows = result.rows or []
        assert rows
        changes = [name for name in _names(result)
                   if "pd_12m_pct" in name and "change" in name]
        assert changes, f"no column proves the PD movement: {_names(result)}"
        for row in rows[:25]:
            value = row.get(changes[0])
            assert value is not None and float(value) > 0, (
                f"a row claims a PD increase and shows {value!r}")


# ==========================================================================
# Two conditions that CAN both be measured
# ==========================================================================


class TestEveryConditionIsAppliedToEveryRowReturned:

    QUESTION = ("Which borrowers had a PD increase and are booked at "
                "stage 2 or worse in Q2 2026?")

    @pytest.fixture(scope="class")
    @classmethod
    def ran(cls):
        return _ran(cls.QUESTION)

    def test_both_conditions_reach_the_filter(self, ran) -> None:
        build, _result = ran
        columns = {str(p.get("column") or "") for p in _where(build.plan)}
        joined = " ".join(columns).lower()
        assert "pd_12m_pct" in joined, f"the PD condition was lost: {columns}"
        assert "stage" in joined, f"the stage condition was lost: {columns}"

    def test_or_worse_is_a_range_and_not_an_equality(self, ran) -> None:
        # The defect this question exists to catch. `= 2` excluded the stage 3
        # borrowers the question was reaching for from a population that
        # claimed to include them.
        build, _result = ran
        stage = [p for p in _where(build.plan)
                 if "stage" in str(p.get("column") or "").lower()]
        assert stage, "no stage predicate at all"
        assert stage[0].get("op") in {">=", "gte"}, (
            f"'stage 2 or worse' compiled to {stage[0].get('op')!r} 2, which "
            "excludes stage 3")

    def test_it_returns_more_than_the_equality_would(self, ran) -> None:
        # Quantified rather than asserted: the widened population must
        # actually contain the borrowers the narrow one dropped.
        _build, result = ran
        narrow = _ran("Which borrowers had a PD increase and are booked at "
                      "stage 2 in Q2 2026?")[1]
        # The row COUNT, not the returned rows: both results are capped, and
        # comparing two truncated pages compares the cap rather than the
        # population.
        assert result.row_count > narrow.row_count, (
            f"'stage 2 or worse' found {result.row_count} borrowers and "
            f"'stage 2' found {narrow.row_count}; the qualifier changed "
            "nothing, so the stage 3 names are still being excluded")

    def test_every_row_returned_satisfies_both(self, ran, facilities,
                                               staging) -> None:
        _build, result = ran
        returned = _returned(result)
        if not returned:
            pytest.skip("nothing came back; the emptiness test covers that")

        opening = _customer_pd(facilities, staging, PRIOR)
        closing = _customer_pd(facilities, staging, LATEST)
        book = staging[staging["period"].astype(str) == LATEST]
        worst_stage = book.groupby("customer_id")["ifrs9_stage"].max()

        for customer in sorted(returned)[:50]:
            assert customer in closing.index and customer in opening.index, (
                f"{customer} is not on book at both dates")
            assert closing[customer] - opening[customer] > 0, (
                f"{customer} came back and its PD did not rise")
            assert float(worst_stage.get(customer, 0)) >= 2, (
                f"{customer} came back at stage "
                f"{worst_stage.get(customer)!r}")


# ==========================================================================
# The detector itself
# ==========================================================================


class TestTheCollapseDetector:

    def test_it_maps_a_quarter_onto_the_completed_cycle(self) -> None:
        assert collapse._aligned("Q2 2026", "completed_year_of_quarter") == "2025"
        assert collapse._aligned("Q4 2026", "completed_year_of_quarter") == "2025"
        assert collapse._aligned("Q2 2026", "year_of_quarter") == "2026"

    def test_two_quarters_in_one_year_collapse_under_the_completed_rule(
            self) -> None:
        rule = "completed_year_of_quarter"
        assert (collapse._aligned("Q1 2026", rule)
                == collapse._aligned("Q4 2026", rule))

    def test_two_quarters_across_a_year_boundary_do_not(self) -> None:
        rule = "completed_year_of_quarter"
        assert (collapse._aligned("Q4 2025", rule)
                != collapse._aligned("Q1 2026", rule))

    def test_a_plan_with_no_asof_join_collapses_nothing(self) -> None:
        found = collapse.inspect({"id": "x", "operations": [
            {"id": "a", "op": "SCAN",
             "params": {"dataset": "portfolio_facility", "period": "Q2 2026"}}]})
        assert not found.any
        assert found.sentence() == ""

    def test_a_finding_says_which_column_it_is_about(self) -> None:
        entry = collapse.Collapsed(
            column="customer_ratings_internal_grade_change",
            dataset="customer_ratings", opening="Q1 2026", closing="Q2 2026",
            cycle="2025", instead="notches_moved")
        said = entry.says
        assert "Q1 2026" in said and "Q2 2026" in said and "2025" in said
        assert "notches_moved" in said
        assert said.endswith(".")

    def test_it_reads_the_periods_from_the_plan_not_the_request(self) -> None:
        # The plan is what ran. A period the request carried and the plan
        # ignored would make this check answer about the wrong dates.
        opening, closing = collapse._movement_periods({"operations": [
            {"id": "opening_base", "op": "SCAN", "params": {"period": "Q3 2025"}},
            {"id": "closing_base", "op": "SCAN", "params": {"period": "Q1 2026"}},
        ]})
        assert (opening, closing) == ("Q3 2025", "Q1 2026")


# ==========================================================================
# The ordinal qualifier
# ==========================================================================


class TestTheOrdinalQualifier:
    """"worse" is not a direction until you know which way the scale runs."""

    def test_higher_is_worse_on_a_stage(self) -> None:
        found = ordinal.read("borrowers at stage 2 or worse", "ifrs9_stage", "2")
        assert found is not None and found.op == "gte"

    def test_higher_is_better_on_interest_cover(self) -> None:
        found = ordinal.read("interest cover of 2 or worse", "interest_coverage",
                             "2")
        assert found is not None and found.op == "lte", (
            "more interest cover is better, so 'or worse' means below it")

    def test_better_reverses_on_each_measure(self) -> None:
        stage = ordinal.read("stage 2 or better", "ifrs9_stage", "2")
        cover = ordinal.read("interest cover 2 or better", "interest_coverage",
                             "2")
        assert stage is not None and stage.op == "lte"
        assert cover is not None and cover.op == "gte"

    def test_a_directional_word_needs_no_scale(self) -> None:
        assert ordinal.read("stage 2 or above", "ifrs9_stage", "2").op == "gte"
        assert ordinal.read("stage 2 or below", "ifrs9_stage", "2").op == "lte"

    def test_a_plain_value_is_left_alone(self) -> None:
        assert ordinal.read("borrowers at stage 2", "ifrs9_stage", "2") is None

    def test_an_ungoverned_direction_produces_nothing(self) -> None:
        # A scale whose direction is not written down here is not guessed at.
        assert "sector" not in ordinal.DIRECTION
        assert ordinal.read("sector 2 or worse", "sector", "2") is None

    def test_a_qualifier_far_from_the_value_is_not_about_it(self) -> None:
        # "stage 2" and an "or worse" belonging to a later clause.
        said = ("borrowers at stage 2 whose collateral coverage has fallen, "
                "or worse")
        assert ordinal.read(said, "ifrs9_stage", "2") is None

    def test_it_quotes_the_words_that_widened_it(self) -> None:
        found = ordinal.read("booked at stage 2 or worse", "ifrs9_stage", "2")
        assert found is not None
        assert "2 or worse" in found.phrase
        assert "at or above 2" in found.says

    def test_the_operator_is_never_equality(self) -> None:
        # A qualifier that resolved to equality is a qualifier that was not
        # there, and returning one would put the defect back silently.
        for said in ("stage 2 or worse", "stage 2 or better",
                     "stage 2 or above", "stage 2 or below"):
            found = ordinal.read(said, "ifrs9_stage", "2")
            assert found is not None and found.op in {"gte", "lte"}
