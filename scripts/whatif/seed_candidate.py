#!/usr/bin/env python3
"""Publish the labelled synthetic candidate releases.

    python3 scripts/whatif/seed_candidate.py --domain all

Builds `v4-whatif-corporate-20q-s1` and `v4-whatif-retail-20m-s1`, runs the
same `invariants.check` gate the accepted books go through, publishes through
the same `lake.publish`, and then re-verifies that both ACCEPTED releases are
byte-identical to what they were before. That last step is not a formality:
this script writes into the same lake root the accepted books live in, and a
generator bug that touched them would otherwise be discovered by a reader
rather than by the build.

**The flags must be on to build.** `lake.publish` requires every relation the
schema declares for the domain, and the candidate relations are declared only
when that book's What-If flag is on. This script sets them for itself, which
is why seeding the ACCEPTED books (`scripts/cockpit_v4/seed_domains.py`) must
be run with the flags off -- their generators do not produce candidate
relations and the publish would refuse.

Everything published is SYNTHETIC_DEMO: generated borrowers, a generated
economy, and ECL measured by `reference_ecl.py`, which is a calculator written
for this demonstration and is not a bank engine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The candidate relations only exist for a book whose flag is on, and the
# build needs them before anything else imports the schema.
os.environ.setdefault("COCKPIT_V4_WHATIF_CORPORATE", "1")
os.environ.setdefault("COCKPIT_V4_WHATIF_RETAIL", "1")

from backend.cockpit_v4 import domains as dom  # noqa: E402
from backend.cockpit_v4 import invariants, lake  # noqa: E402
from backend.cockpit_v4.scenario import candidate_schema as cs  # noqa: E402
from backend.cockpit_v4.scenario.generate import corporate, retail  # noqa: E402
from backend.cockpit_v4.scenario.sensitivity import build as sens  # noqa: E402

BUILDERS = {dom.CORPORATE: corporate.build, dom.RETAIL: retail.build}

#: The accepted releases and the fingerprints they must still have when this
#: script finishes. Read from the published manifests before the build, so a
#: run cannot pass by comparing a corrupted book with itself.
ACCEPTED = dict(dom.DEFAULT_RELEASES)


def accepted_fingerprints() -> dict[str, str]:
    return {release: lake.fingerprint(release)
            for release in ACCEPTED.values()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=["corporate", "retail", "all"],
                        default="all")
    parser.add_argument("--overwrite", action="store_true",
                        help="republish a candidate release that already "
                             "exists. Never touches an accepted release.")
    parser.add_argument("--evidence", default="",
                        help="write a JSON build record to this path.")
    args = parser.parse_args()

    before = accepted_fingerprints()
    print("accepted releases, before:")
    for release, digest in sorted(before.items()):
        print(f"  {release:34s} {digest[:16]}")

    domains = ([dom.CORPORATE, dom.RETAIL] if args.domain == "all"
               else [dom.parse(args.domain)])
    record: dict[str, object] = {
        "origin": cs.ORIGIN,
        "note": ("Generated for a demonstration. Not bank output, and the "
                 "macroeconomic paths are not observed economic history."),
        "releases": {},
    }

    for domain_id in domains:
        release_id = cs.RELEASES[domain_id]
        if release_id in ACCEPTED.values():  # pragma: no cover - impossible
            print(f"REFUSING: {release_id} is an accepted release id.")
            return 2
        started = time.time()
        print(f"\nbuilding {release_id} ...")
        # Model metrics, if `train_emulator.py` has produced any. A book
        # without them publishes the honest not-yet-trained row instead;
        # neither state is a zero.
        artifacts: dict[str, object] = {}
        metric_file = (ROOT / "artifacts" / "whatif" / domain_id
                       / "model_metric.json")
        if metric_file.exists():
            import pandas as pd

            body = json.loads(metric_file.read_text(encoding="utf-8"))
            artifacts[str(body["relation"])] = pd.DataFrame(body["rows"])
            print(f"  {len(body['rows'])} model-metric rows from "
                  f"{metric_file.relative_to(ROOT)}")
        build = BUILDERS[domain_id](release_id=release_id,
                                    artifacts=artifacts or None)
        # The fit reads the frames that are about to become parquet, in this
        # same process, so there is no window in which the published
        # sensitivity artifact could describe different numbers than the book
        # it is published inside. Section 7.1's precomputation happens here
        # and never in a chat turn.
        fitted = sens.attach(build, tenant_id=lake.DEFAULT_TENANT)
        print(f"  sensitivities: {len(fitted.rows)} rows, "
              f"{fitted.by_status()}, cohort {fitted.book.cohort_size:,}")
        findings = invariants.check(build)
        if findings:
            print(f"  {len(findings)} invariant finding(s); nothing "
                  f"published:")
            for finding in findings[:20]:
                print(f"    - {finding}")
            return 1
        manifest = lake.publish(build, overwrite=args.overwrite)
        elapsed = time.time() - started
        rows = sum(int(v) for v in manifest["row_counts"].values())
        print(f"  published {rows:,} rows in {len(manifest['row_counts'])} "
              f"relations in {elapsed:.0f}s")
        print(f"  fingerprint {manifest['release_fingerprint'][:16]}")
        record["releases"][release_id] = {
            "domain_id": domain_id,
            "release_fingerprint": manifest["release_fingerprint"],
            "reporting_periods": manifest["reporting_periods"],
            "row_counts": manifest["row_counts"],
            "entity_counts": manifest["entity_counts"],
            "notes": manifest["notes"],
            "build_seconds": round(elapsed, 1),
            "sensitivity_input_digest": fitted.digest,
            "sensitivity_rows": len(fitted.rows),
            "sensitivity_readiness": fitted.by_status(),
        }

    after = accepted_fingerprints()
    moved = {r: (before[r], after[r]) for r in before if before[r] != after[r]}
    print("\naccepted releases, after:")
    for release, digest in sorted(after.items()):
        mark = "CHANGED" if release in moved else "unchanged"
        print(f"  {release:34s} {digest[:16]}  {mark}")
    if moved:
        print("\nAn accepted release moved. That is a defect in this script, "
              "not an acceptable outcome; the candidate build must not touch "
              "the accepted books.")
        return 3
    record["accepted_unchanged"] = before

    if args.evidence:
        target = Path(args.evidence)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2, sort_keys=True),
                          encoding="utf-8")
        print(f"\nevidence written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
