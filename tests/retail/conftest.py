"""
Fixtures for the retail acceptance gates.

Two books are available to a test:

* `retail_book` — the SHIPPED lake under `data/retail/analytics`, if it has been
  built. Gates that must hold for what the user will actually open read this
  one, and skip with a clear message when it is absent.
* `small_book` — a deterministic 900-facility build in a temporary directory,
  used where a gate needs to run a build itself (idempotency, atomic
  publication, a fresh start) and where the shipped book would be needlessly
  slow.

Both are session-scoped: the small book is generated once, not once per test.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pandas as pd
import pytest

from backend.retail.config import load_config
from backend.retail.generate import PERIOD_FIELD, build

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_ANALYTICS = ROOT / "data" / "retail" / "analytics"
SHIPPED_METADATA = ROOT / "metadata" / "retail"
DATASET = "retail_facility_month"

SMALL_FACILITIES = 900


def _small_config():
    cfg = load_config()
    portfolio = dict(cfg.portfolio)
    portfolio["target_active_facilities_latest_month"] = SMALL_FACILITIES
    return dataclasses.replace(cfg, portfolio=portfolio)


class Book:
    """A published retail lake, with the readers the gates need."""

    def __init__(self, analytics_dir: Path, manifest: dict):
        self.analytics_dir = Path(analytics_dir)
        self.manifest = manifest
        self._cache: dict[str, pd.DataFrame] = {}

    @property
    def dataset_dir(self) -> Path:
        return self.analytics_dir / DATASET

    def months(self) -> list[str]:
        return sorted(p.name.split("=", 1)[1] for p in self.dataset_dir.glob(f"{PERIOD_FIELD}=*"))

    def month(self, reporting_month: str) -> pd.DataFrame:
        if reporting_month not in self._cache:
            path = self.dataset_dir / f"{PERIOD_FIELD}={reporting_month}" / "data.parquet"
            self._cache[reporting_month] = pd.read_parquet(path)
        return self._cache[reporting_month]

    def latest(self) -> pd.DataFrame:
        return self.month(self.months()[-1])

    def first(self) -> pd.DataFrame:
        return self.month(self.months()[0])

    def all_months(self, columns: list[str] | None = None) -> pd.DataFrame:
        frames = []
        for m in self.months():
            path = self.dataset_dir / f"{PERIOD_FIELD}={m}" / "data.parquet"
            frames.append(pd.read_parquet(path, columns=columns))
        return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="session")
def small_config():
    return _small_config()


@pytest.fixture(scope="session")
def small_book(tmp_path_factory) -> Book:
    out = tmp_path_factory.mktemp("retail_small")
    cfg = _small_config()
    manifest = build(cfg, out, log_progress=False)
    return Book(out, manifest)


@pytest.fixture(scope="session")
def retail_book() -> Book:
    """The shipped lake. Skips, loudly, when it has not been built."""
    manifest_path = SHIPPED_METADATA / "retail_dataset_manifest.json"
    if not (SHIPPED_ANALYTICS / DATASET).exists() or not manifest_path.exists():
        pytest.skip(
            "The shipped retail lake is not built. Run "
            "`.venv/bin/python scripts/build_retail_demo.py` first — these gates "
            "check what the user will actually open, so they do not fall back to "
            "a temporary book."
        )
    import json
    return Book(SHIPPED_ANALYTICS, json.loads(manifest_path.read_text()))


@pytest.fixture(scope="session")
def shipped_catalog() -> dict:
    path = SHIPPED_METADATA / "catalog.json"
    if not path.exists():
        pytest.skip("The shipped retail catalogue has not been written.")
    import json
    return json.loads(path.read_text())
