"""
The machine-readable data dictionary and semantic rules. Brief §3.3, §3.4.

For each measure this records the things that make a figure mean one thing
rather than another: its grain, unit, currency, period basis, how it may be
aggregated, what denominator or weight is approved for it, which direction is
good, and what a null means. The Cockpit's tools read this rather than guessing
from a column name, which is what stops a portfolio PD being computed by taking
the arithmetic mean of a PD column.

Three rules that are enforced rather than documented
-----------------------------------------------------
* **Ratios are never summed.** Every ratio carries `aggregation: "not_additive"`
  and an approved weighted form. A tool asked to sum one refuses.
* **Rating labels are never averaged.** `rating_approved_grade` is ordinal-
  labelled; its numeric partner `rating_rank` carries the approved aggregation.
* **A portfolio PD needs a horizon and a weight.** Both are named in the
  measure definition and both are surfaced in the Trace.
"""

from __future__ import annotations

from typing import Any

from backend.cockpit_v2 import DATA_VERSION, DOMAIN, MODEL_VERSION, POLICY_VERSION
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2.generate import AMOUNT_UNIT, REPORTING_CURRENCY

SCHEMA_VERSION = "1.0.0"

#: Aggregation rules a measure may declare.
ADDITIVE = "additive"
NOT_ADDITIVE = "not_additive"
ORDINAL = "ordinal"
POINT_IN_TIME = "point_in_time"

#: Interpretation direction, so the Cockpit knows whether up is good.
HIGHER_IS_WORSE = "higher_is_worse"
HIGHER_IS_BETTER = "higher_is_better"
NEUTRAL = "neutral"


def measure(name: str, label: str, definition: str, *, unit: str,
            aggregation: str, direction: str = NEUTRAL,
            formula: str = "", denominator: str = "", weight: str = "",
            horizon: str = "", valid_min: float | None = None,
            valid_max: float | None = None, null_means: str = "",
            aliases: tuple[str, ...] = (), period_basis: str = "point in time",
            ) -> dict[str, Any]:
    return {
        "name": name, "label": label, "definition": definition, "unit": unit,
        "currency": (REPORTING_CURRENCY if unit == AMOUNT_UNIT else ""),
        "aggregation": aggregation, "direction": direction,
        "formula": formula, "approved_denominator": denominator,
        "approved_weight": weight, "horizon": horizon,
        "valid_min": valid_min, "valid_max": valid_max,
        "null_means": null_means, "aliases": list(aliases),
        "period_basis": period_basis,
        "entity_grain": "facility x reporting date",
    }


MEASURES: tuple[dict[str, Any], ...] = (
    measure("exposure", "Exposure",
            "Drawn balance plus the whole undrawn commitment. Distinct from "
            "EAD, which converts only part of the undrawn amount.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE, direction=NEUTRAL,
            formula="drawn_amount + undrawn_commitment",
            aliases=("outstanding", "total exposure", "limit utilisation base"),
            null_means="the facility was not on the book at this date"),
    measure("ead", "Exposure at default",
            "Drawn balance plus the credit conversion factor applied to the "
            "undrawn commitment. NOT the same number as exposure.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE,
            formula="drawn_amount + ccf * undrawn_commitment",
            aliases=("exposure at default",)),
    measure("drawn_amount", "Drawn amount", "The balance actually outstanding.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE),
    measure("undrawn_commitment", "Undrawn commitment",
            "Committed but not drawn.", unit=AMOUNT_UNIT, aggregation=ADDITIVE),
    measure("gross_carrying_amount", "Gross carrying amount",
            "The carrying amount before impairment allowance.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE),
    measure("limit", "Limit", "The approved facility limit.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE),
    measure("weighted_model_ecl", "Modelled ECL",
            "Scenario-probability-weighted expected credit loss from the "
            "governed calculator, BEFORE any management overlay.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE, direction=HIGHER_IS_WORSE,
            formula="sum over scenarios of scenario_weight * scenario_ecl"),
    measure("overlay", "Management overlay",
            "Separately identified management overlay. Never blended into a "
            "parameter and never inferred from the modelled result.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE, direction=HIGHER_IS_WORSE),
    measure("reported_ecl", "Reported ECL",
            "Modelled ECL plus the separately identified overlay. This is the "
            "impairment allowance the Cockpit reports.",
            unit=AMOUNT_UNIT, aggregation=ADDITIVE, direction=HIGHER_IS_WORSE,
            formula="weighted_model_ecl + overlay",
            aliases=("ECL", "provision", "impairment allowance", "allowance")),
    measure("weighted_twelve_month_pd", "Weighted 12-month PD",
            "Scenario-weighted probability of default within twelve months. "
            "A DESCRIPTIVE summary: multiplying it by weighted LGD and EAD "
            "does not reproduce the weighted ECL.",
            unit="probability", aggregation=NOT_ADDITIVE,
            direction=HIGHER_IS_WORSE, horizon="12 months",
            denominator="ead", weight="ead",
            valid_min=0.0, valid_max=1.0,
            aliases=("PD", "12m PD", "one-year PD"),
            null_means="not measured for this facility at this date"),
    measure("weighted_lifetime_pd", "Weighted lifetime PD",
            "Scenario-weighted cumulative probability of default over the "
            "remaining measurement window. The sum of marginal default "
            "probabilities, never an annual PD multiplied by a number of years.",
            unit="probability", aggregation=NOT_ADDITIVE,
            direction=HIGHER_IS_WORSE, horizon="remaining life",
            denominator="ead", weight="ead", valid_min=0.0, valid_max=1.0,
            aliases=("lifetime PD",)),
    measure("weighted_lgd", "Weighted LGD",
            "Scenario-weighted effective loss severity, weighted within each "
            "scenario by where default mass actually falls.",
            unit="probability", aggregation=NOT_ADDITIVE,
            direction=HIGHER_IS_WORSE, denominator="ead", weight="ead",
            valid_min=0.0, valid_max=1.0, aliases=("LGD", "loss given default")),
    measure("coverage_ratio", "ECL coverage",
            "Reported ECL as a proportion of exposure.",
            unit="ratio", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_WORSE,
            formula="reported_ecl / exposure", denominator="exposure",
            aliases=("provision coverage", "ECL coverage ratio")),
    measure("collateral_coverage_ratio", "Collateral coverage",
            "Allocated recognised collateral as a proportion of exposure, "
            "capped at one. Allocation is pro rata to exposure across the "
            "facilities that share an asset, so a shared property is counted "
            "once.",
            unit="ratio", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_BETTER,
            denominator="exposure", valid_min=0.0, valid_max=1.0),
    measure("utilisation", "Utilisation", "Drawn balance over limit.",
            unit="ratio", aggregation=NOT_ADDITIVE, direction=NEUTRAL,
            formula="drawn_amount / limit", denominator="limit",
            valid_min=0.0, valid_max=1.0),
    measure("rating_rank", "Rating rank",
            "Ordinal position on the demo master scale; higher is weaker. The "
            "numeric partner of the grade label, so a portfolio movement can "
            "be expressed in notches without averaging letters.",
            unit="notches", aggregation=ORDINAL, direction=HIGHER_IS_WORSE,
            weight="exposure", valid_min=1.0, valid_max=13.0),
    measure("stage", "IFRS 9 stage",
            "1, 2 or 3 under the stated demo SICR policy.",
            unit="stage", aggregation=ORDINAL, direction=HIGHER_IS_WORSE,
            valid_min=1.0, valid_max=3.0),
    measure("days_past_due", "Days past due", "Days past due at the date.",
            unit="days", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_WORSE,
            valid_min=0.0),
    measure("ratio_dscr", "DSCR",
            "Cash available for debt service over scheduled principal plus "
            "cash interest, on a twelve-month basis.",
            unit="times", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_BETTER,
            formula="cash_available_for_debt_service / (scheduled_principal + cash_interest)",
            denominator="scheduled_principal + cash_interest",
            period_basis="annualised from the latest available statement",
            null_means="the denominator is zero or negative, or no statement "
                       "is available; not a DSCR of nought",
            aliases=("debt service coverage", "debt service cover")),
    measure("ratio_net_debt_to_ebitda", "Net debt / EBITDA",
            "Total debt less cash over annualised EBITDA. Debt, not total "
            "liabilities.",
            unit="times", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_WORSE,
            formula="(total_debt - cash) / ebitda",
            null_means="EBITDA is zero or negative, so the multiple is not "
                       "meaningful"),
    measure("ratio_interest_coverage", "Interest coverage",
            "EBIT over interest expense, annualised.",
            unit="times", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_BETTER),
    measure("ratio_current_ratio", "Current ratio",
            "Total current assets over current liabilities.",
            unit="times", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_BETTER),
    measure("ratio_quick_ratio", "Quick ratio",
            "Current assets less inventory over current liabilities.",
            unit="times", aggregation=NOT_ADDITIVE, direction=HIGHER_IS_BETTER),
    measure("covenants_breached", "Covenants breached",
            "Count of covenant tests breached at this date.",
            unit="count", aggregation=ADDITIVE, direction=HIGHER_IS_WORSE),
    measure("covenant_worst_headroom", "Worst covenant headroom",
            "The smallest headroom across this borrower's tests, in the "
            "metric's own units. Negative means breached.",
            unit="metric units", aggregation=NOT_ADDITIVE,
            direction=HIGHER_IS_BETTER),
)

MEASURE_BY_NAME = {m["name"]: m for m in MEASURES}

#: Aliases a user may reasonably type, mapped to the governed measure.
ALIAS_TO_MEASURE: dict[str, str] = {}
for _m in MEASURES:
    ALIAS_TO_MEASURE[_m["name"].lower()] = _m["name"]
    ALIAS_TO_MEASURE[_m["label"].lower()] = _m["name"]
    for _a in _m["aliases"]:
        ALIAS_TO_MEASURE[_a.lower()] = _m["name"]


#: Dimensions the snapshot may be grouped or filtered by.
DIMENSIONS: tuple[dict[str, Any], ...] = (
    {"name": "sector", "label": "Sector", "kind": "categorical"},
    {"name": "subsector", "label": "Subsector", "kind": "categorical"},
    {"name": "geography", "label": "Geography", "kind": "categorical"},
    {"name": "segment", "label": "Segment", "kind": "categorical"},
    {"name": "borrower_type", "label": "Borrower type", "kind": "categorical"},
    {"name": "product", "label": "Product", "kind": "categorical"},
    {"name": "business_unit", "label": "Business unit", "kind": "categorical"},
    {"name": "stage", "label": "IFRS 9 stage", "kind": "ordinal"},
    {"name": "rating_approved_grade", "label": "Approved rating",
     "kind": "ordinal",
     "note": "A label. Never averaged; use rating_rank for arithmetic."},
    {"name": "borrower_id", "label": "Borrower", "kind": "entity"},
    {"name": "group_id", "label": "Connected group", "kind": "entity",
     "note": "Aggregate to the group by summing facility rows once. A "
             "borrower with three facilities is one borrower."},
    {"name": "facility_id", "label": "Facility", "kind": "entity"},
)
DIMENSION_NAMES = tuple(d["name"] for d in DIMENSIONS)


#: Grain and keys. Brief §3.2.
GRAIN: dict[str, dict[str, Any]] = {
    "cockpit_quarter": {
        "grain": "One row per facility per reporting date.",
        "primary_keys": ["dataset_version", "facility_id", "reporting_date"],
        "linkage_keys": ["borrower_id", "group_id"],
        "period_field": "period",
    },
    "cockpit_credit_history": {
        "grain": "One row per facility per reporting date, across every "
                 "published quarter.",
        "primary_keys": ["dataset_version", "facility_id", "reporting_date"],
        "linkage_keys": ["borrower_id", "group_id"],
        "period_field": "period",
    },
    "cockpit_borrower_financials": {
        "grain": "One row per borrower per statement, as at each reporting "
                 "date the statement was the latest available one.",
        "primary_keys": ["borrower_id", "statement_id", "reporting_date"],
        "linkage_keys": ["borrower_id"],
        "period_field": "period",
        "note": "Statements repeat across reporting dates because the same "
                "statement stays the latest available one for several "
                "quarters. Summing a financial across facility rows is "
                "therefore double counting, and the semantic rules forbid it.",
    },
    "cockpit_collateral_assets": {
        "grain": "One row per collateral asset per valuation version per "
                 "reporting date.",
        "primary_keys": ["collateral_id", "reporting_date"],
        "linkage_keys": ["borrower_id"],
        "period_field": "period",
    },
    "cockpit_collateral_allocation": {
        "grain": "One row per collateral asset per facility per reporting date.",
        "primary_keys": ["collateral_id", "facility_id", "reporting_date"],
        "linkage_keys": ["borrower_id"],
        "period_field": "period",
    },
    "cockpit_covenant_tests": {
        "grain": "One row per covenant obligation per test date.",
        "primary_keys": ["obligation_id", "test_date"],
        "linkage_keys": ["borrower_id", "facility_id"],
        "period_field": "period",
    },
    "cockpit_scenario_parameters": {
        "grain": "One row per facility per scenario per reporting date.",
        "primary_keys": ["facility_id", "scenario_id", "reporting_date"],
        "linkage_keys": ["borrower_id"],
        "period_field": "period",
    },
    "cockpit_risk_curves": {
        "grain": "One row per facility per scenario per future period.",
        "primary_keys": ["facility_id", "scenario_id", "future_period",
                         "reporting_date"],
        "linkage_keys": ["borrower_id"],
        "period_field": "period",
    },
    "cockpit_macro_paths": {
        "grain": "One row per geography per predictor per forecast vintage "
                 "per scenario per forecast period.",
        "primary_keys": ["geography", "predictor", "forecast_vintage",
                         "scenario_id", "forecast_period"],
        "linkage_keys": ["geography"],
        "period_field": "forecast_period",
    },
    "cockpit_movements": {
        "grain": "One row per facility per reporting date, against its "
                 "matched prior period.",
        "primary_keys": ["facility_id", "reporting_date"],
        "linkage_keys": ["borrower_id"],
        "period_field": "period",
        "note": "A versioned cached derivative of the snapshots, not an "
                "independent source of truth. It carries the data version it "
                "was computed from and is regenerated with the book.",
    },
}


#: Portfolio summaries, with the horizon and weighting basis named. Brief §3.4.
PORTFOLIO_SUMMARIES: tuple[dict[str, Any], ...] = (
    {"name": "portfolio_twelve_month_pd",
     "label": "Portfolio 12-month PD (EAD-weighted)",
     "measure": "weighted_twelve_month_pd", "horizon": "12 months",
     "weight": "ead",
     "formula": "sum(weighted_twelve_month_pd * ead) / sum(ead)",
     "note": "An EAD-weighted average, not a mean of the column. The weight "
             "is shown in the Trace because an equally weighted PD and an "
             "exposure-weighted PD are different numbers."},
    {"name": "portfolio_lifetime_pd",
     "label": "Portfolio lifetime PD (EAD-weighted)",
     "measure": "weighted_lifetime_pd", "horizon": "remaining life",
     "weight": "ead",
     "formula": "sum(weighted_lifetime_pd * ead) / sum(ead)"},
    {"name": "portfolio_lgd", "label": "Portfolio LGD (EAD-weighted)",
     "measure": "weighted_lgd", "weight": "ead",
     "formula": "sum(weighted_lgd * ead) / sum(ead)"},
    {"name": "portfolio_coverage", "label": "Portfolio ECL coverage",
     "measure": "coverage_ratio", "weight": "",
     "formula": "sum(reported_ecl) / sum(exposure)",
     "note": "A ratio of components. It is NOT the average of the facility "
             "coverage ratios, and the two differ whenever exposure is not "
             "evenly spread."},
    {"name": "portfolio_dscr_components",
     "label": "Portfolio DSCR (ratio of components)",
     "measure": "ratio_dscr", "weight": "",
     "formula": "sum(cash_available_for_debt_service) / sum(scheduled_principal + cash_interest)",
     "note": "A ratio of summed components. Distinct from the distribution "
             "of borrower DSCRs and from their exposure-weighted average; "
             "the Cockpit says which one it is reporting."},
    {"name": "portfolio_dscr_weighted",
     "label": "Portfolio DSCR (exposure-weighted average of borrower ratios)",
     "measure": "ratio_dscr", "weight": "exposure",
     "formula": "sum(ratio_dscr * exposure) / sum(exposure) over borrowers "
                "with an available DSCR",
     "note": "Borrowers with no available DSCR are excluded and counted, "
             "rather than treated as zero."},
    {"name": "concentration_top_group_share",
     "label": "Largest connected group share of exposure",
     "measure": "exposure", "weight": "",
     "formula": "max over group_id of sum(exposure) / total sum(exposure)",
     "note": "Facility rows are summed once per group. A borrower with three "
             "facilities is one borrower and is not counted three times."},
)


FORBIDDEN: tuple[dict[str, str], ...] = (
    {"rule": "no_sum_of_ratios",
     "detail": "A measure declared not_additive may not be summed. Ask for "
               "its approved weighted form instead."},
    {"rule": "no_average_of_grades",
     "detail": "A rating grade is a label. Aggregate rating_rank, and report "
               "the result in notches."},
    {"rule": "no_pd_without_horizon",
     "detail": "A PD reported without its horizon is two different measures "
               "wearing one name."},
    {"rule": "no_financial_sum_across_facilities",
     "detail": "Borrower financials repeat across a borrower's facility rows. "
               "Deduplicate to borrower grain before summing."},
    {"rule": "no_weighted_parameter_product",
     "detail": "weighted PD x weighted LGD x weighted EAD is not the weighted "
               "ECL and may not be presented as a way of computing it."},
    {"rule": "no_basis_points_on_currency",
     "detail": "A currency movement has no basis-point form. Report it in the "
               "reporting currency."},
)


def data_dictionary() -> dict[str, Any]:
    """Everything above, as one machine-readable document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "domain": DOMAIN,
        "reporting_currency": REPORTING_CURRENCY,
        "amount_unit": AMOUNT_UNIT,
        "quarter_semantics": cal.QUARTER_SEMANTICS,
        "published_quarters": list(cal.QUARTERS),
        "measures": [dict(m) for m in MEASURES],
        "dimensions": [dict(d) for d in DIMENSIONS],
        "grain": {k: dict(v) for k, v in GRAIN.items()},
        "portfolio_summaries": [dict(s) for s in PORTFOLIO_SUMMARIES],
        "forbidden": [dict(f) for f in FORBIDDEN],
    }


def resolve_measure(text: str) -> str:
    """The governed measure a user's words name, or an empty string."""
    return ALIAS_TO_MEASURE.get(str(text).strip().lower(), "")


__all__ = ["ADDITIVE", "ALIAS_TO_MEASURE", "DIMENSIONS", "DIMENSION_NAMES",
           "FORBIDDEN", "GRAIN", "HIGHER_IS_BETTER", "HIGHER_IS_WORSE",
           "MEASURES", "MEASURE_BY_NAME", "NEUTRAL", "NOT_ADDITIVE", "ORDINAL",
           "PORTFOLIO_SUMMARIES", "SCHEMA_VERSION", "data_dictionary",
           "measure", "resolve_measure"]
