"""Borrower 360 opens on the book, ranked. §18, §11.

The screen opened on a search box. A product that will not show you a
borrower until you can name one assumes you already know which borrower is
the problem — and the names worth knowing are exactly the ones a ranking
would have put at the top.

Two properties, and the second is the one that makes the first usable:

  * with no facet and no name, the cohort IS the whole book at the latest
    period, ordered by 12-month PD, highest first; and
  * the ordering is total. Two borrowers on the same PD are separated by the
    borrower id, so the tenth row is the same tenth row on a second visit
    (§11). An ordering with ties left open is a ranking screen that shows a
    different name each time somebody reloads it.

The presets are ORDERINGS over governed fields. §18 is explicit that they must
not become opaque scores: "liquidity pressure" sorts by single-name limit
utilisation and says so, because a number a bank cannot explain to its
regulator is worse than no number.
"""

from __future__ import annotations

import pytest

from backend.corporate import search as search_mod

service = pytest.importorskip("backend.corporate.service")


def _cohort(**kwargs):
    try:
        return service.filter_cohort(**kwargs)
    except service.DataNotBuilt as e:
        pytest.skip(f"no corporate book here: {e}")


class TestTheDefaultIsARanking:

    def test_an_empty_query_returns_the_book(self):
        found = _cohort(limit=25)
        assert found["matched"] > 100
        assert len(found["borrowers"]) == 25

    def test_it_is_ordered_by_twelve_month_pd_highest_first(self):
        found = _cohort(limit=25)
        assert found["ordered_by"] == "pd_12m"
        assert found["ordered_descending"] is True
        assert found["order_label"] == "12-month probability of default"

        values = [row["pd_12m"] for row in found["borrowers"]
                  if row.get("pd_12m") is not None]
        assert values == sorted(values, reverse=True)

    def test_it_is_at_one_reporting_period(self):
        """Sixteen quarters of the same borrower is not a ranking of
        borrowers."""
        found = _cohort(limit=50)
        ids = [row["borrower_id"] for row in found["borrowers"]]
        assert len(ids) == len(set(ids))

    def test_the_row_carries_what_a_credit_officer_scans_for(self):
        found = _cohort(limit=1)
        row = found["borrowers"][0]
        for column in ("borrower_id", "sector", "internal_rating", "stage",
                       "pd_12m", "ifrs9_ead", "final_ecl", "watchlist_flag"):
            assert column in row, column


class TestTheOrderingIsTotal:

    def test_the_same_request_twice_returns_the_same_rows(self):
        first = _cohort(limit=40)
        second = _cohort(limit=40)
        assert ([r["borrower_id"] for r in first["borrowers"]]
                == [r["borrower_id"] for r in second["borrowers"]])

    def test_ties_are_broken_by_the_borrower_id(self):
        """Stage is a small ordinal, so ordering by it produces many ties —
        which is the case a tie-break exists for."""
        found = _cohort(order_by="stage", limit=60)
        rows = [(r.get("stage"), r["borrower_id"]) for r in found["borrowers"]]
        for (stage, one), (next_stage, two) in zip(rows, rows[1:], strict=False):
            if stage == next_stage:
                assert one < two, f"{one} came before {two} on the same stage"

    def test_a_borrower_with_no_value_does_not_lead_the_ranking(self):
        """A missing PD is not the highest PD. Nulls last, always."""
        found = _cohort(order_by="collateral_shortfall", limit=30)
        values = [r.get("collateral_shortfall") for r in found["borrowers"]]
        seen_null = False
        for value in values:
            if value is None:
                seen_null = True
            elif seen_null:
                pytest.fail("a null sorted above a real value")


class TestThePresets:

    @pytest.mark.parametrize("field", [
        "pd_12m", "ifrs9_ead", "final_ecl", "current_dpd",
        "single_name_utilisation_pct", "average_headroom_pct",
        "collateral_coverage_pct",
    ])
    def test_every_preset_orders_by_a_governed_field(self, field):
        assert field in search_mod.ORDERABLE
        found = _cohort(order_by=field, limit=5)
        assert found["ordered_by"] == field

    def test_a_field_where_low_is_worse_sorts_the_right_way_round(self):
        """Covenant headroom. "Covenant pressure" means the LEAST headroom,
        and a preset that had to be told so every time would eventually not
        be."""
        found = _cohort(order_by="average_headroom_pct", limit=10)
        assert found["ordered_descending"] is False
        values = [r["average_headroom_pct"] for r in found["borrowers"]
                  if r.get("average_headroom_pct") is not None]
        assert values == sorted(values)

    def test_the_direction_can_still_be_overridden(self):
        found = _cohort(order_by="average_headroom_pct", descending=True,
                        limit=10)
        assert found["ordered_descending"] is True

    def test_an_ungoverned_ordering_is_refused_by_name(self):
        """`betweenness` is real, numeric, and ranking a credit book by it
        would be nonsense on a screen."""
        with pytest.raises(search_mod.UnknownOrderError) as caught:
            _cohort(order_by="betweenness")
        assert "betweenness" in str(caught.value)

    def test_no_preset_invents_a_score(self):
        """§18: "Do not create fake opaque risk scores merely for this table."

        Every orderable field is a column the catalogue publishes and the
        dictionary defines. If this ever fails it is because somebody added a
        composite with no owner.
        """
        from backend.data_access.catalog import get_catalog

        published = set(get_catalog().dataset("corporate_borrower_360").fields)
        unknown = set(search_mod.ORDERABLE) - published
        assert not unknown, f"orderings with no governed field: {unknown}"


class TestANameLookupIsNotReordered:
    """The counter-test. Re-sorting a name search by exposure buries the
    borrower whose name was typed."""

    def test_a_text_search_keeps_its_match_order(self):
        try:
            found = service.find("Al", None, limit=10)
        except service.DataNotBuilt as e:
            pytest.skip(str(e))
        assert not found.get("ordered_by")
