"""The Saudi SME datasets, as governed catalogue entries. §6.2.

Same shape as `backend/scorecard/catalogue.py`, and merged into the same
`catalog.json`, so the SME domain is a governed domain like any other: it has
a grain, a period field, declared fields with definitions, a declared origin,
and a declared authority.

Being in the catalogue is not the same as being readable
---------------------------------------------------------
These three datasets are registered here *and* restricted by
`backend/scorecard/domains.py`. That is deliberate and not a contradiction.
The catalogue is a governance record — what exists, what it means, where it
came from — and a dataset that is absent from it is an ungoverned dataset,
which is worse than a restricted one. The restriction is a separate concern
handled at the two access gates, and both have to be in place: registered so
it is governed, restricted so the general Cockpit cannot read it.

What is declared and what is written
--------------------------------------
The declaration is reconciled against the Parquet before it is merged, by the
same `_only_what_was_built` rule the retail catalogue learned the hard way: a
declared column the build did not write makes the whole dataset unqueryable,
because the compiler selects every declared column and one phantom field is a
binder error. What is on disk wins.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.scorecard.catalogue import _only_what_was_built
from backend.scorecard.sme import build as build_mod
from backend.scorecard.sme import synthetic as synth
from backend.scorecard.sme import variables as sme_vars

logger = logging.getLogger(__name__)

CATALOGUE_VERSION = "1.0.0"

DOMAIN_NAME = build_mod.DOMAIN["name"]
OWNER = "Model Risk & Validation"

DATASET_FAMILY: dict[str, str] = {
    build_mod.MONTHLY: "SME SCORECARD MONTHLY VALIDATION",
    build_mod.DEVELOPMENT: "SME SCORECARD DEVELOPMENT REFERENCE",
    build_mod.DECISIONS: "SME SCORECARD DECISIONS AND OVERRIDES",
}


def _field(name: str, business: str, definition: str, data_type: str,
           unit: str = "", nullable: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "source_column": name,
        "business_name": business,
        "definition": definition,
        "data_type": data_type,
        "unit": unit or None,
        "sensitivity": "internal",
        "nullable": nullable,
    }


def _control_fields() -> list[dict[str, Any]]:
    """The identifiers, the dates and the maturity flag.

    `is_matured` and `performance_window_end` are in the catalogue rather
    than derived at read time because every outcome-based metric depends on
    them, and a field that decides whether a number may be computed at all
    should be declared where a reader can find it.
    """
    return [
        _field("sme_obligor_id", "Obligor", "Anonymised SME identifier.",
               "string", nullable=False),
        _field("application_id", "Application",
               "Anonymised application identifier.", "string", nullable=False),
        _field("facility_id", "Facility",
               "Anonymised facility identifier.", "string"),
        _field("cohort_month", "Cohort month",
               "The month this application was scored in.", "string",
               nullable=False),
        _field("snapshot_month", "Snapshot month",
               "The observation month this row describes.", "string"),
        _field("score_date", "Score date",
               "The date the score was produced.", "string"),
        _field("performance_window_end", "Window closes",
               "The month this cohort's performance window closes in. Until "
               "it has passed, no realised outcome exists.", "string"),
        _field("performance_horizon_months", "Performance horizon",
               "Months of performance the outcome is observed over.",
               "integer", "months"),
        _field("is_matured", "Outcome available",
               "True where the performance window has closed and a realised "
               "outcome exists. False means the outcome is not yet known — "
               "which is not the same as no defaults.", "boolean"),
        _field("origin", "Origin",
               "SYNTHETIC_DEMO on every row. Generated data.", "string"),
    ]


def _variable_fields() -> list[dict[str, Any]]:
    """Every SME variable carried on the monthly dataset."""
    out: list[dict[str, Any]] = []
    for name in _CARRIED:
        variable = sme_vars.get(name)
        proxy = (" Synthetic proxy for a system CreditProbe is not connected "
                 "to." if sme_vars.is_proxy(name) else "")
        out.append(_field(
            name, variable.label, variable.definition + proxy,
            {"NUMERIC": "number", "CATEGORICAL": "string",
             "FLAG": "integer"}[variable.kind],
            variable.unit))
    return out


def _woe_fields() -> list[dict[str, Any]]:
    """The approved bin and weight-of-evidence columns.

    Two columns per binned variable, and the distinction between them is the
    reason stability analysis works: `_bin` is which approved bucket the
    value fell in, `_woe` is what the model reads. A drift report on the raw
    value and a drift report on the bin populations answer different
    questions, and `metrics.csi` insists on the second.
    """
    out: list[dict[str, Any]] = []
    for name in build_mod.BINNED_VARIABLES:
        label = sme_vars.get(name).label
        out.append(_field(f"{name}_bin", f"{label} — approved bin",
                          "Which approved bin this value fell in.", "string"))
        out.append(_field(f"{name}_woe", f"{label} — weight of evidence",
                          "The weight of evidence the model reads for this "
                          "bin. Mapped from the approved specification, never "
                          "refitted at validation time.", "number"))
    return out


def _score_fields() -> list[dict[str, Any]]:
    return [
        _field("champion_score", "Champion score",
               "Points score from the active champion. Higher is better "
               "credit quality — declared on the model registry, never "
               "inferred from the data.", "number", "score"),
        _field("champion_pd_12m", "Champion PD",
               "Twelve-month probability of default from the champion's "
               "score-to-PD calibration. A separate governed component from "
               "the score itself.", "number", "rate"),
        _field("challenger_score", "Challenger score",
               "Points score from the registered challenger.", "number",
               "score"),
        _field("challenger_pd_12m", "Challenger PD",
               "Twelve-month probability of default from the challenger.",
               "number", "rate"),
        _field("final_risk_grade", "Risk grade",
               "The grade the score maps to on the approved scale.",
               "string"),
    ]


def _policy_fields(*, with_reason: bool = True) -> list[dict[str, Any]]:
    """Decision, override and the reason recorded against it.

    `with_reason` exists because the reason code is written only to the
    decisions dataset. Declaring it on the other two was caught by
    `_only_what_was_built`, which dropped it and logged the name — the guard
    working exactly as intended. Fixing the declaration is still the right
    response: a catalogue that is correct only because a reconciliation step
    silently repairs it describes the artefact rather than the intent, and
    the next reader cannot tell which fields were meant.
    """
    made = [
        _field("approval_decision", "Decision",
               "APPROVE or DECLINE as finally recorded, which is not always "
               "what the score implied.", "string"),
        _field("override_flag", "Overridden",
               "1 where the final decision departed from the score.",
               "integer"),
        _field("override_direction", "Override direction",
               "UPWARD where an application below the cut-off was approved, "
               "DOWNWARD where one above it was declined.", "string"),
    ]
    if with_reason:
        made.append(_field(
            "override_reason_code", "Override reason",
            "The reason recorded against the override.", "string"))
    return made


def _outcome_fields() -> list[dict[str, Any]]:
    return [
        _field("actual_default_12m", "Realised default",
               "1 where the obligor defaulted within twelve months of the "
               "score date. Null where the window has not closed — null "
               "means not yet known, and is never a zero.", "integer"),
    ]


#: Which of the ninety variables are carried on the built dataset. The
#: generator writes the ones the two models read plus the diagnostic and
#: segmentation fields; the rest of the dictionary describes candidates that
#: a future model version could take, and declaring them here would put
#: columns in the catalogue that the build does not write.
_CARRIED: tuple[str, ...] = (
    "enterprise_size_class_proxy", "economic_sector", "region",
    "key_person_dependency", "employee_count", "annual_revenue_sar",
    "years_since_registration", "bank_credits_to_declared_sales",
    "payroll_regularity_score", "balance_to_credits_ratio",
    "balance_volatility", "top_customer_share", "returned_cheques_12m",
    "overdraft_days_12m", "max_dpd_12m", "ebitda_margin", "debt_to_ebitda",
    "dscr", "current_ratio", "revenue_growth_yoy", "receivable_days",
    "commercial_bureau_score_proxy",
)


def _dataset(name: str, *, business_name: str, purpose: str, grain: str,
             keys: list[str], authoritative_for: list[str],
             fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "domain": DOMAIN_NAME,
        "business_name": business_name,
        "purpose": purpose,
        "grain": grain,
        "primary_keys": keys,
        "period_field": "cohort_month",
        "owner": OWNER,
        "status": "active",
        "version": "1.0.0",
        "is_synthetic": True,
        "origin": synth.ORIGIN,
        "dataset_family": DATASET_FAMILY[name],
        "authoritative_for": authoritative_for,
        "fields": fields,
    }


def datasets() -> list[dict[str, Any]]:
    """The three SME datasets, as catalogue entries."""
    full = (_control_fields() + _variable_fields() + _woe_fields()
            + _score_fields() + _policy_fields(with_reason=False)
            + _outcome_fields())
    return [
        _dataset(
            build_mod.MONTHLY,
            business_name="SME Scorecard Monthly Validation",
            purpose=(
                "One row per SME application per cohort, scored by the "
                "champion and the challenger, with the realised twelve-month "
                "outcome where the performance window has closed."),
            grain="One row per application.",
            keys=["cohort_month", "application_id"],
            authoritative_for=["sme_scorecard_scoring"],
            fields=full),
        _dataset(
            build_mod.DEVELOPMENT,
            business_name="SME Scorecard Development Reference",
            purpose=(
                "The out-of-time population the approved binning was fitted "
                "on, and the calibration with it. The default baseline for "
                "every stability comparison."),
            grain="One row per development-window application.",
            keys=["cohort_month", "application_id"],
            authoritative_for=["sme_scorecard_development_reference"],
            fields=full),
        _dataset(
            build_mod.DECISIONS,
            business_name="SME Scorecard Decisions and Overrides",
            purpose=(
                "What was actually decided: the score, the grade, the "
                "decision, whether it was overridden and why, and how the "
                "overridden cases performed. A narrow view on purpose — a "
                "decision file that repeats every predictor invites somebody "
                "to answer a model question from it."),
            grain="One row per application decision.",
            keys=["cohort_month", "application_id"],
            authoritative_for=["sme_scorecard_decisions"],
            fields=(_control_fields()
                    + [f for f in _variable_fields()
                       if f["name"] in ("enterprise_size_class_proxy",
                                        "economic_sector", "region")]
                    + [f for f in _score_fields()
                       if f["name"] in ("champion_score", "champion_pd_12m",
                                        "final_risk_grade")]
                    + _policy_fields() + _outcome_fields())),
    ]


#: The joins that are allowed. Stability is measured against the development
#: population; the decisions file joins back to the scored population on the
#: application. There is no join to anything outside the SME domain, and that
#: is the point rather than an omission.
RELATIONSHIPS: tuple[dict[str, Any], ...] = (
    {
        "from_dataset": build_mod.MONTHLY,
        "to_dataset": build_mod.DEVELOPMENT,
        "kind": "BASELINE_COMPARISON",
        "on": ["cohort_month"],
        "why": "Stability is measured against the development population.",
    },
    {
        "from_dataset": build_mod.DECISIONS,
        "to_dataset": build_mod.MONTHLY,
        "kind": "ONE_TO_ONE",
        "on": ["cohort_month", "application_id"],
        "why": "The decision taken on a scored application.",
    },
)


def merge_into_catalogue(path: Path | None = None) -> dict[str, Any]:
    """Add the SME datasets to the governed catalogue, in place.

    Merges rather than rewrites: anything already registered is left exactly
    as it was, and re-running replaces only the SME entries.
    """
    from backend.config import settings

    target = path or (Path(settings.metadata_dir) / "catalog.json")
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
        "sme_datasets": sorted(names),
        "total_datasets": len(catalogue["datasets"]),
        "relationships_declared": len(RELATIONSHIPS),
        "all_synthetic": all(d["is_synthetic"] for d in ours),
    }


def summary() -> dict[str, Any]:
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "domain": DOMAIN_NAME,
        "datasets": {d["name"]: d["dataset_family"] for d in datasets()},
        "variables_carried": len(_CARRIED),
        "variables_declared": len(sme_vars.SME),
        "origin": synth.ORIGIN,
        "governed_but_restricted": (
            "These datasets are registered in the governed catalogue and "
            "restricted from the general Cockpit at the same time. Being in "
            "the catalogue is a governance record; being readable is a "
            "separate decision, and an ungoverned dataset would be worse "
            "than a restricted one."),
        "not_client_data": (
            "Every row is generated. It describes no real business and no "
            "real bank's book, and every row carries origin = "
            f"{synth.ORIGIN}."),
    }


__all__ = [
    "CATALOGUE_VERSION", "DATASET_FAMILY", "DOMAIN_NAME", "RELATIONSHIPS",
    "datasets", "merge_into_catalogue", "summary",
]
