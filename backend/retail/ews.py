"""
Retail Early Warning: the signal model, built on the canonical book.

No separate EWS seed and no random alert dataset. Every rule reads
`retail_facility_month` — the same rows Cockpit and What-If read — so an alert's
affected exposure and the portfolio's exposure are the same number by
construction.

Three things this module is careful about, because they are what makes an
early-warning screen either useful or noise:

* **Scope.** A salary interruption is a fact about a CUSTOMER. Raising it once
  per facility would show one person three times and count their exposure three
  times over. Customer-scope rules raise one alert and attach the facilities.
* **Evidence.** Every alert carries the measured value, the threshold it
  crossed, the comparator it moved from, and the columns and dates the numbers
  came from. "The customer has lost their job" is not an output; "salary credit
  has not appeared for two expected cycles" is.
* **Lifecycle.** Running the same evaluation twice does not create two alerts.
  A persisting condition updates the alert it already raised; a resolved one
  closes; a condition that returns after closure retriggers deliberately.

Every threshold is a SYNTHETIC demo threshold, configurable by the bank, and
none of them is an ANB limit or a regulatory trigger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from backend.retail import taxonomy as tax

RULEBOOK_VERSION = "retail-ews-rulebook-1.0.0"
THRESHOLD_SOURCE = "Synthetic demo threshold — bank-configurable, not an ANB or regulatory limit"

FACILITY_SCOPE = "FACILITY"
CUSTOMER_SCOPE = "CUSTOMER"
SEGMENT_SCOPE = "SEGMENT"

SEVERITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

STATUS_OPEN = "OPEN"
STATUS_UPDATED = "UPDATED"
STATUS_CLOSED = "CLOSED"
STATUS_RETRIGGERED = "RETRIGGERED"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    name: str
    family: str
    scope: str
    products: tuple[str, ...]
    features: tuple[str, ...]
    lookback_months: int
    unit: str
    threshold: float
    #: Returns (fired, measured value, comparator value) for each row.
    trigger: Callable[[pd.DataFrame, float], tuple[np.ndarray, np.ndarray, np.ndarray]]
    severity: str
    reason_template: str
    recommended_review: str
    trigger_expression: str
    threshold_source: str = THRESHOLD_SOURCE
    suppression_months: int = 0
    retrigger_after_close_months: int = 1

    def applies_to(self, frame: pd.DataFrame) -> np.ndarray:
        return frame["product_code"].isin(self.products).to_numpy()


def _num(frame: pd.DataFrame, col: str) -> np.ndarray:
    """A rule's numeric input, or all-missing when the column is absent.

    A rule whose input is not in the frame must not fire, and must not raise
    either: a missing feed is a precise limitation, not a crash and not a
    guessed value.
    """
    if col not in frame.columns:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype="float64")


def _flag(frame: pd.DataFrame, col: str) -> np.ndarray:
    """A rule's boolean input, or all-False when the column is absent."""
    if col not in frame.columns:
        return np.zeros(len(frame), dtype=bool)
    return frame[col].fillna(False).to_numpy(dtype=bool)


def _ge(col: str, *, comparator: str | None = None):
    def _t(frame: pd.DataFrame, threshold: float):
        v = _num(frame, col)
        c = _num(frame, comparator) if comparator else np.full(len(frame), np.nan)
        return (~np.isnan(v)) & (v >= threshold), v, c
    return _t


def _le(col: str, *, comparator: str | None = None):
    def _t(frame: pd.DataFrame, threshold: float):
        v = _num(frame, col)
        c = _num(frame, comparator) if comparator else np.full(len(frame), np.nan)
        return (~np.isnan(v)) & (v <= threshold), v, c
    return _t


def _worsening(col: str, prev_col: str, *, min_now: float):
    """Fired when a measure both worsened and is now above a floor."""
    def _t(frame: pd.DataFrame, threshold: float):
        v = _num(frame, col)
        p = _num(frame, prev_col)
        fired = (~np.isnan(v)) & (~np.isnan(p)) & ((v - p) >= threshold) & (v >= min_now)
        return fired, v, p
    return _t


def _drop(col: str, prev_col: str):
    """Fired when a measure fell by at least the threshold."""
    def _t(frame: pd.DataFrame, threshold: float):
        v = _num(frame, col)
        p = _num(frame, prev_col)
        fired = (~np.isnan(v)) & (~np.isnan(p)) & ((p - v) >= threshold)
        return fired, v, p
    return _t


ALL_PRODUCTS = tax.PRODUCT_CODES
CARDS = (tax.CREDIT_CARD,)
SECURED = (tax.AUTO_LOAN, tax.HOME_LOAN)
AUTO = (tax.AUTO_LOAN,)


RULES: tuple[Rule, ...] = (
    Rule("RET-EWS-001", "1.0.0", "Delinquency bucket worsening", "REPAYMENT",
         FACILITY_SCOPE, ALL_PRODUCTS, ("dpd", "previous_month_dpd"), 1, "days", 25.0,
         _worsening("dpd", "previous_month_dpd", min_now=30.0), "HIGH",
         "Days past due rose from {comparator:.0f} to {value:.0f} in one month.",
         "Confirm the arrears position and the collections action already taken.",
         "dpd - previous_month_dpd >= 25 AND dpd >= 30"),

    Rule("RET-EWS-002", "1.0.0", "Consecutive missed payments", "REPAYMENT",
         FACILITY_SCOPE, ALL_PRODUCTS, ("missed_payment_count_3m",), 3, "count", 2.0,
         _ge("missed_payment_count_3m"), "HIGH",
         "{value:.0f} scheduled payments missed in the last three months.",
         "Review affordability and whether a restructure is warranted.",
         "missed_payment_count_3m >= 2"),

    Rule("RET-EWS-003", "1.0.0", "Early-life payment failure", "REPAYMENT",
         FACILITY_SCOPE, ALL_PRODUCTS, ("months_on_book", "missed_payment_count_3m"), 3,
         "count", 1.0,
         lambda f, th: (
             (_num(f, "months_on_book") <= 6) & (_num(f, "missed_payment_count_3m") >= th),
             _num(f, "missed_payment_count_3m"), _num(f, "months_on_book")),
         "CRITICAL",
         "A payment was missed within the first six months on book "
         "({comparator:.0f} months on book, {value:.0f} missed).",
         "Check the origination file: affordability evidence, income verification and any exception.",
         "months_on_book <= 6 AND missed_payment_count_3m >= 1"),

    Rule("RET-EWS-004", "1.0.0", "Persistent minimum payment", "CARD_BEHAVIOUR",
         FACILITY_SCOPE, CARDS, ("minimum_payment_only_months_3m",), 3, "count", 3.0,
         _ge("minimum_payment_only_months_3m"), "MEDIUM",
         "Only the minimum payment was made in {value:.0f} of the last three months.",
         "Assess whether the balance is being serviced or simply carried.",
         "minimum_payment_only_months_3m >= 3"),

    Rule("RET-EWS-005", "1.0.0", "Rising card utilisation", "CARD_BEHAVIOUR",
         FACILITY_SCOPE, CARDS, ("utilisation_ratio", "utilisation_change_3m_pp"), 3,
         "percentage points", 15.0,
         lambda f, th: (
             (_num(f, "utilisation_change_3m_pp") >= th) & (_num(f, "utilisation_ratio") >= 0.70),
             _num(f, "utilisation_change_3m_pp"), _num(f, "utilisation_ratio")),
         "MEDIUM",
         "Utilisation rose {value:.0f} percentage points over three months and now stands at "
         "{comparator:.0%}.",
         "Review the limit and whether spending is being funded by the card.",
         "utilisation_change_3m_pp >= 15 AND utilisation_ratio >= 0.70"),

    Rule("RET-EWS-006", "1.0.0", "Over-limit activity", "CARD_BEHAVIOUR",
         FACILITY_SCOPE, CARDS, ("overlimit_days_3m",), 3, "days", 10.0,
         _ge("overlimit_days_3m"), "MEDIUM",
         "{value:.0f} days spent above the credit limit in three months.",
         "Confirm the limit is appropriate and whether over-limit fees are compounding the balance.",
         "overlimit_days_3m >= 10"),

    Rule("RET-EWS-007", "1.0.0", "Rising cash advances", "CARD_BEHAVIOUR",
         FACILITY_SCOPE, CARDS, ("cash_advance_share_3m",), 3, "ratio", 0.20,
         _ge("cash_advance_share_3m"), "MEDIUM",
         "Cash advances are {value:.0%} of card activity over three months.",
         "Cash advance reliance often precedes arrears; review the customer's liquidity.",
         "cash_advance_share_3m >= 0.20"),

    Rule("RET-EWS-008", "1.0.0", "Salary credit interruption", "INCOME",
         CUSTOMER_SCOPE, ALL_PRODUCTS,
         ("salary_missed_cycle_count_3m", "salary_credit_last_date"), 3, "cycles", 2.0,
         _ge("salary_missed_cycle_count_3m"), "HIGH",
         "No salary credit for {value:.0f} expected cycles. This is evidence of income "
         "interruption; it is not proof of job loss.",
         "Verify income continuity with the customer before any action is taken.",
         "salary_missed_cycle_count_3m >= 2"),

    Rule("RET-EWS-009", "1.0.0", "Material income decline", "INCOME",
         CUSTOMER_SCOPE, ALL_PRODUCTS, ("salary_change_3m_ratio",), 3, "ratio", 0.80,
         _le("salary_change_3m_ratio"), "HIGH",
         "The latest salary credit is {value:.0%} of the prior three-month average.",
         "Confirm whether the reduction is permanent and reassess affordability.",
         "salary_change_3m_ratio <= 0.80"),

    Rule("RET-EWS-010", "1.0.0", "Personal cash buffer exhausted", "INCOME",
         CUSTOMER_SCOPE, ALL_PRODUCTS, ("balance_buffer_months",), 3, "months", 0.15,
         _le("balance_buffer_months"), "MEDIUM",
         "Average account balance covers only {value:.2f} months of credit obligations.",
         "A customer with no buffer misses the next disruption. Review before it happens.",
         "balance_buffer_months <= 0.15"),

    # Compared against the PRIOR MONTH, not against origination.
    #
    # The closeout review: against origination this fired on 3,377 of 14,251
    # customers — 23.7% of the book, at HIGH — because a customer who took a
    # second facility genuinely does carry a higher debt burden than at the
    # first one's origination. That is a true statement and a useless alert: it
    # describes the book's ordinary lifecycle rather than a deterioration.
    #
    # Against the prior month the same rule raises 386 customers (2.7%), and it
    # answers the question the rule is named for. Origination stays in the
    # alert as CONTEXT — the reader still sees where the burden started —
    # through `origination_debt_burden_ratio` in the alert's source columns.
    #
    # Counted at 2026-08. See docs/RETAIL_EWS_011_REVIEW.md.
    Rule("RET-EWS-011", "1.1.0", "Affordability deterioration", "AFFORDABILITY",
         CUSTOMER_SCOPE, ALL_PRODUCTS,
         ("debt_burden_ratio", "previous_month_debt_burden_ratio"), 1, "ratio",
         0.05,
         _worsening("debt_burden_ratio", "previous_month_debt_burden_ratio",
                    min_now=0.65),
         "HIGH",
         "Debt burden has risen from {comparator:.0%} last month to {value:.0%}.",
         "Reassess disposable income before any further limit or facility is granted.",
         "debt_burden_ratio - previous_month_debt_burden_ratio >= 0.05 "
         "AND debt_burden_ratio >= 0.65"),

    Rule("RET-EWS-012", "1.0.0", "New external obligations", "AFFORDABILITY",
         CUSTOMER_SCOPE, ALL_PRODUCTS, ("external_obligations_change_3m_sar",), 3,
         "SAR/month", 2500.0,
         _ge("external_obligations_change_3m_sar"), "MEDIUM",
         "Verified external monthly obligations rose by SAR {value:,.0f} over three months.",
         "Confirm the new borrowing and recompute the debt burden.",
         "external_obligations_change_3m_sar >= 2500"),

    Rule("RET-EWS-013", "1.0.0", "Behavioural score deterioration", "SCORE",
         FACILITY_SCOPE, ALL_PRODUCTS, ("beh_score_value", "behavioural_score_previous_month"), 3,
         "points", 60.0,
         _drop("beh_score_value", "behavioural_score_previous_month"), "MEDIUM",
         "The behavioural score fell {comparator:.0f} to {value:.0f}.",
         "Look at which inputs moved before treating the score itself as the finding.",
         "behavioural_score_previous_month - beh_score_value >= 60"),

    Rule("RET-EWS-014", "1.0.0", "Score input quality exception", "DATA_QUALITY",
         FACILITY_SCOPE, ALL_PRODUCTS, ("beh_input_missing_count",), 1, "count", 4.0,
         _ge("beh_input_missing_count"), "LOW",
         "{value:.0f} behavioural model inputs were missing at this score date.",
         "A score built on missing inputs is weak evidence. Fix the feed before relying on it.",
         "beh_input_missing_count >= 4"),

    Rule("RET-EWS-015", "1.0.0", "Bureau deterioration", "BUREAU",
         CUSTOMER_SCOPE, ALL_PRODUCTS, ("bureau_score_change_3m", "bureau_score_current"), 3,
         "points", 40.0,
         lambda f, th: (
             (_num(f, "bureau_score_change_3m") <= -th),
             _num(f, "bureau_score_change_3m"), _num(f, "bureau_score_current")),
         "MEDIUM",
         "The synthetic bureau proxy score fell {value:.0f} points over three months, to "
         "{comparator:.0f}.",
         "Check whether external delinquency or new external borrowing explains it.",
         "bureau_score_change_3m <= -40"),

    Rule("RET-EWS-016", "1.0.0", "Broken promises to pay", "COLLECTIONS",
         FACILITY_SCOPE, ALL_PRODUCTS, ("broken_promise_count_3m",), 3, "count", 2.0,
         _ge("broken_promise_count_3m"), "HIGH",
         "{value:.0f} promises to pay were not honoured in three months.",
         "Escalate the collections approach; repeated broken promises rarely self-correct.",
         "broken_promise_count_3m >= 2"),

    Rule("RET-EWS-017", "1.0.0", "Repeated direct-debit failure", "COLLECTIONS",
         FACILITY_SCOPE, ALL_PRODUCTS, ("autopay_failure_count_3m",), 3, "count", 2.0,
         _ge("autopay_failure_count_3m"), "MEDIUM",
         "{value:.0f} direct-debit collections failed in three months.",
         "Distinguish a mandate problem from an inability to pay before escalating.",
         "autopay_failure_count_3m >= 2"),

    Rule("RET-EWS-018", "1.0.0", "Forbearance under strain", "FORBEARANCE",
         FACILITY_SCOPE, ALL_PRODUCTS, ("forbearance_flag", "dpd"), 1, "days", 1.0,
         lambda f, th: (
             _flag(f, "forbearance_flag") & (_num(f, "dpd") >= th),
             _num(f, "dpd"), _num(f, "cure_probation_months")),
         "HIGH",
         "A forborne facility is {value:.0f} days past due; the cure conditions are not being met.",
         "Forbearance that is not curing is a Stage 2 or Stage 3 question, not a collections one.",
         "forbearance_flag AND dpd >= 1"),

    Rule("RET-EWS-019", "1.0.0", "Balloon payment approaching", "PRODUCT_STRUCTURE",
         FACILITY_SCOPE, AUTO, ("months_to_balloon", "balance_buffer_months"), 6, "months", 6.0,
         lambda f, th: (
             (_num(f, "months_to_balloon") <= th) & (_num(f, "months_to_balloon") >= 0)
             & (_num(f, "balance_buffer_months") <= 1.0),
             _num(f, "months_to_balloon"), _num(f, "balance_buffer_months")),
         "HIGH",
         "A balloon payment falls due in {value:.0f} months and the customer's buffer covers "
         "{comparator:.2f} months of obligations.",
         "Discuss refinancing or settlement before the balloon date, not after it.",
         "months_to_balloon <= 6 AND balance_buffer_months <= 1.0"),

    Rule("RET-EWS-020", "1.0.0", "Collateral cover deterioration", "COLLATERAL",
         FACILITY_SCOPE, SECURED, ("ltv_current_ratio", "ltv_origination_ratio"), 1, "ratio", 0.08,
         _worsening("ltv_current_ratio", "ltv_origination_ratio", min_now=0.95), "MEDIUM",
         "Current loan to value is {value:.0%} against {comparator:.0%} at origination.",
         "Revalue the security and check the recovery assumption behind this facility's LGD.",
         "ltv_current_ratio - ltv_origination_ratio >= 0.08 AND ltv_current_ratio >= 0.95"),
)

#: Rules that need a portfolio or segment view rather than one row.
SEGMENT_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "RET-EWS-021", "version": "1.0.0",
        "name": "Employer-group salary stress concentration",
        "family": "CONCENTRATION", "scope": SEGMENT_SCOPE,
        "group_by": "employer_id",
        "measure": "share of the group's customers with a missed salary cycle",
        "threshold": 0.20, "min_customers": 25, "severity": "HIGH",
        "recommended_review": (
            "Descriptive concentration only. Employer membership is an attribute of the "
            "borrowers, not a financed company exposure, and this is not evidence that the "
            "employer caused the stress."
        ),
    },
    {
        "rule_id": "RET-EWS-022", "version": "1.0.0",
        "name": "Rising Stage 2 share in a product segment",
        "family": "PORTFOLIO", "scope": SEGMENT_SCOPE,
        "group_by": "product_code",
        "measure": "month-on-month change in the Stage 2 share of facilities",
        "threshold": 0.02, "min_customers": 100, "severity": "MEDIUM",
        "recommended_review": (
            "Look at whether the movement is new entrants, migration of continuing "
            "facilities, or a change in the staging policy version."
        ),
    },
)


def rulebook() -> dict[str, Any]:
    return {
        "rulebook_version": RULEBOOK_VERSION,
        "threshold_source": THRESHOLD_SOURCE,
        "rules": [
            {
                "rule_id": r.rule_id, "version": r.version, "name": r.name, "family": r.family,
                "scope": r.scope, "products": list(r.products), "features": list(r.features),
                "lookback_months": r.lookback_months, "unit": r.unit, "threshold": r.threshold,
                "trigger_expression": r.trigger_expression, "severity": r.severity,
                "recommended_review": r.recommended_review,
                "threshold_source": r.threshold_source,
                "suppression_months": r.suppression_months,
                "retrigger_after_close_months": r.retrigger_after_close_months,
            }
            for r in RULES
        ],
        "segment_rules": [dict(r) for r in SEGMENT_RULES],
        "note": (
            "Recommended actions are reviewed suggestions. Nothing here changes a limit, "
            "contacts a customer or applies an operational restriction."
        ),
    }


#: The only columns an alert row reads off the canonical frame. Named so the
#: evaluator can pull seven narrow arrays instead of walking a five-hundred-column
#: DataFrame row by row: `DataFrame.iterrows` materialises the whole frame as one
#: object array per call, which turned a single snapshot evaluation into minutes.
_ALERT_SOURCE_COLUMNS = (
    "customer_id", "facility_id", "gross_carrying_amount_sar", "record_id",
    "product_code", "employer_id", "region",
)


def _customer_index(frame: pd.DataFrame) -> tuple[dict[Any, list[str]], dict[Any, float]]:
    """Each customer's facilities and their total exposure, computed ONCE.

    Rebuilding this per customer per rule was quadratic: thousands of alerts
    each rescanning a twenty-thousand-row frame.
    """
    unique = frame.drop_duplicates("facility_id")
    facilities = (unique.groupby("customer_id")["facility_id"]
                  .apply(lambda s: sorted(s.astype(str))).to_dict())
    exposure = (unique.groupby("customer_id")["gross_carrying_amount_sar"]
                .sum().round(2).to_dict())
    return facilities, exposure


#: Inputs a rule reads that are NOT columns of the published book.
#:
#: Exactly one, and it is here so that "the rule reads a field the book does
#: not have" stays a failure for every other field. Each entry must be produced
#: by `with_prior_month`, which the acceptance gate checks rather than takes on
#: trust.
DERIVED_FEATURES: frozenset[str] = frozenset({
    "previous_month_debt_burden_ratio",
})


def with_prior_month(frame: "pd.DataFrame",
                     previous: "pd.DataFrame | None") -> "pd.DataFrame":
    """Attach last month's affordability to this month's rows.

    The published book carries a prior-month value for delinquency and for the
    behavioural score, and none for the debt burden. Rather than rebuild
    twenty-five partitions to add one column, the comparator is computed where
    both months are already readable — the evaluation — and the rule reads it
    like any other field.

    A month with nothing before it gets NaN, and the rule does not fire: the
    first published month has no deterioration to measure, and inventing one
    would be the defect this comparator exists to remove.
    """
    out = frame.copy()
    if previous is None or previous.empty or "customer_id" not in previous.columns:
        out["previous_month_debt_burden_ratio"] = np.nan
        return out
    prior = (previous.groupby("customer_id")["debt_burden_ratio"]
             .max().rename("previous_month_debt_burden_ratio"))
    return out.join(prior, on="customer_id")


def evaluate_snapshot(
    frame: pd.DataFrame, *, thresholds: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Every alert this snapshot raises. One row per (rule, scope entity).

    Customer-scope rules are evaluated on the customer's row set and collapsed
    to one alert, with the affected facilities attached and their exposure
    summed once.
    """
    thresholds = thresholds or {}
    if frame.empty:
        return pd.DataFrame(columns=_ALERT_COLUMNS)
    snapshot = frame["snapshot_date"].iloc[0]
    customer_facilities, customer_exposure = _customer_index(frame)
    out: list[dict[str, Any]] = []

    for rule in RULES:
        applicable = frame.loc[rule.applies_to(frame)]
        if applicable.empty:
            continue
        threshold = float(thresholds.get(rule.rule_id, rule.threshold))
        fired, value, comparator = rule.trigger(applicable, threshold)
        if not fired.any():
            continue

        hits = applicable.loc[fired]
        source = {
            c: (hits[c].to_numpy() if c in hits.columns
                else np.full(len(hits), None, dtype=object))
            for c in _ALERT_SOURCE_COLUMNS
        }
        values = value[fired]
        comparators = comparator[fired]

        if rule.scope == FACILITY_SCOPE:
            for i in range(len(hits)):
                facility_id = str(source["facility_id"][i])
                out.append(_alert_row(
                    rule, source, i, snapshot, float(values[i]), float(comparators[i]),
                    threshold, [facility_id],
                    float(source["gross_carrying_amount_sar"][i])))
        else:
            # One alert per customer, carrying the worst measurement they show
            # and every facility they hold.
            best: dict[Any, int] = {}
            for i in range(len(hits)):
                key = source["customer_id"][i]
                current = best.get(key)
                if current is None or abs(values[i]) > abs(values[current]):
                    best[key] = i
            for key, i in best.items():
                facilities = customer_facilities.get(key, [])
                out.append(_alert_row(
                    rule, source, i, snapshot, float(values[i]), float(comparators[i]),
                    threshold, facilities, float(customer_exposure.get(key, 0.0))))

    if not out:
        return pd.DataFrame(columns=_ALERT_COLUMNS)
    return pd.DataFrame(out)[_ALERT_COLUMNS]


_ALERT_COLUMNS = [
    "alert_id", "rule_id", "rule_version", "rulebook_version", "rule_name", "rule_family",
    "scope", "customer_id", "facility_id", "affected_facility_ids", "affected_facility_count",
    "snapshot_date", "first_seen_date", "last_seen_date", "current_status", "severity",
    "trigger_value", "threshold", "threshold_source", "prior_comparator", "unit",
    "evidence_record_refs", "evidence_columns", "affected_exposure_sar", "reason",
    "recommended_review", "product_code", "employer_id", "region", "is_synthetic",
]


def _alert_row(
    rule: Rule, source: dict[str, Any], i: int, snapshot: Any, value: float,
    comparator: float, threshold: float, facilities: list[str], exposure: float,
) -> dict[str, Any]:
    customer_id = str(source["customer_id"][i])
    raw_facility = source["facility_id"][i]
    facility_id = None if raw_facility is None else str(raw_facility)
    scope_id = customer_id if rule.scope == CUSTOMER_SCOPE else facility_id
    try:
        reason = rule.reason_template.format(value=value, comparator=comparator)
    except (ValueError, KeyError):
        reason = rule.reason_template
    return {
        "alert_id": f"{rule.rule_id}|{scope_id}",
        "rule_id": rule.rule_id,
        "rule_version": rule.version,
        "rulebook_version": RULEBOOK_VERSION,
        "rule_name": rule.name,
        "rule_family": rule.family,
        "scope": rule.scope,
        "customer_id": customer_id,
        "facility_id": None if rule.scope == CUSTOMER_SCOPE else facility_id,
        "affected_facility_ids": ",".join(facilities),
        "affected_facility_count": len(facilities),
        "snapshot_date": snapshot,
        "first_seen_date": snapshot,
        "last_seen_date": snapshot,
        "current_status": STATUS_OPEN,
        "severity": rule.severity,
        "trigger_value": value,
        "threshold": threshold,
        "threshold_source": rule.threshold_source,
        "prior_comparator": None if np.isnan(comparator) else comparator,
        "unit": rule.unit,
        "evidence_record_refs": str(source["record_id"][i] or ""),
        "evidence_columns": ",".join(rule.features),
        "affected_exposure_sar": round(exposure, 2),
        "reason": reason,
        "recommended_review": rule.recommended_review,
        "product_code": None if rule.scope == CUSTOMER_SCOPE else source["product_code"][i],
        "employer_id": source["employer_id"][i],
        "region": source["region"][i],
        "is_synthetic": True,
    }


def reconcile(previous: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Carry an alert book forward one month.

    Running this twice on the same snapshot is a no-op: alert identity is
    (rule, scope entity), so a repeated evaluation updates rather than
    duplicates.
    """
    if previous is None or previous.empty:
        return current.copy()
    if current.empty:
        closed = previous.copy()
        closed["current_status"] = STATUS_CLOSED
        return closed

    prev = {r["alert_id"]: r for r in previous.to_dict("records")}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in current.to_dict("records"):
        alert_id = row["alert_id"]
        seen.add(alert_id)
        before = prev.get(alert_id)
        if before is not None:
            was_closed = before["current_status"] == STATUS_CLOSED
            row["first_seen_date"] = (
                row["snapshot_date"] if was_closed else before["first_seen_date"])
            row["current_status"] = STATUS_RETRIGGERED if was_closed else STATUS_UPDATED
        merged.append(row)

    for alert_id, before in prev.items():
        if alert_id not in seen and before["current_status"] != STATUS_CLOSED:
            closed = dict(before)
            closed["current_status"] = STATUS_CLOSED
            merged.append(closed)

    return pd.DataFrame(merged)[_ALERT_COLUMNS]


def affected_exposure(alerts: pd.DataFrame) -> float:
    """Total exposure under alert, counting each facility exactly once.

    Two rules firing on the same facility, or a customer alert and a facility
    alert covering the same account, must not add that exposure twice.
    """
    if alerts.empty:
        return 0.0
    seen: dict[str, float] = {}
    statuses = alerts["current_status"].to_numpy()
    id_lists = alerts["affected_facility_ids"].astype(str).to_numpy()
    exposures = alerts["affected_exposure_sar"].to_numpy(dtype="float64")
    for status, raw, exposure in zip(statuses, id_lists, exposures):
        if status == STATUS_CLOSED:
            continue
        ids = [f for f in raw.split(",") if f]
        if not ids:
            continue
        share = exposure / len(ids)
        for f in ids:
            seen[f] = max(seen.get(f, 0.0), share)
    return round(sum(seen.values()), 2)
