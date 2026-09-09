"""
The reconciliation report is an invariant, not a document.

`scripts/whatif_reconciliation_report.py` answers the three questions a credit
professional asks before trusting a screen: does every partition of the book
add back to it, is every governed grade represented and ordered, and can a
single borrower's provision be checked with a calculator across the quarters it
was on book.

Running it in the suite means a change that breaks one of those is found by the
build rather than by somebody reading the report and noticing.
"""

from __future__ import annotations

import pytest

from backend.whatif import domain as dm


def _lake() -> bool:
    try:
        return bool(dm.periods())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _lake(), reason="the Corporate IFRS 9 lake has not been built")


@pytest.fixture(scope="module")
def report():
    from scripts.whatif_reconciliation_report import build

    return build()


class TestThePortfolioReconciles:
    def test_it_covers_every_quarter(self, report) -> None:
        assert report["portfolio_reconciliation"]["period_count"] == 16

    def test_every_partition_adds_back_to_the_whole(self, report) -> None:
        recon = report["portfolio_reconciliation"]
        broken = [q["period"] for q in recon["quarters"] if not q["reconciles"]]
        assert not broken, f"these quarters do not reconcile: {broken}"

    def test_it_partitions_by_the_four_cuts_a_reader_asks_for(self, report) -> None:
        first = report["portfolio_reconciliation"]["quarters"][0]
        assert set(first["partitions"]) == {"stage", "sector", "segment",
                                            "internal_rating"}
        for name, body in first["partitions"].items():
            assert body["available"], name

    def test_coverage_stays_in_a_range_a_bank_would_report(self, report) -> None:
        coverage = [q["coverage_pct"]
                    for q in report["portfolio_reconciliation"]["quarters"]]
        assert min(coverage) > 0.5
        assert max(coverage) < 20.0


class TestTheRatingDistribution:
    def test_every_governed_grade_appears(self, report) -> None:
        """Nineteen performing grades, then default as its own row.

        The scale is the nineteen; the twentieth row is the state a borrower
        reaches by the default event, and it is there so the total ties to the
        book rather than to the performing part of it.
        """
        dist = report["rating_distribution"]
        assert dist["grades"] == 19
        assert len(dist["rows"]) == 20
        assert [r["grade"] for r in dist["rows"]][:19] == [
            "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
            "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C"]
        assert dist["rows"][19]["grade"] == "D"
        assert dist["rows"][19]["performing"] is False

    def test_the_through_the_cycle_scale_is_ordered(self, report) -> None:
        assert report["rating_distribution"]["monotone_ttc"]

    def test_the_rows_add_up_to_the_total(self, report) -> None:
        assert report["rating_distribution"]["reconciles"]

    def test_a_worse_grade_carries_worse_coverage(self, report) -> None:
        """Not every adjacent pair — the strongest grades hold a handful of
        names — but the shape of the book has to be right end to end."""
        rows = [r for r in report["rating_distribution"]["rows"]
                if r["borrowers"] >= 50]
        assert len(rows) >= 12
        assert rows[0]["coverage_pct"] < rows[-1]["coverage_pct"] / 10


class TestTheSpotCheck:
    def test_it_follows_enough_borrowers_over_enough_quarters(self, report) -> None:
        spot = report["spot_check"]
        assert len(spot["borrowers"]) >= 10
        assert len(spot["quarters"]) >= 8

    def test_every_row_ties_to_the_arithmetic(self, report) -> None:
        """The provision is a product, and a reader has to be able to check it.

        `unexplained` is the reported figure minus the governed product minus
        the overlay. Anything material there is a number the book cannot
        justify.
        """
        spot = report["spot_check"]
        assert spot["all_tie"], (
            f"worst unexplained residual {spot['worst_unexplained']}")

    def test_the_sample_is_not_cherry_picked(self, report) -> None:
        """Stratified on a fixed seed, so the same names come back every run
        and a bad one cannot be quietly dropped."""
        from scripts.whatif_reconciliation_report import build

        assert build()["spot_check"]["borrowers"] == report["spot_check"]["borrowers"]

    def test_the_measurement_basis_follows_the_stage_on_every_row(self, report) -> None:
        for entries in report["spot_check"]["history"].values():
            for row in entries:
                if row["stage"] >= 3:
                    assert row["measurement_basis"] == "Defaulted - PD 100%"
                    assert row["pd_applicable"] == 100.0
                    continue
                expected = "12-month PD" if row["stage"] <= 1 else "Lifetime PD"
                assert row["measurement_basis"] == expected
                assert row["pd_applicable"] == (
                    row["pd_12m"] if row["stage"] <= 1 else row["pd_lifetime"])
