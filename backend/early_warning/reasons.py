"""The fixed reason-code library — Tab 12 of the corrected workbook,
transcribed verbatim, not invented.

One fixed sentence per sub-category and band, so two analysts looking at
the same score read the same explanation, and so the alert vocabulary can
be reported on (Tab 12's own stated purpose). This replaces an earlier
implementation's flat 5-band classifier/T&A "verdict reading" text, which
was invented to fit a model architecture (a flat classifier score, a flat
T&A score) that the corrected workbook does not have — the corrected model
has 22 sub-category nodes, each needing its own band-level reason, which is
exactly what Tab 12 provides.

The UI shows this canonical text; an LLM may elaborate on it, but must not
replace it with freehand primary reasoning.
"""

from __future__ import annotations

#: Tab 12, verbatim: {sub_category_code: {band: reason_text}}.
SUBCATEGORY_REASON_TEXT: dict[str, dict[str, str]] = {
    "L1.1": {
        "VERY_LOW": "Operating balances and inflows stable against the obligor's own baseline",
        "LOW": "Mild softening in balances, within normal variation",
        "MEDIUM": "Clear fall in operating balances and account credits against baseline",
        "HIGH": "Large, sustained fall in balances with account credits down sharply",
        "VERY_HIGH": "Operating inflows have collapsed against the obligor's own baseline",
    },
    "L1.2": {
        "VERY_LOW": "Utilisation steady and well inside the sanctioned limit",
        "LOW": "Utilisation drifting up but with comfortable headroom",
        "MEDIUM": "Utilisation rising materially against the three-month average",
        "HIGH": "Sustained high utilisation with repeated excesses over limit",
        "VERY_HIGH": "Persistently over limit with repeated breaches in the last twelve months",
    },
    "L1.3": {
        "VERY_LOW": "No arrears on any facility",
        "LOW": "Isolated short delay, cured within the month",
        "MEDIUM": "Recurring short delays and occasional failed payments",
        "HIGH": "Sustained arrears in the 30 to 89 day bucket with returned payments",
        "VERY_HIGH": "Arrears at 90 days or more, or repeated returned cheques",
    },
    "L1.4": {
        "VERY_LOW": "Account activity and share of wallet unchanged",
        "LOW": "Slight decline in activity, no pattern",
        "MEDIUM": "Activity down against baseline, some business moving elsewhere",
        "HIGH": "Marked activity decline with collections diverted to other banks",
        "VERY_HIGH": "Account effectively dormant, relationship business moved away",
    },
    "L2.1": {
        "VERY_LOW": "Investment grade equivalent, Stage 1, no arrears",
        "LOW": "Sound grade, Stage 1, no material arrears",
        "MEDIUM": "Sub-investment grade or Stage 2 without arrears",
        "HIGH": "Stage 2 with 30 or more days past due, or PD above 3%",
        "VERY_HIGH": "Stage 3 or 90 or more days past due, credit-impaired",
    },
    "L2.2": {
        "VERY_LOW": "Debt service comfortably covered, leverage low",
        "LOW": "Coverage sound, leverage moderate",
        "MEDIUM": "DSCR approaching the covenant floor, leverage at 3 to 4.5 times",
        "HIGH": "DSCR at or below 1.25 times with leverage above 4.5 times",
        "VERY_HIGH": "Cash flow does not cover debt service, leverage above 6 times",
    },
    "L2.3": {
        "VERY_LOW": "Strong liquidity and a short working capital cycle",
        "LOW": "Adequate liquidity, cycle in line with sector",
        "MEDIUM": "Quick ratio near parity, working capital cycle lengthening",
        "HIGH": "Quick ratio below 0.9 with a materially extended cycle",
        "VERY_HIGH": "Liquidity insufficient, working capital cycle beyond 150 days",
    },
    "L2.4": {
        "VERY_LOW": "Margins well above sector, growing",
        "LOW": "Margins in line with sector, growth positive",
        "MEDIUM": "Margins at or slightly below sector, growth flat",
        "HIGH": "Margins materially below sector with revenue declining",
        "VERY_HIGH": "Negative margin or revenue contraction beyond 15%",
    },
    "L2.5": {
        "VERY_LOW": "Well collateralised with substantial covenant headroom",
        "LOW": "Adequate security, covenant headroom comfortable",
        "MEDIUM": "Security roughly matches exposure, headroom narrowing",
        "HIGH": "Under-collateralised with headroom under 5%",
        "VERY_HIGH": "Covenant breached or waived, security below 70% of exposure",
    },
    "L2.6": {
        "VERY_LOW": "Low utilisation, immaterial share of Tier 1, modest share of obligor debt",
        "LOW": "Moderate exposure and utilisation",
        "MEDIUM": "Utilisation and group exposure both elevated",
        "HIGH": "High utilisation with group exposure above 15% of Tier 1",
        "VERY_HIGH": "Near-full utilisation, group exposure above 20% of Tier 1, bank is the dominant lender",
    },
    "L2.7": {
        "VERY_LOW": "Recent clean audit, resilient sector, strong jurisdiction, long relationship",
        "LOW": "Audited and current, sector stable",
        "MEDIUM": "Statements ageing, sector under some pressure",
        "HIGH": "Qualified opinion or stressed sector, short relationship",
        "VERY_HIGH": "Unaudited or long overdue statements in a stressed sector",
    },
    "L2.T1": {
        "VERY_LOW": "No rating, PD or stage movement",
        "LOW": "Minor PD drift within the grade",
        "MEDIUM": "One notch downgrade or a material PD increase",
        "HIGH": "Multi-notch downgrade or migration into Stage 2",
        "VERY_HIGH": "Downgrade into default grade or migration to Stage 3",
    },
    "L2.T2": {
        "VERY_LOW": "All covenants met, collateral values stable",
        "LOW": "Headroom reduced but no breach",
        "MEDIUM": "Waiver requested on a financial covenant",
        "HIGH": "Covenant breached, or collateral value down 20 to 40%",
        "VERY_HIGH": "Multiple covenants breached, or collateral value down beyond 40%",
    },
    "L3.1": {
        "VERY_LOW": "No adverse disclosure",
        "LOW": "Routine disclosure with no credit relevance",
        "MEDIUM": "Adverse results announcement or a late statutory filing",
        "HIGH": "Restatement, auditor change, or registration status change",
        "VERY_HIGH": "Going-concern language, or registration suspended",
    },
    "L3.2": {
        "VERY_LOW": "No legal or distress event",
        "LOW": "Immaterial claim outstanding",
        "MEDIUM": "Material litigation or a regulatory enquiry opened",
        "HIGH": "Enforcement action, licence suspension, or a filed insolvency procedure",
        "VERY_HIGH": "Insolvency order, sanctions match, or licence revoked",
    },
    "L3.3": {
        "VERY_LOW": "Ratings stable, market pricing unremarkable",
        "LOW": "Outlook affirmed, spreads within range",
        "MEDIUM": "Outlook moved to negative, or spreads widened over 100 basis points",
        "HIGH": "Downgrade or watch negative, equity down sharply against the index",
        "VERY_HIGH": "Multi-notch downgrade or spreads beyond 800 basis points",
    },
    "L3.4": {
        "VERY_LOW": "No adverse news events",
        "LOW": "Minor operational reporting, not financially quantified",
        "MEDIUM": "Contract loss or project delay of moderate scale",
        "HIGH": "Major contract loss, profit warning, or senior management departure",
        "VERY_HIGH": "Fraud allegation, plant closure, or a loss above half of revenue",
    },
    "L3.5": {
        "VERY_LOW": "Sector and macro conditions supportive",
        "LOW": "Sector stable, input prices within range",
        "MEDIUM": "Sector demand softening, input costs rising",
        "HIGH": "Sector contraction with an adverse commodity or FX move",
        "VERY_HIGH": "Severe sector shock or a disruption to a key market",
    },
    "L4.1": {
        "VERY_LOW": "No upstream distress identified",
        "LOW": "Supplier base stable, alternates available",
        "MEDIUM": "A supplier under pressure, alternates exist",
        "HIGH": "A key supplier in confirmed distress with limited alternates",
        "VERY_HIGH": "Critical single-source supplier failing, no substitute available",
    },
    "L4.2": {
        "VERY_LOW": "No downstream distress identified",
        "LOW": "Customer base stable, receivables current",
        "MEDIUM": "A customer under pressure, DSO lengthening",
        "HIGH": "A key customer in confirmed distress with material receivables outstanding",
        "VERY_HIGH": "Largest debtor failing with receivables above half the ledger",
    },
    "L4.3": {
        "VERY_LOW": "Parent and guarantor sound, no group stress",
        "LOW": "Group stable, support unchanged",
        "MEDIUM": "Group entity under pressure, support intact",
        "HIGH": "Parent or guarantor deteriorating, cross-default clause live",
        "VERY_HIGH": "Guarantor in default, or cross-default acceleration served",
    },
    "L4.4": {
        "VERY_LOW": "Network well diversified, all relationships verified",
        "LOW": "Some concentration, relationships verified",
        "MEDIUM": "Concentrated upstream or downstream, some links only corroborated",
        "HIGH": "Heavy concentration with a hard-to-replace supplier or dominant debtor",
        "VERY_HIGH": "Single-source upstream and dominant debtor downstream, links partly inferred",
    },
}

#: Descriptive names, Tab 12's own column, for display alongside the code.
SUBCATEGORY_DISPLAY_NAME: dict[str, str] = {
    "L1.1": "Cash flow and inflows", "L1.2": "Limit and utilisation stress",
    "L1.3": "Payment performance", "L1.4": "Account and relationship activity",
    "L2.1": "Default proximity", "L2.2": "Leverage and coverage",
    "L2.3": "Liquidity and working capital", "L2.4": "Earnings quality",
    "L2.5": "Security and covenant protection", "L2.6": "Exposure and concentration",
    "L2.7": "Obligor profile and information quality",
    "L2.T1": "Rating, PD and stage migration", "L2.T2": "Covenant and collateral events",
    "L3.1": "Official and regulatory events", "L3.2": "Legal and distress events",
    "L3.3": "Ratings and market signals", "L3.4": "News and operating events",
    "L3.5": "Macro and sector shocks",
    "L4.1": "Upstream propagation", "L4.2": "Downstream propagation",
    "L4.3": "Ownership and credit support propagation", "L4.4": "Network fragility",
}

#: Tab 06 Section F caps/overrides — canonical sentences shown when an
#: override fired, instead of an LLM improvising an explanation for a rule
#: it did not choose.
OVERRIDE_REASON_TEXT: dict[str, str] = {
    "ifrs9_stage3_or_90dpd_forces_very_high":
        "The borrower is already credit-impaired (Stage 3, or 90 or more days past due). "
        "Early warning gives way to problem loan management.",
    "confirmed_sanctions_forces_very_high_and_escalation":
        "A confirmed sanctions match is a compliance event, not a gradable credit input.",
    "confirmed_sanctions_forces_very_high_routed_to_compliance":
        "A confirmed sanctions match is a compliance event, not a gradable credit input.",
    "cross_default_acceleration_served_forces_very_high":
        "Contractual default has occurred elsewhere in the group.",
    "unwaived_covenant_breach_floors_high":
        "An unwaived covenant breach is an objective condition. It cannot be averaged or "
        "notched away by an otherwise quiet score.",
    "negative_equity_floors_high":
        "Negative equity leaves leverage undefined; the ratio-based score would otherwise "
        "understate risk.",
    "stale_or_unaudited_statements_floors_medium":
        "The financial statements are unaudited or more than 18 months old. Every ratio-based "
        "classifier loses reliability under stale or unaudited information.",
    "guarantor_in_default_forces_guarantor_capacity_very_high":
        "Credit support has failed: the guarantor is in default and the guarantee was load-bearing.",
    "classifier_very_high_and_ta_very_low_floored_and_capped_at_low":
        "A structurally fragile obligor with no live signal deserves periodic review, not an alert.",
    "entity_match_confidence_below_threshold_excluded_upstream":
        "An unresolved entity match must not move a borrower's band.",
    "single_unverified_tier3_source_capped_severity_2_upstream":
        "One unverified article should not turn a borrower red.",
}

#: Tab 06 Section F, expected action per final band.
EWS_BAND_EXPECTED_ACTION: dict[str, str] = {
    "VERY_LOW": "No action. Routine monitoring.",
    "LOW": "Note in the portfolio review. No individual case work.",
    "MEDIUM": "Analyst review within the monitoring cycle. Borrower 360 pulled, drivers documented.",
    "HIGH": "Watchlist consideration. Relationship manager engaged, action matrix applied.",
    "VERY_HIGH": "Immediate escalation. Escalation matrix triggered, IFRS 9 staging reviewed.",
}


def subcategory_reason(sub_category_code: str, band: str) -> str:
    return SUBCATEGORY_REASON_TEXT[sub_category_code][band]


def subcategory_name(sub_category_code: str) -> str:
    return SUBCATEGORY_DISPLAY_NAME[sub_category_code]


def ews_expected_action(band: str) -> str:
    return EWS_BAND_EXPECTED_ACTION[band]


def override_reason(code: str) -> str:
    return OVERRIDE_REASON_TEXT.get(code, code.replace("_", " "))
