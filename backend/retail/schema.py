"""
The canonical data dictionary and the machine-readable data contract.

Every column of `retail_facility_month` is described here: what it means, its
type, its unit, whether one row's value is a stock, a flow, a ratio or a
descriptor, whether it belongs to the customer or the facility, how it may be
aggregated, and which products it applies to.

The aggregation semantics are not decoration. "Sum twenty-five monthly closing
balances and call it current portfolio exposure" is the single most common way
a monitoring answer goes wrong, and the only defence is for the metadata to
say, per column, that a balance is a stock and a write-off is a flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.retail.models_registry import (
    APP_FEATURES, BEH_FEATURES, APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS,
)
from backend.retail import taxonomy as tax

SCHEMA_VERSION = "retail-schema-1.0.0"

# Grain: whose property is this value?
CUSTOMER = "CUSTOMER"
FACILITY = "FACILITY"

# Aggregation semantics.
STOCK = "STOCK"            # a level at a point in time; never summed across months
FLOW = "FLOW"              # an amount for a period; summed within a period only
RATIO = "RATIO"            # needs an explicit numerator and denominator
DESCRIPTOR = "DESCRIPTOR"  # a label; counted, not summed
IDENTIFIER = "IDENTIFIER"
EVENT_DATE = "EVENT_DATE"
COUNT = "COUNT"
EVALUATION_LABEL = "EVALUATION_LABEL"  # outcome knowledge; never a predictor


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    business_name: str
    definition: str
    data_type: str
    unit: str | None = None
    grain: str = FACILITY
    semantics: str = DESCRIPTOR
    aggregation: str = "none"
    products: tuple[str, ...] = tax.PRODUCT_CODES
    nullable: bool = True
    null_policy: str = ""
    sensitivity: str = "internal"
    valid_range: tuple[float, float] | None = None
    as_of_meaning: str = "The month-end named by snapshot_date."
    lineage: str = "Synthetic retail generator"
    allowed_values: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "business_name": self.business_name,
            "definition": self.definition,
            "data_type": self.data_type,
            "unit": self.unit,
            "grain": self.grain,
            "semantics": self.semantics,
            "aggregation": self.aggregation,
            "products": list(self.products),
            "nullable": self.nullable,
            "null_policy": self.null_policy,
            "sensitivity": self.sensitivity,
            "valid_range": list(self.valid_range) if self.valid_range else None,
            "as_of_meaning": self.as_of_meaning,
            "lineage": self.lineage,
            "allowed_values": list(self.allowed_values) if self.allowed_values else None,
        }


def _title(name: str) -> str:
    words = name.replace("_", " ").strip()
    words = re.sub(r"\bsar\b", "SAR", words)
    words = re.sub(r"\bdpd\b", "DPD", words)
    words = re.sub(r"\bpd\b", "PD", words)
    words = re.sub(r"\blgd\b", "LGD", words)
    words = re.sub(r"\bead\b", "EAD", words)
    words = re.sub(r"\becl\b", "ECL", words)
    words = re.sub(r"\bltv\b", "LTV", words)
    words = re.sub(r"\bifrs9\b", "IFRS 9", words)
    words = re.sub(r"\bsicr\b", "SICR", words)
    words = re.sub(r"\bttc\b", "TTC", words)
    words = re.sub(r"\bpit\b", "PIT", words)
    words = re.sub(r"\bccf\b", "CCF", words)
    return words[:1].upper() + words[1:]


#: Columns whose meaning cannot be guessed from their name and must be stated.
CURATED: dict[str, ColumnSpec] = {}


def _c(name: str, **kw: Any) -> None:
    CURATED[name] = ColumnSpec(
        name=name,
        business_name=kw.pop("business_name", _title(name)),
        definition=kw.pop("definition", ""),
        data_type=kw.pop("data_type", "number"),
        **kw,
    )


# --- identity and chronology ------------------------------------------------
_c("snapshot_date", data_type="date", semantics=IDENTIFIER,
   definition="The month-end this row describes. A row is the state of one facility ON this date.",
   as_of_meaning="This IS the as-of date.")
_c("reporting_month", data_type="string", semantics=IDENTIFIER,
   definition="`snapshot_date` as YYYY-MM. The dataset's partition key.")
_c("dataset_version", data_type="string", semantics=IDENTIFIER,
   definition="Generator version, configuration version and seed, pinned at publication.")
_c("record_id", data_type="string", semantics=IDENTIFIER,
   definition="snapshot_date and facility_id joined. Unique within a published dataset version.")
_c("customer_id", data_type="string", semantics=IDENTIFIER, grain=CUSTOMER,
   sensitivity="confidential",
   definition="Synthetic natural-person customer identifier. Not a national ID and not a real account.")
_c("facility_id", data_type="string", semantics=IDENTIFIER, sensitivity="confidential",
   definition="Synthetic facility identifier, stable across every month the facility is live.")
_c("application_id", data_type="string", semantics=IDENTIFIER,
   definition="The originating application. One per booked facility in this demo book.")
_c("product_code", data_type="string", semantics=DESCRIPTOR, allowed_values=tax.PRODUCT_CODES,
   definition="Retail product family. The stable machine code; `product_label` is what a user reads.")
_c("months_on_book", data_type="integer", unit="months", semantics=STOCK,
   definition="Whole months from origination to this snapshot. Increases by exactly one per month.")
_c("origination_vintage", data_type="string", semantics=DESCRIPTOR,
   definition="Origination month as YYYY-MM. The cohort key for vintage analysis.")

# --- money: stocks ----------------------------------------------------------
for _n, _d in [
    ("outstanding_principal_sar", "Principal outstanding at this month-end, before accrued profit."),
    ("accrued_profit_interest_sar", "Profit or interest accrued and unpaid at this month-end."),
    ("gross_carrying_amount_sar",
     "Outstanding principal plus accrued profit. The exposure the loss allowance is measured against."),
    ("undrawn_commitment_sar", "Limit not drawn at this month-end. Card only."),
    ("available_limit_sar", "Limit still available to draw. Card only."),
    ("current_credit_limit_sar", "Approved card limit in force at this month-end."),
    ("overdue_amount_sar", "Amounts contractually due and unpaid at this month-end."),
    ("collateral_value_current_sar", "Latest valuation of the security held. Secured products only."),
    ("cumulative_writeoff_sar", "Total written off on this facility to date."),
]:
    _c(_n, data_type="number", unit="SAR", semantics=STOCK, aggregation="sum within one snapshot only",
       definition=_d + " A month-end LEVEL: summing it across months does not give a portfolio total.")

# --- money: flows -----------------------------------------------------------
for _n, _d in [
    ("scheduled_payment_due_sar", "Amount contractually due in this month."),
    ("actual_payment_received_sar", "Amount actually received in this month."),
    ("principal_repayment_sar", "Principal repaid in this month."),
    ("new_drawdown_sar", "New amounts drawn in this month."),
    ("accrued_charges_sar", "Profit or interest charged in this month."),
    ("capitalised_amount_sar", "Amounts capitalised into the balance in this month."),
    ("writeoff_amount_month_sar", "Amount written off in this month."),
    ("recovery_amount_month_sar", "Amount recovered in this month."),
    ("other_balance_adjustment_sar", "Any other movement in this month."),
]:
    _c(_n, data_type="number", unit="SAR", semantics=FLOW, aggregation="sum across months in a period",
       definition=_d + " A PERIOD amount: aggregate over the months of the period wanted.")

# --- ECL --------------------------------------------------------------------
for _n, _d in [
    ("ecl_base_sar", "Expected credit loss under the base scenario."),
    ("ecl_upturn_sar", "Expected credit loss under the upturn scenario."),
    ("ecl_downturn_sar", "Expected credit loss under the downturn scenario."),
    ("ecl_weighted_sar", "Probability-weighted ECL across the three scenarios."),
    ("management_overlay_sar", "Overlay applied on top of the modelled result. Kept separate and visible."),
    ("ecl_final_sar", "Weighted ECL plus overlay. The loss allowance carried for this facility."),
]:
    _c(_n, data_type="number", unit="SAR", semantics=STOCK, aggregation="sum within one snapshot only",
       definition=_d)
_c("ecl_coverage_ratio", data_type="number", unit="ratio", semantics=RATIO,
   aggregation="recompute from summed ECL over summed GCA; never average the ratio",
   definition="ecl_final_sar / gross_carrying_amount_sar. Null where the exposure is zero.")
_c("ifrs9_stage", data_type="integer", semantics=DESCRIPTOR, allowed_values=("1", "2", "3"),
   definition="IFRS 9 impairment stage under the versioned synthetic staging policy.")
_c("pd_ttc_12m", data_type="number", unit="probability", semantics=RATIO, valid_range=(0.0, 1.0),
   definition="Through-the-cycle 12-month default probability. NOT the application or behavioural "
              "model's PD, and not the point-in-time PD: the mapping between them is versioned.")
_c("pd_pit_12m_base", data_type="number", unit="probability", semantics=RATIO, valid_range=(0.0, 1.0),
   definition="Point-in-time 12-month default probability under the base scenario.")
_c("pd_pit_lifetime_base", data_type="number", unit="probability", semantics=RATIO, valid_range=(0.0, 1.0),
   definition="Cumulative default probability over the applicable remaining life, base scenario. "
              "A different quantity from the 12-month PD, not a rescaling of it.")
_c("ecl_horizon_months", data_type="integer", unit="months", semantics=DESCRIPTOR,
   definition="Months of DEFAULT EVENTS the calculation counts. Stage 1 counts twelve (or the shorter "
              "remaining life); it does not truncate the loss from those defaults at month twelve.")

# --- affordability ----------------------------------------------------------
_c("verified_total_monthly_income_sar", data_type="number", unit="SAR/month", semantics=STOCK,
   grain=CUSTOMER, aggregation="one value per customer; never multiplied by facility count",
   definition="Verified monthly salary plus verified other income. A CUSTOMER property repeated on "
              "each of their facilities: summing it over facility rows counts one income several times.")
_c("monthly_total_credit_obligations_sar", data_type="number", unit="SAR/month", semantics=STOCK,
   grain=CUSTOMER, aggregation="one value per customer",
   definition="Own-bank obligations, including this facility's instalment exactly once, plus verified "
              "external obligations.")
_c("debt_burden_ratio", data_type="number", unit="ratio", semantics=RATIO, grain=CUSTOMER,
   valid_range=(0.0, 5.0),
   definition="monthly_total_credit_obligations_sar / verified_total_monthly_income_sar at this snapshot.")
_c("disposable_income_sar", data_type="number", unit="SAR/month", semantics=STOCK, grain=CUSTOMER,
   definition="Verified income less household expenses less all credit obligations. Not salary, and "
              "not income: three different quantities kept in three different columns.")

# --- delinquency ------------------------------------------------------------
_c("dpd", data_type="integer", unit="days", semantics=STOCK, valid_range=(0, 3650),
   definition="Days past due at this month-end, derived from the oldest unpaid due date.")
_c("dpd_bucket", data_type="string", semantics=DESCRIPTOR, allowed_values=tax.DPD_BUCKETS,
   definition="`dpd` banded. CURRENT means zero days past due.")
_c("current_default_flag", data_type="boolean", semantics=DESCRIPTOR,
   definition="In default at this month-end under the versioned default definition: 90+ DPD, or "
              "recorded unlikeliness to pay. A cured facility is False here and keeps its "
              "`first_default_date`.")
_c("utilisation_ratio", data_type="number", unit="ratio", semantics=RATIO, products=(tax.CREDIT_CARD,),
   valid_range=(0.0, 3.0), null_policy="Null for every non-revolving product, with product applicability "
                                       "as the reason. Never zero.",
   definition="Drawn balance over current credit limit. Card only; an amortising loan has no utilisation.")

# --- outcome labels ---------------------------------------------------------
for _n, _d in [
    ("observed_default_within_window",
     "Whether a NEW default was observed in the twelve months after this snapshot."),
    ("observed_30plus_within_window", "Whether 30+ DPD was observed in the twelve months after."),
    ("observed_60plus_within_window", "Whether 60+ DPD was observed in the twelve months after."),
]:
    _c(_n, data_type="boolean", semantics=EVALUATION_LABEL, aggregation="evaluation only",
       null_policy="NULL where the window has not fully elapsed and no event was observed. An "
                   "unobserved non-default is NOT a good.",
       definition=_d + " An EVALUATION label. It became knowable at `outcome_known_at` and must never "
                       "be used as a predictor or shown as a current fact.")
_c("outcome_known_at", data_type="date", semantics=EVALUATION_LABEL,
   definition="The date the twelve-month outcome became knowable. Later than snapshot_date, always.")
_c("performance_window_complete_flag", data_type="boolean", semantics=EVALUATION_LABEL,
   definition="Whether all twelve follow-up months fall inside the published history.")
_c("monitoring_eligible_flag", data_type="boolean", semantics=EVALUATION_LABEL,
   definition="Whether this row belongs in a forward-default cohort: it is excluded if the facility "
              "was already in default at the prediction date.")

_SUFFIX_RULES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("_sar", {"data_type": "number", "unit": "SAR", "semantics": STOCK}),
    ("_ratio", {"data_type": "number", "unit": "ratio", "semantics": RATIO}),
    ("_months", {"data_type": "integer", "unit": "months", "semantics": STOCK}),
    ("_days", {"data_type": "integer", "unit": "days", "semantics": STOCK}),
    ("_date", {"data_type": "date", "semantics": EVENT_DATE}),
    ("_flag", {"data_type": "boolean", "semantics": DESCRIPTOR}),
    ("_count", {"data_type": "number", "semantics": COUNT}),
    ("_3m", {"data_type": "number", "semantics": COUNT}),
    ("_6m", {"data_type": "number", "semantics": COUNT}),
    ("_12m", {"data_type": "number", "semantics": COUNT}),
    ("_id", {"data_type": "string", "semantics": IDENTIFIER}),
    ("_version", {"data_type": "string", "semantics": IDENTIFIER}),
    ("_band", {"data_type": "string", "semantics": DESCRIPTOR}),
    ("_status", {"data_type": "string", "semantics": DESCRIPTOR}),
    ("_reason", {"data_type": "string", "semantics": DESCRIPTOR}),
    ("_label", {"data_type": "string", "semantics": DESCRIPTOR}),
    ("_pp", {"data_type": "number", "unit": "percentage points", "semantics": RATIO}),
)


def _model_feature_specs() -> dict[str, ColumnSpec]:
    """Specs for every flattened score column, taken from the model registry."""
    out: dict[str, ColumnSpec] = {}
    for cards, features, prefix, which in (
        (APPLICATION_SCORECARDS, APP_FEATURES, "app", "application"),
        (BEHAVIOURAL_SCORECARDS, BEH_FEATURES, "beh", "behavioural"),
    ):
        used_by: dict[str, list[str]] = {}
        for product, sc in cards.items():
            for f in sc.features:
                used_by.setdefault(f.short, []).append(product)
        for short, products in used_by.items():
            f = features[short]
            base = f"{prefix}_{short}"
            when = ("as at origination, and unchanged on every later snapshot"
                    if prefix == "app" else "recomputed at this month-end")
            out[f"{base}_raw"] = ColumnSpec(
                name=f"{base}_raw", business_name=f"{f.business_name} — raw",
                definition=f"{f.definition} Raw model input, {when}.",
                data_type="number" if f.kind == "numeric" else "string",
                unit=f.unit, semantics=RATIO if f.kind == "numeric" else DESCRIPTOR,
                products=tuple(products),
                null_policy="Null where this product's model does not use the feature.",
                lineage=f"Model input of the {which} scorecard(s) for {', '.join(sorted(products))}")
            out[f"{base}_transformed"] = ColumnSpec(
                name=f"{base}_transformed", business_name=f"{f.business_name} — weight of evidence",
                definition=("The bin's weight of evidence, ln(P(good)/P(bad)). Higher is safer. "
                            "This is the transformed value the model multiplies by its coefficient."),
                data_type="number", unit="WoE", semantics=RATIO, products=tuple(products))
            out[f"{base}_bin"] = ColumnSpec(
                name=f"{base}_bin", business_name=f"{f.business_name} — bin",
                definition="The frozen bin the raw value falls in. MISSING is its own bin.",
                data_type="string", semantics=DESCRIPTOR, products=tuple(products),
                allowed_values=tuple(f.labels) + ("MISSING",))
            out[f"{base}_missing_flag"] = ColumnSpec(
                name=f"{base}_missing_flag", business_name=f"{f.business_name} — missing",
                definition="Whether the raw input was absent and the missing bin was used.",
                data_type="boolean", semantics=DESCRIPTOR, products=tuple(products))
            out[f"{base}_points"] = ColumnSpec(
                name=f"{base}_points", business_name=f"{f.business_name} — points",
                definition=("This feature's contribution to the score: factor * coefficient * WoE. "
                            "Base points plus every feature's points equals the score exactly."),
                data_type="number", unit="points", semantics=RATIO, products=tuple(products))
    return out


def spec_for(name: str) -> ColumnSpec:
    """The dictionary entry for a column, curated or derived from its name.

    The order is deliberate. A hand-written entry wins; then the score columns
    the model registry describes; then the curated definitions in
    `backend/retail/dictionary.py`; and only then the name-shaped guess.

    The guess used to be the answer for 302 of the 546 columns, and it was
    wrong twice over. Its definition restated the column heading and pointed
    at a document generated from this same registry, so a reader who followed
    it arrived back at the sentence they had just read — and a bank's steward
    does not have this repository at all. And its TYPE was read off the name:
    a column whose name ends in nothing recognised was declared `string`, so
    `behavioural_score`, `lgd_base`, `ccf_base` and every point-in-time PD
    were declared text. `_rollup_for` will not average a string and falls back
    to `max`, so "the average behavioural score" was answered with the highest
    score in the book, under the word average.
    """
    if name in CURATED:
        return CURATED[name]
    models = _model_feature_specs()
    if name in models:
        return models[name]
    # Imported here rather than at the top: `dictionary` reads the semantics
    # constants from this module, and importing it at module scope would close
    # the circle.
    from backend.retail import dictionary

    curated = dictionary.spec_kwargs(name)
    if curated is not None:
        return ColumnSpec(name=name, business_name=_title(name), **curated)
    for suffix, kw in _SUFFIX_RULES:
        if name.endswith(suffix):
            return ColumnSpec(name=name, business_name=_title(name),
                              definition=f"{_title(name)}. See docs/RETAIL_DATA_DICTIONARY.md.", **kw)
    return ColumnSpec(name=name, business_name=_title(name), data_type="string",
                      definition=f"{_title(name)}. See docs/RETAIL_DATA_DICTIONARY.md.")


def build_dictionary(columns: Iterable[str]) -> list[ColumnSpec]:
    return [spec_for(c) for c in columns]


def data_contract(columns: Iterable[str]) -> dict[str, Any]:
    """The machine-readable import/publication contract for the canonical table."""
    specs = build_dictionary(columns)
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": "retail_facility_month",
        "display_name": "Cockpit Data",
        "grain": "One retail customer's ONE facility at ONE month-end.",
        "primary_key": ["snapshot_date", "customer_id", "facility_id"],
        "additional_unique_key": ["snapshot_date", "facility_id"],
        "period_field": "reporting_month",
        "currency": "SAR",
        "date_format": "Gregorian ISO-8601",
        "rate_convention": "Annual rates and ratios stored as decimals, not percentages.",
        "dpd_convention": "Integer days.",
        "tenor_convention": "Integer months.",
        "is_synthetic": True,
        "column_count": len(specs),
        "columns": [s.to_dict() for s in specs],
        "restricted_for_prediction": [
            s.name for s in specs if s.semantics == EVALUATION_LABEL
        ],
        "import_rules": [
            "Every column must be mapped explicitly; unmapped source columns are rejected.",
            "Probabilities arrive as decimals in [0, 1]. A percentage is not converted by guessing.",
            "Duplicate primary keys are rejected, never silently de-duplicated.",
            "Supplied historical outcome labels are treated as restricted monitoring labels and "
            "excluded from operational prediction views.",
            "Imported real data and synthetic rows are never mixed into one dataset version without "
            "separately labelled lineage.",
            "Corporate entity types, rating grades and company financial statements are out of scope "
            "and are rejected with a retail-only message.",
        ],
    }
