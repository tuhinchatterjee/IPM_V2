"""
Registering the retail book in the governed catalogue.

ONE entry. `retail_facility_month`, in the Data Builder domain "Cockpit Data",
partitioned into twenty-five monthly members. Not twenty-five datasets, not one
domain per module, and nothing corporate alongside it.

The catalogue is WRITTEN, not merged. A retail installation that merged into an
existing catalogue would inherit the corporate datasets it exists to be free of,
and the first question about "the largest customers by exposure" would have two
answers again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from backend.retail import DOMAIN_DISPLAY, SYNTHETIC_DISCLOSURE
from backend.retail.generate import PERIOD_FIELD
from backend.retail.schema import build_dictionary, data_contract

CATALOG_FILENAME = "catalog.json"
MANIFEST_FILENAME = "retail_dataset_manifest.json"
CONTRACT_FILENAME = "retail_data_contract.json"

DATASET_NAME = "retail_facility_month"

#: Governed purposes the retail book is authoritative for. The corporate
#: purposes — company financials, rating history, the relationship graph — are
#: deliberately absent: nothing in this installation serves them, and a question
#: that needs one gets a retail-only scope error rather than a wrong answer.
RETAIL_PURPOSES: dict[str, str] = {
    "credit_facility_position": (
        "The position of every retail facility at a month-end: exposure, limits, "
        "collateral, IFRS 9 staging, PD, LGD and ECL."
    ),
    "ifrs9_impairment_staging": (
        "The staging decision behind every retail facility: the origination PD "
        "reference it is measured against, each significant-increase trigger "
        "separately, the stage before and after, and the resulting ECL."
    ),
    "facility_delinquency": (
        "Arrears and collections per retail facility: days past due, the bucket, "
        "the amount overdue, forbearance granted and collections escalation."
    ),
    "retail_customer_affordability": (
        "Verified income, household expenses, credit obligations, disposable "
        "income and debt burden for the natural person behind each facility."
    ),
    "retail_scorecard_inputs": (
        "Every configured application and behavioural model input, raw and "
        "transformed, with the bin, the missing flag and the points."
    ),
    "retail_early_warning_signals": (
        "Salary continuity, personal account buffer, utilisation, bureau "
        "deterioration and repayment behaviour, month by month."
    ),
}

AUTHORITATIVE_FOR = tuple(RETAIL_PURPOSES)


def catalog_entry(columns: Iterable[str], manifest: dict[str, Any]) -> dict[str, Any]:
    specs = build_dictionary(columns)
    return {
        "name": DATASET_NAME,
        "domain": DOMAIN_DISPLAY,
        "business_name": "Retail facility month-end position",
        "purpose": (
            "The joined Saudi retail book at each month-end: customer, employment "
            "and affordability, facility terms and balances, delinquency and "
            "collections, salary and bureau signals, both scorecards with every "
            "configured input raw and transformed, and retail IFRS 9 staging, PD, "
            "LGD, EAD and scenario ECL."
        ),
        "grain": "One retail customer's ONE facility at ONE month-end.",
        "primary_keys": ["snapshot_date", "customer_id", "facility_id"],
        "period_field": PERIOD_FIELD,
        "owner": "Retail Credit Risk Analytics",
        "status": "active",
        "version": manifest["dataset_version"],
        "is_synthetic": True,
        "origin": "demo",
        "dataset_family": DATASET_NAME,
        "authoritative_for": list(AUTHORITATIVE_FOR),
        "portfolio_scope": "RETAIL_BOOK",
        "fields": [
            {
                "name": s.name,
                "source_column": s.name,
                "business_name": s.business_name,
                "definition": s.definition,
                "data_type": s.data_type,
                "unit": s.unit,
                "allowed_values": list(s.allowed_values) if s.allowed_values else None,
                "sensitivity": s.sensitivity,
                "nullable": s.nullable,
            }
            for s in specs
        ],
    }


def write_catalog(
    metadata_dir: Path, columns: Iterable[str], manifest: dict[str, Any],
) -> dict[str, Path]:
    """Write the retail catalogue, manifest and data contract. Replaces, never merges."""
    metadata_dir = Path(metadata_dir)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    columns = list(columns)

    catalog = {
        "generated_by": "scripts/build_retail_demo.py",
        "product": "CreditProbe — Saudi retail only",
        "disclosure": SYNTHETIC_DISCLOSURE,
        "governed_purposes": RETAIL_PURPOSES,
        "datasets": [catalog_entry(columns, manifest)],
        "relationships": [
            {
                "from": f"{DATASET_NAME}.customer_id",
                "to": f"{DATASET_NAME}.customer_id",
                "kind": "customer_to_facility",
                "note": (
                    "A customer may hold several facilities in the same month. "
                    "Customer-level values are repeated on each of their rows and "
                    "must be de-duplicated before they are summed."
                ),
            }
        ],
        "monthly_members": [
            {
                "reporting_month": m["reporting_month"],
                "snapshot_date": m["snapshot_date"],
                "rows": m["rows"],
                "distinct_customers": m["distinct_customers"],
                "distinct_facilities": m["distinct_facilities"],
                "products": m["products"],
                "schema_version": manifest["dataset_version"],
                "is_synthetic": True,
                "validation_status": m["validation_status"],
                "content_hash": m["content_hash"],
            }
            for m in manifest["months"]
        ],
    }

    paths = {
        "catalog": metadata_dir / CATALOG_FILENAME,
        "manifest": metadata_dir / MANIFEST_FILENAME,
        "contract": metadata_dir / CONTRACT_FILENAME,
    }
    paths["catalog"].write_text(json.dumps(catalog, indent=2, default=str))
    paths["manifest"].write_text(json.dumps(manifest, indent=2, default=str))
    paths["contract"].write_text(json.dumps(data_contract(columns), indent=2, default=str))
    return paths
