"""
Registering the scorecard datasets in the governed catalogue. §3, §4, §77, §78.

The two domains have to be first-class in Data Builder — discoverable,
profileable, with field definitions and declared relationships — not tables
that happen to exist on disk. This module builds the catalogue entries and
merges them into `metadata/catalog.json` without disturbing anything else
already registered.

Two things it is careful about
-------------------------------
**Synthetic is declared, not implied.** §2: every entry carries
`is_synthetic: true` and `origin: SYNTHETIC_DEMO`, and every row carries the
same origin. A dataset that is synthetic in a comment and silent in its
metadata will eventually be quoted as though it described somebody's book.

**Relationships are declared so joins are governed.** §78: validation rows
to the model specification, application rows to their outcomes, behavioral
snapshots to their future outcomes. Declaring them is what stops an
accidental cross-domain join — an application row and a behavioral snapshot
share a `customer_id` column name and mean entirely different things by it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.scorecard import build as build_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

CATALOGUE_VERSION = "1.0.0"

APP = vars_mod.APPLICATION_SCORECARD
BEH = vars_mod.BEHAVIORAL_SCORECARD

#: Which governed family each physical dataset belongs to. §4's families are
#: business groupings; a family can hold more than one dataset and a dataset
#: belongs to exactly one.
DATASET_FAMILY: dict[str, str] = {
    "retail_application_scorecard_monthly_validation":
        "APPLICATION SCORECARD MONTHLY VALIDATION",
    "retail_application_scorecard_development_reference":
        "APPLICATION SCORECARD DEVELOPMENT REFERENCE",
    "retail_behavioral_scorecard_monthly_validation":
        "BEHAVIORAL SCORECARD MONTHLY VALIDATION",
    "retail_behavioral_scorecard_development_reference":
        "BEHAVIORAL SCORECARD DEVELOPMENT REFERENCE",
}

_TYPES: dict[str, str] = {
    "NUMERIC": "number", "CATEGORICAL": "string", "FLAG": "boolean",
}


def _field(name: str, business: str, definition: str, data_type: str,
           unit: str | None = None, sensitivity: str = "internal",
           nullable: bool = True) -> dict[str, Any]:
    return {
        "name": name, "source_column": name, "business_name": business,
        "definition": definition, "data_type": data_type, "unit": unit,
        "sensitivity": sensitivity, "nullable": nullable,
    }


def _variable_fields(scorecard_type: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for variable in vars_mod.catalogue(scorecard_type):
        fields.append(_field(
            variable.name, variable.label, variable.definition,
            _TYPES.get(variable.kind, "string"), variable.unit or None,
            # A field kept only for fairness monitoring is more sensitive
            # than the rest of the row and is labelled that way, so a
            # profile that shows it says so.
            "restricted" if not variable.scoreable else "internal"))
    return fields


def _woe_fields(scorecard_type: str) -> list[dict[str, Any]]:
    """§10's stored WoE and bin columns, for the model variables."""
    fields: list[dict[str, Any]] = []
    for name in sorted({v for names in
                        build_mod.MODEL_VARIABLES[scorecard_type].values()
                        for v in names}):
        variable = vars_mod.get(scorecard_type, name)
        fields.append(_field(
            vars_mod.woe_name(name), f"{variable.label} (WoE)",
            f"Weight of evidence for {variable.label}, looked up from the "
            "approved development binning specification. Not recomputed on "
            "the validation month.", "number"))
        fields.append(_field(
            f"{name}_bin", f"{variable.label} (bin)",
            f"Which approved bin {variable.label} fell in, including the "
            "MISSING and UNSEEN special bins.", "string"))
    return fields


def _score_fields() -> list[dict[str, Any]]:
    """§14's model outputs, one set per seeded model."""
    fields: list[dict[str, Any]] = []
    for kind in build_mod.MODEL_KINDS:
        suffix = build_mod.OUTPUT_SUFFIX[kind]
        label = kind.title()
        fields.append(_field(f"score_{suffix}", f"{label} score",
                             f"Score produced by the {label.lower()} model "
                             "under the approved score mapping.", "number",
                             "points"))
        fields.append(_field(f"pd_{suffix}", f"{label} PD",
                             f"Probability of default from the "
                             f"{label.lower()} model.", "number", "ratio"))
        fields.append(_field(f"logit_{suffix}", f"{label} logit",
                             f"Log-odds of bad from the {label.lower()} "
                             "model, before the PD transform.", "number"))
    return fields


def _outcome_fields() -> list[dict[str, Any]]:
    return [
        _field("actual_default", "Actual default",
               "Whether the obligation defaulted within the performance "
               "window under the model's default definition. Null — not "
               "zero — where the window has not closed.", "boolean"),
        _field("performance_window_end", "Performance window end",
               "The month at which this cohort's outcome becomes "
               "observable.", "string"),
        _field("matured_flag", "Outcome matured",
               "Whether the performance window has closed. Predictive "
               "metrics may only be computed where this is true.",
               "boolean"),
        _field("performance_horizon_months", "Performance horizon",
               "Months from observation to outcome, per the model "
               "specification.", "number", "months"),
        _field("origin", "Origin",
               "SYNTHETIC_DEMO. This data was generated to demonstrate "
               "scorecard validation and describes no real customer.",
               "string"),
    ]


def _dataset(name: str, *, scorecard_type: str, business_name: str,
             purpose: str, grain: str, keys: list[str], period_field: str,
             authoritative_for: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "domain": build_mod.DOMAINS[scorecard_type]["name"],
        "business_name": business_name,
        "purpose": purpose,
        "grain": grain,
        "primary_keys": keys,
        "period_field": period_field,
        "owner": build_mod.DOMAINS[scorecard_type]["owner"],
        "status": "active",
        "version": "1.0.0",
        "is_synthetic": True,
        "origin": synth.ORIGIN,
        "dataset_family": DATASET_FAMILY[name],
        "authoritative_for": authoritative_for,
        "fields": [
            _field(period_field, "Observation month",
                   "The month this row describes.", "string",
                   nullable=False),
            *(_variable_fields(scorecard_type)),
            *(_woe_fields(scorecard_type)),
            *(_score_fields()),
            *(_outcome_fields()),
        ],
    }


def datasets() -> list[dict[str, Any]]:
    """Every scorecard dataset, as catalogue entries."""
    return [
        _dataset(
            "retail_application_scorecard_monthly_validation",
            scorecard_type=APP,
            business_name="Application Scorecard Monthly Validation",
            purpose=(
                "One row per application, scored by every registered model "
                "version, with the realised twelve-month outcome where the "
                "performance window has closed."),
            grain="One row per application.",
            keys=["application_month", "application_id"],
            period_field="application_month",
            authoritative_for=["retail_application_scoring"]),
        _dataset(
            "retail_application_scorecard_development_reference",
            scorecard_type=APP,
            business_name="Application Scorecard Development Reference",
            purpose=(
                "The out-of-time population the approved binning and the "
                "model coefficients were fitted on. The default baseline "
                "for every stability comparison."),
            grain="One row per development-window application.",
            keys=["application_month", "application_id"],
            period_field="application_month",
            authoritative_for=["retail_application_development_reference"]),
        _dataset(
            "retail_behavioral_scorecard_monthly_validation",
            scorecard_type=BEH,
            business_name="Behavioral Scorecard Monthly Validation",
            purpose=(
                "One row per active account per snapshot month, scored by "
                "every registered model version, with the realised "
                "twelve-month outcome where the window has closed."),
            grain="One row per account per observation month.",
            keys=["observation_month", "account_id"],
            period_field="observation_month",
            authoritative_for=["retail_behavioral_scoring"]),
        _dataset(
            "retail_behavioral_scorecard_development_reference",
            scorecard_type=BEH,
            business_name="Behavioral Scorecard Development Reference",
            purpose=(
                "The out-of-time snapshots the approved behavioral binning "
                "and coefficients were fitted on."),
            grain="One row per account per development snapshot month.",
            keys=["observation_month", "account_id"],
            period_field="observation_month",
            authoritative_for=["retail_behavioral_development_reference"]),
    ]


#: §78. The joins that are allowed, and the one that is explicitly not.
RELATIONSHIPS: tuple[dict[str, Any], ...] = (
    {
        "from_dataset": "retail_application_scorecard_monthly_validation",
        "to_dataset": "retail_application_scorecard_development_reference",
        "kind": "BASELINE_COMPARISON",
        "on": ["application_month"],
        "why": "Stability is measured against the development population.",
    },
    {
        "from_dataset": "retail_behavioral_scorecard_monthly_validation",
        "to_dataset": "retail_behavioral_scorecard_development_reference",
        "kind": "BASELINE_COMPARISON",
        "on": ["observation_month"],
        "why": "Stability is measured against the development population.",
    },
    {
        "from_dataset": "retail_application_scorecard_monthly_validation",
        "to_dataset": "retail_behavioral_scorecard_monthly_validation",
        "kind": "FORBIDDEN",
        "on": ["customer_id"],
        "why": (
            "§78: no accidental cross-domain join. Both carry a customer_id "
            "and they mean different things by it — an application is a "
            "decision at a point in time, a behavioral snapshot is a state "
            "of an existing account. Joining them silently mixes two "
            "populations, two default definitions and two models."),
    },
)


def _only_what_was_built(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop declared columns the build did not actually write.

    The variable list proposes bin and weight-of-evidence columns for every
    model variable; variable selection then drops some of those variables, and
    the writer does not emit columns for them. A catalogue that declares one
    of those anyway is not a small inaccuracy — the compiler selects every
    declared column, so a single phantom field makes the whole dataset
    unqueryable with a binder error, which is how both retail application
    datasets came to be unreadable.

    So the declaration is reconciled against the artefact. What is on disk
    wins, and what was dropped is logged by name.
    """
    from backend.config import settings

    root = settings.analytics_dir / entry["name"]
    if not root.exists():
        return entry
    partitions = sorted(p for p in root.iterdir() if p.is_dir())
    if not partitions:
        return entry

    import duckdb

    pattern = str(partitions[-1] / "*.parquet")
    try:
        with duckdb.connect(database=":memory:") as conn:
            built = {row[0] for row in conn.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{pattern}')").fetchall()}
    except Exception:  # noqa: BLE001 - unreadable data declares nothing
        return entry

    kept = [f for f in entry.get("fields", []) if f["name"] in built]
    dropped = [f["name"] for f in entry.get("fields", [])
               if f["name"] not in built]
    if dropped:
        logger.warning(
            "%s: %s declared but not written by the build; left out of the "
            "catalogue: %s", entry["name"], len(dropped), ", ".join(dropped))
    entry = dict(entry)
    entry["fields"] = kept
    return entry


def merge_into_catalogue(path: Path | None = None) -> dict[str, Any]:
    """Add the scorecard datasets to the governed catalogue, in place.

    Merges rather than rewrites: anything already registered is left exactly
    as it was, and re-running replaces only the scorecard entries.
    """
    from backend.config import settings

    target = path or (settings.metadata_dir / "catalog.json")
    catalogue: dict[str, Any] = (
        json.loads(target.read_text("utf-8")) if target.exists()
        else {"version": "1.0.0", "datasets": []})

    ours = [_only_what_was_built(d) for d in datasets()]
    names = {d["name"] for d in ours}
    kept = [d for d in catalogue.get("datasets", [])
            if d.get("name") not in names]
    catalogue["datasets"] = kept + ours

    relationships = [r for r in catalogue.get("relationships", [])
                     if r.get("from_dataset") not in names]
    catalogue["relationships"] = relationships + list(RELATIONSHIPS)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalogue, indent=2), encoding="utf-8")
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "path": str(target),
        "scorecard_datasets": sorted(names),
        "total_datasets": len(catalogue["datasets"]),
        "relationships_declared": len(RELATIONSHIPS),
        "all_synthetic": all(d["is_synthetic"] for d in ours),
    }


def summary() -> dict[str, Any]:
    """§3/§4, for a report: what exists and under which family."""
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "domains": {t: build_mod.DOMAINS[t]["name"] for t in (APP, BEH)},
        "families": {t: list(build_mod.FAMILIES[t]) for t in (APP, BEH)},
        "family_counts": {t: len(build_mod.FAMILIES[t]) for t in (APP, BEH)},
        "datasets": {d["name"]: d["dataset_family"] for d in datasets()},
        "origin": synth.ORIGIN,
        "not_client_data": (
            "Every dataset here is generated. It is marked synthetic in the "
            "catalogue and every row carries origin = SYNTHETIC_DEMO. It "
            "describes no real customer and no real bank's book."),
    }
