"""
Publishing the quarterly packages into the governed catalogue. Brief §3.1, §3.4.

One selectable dataset per calendar quarter, in a NEW `Cockpit Demo` domain.
Nothing already in the catalogue is deleted, renamed or overwritten: the merge
replaces only entries this module owns and leaves every other dataset and every
other relationship exactly as it found them.

Why the quarterly dataset is wide
----------------------------------
Brief §3.1 asks that a quarter be one logical package the user does not have to
join together. So the per-quarter dataset carries the facility snapshot with
the one-to-many details ALREADY PRE-AGGREGATED to facility grain — collateral
coverage, covenant counts and worst headroom, the borrower's latest available
statement and its ratios, the per-scenario ECLs. "Break ECL down by stage and
sector" then needs no join at all, which is precisely what the base build could
not do: it answered that question with
`cannot join ifrs9_staging to portfolio_facility: no active relationship
connects them`.

The real detail rows are not thrown away. They live in the package's detail
datasets, are declared as ONE_TO_MANY relationships from the snapshot, and are
what drill-down reads. A facility with three collateral assets and four
covenants is ONE row in the snapshot and seven rows across the details, and the
integrity gates assert that it never becomes twelve counted exposures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from backend.cockpit_v2 import DATA_VERSION, DOMAIN, MODEL_VERSION, NOT_CLIENT_DATA, ORIGIN, POLICY_VERSION
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import schema as schema_mod
from backend.cockpit_v2.generate import AMOUNT_UNIT, REPORTING_CURRENCY

logger = logging.getLogger(__name__)

CATALOGUE_VERSION = "1.0.0"

#: The governed name of the interface that spans every published quarter.
HISTORY_DATASET = "cockpit_credit_history"

#: The detail datasets of the package. Each spans every published quarter and
#: is period-partitioned; each is reachable only through a declared join.
DETAIL_DATASETS: tuple[str, ...] = (
    "cockpit_borrower_financials",
    "cockpit_collateral_assets",
    "cockpit_collateral_allocation",
    "cockpit_covenant_tests",
    "cockpit_scenario_parameters",
    "cockpit_risk_curves",
    "cockpit_macro_paths",
    "cockpit_movements",
)

#: The family every quarterly snapshot shares, so the platform treats the eight
#: quarters as repeated snapshots of one logical dataset rather than as eight
#: unrelated tables.
QUARTER_FAMILY = "cockpit_quarter"

_TYPES = {
    "int64": "integer", "Int64": "integer", "int32": "integer",
    "float64": "number", "float32": "number", "Float64": "number",
    "bool": "boolean", "boolean": "boolean",
    "object": "string", "string": "string",
    "datetime64[ns]": "date",
}

_PURPOSE = {
    HISTORY_DATASET: (
        "The authorised history interface. Every published quarter of the "
        "Cockpit demo facility snapshot, with one consistent schema, so the "
        "Cockpit can select and combine compatible quarters without searching "
        "unrelated domains."),
    "cockpit_borrower_financials": (
        "The borrower's latest AVAILABLE statement at each reporting date, "
        "with its ratios and its age. Repeated across reporting dates by "
        "design; deduplicate to borrower grain before summing."),
    "cockpit_collateral_assets": (
        "Collateral assets with valuation, valuation age, haircut and "
        "recognised value."),
    "cockpit_collateral_allocation": (
        "How each asset's recognised value is allocated across the facilities "
        "it secures. The allocations for one asset sum to at most its "
        "recognised value, so a shared property is counted once."),
    "cockpit_covenant_tests": (
        "Covenant obligations: the contractual formula, threshold, operator, "
        "observed value, headroom, breach and waiver validity."),
    "cockpit_scenario_parameters": (
        "Per-scenario PD, LGD, CCF, EAD and scenario ECL for each facility."),
    "cockpit_risk_curves": (
        "The conditional default hazard, survival and marginal default "
        "probability by future period, per facility and scenario."),
    "cockpit_macro_paths": (
        "Macroeconomic actuals and scenario forecasts by geography, predictor, "
        "forecast vintage and forecast period."),
    "cockpit_movements": (
        "Matched-prior movements. A versioned cached derivative of the "
        "snapshots, carrying the data version it was computed from."),
}

_DEFINITIONS: dict[str, str] = {
    m["name"]: f"{m['label']}. {m['definition']}"
    for m in schema_mod.MEASURES}


def _humanise(name: str) -> str:
    words = name.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _unit(name: str) -> str | None:
    described = schema_mod.MEASURE_BY_NAME.get(name)
    if described:
        return described["unit"]
    if name.endswith("_days"):
        return "days"
    if name.endswith("_pp"):
        return "percentage points"
    if name.endswith("_bps"):
        return "basis points"
    if name.startswith("ecl_") or name.endswith(("_amount", "_ecl", "_value")):
        return AMOUNT_UNIT
    if name.endswith(("_pd", "_lgd", "_ratio", "_share", "_weight")):
        return "probability" if name.endswith(("_pd", "_lgd")) else "ratio"
    if name.endswith("_date") or name in ("period", "reporting_date"):
        return None
    return None


def _definition(name: str) -> str:
    if name in _DEFINITIONS:
        return _DEFINITIONS[name]
    special = {
        "sicr_reason": ("Which rule of the stated SICR policy put this "
                        "facility in its stage, in words, at this date."),
        "measurement_method": ("The ECL method applied: the performing "
                               "component method, or the credit-impaired cash "
                               "shortfall method for Stage 3."),
        "is_npl": ("Non-performing under the stated demo policy, which "
                   "declares NPL and Stage 3 to coincide here. That is a demo "
                   "policy, not a universal identity."),
        "ccf": ("Credit conversion factor applied to the undrawn commitment "
                "to obtain EAD. Exposure does not use it."),
        "not_client_data": "The synthetic-data declaration carried on every row.",
        "origin": "SYNTHETIC_DEMO on every row of this dataset.",
    }
    if name in special:
        return special[name]
    return f"{_humanise(name)}."


def _field(name: str, series: pd.Series) -> dict[str, Any]:
    return {
        "name": name, "source_column": name,
        "business_name": (schema_mod.MEASURE_BY_NAME[name]["label"]
                          if name in schema_mod.MEASURE_BY_NAME
                          else _humanise(name)),
        "definition": _definition(name),
        "data_type": _TYPES.get(str(series.dtype), "string"),
        "unit": _unit(name),
        "sensitivity": "internal",
        "nullable": bool(series.isna().any()),
    }


def _entry(*, name: str, business_name: str, purpose: str, grain: str,
           primary_keys: list[str], period_field: str, frame: pd.DataFrame,
           family: str) -> dict[str, Any]:
    return {
        "name": name, "domain": DOMAIN, "business_name": business_name,
        "purpose": purpose, "grain": grain, "primary_keys": primary_keys,
        "period_field": period_field,
        "owner": "Cockpit Intelligence V2 (demonstration)",
        "status": "active", "version": DATA_VERSION,
        "is_synthetic": True, "origin": "demo",
        "dataset_family": family,
        # Deliberately authoritative for nothing. These datasets must never be
        # resolved as the answer to "give me the facility position" for the
        # rest of the product; they are the Cockpit demo's own book and the
        # Cockpit reaches them by name through its declared scope.
        "authoritative_for": [],
        "portfolio_scope": "credit_book",
        "fields": [_field(c, frame[c]) for c in frame.columns],
    }


def quarter_entries(per_quarter: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """One catalogue entry per published quarter."""
    out: list[dict[str, Any]] = []
    for label, frame in sorted(per_quarter.items()):
        grain = schema_mod.GRAIN["cockpit_quarter"]
        out.append(_entry(
            name=cal.dataset_name(label),
            business_name=cal.business_name(label),
            purpose=(
                f"The complete Cockpit demonstration package for "
                f"{cal.display(label)} — the calendar quarter ending "
                f"{cal.iso(label)}. One row per facility, with collateral, "
                f"covenant, financial, scenario and macro detail already "
                f"summarised to facility grain. {cal.QUARTER_SEMANTICS}"),
            grain=grain["grain"], primary_keys=list(grain["primary_keys"]),
            period_field=grain["period_field"], frame=frame,
            family=QUARTER_FAMILY))
    return out


def package_entries(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """The history interface and the detail datasets."""
    out: list[dict[str, Any]] = []
    for name in (HISTORY_DATASET, *DETAIL_DATASETS):
        frame = frames.get(name)
        if frame is None or frame.empty:
            continue
        grain = schema_mod.GRAIN.get(name, {})
        out.append(_entry(
            name=name,
            business_name=_humanise(name.replace("cockpit_", "Cockpit ")),
            purpose=_PURPOSE.get(name, _humanise(name)),
            grain=grain.get("grain", ""),
            primary_keys=list(grain.get("primary_keys", [])),
            period_field=grain.get("period_field", "period"),
            frame=frame,
            family=name))
    return out


def relationships(per_quarter: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """The declared joins. A join not listed here cannot be made.

    Every quarterly package points at the same detail datasets, so a user who
    selects one quarter can drill into that quarter's collateral, covenants,
    curves and macro without knowing anything about the physical layout.
    """
    out: list[dict[str, Any]] = []
    heads = [cal.dataset_name(q) for q in sorted(per_quarter)] + [HISTORY_DATASET]
    detail = {
        "cockpit_borrower_financials": (
            ["borrower_id", "period"], "AS_OF",
            "The statement that was the latest AVAILABLE one at this "
            "reporting date. Not a fiscal-year join: a statement the borrower "
            "had not filed yet was not information the bank had."),
        "cockpit_collateral_allocation": (
            ["facility_id", "period"], "ONE_TO_MANY",
            "Allocated recognised collateral. The snapshot carries the "
            "pre-aggregated total; this carries the rows behind it."),
        "cockpit_covenant_tests": (
            ["borrower_id", "period"], "ONE_TO_MANY",
            "Covenant tests are set at borrower scope in this demo. The "
            "snapshot carries the counts and the worst headroom."),
        "cockpit_scenario_parameters": (
            ["facility_id", "period"], "ONE_TO_MANY",
            "One row per scenario behind the snapshot's scenario columns."),
        "cockpit_risk_curves": (
            ["facility_id", "period"], "ONE_TO_MANY",
            "The hazard, survival and marginal default curve behind each "
            "scenario's PD."),
        "cockpit_movements": (
            ["facility_id", "period"], "ONE_TO_ONE",
            "The matched-prior movement for this facility at this date."),
    }
    for head in heads:
        for target, (on, kind, why) in detail.items():
            out.append({"from_dataset": head, "to_dataset": target,
                        "kind": kind, "on": on, "why": why})
        out.append({
            "from_dataset": head, "to_dataset": "cockpit_macro_paths",
            "kind": "AS_OF", "on": ["geography"],
            "why": ("The macro vintage issued on or before the reporting "
                    "date. A later vintage was not knowable at the quarter "
                    "end and must not be joined.")})
    out.append({
        "from_dataset": "cockpit_collateral_allocation",
        "to_dataset": "cockpit_collateral_assets",
        "kind": "MANY_TO_ONE", "on": ["collateral_id", "period"],
        "why": "Each allocation row belongs to one asset valuation."})
    return out


def merge_into_catalogue(*, per_quarter: dict[str, pd.DataFrame],
                         frames: dict[str, pd.DataFrame],
                         path: Path | None = None) -> dict[str, Any]:
    """Register the Cockpit demo datasets, disturbing nothing else.

    Entries and relationships whose names this module owns are replaced;
    everything else in the file is preserved byte for byte in content. An
    existing dataset from another domain cannot be removed by this function
    even if it were named the same, because the owned set is computed from what
    was just generated rather than from a prefix match on the file.
    """
    from backend.config import settings

    target = path or (settings.metadata_dir / "catalog.json")
    catalogue: dict[str, Any] = (
        json.loads(target.read_text("utf-8")) if target.exists()
        else {"version": "1.0.0", "datasets": []})

    ours = quarter_entries(per_quarter) + package_entries(frames)
    names = {d["name"] for d in ours}

    before = len(catalogue.get("datasets", []))
    kept = [d for d in catalogue.get("datasets", [])
            if d.get("name") not in names]
    catalogue["datasets"] = kept + ours

    our_relationships = relationships(per_quarter)
    kept_relationships = [r for r in catalogue.get("relationships", [])
                          if r.get("from_dataset") not in names]
    catalogue["relationships"] = kept_relationships + our_relationships

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalogue, indent=2), encoding="utf-8")

    return {
        "catalogue_version": CATALOGUE_VERSION,
        "path": str(target),
        "domain": DOMAIN,
        "quarterly_datasets": sorted(cal.dataset_name(q) for q in per_quarter),
        "package_datasets": sorted(names - {cal.dataset_name(q)
                                            for q in per_quarter}),
        "history_dataset": HISTORY_DATASET,
        "datasets_registered": len(ours),
        "datasets_preserved": len(kept),
        "datasets_before": before,
        "total_datasets": len(catalogue["datasets"]),
        "relationships_declared": len(our_relationships),
        "all_synthetic": all(d["is_synthetic"] for d in ours),
        "data_version": DATA_VERSION, "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "reporting_currency": REPORTING_CURRENCY, "amount_unit": AMOUNT_UNIT,
        "origin": ORIGIN, "not_client_data": NOT_CLIENT_DATA,
    }


__all__ = ["CATALOGUE_VERSION", "DETAIL_DATASETS", "HISTORY_DATASET",
           "QUARTER_FAMILY", "merge_into_catalogue", "package_entries",
           "quarter_entries", "relationships"]
