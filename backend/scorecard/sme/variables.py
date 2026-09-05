"""The Saudi SME scorecard variable dictionary. §6.4.

Ninety candidate predictors across six families, in the same
`Variable` vocabulary the retail dictionary uses, so the binning, fitting,
diagnostics and drift machinery reads them without a special case.

What makes this list SME rather than retail
---------------------------------------------
A retail application scorecard asks about a person: income, tenure, bureau
history. An SME scorecard asks about a *business*, and the difference is not
cosmetic. Three things carry most of the signal, and none of them exist in a
retail file:

* **Cash flow observed in the bank's own account.** Declared revenue is a
  claim; monthly credits into the operating account are an observation. The
  gap between them — `bank_credits_to_declared_sales` — is one of the
  strongest predictors here for the same reason it is in practice: a
  business whose banked turnover does not reconcile to its declared sales is
  either banking elsewhere or declaring optimistically, and both matter.

* **Concentration.** An SME with one customer worth 70% of revenue has a
  risk profile a leverage ratio cannot see. Retail has no analogue.

* **Filing and continuity behaviour.** Whether a business files on time,
  keeps issuing invoices, and keeps paying its people is a monthly signal of
  whether it is still trading normally. These are the variables that move
  first when something is wrong.

On the Saudi-specific fields
------------------------------
Several variables are named for Saudi systems — a commercial bureau score, a
VAT filing record, an e-invoicing series, a social-insurance continuity
signal, an enterprise size class. **Every one of them is a synthetic proxy.**

CreditProbe is not connected to SIMAH, ZATCA, the Ministry of Commerce,
GOSI, Qiwa, Mudad, Monsha'at, a bureau or a bank core system, and this file
does not pretend otherwise. Each such field carries `_proxy` in its name and
a `source_family` recording the kind of system a real deployment would map
it from. The naming is deliberate and load-bearing: `simah_score` in a
column header becomes "we have SIMAH" in a demonstration, and the distance
between those two sentences is the whole of the claim.

On what is not allowed to score
---------------------------------
Fields that could raise a lawful-basis, fairness or privacy question are
present so that monitoring has something to monitor, and are marked
`scoreable=False` so no equation can reference them — enforced in
`equation.py`, not merely documented. For an SME book that means owner and
key-person attributes, and the region and city fields, which are geographic
rather than personal but concentrate along lines a lender should be
monitoring rather than pricing.
"""

from __future__ import annotations

from typing import Any

from backend.scorecard.variables import (
    CATEGORICAL,
    FLAG,
    HIGHER,
    LOWER,
    NUMERIC,
    Variable,
)

VARIABLES_VERSION = "1.0.0"

SME_SCORECARD = "SME"

# --------------------------------------------------------------- source families

#: The kind of system a real deployment would map each proxy from. Recorded
#: per variable so a data dictionary can say "this would come from a
#: commercial bureau" without the column name claiming that it already does.
SOURCE_BANK = "BANK_INTERNAL"
SOURCE_FINANCIALS = "SUBMITTED_FINANCIALS"
SOURCE_BUREAU_PROXY = "COMMERCIAL_BUREAU_PROXY"
SOURCE_TAX_PROXY = "TAX_AUTHORITY_PROXY"
SOURCE_INVOICE_PROXY = "E_INVOICING_PROXY"
SOURCE_PAYROLL_PROXY = "SOCIAL_INSURANCE_PROXY"
SOURCE_REGISTRY_PROXY = "COMMERCIAL_REGISTRY_PROXY"
SOURCE_APPLICATION = "APPLICATION_FORM"

SOURCE_FAMILIES: tuple[str, ...] = (
    SOURCE_BANK, SOURCE_FINANCIALS, SOURCE_BUREAU_PROXY, SOURCE_TAX_PROXY,
    SOURCE_INVOICE_PROXY, SOURCE_PAYROLL_PROXY, SOURCE_REGISTRY_PROXY,
    SOURCE_APPLICATION,
)

#: Which of those are proxies for a system CreditProbe is not connected to.
#: A test asserts that every variable in one of these families has `_proxy`
#: in its name, so the honesty of the naming is a property of the module
#: rather than of whoever added the last row.
#:
#: The rule decides what the marker is for, and the first draft of this file
#: got it wrong in a way worth recording. `years_since_registration` was
#: filed under the registry proxy, which is true — a commercial registry is
#: where you would get it — and it made the invariant fail, because nobody
#: reading that column name would think CreditProbe had a registry feed. The
#: marker is not for "a proxy source could supply this". It is for a field
#: that reads as *that system's own output*: a bureau's score, a bureau's
#: view of facilities outstanding, a tax authority's filing record, an
#: e-invoicing series, a certificate. Those four fields moved to
#: APPLICATION_FORM, which is where a bank actually collects them, and the
#: eight commercial-bureau fields took the marker they had been missing.
PROXY_FAMILIES: frozenset[str] = frozenset({
    SOURCE_BUREAU_PROXY, SOURCE_TAX_PROXY, SOURCE_INVOICE_PROXY,
    SOURCE_PAYROLL_PROXY, SOURCE_REGISTRY_PROXY,
})

#: The six families of §6.4, as they appear on a data dictionary page.
FAMILY_ENTERPRISE = "Enterprise profile"
FAMILY_FINANCIAL = "Financial performance"
FAMILY_BANKING = "Banking and cash-flow behaviour"
FAMILY_CREDIT = "Commercial credit and bureau proxies"
FAMILY_DIGITAL = "Digitalisation and compliance proxies"
FAMILY_SECURITY = "Security and support"

FAMILIES: tuple[str, ...] = (
    FAMILY_ENTERPRISE, FAMILY_FINANCIAL, FAMILY_BANKING, FAMILY_CREDIT,
    FAMILY_DIGITAL, FAMILY_SECURITY,
)

#: Per-variable metadata that the shared `Variable` has no field for. Kept
#: beside the definitions rather than inside them so the SME dictionary stays
#: assignable to the same type the rest of the engine already handles.
FAMILY_OF: dict[str, str] = {}
SOURCE_OF: dict[str, str] = {}


def _s(name: str, label: str, kind: str, definition: str,
       direction: str, unit: str, family: str, source: str,
       scoreable: bool = True) -> Variable:
    FAMILY_OF[name] = family
    SOURCE_OF[name] = source
    return Variable(name=name, label=label, kind=kind, definition=definition,
                    risk_direction=direction, unit=unit, scoreable=scoreable)


# ============================================================ A. enterprise profile

_ENTERPRISE: tuple[Variable, ...] = (
    _s("enterprise_size_class_proxy", "Enterprise size class", CATEGORICAL,
       "MICRO, SMALL or MEDIUM, on the revenue and headcount bands a national "
       "enterprise-size certificate would carry. Synthetic proxy.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_REGISTRY_PROXY),
    _s("employee_count", "Employees", NUMERIC,
       "Headcount at the observation date.",
       LOWER, "count", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("annual_revenue_sar", "Annual revenue", NUMERIC,
       "Declared annual turnover in Saudi riyals.",
       LOWER, "SAR", FAMILY_ENTERPRISE, SOURCE_FINANCIALS),
    _s("years_since_registration", "Years trading", NUMERIC,
       "Years since commercial registration. Young businesses fail more "
       "often, and the effect is strongly non-linear below three years.",
       LOWER, "years", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("legal_form", "Legal form", CATEGORICAL,
       "ESTABLISHMENT, LLC, JOINT_STOCK or PARTNERSHIP.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("region", "Region", CATEGORICAL,
       "Saudi administrative region of the registered address. Monitored for "
       "concentration; not scored.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION, scoreable=False),
    _s("city_tier", "City tier", CATEGORICAL,
       "TIER_1, TIER_2 or TIER_3 by the size of the local market. Monitored "
       "for concentration; not scored.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION, scoreable=False),
    _s("economic_sector", "Economic sector", CATEGORICAL,
       "Sector on an ISIC-like classification: CONSTRUCTION, WHOLESALE_RETAIL, "
       "MANUFACTURING, TRANSPORT_LOGISTICS, PROFESSIONAL_SERVICES, "
       "HOSPITALITY, HEALTHCARE, CONTRACTING_GOVERNMENT.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("branch_count", "Branches", NUMERIC,
       "Number of trading locations.",
       LOWER, "count", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("relationship_tenure_months", "Relationship tenure", NUMERIC,
       "Months banked with this institution. A long relationship is both a "
       "risk signal and an information advantage.",
       LOWER, "months", FAMILY_ENTERPRISE, SOURCE_BANK),
    _s("management_experience_years", "Management experience", NUMERIC,
       "Years of sector experience of the principal manager. Personal to an "
       "individual, so monitored rather than scored.",
       LOWER, "years", FAMILY_ENTERPRISE, SOURCE_APPLICATION, scoreable=False),
    _s("key_person_dependency", "Key-person dependency", CATEGORICAL,
       "LOW, MEDIUM or HIGH: how far the business depends on one individual.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("ownership_concentration_pct", "Ownership concentration", NUMERIC,
       "Share held by the largest owner.",
       HIGHER, "pct", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("premises_owned_flag", "Premises owned", FLAG,
       "1 where the business owns rather than rents its main premises.",
       LOWER, "flag", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("facility_type", "Facility type", CATEGORICAL,
       "TERM_LOAN, WORKING_CAPITAL, OVERDRAFT, POS_FINANCING or "
       "INVOICE_FINANCING.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("requested_amount_sar", "Requested amount", NUMERIC,
       "Facility amount requested, in riyals.",
       HIGHER, "SAR", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("amount_to_revenue", "Amount to revenue", NUMERIC,
       "Requested amount divided by annual revenue. The single most direct "
       "statement of whether the business can carry what it is asking for.",
       HIGHER, "ratio", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("requested_tenor_months", "Requested tenor", NUMERIC,
       "Requested repayment term.",
       HIGHER, "months", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
    _s("finance_purpose", "Purpose", CATEGORICAL,
       "WORKING_CAPITAL, EXPANSION, EQUIPMENT, REFINANCE or CONTRACT_EXECUTION.",
       HIGHER, "", FAMILY_ENTERPRISE, SOURCE_APPLICATION),
)


# ======================================================== B. financial performance

_FINANCIAL: tuple[Variable, ...] = (
    _s("revenue_growth_yoy", "Revenue growth", NUMERIC,
       "Year-on-year change in turnover.",
       LOWER, "pct", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("ebitda_margin", "EBITDA margin", NUMERIC,
       "EBITDA over revenue.",
       LOWER, "pct", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("net_profit_margin", "Net margin", NUMERIC,
       "Net profit over revenue.",
       LOWER, "pct", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("current_ratio", "Current ratio", NUMERIC,
       "Current assets over current liabilities.",
       LOWER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("quick_ratio", "Quick ratio", NUMERIC,
       "Current assets less inventory, over current liabilities.",
       LOWER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("debt_to_equity", "Debt to equity", NUMERIC,
       "Total debt over tangible equity.",
       HIGHER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("debt_to_ebitda", "Debt to EBITDA", NUMERIC,
       "Total debt over EBITDA — how many years of earnings the debt "
       "represents.",
       HIGHER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("dscr", "DSCR", NUMERIC,
       "Debt service coverage: cash available for debt service over the "
       "service due.",
       LOWER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("interest_coverage", "Interest coverage", NUMERIC,
       "EBIT over finance cost.",
       LOWER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("ocf_to_debt", "Operating cash flow to debt", NUMERIC,
       "Operating cash flow over total debt.",
       LOWER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("tangible_net_worth_sar", "Tangible net worth", NUMERIC,
       "Equity less intangibles, in riyals.",
       LOWER, "SAR", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("retained_earnings_to_assets", "Retained earnings to assets", NUMERIC,
       "Accumulated retained earnings over total assets.",
       LOWER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("receivable_days", "Receivable days", NUMERIC,
       "Average days to collect.",
       HIGHER, "days", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("inventory_days", "Inventory days", NUMERIC,
       "Average days of stock held.",
       HIGHER, "days", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("payable_days", "Payable days", NUMERIC,
       "Average days taken to pay suppliers. Read with care: stretching "
       "payables is both a working-capital choice and a distress signal.",
       HIGHER, "days", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("cash_conversion_cycle_days", "Cash conversion cycle", NUMERIC,
       "Receivable days plus inventory days less payable days.",
       HIGHER, "days", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("leverage_trend", "Leverage trend", NUMERIC,
       "Change in debt to EBITDA over the prior year.",
       HIGHER, "ratio", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("margin_trend", "Margin trend", NUMERIC,
       "Change in EBITDA margin over the prior year.",
       LOWER, "pct", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("audited_financials_flag", "Audited financials", FLAG,
       "1 where the latest statements are audited.",
       LOWER, "flag", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
    _s("financials_age_months", "Age of financials", NUMERIC,
       "Months since the latest statement date. Stale financials are a data "
       "quality problem and a risk signal at once.",
       HIGHER, "months", FAMILY_FINANCIAL, SOURCE_FINANCIALS),
)


# ============================================ C. banking and cash-flow behaviour

_BANKING: tuple[Variable, ...] = (
    _s("avg_monthly_credits_sar", "Average monthly credits", NUMERIC,
       "Mean monthly credit turnover through the operating account.",
       LOWER, "SAR", FAMILY_BANKING, SOURCE_BANK),
    _s("avg_monthly_debits_sar", "Average monthly debits", NUMERIC,
       "Mean monthly debit turnover.",
       HIGHER, "SAR", FAMILY_BANKING, SOURCE_BANK),
    _s("account_turnover_growth", "Turnover growth", NUMERIC,
       "Change in credit turnover against the prior year.",
       LOWER, "pct", FAMILY_BANKING, SOURCE_BANK),
    _s("balance_to_credits_ratio", "Balance to credits", NUMERIC,
       "Average balance over average monthly credits — the buffer, expressed "
       "in months of turnover.",
       LOWER, "ratio", FAMILY_BANKING, SOURCE_BANK),
    _s("balance_volatility", "Balance volatility", NUMERIC,
       "Coefficient of variation of the daily balance.",
       HIGHER, "ratio", FAMILY_BANKING, SOURCE_BANK),
    _s("returned_cheques_12m", "Returned cheques", NUMERIC,
       "Cheques returned unpaid in twelve months.",
       HIGHER, "count", FAMILY_BANKING, SOURCE_BANK),
    _s("returned_payments_12m", "Returned payments", NUMERIC,
       "Direct debits and standing orders returned unpaid in twelve months.",
       HIGHER, "count", FAMILY_BANKING, SOURCE_BANK),
    _s("overdraft_days_12m", "Overdraft days", NUMERIC,
       "Days spent in unauthorised overdraft in twelve months.",
       HIGHER, "days", FAMILY_BANKING, SOURCE_BANK),
    _s("max_dpd_12m", "Max DPD", NUMERIC,
       "Worst days past due on this bank's own facilities in twelve months.",
       HIGHER, "days", FAMILY_BANKING, SOURCE_BANK),
    _s("payroll_regularity_score", "Payroll regularity", NUMERIC,
       "How consistently salaries leave the account each month, 0 to 1. A "
       "business that stops paying on time is in trouble before its "
       "financials say so.",
       LOWER, "score", FAMILY_BANKING, SOURCE_BANK),
    _s("payroll_growth_12m", "Payroll growth", NUMERIC,
       "Change in total salary payments over twelve months.",
       LOWER, "pct", FAMILY_BANKING, SOURCE_BANK),
    _s("pos_receipts_growth_12m", "POS receipts growth", NUMERIC,
       "Change in card-acquiring receipts over twelve months.",
       LOWER, "pct", FAMILY_BANKING, SOURCE_BANK),
    _s("cash_deposit_share", "Cash deposit share", NUMERIC,
       "Share of credits arriving as cash rather than transfer.",
       HIGHER, "pct", FAMILY_BANKING, SOURCE_BANK),
    _s("seasonality_index", "Seasonality", NUMERIC,
       "Ratio of peak-month to trough-month credits.",
       HIGHER, "ratio", FAMILY_BANKING, SOURCE_BANK),
    _s("revenue_concentration_hhi", "Revenue concentration", NUMERIC,
       "Herfindahl index of counterparty credits.",
       HIGHER, "index", FAMILY_BANKING, SOURCE_BANK),
    _s("top_customer_share", "Top customer share", NUMERIC,
       "Share of credits from the single largest payer.",
       HIGHER, "pct", FAMILY_BANKING, SOURCE_BANK),
    _s("top_supplier_share", "Top supplier share", NUMERIC,
       "Share of debits to the single largest payee.",
       HIGHER, "pct", FAMILY_BANKING, SOURCE_BANK),
    _s("bank_credits_to_declared_sales", "Banked to declared sales", NUMERIC,
       "Annualised account credits over declared annual revenue. A ratio far "
       "below one means the turnover is banked elsewhere or the declaration "
       "is optimistic; far above one usually means intra-group circulation.",
       LOWER, "ratio", FAMILY_BANKING, SOURCE_BANK),
)


# ============================================ D. commercial credit and bureau proxies

_CREDIT: tuple[Variable, ...] = (
    _s("commercial_bureau_score_proxy", "Commercial bureau score", NUMERIC,
       "Commercial credit score, on a 300-900 scale. Synthetic proxy for a "
       "commercial bureau; CreditProbe is not connected to one.",
       LOWER, "score", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("active_facilities_count_proxy", "Active facilities", NUMERIC,
       "Credit facilities open across all lenders.",
       HIGHER, "count", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("total_outstanding_debt_sar_proxy", "Total outstanding debt", NUMERIC,
       "Total drawn balance across all lenders.",
       HIGHER, "SAR", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("revolving_utilisation_proxy", "Revolving utilisation", NUMERIC,
       "Drawn over limit on revolving lines.",
       HIGHER, "pct", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("enquiries_3m_proxy", "Enquiries 3m", NUMERIC,
       "Credit enquiries in three months. Synthetic proxy.",
       HIGHER, "count", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("enquiries_12m_proxy", "Enquiries 12m", NUMERIC,
       "Credit enquiries in twelve months. A business shopping hard for "
       "credit is usually short of it. Synthetic proxy.",
       HIGHER, "count", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("delinquent_facilities_count_proxy", "Delinquent facilities", NUMERIC,
       "Facilities currently past due across all lenders.",
       HIGHER, "count", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("worst_dpd_12m_proxy", "Worst DPD 12m", NUMERIC,
       "Worst days past due across all lenders in twelve months. Synthetic "
       "proxy.",
       HIGHER, "days", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("prior_default_flag_proxy", "Prior default", FLAG,
       "1 where a default or write-off is on record.",
       HIGHER, "flag", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("guaranteed_obligations_sar_proxy", "Guaranteed obligations", NUMERIC,
       "Obligations of others guaranteed by this business.",
       HIGHER, "SAR", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("contingent_liability_sar", "Contingent liabilities", NUMERIC,
       "Letters of credit, guarantees and other off-balance-sheet exposure.",
       HIGHER, "SAR", FAMILY_CREDIT, SOURCE_FINANCIALS),
    _s("debt_service_burden", "Debt service burden", NUMERIC,
       "Annual debt service over annual account credits.",
       HIGHER, "ratio", FAMILY_CREDIT, SOURCE_BANK),
    _s("new_facility_growth_6m_proxy", "New facility growth", NUMERIC,
       "Growth in total facilities over six months.",
       HIGHER, "pct", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
    _s("adverse_credit_event_flag_proxy", "Adverse credit event", FLAG,
       "1 where a judgement, execution order or similar is on record.",
       HIGHER, "flag", FAMILY_CREDIT, SOURCE_BUREAU_PROXY),
)


# ================================= E. digitalisation and compliance proxies

_DIGITAL: tuple[Variable, ...] = (
    _s("vat_filing_timeliness_proxy", "VAT filing timeliness", NUMERIC,
       "Share of VAT returns filed on time over eight quarters. Synthetic "
       "proxy for a tax authority record; CreditProbe is not connected to "
       "one.",
       LOWER, "pct", FAMILY_DIGITAL, SOURCE_TAX_PROXY),
    _s("vat_arrears_flag_proxy", "VAT arrears", FLAG,
       "1 where VAT is in arrears. Synthetic proxy.",
       HIGHER, "flag", FAMILY_DIGITAL, SOURCE_TAX_PROXY),
    _s("vat_sales_to_bank_credits_proxy", "VAT sales to banked credits", NUMERIC,
       "Declared VAT sales over account credits. A second, independent read "
       "on the same reconciliation question as "
       "`bank_credits_to_declared_sales`. Synthetic proxy.",
       HIGHER, "ratio", FAMILY_DIGITAL, SOURCE_TAX_PROXY),
    _s("einvoice_continuity_months_proxy", "E-invoicing continuity", NUMERIC,
       "Consecutive months with e-invoices issued. A business that stops "
       "invoicing has stopped trading. Synthetic proxy.",
       LOWER, "months", FAMILY_DIGITAL, SOURCE_INVOICE_PROXY),
    _s("einvoice_sales_growth_proxy", "E-invoice sales growth", NUMERIC,
       "Change in invoiced sales over twelve months. Synthetic proxy.",
       LOWER, "pct", FAMILY_DIGITAL, SOURCE_INVOICE_PROXY),
    _s("einvoice_volatility_proxy", "E-invoice volatility", NUMERIC,
       "Coefficient of variation of monthly invoiced sales. Synthetic proxy.",
       HIGHER, "ratio", FAMILY_DIGITAL, SOURCE_INVOICE_PROXY),
    _s("invoice_cancellation_ratio_proxy", "Invoice cancellation ratio", NUMERIC,
       "Credit notes over invoices issued. Synthetic proxy.",
       HIGHER, "ratio", FAMILY_DIGITAL, SOURCE_INVOICE_PROXY),
    _s("invoice_customer_concentration_proxy", "Invoice concentration", NUMERIC,
       "Share of invoiced value to the largest customer. Synthetic proxy.",
       HIGHER, "pct", FAMILY_DIGITAL, SOURCE_INVOICE_PROXY),
    _s("payroll_continuity_months_proxy", "Payroll continuity", NUMERIC,
       "Consecutive months of social-insurance contributions filed. "
       "Synthetic proxy.",
       LOWER, "months", FAMILY_DIGITAL, SOURCE_PAYROLL_PROXY),
    _s("workforce_change_12m_proxy", "Workforce change", NUMERIC,
       "Change in registered headcount over twelve months. Synthetic proxy.",
       LOWER, "pct", FAMILY_DIGITAL, SOURCE_PAYROLL_PROXY),
    _s("size_certificate_current_proxy", "Size certificate current", FLAG,
       "1 where the enterprise-size certificate is in date. Synthetic proxy.",
       LOWER, "flag", FAMILY_DIGITAL, SOURCE_REGISTRY_PROXY),
    _s("tax_registration_tenure_months_proxy", "Tax registration tenure", NUMERIC,
       "Months since tax registration. Synthetic proxy.",
       LOWER, "months", FAMILY_DIGITAL, SOURCE_TAX_PROXY),
    _s("filing_exception_count_proxy", "Filing exceptions", NUMERIC,
       "Regulatory filing exceptions raised in twelve months. Synthetic proxy.",
       HIGHER, "count", FAMILY_DIGITAL, SOURCE_REGISTRY_PROXY),
)


# ========================================================= F. security and support

_SECURITY: tuple[Variable, ...] = (
    _s("collateral_value_sar", "Collateral value", NUMERIC,
       "Assessed value of pledged security.",
       LOWER, "SAR", FAMILY_SECURITY, SOURCE_BANK),
    _s("collateral_coverage", "Collateral coverage", NUMERIC,
       "Collateral value over exposure.",
       LOWER, "ratio", FAMILY_SECURITY, SOURCE_BANK),
    _s("guarantee_strength", "Guarantee strength", CATEGORICAL,
       "NONE, PERSONAL, CORPORATE or PROGRAMME — a government or development "
       "programme guarantee.",
       HIGHER, "", FAMILY_SECURITY, SOURCE_BANK),
    _s("owner_guarantee_flag", "Owner guarantee", FLAG,
       "1 where the principal owner has guaranteed the facility.",
       LOWER, "flag", FAMILY_SECURITY, SOURCE_BANK),
    _s("government_contract_share", "Government contract share", NUMERIC,
       "Share of revenue from public-sector contracts. Lowers default risk "
       "and raises receivable days at the same time, which is why both are "
       "in the dictionary.",
       LOWER, "pct", FAMILY_SECURITY, SOURCE_APPLICATION),
    _s("secured_flag", "Secured", FLAG,
       "1 where the facility is secured.",
       LOWER, "flag", FAMILY_SECURITY, SOURCE_BANK),
)


SME: tuple[Variable, ...] = (
    _ENTERPRISE + _FINANCIAL + _BANKING + _CREDIT + _DIGITAL + _SECURITY
)

BY_NAME: dict[str, Variable] = {v.name: v for v in SME}

BY_FAMILY: dict[str, tuple[Variable, ...]] = {
    FAMILY_ENTERPRISE: _ENTERPRISE,
    FAMILY_FINANCIAL: _FINANCIAL,
    FAMILY_BANKING: _BANKING,
    FAMILY_CREDIT: _CREDIT,
    FAMILY_DIGITAL: _DIGITAL,
    FAMILY_SECURITY: _SECURITY,
}


def catalogue() -> tuple[Variable, ...]:
    return SME


def get(name: str) -> Variable:
    try:
        return BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"{name!r} is not an SME scorecard variable. "
            f"{len(SME)} are defined.") from None


def names(*, scoreable_only: bool = False) -> list[str]:
    return [v.name for v in SME if v.scoreable or not scoreable_only]


def scoreable() -> set[str]:
    return {v.name for v in SME if v.scoreable}


def sensitive() -> list[str]:
    """Kept for monitoring, refused to any equation."""
    return [v.name for v in SME if not v.scoreable]


def family_of(name: str) -> str:
    return FAMILY_OF.get(name, "")


def source_of(name: str) -> str:
    return SOURCE_OF.get(name, "")


def is_proxy(name: str) -> bool:
    """Whether this field stands in for a system CreditProbe is not connected to."""
    return SOURCE_OF.get(name, "") in PROXY_FAMILIES


def proxies() -> list[str]:
    return [v.name for v in SME if is_proxy(v.name)]


def summary() -> dict[str, Any]:
    return {
        "variables_version": VARIABLES_VERSION,
        "scorecard_type": SME_SCORECARD,
        "total": len(SME),
        "scoreable": len(scoreable()),
        "monitoring_only": len(sensitive()),
        "families": {f: len(BY_FAMILY[f]) for f in FAMILIES},
        "proxy_fields": len(proxies()),
        "source_families": {
            s: sum(1 for v in SME if SOURCE_OF[v.name] == s)
            for s in SOURCE_FAMILIES
        },
        "not_connected": (
            "Every field in a proxy source family is generated. CreditProbe "
            "is not connected to SIMAH, ZATCA, the Ministry of Commerce, "
            "GOSI, Qiwa, Mudad, Monsha'at, a commercial bureau or a bank core "
            "system. Each such field carries `_proxy` in its name and records "
            "the kind of system a real deployment would map it from."),
    }


__all__ = [
    "BY_FAMILY", "BY_NAME", "FAMILIES", "FAMILY_BANKING", "FAMILY_CREDIT",
    "FAMILY_DIGITAL", "FAMILY_ENTERPRISE", "FAMILY_FINANCIAL", "FAMILY_OF",
    "FAMILY_SECURITY", "PROXY_FAMILIES", "SME", "SME_SCORECARD",
    "SOURCE_FAMILIES", "SOURCE_OF", "VARIABLES_VERSION", "catalogue",
    "family_of", "get", "is_proxy", "names", "proxies", "scoreable",
    "sensitive", "source_of", "summary",
]
