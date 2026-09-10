#!/usr/bin/env python
"""
Build the Saudi retail demonstration installation.

    .venv/bin/python scripts/build_retail_demo.py

Generates the twenty-five linked monthly snapshots of `retail_facility_month`,
registers the single "Cockpit Data" domain in the governed catalogue, and
writes the dataset manifest and the machine-readable data contract.

Idempotent: the same configuration and seed produce byte-identical business
content, and the publication is atomic — the new lake is staged and swapped in
only once every month has passed its checks, so a failed build cannot leave
half a portfolio behind.

Guarded: it refuses any analytics, metadata or database target that is not the
retail installation's, so it cannot be pointed at a frozen source demo.

Everything it writes is SYNTHETIC.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend.retail import DOMAIN_DISPLAY, SYNTHETIC_DISCLOSURE  # noqa: E402
from backend.retail import catalogue as cat  # noqa: E402
from backend.retail import guard  # noqa: E402
from backend.retail.config import load_config  # noqa: E402
from backend.retail.generate import PERIOD_FIELD, build  # noqa: E402

DEFAULT_ANALYTICS = ROOT / "data" / "retail" / "analytics"
DEFAULT_METADATA = ROOT / "metadata" / "retail"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analytics-dir", type=Path, default=DEFAULT_ANALYTICS)
    ap.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--facilities", type=int, default=None,
                    help="override the target active facilities in the latest month")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
    )
    log = logging.getLogger("build_retail_demo")

    cfg = load_config(args.config)
    if args.facilities:
        import dataclasses
        portfolio = dict(cfg.portfolio)
        portfolio["target_active_facilities_latest_month"] = int(args.facilities)
        cfg = dataclasses.replace(cfg, portfolio=portfolio)

    guard.mark(args.analytics_dir)
    guard.mark(args.metadata_dir)
    guard.require_retail_directory(args.analytics_dir, what="publish the retail lake")
    guard.require_retail_directory(args.metadata_dir, what="write the retail catalogue")
    guard.require_retail_database(None, what="seed")

    log.info("Building the Saudi retail demonstration book")
    log.info("  %s", SYNTHETIC_DISCLOSURE)
    log.info("  months        %d (%s .. %s)", cfg.months,
             cfg.first_snapshot.isoformat(), cfg.last_snapshot.isoformat())
    log.info("  seed          %d", cfg.seed)
    log.info("  target size   %s facilities in the latest month",
             f"{cfg.portfolio['target_active_facilities_latest_month']:,}")

    started = time.time()
    manifest = build(cfg, args.analytics_dir, log_progress=not args.quiet)
    elapsed = time.time() - started
    manifest["build_seconds"] = round(elapsed, 1)

    sample = pd.read_parquet(
        args.analytics_dir / cat.DATASET_NAME
        / f"{PERIOD_FIELD}={cfg.last_snapshot.year:04d}-{cfg.last_snapshot.month:02d}"
        / "data.parquet"
    )
    paths = cat.write_catalog(args.metadata_dir, sample.columns, manifest)

    last = manifest["months"][-1]
    log.info("")
    log.info("Published %d monthly datasets under one domain, %r", len(manifest["months"]),
             DOMAIN_DISPLAY)
    log.info("  rows total          %s", f"{manifest['total_rows']:,}")
    log.info("  latest month        %s — %s facilities, %s customers",
             last["reporting_month"], f"{last['distinct_facilities']:,}",
             f"{last['distinct_customers']:,}")
    log.info("  columns             %d", len(sample.columns))
    log.info("  gross carrying amt  SAR %s", f"{last['gross_carrying_amount_sar']:,.0f}")
    log.info("  loss allowance      SAR %s", f"{last['ecl_final_sar']:,.0f}")
    log.info("  build time          %.1fs", elapsed)
    log.info("  manifest hash       %s", manifest["manifest_hash"][:16])
    for name, p in paths.items():
        log.info("  %-18s %s", name, p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
