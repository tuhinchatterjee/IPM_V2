"""Filtering the book, not the page -- and every measure agreeing about it.

The defects these hold
----------------------
The dashboard's tiles read the whole book, its band distribution read the
whole book, its trend read the whole book, and its table filtered the twenty
rows it happened to have fetched. A reader who narrowed to one segment saw a
segment table under portfolio tiles with nothing saying they were about
different populations. Every number was individually true; the screen was not.

And the filtering was done in the browser, so "exposure above five hundred
million" returned the matches among twenty rows rather than among three
hundred obligors -- a smaller, quieter, entirely wrong answer.

So: one spec, applied once, to the whole published month, and every measure a
projection of the result. These tests hold the arithmetic that makes that
claim checkable -- the distribution summing to the tile, the filtered table
summing to the filtered count -- rather than asserting figures that would
have to be rewritten the next time the data is rebuilt.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.early_warning import dashboard_view as dv
from backend.early_warning import filterspec as fsp
from backend.early_warning import v2_service as svc


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def book() -> pd.DataFrame:
    return svc.borrower_month()


def spec(**payload) -> fsp.FilterSpec:
    return fsp.FilterSpec.from_payload(payload)


# ------------------------------------------------------- what is refused


def test_a_filter_on_a_column_the_domain_does_not_have_is_refused():
    # Ignoring it would draw a chip for a filter that was never applied --
    # a right count for a population nobody asked for.
    with pytest.raises(fsp.InvalidFilter) as raised:
        spec(filters={"favourite_colour": ["blue"]})
    assert "favourite_colour" in str(raised.value)


def test_a_band_that_is_not_a_band_is_refused_and_the_bands_are_named():
    with pytest.raises(fsp.InvalidFilter) as raised:
        spec(filters={"ews_band": ["CATASTROPHIC"]})
    message = str(raised.value)
    assert "CATASTROPHIC" in message
    for band in fsp.BANDS:
        assert band in message


def test_an_impossible_range_is_refused_rather_than_returning_nothing():
    # min above max returns an empty table that looks like a finding.
    with pytest.raises(fsp.InvalidFilter):
        spec(filters={"exposure": {"min": 900, "max": 100}})


def test_a_sort_the_table_cannot_do_is_refused():
    with pytest.raises(fsp.InvalidFilter):
        spec(sort_by="whatever_i_like")


def test_a_page_larger_than_the_ceiling_is_clamped_not_honoured():
    assert spec(limit=10_000).limit == fsp.MAX_PAGE


def test_text_that_is_not_a_number_is_refused_as_a_range_bound():
    with pytest.raises(fsp.InvalidFilter):
        spec(filters={"dpd": {"min": "thirty"}})


# ------------------------------------------------- filtering the whole book


def test_a_filter_narrows_the_published_population_not_a_fetched_page(book):
    narrowed = spec(filters={"ews_band": ["HIGH", "VERY_HIGH"]}).apply(book)
    expected = book[book["ews_band"].isin(("HIGH", "VERY_HIGH"))]
    assert len(narrowed) == len(expected)
    # The point: the result is drawn from the whole month, not from a page.
    assert len(book) > fsp.DEFAULT_PAGE


def test_an_exposure_floor_keeps_exactly_the_obligors_above_it(book):
    floor = float(book["exposure"].median())
    narrowed = spec(filters={"exposure": {"min": floor}}).apply(book)
    assert (narrowed["exposure"] >= floor).all()
    assert len(narrowed) == int((book["exposure"] >= floor).sum())


def test_two_filters_are_an_and_not_an_or(book):
    both = spec(filters={"ews_band": ["HIGH"], "dpd": {"min": 1}}).apply(book)
    assert (both["ews_band"] == "HIGH").all()
    assert (both["dpd"] >= 1).all()
    assert len(both) <= len(spec(filters={"ews_band": ["HIGH"]}).apply(book))


def test_a_customer_search_matches_part_of_a_name_and_ignores_case(book):
    name = str(book["customer_name"].iloc[0])
    fragment = name[1:6]
    found = spec(filters={"customer": fragment.upper()}).apply(book)
    assert name in set(found["customer_name"])


def test_a_filter_matching_nothing_returns_nothing_rather_than_everything(book):
    empty = spec(filters={"dpd": {"min": 10_000_000}}).apply(book)
    assert len(empty) == 0


def test_an_empty_spec_is_the_whole_book(book):
    assert len(spec().apply(book)) == len(book)
    assert spec().active is False


# ------------------------------------------- the measures agree with it


def test_every_measure_describes_the_same_population():
    """The defect: tiles about the book above a table about a segment."""
    view = dv.view(spec(filters={"ews_band": ["HIGH", "VERY_HIGH"]}))

    matched = view["scope"]["matched"]
    assert view["kpis"]["borrower_count"] == matched
    assert sum(b["borrower_count"] for b in view["distribution"]) == matched
    assert view["row_count"] == matched
    assert view["trend"]["cohort_size"] == matched


def test_the_distribution_keeps_the_bands_a_filter_excluded_at_zero():
    # Dropping them would turn the chart into one bar with no explanation.
    view = dv.view(spec(filters={"ews_band": ["HIGH"]}))
    bands = {b["band"]: b["borrower_count"] for b in view["distribution"]}
    assert set(bands) == set(fsp.BANDS)
    assert bands["HIGH"] > 0
    assert all(bands[b] == 0 for b in fsp.BANDS if b != "HIGH")


def test_the_percentages_are_of_the_filtered_population(book):
    view = dv.view(spec(filters={"ews_band": ["HIGH", "VERY_HIGH"]}))
    total = sum(b["borrower_pct"] for b in view["distribution"])
    assert round(total) == 100
    assert view["scope"]["matched"] < len(book)


def test_the_exposure_tile_is_the_filtered_exposure_not_the_books(book):
    view = dv.view(spec(filters={"ews_band": ["VERY_HIGH"]}))
    subset = book[book["ews_band"] == "VERY_HIGH"]
    assert view["kpis"]["total_exposure"] == pytest.approx(
        float(subset["exposure"].sum()), abs=0.01)
    assert view["kpis"]["total_exposure"] < float(book["exposure"].sum())


def test_the_table_is_a_page_and_the_count_is_the_whole_result():
    view = dv.view(spec(filters={"ews_band": ["HIGH", "VERY_HIGH"]}, limit=5))
    assert len(view["rows"]) == 5
    assert view["row_count"] > 5, (
        "the count must describe the result, not the page -- a reader "
        "filtering to fifty obligors and seeing 'five' has been told the "
        "size of the fetch")


def test_the_table_does_not_ship_the_whole_model_surface(book):
    # §33. Three hundred rows of two and a half thousand columns to draw
    # eight of them is fifteen million values for a table.
    view = dv.view(spec(limit=5))
    assert len(view["rows"][0]) <= len(dv.TABLE_COLUMNS)
    assert len(book.columns) > len(dv.TABLE_COLUMNS)


def test_paging_walks_the_result_without_repeating_a_row():
    first = dv.view(spec(limit=10, offset=0))["rows"]
    second = dv.view(spec(limit=10, offset=10))["rows"]
    assert {r["customer_id"] for r in first}.isdisjoint(
        {r["customer_id"] for r in second})


def test_sorting_is_honoured_and_reversible():
    down = dv.view(spec(sort_by="ews_score", descending=True, limit=5))["rows"]
    up = dv.view(spec(sort_by="ews_score", descending=False, limit=5))["rows"]
    assert down[0]["ews_score"] >= down[-1]["ews_score"]
    assert up[0]["ews_score"] <= up[-1]["ews_score"]
    assert down[0]["ews_score"] >= up[0]["ews_score"]


# ------------------------------------------------------------ the trend


def test_an_unfiltered_trend_is_the_whole_book_in_every_month():
    trend = dv.view(spec())["trend"]
    assert trend["basis"] == dv.WHOLE_BOOK
    assert len(trend["points"]) == len(svc.periods())


def test_a_filtered_trend_anchors_the_cohort_and_says_so():
    """§8: the same obligors tracked back, labelled as that.

    The alternative -- re-filtering every month -- moves the line when
    membership moves, which reads as a change in the obligors and is not.
    """
    view = dv.view(spec(filters={"ews_band": ["VERY_HIGH"]}))
    trend = view["trend"]
    assert trend["basis"] == dv.COHORT
    assert trend["note"], "a cohort trend unlabelled is a survivorship claim"
    assert trend["cohort_size"] == view["scope"]["matched"]


def test_the_cohort_is_the_same_obligors_in_every_month_it_appears():
    view = dv.view(spec(filters={"ews_band": ["VERY_HIGH"]}))
    trend = view["trend"]
    size = trend["cohort_size"]
    for point in trend["points"]:
        assert point["in_cohort"] <= size, (
            "the cohort is fixed at the as-of month; it cannot grow "
            "backwards")


def test_the_cohort_trend_does_not_run_past_the_month_it_was_anchored_in():
    months = svc.periods()
    if len(months) < 3:
        pytest.skip("Not enough published months to anchor mid-history.")
    anchor = months[len(months) // 2]
    trend = dv.view(spec(period=anchor,
                         filters={"ews_band": ["HIGH", "VERY_HIGH"]}))["trend"]
    assert trend["points"], "the anchor month itself is in the series"
    assert all(p["period"] <= anchor for p in trend["points"])


def test_the_last_point_of_a_cohort_trend_is_the_tile_above_it():
    view = dv.view(spec(filters={"ews_band": ["HIGH", "VERY_HIGH"]}))
    last = view["trend"]["points"][-1]
    assert last["period"] == view["period"]
    assert last["borrower_count"] == view["kpis"]["borrower_count"]
    assert last["portfolio_ews"] == view["kpis"]["portfolio_ews"]


# ------------------------------------------------------ chips and facets


def test_every_active_filter_has_a_chip_and_an_inactive_one_has_none():
    view = dv.view(spec(filters={"ews_band": ["HIGH"], "dpd": {"min": 30}}))
    keys = {c["key"] for c in view["scope"]["chips"]}
    assert keys == {"ews_band", "dpd"}
    assert dv.view(spec())["scope"]["chips"] == []


def test_a_chip_reads_as_words_not_as_constants():
    chips = dv.view(spec(filters={"ews_band": ["VERY_HIGH"]}))["scope"]["chips"]
    assert chips[0]["value"] == "Very High"


def test_a_range_chip_says_which_end_is_open():
    only_low = spec(filters={"dpd": {"min": 30}}).describe()[0]["value"]
    only_high = spec(filters={"dpd": {"max": 30}}).describe()[0]["value"]
    both = spec(filters={"dpd": {"min": 30, "max": 90}}).describe()[0]["value"]
    assert only_low.startswith("at least")
    assert only_high.startswith("at most")
    assert " to " in both


def test_the_facets_offer_the_values_the_book_actually_holds(book):
    view = dv.view(spec())
    assert set(view["facets"]["segment"]) == {
        str(s) for s in book["segment"].dropna().unique()}
    assert view["facets"]["ews_band"] == list(fsp.BANDS)


def test_the_facets_do_not_narrow_with_the_filter(book):
    # A segment control that empties itself as soon as a segment is chosen
    # is a control a reader cannot change their mind with.
    view = dv.view(spec(filters={"segment": [str(book["segment"].iloc[0])]}))
    assert len(view["facets"]["segment"]) == book["segment"].nunique()


def test_the_screen_is_told_what_it_may_filter_by():
    contract = dv.view(spec())["contract"]
    keys = {c["key"] for c in contract["columns"]}
    assert {"customer", "segment", "exposure", "dpd", "ews_band", "ews_score",
            "ta_band", "classifier_band", "dominant_driver"} <= keys
    for column in contract["columns"]:
        assert column["kind"] in (fsp.TEXT, fsp.MULTI, fsp.RANGE)
        assert column["label"]


def test_the_scope_reads_back_as_a_sentence_a_person_can_check():
    view = dv.view(spec(filters={"segment": ["Large Corporate"],
                                 "dpd": {"min": 30}}))
    sentence = view["scope"]["sentence"]
    assert "Large Corporate" in sentence
    assert "30" in sentence
    assert dv.view(spec())["scope"]["sentence"] == "the whole book"


# ------------------------------------------------------- round-tripping


def test_a_spec_survives_being_written_out_and_read_back():
    original = spec(filters={"segment": ["Large Corporate"],
                             "ews_band": ["HIGH"],
                             "exposure": {"min": 10, "max": 900},
                             "customer": "al"},
                    sort_by="exposure", descending=False, limit=25, offset=50)
    again = fsp.FilterSpec.from_payload(original.to_dict())
    assert again.to_dict() == original.to_dict()


def test_a_customer_search_is_text_not_a_pattern(book):
    """A name is a name.

    `str.contains` interprets its argument as a regular expression by
    default, so a reader typing a bracket, a backslash or a plus got either
    a five-hundred or a match on something else -- and "Al-Rajhi (Holding)"
    is an ordinary customer name, not an unusual one.
    """
    for typed in ["(", "[", "\\", "a|b", "*", "a(b"]:
        assert len(spec(filters={"customer": typed}).apply(book)) >= 0

    name = str(book["customer_name"].iloc[0])
    assert name in set(spec(filters={"customer": name}).apply(book)
                       ["customer_name"])
