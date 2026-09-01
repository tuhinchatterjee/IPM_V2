"""
The retail scorecard variable dictionary. §8, §9, §10.

Every candidate variable the two scorecards can see, what it means, how it
is stored, and whether the score is allowed to use it.

Three distinctions this file exists to keep straight
-----------------------------------------------------
**Candidate is not active.** §11: a dataset carries 24+ raw candidates; an
active scorecard normally uses five or six of them. Confusing the two makes
"which variables are in the model" unanswerable, and makes a drift report on
29 variables look like a report on the model. `ACTIVE` never lives here — it
lives in the model registry, per version.

**Raw is not WoE.** §10: a variable is stored twice, as the value the bank
observed and as the weight-of-evidence the approved binning maps it to.
Scoring uses the WoE; a drift report on the raw distribution and a drift
report on the bin populations answer different questions.

**Sensitive is not scoreable.** §8: demographic fields may be present so
fairness monitoring has something to monitor, and are tagged
`scoreable=False` so no equation can reference them. The tag is enforced in
`equation.py`, not just documented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VARIABLES_VERSION = "1.0.0"

#: How a variable is stored and binned.
NUMERIC = "NUMERIC"
CATEGORICAL = "CATEGORICAL"
FLAG = "FLAG"
KINDS: tuple[str, ...] = (NUMERIC, CATEGORICAL, FLAG)


@dataclass(frozen=True)
class Variable:
    """One candidate predictor."""

    name: str
    label: str
    kind: str
    definition: str
    #: Direction credit sense expects: HIGHER_IS_RISKIER or LOWER_IS_RISKIER.
    #: Used by the sign check in §16 — a fitted coefficient that disagrees
    #: with this is a finding, not a rounding difference.
    risk_direction: str = "HIGHER_IS_RISKIER"
    unit: str = ""
    #: False for demographic fields kept for fairness monitoring only.
    scoreable: bool = True
    #: False for identifiers, dates and outcome fields.
    profileable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _v(name: str, label: str, kind: str, definition: str,
       direction: str = "HIGHER_IS_RISKIER", unit: str = "",
       scoreable: bool = True) -> Variable:
    return Variable(name=name, label=label, kind=kind, definition=definition,
                    risk_direction=direction, unit=unit, scoreable=scoreable)


LOWER = "LOWER_IS_RISKIER"
HIGHER = "HIGHER_IS_RISKIER"


# ------------------------------------------------- §8 application candidates

APPLICATION: tuple[Variable, ...] = (
    _v("applicant_age", "Applicant age", NUMERIC,
       "Age in whole years at application.", LOWER, "years", scoreable=False),
    _v("monthly_income", "Monthly income", NUMERIC,
       "Declared and verified gross monthly income.", LOWER, "AED"),
    _v("employment_tenure_months", "Employment tenure", NUMERIC,
       "Months with the current employer at application.", LOWER, "months"),
    _v("employer_type", "Employer type", CATEGORICAL,
       "Government, semi-government, large corporate, SME or self-employed."),
    _v("employment_sector", "Employment sector", CATEGORICAL,
       "Sector of the applicant's employer."),
    _v("residency_tenure_months", "Residency tenure", NUMERIC,
       "Months resident in the country at application.", LOWER, "months"),
    _v("marital_status", "Marital status", CATEGORICAL,
       "Marital status as declared.", HIGHER, "", scoreable=False),
    _v("number_of_dependants", "Dependants", NUMERIC,
       "Number of financial dependants declared.", HIGHER, "count"),
    _v("housing_status", "Housing status", CATEGORICAL,
       "Owned, mortgaged, rented or company-provided."),
    _v("monthly_rent", "Monthly rent", NUMERIC,
       "Declared monthly housing cost.", HIGHER, "AED"),
    _v("existing_total_monthly_obligations", "Existing obligations", NUMERIC,
       "Total monthly repayment on existing credit.", HIGHER, "AED"),
    _v("debt_burden_ratio", "Debt burden ratio", NUMERIC,
       "Total monthly obligations divided by monthly income.", HIGHER, "ratio"),
    _v("requested_amount", "Requested amount", NUMERIC,
       "Facility amount requested.", HIGHER, "AED"),
    _v("requested_tenor_months", "Requested tenor", NUMERIC,
       "Requested repayment term.", HIGHER, "months"),
    _v("down_payment_pct", "Down payment", NUMERIC,
       "Applicant's own contribution as a share of the amount.", LOWER, "pct"),
    _v("loan_to_income", "Loan to income", NUMERIC,
       "Requested amount divided by annualised income.", HIGHER, "ratio"),
    _v("bureau_score", "Bureau score", NUMERIC,
       "Credit bureau score at application.", LOWER, "score"),
    _v("bureau_total_outstanding", "Bureau outstanding", NUMERIC,
       "Total outstanding balance reported by the bureau.", HIGHER, "AED"),
    _v("bureau_active_accounts", "Bureau active accounts", NUMERIC,
       "Count of active credit accounts at the bureau.", HIGHER, "count"),
    _v("bureau_delinquent_accounts_12m", "Bureau delinquencies 12m", NUMERIC,
       "Accounts that went delinquent in the last twelve months.",
       HIGHER, "count"),
    _v("bureau_max_dpd_12m", "Bureau max DPD 12m", NUMERIC,
       "Worst days past due observed at the bureau in twelve months.",
       HIGHER, "days"),
    _v("bureau_enquiries_6m", "Bureau enquiries 6m", NUMERIC,
       "Credit enquiries recorded in the last six months.", HIGHER, "count"),
    _v("bureau_oldest_trade_months", "Bureau file age", NUMERIC,
       "Age of the oldest trade line on the bureau file.", LOWER, "months"),
    _v("credit_card_utilisation", "Card utilisation", NUMERIC,
       "Balance over limit across the applicant's cards.", HIGHER, "pct"),
    _v("existing_bank_relationship_months", "Relationship tenure", NUMERIC,
       "Months the applicant has banked with the institution.",
       LOWER, "months"),
    _v("salary_transfer_flag", "Salary transfer", FLAG,
       "Whether salary is credited to the institution.", LOWER),
    _v("application_channel", "Application channel", CATEGORICAL,
       "Branch, digital, broker, telesales or partner."),
    _v("product_type", "Product type", CATEGORICAL,
       "Personal loan, auto loan, credit card or mortgage."),
    _v("customer_segment", "Customer segment", CATEGORICAL,
       "Mass, affluent, priority or private."),
)


# ------------------------------------------------- §9 behavioral candidates

BEHAVIORAL: tuple[Variable, ...] = (
    _v("months_on_book", "Months on book", NUMERIC,
       "Months since the account was opened.", LOWER, "months"),
    _v("current_balance", "Current balance", NUMERIC,
       "Outstanding balance at the snapshot date.", HIGHER, "AED"),
    _v("credit_limit", "Credit limit", NUMERIC,
       "Approved limit at the snapshot date.", LOWER, "AED"),
    _v("available_limit", "Available limit", NUMERIC,
       "Limit less balance at the snapshot date.", LOWER, "AED"),
    _v("utilisation_pct", "Utilisation", NUMERIC,
       "Balance as a share of limit.", HIGHER, "pct"),
    _v("average_utilisation_3m", "Average utilisation 3m", NUMERIC,
       "Mean utilisation over the last three snapshots.", HIGHER, "pct"),
    _v("average_utilisation_6m", "Average utilisation 6m", NUMERIC,
       "Mean utilisation over the last six snapshots.", HIGHER, "pct"),
    _v("max_utilisation_6m", "Peak utilisation 6m", NUMERIC,
       "Highest utilisation over the last six snapshots.", HIGHER, "pct"),
    _v("current_dpd", "Current DPD", NUMERIC,
       "Days past due at the snapshot date.", HIGHER, "days"),
    _v("max_dpd_3m", "Max DPD 3m", NUMERIC,
       "Worst days past due in the last three months.", HIGHER, "days"),
    _v("max_dpd_6m", "Max DPD 6m", NUMERIC,
       "Worst days past due in the last six months.", HIGHER, "days"),
    _v("times_dpd_30plus_6m", "Times 30+ DPD 6m", NUMERIC,
       "Count of months at 30 or more days past due in six months.",
       HIGHER, "count"),
    _v("times_dpd_60plus_12m", "Times 60+ DPD 12m", NUMERIC,
       "Count of months at 60 or more days past due in twelve months.",
       HIGHER, "count"),
    _v("payment_ratio_latest", "Payment ratio", NUMERIC,
       "Amount paid over amount due in the latest cycle.", LOWER, "ratio"),
    _v("average_payment_ratio_3m", "Average payment ratio 3m", NUMERIC,
       "Mean payment ratio over three cycles.", LOWER, "ratio"),
    _v("minimum_payment_ratio_6m", "Minimum payment ratio 6m", NUMERIC,
       "Lowest payment ratio over six cycles.", LOWER, "ratio"),
    _v("cash_advance_ratio_3m", "Cash advance ratio 3m", NUMERIC,
       "Cash advances as a share of spend over three months.",
       HIGHER, "ratio"),
    _v("transaction_count_3m", "Transaction count 3m", NUMERIC,
       "Number of transactions over three months.", LOWER, "count"),
    _v("transaction_amount_3m", "Transaction value 3m", NUMERIC,
       "Total transaction value over three months.", LOWER, "AED"),
    _v("salary_credit_stability", "Salary credit stability", NUMERIC,
       "Share of the last six months with an expected salary credit.",
       LOWER, "ratio"),
    _v("inflow_outflow_ratio", "Inflow to outflow", NUMERIC,
       "Credits over debits across the customer's accounts.", LOWER, "ratio"),
    _v("balance_growth_3m", "Balance growth 3m", NUMERIC,
       "Change in balance over three months.", HIGHER, "pct"),
    _v("missed_payment_count_6m", "Missed payments 6m", NUMERIC,
       "Cycles with no qualifying payment in six months.", HIGHER, "count"),
    _v("overlimit_count_6m", "Over-limit events 6m", NUMERIC,
       "Cycles ending above the limit in six months.", HIGHER, "count"),
    _v("bureau_score_latest", "Bureau score", NUMERIC,
       "Latest credit bureau score.", LOWER, "score"),
    _v("bureau_score_change_6m", "Bureau score change 6m", NUMERIC,
       "Change in bureau score over six months.", LOWER, "points"),
    _v("bureau_enquiries_6m", "Bureau enquiries 6m", NUMERIC,
       "Credit enquiries recorded in six months.", HIGHER, "count"),
    _v("external_delinquency_flag", "External delinquency", FLAG,
       "Delinquent at another institution per the bureau.", HIGHER),
    _v("restructure_flag", "Restructured", FLAG,
       "Account has been restructured.", HIGHER),
    _v("collections_contact_count_3m", "Collections contacts 3m", NUMERIC,
       "Collections contact attempts over three months.", HIGHER, "count"),
    _v("promise_to_pay_broken_count_6m", "Broken promises 6m", NUMERIC,
       "Promises to pay not honoured over six months.", HIGHER, "count"),
    _v("product", "Product", CATEGORICAL,
       "Credit card, overdraft, personal loan or auto loan."),
    _v("vintage", "Vintage", CATEGORICAL,
       "Origination year cohort the account belongs to."),
)


APPLICATION_SCORECARD = "APPLICATION"
BEHAVIORAL_SCORECARD = "BEHAVIORAL"
SCORECARD_TYPES: tuple[str, ...] = (APPLICATION_SCORECARD, BEHAVIORAL_SCORECARD)

_BY_TYPE: dict[str, tuple[Variable, ...]] = {
    APPLICATION_SCORECARD: APPLICATION,
    BEHAVIORAL_SCORECARD: BEHAVIORAL,
}


class VariableError(KeyError):
    """A variable that does not exist in the dictionary."""


def catalogue(scorecard_type: str) -> tuple[Variable, ...]:
    if scorecard_type not in _BY_TYPE:
        raise VariableError(
            f"{scorecard_type!r} is not a scorecard type; "
            f"expected one of {', '.join(SCORECARD_TYPES)}")
    return _BY_TYPE[scorecard_type]


def get(scorecard_type: str, name: str) -> Variable:
    for variable in catalogue(scorecard_type):
        if variable.name == name:
            return variable
    raise VariableError(
        f"{name!r} is not a candidate variable of the {scorecard_type} "
        "scorecard. A model may not reference a variable the dictionary "
        "does not define — that is how a hidden predictor gets in.")


def names(scorecard_type: str, *, scoreable_only: bool = False) -> list[str]:
    return [v.name for v in catalogue(scorecard_type)
            if not scoreable_only or v.scoreable]


def scoreable(scorecard_type: str) -> set[str]:
    return {v.name for v in catalogue(scorecard_type) if v.scoreable}


def sensitive(scorecard_type: str) -> list[str]:
    """Fields kept for fairness monitoring and excluded from any score."""
    return [v.name for v in catalogue(scorecard_type) if not v.scoreable]


def woe_name(name: str) -> str:
    """§10's convention: monthly_income -> monthly_income_woe."""
    return f"{name}_woe"


def summary() -> dict[str, Any]:
    return {
        "variables_version": VARIABLES_VERSION,
        "counts": {t: len(catalogue(t)) for t in SCORECARD_TYPES},
        "scoreable": {t: len(scoreable(t)) for t in SCORECARD_TYPES},
        "sensitive_excluded_from_scoring": {
            t: sensitive(t) for t in SCORECARD_TYPES},
        "candidate_is_not_active": (
            "These are the candidate predictors the datasets carry. Which "
            "five or six an equation actually uses is the model registry's "
            "answer, per version, not this dictionary's."),
    }
