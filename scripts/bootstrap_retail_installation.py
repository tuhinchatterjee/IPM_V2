#!/usr/bin/env python
"""
Bring the retail installation up to demo-ready, in one idempotent step.

    .venv/bin/python scripts/bootstrap_retail_installation.py

Registers the published retail book in Data Builder's governance tables so that
"Cockpit Data" and its twenty-five monthly members appear on screen, and marks
the retail dataset as authoritative for the retail governed purposes.

Guarded: it refuses any database or metadata target that is not the retail
installation's, so it cannot be pointed at a frozen source demo.

Idempotent. Run it as often as you like; it changes nothing that is already
correct, and it never invents a dataset the lake does not hold.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(message)s")
    log = logging.getLogger("bootstrap_retail")

    from backend.retail import guard
    from backend.config import settings

    guard.require_retail_directory(Path(settings.analytics_dir), what="bootstrap")
    guard.require_retail_directory(Path(settings.metadata_dir), what="bootstrap")
    guard.require_retail_database(os.environ.get("DATABASE_URL", ""), what="bootstrap")

    from backend.data_access.catalog import reload_catalog
    catalog = reload_catalog()
    if not catalog.names():
        from backend.retail.profile import missing_seed_error
        raise SystemExit(str(missing_seed_error()))

    log.info("Governed catalogue: %s", ", ".join(catalog.names()))

    from backend.db.engine import get_session
    from backend.services import governance

    with get_session() as session:
        result = governance.sync_bundled_catalog(session)
    log.info("Registered the bundled retail book in Data Builder: %s", result)

    from backend.services.data_builder import published_datasets
    with get_session() as session:
        published = [d.name for d in published_datasets(session)]
    log.info("Data Builder now publishes: %s", ", ".join(published) or "(none)")

    if "retail_facility_month" not in published:
        log.warning(
            "retail_facility_month is not published in Data Builder. The Cockpit will "
            "still answer from the governed catalogue, but the Data Builder screen "
            "will not list the domain."
        )
        return 1
    log.info("")
    log.info("The retail installation is bootstrapped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
