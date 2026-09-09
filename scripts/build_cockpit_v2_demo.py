#!/usr/bin/env python
"""
Build and publish the Cockpit Intelligence V2 demonstration datasets.

    .venv/bin/python scripts/build_cockpit_v2_demo.py            # eight quarters
    .venv/bin/python scripts/build_cockpit_v2_demo.py --pilot    # the two-quarter pilot

One command, idempotent, and restricted to the V2 namespace: the destination
guard runs before anything is generated and refuses unless the analytics
directory, the metadata directory and the database name all carry the
`cockpit_v2` namespace and the feature switch is on. It writes nothing to the
repository's own `data/analytics` or `metadata`.

Everything it produces is synthetic and says so on every row and in every
catalogue entry.
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

from backend.cockpit_v2 import calendar as cal  # noqa: E402
from backend.cockpit_v2 import generate as generate_mod  # noqa: E402
from backend.cockpit_v2 import guard  # noqa: E402
from backend.cockpit_v2 import persist  # noqa: E402
from backend.cockpit_v2 import stories as stories_mod  # noqa: E402
from backend.cockpit_v2 import validate as validate_mod  # noqa: E402

logger = logging.getLogger("build_cockpit_v2_demo")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true",
                        help="build the two-quarter, twelve-borrower pilot")
    parser.add_argument("--borrowers", type=int, default=0,
                        help="override the borrower count")
    parser.add_argument("--facilities", type=int, default=0,
                        help="override the target facility count")
    parser.add_argument("--quarters", default="",
                        help="comma-separated quarters to publish")
    parser.add_argument("--out", default="",
                        help="where to write the build report")
    parser.add_argument("--skip-validation", action="store_true",
                        help="write without running the integrity gates")
    parser.add_argument(
        "--perturb", default="",
        help=("Anti-canned-answer check (brief 6.2). "
              "BORROWER:KEY=VALUE[,KEY=VALUE], where KEY is one of "
              "pd_multiplier, coverage_multiplier, downturn_weight. Changes "
              "the stored INPUT and regenerates; the narrative is never "
              "touched. Example: CKB-0002:pd_multiplier=1.6"))
    parser.add_argument("--perturb-from", default="",
                        help="quarter from which the perturbation applies")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # The guard runs FIRST, before a single row is generated, so an unsafe
    # destination costs nothing and is impossible to write past.
    try:
        targets = guard.check_targets()
    except guard.UnsafeTarget as e:
        print(f"\nREFUSED: {e}\n", file=sys.stderr)
        return 2
    print("Destination guard passed:")
    for key, value in targets.to_dict().items():
        print(f"  {key:24} {value}")

    if args.quarters:
        publish = [cal.parse(q).label for q in args.quarters.split(",")]
    elif args.pilot:
        publish = list(cal.PILOT_QUARTERS)
    else:
        publish = list(cal.QUARTERS)

    borrowers = args.borrowers or (12 if args.pilot else 500)
    facilities = args.facilities or (22 if args.pilot else 1100)

    perturbations: dict[str, dict[str, float]] = {}
    if args.perturb:
        borrower, _, settings_text = args.perturb.partition(":")
        entry: dict[str, float] = {}
        for pair in settings_text.split(","):
            key, _, value = pair.partition("=")
            if key.strip():
                entry[key.strip()] = float(value)
        perturbations[borrower.strip()] = entry
        print(f"\nPerturbation: {borrower.strip()} {entry}"
              + (f" from {args.perturb_from}" if args.perturb_from else ""))

    print(f"\nGenerating {borrowers} borrowers, ~{facilities} facilities, "
          f"publishing {len(publish)} quarter(s): {', '.join(publish)}")
    started = time.perf_counter()
    build = generate_mod.build_demo(
        publish=publish, borrowers=borrowers, facilities_target=facilities,
        perturbations=perturbations or None,
        perturb_from=(cal.parse(args.perturb_from).label
                      if args.perturb_from else ""))
    generated = time.perf_counter() - started
    print(f"  generated in {generated:.1f}s")

    report = {}
    if not args.skip_validation:
        started = time.perf_counter()
        report = validate_mod.validate(build)
        print(f"  validated in {time.perf_counter() - started:.1f}s: "
              f"{report['passed']} passed, {report['failed']} failed")
        for check in report["checks"]:
            if not check["passed"]:
                print(f"    FAIL {check['id']}: {check['detail']}")
        if report["failed"]:
            print("\nREFUSED: the dataset did not pass its integrity gates, "
                  "so it was not published. Brief §8.1 blocks certification "
                  "of an invalid dataset.\n", file=sys.stderr)
            return 3

    started = time.perf_counter()
    written = persist.write_lake(build)
    print(f"  written in {time.perf_counter() - started:.1f}s")

    print("\nPUBLISHED")
    for name, rows in sorted(written["written_rows"].items()):
        print(f"  {name:36} {rows:>8,} rows")
    registration = written["registration"]
    print(f"\n  domain                    {registration['domain']}")
    print(f"  quarterly datasets        "
          f"{', '.join(registration['quarterly_datasets'])}")
    print(f"  history interface         {registration['history_dataset']}")
    print(f"  catalogue                 {registration['path']}")
    print(f"  datasets preserved        {registration['datasets_preserved']}")
    print(f"  relationships declared    {registration['relationships_declared']}")
    print(f"  data version              {written['data_version']}")

    out = Path(args.out) if args.out else (ROOT / "docs" / "cockpit_v2"
                                           / "evidence" / "demo_build.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {**written, "validation": report,
               "story_manifest_stories": len(stories_mod.STORIES)}
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n  build report              {out}")
    print("\nEvery row is synthetic and describes no real borrower.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
