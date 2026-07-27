"""
One-time seed: load the bundled portfolio workbook into Postgres as the initial
`active` dataset version. Idempotent — if an active version already exists, it does
nothing, so it is safe to re-run.

Usage (from the project root):
    python scripts/migrate_xlsx_to_pg.py
"""

import sys
from pathlib import Path

# Allow running as a plain script: put the project root on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import logging  # noqa: E402

from backend import data_loader as dl  # noqa: E402
from backend.logging_setup import init_logging  # noqa: E402
from backend.services import data_store  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    init_logging()
    existing = data_store.get_active_version_id()
    if existing is not None:
        logger.info("An active dataset version (%s) already exists — nothing to seed.", existing)
        print(f"Already seeded (active version {existing}). No action taken.")
        return 0

    path = dl.DATA_PATH
    content = path.read_bytes()
    logger.info("Seeding bundled workbook %s (%.1f MB) into Postgres", path.name, len(content) / 1024 / 1024)

    report = dl.validate_workbook_bytes(content)
    if not report["ok"]:
        failed = [c for c in report["checks"] if c["status"] == "fail"]
        logger.error("Bundled workbook failed validation: %s", failed)
        print("ERROR: bundled workbook failed validation; not seeded.")
        return 1

    sheets, quarter_sheets = data_store.read_workbook_sheets(path)
    version_id = data_store.create_version(
        sheets, quarter_sheets,
        source_filename=path.name, origin="bundled",
        validation_report=report, status="active",
        file_sha256=data_store.sha256_bytes(content), uploaded_by=None,
    )
    total_rows = sum(len(df) for df in sheets.values())
    print(f"Seeded active dataset version {version_id}: "
          f"{len(quarter_sheets)} quarters, {total_rows:,} rows across {len(sheets)} sheets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
