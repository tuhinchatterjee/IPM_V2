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
    ap.add_argument(
        "--check", action="store_true",
        help="Report what a retail installation is still missing, and change "
             "nothing. Exit 0 when it is ready to demonstrate.")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(message)s")
    log = logging.getLogger("bootstrap_retail")

    from backend.retail import guard
    from backend.config import settings

    guard.require_retail_directory(Path(settings.analytics_dir), what="bootstrap")
    guard.require_retail_directory(Path(settings.metadata_dir), what="bootstrap")
    guard.require_retail_database(os.environ.get("DATABASE_URL", ""), what="bootstrap")

    if args.check:
        return _check(log)

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

    # The workspace. Publishing the book leaves a fresh retail database with
    # no projects, no data-release notifications and no working messages, so
    # the first thing a Head of Retail Risk sees on three screens is an empty
    # state. Seeded through the same services the product writes through, and
    # idempotent: a re-run keeps what is already there.
    from backend.retail import workspace_seed

    with get_session() as session:
        seeded = workspace_seed.seed(session)
        session.commit()
    log.info("Retail workspace: %s", seeded.summary())
    for note in seeded.notes:
        log.warning("  %s", note)

    if "retail_facility_month" not in published:
        log.warning(
            "retail_facility_month is not published in Data Builder. The Cockpit will "
            "still answer from the governed catalogue, but the Data Builder screen "
            "will not list the domain."
        )
        return 1
    with get_session() as session:
        missing = workspace_seed.check(session)
    if missing:
        for item in missing:
            log.warning("Still missing: %s", item)
        return 1

    log.info("")
    log.info("The retail installation is bootstrapped.")
    return 0


def _check(log) -> int:
    """What this installation is still missing, without changing anything.

    A readiness check that runs the seeder would always report ready, which is
    the one answer it must never be able to give by accident. This reads, and
    says what it found.
    """
    from backend.data_access.catalog import reload_catalog
    from backend.db.engine import get_session
    from backend.retail import workspace_seed
    from backend.services.data_builder import published_datasets

    problems: list[str] = []
    catalog = reload_catalog()
    if "retail_facility_month" not in catalog.names():
        problems.append("the governed catalogue does not hold "
                        "retail_facility_month")
    with get_session() as session:
        published = [d.name for d in published_datasets(session)]
        problems.extend(workspace_seed.check(session))
    if "retail_facility_month" not in published:
        problems.append("Data Builder does not publish retail_facility_month")

    for item in problems:
        log.warning("Still missing: %s", item)
    if problems:
        log.warning("")
        log.warning("Run this script without --check to seed what is missing.")
        return 1
    log.info("The retail installation is ready to demonstrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
