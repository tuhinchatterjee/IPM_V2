"""
Read-only access to the retail installation's published Cockpit Data domain.

Read-only is enforced, not promised
-----------------------------------
Every path this module opens is opened for reading, and the one write path in
the adapter (`publish.py`) refuses any target outside the candidate's own
runtime directory. The retail lake and the retail catalogue are inputs here
and nothing else: this integration does not republish, reseed, migrate or
re-version the domain it reads.

What identifies a snapshot
--------------------------
`dataset_version` names the build, `manifest_hash` names the manifest's own
bytes, and each month carries a `content_hash` over its business content. All
three are carried into the published release's lineage, so an answer can be
traced back to the exact bytes it was computed from -- and so a rebuild of
the retail book is visible as a different release rather than as the same one
holding different numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

#: The one dataset the Cockpit Data domain publishes.
DATASET = "retail_facility_month"

#: The domain as the retail Data Builder names it, and its id.
DOMAIN_DISPLAY = "Cockpit Data"
DOMAIN_ID = "retail_cockpit"

#: The column the lake is partitioned by, and the period column of the book.
PERIOD_FIELD = "reporting_month"

MANIFEST_FILENAME = "retail_dataset_manifest.json"
CONTRACT_FILENAME = "retail_data_contract.json"
CATALOG_FILENAME = "catalog.json"


class SnapshotUnavailable(RuntimeError):
    """The published domain could not be read. Said, never substituted."""


@dataclass(frozen=True)
class Month:
    """One published month-end, and what the publisher recorded about it."""

    reporting_month: str
    snapshot_date: str
    rows: int
    distinct_customers: int
    distinct_facilities: int
    products: tuple[str, ...]
    content_hash: str
    validation_status: str
    path: Path

    @property
    def passed(self) -> bool:
        return self.validation_status.upper() == "PASSED"


@dataclass(frozen=True)
class Snapshot:
    """The published Cockpit Data domain, as it stands on disk."""

    analytics_dir: Path
    metadata_dir: Path
    manifest: dict[str, Any]

    # -- identity --------------------------------------------------------

    @property
    def dataset_version(self) -> str:
        return str(self.manifest["dataset_version"])

    @property
    def manifest_hash(self) -> str:
        return str(self.manifest["manifest_hash"])

    @property
    def generator_version(self) -> str:
        return str(self.manifest["generator_version"])

    @property
    def currency(self) -> str:
        return str(self.manifest["currency"])

    @property
    def country(self) -> str:
        return str(self.manifest["portfolio_country"])

    @property
    def scenario(self) -> dict[str, Any]:
        return {"scenario_set_id": self.manifest.get("scenario_set_id"),
                "scenario_set_version": self.manifest.get(
                    "scenario_set_version"),
                "scenario_weights": self.manifest.get("scenario_weights")}

    # -- what is in it ---------------------------------------------------

    @cached_property
    def months(self) -> tuple[Month, ...]:
        out: list[Month] = []
        for entry in self.manifest.get("months") or ():
            month = str(entry["reporting_month"])
            out.append(Month(
                reporting_month=month,
                snapshot_date=str(entry["snapshot_date"]),
                rows=int(entry["rows"]),
                distinct_customers=int(entry["distinct_customers"]),
                distinct_facilities=int(entry["distinct_facilities"]),
                products=tuple(str(p) for p in (entry.get("products") or ())),
                content_hash=str(entry.get("content_hash") or ""),
                validation_status=str(entry.get("validation_status") or ""),
                path=self.part_path(month)))
        return tuple(out)

    @property
    def periods(self) -> tuple[str, ...]:
        return tuple(m.reporting_month for m in self.months)

    @property
    def latest_period(self) -> str:
        return self.periods[-1] if self.periods else ""

    def part_path(self, reporting_month: str) -> Path:
        return (self.analytics_dir / DATASET
                / f"{PERIOD_FIELD}={reporting_month}" / "data.parquet")

    @cached_property
    def contract(self) -> dict[str, Any]:
        """The governed field dictionary, as the retail build published it."""
        path = self.metadata_dir / CONTRACT_FILENAME
        if not path.exists():
            raise SnapshotUnavailable(
                f"The Cockpit Data contract is not published at {path}. "
                f"Nothing was substituted for it.")
        return json.loads(path.read_text(encoding="utf-8"))

    @cached_property
    def columns(self) -> dict[str, dict[str, Any]]:
        """Every governed column, by name, with its declared metadata."""
        return {str(c["name"]): c for c in (self.contract.get("columns") or ())}

    def column(self, name: str) -> dict[str, Any]:
        try:
            return self.columns[name]
        except KeyError as exc:
            raise SnapshotUnavailable(
                f"{name!r} is not a governed column of {DATASET}. The "
                f"adapter maps only columns this snapshot actually "
                f"publishes.") from exc

    # -- reading ---------------------------------------------------------

    def read_month(self, reporting_month: str,
                   columns: list[str] | None = None) -> Any:
        """One month, projected to the columns asked for. Read-only."""
        import pandas as pd

        path = self.part_path(reporting_month)
        if not path.exists():
            raise SnapshotUnavailable(
                f"{reporting_month} is named by the manifest and is not "
                f"published at {path}.")
        return pd.read_parquet(path, columns=columns)

    def verify(self) -> list[str]:
        """Findings about the snapshot itself. Empty means it is readable."""
        findings: list[str] = []
        if not self.months:
            findings.append("the manifest publishes no months")
        for month in self.months:
            if not month.path.exists():
                findings.append(
                    f"{month.reporting_month}: named by the manifest, absent "
                    f"from the lake at {month.path}")
            if not month.passed:
                findings.append(
                    f"{month.reporting_month}: validation_status is "
                    f"{month.validation_status!r}, not PASSED")
        recorded = sum(m.rows for m in self.months)
        declared = int(self.manifest.get("total_rows") or 0)
        if recorded != declared:
            findings.append(
                f"the months sum to {recorded:,} rows and the manifest "
                f"declares {declared:,}")
        return findings


def open_snapshot(analytics_dir: Path | str,
                  metadata_dir: Path | str) -> Snapshot:
    """Open the published domain. Refuses rather than guessing."""
    analytics_dir = Path(analytics_dir)
    metadata_dir = Path(metadata_dir)
    manifest_path = metadata_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise SnapshotUnavailable(
            f"The Cockpit Data manifest is not published at {manifest_path}. "
            f"This runtime has no retail book to read, and nothing was "
            f"substituted for one.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    published = str(manifest.get("dataset_name") or "")
    if published != DATASET:
        raise SnapshotUnavailable(
            f"{manifest_path} describes {published!r}, not {DATASET!r}. The "
            f"adapter reads the Cockpit Data domain and no other.")
    return Snapshot(analytics_dir=analytics_dir, metadata_dir=metadata_dir,
                    manifest=manifest)


__all__ = ["CATALOG_FILENAME", "CONTRACT_FILENAME", "DATASET",
           "DOMAIN_DISPLAY", "DOMAIN_ID", "MANIFEST_FILENAME", "Month",
           "PERIOD_FIELD", "Snapshot", "SnapshotUnavailable", "open_snapshot"]
