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
from dataclasses import dataclass, field
from enum import StrEnum
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
    unit: str | None = None  # e.g. "SAR mn", "%", "days", "x"
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


# Governed purposes — what a dataset is FOR, independent of what it is called.
#
# This is the join between Data Builder and the engine. An analysis needs "the
# credit facility position"; today that is served by the bundled demo dataset,
# and tomorrow by a client's own upload. Naming the purpose rather than the
# table is what lets the second replace the first without touching a
# calculation.
FACILITY_POSITION = "credit_facility_position"
BORROWER_FINANCIALS = "borrower_financials"
IFRS9_STAGING = "ifrs9_impairment_staging"
CUSTOMER_RATING_HISTORY = "customer_rating_history"
MACROECONOMIC_SERIES = "macroeconomic_series"
FACILITY_DELINQUENCY = "facility_delinquency"
CREDIT_FILE_COMMENTARY = "credit_file_commentary"
#: Borrower 360 purposes. B44. Separate constants rather than reusing the
#: credit-book ones, because a corporate group structure is not a facility
#: position and an analysis that asked for one and got the other would be
#: answering a different question with a straight face.
CORPORATE_CONNECTED_GROUP = "corporate_connected_group"
CORPORATE_GRAPH_QUALITY = "corporate_graph_quality"
# There is deliberately no purpose for the Borrower 360 snapshot. B2: the
# snapshot is a fast denormalised READ and is authoritative for nothing, so a
# purpose naming it would be a purpose no dataset can honestly serve.

GOVERNED_PURPOSES: dict[str, str] = {
    FACILITY_POSITION: (
        "The position of every credit facility at a reporting date: exposure, "
        "limits, collateral, rating, IFRS 9 staging, PD, LGD and ECL."
    ),
    BORROWER_FINANCIALS: (
        "Borrower-level financial statements and derived credit ratios."
    ),
    IFRS9_STAGING: (
        "The staging decision behind every facility: the PD at origination it is "
        "measured against, each significant-increase trigger separately, the "
        "stage before and after, and the resulting expected credit loss."
    ),
    CUSTOMER_RATING_HISTORY: (
        "Annual rating cycles per customer: the internal grade awarded, the "
        "financials behind it, and the action taken against the previous year."
    ),
    MACROECONOMIC_SERIES: (
        "Quarterly macroeconomic series for the economy the book lends into, "
        "and the credit cycle factor derived from them."
    ),
    FACILITY_DELINQUENCY: (
        "Arrears and collections per facility: days past due, the arrears "
        "bucket, the amount overdue, forbearance granted, and how far recovery "
        "action has escalated."
    ),
    CREDIT_FILE_COMMENTARY: (
        "What the credit file says, as structured signals: covenant breaches, "
        "liquidity concerns, management changes, sector headwinds and "
        "going-concern language, with the extract that raised each one."
    ),
    CORPORATE_CONNECTED_GROUP: (
        "The derived corporate relationship graph, per borrower per quarter: "
        "its effective-ownership group, its control group, its connected "
        "counterparty candidate group, the counts of the relationships "
        "around it, and the five network measures over them."
    ),
    CORPORATE_GRAPH_QUALITY: (
        "The graph data-quality register: which checks ran for a quarter, "
        "what each observed, and which derived computations a REJECT "
        "blocked."
    ),
}


#: Which book a dataset describes. B44.
#:
#: Two portfolios now live in one catalogue, and they share almost every word:
#: both have customers, exposure at default, an IFRS 9 stage and a covenant.
#: Without a scope, a question about "the largest customers by exposure" has
#: two equally good answers and the retriever picks by string overlap - which
#: is how twenty new corporate datasets pushed the facility book out of the
#: top eight and turned a working question into "which figure should
#: CreditProbe measure?".
#:
#: The default scope is the credit book the product has always been about. The
#: Borrower 360 scope is reached when a question names something only that
#: module has - a group structure, an ultimate beneficial owner, a connected
#: counterparty, a supply chain, a relationship graph.
CREDIT_BOOK_SCOPE = "CREDIT_BOOK"
BORROWER_360_SCOPE = "BORROWER_360"

PORTFOLIO_SCOPES: tuple[str, ...] = (CREDIT_BOOK_SCOPE, BORROWER_360_SCOPE)


class DatasetOrigin(StrEnum):
    """Where a dataset came from, and therefore how much it may be trusted.

    DEMO is the bundled synthetic book CreditProbe ships with so the product can be seen
    working. It is never allowed to stand in for client data once a client
    dataset has been made authoritative for the same purpose.
    """

    DEMO = "demo"                # bundled bootstrap data
    CLIENT = "client"            # onboarded through Data Builder
    SUPPLEMENTARY = "supplementary"  # reference data, not a source of truth


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

    # ---- governance ---------------------------------------------------------
    # Where the data came from. Drives the DEMO label in Data Builder and the
    # refusal to fall back to demo data once client data exists.
    origin: str = DatasetOrigin.DEMO

    # Repeated snapshots of the same logical dataset share a family, and a
    # family shares one canonical schema. "portfolio_facility" is the family
    # for every quarterly facility file.
    dataset_family: str = ""

    # The governed purposes this dataset is the authoritative source for. Empty
    # means it may be read directly by name but never resolved as the answer to
    # "give me the facility position".
    authoritative_for: list[str] = field(default_factory=list)

    # Which book this dataset describes. Defaults to the credit book, so an
    # existing entry that says nothing keeps the behaviour it had.
    portfolio_scope: str = CREDIT_BOOK_SCOPE

    @property
    def is_demo(self) -> bool:
        return self.origin == DatasetOrigin.DEMO

    @property
    def family(self) -> str:
        return self.dataset_family or self.name

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
            "origin": self.origin,
            "is_demo": self.is_demo,
            "dataset_family": self.family,
            "authoritative_for": list(self.authoritative_for),
            "portfolio_scope": self.portfolio_scope,
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

    def serving(self, purpose: str) -> list[DatasetDef]:
        """Every dataset declared authoritative for a governed purpose."""
        return [d for d in self.all() if purpose in d.authoritative_for]

    def families(self) -> dict[str, list[DatasetDef]]:
        out: dict[str, list[DatasetDef]] = {}
        for d in self.all():
            out.setdefault(d.family, []).append(d)
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
                origin=raw.get("origin",
                               DatasetOrigin.DEMO if raw.get("is_synthetic")
                               else DatasetOrigin.CLIENT),
                dataset_family=raw.get("dataset_family", ""),
                authoritative_for=list(raw.get("authoritative_for") or []),
                portfolio_scope=raw.get("portfolio_scope",
                                        CREDIT_BOOK_SCOPE),
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
