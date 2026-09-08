#!/usr/bin/env python
"""Build and publish the Cockpit Agentic V3 twenty-quarter demonstration release.

    COCKPIT_AGENTIC_V3=true python scripts/build_cockpit_agentic_v3.py

Deterministic: the same arguments produce byte-identical data. Refuses to write
anywhere outside the configured V3 namespace, and refuses to publish a release
that fails any integrity gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cockpit_agentic import generate, profile, store, validate_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default="demo-20q-v1")
    parser.add_argument("--last-quarter", default="2026Q2")
    parser.add_argument("--borrowers", type=int,
                        default=generate.DEFAULT_BORROWERS)
    parser.add_argument("--facilities", type=int,
                        default=generate.DEFAULT_FACILITIES)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--evidence", default="docs/cockpit_agentic_v3/evidence")
    args = parser.parse_args()

    print(f"Building {args.release}: {args.borrowers} borrowers, "
          f"{args.facilities} facilities, twenty quarters to "
          f"{args.last_quarter}.")
    release = generate.build_release(
        dataset_release_id=args.release, last_quarter=args.last_quarter,
        borrowers=args.borrowers, facilities=args.facilities)
    conformance = generate.conform(release)
    print(f"  conformed: {sum(len(v) for v in conformance['added_as_null'].values())} "
          f"declared columns added as null, "
          f"{sum(len(v) for v in conformance['removed_undeclared'].values())} "
          f"undeclared removed.")

    report = validate_data.validate(release)
    print(f"  integrity: {report['checks_run']} checks, "
          f"{report['checks_failed']} failed.")
    if not report["passed"]:
        for failure in report["failures"]:
            print(f"    FAIL {failure['check_id']}: {failure['detail']}")
        print("Refusing to publish a release that fails an integrity gate.")
        return 1

    coverage = profile.profile_release(release)
    manifest = store.write(release, overwrite=args.overwrite)
    print(f"  published to {store.release_dir(args.release)}")

    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "release_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str))
    (evidence / "integrity_checks.json").write_text(
        json.dumps(report, indent=2, default=str))
    # The bounded, reviewable form. The full per-field profile is a build
    # artefact of the same seed and is rebuilt rather than committed.
    (evidence / "coverage_profile_summary.json").write_text(
        json.dumps(profile.compact(coverage), indent=2, default=str))
    (evidence / "release_summary.json").write_text(
        json.dumps(release.summary(), indent=2, default=str))
    print(f"  evidence written to {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
