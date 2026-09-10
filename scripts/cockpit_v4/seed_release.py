#!/usr/bin/env python3
"""Publish an isolated V4 synthetic release. Never overwrites another one.

V4 does not need its own data domain -- it uses the V3 corporate_cockpit
generator unchanged, which is the point: the domain is preserved and only the
orchestration changed. What V4 needs is its OWN namespace, so a V4 build
cannot write over a release a running V3 or demo instance is serving.

Usage:
    python3 scripts/cockpit_v4/seed_release.py --release v4-uat-20q-v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default="v4-uat-20q-v1")
    parser.add_argument("--namespace", default="cockpit_v4",
                        help="Runtime namespace. Never the V3 one.")
    parser.add_argument("--borrowers", type=int, default=120)
    parser.add_argument("--facilities", type=int, default=280)
    parser.add_argument("--last-quarter", default="2026Q2")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.namespace.strip() in ("", "cockpit_agentic_v3"):
        print("Refusing to seed into the V3 namespace. V4 uses its own.",
              file=sys.stderr)
        return 2

    # These are read by backend.config at import time, so they are set first.
    os.environ["COCKPIT_AGENTIC_V3"] = "true"
    os.environ["COCKPIT_AGENTIC_V3_NAMESPACE"] = args.namespace

    from backend.cockpit_agentic import generate, profile, store, validate_data

    target = store.release_dir(args.release)
    if args.namespace not in str(target):
        print(f"Refusing: {target} is not inside the V4 namespace.",
              file=sys.stderr)
        return 2
    if target.exists() and not args.overwrite:
        print(f"Release {args.release} already exists at {target}. A "
              f"published release is immutable; pass --overwrite "
              f"deliberately or choose a new id.")
        return 0

    print(f"Building {args.release}: {args.borrowers} borrowers, "
          f"{args.facilities} facilities, ending {args.last_quarter}")
    release = generate.build_release(
        dataset_release_id=args.release, last_quarter=args.last_quarter,
        borrowers=args.borrowers, facilities=args.facilities)
    conformance = generate.conform(release)
    report = validate_data.validate(release)
    failures = [c for c in report.get("checks", [])
                if not c.get("ok") and c.get("severity") == "error"]
    if failures:
        print("Refusing to publish a release that fails an integrity gate:")
        for check in failures:
            print(f"  - {check.get('name')}: {check.get('detail')}")
        return 1

    coverage = profile.profile_release(release)
    manifest = store.write(release, overwrite=args.overwrite)
    print(f"  published to {target}")
    print(f"  relations: {len(manifest['relations'])}")
    print(f"  quarters:  {len(release.calendar.slots)} "
          f"({release.calendar.slots[0]}..{release.calendar.slots[-1]})")

    evidence = ROOT / "docs" / "cockpit_v4" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "release_manifest.json").write_text(
        json.dumps({"release": args.release, "namespace": args.namespace,
                    "relations": manifest["relations"],
                    "conformance": conformance},
                   indent=2, default=str))
    (evidence / "release_summary.json").write_text(
        json.dumps(release.summary(), indent=2, default=str))
    (evidence / "coverage_summary.json").write_text(
        json.dumps(profile.outline(coverage), indent=2, default=str))
    print(f"  evidence written to {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
