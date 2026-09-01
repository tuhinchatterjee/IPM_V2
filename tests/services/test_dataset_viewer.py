"""
The dataset viewer is a viewer, not a query surface.

The whole reason CreditProbe can claim its figures are trustworthy is that
nothing reaches the data except through the governed catalogue. A grid that
takes a column name from a query string and a value from a text box is the most
likely place for that to quietly stop being true, so the rules are tested here
directly rather than inferred from the screen behaving.
"""

from __future__ import annotations

import pytest

from backend.services import data_builder as db

DATASET = "portfolio_facility"


@pytest.fixture(scope="module")
def first_page() -> dict:
    return db.browse_dataset(DATASET, limit=5)


def test_a_page_is_a_page_not_the_whole_dataset(first_page):
    """Fifteen thousand rows are never handed to the browser."""
    assert first_page["returned"] <= 5
    assert first_page["total_rows"] > 5_000, "the fixture book should be large"
    assert len(first_page["rows"]) == first_page["returned"]


def test_the_schema_travels_with_the_page(first_page):
    """A column shown without its definition is a column nobody can check."""
    assert first_page["fields"], "no schema returned"
    for field in first_page["fields"]:
        assert field["name"]
        assert "definition" in field
        assert "data_type" in field
        assert "sensitivity" in field


def test_an_unknown_sort_column_is_refused():
    with pytest.raises(ValueError, match="not a field"):
        db.browse_dataset(DATASET, sort="; drop table facilities")


def test_an_unknown_filter_column_is_refused():
    with pytest.raises(ValueError, match="not a field"):
        db.browse_dataset(DATASET, filters=["nonexistent_column:eq:1"])


def test_an_unknown_comparison_is_refused():
    """The set of things a filter can express is fixed in the product."""
    with pytest.raises(ValueError, match="not a comparison"):
        db.browse_dataset(DATASET, filters=["ifrs9_stage:like:%2%"])


def test_a_malformed_filter_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="not a filter"):
        db.browse_dataset(DATASET, filters=["justacolumn"])


def test_a_filter_value_is_compared_never_executed():
    """A value that looks like SQL is a value that matches nothing."""
    page = db.browse_dataset(DATASET, filters=["ifrs9_stage:eq:1' OR '1'='1"])
    assert page["total_rows"] == 0


def test_a_search_term_is_a_substring_not_a_pattern():
    """Typing a bracket into a search box must not raise."""
    page = db.browse_dataset(DATASET, search="(unclosed")
    assert page["total_rows"] == 0


def test_filtering_reports_both_counts():
    """"1,841 of 16,346" reads as a filter; "1,841" reads as a small dataset."""
    page = db.browse_dataset(DATASET, filters=["ifrs9_stage:eq:2"], limit=5)
    assert page["filtered"] is True
    assert 0 < page["total_rows"] < page["total_in_period"]


def test_an_unfiltered_page_says_so(first_page):
    assert first_page["filtered"] is False
    assert first_page["total_rows"] == first_page["total_in_period"]


def test_sorting_is_stable_and_ordered():
    ascending = db.browse_dataset(DATASET, sort="ead", limit=20)
    values = [row["ead"] for row in ascending["rows"] if row["ead"] is not None]
    assert values == sorted(values)

    descending = db.browse_dataset(DATASET, sort="ead", descending=True, limit=20)
    top = [row["ead"] for row in descending["rows"] if row["ead"] is not None]
    assert top == sorted(top, reverse=True)


def test_paging_walks_the_dataset_without_repeating():
    one = db.browse_dataset(DATASET, sort="account_id", limit=5, offset=0)
    two = db.browse_dataset(DATASET, sort="account_id", limit=5, offset=5)
    assert [r["account_id"] for r in one["rows"]] != [r["account_id"] for r in two["rows"]]


def test_columns_lead_with_the_ones_that_identify_a_row(first_page):
    """Alphabetical is not an order — it puts "AI Risk Score" before "Borrower".

    These are also the columns the grid keeps on screen while you scroll
    sideways, so getting them wrong costs the reader the ability to tell which
    facility a row is.
    """
    names = [f["name"] for f in first_page["fields"]]
    assert names[:3] == ["account_id", "customer_id", "borrower_name"]


def test_a_column_constant_across_the_page_is_not_promoted(first_page):
    """Every row carries the same period; the toolbar already says which."""
    names = [f["name"] for f in first_page["fields"]]
    assert names[0] != "period"


def test_an_explicit_column_list_is_honoured_in_the_callers_order():
    page = db.browse_dataset(
        DATASET, limit=1, fields=["ead", "borrower_name", "ifrs9_stage"])
    assert [f["name"] for f in page["fields"]] == [
        "ead", "borrower_name", "ifrs9_stage"]


def test_only_governed_fields_are_returned():
    page = db.browse_dataset(DATASET, fields=["ead", "not_a_field"], limit=1)
    assert [f["name"] for f in page["fields"]] == ["ead"]
    assert set(page["rows"][0]) == {"ead"}


# ------------------------------------------------------------- column profile


def test_a_column_profile_describes_what_is_there_not_what_should_be():
    profile = db.column_profile(DATASET, "ifrs9_stage")
    assert profile["rows"] > 0
    assert profile["distinct"] >= 1
    assert 0.0 <= profile["missing_pct"] <= 100.0
    assert profile["top_values"], "a categorical column should report its values"
    assert sum(v["count"] for v in profile["top_values"]) <= profile["rows"]


def test_a_numeric_column_gets_a_numeric_summary():
    profile = db.column_profile(DATASET, "ead")
    stats = profile["statistics"]
    assert stats is not None
    assert stats["min"] <= stats["p25"] <= stats["median"] <= stats["p75"] <= stats["max"]


def test_profiling_an_unknown_column_is_refused():
    with pytest.raises(ValueError, match="not a field"):
        db.column_profile(DATASET, "salary")


# ------------------------------------------------------------ schema history


def test_schema_history_covers_every_published_period():
    history = db.schema_across_periods(DATASET)
    assert history["periods"], "the fixture book should have periods"
    assert set(history["presence"]) == set(history["periods"])
    for period in history["periods"]:
        assert set(history["presence"][period]["fields"]) == set(history["fields"])


def test_schema_history_reports_stability_honestly():
    history = db.schema_across_periods(DATASET)
    assert history["stable"] == (not history["changes"])


# ------------------------------------------------------------------- export


def test_an_export_is_capped_and_says_when_it_truncated():
    _, description = db.export_rows(DATASET, limit=10)
    assert description["rows"] == 10
    assert description["truncated"] is True
    assert description["matched_rows"] > 10


def test_an_export_carries_the_same_rows_as_the_view():
    filters = ["ifrs9_stage:eq:3"]
    page = db.browse_dataset(DATASET, filters=filters, limit=5)
    csv_text, description = db.export_rows(DATASET, filters=filters, limit=5)
    assert description["rows"] == page["returned"]
    assert description["matched_rows"] == page["total_rows"]
    header = csv_text.splitlines()[0].split(",")
    assert header == [f["name"] for f in page["fields"]]


def test_an_export_of_demonstration_data_is_marked_as_such():
    _, description = db.export_rows(DATASET, limit=1)
    assert description["is_synthetic"] is True
