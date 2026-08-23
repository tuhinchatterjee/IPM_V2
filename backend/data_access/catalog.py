"""
The dataset catalogue — governed names to physical storage.

The engine asks for `portfolio_facility.ead`. The catalogue knows that today
this means the `ead` column of the Parquet files under
`data/analytics/portfolio_facility/`, and that it originated as the
"CCF-Adjusted EAD (USD mn)" column of the source workbook.

Holding that mapping here rather than inside the engine is what lets the physical
layout change without touching a calculation, and it is what Data Builder will
edit in Phase 5. For now the catalogue is loaded from a JSON file in `metadata/`;
in Phase 5 that same structure moves into PostgreSQL so it can be governed,
versioned and edited through the UI. The shape stays the same, so nothing above
the catalogue has to change when it does.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.data_access.protocol import UnknownDatasetError, UnknownFieldError

logger = logging.getLogger(__name__)

CATALOG_FILENAME = "catalog.json"


@dataclass(frozen=True)
class FieldDef:
    """One governed field. This is the Data Dictionary entry for a column."""

    name: str  # governed name, e.g. "ead"
    source_column: str  # column in the source data, e.g. "CCF-Adjusted EAD (USD mn)"
    business_name: str  # what a risk officer calls it, e.g. "Exposure at Default"
    definition: str  # what it means, in reviewable English
    data_type: str  # string | integer | number | boolean | date
    unit: str | None = None  # e.g. "USD mn", "%", "days", "x"
    allowed_values: list[str] | None = None
    sensitivity: str = "internal"  # public | internal | confidential | restricted
    nullable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_column": self.source_column,
            "business_name": self.business_name,
            "definition": self.definition,
            "data_type": self.data_type,
            "unit": self.unit,
            "allowed_values": self.allowed_values,
            "sensitivity": self.sensitivity,
            "nullable": self.nullable,
        }


@dataclass(frozen=True)
class DatasetDef:
    """One governed dataset."""

    name: str  # governed name, e.g. "portfolio_facility"
    domain: str  # Data Builder domain, e.g. "Core Portfolio / Facility"
    business_name: str
    purpose: str
    grain: str  # what one row represents — the most-misunderstood property of a table
    primary_keys: list[str]
    period_field: str  # the field carrying the reporting period
    fields: dict[str, FieldDef]
    owner: str = "Credit Risk Analytics"
    status: str = "active"
    version: str = "1.0.0"
    is_synthetic: bool = False  # surfaced in the UI wherever its figures appear

    def field(self, name: str) -> FieldDef:
        try:
            return self.fields[name]
        except KeyError:
            raise UnknownFieldError(
                f"'{name}' is not a field of dataset '{self.name}'. "
                f"Available: {', '.join(sorted(self.fields))}"
            ) from None

    def source_column(self, name: str) -> str:
        return self.field(name).source_column

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "business_name": self.business_name,
            "purpose": self.purpose,
            "grain": self.grain,
            "primary_keys": self.primary_keys,
            "period_field": self.period_field,
            "owner": self.owner,
            "status": self.status,
            "version": self.version,
            "is_synthetic": self.is_synthetic,
            "field_count": len(self.fields),
            "fields": [f.to_dict() for f in self.fields.values()],
        }


class Catalog:
    """All governed datasets, keyed by governed name."""

    def __init__(self, datasets: dict[str, DatasetDef]):
        self._datasets = datasets

    def __len__(self) -> int:
        return len(self._datasets)

    def names(self) -> list[str]:
        return sorted(self._datasets)

    def all(self) -> list[DatasetDef]:
        return [self._datasets[n] for n in self.names()]

    def dataset(self, name: str) -> DatasetDef:
        try:
            return self._datasets[name]
        except KeyError:
            raise UnknownDatasetError(
                f"'{name}' is not a governed dataset. "
                f"Available: {', '.join(self.names()) or '(none — has the data lake been built?)'}"
            ) from None

    def domains(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for d in self.all():
            out.setdefault(d.domain, []).append(d.name)
        return out

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Catalog:
        datasets: dict[str, DatasetDef] = {}
        for raw in payload.get("datasets", []):
            fields = {
                f["name"]: FieldDef(
                    name=f["name"],
                    source_column=f["source_column"],
                    business_name=f.get("business_name", f["name"]),
                    definition=f.get("definition", ""),
                    data_type=f.get("data_type", "string"),
                    unit=f.get("unit"),
                    allowed_values=f.get("allowed_values"),
                    sensitivity=f.get("sensitivity", "internal"),
                    nullable=f.get("nullable", True),
                )
                for f in raw.get("fields", [])
            }
            datasets[raw["name"]] = DatasetDef(
                name=raw["name"],
                domain=raw.get("domain", "Uncategorised"),
                business_name=raw.get("business_name", raw["name"]),
                purpose=raw.get("purpose", ""),
                grain=raw.get("grain", ""),
                primary_keys=raw.get("primary_keys", []),
                period_field=raw.get("period_field", "period"),
                fields=fields,
                owner=raw.get("owner", "Credit Risk Analytics"),
                status=raw.get("status", "active"),
                version=raw.get("version", "1.0.0"),
                is_synthetic=raw.get("is_synthetic", False),
            )
        return cls(datasets)

    @classmethod
    def load(cls, path: Path | None = None) -> Catalog:
        """The governed catalogue: bundled datasets plus every PUBLISHED one.

        Two sources, one shape:

          * `metadata/catalog.json` — written by scripts/build_data_lake.py. These
            are the bundled datasets; that development path keeps working.
          * PostgreSQL — datasets a steward onboarded through Data Builder and
            published. **Only `published` ones appear here**, which is what stops
            a draft or half-mapped dataset from ever reaching an analysis.

        Database entries win on a name clash, because a steward republishing a
        dataset is a deliberate act and should take effect.
        """
        datasets: dict[str, DatasetDef] = {}

        p = path or (settings.metadata_dir / CATALOG_FILENAME)
        if p.exists():
            datasets.update(cls.from_dict(json.loads(p.read_text()))._datasets)

        for entry in _published_entries_from_db():
            datasets.update(cls.from_dict({"datasets": [entry]})._datasets)

        # An empty catalogue is a valid state before anything is built. The
        # /health endpoint reports it; nothing crashes.
        return cls(datasets)


def _published_entries_from_db() -> list[dict[str, Any]]:
    """Catalogue entries for datasets published through Data Builder.

    Deliberately defensive: the Data Access Layer must keep working with no
    database configured at all (the test suite runs that way, and so does a first
    boot before `docker compose up`). A database problem degrades the catalogue to
    the bundled datasets rather than breaking every analysis.
    """
    if not settings.has_database:
        return []
    try:
        from backend.db.engine import get_session
        from backend.services.data_builder import dataset_catalog_entry, published_datasets

        with get_session() as session:
            return [dataset_catalog_entry(session, d) for d in published_datasets(session)]
    except Exception as e:
        logger.warning("Could not read published datasets from PostgreSQL: %s", e)
        return []


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """The process-wide catalogue. Cached because it is read on every request."""
    return Catalog.load()


def reload_catalog() -> Catalog:
    """Drop the cache and re-read from disk — used after the lake is rebuilt."""
    get_catalog.cache_clear()
    return get_catalog()
