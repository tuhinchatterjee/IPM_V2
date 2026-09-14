"""
What each book contains. One registry, two domains, no shared assumptions.

Why this exists rather than reusing V3's
----------------------------------------
V3's catalogue is a module of constants: `QUERYABLE_RELATIONS` and a field
registry hard-bound to the corporate book, reached through static methods. It
is correct for what it is and V4 used it unchanged for a corporate-only
runtime. It cannot describe a second book, and teaching it to would mean
editing V3 -- which is not on the table and would not be right anyway: a
retail account is not a corporate facility with different words on it.

So the schema is DATA here. A relation is a name, a grain, a period column
and a list of fields; a field is a name, a type, a unit and a sentence saying
what it means. Both books are described the same way and neither can see the
other's entries, because `RELATIONS` is keyed by domain and every lookup
takes the domain as its first argument.

Units are the display policy's vocabulary
-----------------------------------------
`unit` is not decoration. `display.classify` reads it to decide that an
amount shows no decimals and a probability shows two, so `rcy` and
`probability_0_1` here are the same words that module already understands.
A field whose unit is spelled inventively is a field whose figures get
published wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4 import domains as dom


class UnknownRelation(LookupError):
    """A relation this domain does not have. Named with what it does have."""


class UnknownField(LookupError):
    """A column this relation does not define."""


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str
    unit: str
    description: str
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.dtype, "unit": self.unit,
                "description": self.description, "group": self.group}


@dataclass(frozen=True)
class Relation:
    name: str
    grain: str
    period_column: str
    key_columns: tuple[str, ...]
    description: str
    fields: tuple[Field, ...]

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def field(self, column: str) -> Field:
        wanted = str(column or "").strip()
        for spec in self.fields:
            if spec.name == wanted:
                return spec
        raise UnknownField(
            f"Column {column!r} is not defined in {self.name}. It holds: "
            f"{', '.join(self.columns)}.")

    def to_dict(self) -> dict[str, Any]:
        return {"relation": self.name, "grain": self.grain,
                "period_column": self.period_column,
                "key_columns": list(self.key_columns),
                "description": self.description,
                "fields": [f.to_dict() for f in self.fields]}


def _f(name, dtype, unit, description, group=""):
    return Field(name, dtype, unit, description, group)


#: Columns every relation in every domain carries. They are the isolation:
#: the session filters on them when it materializes the table, so a query
#: cannot reach another tenant, release or domain by forgetting a WHERE.
GOVERNANCE_FIELDS: tuple[Field, ...] = (
    _f("tenant_id", "string", "", "The tenant this row belongs to.",
       "Governance"),
    _f("dataset_release_id", "string", "",
       "The immutable release this row was published in.", "Governance"),
    _f("domain_id", "string", "",
       "The analytical domain this row belongs to.", "Governance"),
    _f("reporting_currency", "string", "",
       "The currency every amount in this row is denominated in.",
       "Governance"),
)

# ---- corporate ---------------------------------------------------------

_CORP_BORROWER = Relation(
    name="corp_borrower_month",
    grain="one row per borrower per reporting month",
    period_column="reporting_month",
    key_columns=("borrower_id", "reporting_month"),
    description=("The obligor as at a month end: who it is, how it is "
                 "segmented, how it is rated and what its financials say."),
    fields=GOVERNANCE_FIELDS + (
        _f("borrower_id", "string", "", "Stable obligor identifier.",
           "Identity"),
        _f("borrower_name", "string", "", "Fictional obligor name.",
           "Identity"),
        _f("group_id", "string", "", "Parent group identifier.", "Identity"),
        _f("group_name", "string", "", "Fictional parent group name.",
           "Identity"),
        _f("reporting_month", "string", "",
           "Reporting month as YYYY-MM.", "Period"),
        _f("sector", "string", "", "Economic sector.", "Segmentation"),
        _f("sub_sector", "string", "", "Sector sub-classification.",
           "Segmentation"),
        _f("region", "string", "", "Saudi region of the primary operation.",
           "Segmentation"),
        _f("relationship_tier", "string", "",
           "Relationship management tier.", "Segmentation"),
        _f("rating_current", "string", "",
           "Internal rating this month, on the 19-grade scale.", "Rating"),
        _f("rating_previous", "string", "",
           "Internal rating the previous month.", "Rating"),
        _f("rating_notches_moved", "integer", "notches",
           "Notches moved since last month. Negative is a downgrade.",
           "Rating"),
        _f("rating_outlook", "string", "",
           "Positive, Stable or Negative.", "Rating"),
        _f("pd_ttc_12m", "float", "probability_0_1",
           "Through-the-cycle 12-month probability of default.", "Rating"),
        _f("revenue_sar_mn", "float", "rcy", "Trailing twelve-month revenue.",
           "Financials"),
        _f("ebitda_sar_mn", "float", "rcy",
           "Trailing twelve-month EBITDA.", "Financials"),
        _f("total_debt_sar_mn", "float", "rcy", "Total debt outstanding.",
           "Financials"),
        _f("cash_sar_mn", "float", "rcy", "Cash and equivalents.",
           "Financials"),
        _f("net_debt_sar_mn", "float", "rcy", "Total debt less cash.",
           "Financials"),
        _f("leverage_x", "float", "times", "Net debt to EBITDA.", "Ratios"),
        _f("dscr_x", "float", "times", "Debt service coverage ratio.",
           "Ratios"),
        _f("interest_cover_x", "float", "times",
           "EBITDA to interest expense.", "Ratios"),
        _f("current_ratio_x", "float", "times",
           "Current assets to current liabilities.", "Ratios"),
        _f("ebitda_margin_pct", "float", "percent",
           "EBITDA as a percentage of revenue.", "Ratios"),
        _f("qualitative_score", "float", "index",
           "Analyst qualitative assessment, 0 (weak) to 100 (strong).",
           "Qualitative"),
    ))

_CORP_FACILITY = Relation(
    name="corp_facility_month",
    grain="one row per facility per reporting month",
    period_column="reporting_month",
    key_columns=("facility_id", "reporting_month"),
    description=("The exposure as at a month end: limits, drawings, IFRS 9 "
                 "stage, PD, LGD, EAD and ECL."),
    fields=GOVERNANCE_FIELDS + (
        _f("facility_id", "string", "", "Stable facility identifier.",
           "Identity"),
        _f("borrower_id", "string", "", "The obligor this facility is to.",
           "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("facility_type", "string", "",
           "Term Loan, Revolving Credit, Trade Finance, Project Finance or "
           "Working Capital.", "Segmentation"),
        _f("sector", "string", "", "The obligor's sector, carried for "
           "single-relation sector analysis.", "Segmentation"),
        _f("region", "string", "", "The obligor's region.", "Segmentation"),
        _f("limit_sar_mn", "float", "rcy", "Sanctioned limit.", "Exposure"),
        _f("drawn_sar_mn", "float", "rcy", "Drawn balance.", "Exposure"),
        _f("undrawn_sar_mn", "float", "rcy", "Undrawn commitment.",
           "Exposure"),
        _f("utilisation_pct", "float", "percent",
           "Drawn as a percentage of limit.", "Exposure"),
        _f("ead_sar_mn", "float", "rcy",
           "Exposure at default: drawn plus the credit-converted undrawn.",
           "Exposure"),
        _f("stage", "integer", "count", "IFRS 9 stage: 1, 2 or 3.", "IFRS 9"),
        _f("sicr_flag", "integer", "count",
           "1 when a significant increase in credit risk is recognised.",
           "IFRS 9"),
        _f("default_flag", "integer", "count",
           "1 when the facility is in default.", "IFRS 9"),
        _f("dpd_days", "integer", "days", "Days past due.", "IFRS 9"),
        _f("pd_pit_12m", "float", "probability_0_1",
           "Point-in-time 12-month probability of default.", "IFRS 9"),
        _f("pd_lifetime", "float", "probability_0_1",
           "Lifetime probability of default.", "IFRS 9"),
        _f("lgd_pct", "float", "percent", "Loss given default.", "IFRS 9"),
        _f("ecl_12m_sar_mn", "float", "rcy", "Twelve-month expected credit "
           "loss.", "IFRS 9"),
        _f("ecl_lifetime_sar_mn", "float", "rcy",
           "Lifetime expected credit loss.", "IFRS 9"),
        _f("ecl_sar_mn", "float", "rcy",
           "Recognised ECL: the 12-month figure in Stage 1 and the lifetime "
           "figure in Stages 2 and 3.", "IFRS 9"),
        _f("past_due_flag", "integer", "count",
           "1 when any amount is past due.", "IFRS 9"),
        _f("months_in_stage", "integer", "months",
           "Consecutive months at the current stage.", "IFRS 9"),
    ))

_CORP_COLLATERAL = Relation(
    name="corp_collateral_month",
    grain="one row per collateral item per facility per reporting month",
    period_column="reporting_month",
    key_columns=("collateral_id", "reporting_month"),
    description="Security held against a facility, and what it is worth.",
    fields=GOVERNANCE_FIELDS + (
        _f("collateral_id", "string", "", "Stable collateral identifier.",
           "Identity"),
        _f("facility_id", "string", "", "The facility this secures.",
           "Identity"),
        _f("borrower_id", "string", "", "The obligor.", "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("collateral_type", "string", "",
           "Real Estate, Plant and Equipment, Receivables, Cash Deposit or "
           "Corporate Guarantee.", "Collateral"),
        _f("market_value_sar_mn", "float", "rcy", "Appraised market value.",
           "Collateral"),
        _f("haircut_pct", "float", "percent",
           "Regulatory haircut applied to the market value.", "Collateral"),
        _f("allocated_value_sar_mn", "float", "rcy",
           "Market value after haircut, allocated to this facility.",
           "Collateral"),
        _f("coverage_pct", "float", "percent",
           "Allocated value as a percentage of the facility's EAD.",
           "Collateral"),
        _f("ltv_pct", "float", "percent",
           "EAD as a percentage of market value.", "Collateral"),
        _f("valuation_age_months", "integer", "months",
           "Months since the last appraisal.", "Collateral"),
    ))

_CORP_COVENANT = Relation(
    name="corp_covenant_month",
    grain="one row per covenant test per facility per reporting month",
    period_column="reporting_month",
    key_columns=("covenant_id", "reporting_month"),
    description="Covenant tests, their thresholds and what was observed.",
    fields=GOVERNANCE_FIELDS + (
        _f("covenant_id", "string", "", "Stable covenant identifier.",
           "Identity"),
        _f("facility_id", "string", "", "The facility this tests.",
           "Identity"),
        _f("borrower_id", "string", "", "The obligor.", "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("covenant_type", "string", "",
           "Leverage, DSCR, Interest Cover, Current Ratio or Minimum "
           "EBITDA.", "Covenants"),
        _f("threshold_value", "float", "times",
           "The level the covenant requires.", "Covenants"),
        _f("observed_value", "float", "times",
           "The level actually observed this month.", "Covenants"),
        _f("headroom_pct", "float", "percent",
           "Headroom against the threshold. Negative is a breach.",
           "Covenants"),
        _f("test_status", "string", "", "PASS, WATCH or BREACH.",
           "Covenants"),
        _f("breach_flag", "integer", "count", "1 when the test is breached.",
           "Covenants"),
        _f("waiver_flag", "integer", "count",
           "1 when a waiver has been granted for this breach.", "Covenants"),
        _f("waiver_month", "string", "",
           "The month the waiver was granted, empty when there is none.",
           "Covenants"),
    ))

# ---- retail ------------------------------------------------------------

_RETAIL_CUSTOMER = Relation(
    name="retail_customer_month",
    grain="one row per retail customer per reporting month",
    period_column="reporting_month",
    key_columns=("customer_id", "reporting_month"),
    description=("The retail customer as at a month end: segment, tenure, "
                 "behaviour score and their worst account position."),
    fields=GOVERNANCE_FIELDS + (
        _f("customer_id", "string", "", "Stable customer identifier.",
           "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("customer_segment", "string", "",
           "Mass, Affluent, Private or Payroll.", "Segmentation"),
        _f("region", "string", "", "Saudi region of residence.",
           "Segmentation"),
        _f("tenure_months", "integer", "months",
           "Months since the relationship opened.", "Segmentation"),
        _f("accounts_held", "integer", "count",
           "Number of open accounts this month.", "Segmentation"),
        _f("behaviour_score", "float", "index",
           "Behavioural score this month, 300 (weak) to 900 (strong).",
           "Behaviour score"),
        _f("behaviour_score_previous", "float", "index",
           "Behavioural score the previous month.", "Behaviour score"),
        _f("behaviour_score_change", "float", "index",
           "Change since last month. Negative is deterioration.",
           "Behaviour score"),
        _f("score_band", "string", "",
           "Band of the current score: A (best) to E (worst).",
           "Behaviour score"),
        _f("score_band_previous", "string", "",
           "Band of the previous month's score.", "Behaviour score"),
        _f("score_migration", "string", "",
           "IMPROVED, STABLE or DETERIORATED.", "Behaviour score"),
        _f("total_ead_sar_mn", "float", "rcy",
           "Exposure at default across the customer's accounts.",
           "Exposure"),
        _f("total_ecl_sar_mn", "float", "rcy",
           "Recognised ECL across the customer's accounts.", "IFRS 9"),
        _f("worst_stage", "integer", "count",
           "The worst IFRS 9 stage across the customer's accounts.",
           "IFRS 9"),
        _f("worst_dpd_days", "integer", "days",
           "The worst days past due across the customer's accounts.",
           "Delinquency"),
    ))

_RETAIL_ACCOUNT = Relation(
    name="retail_account_month",
    grain="one row per retail account per reporting month",
    period_column="reporting_month",
    key_columns=("account_id", "reporting_month"),
    description=("The retail account as at a month end: product, balances, "
                 "IFRS 9 position and delinquency."),
    fields=GOVERNANCE_FIELDS + (
        _f("account_id", "string", "", "Stable account identifier.",
           "Identity"),
        _f("customer_id", "string", "", "The customer who holds it.",
           "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("product", "string", "",
           "Mortgage, Personal Finance, Auto Finance or Credit Card.",
           "Product"),
        _f("secured_flag", "integer", "count",
           "1 when the product is secured.", "Product"),
        _f("origination_month", "string", "",
           "The month the account was opened, as YYYY-MM.", "Vintage"),
        _f("vintage_year", "integer", "count",
           "The calendar year of origination.", "Vintage"),
        _f("months_on_book", "integer", "months",
           "Months since origination.", "Vintage"),
        _f("customer_segment", "string", "", "The customer's segment.",
           "Segmentation"),
        _f("region", "string", "", "The customer's region.", "Segmentation"),
        _f("limit_sar_mn", "float", "rcy",
           "Sanctioned limit or original advance.", "Exposure"),
        _f("balance_sar_mn", "float", "rcy", "Outstanding balance.",
           "Exposure"),
        _f("ead_sar_mn", "float", "rcy", "Exposure at default.", "Exposure"),
        _f("utilisation_pct", "float", "percent",
           "Balance as a percentage of limit.", "Exposure"),
        _f("stage", "integer", "count", "IFRS 9 stage: 1, 2 or 3.", "IFRS 9"),
        _f("sicr_flag", "integer", "count",
           "1 when a significant increase in credit risk is recognised.",
           "IFRS 9"),
        _f("default_flag", "integer", "count",
           "1 when the account is in default.", "IFRS 9"),
        _f("dpd_days", "integer", "days", "Days past due.", "Delinquency"),
        _f("delinquency_bucket", "string", "",
           "Current, 1-29, 30-59, 60-89 or 90+ days past due.",
           "Delinquency"),
        _f("pd_pit_12m", "float", "probability_0_1",
           "Point-in-time 12-month probability of default.", "IFRS 9"),
        _f("pd_lifetime", "float", "probability_0_1",
           "Lifetime probability of default.", "IFRS 9"),
        _f("lgd_pct", "float", "percent", "Loss given default.", "IFRS 9"),
        _f("ecl_12m_sar_mn", "float", "rcy",
           "Twelve-month expected credit loss.", "IFRS 9"),
        _f("ecl_lifetime_sar_mn", "float", "rcy",
           "Lifetime expected credit loss.", "IFRS 9"),
        _f("ecl_sar_mn", "float", "rcy",
           "Recognised ECL: the 12-month figure in Stage 1 and the lifetime "
           "figure in Stages 2 and 3.", "IFRS 9"),
        _f("write_off_sar_mn", "float", "rcy",
           "Amount written off this month.", "IFRS 9"),
        _f("recovery_sar_mn", "float", "rcy",
           "Amount recovered this month.", "IFRS 9"),
        _f("cure_flag", "integer", "count",
           "1 when the account cured from delinquency this month.",
           "Delinquency"),
        _f("behaviour_score", "float", "index",
           "The customer's behavioural score, carried for single-relation "
           "score analysis.", "Behaviour score"),
        _f("score_band", "string", "", "The customer's score band.",
           "Behaviour score"),
    ))

_RETAIL_BEHAVIOUR = Relation(
    name="retail_behaviour_month",
    grain="one row per retail account per reporting month",
    period_column="reporting_month",
    key_columns=("account_id", "reporting_month"),
    description=("The behavioural variables the score is built from: how the "
                 "account is actually being used and repaid."),
    fields=GOVERNANCE_FIELDS + (
        _f("account_id", "string", "", "The account.", "Identity"),
        _f("customer_id", "string", "", "The customer.", "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("product", "string", "", "The account's product.", "Product"),
        _f("utilisation_pct", "float", "percent",
           "Balance as a percentage of limit.", "Behaviour variables"),
        _f("utilisation_change_pp", "float", "percentage points",
           "Change in utilisation since last month.",
           "Behaviour variables"),
        _f("payment_ratio_pct", "float", "percent",
           "Amount paid this month as a percentage of the amount due.",
           "Behaviour variables"),
        _f("missed_payments_12m", "integer", "count",
           "Payments missed in the last twelve months.",
           "Behaviour variables"),
        _f("delinquency_streak_months", "integer", "months",
           "Consecutive months past due.", "Behaviour variables"),
        _f("balance_growth_pct", "float", "percent",
           "Change in balance since last month.", "Behaviour variables"),
        _f("cash_advance_ratio_pct", "float", "percent",
           "Cash advances as a percentage of spend. Cards only; zero "
           "elsewhere.", "Behaviour variables"),
        _f("overlimit_flag", "integer", "count",
           "1 when the balance exceeded the limit this month.",
           "Behaviour variables"),
        _f("inflow_change_pct", "float", "percent",
           "Change in credited salary or other inflow since last month.",
           "Behaviour variables"),
        _f("bureau_inquiries_6m", "integer", "count",
           "Credit bureau inquiries in the last six months.",
           "Behaviour variables"),
        _f("repayment_behaviour_score", "float", "index",
           "Repayment component of the behavioural score, 0 to 100.",
           "Behaviour variables"),
    ))

_RETAIL_COLLATERAL = Relation(
    name="retail_collateral_month",
    grain="one row per secured retail account per reporting month",
    period_column="reporting_month",
    key_columns=("account_id", "reporting_month"),
    description=("Security on secured retail lending. Unsecured products do "
                 "not appear here at all rather than appearing with zeroes."),
    fields=GOVERNANCE_FIELDS + (
        _f("account_id", "string", "", "The account.", "Identity"),
        _f("customer_id", "string", "", "The customer.", "Identity"),
        _f("reporting_month", "string", "", "Reporting month as YYYY-MM.",
           "Period"),
        _f("product", "string", "", "Mortgage or Auto Finance.", "Product"),
        _f("collateral_type", "string", "", "Residential Property or "
           "Motor Vehicle.", "Collateral"),
        _f("collateral_value_sar_mn", "float", "rcy",
           "Appraised value of the security.", "Collateral"),
        _f("ltv_pct", "float", "percent",
           "Balance as a percentage of collateral value.", "Collateral"),
        _f("collateral_coverage_pct", "float", "percent",
           "Collateral value as a percentage of EAD.", "Collateral"),
        _f("valuation_age_months", "integer", "months",
           "Months since the last valuation.", "Collateral"),
    ))


RELATIONS: dict[str, tuple[Relation, ...]] = {
    dom.CORPORATE: (_CORP_BORROWER, _CORP_FACILITY, _CORP_COLLATERAL,
                    _CORP_COVENANT),
    dom.RETAIL: (_RETAIL_CUSTOMER, _RETAIL_ACCOUNT, _RETAIL_BEHAVIOUR,
                 _RETAIL_COLLATERAL),
}


def relations(domain_id: str) -> tuple[Relation, ...]:
    return RELATIONS[dom.parse(domain_id)]


def relation_names(domain_id: str) -> tuple[str, ...]:
    return tuple(r.name for r in relations(domain_id))


def relation(domain_id: str, name: str) -> Relation:
    wanted = str(name or "").strip().lower()
    for spec in relations(domain_id):
        if spec.name == wanted:
            return spec
    raise UnknownRelation(
        f"{name!r} is not a relation of the {dom.LABELS[dom.parse(domain_id)]} "
        f"domain. Its relations are: "
        f"{', '.join(relation_names(domain_id))}.")


def field(domain_id: str, relation_name: str, column: str) -> Field:
    return relation(domain_id, relation_name).field(column)


def domain_of_relation(name: str) -> str:
    """Which book owns this relation name. Used to refuse a cross-domain read.

    Relation names are deliberately prefixed per domain, so this is a lookup
    rather than a guess -- and a name belonging to neither book raises rather
    than defaulting to one.
    """
    wanted = str(name or "").strip().lower()
    for domain_id, specs in RELATIONS.items():
        if any(spec.name == wanted for spec in specs):
            return domain_id
    raise UnknownRelation(f"{name!r} is not a relation of any domain.")


__all__ = ["Field", "GOVERNANCE_FIELDS", "RELATIONS", "Relation",
           "UnknownField", "UnknownRelation", "domain_of_relation", "field",
           "relation", "relation_names", "relations"]
