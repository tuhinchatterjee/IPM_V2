"""
The demonstration policy set. Brief §4.2.

Every number in this file is a SYNTHETIC DEMONSTRATION ASSUMPTION. None of it
is calibrated to any portfolio, validated against any outcome, approved by any
committee or compliant with any standard. It exists so that the demo book is
reproducible and so that the Cockpit can show the rule it applied rather than
asserting a conclusion — "Stage 2 because the SICR policy's notch threshold was
crossed" is a statement about this file, and that is the only kind of causal
statement the product is allowed to make about staging.

Policies are versioned. `POLICY_VERSION` is part of every run key, cache key
and stored attribution, so a changed threshold can never be answered from a
cache built under the old one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.cockpit_v2 import POLICY_VERSION

SYNTHETIC_ASSUMPTION = (
    "Synthetic demonstration assumption. Not calibrated, not validated, not "
    "approved for any regulatory or accounting purpose.")


# ------------------------------------------------------------ rating scale


#: The demo master scale. `rank` is ordinal and increases with risk, so a
#: downgrade is a positive notch movement. Twelve-month PDs rise roughly
#: geometrically across it, which is a conventional shape and nothing more.
RATING_SCALE: tuple[dict[str, Any], ...] = (
    {"grade": "AAA", "rank": 1, "twelve_month_pd": 0.0003, "investment": True},
    {"grade": "AA",  "rank": 2, "twelve_month_pd": 0.0006, "investment": True},
    {"grade": "A",   "rank": 3, "twelve_month_pd": 0.0012, "investment": True},
    {"grade": "BBB", "rank": 4, "twelve_month_pd": 0.0030, "investment": True},
    {"grade": "BB+", "rank": 5, "twelve_month_pd": 0.0070, "investment": False},
    {"grade": "BB",  "rank": 6, "twelve_month_pd": 0.0130, "investment": False},
    {"grade": "BB-", "rank": 7, "twelve_month_pd": 0.0220, "investment": False},
    {"grade": "B+",  "rank": 8, "twelve_month_pd": 0.0380, "investment": False},
    {"grade": "B",   "rank": 9, "twelve_month_pd": 0.0620, "investment": False},
    {"grade": "B-",  "rank": 10, "twelve_month_pd": 0.0950, "investment": False},
    {"grade": "CCC", "rank": 11, "twelve_month_pd": 0.1800, "investment": False},
    {"grade": "CC",  "rank": 12, "twelve_month_pd": 0.3200, "investment": False},
    {"grade": "D",   "rank": 13, "twelve_month_pd": 1.0000, "investment": False},
)

RATING_BY_GRADE = {r["grade"]: r for r in RATING_SCALE}
RATING_BY_RANK = {r["rank"]: r for r in RATING_SCALE}
DEFAULT_RANK = 13
WORST_PERFORMING_RANK = 12

RATING_SCALE_ID = "COCKPIT_DEMO_MASTER_SCALE"
RATING_MODEL_VERSION = "1.0.0"


def rating_pd(grade: str) -> float:
    """The through-the-cycle twelve-month PD the scale maps a grade to."""
    try:
        return float(RATING_BY_GRADE[grade]["twelve_month_pd"])
    except KeyError:
        raise KeyError(
            f"{grade!r} is not a grade on {RATING_SCALE_ID}. Grades: "
            f"{', '.join(RATING_BY_GRADE)}") from None


def grade_for_rank(rank: int) -> str:
    return RATING_BY_RANK[max(1, min(int(rank), DEFAULT_RANK))]["grade"]


# --------------------------------------------------- rating from financials


@dataclass(frozen=True)
class RatingFactor:
    """One scored input of the demo rating model."""

    field: str
    label: str
    weight: float
    #: Score bands, richest first: (threshold, score). A value at or above the
    #: threshold takes that score when `higher_is_better`, at or below when not.
    bands: tuple[tuple[float, float], ...]
    higher_is_better: bool
    #: What happens when the input is missing. Never silently zero — a missing
    #: DSCR is not a DSCR of nought.
    missing_score: float = 5.0
    missing_note: str = "input not available; the neutral band score is used"


#: The demo corporate rating model. Weights sum to one; scores run 1 (weakest)
#: to 10 (strongest) and map to the master scale by `score_to_rank` below.
RATING_FACTORS: tuple[RatingFactor, ...] = (
    RatingFactor("dscr", "Debt service coverage", 0.28,
                 ((2.50, 10.0), (2.00, 9.0), (1.60, 8.0), (1.35, 7.0),
                  (1.20, 6.0), (1.10, 5.0), (1.00, 4.0), (0.85, 3.0),
                  (0.60, 2.0), (float("-inf"), 1.0)), True),
    RatingFactor("net_debt_to_ebitda", "Net debt / EBITDA", 0.24,
                 ((0.75, 10.0), (1.50, 9.0), (2.25, 8.0), (3.00, 7.0),
                  (3.75, 6.0), (4.50, 5.0), (5.50, 4.0), (6.50, 3.0),
                  (8.00, 2.0), (float("inf"), 1.0)), False),
    RatingFactor("interest_coverage", "EBIT / interest", 0.18,
                 ((9.0, 10.0), (6.5, 9.0), (4.5, 8.0), (3.2, 7.0), (2.4, 6.0),
                  (1.8, 5.0), (1.4, 4.0), (1.1, 3.0), (0.8, 2.0),
                  (float("-inf"), 1.0)), True),
    RatingFactor("ebitda_margin", "EBITDA margin", 0.14,
                 ((0.28, 10.0), (0.22, 9.0), (0.18, 8.0), (0.145, 7.0),
                  (0.115, 6.0), (0.09, 5.0), (0.06, 4.0), (0.035, 3.0),
                  (0.0, 2.0), (float("-inf"), 1.0)), True),
    RatingFactor("current_ratio", "Current ratio", 0.09,
                 ((2.20, 10.0), (1.80, 9.0), (1.55, 8.0), (1.35, 7.0),
                  (1.20, 6.0), (1.05, 5.0), (0.95, 4.0), (0.85, 3.0),
                  (0.70, 2.0), (float("-inf"), 1.0)), True),
    RatingFactor("revenue_growth", "Revenue growth", 0.07,
                 ((0.14, 10.0), (0.09, 9.0), (0.055, 8.0), (0.03, 7.0),
                  (0.01, 6.0), (0.0, 5.0), (-0.03, 4.0), (-0.07, 3.0),
                  (-0.14, 2.0), (float("-inf"), 1.0)), True),
)

RATING_MODEL_ID = "COCKPIT_DEMO_CORPORATE_RATING_V1"


def score_factor(factor: RatingFactor, value: float | None) -> dict[str, Any]:
    """Score one input, saying explicitly when it was missing."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return {"field": factor.field, "label": factor.label,
                "value": None, "score": factor.missing_score,
                "weight": factor.weight, "available": False,
                "note": factor.missing_note}
    v = float(value)
    score = factor.bands[-1][1]
    for threshold, band_score in factor.bands:
        if (v >= threshold) if factor.higher_is_better else (v <= threshold):
            score = band_score
            break
    return {"field": factor.field, "label": factor.label, "value": v,
            "score": score, "weight": factor.weight, "available": True,
            "note": ""}


def score_to_rank(score: float) -> int:
    """Map a 1-10 weighted score onto the master scale's ordinal rank.

    A straight linear map from the score range onto ranks 1..12. Rank 13 is
    default and is never reached by a score — an account defaults because the
    default policy says so, not because its financials scored badly.
    """
    s = max(1.0, min(float(score), 10.0))
    rank = 1 + round((10.0 - s) / 9.0 * (WORST_PERFORMING_RANK - 1))
    return int(max(1, min(rank, WORST_PERFORMING_RANK)))


def rate_borrower(ratios: dict[str, float | None]) -> dict[str, Any]:
    """The demo model grade for one borrower, with its inputs shown.

    Returns the scored factors as well as the grade, because "explain this
    borrower's rating using the model inputs" (question A3.14) has to be
    answerable from stored evidence rather than from prose.
    """
    scored = [score_factor(f, ratios.get(f.field)) for f in RATING_FACTORS]
    total_weight = sum(s["weight"] for s in scored)
    weighted = sum(s["score"] * s["weight"] for s in scored) / total_weight
    rank = score_to_rank(weighted)
    return {
        "model_id": RATING_MODEL_ID, "model_version": RATING_MODEL_VERSION,
        "scale": RATING_SCALE_ID, "policy_version": POLICY_VERSION,
        "weighted_score": weighted, "rank": rank, "grade": grade_for_rank(rank),
        "twelve_month_pd": rating_pd(grade_for_rank(rank)),
        "factors": scored,
        "missing_inputs": [s["field"] for s in scored if not s["available"]],
        "assumption": SYNTHETIC_ASSUMPTION,
    }


# ------------------------------------------------------------------- SICR


#: Notches of downgrade since ORIGINATION that trigger Stage 2 on their own.
#: Three, not one. Brief §3.3 is explicit that one downgrade must not stage an
#: account automatically, and question A6.27 asks the Cockpit to explain this
#: rule and then check the actual cases against it.
SICR_NOTCH_THRESHOLD = 3

#: Relative increase in lifetime PD since origination that triggers Stage 2.
SICR_RELATIVE_PD_INCREASE = 2.0
#: Absolute floor below which the relative test is not applied, so a move from
#: 0.03% to 0.09% does not stage an investment-grade account.
SICR_ABSOLUTE_PD_FLOOR = 0.01

#: The backstop. Thirty days past due is a presumption of significant increase.
SICR_DPD_BACKSTOP = 30
#: Ninety days past due is the default definition used throughout this demo.
DEFAULT_DPD = 90

SICR_POLICY_ID = "COCKPIT_DEMO_SICR_V1"

#: NPL and Stage 3 are declared to coincide in this demo, and that declaration
#: is recorded rather than assumed. Brief §3.3.
NPL_EQUALS_STAGE_3 = True
NPL_POLICY_NOTE = (
    "In this demonstration an account is non-performing exactly when it is "
    "credit-impaired and in Stage 3. That is a stated demo policy, not a "
    "universal identity between the two definitions.")


def assess_sicr(*, origination_rank: int, current_rank: int,
                origination_lifetime_pd: float, current_lifetime_pd: float,
                days_past_due: int, watchlist: bool = False,
                manual_override_stage: int | None = None,
                override_reason: str = "") -> dict[str, Any]:
    """Which stage this account is in, and which rule put it there.

    Order matters and is stated: default first, then the past-due backstop,
    then the quantitative PD test, then the notch test, then watchlist, then
    Stage 1. A manual override wins over all of them and must carry a reason.
    """
    reasons: list[str] = []

    if manual_override_stage is not None:
        return {"stage": int(manual_override_stage),
                "trigger": "manual_override",
                "reason": override_reason or "manual override, reason not recorded",
                "policy_id": SICR_POLICY_ID, "policy_version": POLICY_VERSION,
                "overridden": True}

    if current_rank >= DEFAULT_RANK or days_past_due >= DEFAULT_DPD:
        return {"stage": 3, "trigger": "default",
                "reason": (f"the account meets the demo default definition: "
                           f"{days_past_due} days past due against a "
                           f"{DEFAULT_DPD}-day definition"
                           if days_past_due >= DEFAULT_DPD else
                           "the account is graded D on the master scale"),
                "policy_id": SICR_POLICY_ID, "policy_version": POLICY_VERSION,
                "overridden": False}

    if days_past_due >= SICR_DPD_BACKSTOP:
        reasons.append(f"{days_past_due} days past due, against the "
                       f"{SICR_DPD_BACKSTOP}-day backstop")

    notches = current_rank - origination_rank
    relative = (current_lifetime_pd / origination_lifetime_pd
                if origination_lifetime_pd > 0 else 0.0)
    if (current_lifetime_pd >= SICR_ABSOLUTE_PD_FLOOR
            and relative >= SICR_RELATIVE_PD_INCREASE):
        reasons.append(
            f"lifetime PD has risen {relative:.2f}x since origination, at or "
            f"above the {SICR_RELATIVE_PD_INCREASE:.1f}x threshold, and is "
            f"above the {SICR_ABSOLUTE_PD_FLOOR:.0%} absolute floor")
    if notches >= SICR_NOTCH_THRESHOLD:
        reasons.append(
            f"{notches} notches of downgrade since origination, at or above "
            f"the {SICR_NOTCH_THRESHOLD}-notch threshold")
    if watchlist:
        reasons.append("the account is on the credit watchlist")

    if reasons:
        return {"stage": 2, "trigger": "sicr", "reason": "; ".join(reasons),
                "policy_id": SICR_POLICY_ID, "policy_version": POLICY_VERSION,
                "overridden": False, "notches": notches,
                "relative_pd_increase": relative}

    return {"stage": 1, "trigger": "none",
            "reason": (f"no significant increase in credit risk: {notches} "
                       f"notch(es) of movement against a "
                       f"{SICR_NOTCH_THRESHOLD}-notch threshold, lifetime PD "
                       f"at {relative:.2f}x origination against a "
                       f"{SICR_RELATIVE_PD_INCREASE:.1f}x threshold, and "
                       f"{days_past_due} days past due"),
            "policy_id": SICR_POLICY_ID, "policy_version": POLICY_VERSION,
            "overridden": False, "notches": notches,
            "relative_pd_increase": relative}


# ------------------------------------------------------------- recovery/LGD


#: Unsecured loss severity by segment. Demonstration assumptions.
UNSECURED_LGD: dict[str, float] = {
    "Large Corporate": 0.55, "Mid Corporate": 0.62, "SME": 0.70,
}
#: Severity on the secured leg once collateral has been realised — the cost of
#: getting to the money, not the value of the money.
SECURED_LGD: dict[str, float] = {
    "Large Corporate": 0.18, "Mid Corporate": 0.22, "SME": 0.28,
}

#: Haircut applied to a collateral valuation before it is recognised, by asset
#: type, and the expected years from default to realisation.
COLLATERAL_POLICY: dict[str, dict[str, float]] = {
    "Commercial property": {"haircut": 0.30, "recovery_lag_years": 2.0},
    "Residential property": {"haircut": 0.25, "recovery_lag_years": 1.5},
    "Industrial property": {"haircut": 0.35, "recovery_lag_years": 2.5},
    "Plant and machinery": {"haircut": 0.50, "recovery_lag_years": 1.5},
    "Inventory": {"haircut": 0.60, "recovery_lag_years": 0.75},
    "Receivables": {"haircut": 0.40, "recovery_lag_years": 0.5},
    "Listed securities": {"haircut": 0.20, "recovery_lag_years": 0.25},
    "Cash deposit": {"haircut": 0.00, "recovery_lag_years": 0.0},
}

#: A valuation older than this is stale, and the Cockpit says so rather than
#: quietly using it as though it were current.
STALE_VALUATION_DAYS = 540
#: A financial statement older than this is stale for rating purposes.
STALE_STATEMENT_DAYS = 450
#: A rating older than this is stale.
STALE_RATING_DAYS = 400

#: Expected recovery on a credit-impaired account, by segment, before the
#: collateral it actually holds is taken into account.
IMPAIRED_BASE_RECOVERY: dict[str, float] = {
    "Large Corporate": 0.42, "Mid Corporate": 0.36, "SME": 0.30,
}
IMPAIRED_RECOVERY_LAG_YEARS = 2.0

RECOVERY_POLICY_ID = "COCKPIT_DEMO_RECOVERY_V1"


# ---------------------------------------------------------------- scenarios


#: The three-scenario demo set. Weights sum to one exactly.
SCENARIOS: tuple[dict[str, Any], ...] = (
    {"scenario_id": "base", "label": "Base", "weight": 0.60},
    {"scenario_id": "upturn", "label": "Upturn", "weight": 0.20},
    {"scenario_id": "downturn", "label": "Downturn", "weight": 0.20},
)
SCENARIO_IDS = tuple(s["scenario_id"] for s in SCENARIOS)
SCENARIO_WEIGHT = {s["scenario_id"]: s["weight"] for s in SCENARIOS}


# ------------------------------------------------------------ macro model


#: The demo macroeconomic candidate set. Brief §3.3 is explicit that this is a
#: proposed demonstration set, NOT a statistically validated "top ten".
MACRO_PREDICTORS: tuple[dict[str, Any], ...] = (
    {"predictor": "real_gdp_growth", "label": "Real GDP growth",
     "unit": "percent per annum", "direction": "higher is better"},
    {"predictor": "inflation", "label": "Consumer price inflation",
     "unit": "percent per annum", "direction": "context dependent"},
    {"predictor": "unemployment", "label": "Unemployment rate",
     "unit": "percent", "direction": "lower is better"},
    {"predictor": "policy_rate", "label": "Policy interest rate",
     "unit": "percent", "direction": "lower is better for borrowers"},
    {"predictor": "government_bond_yield", "label": "10-year government bond yield",
     "unit": "percent", "direction": "lower is better for borrowers"},
    {"predictor": "exchange_rate_move", "label": "Exchange rate movement",
     "unit": "percent change against the reporting currency",
     "direction": ("context dependent: it is not a basis-point measure and its "
                   "sign helps an exporter and hurts an importer")},
    {"predictor": "commercial_property_prices", "label": "Commercial property prices",
     "unit": "percent change", "direction": "higher is better"},
    {"predictor": "oil_price_move", "label": "Oil price movement",
     "unit": "percent change", "direction": "context dependent"},
    {"predictor": "industrial_production", "label": "Industrial production growth",
     "unit": "percent per annum", "direction": "higher is better"},
    {"predictor": "real_household_income", "label": "Real household income growth",
     "unit": "percent per annum", "direction": "higher is better"},
)
MACRO_PREDICTOR_IDS = tuple(m["predictor"] for m in MACRO_PREDICTORS)


@dataclass(frozen=True)
class MacroSensitivity:
    """One declared dependency of a segment's PD or LGD on one predictor."""

    sector: str
    predictor: str
    #: "pd" or "lgd". A predictor that enters LGD does not thereby enter PD.
    target: str
    #: Coefficient on the STANDARDISED, LAGGED predictor, in log-odds for PD.
    coefficient: float
    lag_quarters: int
    note: str = ""


#: Not every predictor enters every model, and the Cockpit must be able to say
#: which ones do (question A8.36) and which affect LGD rather than PD (A8.40).
MACRO_SENSITIVITIES: tuple[MacroSensitivity, ...] = (
    # Construction — property-cycle sensitive on both PD and recovery.
    MacroSensitivity("Construction", "real_gdp_growth", "pd", -0.42, 1),
    MacroSensitivity("Construction", "policy_rate", "pd", 0.30, 2),
    MacroSensitivity("Construction", "commercial_property_prices", "pd", -0.22, 1),
    MacroSensitivity("Construction", "commercial_property_prices", "lgd", -0.35, 0,
                     "Enters recovery, not default: it moves what the security "
                     "is worth, not how likely the borrower is to fail."),
    MacroSensitivity("Construction", "unemployment", "pd", 0.18, 2),
    # Manufacturing.
    MacroSensitivity("Manufacturing", "industrial_production", "pd", -0.46, 1),
    MacroSensitivity("Manufacturing", "real_gdp_growth", "pd", -0.28, 1),
    MacroSensitivity("Manufacturing", "policy_rate", "pd", 0.22, 2),
    MacroSensitivity("Manufacturing", "exchange_rate_move", "pd", -0.14, 1,
                     "Exporter-weighted: a weaker reporting currency helps."),
    MacroSensitivity("Manufacturing", "plant_recovery", "lgd", 0.0, 0,
                     "Placeholder removed from the active set; see validation."),
    # Retail Trade.
    MacroSensitivity("Retail Trade", "real_household_income", "pd", -0.50, 1),
    MacroSensitivity("Retail Trade", "unemployment", "pd", 0.34, 1),
    MacroSensitivity("Retail Trade", "inflation", "pd", 0.16, 2),
    # Transport and Logistics.
    MacroSensitivity("Transport and Logistics", "oil_price_move", "pd", 0.30, 1),
    MacroSensitivity("Transport and Logistics", "real_gdp_growth", "pd", -0.32, 1),
    MacroSensitivity("Transport and Logistics", "industrial_production", "pd", -0.20, 2),
    # Hospitality.
    MacroSensitivity("Hospitality", "real_household_income", "pd", -0.44, 1),
    MacroSensitivity("Hospitality", "unemployment", "pd", 0.30, 1),
    MacroSensitivity("Hospitality", "exchange_rate_move", "pd", 0.18, 1,
                     "Importer-weighted: a weaker reporting currency hurts."),
    # Healthcare — deliberately sparse, so 'which predictors enter this model'
    # has a genuinely different answer for at least one sector.
    MacroSensitivity("Healthcare", "real_gdp_growth", "pd", -0.14, 1),
    MacroSensitivity("Healthcare", "policy_rate", "pd", 0.12, 2),
    # Information Technology.
    MacroSensitivity("Information Technology", "real_gdp_growth", "pd", -0.24, 1),
    MacroSensitivity("Information Technology", "exchange_rate_move", "pd", -0.20, 1),
    MacroSensitivity("Information Technology", "policy_rate", "pd", 0.16, 2),
    # Real Estate.
    MacroSensitivity("Real Estate", "commercial_property_prices", "pd", -0.40, 1),
    MacroSensitivity("Real Estate", "policy_rate", "pd", 0.34, 2),
    MacroSensitivity("Real Estate", "real_gdp_growth", "pd", -0.20, 1),
    MacroSensitivity("Real Estate", "commercial_property_prices", "lgd", -0.45, 0,
                     "Enters recovery: collateral values move with the index."),
)

#: Dropped from the active set but kept above so the validation gate has
#: something real to reject. `active_sensitivities` is what the model uses.
_INACTIVE = {("Manufacturing", "plant_recovery", "lgd")}

MACRO_MODEL_ID = "COCKPIT_DEMO_MACRO_PD_V1"
#: The PD transform is bounded so a scenario can never drive PD to 0 or 1.
PD_FLOOR = 0.0001
PD_CAP = 0.9500
LGD_FLOOR = 0.02
LGD_CAP = 0.95


def active_sensitivities(sector: str = "", target: str = "") -> list[MacroSensitivity]:
    """The dependencies actually in the model, optionally for one sector."""
    out = [s for s in MACRO_SENSITIVITIES
           if (s.sector, s.predictor, s.target) not in _INACTIVE]
    if sector:
        out = [s for s in out if s.sector == sector]
    if target:
        out = [s for s in out if s.target == target]
    return out


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-12), 1 - 1e-12)
    return math.log(p / (1.0 - p))


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def macro_adjusted_pd(*, base_pd: float, sector: str,
                      standardised: dict[str, float]) -> dict[str, Any]:
    """A bounded logistic adjustment of the rating-linked PD. Brief §4.2.

    `standardised` maps predictor to its standardised, already-lagged value for
    the scenario and period being modelled. Predictors with no declared
    sensitivity for this sector are ignored — and the fact that they were
    ignored is returned, because "which of these ten actually enter the model
    for Construction" is a question the Cockpit must answer from the model
    rather than from the predictor list.
    """
    used: list[dict[str, Any]] = []
    shift = 0.0
    for s in active_sensitivities(sector, "pd"):
        x = float(standardised.get(s.predictor, 0.0))
        term = s.coefficient * x
        shift += term
        used.append({"predictor": s.predictor, "coefficient": s.coefficient,
                     "lag_quarters": s.lag_quarters, "standardised_value": x,
                     "log_odds_contribution": term, "note": s.note})

    adjusted = _logistic(_logit(base_pd) + shift)
    return {
        "model_id": MACRO_MODEL_ID, "policy_version": POLICY_VERSION,
        "base_pd": base_pd, "log_odds_shift": shift,
        "adjusted_pd": min(max(adjusted, PD_FLOOR), PD_CAP),
        "floor": PD_FLOOR, "cap": PD_CAP,
        "predictors_used": used,
        "predictors_not_in_model": [
            p for p in MACRO_PREDICTOR_IDS
            if p not in {u["predictor"] for u in used}],
        "transform": ("bounded logistic on the rating-linked twelve-month PD: "
                      "logistic(logit(base_pd) + sum(coefficient * "
                      "standardised predictor))"),
        "assumption": SYNTHETIC_ASSUMPTION,
    }


def macro_adjusted_lgd(*, base_lgd: float, sector: str,
                       standardised: dict[str, float]) -> dict[str, Any]:
    """The same treatment for loss severity, on its own declared dependencies."""
    used: list[dict[str, Any]] = []
    shift = 0.0
    for s in active_sensitivities(sector, "lgd"):
        x = float(standardised.get(s.predictor, 0.0))
        term = s.coefficient * x
        shift += term
        used.append({"predictor": s.predictor, "coefficient": s.coefficient,
                     "lag_quarters": s.lag_quarters, "standardised_value": x,
                     "log_odds_contribution": term, "note": s.note})
    adjusted = _logistic(_logit(base_lgd) + shift)
    return {"model_id": MACRO_MODEL_ID, "base_lgd": base_lgd,
            "log_odds_shift": shift,
            "adjusted_lgd": min(max(adjusted, LGD_FLOOR), LGD_CAP),
            "predictors_used": used, "assumption": SYNTHETIC_ASSUMPTION}


# ------------------------------------------------------------------ CCF/EAD


#: Credit conversion factors by product. Applied to the UNDRAWN commitment;
#: exposure and EAD are different numbers throughout and the schema keeps them
#: in separate fields.
CCF: dict[str, float] = {
    "Term Loan": 0.00,
    "Revolving Credit Facility": 0.55,
    "Working Capital Line": 0.50,
    "Overdraft": 0.45,
    "Trade Finance": 0.30,
    "Project Finance": 0.60,
    "Guarantee": 0.50,
}

#: Whether the product amortises over its remaining term.
AMORTISING: dict[str, bool] = {
    "Term Loan": True, "Project Finance": True, "Trade Finance": False,
    "Revolving Credit Facility": False, "Working Capital Line": False,
    "Overdraft": False, "Guarantee": False,
}


# ----------------------------------------------------------------- covenants


#: The covenant tests the demo book carries, with a direction and a comparison
#: operator so the Cockpit reports the actual contractual test rather than a
#: breach count. Brief §3.3.
COVENANT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"covenant_id": "DSCR_MIN", "metric": "dscr",
     "label": "Minimum debt service coverage",
     "formula": "cash available for debt service / (scheduled principal + cash interest)",
     "operator": ">=", "tolerance": 0.02, "frequency": "quarterly",
     "materiality": "high"},
    {"covenant_id": "LEVERAGE_MAX", "metric": "net_debt_to_ebitda",
     "label": "Maximum net leverage",
     "formula": "(total debt - cash) / EBITDA, trailing twelve months",
     "operator": "<=", "tolerance": 0.10, "frequency": "quarterly",
     "materiality": "high"},
    {"covenant_id": "ICR_MIN", "metric": "interest_coverage",
     "label": "Minimum interest cover",
     "formula": "EBIT / interest expense, trailing twelve months",
     "operator": ">=", "tolerance": 0.05, "frequency": "semiannual",
     "materiality": "medium"},
    {"covenant_id": "CURRENT_MIN", "metric": "current_ratio",
     "label": "Minimum current ratio",
     "formula": "total current assets / total current liabilities",
     "operator": ">=", "tolerance": 0.05, "frequency": "quarterly",
     "materiality": "medium"},
    {"covenant_id": "GEARING_MAX", "metric": "debt_to_equity",
     "label": "Maximum gearing",
     "formula": "total debt / total equity",
     "operator": "<=", "tolerance": 0.10, "frequency": "annual",
     "materiality": "low"},
)
COVENANT_BY_ID = {c["covenant_id"]: c for c in COVENANT_DEFINITIONS}

#: Days after a breach within which a cure is contractually permitted.
COVENANT_CURE_DAYS = 60

COVENANT_POLICY_ID = "COCKPIT_DEMO_COVENANTS_V1"


def test_covenant(definition: dict[str, Any], observed: float | None,
                  threshold: float) -> dict[str, Any]:
    """Run one covenant test and report headroom in the metric's own units."""
    if observed is None:
        return {"covenant_id": definition["covenant_id"], "tested": False,
                "breached": None, "near_breach": None, "headroom": None,
                "reason": "the observed value for this test is not available"}
    v = float(observed)
    t = float(threshold)
    tol = float(definition["tolerance"])
    if definition["operator"] == ">=":
        breached = v < t
        headroom = v - t
        near = (not breached) and headroom <= tol
    else:
        breached = v > t
        headroom = t - v
        near = (not breached) and headroom <= tol
    return {"covenant_id": definition["covenant_id"], "tested": True,
            "observed": v, "threshold": t, "operator": definition["operator"],
            "breached": bool(breached), "near_breach": bool(near),
            "headroom": headroom, "tolerance": tol,
            "policy_id": COVENANT_POLICY_ID}


# ------------------------------------------------------------------ overlays


#: Named management overlays. Each is separately identified at every date and
#: never folded into a parameter. Brief §4.3.
OVERLAYS: tuple[dict[str, Any], ...] = (
    {"overlay_id": "OVL_CONSTRUCTION_CYCLE",
     "label": "Construction sector cycle overlay",
     "sector": "Construction",
     "rationale": ("A demonstration overlay standing for model risk the "
                   "committee judged the through-the-cycle PD not to capture."),
     "basis": "percentage of modelled ECL on the sector"},
    {"overlay_id": "OVL_SME_DATA_QUALITY",
     "label": "SME statement-availability overlay",
     "segment": "SME",
     "rationale": ("A demonstration overlay standing for the uncertainty in "
                   "rating SME borrowers on stale statements."),
     "basis": "percentage of modelled ECL on the segment"},
)
OVERLAY_BY_ID = {o["overlay_id"]: o for o in OVERLAYS}


def policy_manifest() -> dict[str, Any]:
    """Everything above, as one machine-readable block for the Trace."""
    return {
        "policy_version": POLICY_VERSION,
        "assumption": SYNTHETIC_ASSUMPTION,
        "rating": {"scale_id": RATING_SCALE_ID, "model_id": RATING_MODEL_ID,
                   "model_version": RATING_MODEL_VERSION,
                   "grades": [dict(r) for r in RATING_SCALE],
                   "factors": [{"field": f.field, "label": f.label,
                                "weight": f.weight,
                                "higher_is_better": f.higher_is_better,
                                "missing_score": f.missing_score}
                               for f in RATING_FACTORS]},
        "sicr": {"policy_id": SICR_POLICY_ID,
                 "notch_threshold": SICR_NOTCH_THRESHOLD,
                 "relative_pd_increase": SICR_RELATIVE_PD_INCREASE,
                 "absolute_pd_floor": SICR_ABSOLUTE_PD_FLOOR,
                 "dpd_backstop": SICR_DPD_BACKSTOP,
                 "default_dpd": DEFAULT_DPD,
                 "npl_equals_stage_3": NPL_EQUALS_STAGE_3,
                 "npl_note": NPL_POLICY_NOTE},
        "recovery": {"policy_id": RECOVERY_POLICY_ID,
                     "unsecured_lgd": dict(UNSECURED_LGD),
                     "secured_lgd": dict(SECURED_LGD),
                     "collateral": {k: dict(v)
                                    for k, v in COLLATERAL_POLICY.items()},
                     "impaired_base_recovery": dict(IMPAIRED_BASE_RECOVERY),
                     "impaired_recovery_lag_years": IMPAIRED_RECOVERY_LAG_YEARS,
                     "stale_valuation_days": STALE_VALUATION_DAYS},
        "scenarios": [dict(s) for s in SCENARIOS],
        "macro": {"model_id": MACRO_MODEL_ID,
                  "predictors": [dict(m) for m in MACRO_PREDICTORS],
                  "sensitivities": [
                      {"sector": s.sector, "predictor": s.predictor,
                       "target": s.target, "coefficient": s.coefficient,
                       "lag_quarters": s.lag_quarters, "note": s.note}
                      for s in active_sensitivities()],
                  "pd_floor": PD_FLOOR, "pd_cap": PD_CAP,
                  "candidate_set_note": (
                      "A proposed demonstration set of ten macroeconomic "
                      "predictors. It is not a statistically validated 'top "
                      "ten' and no selection procedure produced it.")},
        "ccf": dict(CCF),
        "covenants": {"policy_id": COVENANT_POLICY_ID,
                      "cure_days": COVENANT_CURE_DAYS,
                      "definitions": [dict(c) for c in COVENANT_DEFINITIONS]},
        "overlays": [dict(o) for o in OVERLAYS],
        "staleness": {"valuation_days": STALE_VALUATION_DAYS,
                      "statement_days": STALE_STATEMENT_DAYS,
                      "rating_days": STALE_RATING_DAYS},
    }


__all__ = [
    "AMORTISING", "CCF", "COLLATERAL_POLICY", "COVENANT_BY_ID",
    "COVENANT_CURE_DAYS", "COVENANT_DEFINITIONS", "COVENANT_POLICY_ID",
    "DEFAULT_DPD", "DEFAULT_RANK", "IMPAIRED_BASE_RECOVERY",
    "IMPAIRED_RECOVERY_LAG_YEARS", "LGD_CAP", "LGD_FLOOR", "MACRO_MODEL_ID",
    "MACRO_PREDICTORS", "MACRO_PREDICTOR_IDS", "MACRO_SENSITIVITIES",
    "MacroSensitivity", "NPL_EQUALS_STAGE_3", "NPL_POLICY_NOTE", "OVERLAYS",
    "OVERLAY_BY_ID", "PD_CAP", "PD_FLOOR", "RATING_BY_GRADE", "RATING_BY_RANK",
    "RATING_FACTORS", "RATING_MODEL_ID", "RATING_MODEL_VERSION",
    "RATING_SCALE", "RATING_SCALE_ID", "RECOVERY_POLICY_ID", "SCENARIOS",
    "SCENARIO_IDS", "SCENARIO_WEIGHT", "SECURED_LGD",
    "SICR_ABSOLUTE_PD_FLOOR", "SICR_DPD_BACKSTOP", "SICR_NOTCH_THRESHOLD",
    "SICR_POLICY_ID", "SICR_RELATIVE_PD_INCREASE", "STALE_RATING_DAYS",
    "STALE_STATEMENT_DAYS", "STALE_VALUATION_DAYS", "SYNTHETIC_ASSUMPTION",
    "UNSECURED_LGD", "WORST_PERFORMING_RANK", "active_sensitivities",
    "assess_sicr", "grade_for_rank", "macro_adjusted_lgd", "macro_adjusted_pd",
    "policy_manifest", "rate_borrower", "rating_pd", "score_factor",
    "score_to_rank", "test_covenant",
]
