"""A downloaded book has to be a book, not a table that opens with a warning.

What this is holding
--------------------
"Export to Excel" is easy to satisfy badly. A CSV renamed, or an HTML table
with an .xls extension, opens with a security prompt and arrives as text: every
exposure a string, every score a string, nothing to sort, nothing to sum,
nothing to pivot. It looks like the feature and is not.

So these tests open the bytes the endpoint would return and check the things
that make it useful in the hands of a credit officer: a real XLSX, numbers
stored as numbers, the COMPLETE filtered result rather than the page that was
on screen, and a second sheet recording the scope -- because a spreadsheet
that leaves the building without its filters will be read next quarter as if
it were the whole book.
"""

from __future__ import annotations

import io

import pytest

from backend.early_warning import dashboard_view as dv
from backend.early_warning import export as xp
from backend.early_warning import filterspec as fsp
from backend.early_warning import v2_service as svc

openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def built(**payload):
    spec = fsp.FilterSpec.from_payload(payload)
    frame, meta = dv.complete(spec)
    data = xp.workbook(frame, meta, exported_by="a test")
    return openpyxl.load_workbook(io.BytesIO(data)), frame, meta, data


# ------------------------------------------------------ it is a workbook


def test_it_is_a_real_xlsx_and_not_a_renamed_table():
    _, _, _, data = built()
    # The ZIP magic every OOXML file starts with. A CSV or an HTML table
    # with an .xls name fails here, which is exactly the point.
    assert data[:2] == b"PK"
    assert xp.MIME.endswith("spreadsheetml.sheet")


def test_it_has_the_data_sheet_and_the_view_sheet():
    book, _, _, _ = built()
    assert book.sheetnames == ["Early Warning", "View"]


def test_a_number_arrives_as_a_number():
    book, frame, _, _ = built(filters={"ews_band": ["HIGH", "VERY_HIGH"]})
    sheet = book["Early Warning"]
    headings = [c.value for c in sheet[1]]
    for column, kind in (("Exposure (SAR m)", float),
                         ("Early Warning score", float),
                         ("Days past due", int)):
        index = headings.index(column) + 1
        value = sheet.cell(row=2, column=index).value
        assert isinstance(value, (int, float)), (
            f"{column} arrived as {type(value).__name__}; a column stored as "
            "text cannot be summed, sorted or pivoted")
        assert not isinstance(value, bool)


def test_a_numeric_column_carries_a_number_format():
    book, _, _, _ = built()
    sheet = book["Early Warning"]
    headings = [c.value for c in sheet[1]]
    index = headings.index("Exposure (SAR m)") + 1
    assert sheet.cell(row=2, column=index).number_format != "General"


def test_the_header_is_frozen_and_filterable():
    # The first thing anyone does with a downloaded book is sort it.
    book, frame, _, _ = built()
    sheet = book["Early Warning"]
    assert sheet.freeze_panes == "A2"
    if len(frame):
        assert sheet.auto_filter.ref


def test_the_headings_are_words_not_stored_column_names():
    book, _, _, _ = built()
    headings = [c.value for c in book["Early Warning"][1]]
    assert "Customer" in headings
    assert "Early Warning band" in headings
    assert "ews_band" not in headings


# ------------------------------------------- it is the complete result


def test_the_file_holds_every_matching_obligor_not_the_page_on_screen():
    narrow = {"ews_band": ["HIGH", "VERY_HIGH"]}
    on_screen = dv.view(fsp.FilterSpec.from_payload(
        {"filters": narrow, "limit": 5}))
    book, frame, meta, _ = built(filters=narrow, limit=5)

    assert len(on_screen["rows"]) == 5
    assert len(frame) == on_screen["row_count"] > 5, (
        "the export exists because the screen shows a page; handing it the "
        "same page makes the button a slower way of copying what is visible")
    assert book["Early Warning"].max_row == len(frame) + 1


def test_the_export_and_the_screen_describe_the_same_population():
    narrow = {"segment": ["Large Corporate"]}
    on_screen = dv.view(fsp.FilterSpec.from_payload({"filters": narrow}))
    _, frame, meta, _ = built(filters=narrow)
    assert len(frame) == on_screen["row_count"]
    assert meta["period"] == on_screen["period"]


def test_the_export_honours_the_sort_the_reader_set():
    _, frame, _, _ = built(sort_by="exposure", descending=False)
    exposures = list(frame["exposure"])
    assert exposures == sorted(exposures)


def test_an_unfiltered_export_is_the_whole_month():
    _, frame, _, _ = built()
    assert len(frame) == len(svc.borrower_month())


def test_a_filter_matching_nothing_produces_a_readable_empty_workbook():
    book, frame, _, _ = built(filters={"dpd": {"min": 10_000_000}})
    assert len(frame) == 0
    # Headings still present, so the file says what it would have held.
    assert [c.value for c in book["Early Warning"][1]][0] == "Customer ID"


# ------------------------------------------------------ it says its scope


def test_the_view_sheet_records_the_as_of_month_and_the_filters():
    book, _, _, _ = built(filters={"segment": ["Large Corporate"],
                                   "dpd": {"min": 30}})
    text = "\n".join(
        " | ".join("" if v is None else str(v) for v in row)
        for row in book["View"].iter_rows(values_only=True))
    assert "As-of month" in text
    assert svc.latest_period() in text
    assert "Large Corporate" in text
    assert "30" in text
    assert "Sorted by" in text


def test_the_view_sheet_says_how_many_matched_out_of_how_many_published():
    book, frame, _, _ = built(filters={"ews_band": ["VERY_HIGH"]})
    values = {str(row[0]): row[1]
              for row in book["View"].iter_rows(values_only=True)
              if row and row[0]}
    assert values["Obligors in this file"] == len(frame)
    assert values["Obligors published in the month"] == len(
        svc.borrower_month())


def test_an_unfiltered_export_says_it_is_the_whole_book():
    book, _, _, _ = built()
    text = "\n".join(str(row[0]) for row in book["View"].iter_rows(
        values_only=True) if row and row[0])
    assert "whole book" in text


def test_the_view_sheet_carries_the_descriptive_not_predictive_basis():
    # The caveat travels with the file, because the file outlives the screen
    # that carried it.
    book, _, _, _ = built()
    text = " ".join(str(c) for row in book["View"].iter_rows(values_only=True)
                    for c in row if c)
    assert "not a prediction" in text
    assert "approval or decline" in text


# ------------------------------------------------------------ the name


def test_the_filename_says_the_month_the_cut_and_the_size():
    _, _, meta, _ = built(filters={"ews_band": ["HIGH", "VERY_HIGH"]})
    name = xp.filename(meta)
    assert name.endswith(".xlsx")
    assert svc.latest_period() in name
    assert "obligors" in name
    assert "high" in name.lower()


def test_the_filename_is_safe_to_write_to_a_disk():
    _, _, meta, _ = built(filters={"customer": 'a/b\\c:"*?<>|'})
    name = xp.filename(meta)
    assert not set(name) & set('/\\:*?"<>|')
    assert len(name) <= 128
