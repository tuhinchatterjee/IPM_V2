"""
The concepts a Saudi retail credit officer talks about, and where each lives.

The corporate registry in `concepts.py` binds every concept to
`portfolio_facility`, `ifrs9_staging`, `customer_ratings` and their companions.
None of those datasets exists in the retail installation, so on the retail book
every question reached the planner, found no governed measure behind any word in
it, and came back as "Which figure should CreditProbe measure?" — with a list of
corporate concepts. The data conversion, the catalogue, Early Warning, What-If
and the API were all retail; the layer that READS a question was not, and no API
test could see it because an API test does not go through the reader.

Every concept here binds to a column of `retail_facility_month`, the one
canonical retail dataset. Concepts with no retail meaning — a rating notch, a
covenant headroom, DSCR, a connected-group graph measure — are absent rather
than renamed, because relabelling corporate rating-transition mathematics as a
retail score model is the specific dishonesty the conversion exists to avoid.
"""

from __future__ import annotations

from backend.orchestration.concepts import Candidate, Concept, _c

#: The one canonical retail dataset. Every candidate below reads a column of it.
RETAIL = "retail_facility_month"


RETAIL_CONCEPTS: tuple[Concept, ...] = (
    # ---- money on the book -------------------------------------------------
    Concept(
        id="exposure", label="gross carrying amount",
        pattern=r"gross carrying amount|\bgca\b|drawn exposure|outstanding balance|\bexposure\b(?! at default)",
        unit="SAR",
        candidates=(
            _c(RETAIL, "gross_carrying_amount_sar",
               "Outstanding principal plus accrued profit — the exposure the "
               "loss allowance is measured against, and what a retail portfolio "
               "question means by exposure.",
               "gross", "carrying", "gca", "book", default=True,
               label="gross carrying amount"),
            _c(RETAIL, "outstanding_principal_sar",
               "Principal outstanding only, before accrued profit.",
               "principal", "outstanding", label="outstanding principal"),
            _c(RETAIL, "ead_base_sar",
               "Exposure at default under the base scenario, including the "
               "credit-conversion allowance on undrawn card commitments.",
               "at default", "ead", "ccf", label="exposure at default"),
        )),
    Concept(
        id="ead", label="exposure at default",
        pattern=r"exposure at default|\bead\b",
        unit="SAR",
        candidates=(
            _c(RETAIL, "ead_base_sar", "Exposure at default, base scenario.",
               "base", default=True),
            _c(RETAIL, "ead_downturn_sar", "Exposure at default, downturn scenario.",
               "downturn", "stress", "adverse"),
            _c(RETAIL, "ead_upturn_sar", "Exposure at default, upturn scenario.",
               "upturn", "benign"),
        )),
    Concept(
        id="limit", label="credit limit",
        pattern=r"credit limit|\blimit\b|approved limit",
        unit="SAR",
        candidates=(
            _c(RETAIL, "current_credit_limit_sar",
               "The card limit in force at this month-end. Card only.",
               "current", "card", default=True),
            _c(RETAIL, "original_credit_limit_sar",
               "The card limit approved at origination.", "original", "origination"),
        )),
    Concept(
        id="undrawn", label="undrawn commitment",
        pattern=r"undrawn|available limit|headroom",
        unit="SAR",
        candidates=(
            _c(RETAIL, "undrawn_commitment_sar",
               "Card limit not drawn at this month-end.", default=True),
        )),
    Concept(
        id="finance_amount", label="original finance amount",
        pattern=r"original finance amount|finance amount|loan amount|amount financed",
        unit="SAR",
        candidates=(
            _c(RETAIL, "original_finance_amount_sar",
               "The amount financed at origination. Amortising products only.",
               default=True),
        )),

    # ---- impairment --------------------------------------------------------
    Concept(
        id="ecl", label="expected credit loss",
        pattern=r"expected credit loss|\becl\b|loss allowance|impairment|provision(?:ing)?",
        unit="SAR",
        candidates=(
            _c(RETAIL, "ecl_final_sar",
               "The loss allowance carried on the facility: probability-weighted "
               "ECL plus management overlay. The figure an impairment question "
               "means, and the What-If baseline.",
               "final", "allowance", "carried", "booked", "weighted",
               default=True, label="final ECL"),
            _c(RETAIL, "ecl_weighted_sar",
               "Probability-weighted ECL across the three scenarios, before any "
               "overlay.", "before overlay", "modelled", label="weighted ECL"),
            _c(RETAIL, "ecl_base_sar",
               "ECL under the BASE macroeconomic scenario alone — one of the "
               "three inside the weighted figure, not the allowance.",
               "base", "base scenario", label="base-scenario ECL"),
            _c(RETAIL, "ecl_downturn_sar",
               "ECL under the downturn scenario.", "downturn", "stress",
               "adverse", label="downturn ECL"),
            _c(RETAIL, "ecl_upturn_sar",
               "ECL under the upturn scenario.", "upturn", "benign",
               label="upturn ECL"),
        )),
    Concept(
        id="ecl_coverage", label="ECL coverage",
        pattern=r"ecl coverage|coverage ratio|provision coverage|allowance coverage",
        higher_is_worse=False, unit="ratio",
        candidates=(
            _c(RETAIL, "ecl_coverage_ratio",
               "The loss allowance as a proportion of the gross carrying amount.",
               default=True),
        )),
    Concept(
        id="overlay", label="management overlay",
        pattern=r"management overlay|\boverlay\b|post-model adjustment",
        unit="SAR",
        candidates=(
            _c(RETAIL, "management_overlay_sar",
               "The overlay applied on top of the modelled result, kept separate "
               "and visible.", default=True),
        )),
    Concept(
        id="stage", label="IFRS 9 stage",
        pattern=r"ifrs\s*9 stage|\bstage\b|staging|\bsicr\b",
        is_ordinal=True,
        candidates=(
            _c(RETAIL, "ifrs9_stage",
               "The IFRS 9 impairment stage under the versioned synthetic "
               "staging policy.", default=True),
            _c(RETAIL, "previous_month_stage",
               "The stage carried in the previous month, for migration.",
               "previous", "prior", "last month"),
        )),
    Concept(
        id="sicr", label="significant increase in credit risk",
        pattern=r"significant increase in credit risk|sicr flag|sicr trigger",
        is_state=True,
        candidates=(
            _c(RETAIL, "sicr_flag",
               "Whether a significant increase in credit risk was recognised.",
               default=True),
        )),

    # ---- probability, loss and the curves ----------------------------------
    Concept(
        id="pd_12m", label="12-month PD",
        pattern=r"12[- ]?month pd|twelve[- ]?month pd|\bpd12\b|point[- ]in[- ]time pd|\bpit pd\b",
        unit="probability",
        candidates=(
            _c(RETAIL, "pd_pit_12m_base",
               "Point-in-time 12-month default probability, base scenario.",
               "base", "pit", "point in time", default=True),
            _c(RETAIL, "pd_pit_12m_downturn",
               "12-month PD under the downturn scenario.", "downturn", "stress"),
            _c(RETAIL, "pd_ttc_12m",
               "Through-the-cycle 12-month reference probability.",
               "ttc", "through the cycle", "cycle"),
        )),
    Concept(
        id="pd_lifetime", label="lifetime PD",
        pattern=r"lifetime pd|remaining[- ]life pd|cumulative pd",
        unit="probability",
        candidates=(
            _c(RETAIL, "pd_pit_lifetime_base",
               "Cumulative default probability over the applicable remaining "
               "life, base scenario. A different quantity from the 12-month PD.",
               "base", default=True),
            _c(RETAIL, "pd_pit_lifetime_downturn",
               "Lifetime PD under the downturn scenario.", "downturn", "stress"),
        )),
    Concept(
        id="pd", label="probability of default",
        pattern=r"probability of default|\bpd\b(?! ?model)",
        unit="probability",
        candidates=(
            _c(RETAIL, "pd_pit_12m_base",
               "Point-in-time 12-month PD, base scenario. What a PD question "
               "means unless a lifetime horizon is asked for.",
               "12 month", "twelve month", "annual", default=True,
               label="12-month PD"),
            _c(RETAIL, "pd_pit_lifetime_base",
               "Cumulative PD over the remaining life.", "lifetime",
               "remaining life", label="lifetime PD"),
            _c(RETAIL, "pd_ttc_12m",
               "Through-the-cycle reference PD.", "ttc", "through the cycle",
               label="through-the-cycle PD"),
        )),
    Concept(
        id="pd_origination", label="PD at origination",
        pattern=r"pd at origination|origination pd|initial pd",
        unit="probability",
        candidates=(
            _c(RETAIL, "pd_ttc_at_origination_12m",
               "The through-the-cycle 12-month PD recorded at origination, the "
               "reference a SICR test measures against.", default=True),
        )),
    Concept(
        id="lgd", label="loss given default",
        pattern=r"loss given default|\blgd\b",
        unit="ratio",
        candidates=(
            _c(RETAIL, "lgd_base", "Loss given default, base scenario.",
               "base", default=True),
            _c(RETAIL, "lgd_downturn", "LGD under the downturn scenario.",
               "downturn", "stress", "adverse"),
            _c(RETAIL, "lgd_upturn", "LGD under the upturn scenario.", "upturn"),
        )),

    # ---- delinquency and collections ---------------------------------------
    Concept(
        id="dpd", label="days past due",
        pattern=r"days past due|\bdpd\b|arrears|delinquen(?:t|cy)|overdue",
        unit="days",
        candidates=(
            _c(RETAIL, "dpd", "Days past due at this month-end.",
               "current", default=True),
            _c(RETAIL, "max_dpd_12m", "The worst days past due in twelve months.",
               "worst", "maximum", "max", "12 month"),
            _c(RETAIL, "max_dpd_6m", "The worst days past due in six months.",
               "six month", "6 month"),
            _c(RETAIL, "previous_month_dpd", "Days past due a month earlier.",
               "previous", "prior", "last month"),
        )),
    Concept(
        id="dpd_bucket", label="delinquency bucket",
        pattern=r"dpd bucket|arrears bucket|delinquency bucket|ageing bucket",
        is_categorical=True,
        candidates=(
            _c(RETAIL, "dpd_bucket", "The banded days-past-due position.",
               default=True),
        )),
    Concept(
        id="overdue", label="overdue amount",
        pattern=r"overdue amount|amount overdue|amount in arrears",
        unit="SAR",
        candidates=(
            _c(RETAIL, "overdue_amount_sar",
               "Amounts contractually due and unpaid at this month-end.",
               default=True),
        )),
    Concept(
        id="default_state", label="in default",
        pattern=r"\bin default\b|defaulted|credit[- ]impaired",
        is_state=True,
        candidates=(
            _c(RETAIL, "current_default_flag",
               "In default under the versioned default definition: 90+ days past "
               "due, or recorded unlikeliness to pay.", default=True),
        )),
    Concept(
        id="cure", label="cured",
        pattern=r"\bcured?\b|cure flag|probation",
        is_state=True,
        candidates=(
            _c(RETAIL, "cure_flag",
               "Whether the facility has cured out of a default episode.",
               default=True),
        )),
    Concept(
        id="forbearance", label="forbearance",
        pattern=r"forbearance|forborne|restructur(?:ed|ing)",
        is_state=True,
        candidates=(
            _c(RETAIL, "forbearance_flag", "Whether forbearance was granted.",
               default=True),
            _c(RETAIL, "restructured_flag", "Whether the contract was restructured.",
               "restructure", "restructured"),
        )),
    Concept(
        id="writeoff", label="write-off",
        pattern=r"write[- ]?offs?|written off|charge[- ]?off",
        unit="SAR",
        candidates=(
            _c(RETAIL, "writeoff_amount_month_sar",
               "Amount written off in this month. A period FLOW.",
               "this month", "monthly", default=True),
            _c(RETAIL, "cumulative_writeoff_sar",
               "Total written off on this facility to date.",
               "cumulative", "total", "to date"),
        )),
    Concept(
        id="collections_stage", label="collections stage",
        pattern=r"collections? stage|collection status|recovery stage",
        is_categorical=True,
        candidates=(
            _c(RETAIL, "collections_stage",
               "How far collections escalation has gone.", default=True),
        )),

    # ---- card behaviour ----------------------------------------------------
    Concept(
        id="utilisation", label="utilisation",
        pattern=r"utili[sz]ation|\butili[sz]ed\b|limit usage",
        unit="ratio",
        candidates=(
            _c(RETAIL, "utilisation_ratio",
               "Drawn balance over the current credit limit. Card only.",
               "current", default=True),
            _c(RETAIL, "utilisation_avg_3m",
               "Average utilisation over three months.", "average", "3 month",
               "three month"),
            _c(RETAIL, "utilisation_change_3m_pp",
               "Change in utilisation over three months, in percentage points.",
               "change", "movement", "shift"),
        )),

    # ---- the scorecards ----------------------------------------------------
    Concept(
        id="application_score", label="application score",
        pattern=r"application scores?|origination scores?|underwriting scores?|\bapp score\b",
        higher_is_worse=False, unit="points",
        candidates=(
            _c(RETAIL, "application_score_at_origination",
               "The application score recorded at origination, frozen on every "
               "later snapshot.", default=True),
        )),
    Concept(
        id="behavioural_score", label="behavioural score",
        pattern=r"behaviou?ral scores?|\bbeh(?:aviou?ral)? score\b|monthly scores?",
        higher_is_worse=False, unit="points",
        candidates=(
            _c(RETAIL, "behavioural_score",
               "The behavioural score at this month-end, recomputed from "
               "information available by that date.", default=True),
            _c(RETAIL, "behavioural_score_change_3m",
               "The change in behavioural score over three months.",
               "change", "movement", "deterioration"),
        )),
    Concept(
        id="score_band", label="score band",
        pattern=r"score bands?|risk bands?|rating bands?",
        is_categorical=True,
        candidates=(
            _c(RETAIL, "application_score_band",
               "The band the application score falls in.",
               "application", "origination", default=True),
            _c(RETAIL, "behavioural_score_band",
               "The band the behavioural score falls in.",
               "behavioural", "behavioral", "monthly"),
        )),
    Concept(
        id="bureau_score", label="bureau score",
        pattern=r"bureau scores?|credit bureau|simah|external scores?",
        higher_is_worse=False, unit="points",
        candidates=(
            _c(RETAIL, "bureau_score_current",
               "The synthetic bureau proxy score at this month-end.",
               "current", "latest", default=True),
            _c(RETAIL, "bureau_score_at_origination",
               "The bureau proxy score recorded at origination.",
               "origination", "at origination", "initial"),
            _c(RETAIL, "bureau_score_change_3m",
               "The change in the bureau proxy score over three months.",
               "change", "movement", "deterioration"),
        )),

    # ---- the customer ------------------------------------------------------
    Concept(
        id="income", label="verified monthly income",
        pattern=r"verified income|monthly income|\bincome\b|\bsalary\b(?! transfer)",
        unit="SAR/month",
        candidates=(
            _c(RETAIL, "verified_total_monthly_income_sar",
               "Verified monthly salary plus verified other income. A CUSTOMER "
               "value, repeated on each of their facilities.",
               "total", "verified", default=True),
            _c(RETAIL, "verified_monthly_salary_sar",
               "Verified monthly salary alone.", "salary", "basic"),
            _c(RETAIL, "origination_income_sar",
               "Verified income evidenced at application.",
               "origination", "at origination", "application"),
        )),
    Concept(
        id="obligations", label="monthly credit obligations",
        pattern=r"credit obligations?|monthly obligations?|debt service|instal?ments?",
        unit="SAR/month",
        candidates=(
            _c(RETAIL, "monthly_total_credit_obligations_sar",
               "Own-bank obligations, this facility's instalment included once, "
               "plus verified external obligations. A CUSTOMER value.",
               "total", default=True),
            _c(RETAIL, "monthly_external_credit_obligations_sar",
               "Verified obligations to other lenders.", "external", "other banks"),
        )),
    Concept(
        id="dbr", label="debt burden ratio",
        pattern=r"debt burden(?: ratio)?|\bdbr\b|indebtedness",
        unit="ratio",
        candidates=(
            _c(RETAIL, "debt_burden_ratio",
               "Total monthly credit obligations over verified total monthly "
               "income at this snapshot.", "current", default=True),
            _c(RETAIL, "origination_debt_burden_ratio",
               "The debt burden ratio recorded at application.",
               "origination", "at origination", "application"),
        )),
    Concept(
        id="disposable_income", label="disposable income",
        pattern=r"disposable income|affordability buffer|surplus income",
        higher_is_worse=False, unit="SAR/month",
        candidates=(
            _c(RETAIL, "disposable_income_sar",
               "Verified income less household expenses and all credit "
               "obligations. A CUSTOMER value.", default=True),
        )),
    Concept(
        id="salary_missed", label="missed salary cycles",
        pattern=r"missed salary|salary interruption|salary missed|salary delay",
        unit="count",
        candidates=(
            _c(RETAIL, "salary_missed_cycle_count_3m",
               "Expected salary credit cycles with no salary observed, over three "
               "months. Evidence of income interruption, not proof of job loss.",
               default=True),
        )),
    Concept(
        id="buffer", label="cash buffer",
        pattern=r"cash buffer|balance buffer|personal buffer",
        higher_is_worse=False, unit="months",
        candidates=(
            _c(RETAIL, "balance_buffer_months",
               "Average personal account balance over monthly credit obligations.",
               default=True),
        )),

    # ---- security ----------------------------------------------------------
    Concept(
        id="collateral", label="collateral value",
        pattern=r"collateral(?: value)?|security value|property value",
        higher_is_worse=False, unit="SAR",
        candidates=(
            _c(RETAIL, "collateral_value_current_sar",
               "Latest valuation of the security held. Secured products only.",
               "current", "latest", default=True),
            _c(RETAIL, "collateral_value_origination_sar",
               "Valuation at origination.", "origination", "original"),
        )),
    Concept(
        id="ltv", label="loan to value",
        pattern=r"loan[- ]to[- ]value|\bltv\b",
        unit="ratio",
        candidates=(
            _c(RETAIL, "ltv_current_ratio",
               "Gross carrying amount over current collateral value.",
               "current", default=True),
            _c(RETAIL, "ltv_origination_ratio",
               "Original finance amount over collateral value at origination.",
               "origination", "original", "at origination"),
        )),

    # ---- lifecycle ---------------------------------------------------------
    Concept(
        id="months_on_book", label="months on book",
        pattern=r"months on book|\bmob\b|seasoning|age on book",
        unit="months",
        candidates=(
            _c(RETAIL, "months_on_book",
               "Whole months from origination to this snapshot.", default=True),
        )),
    Concept(
        id="vintage", label="origination vintage",
        pattern=r"vintages?|origination cohort|booking month",
        is_categorical=True,
        candidates=(
            _c(RETAIL, "origination_vintage",
               "The origination month, as the cohort key for vintage analysis.",
               default=True),
        )),
    Concept(
        id="tenor", label="remaining tenor",
        pattern=r"remaining tenor|tenor|remaining term|months to maturity",
        unit="months",
        candidates=(
            _c(RETAIL, "remaining_contractual_tenor_months",
               "Contractual months still to run.", "remaining", default=True),
            _c(RETAIL, "original_tenor_months",
               "The tenor granted at origination.", "original", "granted"),
        )),

    # ---- monitoring outcomes ----------------------------------------------
    Concept(
        id="observed_default", label="observed 12-month default",
        pattern=r"observed defaults?|realised defaults?|actual defaults?|default outcome",
        is_state=True,
        candidates=(
            _c(RETAIL, "observed_default_within_window",
               "Whether a NEW default was observed in the twelve months after "
               "the snapshot. An EVALUATION label: it became knowable at "
               "outcome_known_at and is never a predictor.", default=True),
        )),
)


def concept_ids() -> tuple[str, ...]:
    return tuple(c.id for c in RETAIL_CONCEPTS)
