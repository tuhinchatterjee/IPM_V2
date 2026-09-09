#!/usr/bin/env python
"""Publish `corporate_ifrs9_facility` beside the canonical corporate book.

    .venv/bin/python scripts/build_corporate_ifrs9_facility.py

Reads `corporate_ifrs9` and `corporate_facilities` from the analytics lake and
writes the facility-grain view of the same book, partitioned by period like its
two sources. Refuses to publish if the two grains do not reconcile.

Deterministic: it derives, it does not draw. Running it twice produces the same
bytes, and running it after a corporate rebuild is how it stays true.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.corporate import ifrs9_facility as derive  # noqa: E402

SOURCES = ("corporate_ifrs9", "corporate_facilities")


def _read(root: Path, name: str) -> pd.DataFrame:
    directory = root / name
    if not directory.exists():
        raise SystemExit(
            f"{name} is not in the lake at {directory}. Run "
            f"scripts/build_corporate_universe.py first.")
    parts = sorted(directory.rglob("*.parquet"))
    if not parts:
        raise SystemExit(f"{name} has no Parquet files under {directory}.")
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="")
    parser.add_argument("--check", action="store_true",
                        help="reconcile only; write nothing")
    args = parser.parse_args(argv)

    root = Path(args.out) if args.out else Path(settings.analytics_dir)
    ifrs9 = _read(root, "corporate_ifrs9")
    facilities = _read(root, "corporate_facilities")
    print(f"> read {len(ifrs9):,} obligor-quarter and "
          f"{len(facilities):,} facility-quarter rows")

    frame = derive.build(ifrs9, facilities)
    print(f"> derived {len(frame):,} facility-quarter rows, "
          f"{frame.shape[1]} columns")

    breaks = derive.reconciles(frame, ifrs9)
    if len(breaks):
        print(f"! {len(breaks)} borrower-quarter(s) do not reconcile:")
        print(breaks.head(10).to_string())
        return 1
    print(f"> reconciles to obligor grain on every one of "
          f"{ifrs9[['borrower_id', 'period']].drop_duplicates().shape[0]:,} "
          f"borrower-quarters, within {derive.TOLERANCE}")

    if args.check:
        return 0

    directory = root / derive.DATASET
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for period, chunk in frame.groupby("period", sort=True):
        part = directory / f"period={period}"
        part.mkdir(parents=True, exist_ok=True)
        chunk.to_parquet(part / "data.parquet", index=False)
    print(f"> wrote {directory} "
          f"({frame['period'].nunique()} period partitions)")

    # Register it, or it is invisible. A dataset the governed catalogue does
    # not carry cannot be browsed in Data Builder, cannot be joined under a
    # declared relationship, and cannot be read by any module that goes
    # through the catalogue rather than around it — which is exactly how the
    # three Early Warning datasets came to exist on disk and nowhere else.
    from backend.corporate import catalogue as corporate_catalogue

    report = corporate_catalogue.merge_into_catalogue(
        {derive.DATASET: frame})
    print(f"> registered in the governed catalogue "
          f"({report.get('total_datasets')} datasets now)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
