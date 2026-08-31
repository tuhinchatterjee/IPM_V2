#!/usr/bin/env python
"""
Build the corporate Borrower 360 demonstration universe. B1-B7.

    .venv/bin/python scripts/build_corporate_universe.py

Generates 3,800 corporate borrowers over sixteen quarters, the nineteen
governed domains, the observed relationship graph, entity resolution across
three source systems and the Borrower 360 semantic snapshot; writes the
Parquet lake and registers the datasets in the governed catalogue.

Everything it writes is synthetic and says so: every row carries
`origin = SYNTHETIC_DEMO` and every catalogue entry is marked synthetic. It
describes no real company, no real ownership structure and no real bank's
book.

Options
--------
    --quarters N       build only the first N quarters, for a fast smoke run
    --graph-quarters N derive the graph for only the last N quarters
    --no-graph         skip the derived graph entirely
    --no-catalogue     skip catalogue registration
    --no-write         build and report without writing any Parquet
    --out PATH         where to write the build report
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.corporate import NOT_CLIENT_DATA, ORIGIN  # noqa: E402
from backend.corporate import catalogue as catalogue_mod  # noqa: E402
from backend.corporate import domains as domains_mod  # noqa: E402
from backend.corporate import graphsummary as graphsummary_mod  # noqa: E402
from backend.corporate import lineage as lineage_mod  # noqa: E402
from backend.corporate import resolution as resolution_mod  # noqa: E402
from backend.corporate import snapshot as snapshot_mod  # noqa: E402
from backend.corporate import universe as universe_mod  # noqa: E402

logger = logging.getLogger("build_corporate_universe")

#: Datasets partitioned by period on disk. The rest are small enough that
#: partitioning them costs more in directory overhead than it saves in scans.
PARTITIONED: frozenset[str] = frozenset({
    "corporate_customer_master", "corporate_ratings", "corporate_facilities",
    "corporate_ifrs9", "corporate_delinquency", "corporate_covenants",
    "corporate_collateral", "corporate_limits", "corporate_profitability",
    graphsummary_mod.GROUPS_DATASET,
    catalogue_mod.SNAPSHOT_DATASET,
})


def write_frame(name: str, frame: pd.DataFrame, root: Path) -> int:
    directory = root / name
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)

    if name not in PARTITIONED or "period" not in frame.columns:
        frame.to_parquet(directory / "data.parquet", index=False)
        return 1
    written = 0
    for period, chunk in frame.groupby("period", sort=True):
        part = directory / f"period={period}"
        part.mkdir(parents=True, exist_ok=True)
        chunk.to_parquet(part / "data.parquet", index=False)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarters", type=int, default=0,
                        help="build only the first N quarters (smoke run)")
    parser.add_argument("--graph-quarters", type=int, default=0,
                        help="derive the graph for only the last N quarters")
    parser.add_argument("--no-graph", action="store_true",
                        help="skip the derived graph; its twenty Borrower 360 "
                             "fields then read NOT COMPUTED")
    parser.add_argument("--no-catalogue", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--out", default="docs/corporate_universe_build.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    periods = (universe_mod.QUARTERS[:args.quarters] if args.quarters
               else None)

    print("> Building the corporate universe")
    started = time.time()
    universe = universe_mod.build(periods=periods)
    print(f"  {len(universe.quarters)} quarter(s) in "
          f"{time.time() - started:.0f}s")

    graph_frames: dict[str, pd.DataFrame] = {}
    graph_periods: list[str] | None = None
    if not args.no_graph:
        graph_periods = (universe.quarters[-args.graph_quarters:]
                         if args.graph_quarters else list(universe.quarters))
        print(f"> Deriving the graph for {len(graph_periods)} quarter(s)")
        started = time.time()
        graph_frames = graphsummary_mod.build(universe, periods=graph_periods)
        groups = graph_frames[graphsummary_mod.GROUPS_DATASET]
        print(f"  {len(groups):,} borrower-quarter rows, "
              f"{len(graph_frames[graphsummary_mod.DQ_DATASET]):,} quality "
              f"issue(s) in {time.time() - started:.0f}s")

    print("> Assembling the Borrower 360 snapshot")
    started = time.time()
    snapshot = snapshot_mod.assemble(
        universe,
        graph=graph_frames.get(graphsummary_mod.GROUPS_DATASET))
    print(f"  {len(snapshot):,} rows x {len(lineage_mod.FIELDS)} fields in "
          f"{time.time() - started:.0f}s")

    frames = dict(universe.frames)
    if graph_frames:
        # The group limit could not be computed before the graph existed, so
        # `build_limits` wrote NOT YET COMPUTED. It exists now.
        frames["corporate_limits"] = graphsummary_mod.apply_group_limits(
            frames, graph_frames[graphsummary_mod.GROUPS_DATASET])
        frames.update(graph_frames)
    frames[catalogue_mod.SNAPSHOT_DATASET] = snapshot

    report: dict[str, object] = {
        "origin": ORIGIN,
        "not_client_data": NOT_CLIENT_DATA,
        "universe": universe.to_dict(),
        "domains": domains_mod.catalogue(),
        "lineage": {k: v for k, v in lineage_mod.catalogue().items()
                    if k != "fields"},
        "snapshot": snapshot_mod.summary(snapshot),
        "entity_resolution": resolution_mod.summary(
            universe["corporate_entity_resolution"]),
        "graph": {
            "derived": bool(graph_frames),
            "quarters": graph_periods or [],
            "provenance": (
                graph_frames[graphsummary_mod.GROUPS_DATASET].attrs.get(
                    "provenance", []) if graph_frames else []),
        },
    }

    if not args.no_write:
        print("> Writing the Parquet lake")
        root = Path(settings.analytics_dir)
        total_parts = 0
        for name, frame in sorted(frames.items()):
            parts = write_frame(name, frame, root)
            total_parts += parts
            print(f"  {name:34s} {len(frame):>8,} rows  {parts:>3} part(s)")
        report["lake"] = {"root": str(root), "parts": total_parts,
                          "datasets": len(frames)}

    if not args.no_catalogue:
        print("> Registering the governed catalogue")
        registered = catalogue_mod.merge_into_catalogue(frames)
        print(f"  {registered['dataset_count']} dataset(s), "
              f"{registered['relationships_declared']} relationship(s), "
              f"{registered['forbidden_joins']} forbidden join(s)")
        report["catalogue"] = registered

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n> Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
