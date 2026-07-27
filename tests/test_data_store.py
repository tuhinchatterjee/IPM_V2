"""Parquet codec + frame reconstruction in services.data_store — the DB-free parts
that guarantee a workbook stored in Postgres reloads byte-identically. (The dummy
DATABASE_URL from conftest lets the module import; these tests never connect.)"""

import pandas as pd

from backend import data_loader as dl
from backend.services import data_store


def test_parquet_roundtrip_preserves_dtypes_and_values(q):
    sub = dl.filtered_quarter(q)
    blob = data_store.df_to_parquet(sub)
    back = data_store.parquet_to_df(blob)
    assert len(back) == len(sub)
    assert str(back["Snapshot Date"].dtype) == str(sub["Snapshot Date"].dtype)
    assert back[dl.EAD_COL].sum() == pd.Series(sub[dl.EAD_COL]).sum()


def test_read_workbook_sheets_finds_quarters_and_supp():
    sheets, quarters = data_store.read_workbook_sheets(dl.DATA_PATH)
    assert quarters == dl.QUARTER_SHEETS
    assert dl.SUPP_SHEET in sheets
    for qsheet in quarters:
        assert qsheet in sheets


def test_sheets_to_frames_reconstructs_bundled_df():
    """Rebuilding from stored sheets reproduces data_loader's DF exactly."""
    sheets, quarters = data_store.read_workbook_sheets(dl.DATA_PATH)
    df, supp = data_store.sheets_to_frames(sheets, quarters)

    assert len(df) == len(dl.DF)
    assert df[dl.EAD_COL].sum() == dl.DF[dl.EAD_COL].sum()
    # Quarter is restored as an ordered categorical with the same categories.
    assert isinstance(df["Quarter"].dtype, pd.CategoricalDtype)
    assert list(df["Quarter"].cat.categories) == quarters
    # Supplementary is indexed by Customer ID, like SUPP_DF.
    assert supp.index.name == "Customer ID"
    assert len(supp) == len(dl.SUPP_DF)


def test_sha256_is_stable():
    content = b"hello world"
    assert data_store.sha256_bytes(content) == data_store.sha256_bytes(content)
    assert len(data_store.sha256_bytes(content)) == 64
