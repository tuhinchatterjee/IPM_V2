"""A declared column that does not exist makes a whole dataset unreadable.

Not a small inaccuracy: the compiler selects every declared column, so one
phantom field turns every analysis over that dataset into a binder error. Both
retail application scorecard datasets were in exactly that state — the
catalogue declared `loan_to_income_bin` and `loan_to_income_woe`, the build
never wrote them, and nothing could read either dataset.

This walks every governed dataset that has data on disk and checks the
declaration against the artefact. It is slow enough to be worth its own file
and cheap enough to run every time.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.data_access.catalog import get_catalog


def _built_columns(dataset: str) -> set[str] | None:
    """The columns actually present, from the most recent partition."""
    import duckdb

    root = settings.analytics_dir / dataset
    if not root.exists():
        return None
    partitions = sorted(p for p in root.iterdir() if p.is_dir())
    pattern = (str(partitions[-1] / "*.parquet") if partitions
               else str(root / "*.parquet"))
    try:
        with duckdb.connect(database=":memory:") as conn:
            return {row[0] for row in conn.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{pattern}')").fetchall()}
    except Exception:  # noqa: BLE001 - nothing readable, nothing to check
        return None


def _datasets_with_data() -> list[str]:
    catalog = get_catalog()
    out = []
    for definition in catalog.all():
        if (settings.analytics_dir / definition.name).exists():
            out.append(definition.name)
    return sorted(out)


@pytest.mark.parametrize("dataset", _datasets_with_data())
def test_every_declared_field_exists_in_the_data(dataset):
    built = _built_columns(dataset)
    if built is None:
        pytest.skip(f"{dataset} has no readable partition")
    declared = set(get_catalog().dataset(dataset).fields)
    phantom = sorted(declared - built)
    assert not phantom, (
        f"{dataset} declares {len(phantom)} field(s) the data does not "
        f"contain: {', '.join(phantom)}. Every analysis over this dataset "
        "will fail at the binder, because the compiler selects every declared "
        "column.")
