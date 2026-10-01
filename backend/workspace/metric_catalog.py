"""
The Metric Catalogue: governed, versioned, fully defined metric definitions.

Every Lens KPI, every Requires Attention card and every Monitoring rule names a
metric id and version from this registry -- there is no anonymous arithmetic
in a seeded object. A definition is complete only when its formula, numerator,
denominator, unit, scaling, aggregation, grain, eligible population,
exclusions, null treatment, period semantics, domain applicability,
directionality, thresholds, lineage, drill-down dimensions, scenario
interpretation, example rendering and validation rule are all stated;
`test_every_metric_is_fully_defined` refuses one that is not.

The EXECUTABLE part of a book metric is `num` / `den`: SQL aggregate
expressions over the governed latest-period grid view (`grid.py`) for the
chosen period. They are written here, reviewed, versioned and tested -- never
authored by a model at run time. Metrics that are not portfolio aggregates
(scenario results, sensitivities, platform health) name an `evaluator` in
`metrics.py` instead.

Storage units: money is SAR MILLION in every published book; PD and CCF are
fractions; LGD, utilisation, LTV and payment ratio are PERCENT (0-100).
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = "gw-metrics-1.0.0"

#: Shared text, so identical policies are identical words.
_EXCL_INVALID_STAGE = ("Rows with a missing or invalid stage are excluded "
                       "from the denominator and counted in the data-quality "
                       "metric M045.")
_NULL_SUM = "NULL values contribute nothing to a sum; an all-NULL group is NULL, never 0."
#: A qualifying-population amount (e.g. Stage 3 EAD) is a MEASURED 0 when no
#: row qualifies; only missing data is NULL. (P8 formula tests: Stage 3 share
#: of a book with no Stage 3 exposure was published as NULL.)
_NULL_RATIO = "Null (not zero) when the denominator is zero or NULL."
_PERIOD_POINT = "Point-in-time at the selected reporting period (quarter for Corporate, month for Retail)."
_PERIOD_MOVE = ("Movement between the selected period t and the immediately "
                "preceding published period t-1 of the same book.")
_PERIOD_TRANSITION = ("Same entity observed at t-1 and t (consecutive published "
                      "periods); entities entering or leaving the book between "
                      "the two periods are excluded.")


def _m(metric_id: str, name: str, domain: str, definition: str, formula: str,
       *, num: str = "", den: str = "", numerator: str = "",
       denominator: str = "", unit: str, direction: str, grain: str,
       population: str, exclusions: str = "None beyond the eligible population.",
       nulls: str = _NULL_SUM, period: str = _PERIOD_POINT,
       thresholds: dict[str, Any] | None = None,
       lineage: list[str] | None = None,
       dimensions: list[str] | None = None, scenario: str = "",
       example: str = "", validation: str = "", evaluator: str = "",
       aggregation: str = "", kind: str = "book", family: str = "",
       relative_to: str = "") -> dict[str, Any]:
    return {
        "metric_id": metric_id, "version": 1, "name": name, "domain": domain,
        "family": family, "kind": kind, "definition": definition,
        "formula": formula,
        "numerator": numerator or (formula if not den else ""),
        "denominator": denominator or ("—" if not den else ""),
        "num_sql": num, "den_sql": den, "evaluator": evaluator,
        "relative_to": relative_to,
        "unit": unit,
        "scaling": {"SAR_mn": "Stored in SAR million; displayed adaptively "
                              "(SAR k / m / bn) with the raw value on hover "
                              "and in exports.",
                    "fraction": "Stored as a fraction 0-1; displayed as a "
                                "percentage with 2 decimals.",
                    "pct_points": "Stored in percent 0-100; displayed with %.",
                    "count": "Plain integer with thousands separators.",
                    }.get(unit, "Displayed in its native unit, unscaled."),
        "aggregation": aggregation or ("sum" if not den else "ratio of sums"),
        "grain": grain, "eligible_population": population,
        "exclusions": exclusions, "null_treatment": nulls,
        "period_semantics": period, "directionality": direction,
        "thresholds": thresholds or {},
        "lineage": lineage or [],
        "drilldown_dimensions": dimensions or [],
        "scenario_interpretation": scenario or (
            "Under a What-If result the metric is re-evaluated on the "
            "stressed values of the same frozen cohort; the booked value is "
            "never overwritten."),
        "example_rendering": example or _EXAMPLES.get(unit, "4.2"),
        "validation_rule": validation or (
            "Recomputed from the exported rows of the same period and filters "
            "to within 1e-9 relative (test_metric_reconciles_to_its_rows)."),
        "owner": "Credit Risk Analytics", "status": "APPROVED",
        "catalog_version": CATALOG_VERSION,
    }


#: How a value of each unit is rendered, when the entry states no example.
_EXAMPLES = {"SAR_mn": "SAR 171m (hover: 171.2345 SAR million raw)",
             "fraction": "12.34%", "count": "1,234", "score": "4.20",
             "hours": "36 h", "coefficient": "−0.042 per unit (lag 1)",
             "notches": "+0.12 notches", "pct_points": "62.5%"}

CORP_DIMS = ["sector", "sub_sector", "region", "rating_current", "stage",
             "product_type", "relationship_tier"]
RET_DIMS = ["product", "sub_product", "region", "score_band", "stage",
            "vintage_year", "delinquency_bucket", "employment_type"]
BOTH_DIMS = ["stage", "region"]

EAD = "SUM(ead_sar_mn)"
ECL = "SUM(ecl_sar_mn)"

METRICS: list[dict[str, Any]] = [
    _m("M001", "Booked ECL", "both", "Reported (booked) expected credit loss of the eligible population. No model substitution.",
       "SUM(reported_ecl)", num=ECL, unit="SAR_mn", direction="lower_is_better",
       grain="entity-period", population="Every exposure in the book at the period.",
       lineage=["corp_facility_quarter.ecl_sar_mn", "retail_account_month.ecl_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="ECL",
       example="SAR 1.94bn", thresholds={"move_pct_amber": 0.05, "move_pct_red": 0.10}),
    _m("M002", "ECL change", "both", "Absolute movement in booked ECL from t-1 to t.",
       "ECL_t - ECL_t-1", num=ECL, unit="SAR_mn", direction="lower_is_better",
       grain="portfolio/segment-period", population="Exposures in the book at each period.",
       period=_PERIOD_MOVE, kind="delta", relative_to="M001", aggregation="difference of sums",
       lineage=["M001"], dimensions=CORP_DIMS + RET_DIMS, family="ECL", example="+SAR 172m",
       validation="Equals M001(t) - M001(t-1) exactly (test_delta_metrics_equal_their_parts)."),
    _m("M003", "ECL change %", "both", "Relative movement in booked ECL from t-1 to t.",
       "(ECL_t / ECL_t-1) - 1", num=ECL, unit="fraction", direction="lower_is_better",
       grain="portfolio/segment-period", population="Exposures in the book at each period.",
       nulls="Null if prior ECL <= 0.", period=_PERIOD_MOVE, kind="delta_pct", relative_to="M001",
       aggregation="ratio of sums", lineage=["M001"], dimensions=CORP_DIMS + RET_DIMS, family="ECL",
       thresholds={"amber": 0.05, "red": 0.10}, example="+9.6%"),
    _m("M004", "Stage 1 EAD share", "both", "Share of EAD in Stage 1.",
       "SUM(EAD stage1) / SUM(EAD)", num="SUM(CASE WHEN stage = 1 THEN ead_sar_mn ELSE 0 END)",
       den="SUM(CASE WHEN stage IN (1, 2, 3) THEN ead_sar_mn END)",
       numerator="SUM(EAD where stage = 1)", denominator="SUM(EAD where stage in 1,2,3)",
       unit="fraction", direction="context", grain="portfolio-period",
       population="Exposures with a valid stage.", exclusions=_EXCL_INVALID_STAGE, nulls=_NULL_RATIO,
       lineage=["*.stage", "*.ead_sar_mn"], dimensions=CORP_DIMS + RET_DIMS, family="Stage",
       example="99.6%"),
    _m("M005", "Stage 2 EAD share", "both", "Share of EAD in Stage 2 — the SICR stock indicator.",
       "SUM(EAD stage2) / SUM(EAD)", num="SUM(CASE WHEN stage = 2 THEN ead_sar_mn ELSE 0 END)",
       den="SUM(CASE WHEN stage IN (1, 2, 3) THEN ead_sar_mn END)",
       numerator="SUM(EAD where stage = 2)", denominator="SUM(EAD where stage in 1,2,3)",
       unit="fraction", direction="lower_is_better", grain="portfolio-period",
       population="Exposures with a valid stage.", exclusions=_EXCL_INVALID_STAGE, nulls=_NULL_RATIO,
       thresholds={"amber": 0.05, "red": 0.10}, lineage=["*.stage", "*.ead_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Stage", example="0.39%"),
    _m("M006", "Stage 3 EAD share", "both", "Share of EAD in Stage 3 — the default/impaired stock.",
       "SUM(EAD stage3) / SUM(EAD)", num="SUM(CASE WHEN stage = 3 THEN ead_sar_mn ELSE 0 END)",
       den="SUM(CASE WHEN stage IN (1, 2, 3) THEN ead_sar_mn END)",
       numerator="SUM(EAD where stage = 3)", denominator="SUM(EAD where stage in 1,2,3)",
       unit="fraction", direction="lower_is_better", grain="portfolio-period",
       population="Exposures with a valid stage.", exclusions=_EXCL_INVALID_STAGE, nulls=_NULL_RATIO,
       thresholds={"amber": 0.02, "red": 0.04}, lineage=["*.stage", "*.ead_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Stage", example="0.00%"),
    _m("M007", "Stage 2 ECL share", "both", "Share of booked ECL held in Stage 2.",
       "SUM(ECL stage2) / SUM(ECL)", num="SUM(CASE WHEN stage = 2 THEN ecl_sar_mn ELSE 0 END)",
       den="SUM(CASE WHEN stage IN (1, 2, 3) THEN ecl_sar_mn END)",
       numerator="SUM(ECL where stage = 2)", denominator="SUM(ECL where stage in 1,2,3)",
       unit="fraction", direction="lower_is_better", grain="portfolio-period",
       population="Exposures with a valid stage.", exclusions=_EXCL_INVALID_STAGE, nulls=_NULL_RATIO,
       lineage=["*.stage", "*.ecl_sar_mn"], dimensions=CORP_DIMS + RET_DIMS, family="Stage",
       example="4.2%"),
    _m("M008", "Stage 3 ECL share", "both", "Share of booked ECL held in Stage 3.",
       "SUM(ECL stage3) / SUM(ECL)", num="SUM(CASE WHEN stage = 3 THEN ecl_sar_mn ELSE 0 END)",
       den="SUM(CASE WHEN stage IN (1, 2, 3) THEN ecl_sar_mn END)",
       numerator="SUM(ECL where stage = 3)", denominator="SUM(ECL where stage in 1,2,3)",
       unit="fraction", direction="lower_is_better", grain="portfolio-period",
       population="Exposures with a valid stage.", exclusions=_EXCL_INVALID_STAGE, nulls=_NULL_RATIO,
       lineage=["*.stage", "*.ecl_sar_mn"], dimensions=CORP_DIMS + RET_DIMS, family="Stage"),
    _m("M009", "Stage 1→2 migration EAD", "both", "EAD of exposures that were Stage 1 at t-1 and are Stage 2 at t.",
       "SUM(EAD where prior stage = 1 and current stage = 2)",
       num="SUM(CASE WHEN prior_stage = 1 AND stage = 2 THEN ead_sar_mn ELSE 0 END)", unit="SAR_mn",
       direction="lower_is_better", grain="entity-transition period",
       population="Exposures present at both t-1 and t.", period=_PERIOD_TRANSITION,
       exclusions="Exposures without a t-1 observation.", lineage=["*.stage", "prior-period *.stage", "*.ead_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Stage", example="SAR 1.1bn",
       validation="Equals the (1,2) cell of the stage transition matrix (test_migration_matrix_reconciles)."),
    _m("M010", "Stage 2→3 migration EAD", "both", "EAD of exposures that were Stage 2 at t-1 and are Stage 3 at t.",
       "SUM(EAD where prior stage = 2 and current stage = 3)",
       num="SUM(CASE WHEN prior_stage = 2 AND stage = 3 THEN ead_sar_mn ELSE 0 END)", unit="SAR_mn",
       direction="lower_is_better", grain="entity-transition period",
       population="Exposures present at both t-1 and t.", period=_PERIOD_TRANSITION,
       exclusions="Exposures without a t-1 observation.", lineage=["*.stage", "prior-period *.stage"],
       dimensions=CORP_DIMS + RET_DIMS, family="Stage"),
    _m("M011", "Cure EAD", "both", "EAD of exposures whose stage improved (3→2/1 or 2→1) between t-1 and t. Definition version 1, identical for both books.",
       "SUM(EAD with improving stage)", num="SUM(CASE WHEN prior_stage > stage THEN ead_sar_mn ELSE 0 END)",
       unit="SAR_mn", direction="higher_is_better", grain="entity-transition period",
       population="Exposures present at both t-1 and t.", period=_PERIOD_TRANSITION,
       lineage=["*.stage", "prior-period *.stage"], dimensions=CORP_DIMS + RET_DIMS, family="Stage"),
    _m("M012", "Default-entry rate", "both", "New defaults as a share of the population that was performing at t-1.",
       "New defaults / eligible performing population",
       num="SUM(CASE WHEN COALESCE(prior_default_flag, 0) = 0 AND default_flag = 1 AND prior_stage IS NOT NULL THEN 1 ELSE 0 END)",
       den="SUM(CASE WHEN COALESCE(prior_default_flag, 0) = 0 AND prior_stage IS NOT NULL THEN 1 ELSE 0 END)",
       numerator="count(entities performing at t-1 and in default at t)",
       denominator="count(entities performing at t-1 and present at t)", unit="fraction",
       direction="lower_is_better", grain="entity-period", population="Entities performing (not in default) at t-1.",
       nulls=_NULL_RATIO, period=_PERIOD_TRANSITION, thresholds={"amber": 0.002, "red": 0.005},
       lineage=["*.default_flag", "prior-period *.default_flag"], dimensions=CORP_DIMS + RET_DIMS,
       family="Default", example="0.14%"),
    _m("M013", "Default count", "both", "Number of distinct entities newly in default at t.",
       "COUNT(new default entities)",
       num="SUM(CASE WHEN COALESCE(prior_default_flag, 0) = 0 AND default_flag = 1 AND prior_stage IS NOT NULL THEN 1 ELSE 0 END)",
       unit="count", direction="lower_is_better", grain="entity-period",
       population="Entities performing at t-1.", period=_PERIOD_TRANSITION, aggregation="count",
       lineage=["*.default_flag"], dimensions=CORP_DIMS + RET_DIMS, family="Default"),
    _m("M014", "NPL / default EAD", "both", "EAD in default or Stage 3 (domain mapping: default_flag = 1 OR stage = 3, both books).",
       "SUM(EAD default/Stage3)", num="SUM(CASE WHEN default_flag = 1 OR stage = 3 THEN ead_sar_mn ELSE 0 END)",
       unit="SAR_mn", direction="lower_is_better", grain="entity-period",
       population="Every exposure at the period.", lineage=["*.default_flag", "*.stage", "*.ead_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Default"),
    _m("M015", "EAD-weighted PD", "both", "Exposure-weighted 12-month point-in-time PD.",
       "SUM(EAD * PD) / SUM(EAD with valid PD)",
       num="SUM(ead_sar_mn * pd_pit_12m)", den="SUM(CASE WHEN pd_pit_12m IS NOT NULL THEN ead_sar_mn END)",
       numerator="SUM(EAD × PD12m)", denominator="SUM(EAD where PD12m is valid)", unit="fraction",
       direction="lower_is_better", grain="entity-period", population="Exposures with a valid PD.",
       nulls=_NULL_RATIO + " Rows with NULL PD are excluded from both parts.",
       thresholds={"move_bps_amber": 5, "move_bps_red": 15}, lineage=["*.pd_pit_12m", "*.ead_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Risk parameters", example="1.37%",
       scenario="A PD stress moves this directly; Delta scales ECL proportionally to the PD multiplier."),
    _m("M016", "EAD-weighted LGD", "both", "Exposure-weighted loss given default (basis: published LGD, percent).",
       "SUM(EAD * LGD) / SUM(EAD with valid LGD)",
       num="SUM(ead_sar_mn * lgd_pct) / 100.0", den="SUM(CASE WHEN lgd_pct IS NOT NULL THEN ead_sar_mn END)",
       numerator="SUM(EAD × LGD) (LGD as a fraction)", denominator="SUM(EAD where LGD is valid)",
       unit="fraction", direction="lower_is_better", grain="entity-period", population="Exposures with a valid LGD.",
       nulls=_NULL_RATIO, lineage=["*.lgd_pct", "*.ead_sar_mn"], dimensions=CORP_DIMS + RET_DIMS,
       family="Risk parameters", example="28.57%"),
    _m("M017", "EAD-weighted CCF", "corporate", "Undrawn-weighted credit conversion factor, only where CCF applies (undrawn > 0).",
       "SUM(undrawn * CCF) / SUM(undrawn with valid CCF)",
       num="SUM(CASE WHEN undrawn_sar_mn > 0 AND ccf IS NOT NULL THEN undrawn_sar_mn * ccf END)",
       den="SUM(CASE WHEN undrawn_sar_mn > 0 AND ccf IS NOT NULL THEN undrawn_sar_mn END)",
       numerator="SUM(undrawn × CCF)", denominator="SUM(undrawn where CCF is valid)", unit="fraction",
       direction="lower_is_better", grain="facility-period", population="Facilities with an undrawn commitment.",
       exclusions=("Retail: BLOCKED by the governed data, not by choice. The Retail release publishes no CCF field, "
                   "and its EAD equals the outstanding balance on every account (measured: 6,702 of 6,702 in 2026-08), "
                   "so (EAD - balance) / undrawn is 0 by construction, not an observed conversion factor. Reporting it "
                   "would fake a CCF; the metric is Corporate-only until the Retail book publishes CCF or an EAD that "
                   "converts undrawn limits (test_m017_retail_incompatibility_is_measured_not_assumed)."),
       nulls=_NULL_RATIO,
       lineage=["corp_facility_quarter.undrawn_sar_mn", "whatif_corp_ifrs9.ccf_pit"], dimensions=CORP_DIMS,
       family="Risk parameters"),
    _m("M018", "Total EAD", "both", "Exposure at default of the eligible population.", "SUM(EAD)",
       num=EAD, unit="SAR_mn", direction="context", grain="entity-period",
       population="Every exposure at the period.", lineage=["*.ead_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Exposure", example="SAR 282bn"),
    _m("M019", "Utilisation rate", "both", "Drawn (Corporate) or balance (Retail) over approved limit.",
       "SUM(drawn) / SUM(limit)",
       num="SUM(limit_sar_mn * utilisation_pct / 100.0)", den="SUM(limit_sar_mn)",
       numerator="SUM(limit × utilisation) = drawn (Corporate) / balance (Retail)",
       denominator="SUM(approved limit)", unit="fraction", direction="context", grain="facility/account-period",
       population="Exposures with a limit.", nulls=_NULL_RATIO,
       lineage=["*.limit_sar_mn", "*.utilisation_pct"], dimensions=CORP_DIMS + RET_DIMS, family="Exposure",
       thresholds={"amber": 0.75, "red": 0.85}),
    _m("M020", "Top-10 concentration", "both", "EAD of the ten largest owners (borrowers / customers) over total EAD, after active filters.",
       "SUM(top10 EAD) / SUM(EAD)", unit="fraction", direction="lower_is_better",
       grain="portfolio-period", population="Owners in the filtered population.", evaluator="top_n_share",
       aggregation="ranked share", lineage=["*.ead_sar_mn", "owner id"], dimensions=["sector", "product"],
       nulls=_NULL_RATIO, thresholds={"amber": 0.10, "red": 0.15}, family="Concentration",
       denominator="SUM(EAD)", numerator="SUM(EAD of the 10 largest owners)"),
    _m("M021", "Largest-name concentration", "both", "EAD of the single largest owner over total EAD.",
       "MAX(entity EAD) / SUM(EAD)", unit="fraction", direction="lower_is_better", grain="portfolio-period",
       population="Owners in the filtered population.", evaluator="largest_name_share", aggregation="ranked share",
       lineage=["*.ead_sar_mn"], nulls=_NULL_RATIO, thresholds={"amber": 0.02, "red": 0.05},
       family="Concentration", numerator="MAX(owner EAD)", denominator="SUM(EAD)"),
    _m("M022", "Sector/product EAD share", "both", "EAD share of each value of the book's primary segment (sector for Corporate, product for Retail).",
       "SUM(EAD dimension value) / SUM(EAD)", unit="fraction", direction="context",
       grain="dimension-period", population="Every exposure at the period.", evaluator="segment_share",
       aggregation="share of total", lineage=["*.sector|product", "*.ead_sar_mn"], family="Concentration",
       numerator="SUM(EAD in the segment value)", denominator="SUM(EAD)", nulls=_NULL_RATIO),
    _m("M023", "Rating downgrade rate", "corporate", "Borrowers downgraded this quarter over rated borrowers with a prior grade (ordering from the governed masterscale).",
       "Downgraded borrowers / rated borrowers with prior grade", unit="fraction",
       direction="lower_is_better", grain="borrower-transition", population="Borrowers with a current and a prior rating.",
       evaluator="rating_migration_rate", aggregation="distinct-borrower ratio", period=_PERIOD_TRANSITION,
       lineage=["corp_borrower_quarter.rating_notches_moved"], dimensions=["sector", "region"],
       nulls=_NULL_RATIO, thresholds={"amber": 0.05, "red": 0.10}, family="Ratings",
       numerator="COUNT(DISTINCT borrower where notches_moved > 0)",
       denominator="COUNT(DISTINCT borrower with a prior rating)"),
    _m("M024", "Rating upgrade rate", "corporate", "Borrowers upgraded this quarter over rated borrowers with a prior grade.",
       "Upgraded borrowers / rated borrowers with prior grade", unit="fraction",
       direction="higher_is_better", grain="borrower-transition", population="Borrowers with a current and a prior rating.",
       evaluator="rating_migration_rate", aggregation="distinct-borrower ratio", period=_PERIOD_TRANSITION,
       lineage=["corp_borrower_quarter.rating_notches_moved"], dimensions=["sector", "region"],
       nulls=_NULL_RATIO, family="Ratings", numerator="COUNT(DISTINCT borrower where notches_moved < 0)",
       denominator="COUNT(DISTINCT borrower with a prior rating)"),
    _m("M025", "Average rating notch movement", "corporate", "Mean notch movement per rated borrower (positive = worse on the governed scale).",
       "AVG(current notch - prior notch)", unit="notches", direction="lower_is_better",
       grain="borrower-transition", population="Borrowers with a current and a prior rating.",
       evaluator="avg_notch_movement", aggregation="mean over distinct borrowers", period=_PERIOD_TRANSITION,
       lineage=["corp_borrower_quarter.rating_notches_moved"], dimensions=["sector"], family="Ratings",
       numerator="SUM(notches moved)", denominator="COUNT(rated borrowers)"),
    _m("M026", "Behaviour score movement", "retail", "Mean month-on-month change in behaviour score per customer. Directionality from the governed scorecard metadata: HIGHER_IS_SAFER.",
       "AVG(score_t - score_t-1)", unit="score", direction="higher_is_better",
       grain="customer/account-transition", population="Customers scored at t and t-1.",
       evaluator="avg_score_movement", aggregation="mean over distinct customers", period=_PERIOD_TRANSITION,
       lineage=["retail_customer_month.behaviour_score_change", "whatif_retail_score_map.direction"],
       dimensions=["product", "region", "score_band"], family="Scores",
       numerator="SUM(score change)", denominator="COUNT(customers)"),
    _m("M027", "Application score distribution", "retail", "Distribution of application scores by governed band (bands 300-899, 100-point edges, version whatif-application-bands-1).",
       "Distribution by governed score bands", unit="count", direction="context",
       grain="application-period", population="Customers with an application score.",
       evaluator="application_score_distribution", aggregation="count by band",
       lineage=["whatif_retail_profile.application_score"], family="Scores", numerator="count per band",
       denominator="count of scored customers"),
    _m("M028", "30+ DPD rate", "retail", "Share of accounts (count variant) and of EAD (EAD variant, M028E) 30 or more days past due.",
       "Accounts with DPD >= 30 / eligible accounts",
       num="SUM(CASE WHEN dpd_days >= 30 THEN 1 ELSE 0 END)", den="COUNT(*)",
       numerator="count(accounts DPD >= 30)", denominator="count(accounts)", unit="fraction",
       direction="lower_is_better", grain="account-period", population="Every account at the period.",
       nulls=_NULL_RATIO, thresholds={"amber": 0.02, "red": 0.04}, lineage=["retail_account_month.dpd_days"],
       dimensions=RET_DIMS, family="Delinquency"),
    _m("M029", "90+ DPD rate", "retail", "Share of accounts 90 or more days past due (count variant; EAD variant M029E).",
       "Accounts with DPD >= 90 / eligible accounts",
       num="SUM(CASE WHEN dpd_days >= 90 THEN 1 ELSE 0 END)", den="COUNT(*)",
       numerator="count(accounts DPD >= 90)", denominator="count(accounts)", unit="fraction",
       direction="lower_is_better", grain="account-period", population="Every account at the period.",
       nulls=_NULL_RATIO, thresholds={"amber": 0.01, "red": 0.02}, lineage=["retail_account_month.dpd_days"],
       dimensions=RET_DIMS, family="Delinquency"),
    _m("M030", "Roll-forward rate", "retail", "Accounts moving to a worse delinquency bucket, over accounts in a delinquency bucket at t-1 (bucket order Current < 1-30 < 31-60 < 61-90 < 90+).",
       "Population moving to worse DPD bucket / source bucket population",
       num=("SUM(CASE WHEN prior_delinquency_bucket IS NOT NULL AND "
            "(CASE delinquency_bucket WHEN 'Current' THEN 0 WHEN '1-30' THEN 1 WHEN '31-60' THEN 2 WHEN '61-90' THEN 3 WHEN '90+' THEN 4 END) > "
            "(CASE prior_delinquency_bucket WHEN 'Current' THEN 0 WHEN '1-30' THEN 1 WHEN '31-60' THEN 2 WHEN '61-90' THEN 3 WHEN '90+' THEN 4 END) "
            "THEN 1 ELSE 0 END)"),
       den="SUM(CASE WHEN prior_delinquency_bucket IS NOT NULL THEN 1 ELSE 0 END)",
       numerator="count(accounts whose bucket worsened)", denominator="count(accounts observed at t-1)",
       unit="fraction", direction="lower_is_better", grain="account-transition",
       population="Accounts observed at t-1 and t.", period=_PERIOD_TRANSITION, nulls=_NULL_RATIO,
       lineage=["retail_account_month.delinquency_bucket"], dimensions=RET_DIMS, family="Delinquency"),
    _m("M031", "Cure rate", "retail", "Accounts past due at t-1 that are current at t, over accounts past due at t-1.",
       "Population improving from delinquent / eligible starting population",
       num="SUM(CASE WHEN prior_dpd_days > 0 AND dpd_days = 0 THEN 1 ELSE 0 END)",
       den="SUM(CASE WHEN prior_dpd_days > 0 THEN 1 ELSE 0 END)",
       numerator="count(accounts DPD>0 at t-1 and DPD=0 at t)", denominator="count(accounts DPD>0 at t-1)",
       unit="fraction", direction="higher_is_better", grain="account-transition",
       population="Accounts past due at t-1.", period=_PERIOD_TRANSITION, nulls=_NULL_RATIO,
       lineage=["retail_account_month.dpd_days"], dimensions=RET_DIMS, family="Delinquency"),
    _m("M032", "EWS warned customers", "retail", "Distinct customers with at least one active warning under EWS rule set gw-ews-1.0.0.",
       "COUNT(DISTINCT customer with active warning)", unit="count", direction="lower_is_better",
       grain="customer-period", population="Every customer at the period.", evaluator="ews_owners",
       aggregation="distinct count", lineage=["backend/workspace/ews.py RULES.retail"],
       dimensions=["product", "region"], family="Early warning", thresholds={"move_pct_amber": 0.10}),
    _m("M033", "EWS high/critical share", "retail", "High + critical warned customers over warned customers.",
       "High+Critical warned / warned", unit="fraction", direction="lower_is_better",
       grain="customer-period", population="Warned customers.", evaluator="ews_severe_share",
       aggregation="distinct-customer ratio", lineage=["backend/workspace/ews.py"], nulls=_NULL_RATIO,
       dimensions=["product"], family="Early warning", thresholds={"amber": 0.05, "red": 0.10},
       numerator="COUNT(DISTINCT customer with band high/critical)", denominator="COUNT(DISTINCT warned customer)"),
    _m("M034", "Forward-risk customers", "retail", "Customers with any account whose 12m PD rose by 20% or more relative since t-1 while still Stage 1 (forward-risk rule gw-forward-risk-1).",
       "COUNT(DISTINCT customer flagged forward risk)", unit="count", direction="lower_is_better",
       grain="customer-period", population="Customers with a prior PD.", evaluator="forward_risk_owners",
       aggregation="distinct count", period=_PERIOD_TRANSITION,
       lineage=["retail_account_month.pd_pit_12m", "prior-period pd_pit_12m"], family="Early warning"),
    _m("M035", "EWS score", "retail", "Mean EWS rule score per account (rule weights are additive by construction, so the mean is a defined aggregate).",
       "AVG(ews_score)", num="SUM(ews_score)", den="COUNT(*)", unit="score", direction="lower_is_better",
       grain="customer-period", population="Every account at the period.", aggregation="mean",
       lineage=["backend/workspace/ews.py"], dimensions=RET_DIMS, family="Early warning",
       numerator="SUM(ews_score)", denominator="COUNT(accounts)"),
    _m("M036", "Covenant breach rate", "corporate", "Facilities with an active covenant breach over facilities with covenant tests this quarter.",
       "Facilities with active breach / monitored facilities",
       num="SUM(CASE WHEN covenant_breaches > 0 THEN 1 ELSE 0 END)",
       den="SUM(CASE WHEN covenant_breaches IS NOT NULL THEN 1 ELSE 0 END)",
       numerator="count(facilities with >= 1 breach)", denominator="count(facilities with covenant tests)",
       unit="fraction", direction="lower_is_better", grain="facility-period",
       population="Facilities with covenant tests.", nulls=_NULL_RATIO, thresholds={"amber": 0.25, "red": 0.35},
       lineage=["corp_covenant_quarter.breach_flag"], dimensions=CORP_DIMS, family="Covenants"),
    _m("M037", "Limit utilisation", "both", "Exposure (EAD) over approved limit.",
       "Exposure / approved limit", num=EAD, den="SUM(limit_sar_mn)", numerator="SUM(EAD)",
       denominator="SUM(approved limit)", unit="fraction", direction="lower_is_better",
       grain="limit/entity-period", population="Exposures with a limit.", nulls=_NULL_RATIO,
       thresholds={"amber": 0.80, "red": 0.90}, lineage=["*.ead_sar_mn", "*.limit_sar_mn"],
       dimensions=CORP_DIMS + RET_DIMS, family="Limits"),
    _m("M038", "Limit breach count", "both", "Exposures whose utilisation exceeds 100% of the approved limit (rule gw-limit-breach-1).",
       "COUNT(active breaches)", num="SUM(CASE WHEN utilisation_pct > 100 THEN 1 ELSE 0 END)",
       unit="count", direction="lower_is_better", grain="limit/entity-period",
       population="Exposures with a limit.", aggregation="count", lineage=["*.utilisation_pct"],
       dimensions=CORP_DIMS + RET_DIMS, family="Limits"),
    _m("M039", "Scenario ECL delta", "both", "Scenario post-ECL minus scenario baseline ECL for one executed scenario result.",
       "Scenario post ECL - scenario baseline ECL", unit="SAR_mn", direction="lower_is_better",
       grain="scenario-scope", population="The frozen cohort of the scenario result.", kind="scenario",
       evaluator="scenario_delta", aggregation="as computed by the selected ECL method",
       lineage=["scenario_result.results"], nulls="Null when the method was unavailable (never 0).",
       period="The scenario result's source period.", family="Scenario",
       validation="Equals the closing minus opening bar of the selected-scope bridge exactly."),
    _m("M040", "Scenario ECL delta %", "both", "Scenario ECL delta over scenario baseline ECL.",
       "Scenario delta / scenario baseline ECL", unit="fraction", direction="lower_is_better",
       grain="scenario-scope", population="The frozen cohort of the scenario result.", kind="scenario",
       evaluator="scenario_delta_pct", nulls="Null when baseline <= 0.", period="The scenario result's source period.",
       lineage=["scenario_result.results"], family="Scenario", numerator="M039", denominator="baseline ECL"),
    _m("M041", "Selected-scope contribution to total ECL change", "both", "Selected-scope ECL delta over total-domain ECL delta (SAR amount stored beside it).",
       "selected scope ECL delta / total-domain ECL delta", unit="fraction", direction="context",
       grain="scenario-scope", population="One scenario result.", kind="scenario",
       evaluator="scope_contribution", nulls="Null when the total-domain delta is 0.",
       period="The scenario result's source period.", lineage=["scenario_result.decomposition"],
       family="Scenario", numerator="selected-scope delta", denominator="total-book delta"),
    _m("M042", "Model calibration gap", "both", "Method 2 model baseline ECL minus booked ECL, for the same cohort and period. Never hidden inside scenario effects.",
       "model baseline ECL - booked ECL", unit="SAR_mn", direction="lower_is_better",
       grain="scenario-scope", population="One Method 2 execution.", kind="scenario",
       evaluator="calibration_gap", nulls="Null for methods other than the ML emulator.",
       period="The scenario result's source period.", lineage=["scenario_result.results.ml"],
       family="Scenario", aggregation="difference"),
    _m("M043", "MEV sensitivity coefficient", "both", "Governed estimator coefficient/elasticity of a risk parameter to one macroeconomic variable.",
       "Governed estimator coefficient", unit="coefficient", direction="context",
       grain="MEV-risk parameter", population="Published sensitivity rows of the release.", kind="sensitivity",
       evaluator="sensitivity_coefficient", aggregation="as published", period="The fit window stated on the row (train/validation periods).",
       lineage=["whatif_*_sensitivity.coefficient", "method", "lag", "training_periods", "readiness"],
       dimensions=["factor_id", "parameter"], family="Macro",
       nulls="A row without a coefficient is reported with its readiness status, never as 0."),
    _m("M044", "MEV sensitivity stability", "both", "Share of period resamples in which the coefficient keeps its sign.",
       "Governed stability statistic across windows/splits", unit="fraction", direction="higher_is_better",
       grain="MEV-risk parameter", population="Published sensitivity rows.", kind="sensitivity",
       evaluator="sensitivity_stability", lineage=["whatif_*_sensitivity.sign_stability"],
       dimensions=["factor_id", "parameter"], family="Macro", thresholds={"amber": 0.8, "red": 0.6},
       period="The fit window stated on the row."),
    _m("M045", "Data completeness", "both", "Non-null required fields over required cells for the exposure view (required set gw-required-1: ead, ecl, stage, pd_pit_12m, lgd_pct, limit).",
       "non-null required fields / required cells", unit="fraction", direction="higher_is_better",
       grain="dataset-field-period", population="Every exposure row at the period.", kind="platform",
       evaluator="completeness", lineage=["grid view"], thresholds={"amber": 0.99, "red": 0.97},
       family="Data quality", numerator="non-null required cells", denominator="rows × required fields"),
    _m("M046", "Data freshness", "both", "Hours since the release in use was published (manifest built_at).",
       "now - latest governed source timestamp", unit="hours", direction="lower_is_better",
       grain="dataset-period", population="The release in use.", kind="platform", evaluator="freshness",
       lineage=["manifest.built_at"], family="Data quality",
       nulls="If the release does not record its publication time, the metric is UNAVAILABLE, not 0.",
       period="Wall-clock at evaluation; shown as current only after a successful load."),
    _m("M047", "Reconciliation residual", "both", "Reported total ECL minus the sum of its stage components (must be 0 within SAR 1e-6m or publication is blocked).",
       "reported total - sum(components)", unit="SAR_mn", direction="lower_is_better",
       grain="decomposition-period", population="Every exposure at the period.", kind="book",
       evaluator="reconciliation_residual", lineage=["*.ecl_sar_mn", "*.stage"], family="Data quality",
       thresholds={"red_abs": 1e-6}),
    _m("M048", "Breach count active", "both", "Alerts whose state is NEW, ACTIVE or WORSENING.",
       "COUNT(alerts in NEW/ACTIVE/WORSENING)", unit="count", direction="lower_is_better",
       grain="lens/rule-period", population="Alerts of this tenant.", kind="platform",
       evaluator="active_breaches", lineage=["workspace alerts"], family="Monitoring", aggregation="count"),
    _m("M049", "Material changes since prior refresh", "both", "Metrics whose change since the previous successful Lens observation exceeds the Lens' materiality policy.",
       "COUNT(metric changes above configured materiality)", unit="count", direction="lower_is_better",
       grain="lens-refresh", population="Metrics of one Lens version.", kind="platform",
       evaluator="material_changes", lineage=["lens_observations"], family="Monitoring", aggregation="count"),
    _m("M050", "Lens refresh age", "both", "Hours since the Lens' last SUCCESSFUL refresh. A failed refresh never resets it.",
       "now - last successful refresh", unit="hours", direction="lower_is_better", grain="lens",
       population="One Lens.", kind="platform", evaluator="refresh_age", lineage=["lens_observations"],
       family="Monitoring", nulls="UNAVAILABLE if the Lens has never refreshed successfully."),
    # ---- beyond the minimum registry --------------------------------------------
    _m("M051", "Watchlist EAD share", "corporate", "Share of EAD owed by borrowers on the watchlist.",
       "SUM(EAD watchlist) / SUM(EAD)", num="SUM(CASE WHEN watchlist_flag = 1 THEN ead_sar_mn ELSE 0 END)",
       den=EAD, numerator="SUM(EAD where watchlist)", denominator="SUM(EAD)", unit="fraction",
       direction="lower_is_better", grain="facility-period", population="Every facility.",
       nulls=_NULL_RATIO, thresholds={"amber": 0.08, "red": 0.12}, lineage=["corp_borrower_quarter.watchlist_flag"],
       dimensions=CORP_DIMS, family="Early warning"),
    _m("M052", "ECL coverage", "both", "Booked ECL over EAD.", "SUM(ECL) / SUM(EAD)", num=ECL, den=EAD,
       numerator="SUM(ECL)", denominator="SUM(EAD)", unit="fraction", direction="context",
       grain="entity-period", population="Every exposure.", nulls=_NULL_RATIO,
       lineage=["*.ecl_sar_mn", "*.ead_sar_mn"], dimensions=CORP_DIMS + RET_DIMS, family="ECL"),
    _m("M053", "EAD-weighted LTV", "both", "Exposure-weighted loan-to-value where collateral is allocated.",
       "SUM(EAD × LTV) / SUM(EAD with LTV)", num="SUM(ead_sar_mn * ltv_pct) / 100.0",
       den="SUM(CASE WHEN ltv_pct IS NOT NULL THEN ead_sar_mn END)", numerator="SUM(EAD × LTV)",
       denominator="SUM(EAD where LTV is valid)", unit="fraction", direction="lower_is_better",
       grain="entity-period", population="Collateralised exposures.", nulls=_NULL_RATIO,
       thresholds={"amber": 0.80, "red": 0.90}, lineage=["*_collateral_*.ltv_pct"],
       dimensions=CORP_DIMS + RET_DIMS, family="Collateral"),
    _m("M054", "Past-due EAD", "both", "EAD with any days past due.", "SUM(EAD where DPD > 0)",
       num="SUM(CASE WHEN dpd_days > 0 THEN ead_sar_mn ELSE 0 END)", unit="SAR_mn", direction="lower_is_better",
       grain="entity-period", population="Every exposure.", lineage=["*.dpd_days"],
       dimensions=CORP_DIMS + RET_DIMS, family="Delinquency"),
    _m("M055", "Stage 2 count", "both", "Number of exposures in Stage 2.", "COUNT(stage = 2)",
       num="SUM(CASE WHEN stage = 2 THEN 1 ELSE 0 END)", unit="count", direction="lower_is_better",
       grain="entity-period", population="Every exposure.", aggregation="count", lineage=["*.stage"],
       dimensions=CORP_DIMS + RET_DIMS, family="Stage"),
    _m("M056", "Weak score-band share", "retail", "EAD share of accounts in behaviour bands D and E.",
       "SUM(EAD bands D,E) / SUM(EAD)", num="SUM(CASE WHEN score_band IN ('D', 'E') THEN ead_sar_mn ELSE 0 END)",
       den=EAD, numerator="SUM(EAD in D/E)", denominator="SUM(EAD)", unit="fraction",
       direction="lower_is_better", grain="account-period", population="Every account.", nulls=_NULL_RATIO,
       thresholds={"amber": 0.25, "red": 0.35}, lineage=["retail_account_month.score_band"],
       dimensions=RET_DIMS, family="Scores"),
    _m("M057", "Average payment ratio", "retail", "Mean payment-to-due ratio across accounts (percent).",
       "AVG(payment_ratio_pct)", num="SUM(payment_ratio_pct) / 100.0",
       den="SUM(CASE WHEN payment_ratio_pct IS NOT NULL THEN 1 ELSE 0 END)", numerator="SUM(payment ratio)",
       denominator="COUNT(accounts with a payment ratio)", unit="fraction", direction="higher_is_better",
       grain="account-period", population="Accounts with a behaviour record.", nulls=_NULL_RATIO,
       lineage=["retail_behaviour_month.payment_ratio_pct"], dimensions=RET_DIMS, family="Behaviour",
       thresholds={"amber": 0.35, "red": 0.30}),
    _m("M058", "Deteriorated-score customers", "retail", "Customers whose behaviour score band deteriorated this month.",
       "COUNT(DISTINCT customer with score_migration = Deteriorated)", unit="count",
       direction="lower_is_better", grain="customer-period", population="Every customer.",
       evaluator="deteriorated_customers", aggregation="distinct count",
       lineage=["retail_customer_month.score_migration"], dimensions=["product"], family="Scores"),
    _m("M059", "Borrower / customer count", "both", "Distinct owners (borrowers or customers) in the population.",
       "COUNT(DISTINCT owner)", unit="count", direction="context", grain="owner-period",
       population="Every exposure.", evaluator="owner_count", aggregation="distinct count",
       lineage=["owner id"], dimensions=CORP_DIMS + RET_DIMS, family="Exposure"),
    _m("M060", "Exposure count", "both", "Facilities (Corporate) or accounts (Retail) in the population.",
       "COUNT(exposures)", num="COUNT(*)", unit="count", direction="context", grain="entity-period",
       population="Every exposure.", aggregation="count", lineage=["exposure id"],
       dimensions=CORP_DIMS + RET_DIMS, family="Exposure"),
    _m("M061", "Newest-vintage PD", "retail", "EAD-weighted PD of accounts on book for 6 months or less.",
       "SUM(EAD × PD, MOB<=6) / SUM(EAD, MOB<=6)",
       num="SUM(CASE WHEN months_on_book <= 6 THEN ead_sar_mn * pd_pit_12m END)",
       den="SUM(CASE WHEN months_on_book <= 6 THEN ead_sar_mn END)", numerator="SUM(EAD × PD) for MOB <= 6",
       denominator="SUM(EAD) for MOB <= 6", unit="fraction", direction="lower_is_better",
       grain="account-period", population="Accounts with months on book <= 6.", nulls=_NULL_RATIO,
       lineage=["retail_account_month.months_on_book", "pd_pit_12m"], dimensions=["product"],
       family="Vintage"),
    _m("M062", "EWS warned EAD", "both", "EAD of exposures with an active EWS warning (band low or worse).",
       "SUM(EAD where ews_band != none)", num="SUM(CASE WHEN ews_band <> 'none' THEN ead_sar_mn ELSE 0 END)",
       unit="SAR_mn", direction="lower_is_better", grain="entity-period", population="Every exposure.",
       lineage=["backend/workspace/ews.py"], dimensions=CORP_DIMS + RET_DIMS, family="Early warning"),
    _m("M063", "High/critical EWS EAD", "both", "EAD of exposures in EWS bands high or critical.",
       "SUM(EAD where ews_band in (high, critical))",
       num="SUM(CASE WHEN ews_band IN ('high', 'critical') THEN ead_sar_mn ELSE 0 END)", unit="SAR_mn",
       direction="lower_is_better", grain="entity-period", population="Every exposure.",
       lineage=["backend/workspace/ews.py"], dimensions=CORP_DIMS + RET_DIMS, family="Early warning"),
    _m("M064", "Covenant-breach EAD", "corporate", "EAD of facilities with at least one covenant breach.",
       "SUM(EAD where covenant_breaches > 0)", num="SUM(CASE WHEN covenant_breaches > 0 THEN ead_sar_mn ELSE 0 END)",
       unit="SAR_mn", direction="lower_is_better", grain="facility-period", population="Every facility.",
       lineage=["corp_covenant_quarter.breach_flag"], dimensions=CORP_DIMS, family="Covenants"),
]

#: MATERIALITY where no breach level is governed (§46: thresholds /
#: materiality are part of every definition). These are change-detection
#: materialities -- what counts as a material move between refreshes (M049) --
#: and say so in `basis`; they are not breach limits.
_MATERIALITY: dict[str, dict[str, Any]] = {
    "SAR_mn": {"materiality_move_pct": 0.05, "materiality_abs_sar_mn": 1.0},
    "fraction": {"materiality_move_pp": 0.5},
    "count": {"materiality_move_pct": 0.10, "materiality_abs": 5},
    "score": {"materiality_move_abs": 5.0},
    "notches": {"materiality_move_abs": 0.1},
    "coefficient": {"materiality_move_pct": 0.25},
}

#: Explicit levels for the platform metrics that have a natural limit.
_LEVELS: dict[str, dict[str, Any]] = {
    "M046": {"amber_hours": 24, "red_hours": 72},
    "M048": {"amber": 1, "red": 5},
    "M049": {"amber": 3, "red": 10},
    "M050": {"amber_hours": 24, "red_hours": 72},
}

#: Drill-down for metrics that are not a plain portfolio aggregate.
_DRILL: dict[str, list[str]] = {
    "M021": ["sector|product", "region", "stage"],
    "M022": ["sector|product", "region", "stage"],
    "M027": ["score_band", "product"],
    "M034": ["product", "region", "score_band"],
    "M039": ["scenario", "method", "baseline", "result"],
    "M040": ["scenario", "method", "baseline", "result"],
    "M041": ["scenario", "method", "baseline", "result"],
    "M042": ["scenario", "result"],
    "M043": ["factor", "parameter", "segment"],
    "M044": ["factor", "parameter", "segment"],
    "M045": ["field"],
    "M046": ["dataset"],
    "M047": ["stage", "component"],
    "M048": ["lens", "rule", "severity"],
    "M049": ["lens", "metric"],
    "M050": ["lens"],
}


def _complete(metric: dict[str, Any]) -> dict[str, Any]:
    mid = metric["metric_id"]
    if mid in _LEVELS:
        metric["thresholds"] = {**_LEVELS[mid], **metric["thresholds"],
                                "basis": "governed platform limit"}
    elif not metric["thresholds"]:
        metric["thresholds"] = {
            **_MATERIALITY.get(metric["unit"], {"materiality_move_pct": 0.05}),
            "basis": ("catalogue materiality for change detection; no breach "
                      "level is governed for this "
                      + ("context " if metric["directionality"] == "context"
                         else "") + "metric")}
    if not metric["drilldown_dimensions"]:
        metric["drilldown_dimensions"] = list(_DRILL.get(mid, []))
    return metric


METRICS = [_complete(m) for m in METRICS]

BY_ID = {m["metric_id"]: m for m in METRICS}

#: What "fully defined" means, checked by test for every entry.
DEFINITION_FIELDS = (
    "metric_id", "version", "name", "definition", "formula", "numerator",
    "denominator", "unit", "scaling", "aggregation", "grain",
    "eligible_population", "exclusions", "null_treatment", "period_semantics",
    "domain", "directionality", "thresholds", "lineage",
    "drilldown_dimensions", "scenario_interpretation", "example_rendering",
    "validation_rule")


def get(metric_id: str) -> dict[str, Any]:
    return BY_ID[metric_id]


def applies(metric: dict[str, Any], domain_id: str) -> bool:
    return metric["domain"] in ("both", domain_id)


__all__ = ["BY_ID", "CATALOG_VERSION", "DEFINITION_FIELDS", "METRICS",
           "applies", "get"]
