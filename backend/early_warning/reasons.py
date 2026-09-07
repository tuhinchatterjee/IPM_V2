"""The fixed reason-code library — canonical band-level text, transcribed
verbatim from the workbook, not invented.

An earlier design description (spec Section Y) assumed a reason code per
sub-category x band, keyed off the 22-weighted-sub-category hierarchy that
Conflict A found does not exist in the workbook. What the workbook DOES
provide, and what this module transcribes, is canonical reading text at
three levels: the classifier verdict (Tab 2 Section C), the T&A verdict
(Tab 3 Section D), and the final EWS band / expected action (Tab 4 Section
D, already in `combination.EXPECTED_ACTION`). The UI shows this canonical
text; an LLM may elaborate on it, but must not replace it with freehand
primary reasoning (spec Rule 5).
"""

from __future__ import annotations

CLASSIFIER_VERDICT_READING: dict[str, str] = {
    "VERY_LOW": "Structurally strong. A behavioural trigger here is unlikely to be a solvency issue.",
    "LOW": "Sound. Triggers are read at close to face value.",
    "MEDIUM": "Neutral. No amplification and no dampening of the trigger score.",
    "HIGH": "Vulnerable. The same behavioural deterioration deserves materially more attention.",
    "VERY_HIGH": "Already fragile. Even a modest trigger should reach the watchlist.",
}

TA_VERDICT_READING: dict[str, str] = {
    "VERY_LOW": "No material live deterioration.",
    "LOW": "Isolated or decaying signals. Monitor only.",
    "MEDIUM": "Genuine deterioration under way. Analyst review.",
    "HIGH": "Multiple corroborated signals worsening. Watchlist candidate.",
    "VERY_HIGH": "Severe, fast, corroborated deterioration. Immediate action.",
}

#: Tab 4 Section D — duplicated here (also in combination.EXPECTED_ACTION)
#: so the reason-code library is a single importable surface for the UI/chat
#: without needing to reach into the scoring module for display text.
EWS_BAND_EXPECTED_ACTION: dict[str, str] = {
    "VERY_LOW": "No action. Routine monitoring.",
    "LOW": "Note in the portfolio review. No individual case work.",
    "MEDIUM": "Analyst review within the monitoring cycle. Borrower 360 pulled, drivers documented.",
    "HIGH": "Watchlist consideration. Relationship manager engaged, action matrix applied.",
    "VERY_HIGH": "Immediate escalation. Escalation matrix triggered, IFRS 9 staging reviewed.",
}

#: Tab 2 Section C / Tab 4 Section D override rules, as canonical sentences —
#: what the UI shows when an override fired, instead of an LLM improvising
#: an explanation for a rule it did not choose.
OVERRIDE_REASON_TEXT: dict[str, str] = {
    "ifrs9_stage3_or_90dpd_forces_very_high":
        "The borrower is already credit-impaired (Stage 3, or 90 or more days past due). "
        "Early warning gives way to problem loan management.",
    "confirmed_sanctions_forces_very_high_and_escalation":
        "A confirmed sanctions match is a compliance event, not a gradable credit input.",
    "confirmed_sanctions_forces_very_high_routed_to_compliance":
        "A confirmed sanctions match is a compliance event, not a gradable credit input.",
    "unwaived_covenant_breach_floors_high":
        "An unwaived covenant breach is an objective condition. It cannot be averaged away "
        "by an otherwise quiet score.",
    "negative_equity_floors_high":
        "Negative equity leaves leverage undefined; the ratio-based score would otherwise "
        "understate risk.",
    "stale_or_unaudited_statements_floors_medium":
        "The financial statements are unaudited or more than 18 months old. Every ratio-based "
        "classifier loses reliability under stale or unaudited information.",
    "guarantor_in_default_forces_guarantor_capacity_very_high":
        "Credit support has failed: the guarantor is in default and the guarantee was load-bearing.",
    "classifier_very_high_and_ta_very_low_floors_low_periodic_review":
        "A structurally fragile borrower with no live signal is still worth a periodic look, "
        "but it is not an early warning alert.",
    "cross_default_acceleration_served_forces_very_high":
        "Contractual default has occurred elsewhere in the group.",
    "entity_match_confidence_below_threshold_excluded_upstream":
        "An unresolved entity match must not move a borrower's band.",
    "single_unverified_tier3_source_capped_severity_2_upstream":
        "One unverified article should not turn a borrower red.",
}


def classifier_reading(band: str) -> str:
    return CLASSIFIER_VERDICT_READING[band]


def ta_reading(band: str) -> str:
    return TA_VERDICT_READING[band]


def ews_expected_action(band: str) -> str:
    return EWS_BAND_EXPECTED_ACTION[band]


def override_reason(code: str) -> str:
    return OVERRIDE_REASON_TEXT.get(code, code.replace("_", " "))
