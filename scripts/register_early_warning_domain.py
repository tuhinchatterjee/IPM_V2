#!/usr/bin/env python3
"""Reconcile the Early Warning domain's metadata with the data on disk.

When to run this
----------------
When the Early Warning data is present and the Data Builder still shows the
domain as empty or stale. That happens on an environment whose lake was
copied, restored or built by an older script that wrote parquet and
registered nothing -- the catalogue is a file, and a file can be older than
the data beside it.

A normal build does not need this: `scripts/build_early_warning_v2.py`
registers as its last step. This is the deterministic path for the
environments that were built before it did, and a safe no-op everywhere
else -- it rewrites the same definitions from the same governed dictionary,
so running it twice leaves the catalogue identical.

It publishes the SHAPE of the three datasets. Row counts and periods are
never written here; they are read from the lake on every request, so this
script cannot make the screen claim a number the data does not support. If
the lake is empty, the domain will still read as empty afterwards -- and it
should, because then it is.

    .venv/bin/python scripts/register_early_warning_domain.py
    .venv/bin/python scripts/register_early_warning_domain.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="Report whether the domain is registered, and change nothing. "
             "Exits 1 when it is not, so a deployment check can use it.")
    args = parser.parse_args()

    from backend.early_warning import registration as reg

    if args.check:
        ok = reg.registered()
        print(f"Early Warning registered in the catalogue: {ok}")
        return 0 if ok else 1

    before = reg.registered()
    result = reg.publish()
    print(f"> Catalogue: {result['catalog']}")
    print(f"> {'Re-registered' if before else 'Registered'}: "
          f"{', '.join(result['registered'])}")
    print(f"> Borrower-month fields: {result['borrower_month_fields']}")

    # Read the domain back through the one metadata reader every surface
    # uses, so the output of this script is what the screen will show.
    from backend import metadata as md

    domain = md.domain(reg.CATALOGUE_DOMAIN)
    if domain is None:
        print("! The domain map does not claim a heading named "
              f"{reg.CATALOGUE_DOMAIN!r}; the datasets are registered but "
              "unplaced. Check backend/services/data_domains.py.")
        return 1

    print(f"> {domain.name}: {len(domain.datasets)} datasets, "
          f"{domain.row_count:,} rows, {domain.field_count:,} fields, "
          f"{len(domain.periods)} periods")
    for name in domain.datasets:
        dataset = md.dataset(name)
        if dataset is None:
            continue
        span = (f"{dataset.periods[0]}..{dataset.periods[-1]}"
                if dataset.periods else "no published periods")
        print(f"    {name}: {dataset.row_count:,} rows, "
              f"{dataset.field_count:,} fields, {span}"
              f"{'' if dataset.readable else '  (NOT READABLE FROM THE LAKE)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
