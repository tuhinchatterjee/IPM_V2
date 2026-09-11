"""
The active product profile: this installation is retail, and only retail.

There is no corporate/retail switch on screen. The profile is an internal
mechanism so that shared code can ask "which product am I serving?" without
every module growing its own copy of the answer; the shipped runtime resolves to
retail and nothing else.

What this module owns:

* the retired domain and dataset identifiers, and the message a stale URL or a
  cached request gets instead of the old portfolio;
* the governed purposes the active catalogue may serve;
* the seeded questions, chips and examples the product offers on a first visit.

A missing retail seed must produce an actionable error. It must never fall back
to the retired book, which is why `retail_only_error` exists and why nothing in
here knows how to load one.
"""

from __future__ import annotations

import os
from typing import Any

RETAIL = "retail"

#: The shipped profile. The environment may name it explicitly for clarity, but
#: it cannot select anything else: this installation has one product.
ACTIVE_PROFILE = RETAIL


def is_retail() -> bool:
    configured = os.environ.get("CREDITPROBE_PRODUCT_PROFILE", RETAIL).strip().lower()
    return configured in ("", RETAIL)


#: Dataset and domain identifiers this installation no longer serves. A request
#: naming one of these is answered with a retail-only scope error — not with a
#: near-miss match, and not by reviving the dataset.
RETIRED_DOMAIN_IDS: frozenset[str] = frozenset({
    "portfolio_facility", "borrower_financials", "customer_ratings",
    "ifrs9_staging", "facility_delinquency", "credit_memo_signals",
    "macro_saudi", "corporate_connected_group", "corporate_graph_quality",
    "corporate_universe", "obligor_group", "borrower_360",
    "Core Portfolio / Facility", "Corporate Ratings", "IFRS 9 Impairment",
    "Arrears and Collections", "Credit File and Commentary", "Macroeconomic",
    "Borrower 360", "CREDIT_BOOK", "BORROWER_360",
})

#: Governed purposes the active catalogue may serve. Everything corporate is
#: absent by construction rather than filtered at the last moment.
ACTIVE_GOVERNED_PURPOSES: frozenset[str] = frozenset({
    "credit_facility_position",
    "ifrs9_impairment_staging",
    "facility_delinquency",
    "retail_customer_affordability",
    "retail_scorecard_inputs",
    "retail_early_warning_signals",
})


class RetailOnlyScopeError(LookupError):
    """A request named something this retail installation does not serve."""


def retail_only_error(identifier: str) -> RetailOnlyScopeError:
    return RetailOnlyScopeError(
        f"'{identifier}' is not available in this installation. CreditProbe is "
        "configured for Saudi retail only: it serves one analytical domain, "
        "Cockpit Data, holding the retail facility month-end book. Corporate "
        "facilities, company financial statements and internal rating grades "
        "have been retired and are not loaded. Ask a retail question, or select "
        "a month of Cockpit Data."
    )


def is_retired(identifier: str) -> bool:
    return str(identifier) in RETIRED_DOMAIN_IDS


def missing_seed_error() -> RuntimeError:
    """What the user sees when the retail data has not been built.

    Deliberately actionable, and deliberately not a fallback. An empty retail
    dataset is a build that has not been run, not an invitation to serve the
    retired portfolio.
    """
    return RuntimeError(
        "The retail dataset has not been built, so there is nothing to answer "
        "from. Run:\n\n"
        "    .venv/bin/python scripts/build_retail_demo.py\n\n"
        "then start the installation with launchers/retail/start-retail.command. "
        "No other portfolio will be served in its place."
    )


# --------------------------------------------------------------------------
# Seeded product content
# --------------------------------------------------------------------------

#: The questions the Cockpit offers on a first visit. Each is a retail question
#: this installation can genuinely answer from Cockpit Data.
STARTER_QUESTIONS: tuple[dict[str, str], ...] = (
    {"question": "For August 2026, show retail exposure, customers, facilities and "
                 "weighted ECL by product.",
     "needs": "retail_portfolio_overview",
     "note": "The standard opening review of the retail book"},
    {"question": "Why did ECL increase from July to August? Separate stage, PD, LGD, "
                 "EAD, new business and exits.",
     "needs": "retail_ecl_movement",
     "note": "The impairment bridge, with entrants and exits kept separate"},
    {"question": "Which personal-finance origination vintages show the highest "
                 "six-month delinquency?",
     "needs": "retail_vintage_performance",
     "note": "Vintage curves, with immature vintages excluded"},
    {"question": "Show Stage 1 to Stage 2 migration for auto finance between June and "
                 "August 2026.",
     "needs": "retail_stage_migration",
     "note": "Facilities matched across dates; entrants and exits are not migrations"},
    {"question": "For cards, show 30+ and 90+ DPD trends over all 25 months, with the "
                 "denominators.",
     "needs": "retail_delinquency_trend",
     "note": "Delinquency over the whole published history"},
    {"question": "Using the latest fully observed 12-month cohorts, test the "
                 "personal-finance application scorecard's AUC, Gini and KS.",
     "needs": "retail_application_discrimination",
     "note": "Matured cohorts only, each application counted once"},
    {"question": "Which retail customers have missed salary credits and simultaneously "
                 "increased card utilisation?",
     "needs": "retail_ews_investigation",
     "note": "Two retail early-warning signals on the same customers"},
    {"question": "Increase personal-finance PIT PD by 20% relative and show the "
                 "weighted ECL change.",
     "needs": "retail_whatif_sensitivity",
     "note": "A retail What-If on one product family"},
)

#: One-click chips for the scenario lab. Retail sensitivities only.
SCENARIO_STARTERS: tuple[str, ...] = (
    "Increase personal-finance PD by 20% relative",
    "Reduce verified salary by 15% for salary-transfer customers",
    "Reduce mortgage collateral values by 10% and lengthen recovery by six months",
    "Change scenario weights to base 50%, upturn 10%, downturn 40%",
)

#: Follow-ups the Cockpit offers after a retail answer.
FOLLOW_UPS: tuple[str, ...] = (
    "Now only salary-transfer customers",
    "Compare with the same month last year",
    "Why did that rise?",
    "Show the evidence",
)

#: The governed fields a retail question may break an answer down by, or filter
#: on, in the order a credit officer reaches for them.
#:
#: The failure this prevents
#: -------------------------
#:     "Show exposure, customers, facilities and weighted ECL by retail product"
#:
#: came back as ten FACILITIES. The planner's filterable-dimension list still
#: named the corporate book's columns — sector, region, segment, product_type,
#: rating_bucket, country — none of which the retail dataset carries, so the
#: installation governed NO dimensions at all: "by retail product" resolved to
#: nothing, the question fell through to the source grain, and "only personal
#: finance" had nothing to filter on either.
#:
#: Every entry is a real low-cardinality column of `retail_facility_month`.
RETAIL_DIMENSIONS: tuple[str, ...] = (
    "product_label",
    "product_subsegment",
    "customer_segment",
    "region_label",
    "city",
    "origination_channel",
    "employment_status",
    "employer_sector",
    "income_band",
    "indebtedness_band",
    "age_band",
    "dpd_bucket",
    "collections_stage",
    "utilisation_band",
    "ltv_band",
    "application_score_band",
    "behavioural_score_band",
    "collateral_type",
    "facility_status",
    "ifrs9_stage",
    # ------------------------------------------------------------------
    # The POLICY AND STATE FLAGS.
    #
    # The failure this closes
    # -----------------------
    #     "aug 2026 personal finance salary transfer stage2 ecl vs jul"
    #
    # came back with the ECL of the whole personal-finance book — SAR
    # 8,012,419 to 8,994,012 — under a heading that said "PERSONAL FINANCE".
    # Both the salary-transfer and the Stage 2 conditions were dropped, and
    # nothing on the answer said they had been. A reader would have taken that
    # figure as the salary-transfer Stage 2 movement, and it is roughly four
    # times too large.
    #
    # `salary_transfer_flag` is the single strongest affordability control in a
    # Saudi retail book, and it was not governed at all, so it could be neither
    # filtered on nor broken out by. Neither could forbearance, security,
    # policy exceptions or score overrides — which is to say, none of the
    # things a credit officer narrows a question with.
    #
    # Every entry below is a real two-valued column of `retail_facility_month`
    # with both values present.
    "salary_transfer_flag",
    "secured_flag",
    "forbearance_flag",
    "restructured_flag",
    "credit_impaired_flag",
    "current_default_flag",
    "unlikeliness_to_pay_flag",
    "sicr_flag",
    "cure_flag",
    "writeoff_flag",
    "policy_exception_flag",
    "score_override_flag",
    "new_to_bank_at_origination_flag",
    "job_loss_reported_flag",
    "employment_change_flag",
    "promise_to_pay_flag",
    "bureau_thin_file_flag",
    "bureau_adverse_flag",
    "housing_support_flag",
    # The origination cohort. Higher cardinality than the rest — one per
    # origination month — and included because vintage analysis is a question
    # this product is asked on its first screen.
    "origination_vintage",
)

#: How a credit officer writes each of those dimensions. Only the spellings the
#: field name does not already carry: `product_label` is reached by "product
#: label" without help, and "retail product" is the phrase people actually type.
RETAIL_DIMENSION_ALIASES: dict[str, tuple[str, ...]] = {
    "product_label": ("product", "products", "retail product", "retail products",
                      "product family", "product families", "product type",
                      "product types"),
    "product_subsegment": ("subsegment", "sub segment", "sub-segment"),
    "customer_segment": ("segment", "segments", "customer segments",
                         "client segment", "wealth segment"),
    "region_label": ("region", "regions", "province", "provinces", "geography",
                     "geographies", "area", "areas"),
    "city": ("cities", "town", "towns"),
    "origination_channel": ("channel", "channels", "origination channels",
                            "acquisition channel", "sourcing channel"),
    "employment_status": ("employment", "employment type", "employer type",
                          "employment types"),
    "employer_sector": ("sector", "sectors", "industry", "industries",
                        "employment sector", "employer industry"),
    "income_band": ("income", "income bands", "salary band", "salary bands"),
    "indebtedness_band": ("indebtedness", "dbr band", "dbr bands",
                          "debt burden band", "debt burden bands"),
    "age_band": ("age", "age bands", "age group", "age groups"),
    "dpd_bucket": ("dpd", "dpd buckets", "delinquency bucket",
                   "delinquency buckets", "arrears bucket", "arrears buckets",
                   "bucket", "buckets"),
    "collections_stage": ("collections", "collection stage", "collection stages",
                          "collections stages"),
    "utilisation_band": ("utilisation", "utilization", "utilisation bands",
                         "card utilisation band"),
    "ltv_band": ("ltv", "ltv bands", "loan to value band"),
    "application_score_band": ("application score bands", "application band",
                               "application bands"),
    "behavioural_score_band": ("behavioural score bands", "behavioral score band",
                               "behavioural band", "behavioural bands"),
    "collateral_type": ("collateral", "collateral types", "security type"),
    "facility_status": ("status", "facility statuses"),
    "ifrs9_stage": ("stage", "stages", "ifrs 9 stage", "ifrs 9 stages",
                    "ifrs9 stage", "staging", "impairment stage"),
    # How a credit officer says each flag. The column name is unspeakable;
    # these are the words people type.
    "salary_transfer_flag": ("salary transfer", "salary transferred",
                             "salary assignment", "salary assigned",
                             "salary-transfer customers", "salary transfers"),
    "secured_flag": ("secured", "unsecured", "with security", "collateralised",
                     "collateralized"),
    "forbearance_flag": ("forbearance", "forborne", "under forbearance"),
    "restructured_flag": ("restructured", "restructuring", "rescheduled"),
    "credit_impaired_flag": ("credit impaired", "credit-impaired", "impaired"),
    "current_default_flag": ("in default", "defaulted", "currently in default"),
    "unlikeliness_to_pay_flag": ("unlikeliness to pay", "utp",
                                 "unlikely to pay"),
    "sicr_flag": ("sicr", "significant increase in credit risk",
                  "sicr flagged"),
    "cure_flag": ("cured", "cure", "cures"),
    "writeoff_flag": ("written off", "write-off", "writeoff", "charged off"),
    "policy_exception_flag": ("policy exception", "policy exceptions",
                              "exception", "exceptions", "policy override",
                              "policy overrides"),
    "score_override_flag": ("score override", "score overrides", "override",
                            "overrides", "overridden"),
    "new_to_bank_at_origination_flag": ("new to bank", "new-to-bank", "ntb",
                                        "new customers"),
    "job_loss_reported_flag": ("job loss", "job losses", "lost their job",
                               "unemployment reported"),
    "employment_change_flag": ("employment change", "changed employer",
                               "employer change"),
    "promise_to_pay_flag": ("promise to pay", "ptp", "promises to pay"),
    "bureau_thin_file_flag": ("thin file", "thin-file", "no bureau history"),
    "bureau_adverse_flag": ("adverse bureau", "bureau adverse",
                            "adverse credit"),
    "housing_support_flag": ("housing support", "housing subsidy"),
    "origination_vintage": ("vintage", "vintages", "origination cohort",
                            "booking month", "cohort", "cohorts"),
}


#: The disclosure that travels with every seeded example and generated report.
DISCLOSURE = (
    "Synthetic Saudi retail demonstration data — not ANB customer data or "
    "approved models."
)


def product_manifest() -> dict[str, Any]:
    return {
        "profile": ACTIVE_PROFILE,
        "domain_id": "retail_cockpit",
        "domain_display": "Cockpit Data",
        "canonical_dataset": "retail_facility_month",
        "active_governed_purposes": sorted(ACTIVE_GOVERNED_PURPOSES),
        "retired_domain_ids": sorted(RETIRED_DOMAIN_IDS),
        "starter_questions": [q["question"] for q in STARTER_QUESTIONS],
        "scenario_starters": list(SCENARIO_STARTERS),
        "follow_ups": list(FOLLOW_UPS),
        "disclosure": DISCLOSURE,
    }
