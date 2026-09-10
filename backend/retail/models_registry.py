"""
The model registry: which features belong to which scorecard, and their bins.

This file is the answer to "show me every variable the model actually uses".
There is no other list. The canonical dataset's flattened score columns are
generated from these definitions, and the schema gate compares the two, so a
feature cannot be scored without a raw column or carried as a column nobody
scores.

All coefficients, bin boundaries and weights of evidence are SYNTHETIC
demonstration values.
"""

from __future__ import annotations

from typing import Sequence

from backend.retail.scorecards import Feature, Scorecard
from backend.retail.taxonomy import AUTO_LOAN, CREDIT_CARD, HOME_LOAN, PERSONAL_LOAN

APPLICATION_TARGET_ID = "retail-app-target-first-default-12m-1.0.0"
BEHAVIOURAL_TARGET_ID = "retail-beh-target-first-default-12m-1.0.0"

APPLICATION_TARGET_EVENT = (
    "First new default (90+ DPD or recorded unlikeliness to pay) within 12 months "
    "of origination, among facilities not already in default at origination."
)
BEHAVIOURAL_TARGET_EVENT = (
    "First new default (90+ DPD or recorded unlikeliness to pay) within 12 months "
    "of the score date, among facilities performing and not in default at that date."
)

TRANSFORM_VERSION = "retail-woe-1.0.0"


def _num(
    short: str, source: str, business_name: str, coef: float,
    edges: Sequence[float], woes: Sequence[float],
    *, unit: str | None = None, definition: str = "", woe_missing: float = -0.25,
) -> Feature:
    labels = _numeric_labels(edges)
    return Feature(
        short=short, source=source, business_name=business_name, kind="numeric",
        coefficient=coef, edges=tuple(float(e) for e in edges), labels=labels,
        woe={lab: float(w) for lab, w in zip(labels, woes)},
        woe_missing=woe_missing, unit=unit, definition=definition,
    )


def _numeric_labels(edges: Sequence[float]) -> tuple[str, ...]:
    """Readable, unambiguous bin labels: [lo, hi) with the open ends named."""
    def fmt(x: float) -> str:
        return f"{x:g}"
    labels = [f"<{fmt(edges[0])}"]
    for lo, hi in zip(edges, edges[1:]):
        labels.append(f"{fmt(lo)}-{fmt(hi)}")
    labels.append(f">={fmt(edges[-1])}")
    return tuple(labels)


def _cat(
    short: str, source: str, business_name: str, coef: float, woe: dict[str, float],
    *, definition: str = "", woe_missing: float = -0.25,
) -> Feature:
    return Feature(
        short=short, source=source, business_name=business_name, kind="categorical",
        coefficient=coef, edges=(), labels=tuple(woe), woe=dict(woe),
        woe_missing=woe_missing, definition=definition,
    )


# ==========================================================================
# Application features — measured at origination and frozen thereafter.
# ==========================================================================

APP_FEATURES: dict[str, Feature] = {
    "income": _num(
        "income", "origination_income_sar", "Verified monthly income at application", 0.35,
        (5_000, 10_000, 20_000, 35_000, 60_000),
        (-0.55, -0.25, 0.05, 0.30, 0.50, 0.65),
        unit="SAR/month",
        definition="Total verified monthly income evidenced at application.",
    ),
    "dbr": _num(
        "dbr", "origination_debt_burden_ratio", "Debt burden ratio at application", 0.55,
        (0.15, 0.30, 0.45, 0.55), (0.60, 0.30, -0.05, -0.45, -0.85),
        unit="ratio",
        definition="Total monthly credit obligations divided by verified total monthly income at application, this facility's instalment included exactly once.",
    ),
    "disposable": _num(
        "disposable", "origination_disposable_income_sar", "Disposable income at application", 0.30,
        (2_000, 5_000, 10_000, 20_000), (-0.70, -0.25, 0.10, 0.40, 0.60),
        unit="SAR/month",
        definition="Verified income less household expenses and all credit obligations at application.",
    ),
    "emp_tenure": _num(
        "emp_tenure", "origination_employment_tenure_months", "Employment tenure at application", 0.30,
        (12, 36, 60, 120), (-0.60, -0.20, 0.10, 0.35, 0.50),
        unit="months", definition="Months with the current employer at application.",
    ),
    "cust_tenure": _num(
        "cust_tenure", "origination_customer_tenure_months", "Relationship tenure at application", 0.20,
        (6, 24, 60), (-0.40, -0.10, 0.20, 0.40),
        unit="months", definition="Months as a customer of the bank at application. Zero for new-to-bank.",
    ),
    "salary_transfer": _cat(
        "salary_transfer", "origination_salary_transfer_status", "Salary transfer at application", 0.55,
        {"YES": 0.35, "NO": -0.55},
        definition="Whether salary was mandated to transfer to the bank at application.",
    ),
    "bureau_score": _num(
        "bureau_score", "bureau_score_at_origination", "Bureau score at origination", 0.70,
        (550, 620, 680, 740), (-0.95, -0.40, 0.05, 0.45, 0.85),
        unit="points",
        definition="Synthetic bureau proxy score as at origination, on the synthetic 300-900 proxy scale.",
        woe_missing=-0.30,
    ),
    "bureau_enquiries": _num(
        "bureau_enquiries", "origination_bureau_enquiries_3m", "Bureau enquiries in 3m at application", 0.30,
        (1, 3, 6), (0.35, 0.05, -0.35, -0.75),
        unit="count", definition="Credit enquiries recorded by the synthetic bureau proxy in the three months before application.",
    ),
    "bureau_dpd": _num(
        "bureau_dpd", "origination_bureau_external_dpd_max", "External delinquency at application", 0.45,
        (1, 30, 60), (0.40, -0.10, -0.60, -1.10),
        unit="days", definition="Worst days past due on external obligations reported at application.",
    ),
    "bureau_facilities": _num(
        "bureau_facilities", "origination_bureau_active_facilities", "External active obligations at application", 0.20,
        (2, 4, 7), (0.30, 0.10, -0.20, -0.55),
        unit="count", definition="Active external credit facilities reported at application.",
    ),
    "amount_to_income": _num(
        "amount_to_income", "origination_amount_to_income_ratio", "Requested amount to monthly income", 0.25,
        (3, 6, 12, 24), (0.40, 0.15, -0.10, -0.40, -0.70),
        unit="x", definition="Original finance amount (or approved card limit) divided by verified monthly income at application.",
    ),
    "instalment_to_income": _num(
        "instalment_to_income", "origination_instalment_to_income_ratio", "Instalment to monthly income", 0.35,
        (0.10, 0.20, 0.30, 0.40), (0.45, 0.20, -0.05, -0.35, -0.70),
        unit="ratio", definition="Scheduled monthly instalment divided by verified monthly income at application.",
    ),
    "tenor": _num(
        "tenor", "original_tenor_months", "Original tenor", 0.15,
        (24, 48, 60, 120), (0.25, 0.10, -0.10, -0.20, -0.30),
        unit="months", definition="Contractual tenor granted at origination.",
    ),
    "ltv": _num(
        "ltv", "ltv_origination_ratio", "Loan to value at origination", 0.35,
        (0.60, 0.70, 0.80, 0.90), (0.45, 0.20, -0.05, -0.30, -0.60),
        unit="ratio", definition="Original finance amount divided by collateral value at origination.",
    ),
    "balloon_ratio": _num(
        "balloon_ratio", "origination_balloon_ratio", "Balloon share of finance amount", 0.25,
        (0.001, 0.20, 0.35), (0.20, 0.05, -0.25, -0.55),
        unit="ratio", definition="Final balloon payment divided by the original finance amount. Zero where the contract has no balloon.",
    ),
    "income_stability": _num(
        "income_stability", "origination_income_stability_ratio", "Income stability before application", 0.25,
        (0.80, 0.90, 0.97), (-0.55, -0.20, 0.10, 0.30),
        unit="ratio",
        definition="Lowest observed monthly salary credit divided by the mean, over the pre-application months actually available. Null where too little history exists.",
        woe_missing=-0.15,
    ),
}

_APP_CORE = (
    "income", "dbr", "disposable", "emp_tenure", "cust_tenure", "salary_transfer",
    "bureau_score", "bureau_enquiries", "bureau_dpd", "bureau_facilities", "amount_to_income",
)

APPLICATION_FEATURE_SETS: dict[str, tuple[str, ...]] = {
    CREDIT_CARD: _APP_CORE,
    PERSONAL_LOAN: _APP_CORE + ("instalment_to_income", "tenor", "income_stability"),
    AUTO_LOAN: _APP_CORE + ("instalment_to_income", "tenor", "ltv", "balloon_ratio"),
    HOME_LOAN: _APP_CORE + ("instalment_to_income", "tenor", "ltv", "income_stability"),
}

APPLICATION_INTERCEPTS: dict[str, float] = {
    CREDIT_CARD: -3.35, PERSONAL_LOAN: -3.55, AUTO_LOAN: -3.85, HOME_LOAN: -4.50,
}


# ==========================================================================
# Behavioural features — recomputed monthly from information available by the
# score date. Nothing here may read a future month.
# ==========================================================================

BEH_FEATURES: dict[str, Feature] = {
    "dpd": _num(
        "dpd", "dpd", "Days past due", 0.60,
        (1, 30, 60, 90), (0.55, -0.15, -0.95, -1.60, -2.40),
        unit="days", definition="Days past due at the score date.", woe_missing=-0.40,
    ),
    "max_dpd_6m": _num(
        "max_dpd_6m", "max_dpd_6m", "Worst DPD in 6 months", 0.40,
        (1, 30, 60), (0.45, -0.05, -0.70, -1.30),
        unit="days", definition="Highest days past due observed in the six months to the score date.",
    ),
    "missed_6m": _num(
        "missed_6m", "missed_payment_count_6m", "Missed payments in 6 months", 0.40,
        (1, 2, 4), (0.40, -0.10, -0.60, -1.10),
        unit="count", definition="Scheduled payments not met in the six months to the score date.",
    ),
    "pay_ratio_3m": _num(
        "pay_ratio_3m", "payment_to_due_ratio_3m", "Payment to due ratio over 3 months", 0.45,
        (0.5, 0.9, 1.0, 1.5), (-1.10, -0.45, 0.10, 0.35, 0.55),
        unit="ratio", definition="Payments received divided by amounts due over the three months to the score date.",
    ),
    "utilisation": _num(
        "utilisation", "utilisation_ratio", "Card utilisation", 0.40,
        (0.2, 0.4, 0.6, 0.8, 1.0), (0.45, 0.25, 0.00, -0.30, -0.65, -1.00),
        unit="ratio", definition="Drawn balance divided by the current credit limit. Card only.",
    ),
    "util_change": _num(
        "util_change", "utilisation_change_3m_pp", "Utilisation change over 3 months", 0.25,
        (-5, 0, 10, 20), (0.30, 0.15, -0.05, -0.35, -0.65),
        unit="percentage points", definition="Change in utilisation over three months, in percentage points. Card only.",
    ),
    "min_pay": _num(
        "min_pay", "minimum_payment_only_months_3m", "Minimum-payment-only months", 0.30,
        (1, 2, 3), (0.30, -0.05, -0.35, -0.70),
        unit="count", definition="Months in the last three where only the minimum payment was made. Card only.",
    ),
    "overlimit": _num(
        "overlimit", "overlimit_days_3m", "Days over limit in 3 months", 0.25,
        (1, 5, 15), (0.25, -0.20, -0.55, -0.95),
        unit="days", definition="Days spent above the credit limit in the last three months. Card only.",
    ),
    "cash_advance": _num(
        "cash_advance", "cash_advance_share_3m", "Cash advance share", 0.25,
        (0.001, 0.05, 0.20), (0.20, 0.00, -0.35, -0.80),
        unit="ratio", definition="Cash advances as a share of card spend over three months. Card only.",
    ),
    "salary_change": _num(
        "salary_change", "salary_change_3m_ratio", "Salary change over 3 months", 0.35,
        (0.7, 0.9, 1.02, 1.15), (-0.95, -0.40, 0.10, 0.30, 0.35),
        unit="ratio", definition="Latest salary credit divided by the average of the three months before it.",
    ),
    "salary_missed": _num(
        "salary_missed", "salary_missed_cycle_count_3m", "Missed salary cycles", 0.45,
        (1, 2), (0.25, -0.75, -1.40),
        unit="count",
        definition="Expected salary credit cycles with no salary credit observed, in three months. Evidence of income interruption, not proof of job loss.",
    ),
    "income_vol": _num(
        "income_vol", "income_volatility_6m", "Income volatility over 6 months", 0.20,
        (0.05, 0.15, 0.30), (0.30, 0.10, -0.25, -0.60),
        unit="ratio", definition="Coefficient of variation of monthly salary credits over six months.",
    ),
    "buffer": _num(
        "buffer", "balance_buffer_months", "Personal cash buffer", 0.30,
        (0.25, 1, 3), (-0.70, -0.20, 0.20, 0.45),
        unit="months", definition="Average personal account balance divided by monthly credit obligations.",
    ),
    "bureau_change": _num(
        "bureau_change", "bureau_score_change_3m", "Bureau score change over 3 months", 0.30,
        (-40, -15, 0, 15), (-0.85, -0.35, 0.00, 0.20, 0.35),
        unit="points", definition="Change in the synthetic bureau proxy score over three months.",
    ),
    "bureau_dpd": _num(
        "bureau_dpd", "bureau_external_dpd_max", "External delinquency", 0.35,
        (1, 30, 60), (0.35, -0.15, -0.65, -1.15),
        unit="days", definition="Worst days past due currently reported on external obligations.",
    ),
    "ext_oblig_change": _num(
        "ext_oblig_change", "external_obligations_change_3m_sar", "New external obligations", 0.20,
        (0.001, 500, 2_000), (0.25, 0.05, -0.25, -0.60),
        unit="SAR/month", definition="Increase in monthly external credit obligations over three months.",
    ),
    "enquiries": _num(
        "enquiries", "bureau_enquiries_3m", "Bureau enquiries in 3 months", 0.20,
        (1, 3, 6), (0.25, 0.05, -0.30, -0.65),
        unit="count", definition="Credit enquiries recorded by the synthetic bureau proxy in three months.",
    ),
    "broken_promise": _num(
        "broken_promise", "broken_promise_count_3m", "Broken promises to pay", 0.30,
        (1, 2), (0.20, -0.60, -1.15),
        unit="count", definition="Promises to pay not honoured in the last three months.",
    ),
    "autopay_fail": _num(
        "autopay_fail", "autopay_failure_count_3m", "Failed direct debits", 0.25,
        (1, 2), (0.20, -0.45, -0.90),
        unit="count", definition="Direct-debit or standing-order collections that failed in three months.",
    ),
    "mob": _num(
        "mob", "months_on_book", "Months on book", 0.20,
        (6, 12, 36), (-0.35, -0.10, 0.15, 0.30),
        unit="months", definition="Months since origination at the score date.",
    ),
    "balloon_months": _num(
        "balloon_months", "months_to_balloon", "Months to balloon payment", 0.25,
        (3, 6, 12), (-0.55, -0.25, 0.05, 0.20),
        unit="months", definition="Months until the final balloon payment falls due. Auto only, and only where the contract has one.",
        woe_missing=0.0,
    ),
    "ltv_current": _num(
        "ltv_current", "ltv_current_ratio", "Current loan to value", 0.25,
        (0.6, 0.75, 0.9), (0.35, 0.10, -0.25, -0.60),
        unit="ratio", definition="Gross carrying amount divided by current collateral value. Secured products only.",
    ),
}

_BEH_CORE = (
    "dpd", "max_dpd_6m", "missed_6m", "pay_ratio_3m", "salary_change", "salary_missed",
    "income_vol", "buffer", "bureau_change", "bureau_dpd", "ext_oblig_change",
    "enquiries", "broken_promise", "autopay_fail", "mob",
)
_BEH_CARD_ONLY = ("utilisation", "util_change", "min_pay", "overlimit", "cash_advance")

BEHAVIOURAL_FEATURE_SETS: dict[str, tuple[str, ...]] = {
    CREDIT_CARD: _BEH_CORE + _BEH_CARD_ONLY,
    PERSONAL_LOAN: _BEH_CORE,
    AUTO_LOAN: _BEH_CORE + ("balloon_months", "ltv_current"),
    HOME_LOAN: _BEH_CORE + ("ltv_current",),
}

BEHAVIOURAL_INTERCEPTS: dict[str, float] = {
    CREDIT_CARD: -3.20, PERSONAL_LOAN: -3.40, AUTO_LOAN: -3.70, HOME_LOAN: -4.30,
}


# ==========================================================================
# The registry
# ==========================================================================

def _application_scorecard(product: str) -> Scorecard:
    return Scorecard(
        model_id=f"RETAIL_APP_{product}",
        model_version="1.0.0",
        transform_version=TRANSFORM_VERSION,
        prefix="app",
        product_code=product,
        subject_grain="FACILITY",
        target_event=APPLICATION_TARGET_EVENT,
        horizon_months=12,
        target_definition_id=APPLICATION_TARGET_ID,
        intercept=APPLICATION_INTERCEPTS[product],
        features=tuple(APP_FEATURES[k] for k in APPLICATION_FEATURE_SETS[product]),
        description=(
            f"Synthetic application scorecard for {product}. Scored once, at "
            "origination, from evidence available on the application date, and "
            "frozen on every later snapshot."
        ),
    )


def _behavioural_scorecard(product: str) -> Scorecard:
    return Scorecard(
        model_id=f"RETAIL_BEH_{product}",
        model_version="1.0.0",
        transform_version=TRANSFORM_VERSION,
        prefix="beh",
        product_code=product,
        subject_grain="FACILITY",
        target_event=BEHAVIOURAL_TARGET_EVENT,
        horizon_months=12,
        target_definition_id=BEHAVIOURAL_TARGET_ID,
        intercept=BEHAVIOURAL_INTERCEPTS[product],
        features=tuple(BEH_FEATURES[k] for k in BEHAVIOURAL_FEATURE_SETS[product]),
        description=(
            f"Synthetic behavioural scorecard for {product}. Recomputed at every "
            "month-end from information available by that date."
        ),
    )


APPLICATION_SCORECARDS: dict[str, Scorecard] = {
    p: _application_scorecard(p) for p in APPLICATION_FEATURE_SETS
}
BEHAVIOURAL_SCORECARDS: dict[str, Scorecard] = {
    p: _behavioural_scorecard(p) for p in BEHAVIOURAL_FEATURE_SETS
}


def all_scorecards() -> list[Scorecard]:
    return list(APPLICATION_SCORECARDS.values()) + list(BEHAVIOURAL_SCORECARDS.values())


def application_columns() -> list[str]:
    """Every flattened application column, across products.

    A card facility has no `app_ltv_raw`; the column still exists and is null
    with a product-applicability reason, because one canonical wide table is
    the contract and a per-product column set is not.
    """
    seen: dict[str, None] = {}
    for sc in APPLICATION_SCORECARDS.values():
        for c in sc.column_names():
            seen.setdefault(c, None)
    return list(seen)


def behavioural_columns() -> list[str]:
    seen: dict[str, None] = {}
    for sc in BEHAVIOURAL_SCORECARDS.values():
        for c in sc.column_names():
            seen.setdefault(c, None)
    return list(seen)


def required_raw_sources() -> set[str]:
    """Every canonical column any configured model reads."""
    out: set[str] = set()
    for sc in all_scorecards():
        out.update(sc.required_sources())
    return out


def registry_manifest() -> dict[str, object]:
    return {
        "transform_version": TRANSFORM_VERSION,
        "transformation": "Weight of evidence, ln(P(good in bin) / P(bad in bin)); higher is safer.",
        "score_direction": "HIGHER_IS_SAFER",
        "application_target": {
            "target_definition_id": APPLICATION_TARGET_ID,
            "target_event": APPLICATION_TARGET_EVENT,
            "horizon_months": 12,
        },
        "behavioural_target": {
            "target_definition_id": BEHAVIOURAL_TARGET_ID,
            "target_event": BEHAVIOURAL_TARGET_EVENT,
            "horizon_months": 12,
        },
        "models": [sc.to_dict() for sc in all_scorecards()],
        "disclaimer": (
            "Synthetic demonstration scorecards. Not ANB models, not a bureau's "
            "model, and the score scale is a demonstration scale."
        ),
    }
