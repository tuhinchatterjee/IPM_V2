"""
Register the Early Warning datasets in the governed catalogue.

The gap this closes
-------------------
`scripts/build_early_warning_v2.py` writes three Parquet datasets and stops.
It never touches `metadata/catalog.json`, so the Early Warning book existed on
disk and was invisible to Data Builder: eighty governed datasets catalogued,
none of them Early Warning's, while the bootstrap reported the deployment
ready.

The readiness check could not catch it, because it asked the wrong question —
"do the files exist?" rather than "can the product see them?". A dataset the
governed catalogue does not know about cannot be browsed, cannot be joined
under a declared relationship, and cannot be read by any module that goes
through the catalogue rather than around it.

The declared relationship matters as much as the entry
------------------------------------------------------
Early Warning is borrower-grain on a MONTHLY calendar; the corporate book is
borrower-grain on a QUARTERLY one. Joining them on `borrower_id` alone is
correct; joining a month to a quarter without saying which quarter contains it
is the mistake the relationship declaration exists to prevent, so the mapping
is named in the relationship rather than left to whoever writes the query.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

CATALOGUE_VERSION = "ews-2.0.0"
DOMAIN = "Early Warning"
OWNER = "Credit Risk — Early Warning"
ORIGIN = "SYNTHETIC_DEMO"

#: The identity column as the generator writes it today. `customer_id` carries
#: canonical `CORP-` values — the same values under a different name — and is
#: declared here as the join key so nothing has to guess.
IDENTITY = "customer_id"

DATASETS: dict[str, dict[str, str]] = {
    "early_warning_borrower_month": {
        "business_name": "Early Warning — Borrower Month",
        "purpose": ("One row per borrower per published month: the Early "
                    "Warning score, its four intelligence layers, the "
                    "triggers that fired and the IFRS 9 fields mirrored from "
                    "the canonical book as at the containing quarter."),
        "grain": "borrower x month",
    },
    "early_warning_signal_observation": {
        "business_name": "Early Warning — Signal Observation",
        "purpose": ("One row per signal per borrower per month: the raw "
                    "observation, its severity band and the classifier that "
                    "read it. This is the evidence behind a score."),
        "grain": "borrower x month x signal",
    },
    "early_warning_external_event_synthetic": {
        "business_name": "Early Warning — External Event",
        "purpose": ("External intelligence attached to a borrower. An "
                    "Early-Warning-only concept: the canonical book carries "
                    "no equivalent, which is why this is authoritative here "
                    "rather than mirrored from somewhere else."),
        "grain": "borrower x event",
    },
}

#: How Early Warning joins to the rest of the product, declared rather than
#: inferred. The month-to-quarter mapping is stated because it is the one
#: place a reader could silently get it wrong.
RELATIONSHIPS: list[dict[str, Any]] = [
    {
        "from_dataset": "early_warning_borrower_month",
        "from_field": IDENTITY,
        "to_dataset": "corporate_borrower_360",
        "to_field": "borrower_id",
        "kind": "MANY_TO_ONE",
        "note": ("Early Warning is monthly and the corporate book is "
                 "quarterly. Join on the borrower; take the corporate row for "
                 "the quarter that CONTAINS the month, as-of, never "
                 "interpolated."),
    },
    {
        "from_dataset": "early_warning_signal_observation",
        "from_field": IDENTITY,
        "to_dataset": "early_warning_borrower_month",
        "to_field": IDENTITY,
        "kind": "MANY_TO_ONE",
        "note": "The observations behind one borrower-month score.",
    },
    {
        "from_dataset": "early_warning_external_event_synthetic",
        "from_field": IDENTITY,
        "to_dataset": "corporate_borrower_360",
        "to_field": "borrower_id",
        "kind": "MANY_TO_ONE",
        "note": "External intelligence, attached to a canonical borrower.",
    },
]

#: What Early Warning is the authority on. Deliberately short: the score and
#: its evidence are its own, and the IFRS 9 fields beside them are MIRRORS of
#: the canonical book that this domain must never be treated as owning.
AUTHORITATIVE_FOR: dict[str, list[str]] = {
    "early_warning_borrower_month": ["early_warning_score", "trigger_state"],
    "early_warning_signal_observation": ["signal_observation"],
    "early_warning_external_event_synthetic": ["external_event"],
}

_TYPES = {"object": "string", "string": "string", "int64": "integer",
          "int32": "integer", "float64": "number", "float32": "number",
          "bool": "boolean", "datetime64[ns]": "date"}


def _field(name: str, dtype: str) -> dict[str, Any]:
    return {
        "name": name,
        "business_name": name.replace("_", " ").title(),
        "data_type": _TYPES.get(str(dtype), "string"),
        "definition": f"{name.replace('_', ' ').capitalize()} as published by "
                      f"the Early Warning build.",
        "nullable": True,
        "sensitivity": "internal",
        "source_column": name,
        "unit": None,
    }


def datasets(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """One catalogue entry per Early Warning dataset present."""
    out: list[dict[str, Any]] = []
    for name, spec in DATASETS.items():
        frame = frames.get(name)
        if frame is None:
            continue
        keys = [c for c in (IDENTITY, "snapshot_month", "period", "signal_key",
                            "event_id") if c in frame.columns]
        period = next((c for c in ("snapshot_month", "period", "month")
                       if c in frame.columns), None)
        out.append({
            "name": name,
            "business_name": spec["business_name"],
            "dataset_family": name,
            "domain": DOMAIN,
            "owner": OWNER,
            "purpose": spec["purpose"],
            "grain": spec["grain"],
            "primary_keys": keys,
            "period_field": period,
            "fields": [_field(c, frame[c].dtype) for c in frame.columns],
            "is_synthetic": True,
            "origin": ORIGIN,
            "status": "published",
            "version": CATALOGUE_VERSION,
            "authoritative_for": AUTHORITATIVE_FOR.get(name, []),
        })
    return out


def merge_into_catalogue(frames: dict[str, pd.DataFrame],
                         path: Path | None = None) -> dict[str, Any]:
    """Add the Early Warning datasets to the governed catalogue, in place."""
    from backend.config import settings
    from backend.data_access import catalogue_io

    target = path or catalogue_io.path_for(settings.metadata_dir)
    ours = datasets(frames)
    if not ours:
        return {"catalogue_version": CATALOGUE_VERSION, "dataset_count": 0,
                "note": "no Early Warning frames were supplied"}
    catalogue = catalogue_io.merge(target.parent, datasets=ours,
                                   relationships=list(RELATIONSHIPS))
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "path": str(target),
        "early_warning_datasets": sorted(d["name"] for d in ours),
        "dataset_count": len(ours),
        "total_datasets": len(catalogue["datasets"]),
        "relationships_declared": len(RELATIONSHIPS),
        "origin": ORIGIN,
    }


def read_lake(root: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """Load whichever Early Warning datasets are on disk."""
    import glob

    from backend.config import settings

    base = Path(root) if root else Path(settings.analytics_dir)
    frames: dict[str, pd.DataFrame] = {}
    for name in DATASETS:
        parts = sorted(glob.glob(str(base / name / "**" / "*.parquet"),
                                 recursive=True))
        if parts:
            frames[name] = pd.concat([pd.read_parquet(p) for p in parts],
                                     ignore_index=True)
    return frames


__all__ = ["AUTHORITATIVE_FOR", "CATALOGUE_VERSION", "DATASETS", "DOMAIN",
           "IDENTITY", "RELATIONSHIPS", "datasets", "merge_into_catalogue",
           "read_lake"]
