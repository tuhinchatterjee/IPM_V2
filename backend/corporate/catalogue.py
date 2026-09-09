"""Registering the corporate datasets in the governed catalogue. B3, B5.

Same job the retail scorecard's catalogue module does, for a bigger surface:
turn the twenty physical datasets into first-class Data Builder objects with
field definitions, declared grain, an owning domain and declared
relationships, and merge them into `metadata/catalog.json` without disturbing
anything already registered.

Two things it is careful about
------------------------------
**Synthetic is declared, not implied.** Every entry carries `is_synthetic` and
`origin = SYNTHETIC_DEMO`, and so does every row. A dataset that is synthetic
in a comment and silent in its metadata is eventually quoted as somebody's
book.

**The snapshot is registered as authoritative for nothing.** It is the widest
and fastest dataset here and it would be the natural default for any query
that needs a borrower attribute - which is exactly why its
`authoritative_for` is empty. B2's rule survives only if the metadata says so
where the resolver reads it, not only in a docstring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backend.corporate import NOT_CLIENT_DATA, ORIGIN
from backend.corporate import domains as domains_mod
from backend.data_access import catalog as catalog_mod

CATALOGUE_VERSION = "1.0.0"

SNAPSHOT_DATASET = "corporate_borrower_360"

#: The governed purpose each dataset is the last word on. Read from the domain
#: definitions rather than restated, so the two can never drift.
AUTHORITATIVE_FOR: dict[str, list[str]] = {}
for _domain in domains_mod.DOMAINS:
    for _dataset in _domain.datasets:
        AUTHORITATIVE_FOR[_dataset] = list(_domain.authoritative_for)

#: What one row of each dataset is. The property most often misunderstood
#: about a table and the one that makes a wrong answer look right.
GRAIN: dict[str, str] = {
    "corporate_customer_master": "One row per borrower per quarter.",
    "corporate_ratings": "One row per borrower per quarter.",
    "corporate_financials": "One row per borrower per fiscal year.",
    "corporate_facilities": "One row per facility per quarter.",
    "corporate_ifrs9": "One row per borrower per quarter (obligor staging).",
    "corporate_ifrs9_facility": (
        "One row per FACILITY per quarter. The same book as corporate_ifrs9 "
        "at a second grain, not a second measurement: stage, SICR, PD and LGD "
        "are the obligor's and are carried unchanged to each of their "
        "facilities, EAD is read from the facility itself, and ECL is split "
        "by EAD share and sums back to the obligor figure exactly."),
    "corporate_delinquency": "One row per borrower per quarter.",
    "corporate_covenants": "One row per covenant test per quarter.",
    "corporate_collateral": "One row per collateral item per quarter.",
    "corporate_guarantees": (
        "One row per guarantee edge - a PROVIDES from a guarantor, or a "
        "COVERS onto a facility."),
    "corporate_limits": "One row per borrower per quarter.",
    "corporate_watchlist": "One row per signal raised per borrower-quarter.",
    "corporate_restructuring": "One row per concession granted.",
    "corporate_profitability": "One row per borrower per quarter.",
    "corporate_ownership_edges": (
        "One row per observed edge assertion, valid over a period."),
    "corporate_graph_nodes": "One row per graph node.",
    "corporate_supply_chain": "One row per supplier-buyer pair.",
    "corporate_exposure_network": (
        "One row per financial claim between two counterparties."),
    "corporate_connected_groups": (
        "One row per borrower per quarter, giving its derived groups."),
    "corporate_entity_resolution": (
        "One row per SOURCE RECORD, not per entity - the mapping is what is "
        "recorded, and an unresolved record has to be expressible."),
    "corporate_graph_dq": "One row per data-quality issue.",
    SNAPSHOT_DATASET: "One row per borrower per quarter.",
}

#: Which column carries the period.
PERIOD_FIELD: dict[str, str] = {
    "corporate_financials": "fiscal_year",
    "corporate_ownership_edges": "valid_from",
    "corporate_graph_nodes": "",
    "corporate_supply_chain": "valid_from",
    "corporate_exposure_network": "valid_from",
    "corporate_guarantees": "valid_from",
    "corporate_entity_resolution": "",
}

#: Primary keys, where they are not (borrower_id, period).
PRIMARY_KEYS: dict[str, list[str]] = {
    "corporate_ifrs9_facility": ["facility_id", "period"],
    "corporate_financials": ["borrower_id", "fiscal_year"],
    "corporate_facilities": ["facility_id", "period"],
    "corporate_covenants": ["borrower_id", "period", "covenant_id"],
    "corporate_collateral": ["collateral_id", "period"],
    "corporate_watchlist": ["borrower_id", "period", "signal"],
    "corporate_restructuring": ["restructuring_id"],
    "corporate_ownership_edges": ["edge_id"],
    "corporate_graph_nodes": ["node_id"],
    "corporate_supply_chain": ["edge_id"],
    "corporate_exposure_network": ["edge_id"],
    "corporate_guarantees": ["edge_id"],
    "corporate_entity_resolution": ["resolution_id"],
    "corporate_graph_dq": ["issue_id"],
}

_TYPES: dict[str, str] = {
    "int64": "integer", "int32": "integer", "Int64": "integer",
    "float64": "number", "float32": "number",
    "bool": "boolean", "boolean": "boolean",
    "object": "string", "string": "string",
    "datetime64[ns]": "date",
}


def _humanise(name: str) -> str:
    words = name.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _field(name: str, series: pd.Series) -> dict[str, Any]:
    return {
        "name": name,
        "source_column": name,
        "business_name": _humanise(name),
        "definition": _definition(name),
        "data_type": _TYPES.get(str(series.dtype), "string"),
        "unit": _unit(name),
        "sensitivity": _sensitivity(name),
        "nullable": bool(series.isna().any()),
    }


def _definition(name: str) -> str:
    """A reviewable English definition, from the lineage table where it has one."""
    from backend.corporate import lineage as lineage_mod

    entry = lineage_mod.BY_NAME.get(name)
    if entry is not None:
        return (f"{_humanise(name)}. Source: {entry.source_domain} / "
                f"{entry.source_dataset}.{entry.source_field}. "
                f"{entry.transformation.capitalize()}.")
    return f"{_humanise(name)}."


def _unit(name: str) -> str | None:
    if name.endswith("_pct") or name.endswith("_share") or "margin" in name:
        return "%"
    if name.endswith("_days") or name == "current_dpd":
        return "days"
    if name.endswith("_count"):
        return "count"
    if any(part in name for part in (
            "exposure", "amount", "limit", "ecl", "value", "revenue",
            "ebitda", "equity", "assets", "debt", "capital", "income")):
        return "SAR millions"
    return None


def _sensitivity(name: str) -> str:
    # A natural person's name and a national identifier are more sensitive
    # than a company's exposure, and are labelled that way so a profile that
    # shows them says so.
    if any(part in name for part in ("arabic_name", "national", "person")):
        return "confidential"
    if name in {"legal_name", "alias", "display_name", "relationship_manager"}:
        return "internal"
    return "internal"


def datasets(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Catalogue entries for every corporate dataset that was built."""
    entries: list[dict[str, Any]] = []
    for name, frame in sorted(frames.items()):
        domain = domains_mod.DATASET_DOMAIN.get(name, "CORPORATE BORROWER 360")
        owner = next(
            (d.owner for d in domains_mod.DOMAINS if d.name == domain),
            "Credit Risk Analytics")
        entries.append({
            "name": name,
            "domain": domain,
            "business_name": _humanise(name.replace("corporate_", "Corporate ")),
            "purpose": _purpose(name, domain),
            "grain": GRAIN.get(name, "One row per record."),
            "primary_keys": PRIMARY_KEYS.get(name, ["borrower_id", "period"]),
            "period_field": PERIOD_FIELD.get(name, "period"),
            "owner": owner,
            "status": "active",
            "version": "1.0.0",
            "is_synthetic": True,
            "origin": ORIGIN,
            "dataset_family": domain,
            "authoritative_for": AUTHORITATIVE_FOR.get(name, []),
            # B44. These datasets describe a DIFFERENT BOOK from the credit
            # portfolio the product has always carried, and they share almost
            # every word with it: customers, exposure at default, IFRS 9
            # stage, covenant. Declaring the scope is what stops a question
            # about one being answered from the other by string overlap.
            "portfolio_scope": catalog_mod.BORROWER_360_SCOPE,
            "fields": [_field(column, frame[column])
                       for column in frame.columns],
        })
    return entries


def _purpose(name: str, domain: str) -> str:
    if name == SNAPSHOT_DATASET:
        return (
            "The Borrower 360 semantic snapshot: 137 fields per borrower per "
            "quarter, denormalised for reading. AUTHORITATIVE FOR NOTHING - "
            "every field is a copy of, or a derivation from, a field another "
            "domain owns (B2). Query it for speed; cite the source domain.")
    entry = next((d for d in domains_mod.DOMAINS if d.name == domain), None)
    return entry.purpose if entry else _humanise(name)


#: Declared joins. B3/B5: a join that is not declared is a join nobody
#: reviewed, and the FORBIDDEN entries are the ones that matter - they name
#: the joins that look reasonable and are wrong.
RELATIONSHIPS: tuple[dict[str, Any], ...] = (
    {
        "from_dataset": SNAPSHOT_DATASET,
        "to_dataset": "corporate_ifrs9",
        "kind": "LINEAGE",
        "on": ["borrower_id", "period"],
        "why": ("The snapshot's stage and ECL are copies. This is the join "
                "VIEW SOURCE follows back to the authoritative row."),
    },
    {
        "from_dataset": SNAPSHOT_DATASET,
        "to_dataset": "corporate_financials",
        "kind": "AS_OF",
        "on": ["borrower_id"],
        "why": ("The latest statement PUBLISHED on or before the quarter "
                "end. Not a fiscal-year join: a statement the borrower had "
                "not filed yet was not information the bank had."),
    },
    {
        "from_dataset": "corporate_facilities",
        "to_dataset": "corporate_collateral",
        "kind": "ONE_TO_MANY",
        "on": ["facility_id", "period"],
        "why": "Security is held against a facility, not against a borrower.",
    },
    {
        "from_dataset": "corporate_guarantees",
        "to_dataset": "corporate_facilities",
        "kind": "ONE_TO_MANY",
        "on": ["facility_id"],
        "why": ("A guarantee is a reified node covering one or more "
                "facilities; COVERS edges carry the facility."),
    },
    {
        "from_dataset": "corporate_entity_resolution",
        "to_dataset": "corporate_customer_master",
        "kind": "RESOLUTION",
        "on": ["canonical_entity_id", "borrower_id"],
        "why": ("Source records resolve to a canonical borrower. The join "
                "drops records whose match was rejected on review, which is "
                "correct: they resolve to nothing."),
    },
    {
        "from_dataset": SNAPSHOT_DATASET,
        "to_dataset": "corporate_covenants",
        "kind": "FORBIDDEN",
        "on": ["borrower_id", "period"],
        "why": (
            "Different grain. The snapshot is one row per borrower-quarter "
            "and covenants are one row per TEST, so this join multiplies "
            "every exposure figure by the borrower's covenant count. Use the "
            "snapshot's pre-aggregated covenant columns, or aggregate the "
            "covenant domain first."),
    },
    {
        "from_dataset": "corporate_supply_chain",
        "to_dataset": "corporate_connected_groups",
        "kind": "FORBIDDEN",
        "on": ["from_node", "borrower_id"],
        "why": (
            "B21. Commercial dependence is not control. Joining supply-chain "
            "edges into group formation is exactly the mistake that turns a "
            "sector into one connected counterparty."),
    },
)


def reconcile_published(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Bring PUBLISHED Data Builder entries back in line with the rebuilt lake.

    A published dataset in PostgreSQL OVERRIDES the file catalogue entry of the
    same name — deliberately, because a steward republishing a dataset is a
    deliberate act. The consequence nobody planned for is that rebuilding the
    lake with new columns leaves those columns invisible: the Parquet has them,
    the file catalogue has them, and every analysis is refused with "not a
    field of dataset" because a database row written months ago does not.

    That is what happened to nine columns of `corporate_borrower_360`, and the
    failure looked like a bug in the caller rather than a stale catalogue. So
    the build reconciles: any column the frame carries and the published entry
    does not is added to the dictionary, typed from the data, and reported.
    Nothing is ever REMOVED here — a steward's own definition is theirs.

    Silent where there is no database. This is a repair step in a generator,
    not a migration.
    """
    from backend.config import settings

    report: dict[str, Any] = {"available": False, "added": {}, "checked": 0}
    if not settings.has_database:
        report["why"] = "No DATABASE_URL, so nothing is published to reconcile."
        return report
    try:
        from backend.db.engine import get_session
        from backend.services.data_builder import (
            get_dataset,
            published_datasets,
            upsert_field_definition,
        )
    except Exception as e:  # pragma: no cover - the DAL must survive this
        report["why"] = f"Data Builder is unavailable: {e}"
        return report

    try:
        with get_session() as session:
            published = {d.name for d in published_datasets(session)}
            for name, frame in sorted(frames.items()):
                if name not in published:
                    continue
                report["checked"] += 1
                known = {f.name for f in get_dataset(session, name).fields}
                missing = [c for c in frame.columns if c not in known]
                for column in missing:
                    upsert_field_definition(
                        session, name, name=column,
                        data_type=_TYPES.get(str(frame[column].dtype), "string"),
                        unit=_unit(column), sensitivity=_sensitivity(column),
                        business_name=_humanise(column),
                        source_system=ORIGIN, source_field=column,
                        definition=_definition(column) or (
                            "Added by the corporate universe build to match "
                            "the rebuilt lake."))
                if missing:
                    report["added"][name] = missing
            session.commit()
        report["available"] = True
    except Exception as e:  # pragma: no cover - a build must not die on this
        report["why"] = f"Could not reconcile published datasets: {e}"
    return report


def merge_into_catalogue(frames: dict[str, pd.DataFrame],
                         path: Path | None = None) -> dict[str, Any]:
    """Add the corporate datasets to the governed catalogue, in place."""
    from backend.config import settings
    from backend.data_access import catalogue_io

    target = path or catalogue_io.path_for(settings.metadata_dir)
    ours = datasets(frames)
    names = {d["name"] for d in ours}
    catalogue = catalogue_io.merge(target.parent, datasets=ours,
                                   relationships=list(RELATIONSHIPS))
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "path": str(target),
        "corporate_datasets": sorted(names),
        "dataset_count": len(ours),
        "total_datasets": len(catalogue["datasets"]),
        "relationships_declared": len(RELATIONSHIPS),
        "forbidden_joins": sum(
            1 for r in RELATIONSHIPS if r["kind"] == "FORBIDDEN"),
        "all_synthetic": all(d["is_synthetic"] for d in ours),
        "snapshot_authoritative_for": AUTHORITATIVE_FOR.get(
            SNAPSHOT_DATASET, []),
        "origin": ORIGIN,
        "not_client_data": NOT_CLIENT_DATA,
    }
