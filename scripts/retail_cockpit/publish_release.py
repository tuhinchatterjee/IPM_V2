#!/usr/bin/env python3
"""Project the published Cockpit Data domain into a release the Cockpit reads.

    .venv/bin/python scripts/retail_cockpit/publish_release.py
    .venv/bin/python scripts/retail_cockpit/publish_release.py --verify

Reads the retail installation's own lake and catalogue, READ-ONLY, and writes
one immutable release into the candidate Cockpit lake. It publishes nothing
back to the retail domain, re-versions nothing, and refuses to overwrite a
release that already exists.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from backend.retail import scorecards, taxonomy
    from backend.retail_cockpit_adapter import gates
    from backend.retail_cockpit_adapter import publish as pub
    from backend.retail_cockpit_adapter.source import open_snapshot

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analytics-dir", type=Path,
                    default=ROOT / "data" / "retail" / "analytics",
                    help="the retail lake to READ")
    ap.add_argument("--metadata-dir", type=Path,
                    default=ROOT / "metadata" / "retail",
                    help="the retail catalogue to READ")
    ap.add_argument("--lake", type=Path, default=None,
                    help="the Cockpit lake to WRITE (default: the V4 lake "
                         "this runtime is configured for)")
    ap.add_argument("--tenant", default=pub.DEFAULT_TENANT)
    # Revision 5. `p1` is the millions-only release kept as failed
    # evidence; `p2` and `p3` were superseded candidate builds and `p4` is
    # the one the memory benchmark ran against. A revision number is never
    # reused, on any machine, so a release id always names one set of bytes.
    ap.add_argument("--revision", type=int, default=5)
    ap.add_argument("--overwrite", action="store_true",
                    help="rewrite a published release. Deliberate only.")
    ap.add_argument("--verify", action="store_true",
                    help="check published bytes against their fingerprint")
    args = ap.parse_args()

    snapshot = open_snapshot(args.analytics_dir, args.metadata_dir)
    lake_root = args.lake
    if lake_root is None:
        from backend.cockpit_v4 import lake as lake_mod

        lake_root = lake_mod.root()
    release_id = pub.release_id_for(snapshot, revision=args.revision)

    if args.verify:
        import json

        from backend.retail_cockpit_adapter.publish import MANIFEST, digest

        directory = Path(lake_root) / release_id
        manifest_path = directory / MANIFEST
        if not manifest_path.exists():
            print(f"  {release_id}  NOT PUBLISHED at {directory}")
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = str(manifest.get("release_fingerprint") or "")
        actual = digest(sorted(directory.glob("*.parquet")))
        ok = recorded == actual
        print(f"  {release_id}  "
              f"{'verified' if ok else 'FINGERPRINT MISMATCH'}  "
              f"{recorded[:16]}")
        lineage = manifest.get("notes", {}).get("projected_from", {})
        print(f"             projected from {lineage.get('dataset')} "
              f"{lineage.get('dataset_version')} "
              f"manifest {str(lineage.get('manifest_hash'))[:16]}")
        return 0 if ok else 1

    governed = {"score_bands": scorecards.SCORE_BAND_LABELS,
                "products": tuple(taxonomy.PRODUCT_LABELS.values())}

    def gate(projected, month) -> None:
        findings = gates.check_month(
            projected, month, tenant_id=args.tenant, release_id=release_id,
            domain_id=pub.ENGINE_DOMAIN, currency=snapshot.currency,
            governed=governed)
        # Read the source a second time and reconcile the riyal totals to
        # it. The projection is not trusted to report on itself.
        findings += gates.check_source_totals(snapshot, projected, month)
        if findings:
            raise gates.GatesFailed(findings)

    def report(month, projected) -> None:
        print(f"  {month.reporting_month}  {projected.source_rows:,} "
              f"facility rows projected")

    print(f"Projecting {snapshot.manifest['dataset_name']} "
          f"{snapshot.dataset_version}")
    print(f"  from      {args.analytics_dir}")
    print(f"  into      {Path(lake_root) / release_id}")
    print(f"  months    {len(snapshot.months)} "
          f"({snapshot.periods[0]} .. {snapshot.latest_period})")
    try:
        published = pub.publish(snapshot, lake_root=Path(lake_root),
                                tenant_id=args.tenant,
                                revision=args.revision,
                                overwrite=args.overwrite, gate=gate,
                                on_month=report)
    except gates.GatesFailed as exc:
        print("  REFUSING to publish: the projection failed its own gates.")
        for finding in exc.findings[:12]:
            print(f"    - {finding}")
        return 1
    except pub.PublishRefused as exc:
        print(f"  {exc}")
        return 1

    manifest = published.manifest
    rows = sum(manifest["row_counts"].values())
    print(f"  published {published.release_id}")
    print(f"             {len(manifest['reporting_periods'])} months "
          f"{manifest['reporting_periods'][0]}.."
          f"{manifest['latest_period']}")
    print(f"             {len(manifest['relations'])} relations, {rows:,} "
          f"rows, "
          f"{sum(len(r['fields']) for r in manifest['relations'])} fields")
    for relation, count in sorted(manifest["row_counts"].items()):
        print(f"               {relation:26s} {count:9,d}")
    print(f"             {manifest['geography_name']} · "
          f"{manifest['reporting_currency']} {manifest['amount_scale']} · "
          f"{manifest['reporting_frequency']}")
    print(f"             fingerprint {published.fingerprint[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
