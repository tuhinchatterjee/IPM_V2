"""
The book's economics, asserted where they can regress.

`scripts/whatif_economic_validation.py` is the full review — fourteen sections,
forty-four checks, a written report. This file is the part of it that has to
FAIL A BUILD rather than appear in a document: the handful of properties that,
if they slipped, would make every figure in the product quietly wrong while
every schema check, range check and reconciliation still passed.

Three of them were genuinely broken and are locked here because of it. A rating
that is re-derived from a score each quarter, a Stage 2 population that cures
on noise, and an ML methodology that ignores exposure are not things a
reconciliation can see.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.corporate.universe import RATING_SCALE
from backend.ifrs9 import policy
from backend.whatif import domain as dm

GRADE_INDEX = {g: i for i, g in enumerate(RATING_SCALE)}
PERFORMING = [g for g in RATING_SCALE if g != "D"]


def _lake() -> bool:
    try:
        return bool(dm.periods())
    except Exception:
        return False


needs_lake = pytest.mark.skipif(
    not _lake(), reason="the Corporate IFRS 9 lake has not been built")


@pytest.fixture(scope="module")
def books() -> dict[str, pd.DataFrame]:
    return {p: dm.book(p)[0] for p in dm.periods()}


@pytest.fixture(scope="module")
def paired(books) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Consecutive quarters, joined on the borrowers present in both."""
    periods = list(books)
    out = []
    for a, b in zip(periods, periods[1:], strict=False):
        A = books[a].set_index("borrower_id")
        B = books[b].set_index("borrower_id")
        both = A.index.intersection(B.index)
        out.append((A.loc[both], B.loc[both]))
    return out


@needs_lake
class TestTheRatingIsARating:
    """A grade read straight off a score each quarter moved the average name
    1.31 notches a quarter and left a quarter of the book on its opening
    grade. Nothing in a schema or a reconciliation can see that."""

    def test_most_borrowers_hold_their_grade_from_quarter_to_quarter(
            self, paired) -> None:
        held = []
        for before, after in paired:
            same = (before["internal_rating"] == after["internal_rating"])
            held.append(float(same.mean()))
        average = float(np.mean(held)) * 100
        assert average >= 80.0, (
            f"only {average:.1f}% of borrowers hold their grade quarter to "
            "quarter; a rating that changes for most of the book every "
            "quarter is a re-binned score")

    def test_the_typical_borrower_does_not_move_at_all(self, paired) -> None:
        moves = pd.concat([
            (after["internal_rating"].map(GRADE_INDEX)
             - before["internal_rating"].map(GRADE_INDEX)).abs()
            for before, after in paired])
        assert float(moves.median()) == 0.0
        assert float(moves.mean()) < 0.75, (
            f"the average borrower moves {moves.mean():.2f} notches a quarter")

    def test_a_multi_notch_fall_is_a_credit_event_not_a_quarter(
            self, paired) -> None:
        big = []
        for before, after in paired:
            alive = before["internal_rating"] != "D"
            move = (after.loc[alive, "internal_rating"].map(GRADE_INDEX)
                    - before.loc[alive, "internal_rating"].map(GRADE_INDEX))
            big.append(float((move >= 3).mean()))
        assert float(np.mean(big)) * 100 <= 3.0

    def test_the_top_of_the_scale_is_not_downgraded_every_quarter(
            self, books) -> None:
        """The boundary artefact of an unsmoothed assignment: the top of the
        scale has nowhere to be upgraded to, so noise can only push it down.

        The strongest BAND rather than the single strongest grade, because a
        book that carries a handful of AAA names cannot answer the question
        either way — and a test that skips on a thin grade is a test that
        stops watching the thing it was written for.
        """
        band = set(PERFORMING[:3])
        periods = list(books)
        stayed, seen = 0, 0
        for a, b in zip(periods, periods[1:], strict=False):
            A = books[a].set_index("borrower_id")
            B = books[b].set_index("borrower_id")
            both = A.index.intersection(B.index)
            top = A.loc[both, "internal_rating"].isin(band)
            seen += int(top.sum())
            stayed += int(B.loc[both, "internal_rating"][top].isin(band).sum())
        assert seen >= 100, f"only {seen} borrower-quarters in {sorted(band)}"
        assert stayed / seen > 0.5, (
            f"only {stayed / seen:.1%} of the strongest band stays in it")


@needs_lake
class TestStagingMeasuresCreditRatherThanNoise:
    def test_stage_2_does_not_cure_a_third_of_itself_every_quarter(
            self, paired) -> None:
        cures = []
        for before, after in paired:
            was = before["stage"] == 2
            base = float(before.loc[was, "ead"].sum())
            if base <= 0:
                continue
            back = before.loc[was & (after["stage"] == 1), "ead"].sum()
            cures.append(float(back) / base)
        average = float(np.mean(cures)) * 100
        assert average <= 25.0, (
            f"{average:.1f}% of Stage 2 exposure returns to Stage 1 each "
            "quarter, an average sojourn under four quarters")

    def test_provision_intensity_escalates_through_the_stages(
            self, books) -> None:
        for period, frame in books.items():
            rates = []
            for stage in (1, 2, 3):
                part = frame[frame["stage"] == stage]
                ead = float(part["ead"].sum())
                rates.append(float(part["final_ecl"].sum()) / ead
                             if ead else 0.0)
            assert rates[0] < rates[1] < rates[2], f"{period}: {rates}"

    def test_stage_3_is_exactly_the_defaulted_population(self, books) -> None:
        for period, frame in books.items():
            impaired = frame[frame["stage"] == 3]
            assert bool(impaired["default_flag"].all()), period
            assert set(impaired["internal_rating"]) <= {"D"}, period
            triggered = frame[
                (frame["current_dpd"] >= policy.DEFAULT_DPD_DAYS)
                | frame["default_flag"].astype(bool)]
            assert bool((triggered["stage"] == 3).all()), period


@needs_lake
class TestTheThreePdsAreThreeDifferentThings:
    def test_ttc_is_a_property_of_the_grade_and_nothing_else(
            self, books) -> None:
        seen: dict[str, set[float]] = {}
        for frame in books.values():
            for grade, values in frame.groupby("internal_rating")["ttc_pd_pct"]:
                seen.setdefault(grade, set()).update(
                    round(float(v), 6) for v in values)
        moving = {g: v for g, v in seen.items() if len(v) > 1}
        assert not moving, f"TTC moves within a grade: {sorted(moving)}"

    def test_ttc_rises_strictly_through_the_scale(self, books) -> None:
        latest = list(books.values())[-1]
        levels = (latest.groupby("internal_rating")["ttc_pd_pct"].first()
                  .reindex([g for g in RATING_SCALE
                            if g in set(latest["internal_rating"])]))
        assert levels.is_monotonic_increasing, levels.to_dict()

    def test_lifetime_is_never_below_the_twelve_month(self, books) -> None:
        for period, frame in books.items():
            assert not (frame["pd_lifetime"]
                        < frame["pd_12m"] - 1e-9).any(), period

    def test_the_point_in_time_pd_follows_the_cycle(self, books) -> None:
        macro = dm.macro().set_index("period")["credit_cycle_factor"]
        pit, cycle = [], []
        for period, frame in books.items():
            e = frame["ead"]
            pit.append(float((frame["pit_pd_12m_pct"] * e).sum() / e.sum()))
            cycle.append(float(macro.get(period, np.nan)))
        correlation = pd.Series(pit).rank().corr(pd.Series(cycle).rank())
        assert correlation <= -0.5, (
            f"the point-in-time PD tracks the cycle at {correlation:.3f}")


@needs_lake
class TestLossGivenDefaultFollowsTheSecurity:
    def test_lgd_falls_as_collateral_rises(self, books) -> None:
        latest = list(books.values())[-1]
        correlation = latest["lgd"].rank().corr(
            latest["collateral_coverage_pct"].rank())
        assert correlation <= -0.5, correlation

    def test_no_impossible_collateral_position(self, books) -> None:
        for period, frame in books.items():
            assert not (frame["secured_exposure"]
                        > frame["ead"] + 1e-6).any(), period
            assert not (frame["unsecured_exposure"] < -1e-9).any(), period
            assert not (frame["collateral_eligible_value"]
                        > frame["collateral_market_value"] + 1e-6).any(), period


@needs_lake
class TestTheMlMethodologyPricesExposure:
    """The model's target is a RATE, so a ratio of two predictions is a ratio
    of two rates and the exposure leg has to be multiplied in separately.
    Without it, "raise EAD by 20%" was priced at a twentieth of its effect."""

    def test_an_exposure_shock_reaches_the_ml_answer(self) -> None:
        from backend.whatif import methodology as me
        from backend.whatif import run as rn
        from backend.whatif import scenarios as sc
        from backend.whatif import steps as sp
        from backend.whatif.ml import registry as rg

        if not rg.active_version():
            pytest.skip("no ML model has been activated")
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.EAD, (sc.Shock(sc.EAD, 20.0, sc.RELATIVE),),
                    interpreted="EAD +20%"))
        delta = rn.execute(state, requested=me.DELTA, plausible=False)
        modelled = rn.execute(state, requested=me.ML, plausible=False)
        a = float(delta.summary["incremental_ecl"])
        b = float(modelled.summary["incremental_ecl"])
        assert a > 0 and b > 0
        assert 0.4 <= b / a <= 2.5, (
            f"the ML model priced an exposure shock at {b / a:.2f}x the "
            "Delta answer; a rate ratio alone does not carry exposure")
