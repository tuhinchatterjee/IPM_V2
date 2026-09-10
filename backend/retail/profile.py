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
