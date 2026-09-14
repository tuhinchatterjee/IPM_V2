"""
Publishing the Early Warning domain, so the Data Builder can see it.

The defect this closes
----------------------
Data Builder showed Early Warning as **Empty** — no published periods, no
rows — while the certified build held three hundred obligors, twenty monthly
snapshots and six thousand borrower-month rows. The card was not lying. The
business domain existed in the domain map and claimed the catalogue heading
"Early Warning", and no dataset had ever been registered under it: the build
wrote its parquet into the lake and told the catalogue nothing.

    scripts/build_early_warning_v2.py
        -> data/analytics/early_warning_borrower_month/period=YYYY-MM/...
        -> (nothing)                      metadata/catalog.json

So a screen that reads the catalogue reported an empty domain, correctly, and
the chat that reads the parquet answered from it, also correctly. Two truths
about one domain.

What this module does
---------------------
Describes the three governed Early Warning datasets in the catalogue's own
shape and merges them into `metadata/catalog.json`. The build calls it, so a
rebuild republishes rather than drifting; `scripts/register_early_warning_domain.py`
calls it too, which is the deterministic reconciliation path for an
environment whose data is present and whose metadata is stale.

**One source for the fields.** The field list is generated from
`backend.early_warning.dictionary`, the same dictionary the conversation
validates against and the dashboard filters are derived from. A hand-kept copy
in a JSON file is a second definition of what Early Warning data means, and
two definitions of that is the condition this module exists to remove.

Nothing here is hard-coded about size. Periods and row counts are read from
the lake by the catalogue, exactly as they are for every other dataset; this
module declares the SHAPE, and the data says how much of it there is.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The catalogue heading the business-domain map claims for Early Warning.
#: It must match `backend.services.data_domains`' entry exactly, or the
#: datasets land under "unplaced" and the card stays empty for a new reason.
CATALOGUE_DOMAIN = "Early Warning"

BORROWER_MONTH = "early_warning_borrower_month"
SIGNAL_OBSERVATION = "early_warning_signal_observation"
EXTERNAL_EVENT = "early_warning_external_event_synthetic"

#: The analytical grain. One row per customer per published month — the thing
#: every Early Warning answer is ultimately about.
GRAIN = "One row per customer per published month end."

CATALOG_FILENAME = "catalog.json"


def _field_entries() -> list[dict[str, Any]]:
    """The borrower-month fields, from the governed dictionary.

    Generated rather than transcribed. If the Data Builder says a field
    exists, the conversation's dictionary is where that claim came from, so
    the two cannot disagree about what Early Warning holds.
    """
    from backend.early_warning import dictionary as dic

    out: list[dict[str, Any]] = []
    for entry in dic.fields():
        out.append({
            "name": entry.name,
            "source_column": entry.name,
            "business_name": entry.label,
            "definition": entry.definition,
            "data_type": entry.dtype,
            "unit": entry.unit or None,
            "sensitivity": "internal",
            "nullable": True,
            # Kept so a reader of the catalogue can see which layer, node or
            # signal a field belongs to without opening the product.
            "category": entry.group,
            "derived": bool(entry.derived),
        })
    return out


def _observation_fields() -> list[dict[str, Any]]:
    """The normalised signal-observation columns.

    Described here rather than generated, because this dataset is long rather
    than wide: one row per fired signal per customer per month, and its
    columns are the explanation of a single observation.
    """
    described = [
        ("customer_id", "Customer", "The obligor the observation is about.",
         "string"),
        ("snapshot_month", "Month", "The published month end.", "string"),
        ("signal_key", "Signal", "Which of the governed signals fired.",
         "string"),
        ("signal_score", "Signal score",
         "The signal's contribution after trigger severity, accelerator and "
         "decay.", "number"),
        ("sub_category", "Sub-category",
         "The governed node the signal rolls into.", "string"),
        ("layer", "Layer", "The detection layer, L1 to L4.", "string"),
        ("causal_chain_id", "Causal chain",
         "Which chain of related events this observation belongs to, so one "
         "event counted twice is visible as one event.", "string"),
        ("trigger_severity_band", "Trigger severity",
         "The severity band the trigger assigned.", "string"),
        ("trigger_severity_score", "Trigger severity score",
         "The trigger's own score before the accelerator.", "number"),
        ("accelerator_multiplier", "Accelerator",
         "The combined multiplier from the five accelerator dimensions.",
         "number"),
        ("decay_class", "Decay class",
         "Which half-life class governs this signal's decay.", "string"),
        ("decay_factor", "Decay factor",
         "How much of the original severity survives, after cure and age.",
         "number"),
        ("half_life_days", "Half life", "The class's half-life, in days.",
         "number"),
        ("cured", "Cured", "Whether the underlying condition has cured.",
         "boolean"),
        ("days_since_cure", "Days since cure",
         "How long ago it cured, which is what decay is measured from.",
         "number"),
        ("age_days", "Evidence age", "How old the evidence is, in days.",
         "number"),
        ("source_system", "Source system",
         "Which system the observation came from.", "string"),
        ("source_tier", "Source tier",
         "How much the source is relied on: tier 1 is internal and "
         "authoritative, tier 3 is external and single-sourced.", "string"),
        ("is_synthetic", "Synthetic",
         "Whether the observation is generated demonstration data.",
         "boolean"),
    ]
    return [{
        "name": name,
        "source_column": name,
        "business_name": label,
        "definition": definition,
        "data_type": dtype,
        "unit": None,
        "sensitivity": "internal",
        "nullable": True,
        "category": "Signal observation",
    } for name, label, definition, dtype in described]


def _event_fields() -> list[dict[str, Any]]:
    described = [
        ("customer_id", "Customer", "The obligor the event concerns.",
         "string"),
        ("snapshot_month", "Month", "The published month the event lands in.",
         "string"),
        ("event_type", "Event type", "What kind of external event it is.",
         "string"),
        ("severity", "Severity", "How serious the event is.", "string"),
        ("source_system", "Source system",
         "Which external feed reported it.", "string"),
        ("source_tier", "Source tier",
         "How much the feed is relied on.", "string"),
        ("headline", "Headline", "What the feed said, in one line.",
         "string"),
        ("is_synthetic", "Synthetic",
         "Whether the event is generated demonstration data.", "boolean"),
    ]
    return [{
        "name": name,
        "source_column": name,
        "business_name": label,
        "definition": definition,
        "data_type": dtype,
        "unit": None,
        "sensitivity": "internal",
        "nullable": True,
        "category": "External event",
    } for name, label, definition, dtype in described]


def dataset_definitions() -> list[dict[str, Any]]:
    """The three Early Warning datasets, in the catalogue's own shape."""
    return [
        {
            "name": BORROWER_MONTH,
            "domain": CATALOGUE_DOMAIN,
            "business_name": "Early Warning Borrower Month",
            "purpose": (
                "The scored Early Warning position of every obligor at every "
                "published month end: the four layer scores, the trigger-and-"
                "accelerator and classifier dimensions, the anchor, the "
                "notches, the final score and band, and the credit inputs the "
                "model needed to produce them."),
            "grain": GRAIN,
            "primary_keys": ["snapshot_month", "customer_id"],
            "period_field": "snapshot_month",
            "owner": "Credit Risk Analytics",
            "status": "active",
            "version": "2.1.0",
            "is_synthetic": True,
            "origin": "derived",
            "dataset_family": "early_warning",
            "authoritative_for": ["early_warning_position"],
            "fields": _field_entries(),
        },
        {
            "name": SIGNAL_OBSERVATION,
            "domain": CATALOGUE_DOMAIN,
            "business_name": "Early Warning Signal Observation",
            "purpose": (
                "One row per governed signal that fired, for one obligor, in "
                "one month — with the trigger severity, the accelerator "
                "dimensions, the decay state and the source that reported it. "
                "This is the evidence behind a score."),
            "grain": ("One row per customer per signal per published month "
                      "end."),
            "primary_keys": ["snapshot_month", "customer_id", "signal_key"],
            "period_field": "snapshot_month",
            "owner": "Credit Risk Analytics",
            "status": "active",
            "version": "2.1.0",
            "is_synthetic": True,
            "origin": "derived",
            "dataset_family": "early_warning",
            "authoritative_for": ["early_warning_evidence"],
            "fields": _observation_fields(),
        },
        {
            "name": EXTERNAL_EVENT,
            "domain": CATALOGUE_DOMAIN,
            "business_name": "Early Warning External Event",
            "purpose": (
                "The external events the Layer 3 signals are built from: "
                "news, legal filings, rating actions and market signals, with "
                "the feed that reported each one and how much that feed is "
                "relied on."),
            "grain": "One row per external event.",
            "primary_keys": ["snapshot_month", "customer_id", "event_type"],
            "period_field": "snapshot_month",
            "owner": "Credit Risk Analytics",
            "status": "active",
            "version": "2.1.0",
            "is_synthetic": True,
            "origin": "derived",
            "dataset_family": "early_warning",
            "authoritative_for": [],
            "fields": _event_fields(),
        },
    ]


def publish(catalog_path: Path | None = None, *,
            sync_database: bool = True) -> dict[str, Any]:
    """Merge the Early Warning datasets into the governed catalogue.

    A merge rather than a write: the file holds every other domain's
    datasets, and a build that replaced it would publish Early Warning by
    un-publishing the bank.

    With a database configured, the bundled-catalogue sync runs afterwards so
    the governance tables agree with the file. Every other domain's datasets
    have a row there; without one, Early Warning would read as three datasets
    of which none is published, which is a second way of saying Empty.

    Returns what it did, so a build can print it and a test can assert it.
    """
    from backend.config import settings

    path = catalog_path or (settings.metadata_dir / CATALOG_FILENAME)
    payload: dict[str, Any] = {"version": 1, "datasets": []}
    if path.exists():
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("The catalogue at %s is not readable JSON; "
                           "Early Warning is being registered into a fresh "
                           "one.", path)
            payload = {"version": 1, "datasets": []}

    existing = list(payload.get("datasets") or [])
    ours = dataset_definitions()
    names = {d["name"] for d in ours}
    kept = [d for d in existing if str(d.get("name")) not in names]
    payload["datasets"] = kept + ours

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))

    # The catalogue is cached process-wide and read on every request, so a
    # build that wrote the file and left the cache alone would register a
    # domain that this process still cannot see.
    try:
        from backend.data_access.catalog import reload_catalog

        reload_catalog()
    except Exception:  # noqa: BLE001 - a build with no app running is fine
        pass
    try:
        from backend import metadata as md

        md.invalidate()
    except Exception:  # noqa: BLE001
        pass

    synced = _sync_database() if sync_database else False

    return {
        "database_synced": synced,
        "catalog": str(path),
        "registered": sorted(names),
        "replaced": sorted(names & {str(d.get("name")) for d in existing}),
        "datasets_in_catalogue": len(payload["datasets"]),
        "borrower_month_fields": len(ours[0]["fields"]),
    }


def _sync_database() -> bool:
    """Bring the governance tables into line with the catalogue file.

    Reuses Data Builder's own idempotent bundled-catalogue sync rather than
    inserting rows here: two pieces of code writing `DatasetDefinition` is how
    a steward's edit gets silently overwritten by a build. A build with no
    database, which is how the test suite and a first boot both run, is not an
    error -- it says so and carries on.
    """
    try:
        from backend.config import settings

        if not settings.has_database:
            return False
        from backend.db.engine import get_session
        from backend.services import governance

        with get_session() as session:
            governance.sync_bundled_catalog(session)
        return True
    except Exception:  # noqa: BLE001 - the catalogue file is the contract
        logger.warning("Early Warning is registered in the catalogue file, "
                       "but the governance tables could not be updated. Run "
                       "scripts/register_early_warning_domain.py once the "
                       "database is reachable.", exc_info=True)
        return False


def registered(catalog_path: Path | None = None) -> bool:
    """Whether the Early Warning datasets are in the catalogue already."""
    from backend.config import settings

    path = catalog_path or (settings.metadata_dir / CATALOG_FILENAME)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    names = {str(d.get("name")) for d in (payload.get("datasets") or [])}
    return {BORROWER_MONTH, SIGNAL_OBSERVATION}.issubset(names)


__all__ = ["BORROWER_MONTH", "CATALOGUE_DOMAIN", "EXTERNAL_EVENT", "GRAIN",
           "SIGNAL_OBSERVATION", "dataset_definitions", "publish",
           "registered"]
