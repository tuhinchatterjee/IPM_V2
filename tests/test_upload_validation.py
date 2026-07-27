"""Upload validation: the bundled workbook passes; malformed workbooks are
rejected with a failing check (the active dataset is never touched)."""

import io

import pandas as pd

from backend import data_loader as dl


def _bundled_sheets():
    xl = pd.ExcelFile(dl.DATA_PATH)
    return xl, {name: pd.read_excel(xl, sheet_name=name) for name in xl.sheet_names}


def _to_bytes(sheets: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    return buf.getvalue()


def test_bundled_workbook_passes():
    report = dl.validate_workbook_bytes(dl.DATA_PATH.read_bytes())
    assert report["ok"]
    assert not any(c["status"] == "fail" for c in report["checks"])


def test_non_excel_rejected():
    report = dl.validate_workbook_bytes(b"this is not an excel file")
    assert not report["ok"]
    assert report["checks"][0]["status"] == "fail"


def test_missing_supplementary_sheet_rejected():
    _xl, sheets = _bundled_sheets()
    sheets.pop(dl.SUPP_SHEET, None)
    report = dl.validate_workbook_bytes(_to_bytes(sheets))
    assert not report["ok"]
    assert any("Supplementary" in c["name"] and c["status"] == "fail" for c in report["checks"])


def test_no_quarter_sheets_rejected():
    _xl, sheets = _bundled_sheets()
    # Keep only the supplementary sheet — no Q# sheets remain.
    only_supp = {dl.SUPP_SHEET: sheets[dl.SUPP_SHEET]}
    report = dl.validate_workbook_bytes(_to_bytes(only_supp))
    assert not report["ok"]


def test_too_many_sheets_rejected():
    # A workbook with far more sheets than a real portfolio workbook.
    sheets = {f"Sheet{i}": pd.DataFrame({"a": [1]}) for i in range(dl.MAX_WORKBOOK_SHEETS + 2)}
    report = dl.validate_workbook_bytes(_to_bytes(sheets))
    assert not report["ok"]
    assert any(c["name"] == "Sheet count" and c["status"] == "fail" for c in report["checks"])


def test_missing_required_column_rejected():
    _xl, sheets = _bundled_sheets()
    quarters = dl.detect_quarter_sheets(list(sheets.keys()))
    # Drop a required column from one quarterly sheet.
    victim = quarters[-1]
    sheets[victim] = sheets[victim].drop(columns=[dl.EAD_COL])
    report = dl.validate_workbook_bytes(_to_bytes(sheets))
    assert not report["ok"]
    assert any(c["name"] == "Required columns" and c["status"] == "fail" for c in report["checks"])
