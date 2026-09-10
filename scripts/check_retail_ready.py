#!/usr/bin/env python
"""
Verify the retail installation is ready to demonstrate — without changing it.

    .venv/bin/python scripts/check_retail_ready.py

Read-only. It opens the published lake and the catalogue and checks the things
that would embarrass a demonstration if they were wrong: that there are exactly
twenty-five consecutive months, that the catalogue and the lake agree on the
dataset version, that the keys are unique, that the ECL identities reconcile,
that the scenario ordering holds, and that nothing corporate is in the active
catalogue.

Exit code 0 means every check passed. Anything else names what failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backend.retail.generate import PERIOD_FIELD  # noqa: E402

DATASET = "retail_facility_month"
DEFAULT_ANALYTICS = ROOT / "data" / "retail" / "analytics"
DEFAULT_METADATA = ROOT / "metadata" / "retail"

#: Tokens that must not appear in the active retail catalogue.
RETIRED_TOKENS = (
    "rating_grade", "master_scale", "customer_rating", "borrower_financials",
    "ebitda", "dscr", "covenant", "balance_sheet", "income_statement",
    "corporate", "obligor_group",
)


class Check:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.results if not r[1]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analytics-dir", type=Path, default=DEFAULT_ANALYTICS)
    ap.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    c = Check()
    dataset_dir = args.analytics_dir / DATASET
    manifest_path = args.metadata_dir / "retail_dataset_manifest.json"
    catalog_path = args.metadata_dir / "catalog.json"

    if not c.add("lake exists", dataset_dir.exists(), str(dataset_dir)):
        return _report(c, args.quiet)
    if not c.add("manifest exists", manifest_path.exists(), str(manifest_path)):
        return _report(c, args.quiet)
    if not c.add("catalogue exists", catalog_path.exists(), str(catalog_path)):
        return _report(c, args.quiet)

    manifest = json.loads(manifest_path.read_text())
    catalog = json.loads(catalog_path.read_text())

    months = sorted(p.name.split("=", 1)[1] for p in dataset_dir.glob(f"{PERIOD_FIELD}=*"))
    c.add("exactly 25 published months", len(months) == 25, f"found {len(months)}")
    c.add("months are consecutive", _consecutive(months), f"{months[0]}..{months[-1]}" if months else "")
    c.add("range is the pinned demo range",
          bool(months) and months[0] == "2024-08" and months[-1] == "2026-08",
          f"{months[0]}..{months[-1]}" if months else "")
    c.add("no future month beyond the pinned as-of",
          bool(months) and months[-1] == manifest["demo_as_of_month"],
          f"manifest says {manifest['demo_as_of_month']}")

    datasets = catalog.get("datasets", [])
    c.add("exactly one analytical dataset in the catalogue", len(datasets) == 1,
          f"found {len(datasets)}: {[d.get('name') for d in datasets]}")
    if datasets:
        entry = datasets[0]
        c.add("the single domain is 'Cockpit Data'", entry.get("domain") == "Cockpit Data",
              str(entry.get("domain")))
        c.add("catalogue and manifest agree on the dataset version",
              entry.get("version") == manifest["dataset_version"],
              f"{entry.get('version')} vs {manifest['dataset_version']}")
        c.add("catalogue lists 25 monthly members",
              len(catalog.get("monthly_members", [])) == 25,
              str(len(catalog.get("monthly_members", []))))

    blob = json.dumps(catalog).lower()
    found = sorted({t for t in RETIRED_TOKENS if t in blob})
    c.add("no retired corporate vocabulary in the active catalogue", not found, ", ".join(found))

    latest = pd.read_parquet(dataset_dir / f"{PERIOD_FIELD}={months[-1]}" / "data.parquet")
    c.add("primary key is unique",
          not latest[["snapshot_date", "customer_id", "facility_id"]].duplicated().any())
    c.add("facility key is unique within the snapshot",
          not latest["facility_id"].duplicated().any())

    weighted = (latest["scenario_weight_base"] * latest["ecl_base_sar"]
                + latest["scenario_weight_upturn"] * latest["ecl_upturn_sar"]
                + latest["scenario_weight_downturn"] * latest["ecl_downturn_sar"])
    worst = float((latest["ecl_weighted_sar"] - weighted).abs().max())
    c.add("weighted ECL identity reconciles", worst <= 0.02, f"max row error SAR {worst:.4f}")

    final_err = float((latest["ecl_final_sar"]
                       - (latest["ecl_weighted_sar"] + latest["management_overlay_sar"])).abs().max())
    c.add("final ECL identity reconciles", final_err <= 0.01, f"max row error SAR {final_err:.4f}")

    violations = int(((latest["ecl_upturn_sar"] > latest["ecl_base_sar"] + 0.01)
                      | (latest["ecl_base_sar"] > latest["ecl_downturn_sar"] + 0.01)).sum())
    c.add("scenario ordering holds row-wise", violations == 0, f"{violations} violations")

    numeric = latest.select_dtypes(include=[np.floating])
    infinite = int(np.isinf(numeric.to_numpy(dtype="float64", na_value=0.0)).sum())
    c.add("no infinities in the published numbers", infinite == 0, str(infinite))

    products = sorted(latest["product_code"].unique())
    c.add("all four retail product families present", len(products) == 4, ", ".join(products))

    c.add("the latest month has no matured 12-month outcome",
          not bool(latest["performance_window_complete_flag"].any()),
          "an outcome window that has not elapsed must not be marked complete")

    return _report(c, args.quiet, manifest, months, latest)


def _consecutive(months: list[str]) -> bool:
    idx = [int(m[:4]) * 12 + int(m[5:]) for m in months]
    return all(b - a == 1 for a, b in zip(idx, idx[1:]))


def _report(c: Check, quiet: bool, manifest=None, months=None, latest=None) -> int:
    if not quiet:
        print("Retail readiness")
        print("Synthetic Saudi retail demonstration data — not ANB customer data or approved models.")
        print()
        for name, ok, detail in c.results:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))
        if manifest is not None and latest is not None:
            print()
            print(f"  months            {months[0]} .. {months[-1]} ({len(months)})")
            print(f"  dataset version   {manifest['dataset_version']}")
            print(f"  manifest hash     {manifest['manifest_hash'][:16]}")
            print(f"  latest month      {len(latest):,} facilities, "
                  f"{latest['customer_id'].nunique():,} customers")
            print(f"  exposure          SAR {latest['gross_carrying_amount_sar'].sum():,.0f}")
            print(f"  loss allowance    SAR {latest['ecl_final_sar'].sum():,.0f}")
        print()
    if c.failed:
        if not quiet:
            print(f"{len(c.failed)} check(s) failed.")
        else:
            for name, _, detail in c.failed:
                print(f"FAIL: {name} — {detail}", file=sys.stderr)
        return 1
    if not quiet:
        print("All checks passed. The retail installation is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
