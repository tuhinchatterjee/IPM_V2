#!/usr/bin/env python
"""
Build the retail scorecard demonstration universe.

    .venv/bin/python scripts/build_retail_scorecards.py

Generates both domains, fits the frozen binning and the three models per
scorecard on an out-of-time development population, scores every validation
month, writes the Parquet lake and registers the datasets in the governed
catalogue.

Everything it writes is synthetic and says so: every row carries
`origin = SYNTHETIC_DEMO` and every catalogue entry is marked synthetic. It
describes no real customer and no real bank's book.

Options
--------
    --application-only / --behavioral-only   build one side
    --months N                               build only the first N months,
                                             for a fast smoke run
    --no-catalogue                           skip catalogue registration
    --register                               also record the built models,
                                             their binning specification and
                                             the demonstration validation
                                             policy in the model registry
                                             (§12); needs a database
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

from backend.scorecard import build as build_mod  # noqa: E402
from backend.scorecard import catalogue as catalogue_mod  # noqa: E402
from backend.scorecard import synthetic as synth  # noqa: E402

logger = logging.getLogger("build_retail_scorecards")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-only", action="store_true")
    parser.add_argument("--behavioral-only", action="store_true")
    parser.add_argument("--months", type=int, default=0,
                        help="build only the first N months (smoke run)")
    parser.add_argument("--no-catalogue", action="store_true")
    parser.add_argument("--register", action="store_true",
                        help="record the built models in the §12 registry")
    parser.add_argument("--out", default="docs/retail_scorecard_build.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    wanted = [build_mod.APP, build_mod.BEH]
    if args.application_only:
        wanted = [build_mod.APP]
    elif args.behavioral_only:
        wanted = [build_mod.BEH]

    report: dict[str, object] = {
        "origin": synth.ORIGIN,
        "not_client_data": (
            "Every row generated here is synthetic. It describes no real "
            "customer and no real bank's book."),
        "scorecards": {},
    }

    for scorecard_type in wanted:
        months = None
        if args.months:
            source = (synth.APPLICATION_MONTHS
                      if scorecard_type == build_mod.APP
                      else synth.BEHAVIORAL_MONTHS)
            months = source[:args.months]

        print(f"\n> Building {scorecard_type}")
        started = time.time()
        result = build_mod.build(scorecard_type, months=months)
        counts = result.counts
        elapsed = time.time() - started

        print(f"  {len(counts.months)} month(s), {counts.total_rows:,} rows, "
              f"smallest month {counts.smallest_month:,}, "
              f"{len(counts.matured_months)} matured [{elapsed:.0f}s]")
        for kind, equation in result.models.items():
            print(f"  {kind}: {len(equation['terms'])} variables, "
                  f"intercept {equation['intercept']:+.4f}")
        report["scorecards"][scorecard_type] = result.to_dict()

    if not args.no_catalogue:
        print("\n> Registering the governed catalogue")
        registered = catalogue_mod.merge_into_catalogue()
        print(f"  {len(registered['scorecard_datasets'])} dataset(s), "
              f"{registered['relationships_declared']} relationship(s)")
        report["catalogue"] = registered

    if args.register:
        # Registration is opt-in because it needs a database, and the build
        # itself does not: generating the lake on a machine with no
        # PostgreSQL is a normal thing to do.
        print("\n> Recording the model registry")
        from backend.db.engine import get_session  # noqa: PLC0415
        from backend.scorecard import registry as registry_mod  # noqa: PLC0415

        with get_session() as session:
            recorded = registry_mod.seed(session)
        for entry in recorded["models"]:
            print(f"  {entry['model_id']} {entry['model_version']} "
                  f"{entry['status']}")
        print(f"  {recorded['limits']} demonstration policy limit(s)")
        report["registry"] = recorded

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n> Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
