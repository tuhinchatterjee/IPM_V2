"""Tab 4: the final EWS score. Multiplication, not a lookup matrix.

    CCM (Classifier Context Multiplier): VERY_LOW 0.70, LOW 0.85, MEDIUM 1.00,
    HIGH 1.20, VERY_HIGH 1.40 — one scalar per classifier band.

    EWS score = MIN(100, T&A score * CCM)

Tab 4 Section C's "5x5 outcome matrix" is a *derived illustration* of this
formula at band midpoints — it is not an independently configured lookup
table, and the specific cell values an earlier design conversation proposed
(5/8/12/16/22 ... 95, an "anchor" plus five ±1 notch modifiers worth 8 points
each) do not exist anywhere in this workbook. This module implements the
workbook's actual multiplicative mechanism. See Section 0 of the
implementation plan for the full reconciliation.

Verified against Tab 4 Section B's worked example: classifier score 62
(HIGH), T&A score 62.217775 (HIGH), CCM 1.2 -> EWS score 74.66133 (HIGH).
`test_combination.py` reproduces this exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

CCM: dict[str, float] = {
    "VERY_LOW": 0.70, "LOW": 0.85, "MEDIUM": 1.00, "HIGH": 1.20, "VERY_HIGH": 1.40,
}


def verdict_band(score: float) -> str:
    """Tab 4 Section D band scale — same convention throughout the model."""
    if score < 20.0:
        return "VERY_LOW"
    if score < 40.0:
        return "LOW"
    if score < 60.0:
        return "MEDIUM"
    if score < 80.0:
        return "HIGH"
    return "VERY_HIGH"


EXPECTED_ACTION: dict[str, str] = {
    "VERY_LOW": "No action. Routine monitoring.",
    "LOW": "Note in the portfolio review. No individual case work.",
    "MEDIUM": "Analyst review within the monitoring cycle. Borrower 360 pulled, drivers documented.",
    "HIGH": "Watchlist consideration. Relationship manager engaged, action matrix applied.",
    "VERY_HIGH": "Immediate escalation. Escalation matrix triggered, IFRS 9 staging reviewed.",
}


@dataclass(frozen=True)
class CombinationInput:
    ta_score: float
    classifier_score: float
    classifier_band: str
    ifrs9_stage: int | None = None
    dpd: int | None = None
    confirmed_sanctions_match: bool = False
    cross_default_acceleration_served: bool = False
    unwaived_covenant_breach: bool = False
    entity_match_confidence_below_threshold: bool = False
    single_unverified_tier3_source_no_corroboration: bool = False


@dataclass(frozen=True)
class CombinationResult:
    ccm: float
    ews_score: float
    ews_band: str
    expected_action: str
    overrides_applied: tuple[str, ...]


def combine(inp: CombinationInput) -> CombinationResult:
    """Tab 4 Sections A and D: multiply, then apply the floor/override table."""
    ccm = CCM[inp.classifier_band]
    ews_score = min(100.0, inp.ta_score * ccm)
    band = verdict_band(ews_score)
    overrides: list[str] = []

    # Tab 4 Section D, verbatim. "Floored" means a minimum band, not a cap:
    # it only ever raises the score/band, never lowers what the formula gave.
    if inp.classifier_band == "VERY_HIGH" and verdict_band(inp.ta_score) == "VERY_LOW" and band == "VERY_LOW":
        ews_score = 20.0
        band = "LOW"
        overrides.append("classifier_very_high_and_ta_very_low_floors_low_periodic_review")
    if inp.unwaived_covenant_breach and band not in ("HIGH", "VERY_HIGH"):
        ews_score = max(ews_score, 60.0)
        band = "HIGH"
        overrides.append("unwaived_covenant_breach_floors_high")
    # The four "forced" overrides apply last and win over every floor above.
    if (inp.ifrs9_stage is not None and inp.ifrs9_stage >= 3) or (inp.dpd is not None and inp.dpd >= 90):
        ews_score = 100.0
        band = "VERY_HIGH"
        overrides.append("ifrs9_stage3_or_90dpd_forces_very_high")
    if inp.confirmed_sanctions_match:
        ews_score = 100.0
        band = "VERY_HIGH"
        overrides.append("confirmed_sanctions_forces_very_high_routed_to_compliance")
    if inp.cross_default_acceleration_served:
        ews_score = 100.0
        band = "VERY_HIGH"
        overrides.append("cross_default_acceleration_served_forces_very_high")

    # These two do not change the combination step itself — they are applied
    # upstream, when the T&A input signals are selected (excluding unresolved
    # entity matches; capping an uncorroborated Tier-3 external trigger's
    # severity at 2 before it ever reaches the accelerator/aggregation
    # stage) — recorded here only as informational flags for audit/lineage
    # when the caller indicates they were applied upstream.
    if inp.entity_match_confidence_below_threshold:
        overrides.append("entity_match_confidence_below_threshold_excluded_upstream")
    if inp.single_unverified_tier3_source_no_corroboration:
        overrides.append("single_unverified_tier3_source_capped_severity_2_upstream")

    return CombinationResult(
        ccm=ccm, ews_score=round(ews_score, 6), ews_band=band,
        expected_action=EXPECTED_ACTION[band], overrides_applied=tuple(overrides),
    )
