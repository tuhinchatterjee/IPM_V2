"""Tab 06 Sections D-F: the final EWS score. Matrix anchor, then notches,
then caps — never a multiplication.

This replaces an earlier implementation built against a different,
incorrect workbook draft, whose combination step was `EWS = MIN(100,
T&A * CCM)` — a Classifier Context Multiplier that does not exist in the
corrected workbook. The corrected model follows the S&P-style precedent Tab
06 Section B cites explicitly: a structured anchor (`matrix.py`), then
discrete adjustments (`notches.py`), then caps — never one equation.

    anchor              = matrix.anchor(ta_band, classifier_band)          Tab 06 D
    final_before_caps   = notches.apply_notches(anchor, notch_values)      Tab 06 E
    band                = verdict_band(final_before_caps)
    ... caps/overrides applied last, Tab 06 F, verbatim ...

Verified against the Rawabi Al Nakhil worked example (Tab 07): T&A 73.0775
(HIGH), Classifier 71.283 (HIGH) -> anchor 72 -> notches -1 (network
contagion), -1 (direction of travel), 0, 0, 0 -> net -2 -> final EWS 56,
MEDIUM. `test_rawabi_regression.py` reproduces this exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.early_warning import matrix
from backend.early_warning import notches as nt

#: The representative score used when a cap/override forces a band rather
#: than reading a number off the formula — a documented implementation
#: choice, not a workbook-given number, made concrete so the result is
#: always a specific, testable score rather than "somewhere in the band".
FORCED_VERY_HIGH_SCORE = 95.0
FLOORED_HIGH_SCORE = 60.0  # the HIGH band's own lower boundary
#: Tab 06 Section F: "floored and capped at LOW" for Classifier VERY_HIGH +
#: T&A VERY_LOW — represented as the matrix's own VERY_LOW x VERY_HIGH cell
#: (22), consistent with its own reading: "an obligor with no live signal
#: cannot exceed 22".
NO_SIGNAL_FRAGILE_OBLIGOR_SCORE = 22.0


def verdict_band(score: float) -> str:
    """Tab 06 band scale — same convention throughout the model."""
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
    ta_band: str
    classifier_score: float
    classifier_band: str
    notch_values: dict[str, int]
    ifrs9_stage: int | None = None
    dpd: int | None = None
    confirmed_sanctions_match: bool = False
    cross_default_acceleration_served: bool = False
    unwaived_covenant_breach: bool = False
    entity_match_confidence_below_threshold: bool = False
    single_unverified_tier3_source_no_corroboration: bool = False


@dataclass(frozen=True)
class CombinationResult:
    anchor: int
    notch_result: nt.NotchResult
    ews_score: float
    ews_band: str
    expected_action: str
    overrides_applied: tuple[str, ...]


def combine(inp: CombinationInput) -> CombinationResult:
    """Tab 06 Sections D-F: anchor from the matrix, then notches, then caps."""
    anchor_score = matrix.anchor(inp.ta_band, inp.classifier_band)
    notch_result = nt.apply_notches(anchor_score, inp.notch_values)
    ews_score = notch_result.final_before_caps
    band = verdict_band(ews_score)
    overrides: list[str] = []

    # Tab 06 Section F, applied in order — each entry only ever raises what
    # came before it toward its own floor/forced value, never lowers it,
    # except the two forcing rules which set an absolute outcome.
    if inp.classifier_band == "VERY_HIGH" and inp.ta_band == "VERY_LOW":
        ews_score = NO_SIGNAL_FRAGILE_OBLIGOR_SCORE
        band = "LOW"
        overrides.append("classifier_very_high_and_ta_very_low_floored_and_capped_at_low")
    if inp.unwaived_covenant_breach and band not in ("HIGH", "VERY_HIGH"):
        ews_score = max(ews_score, FLOORED_HIGH_SCORE)
        band = "HIGH"
        overrides.append("unwaived_covenant_breach_floors_high")
    # The three "forced" overrides apply last and win over every floor above.
    if (inp.ifrs9_stage is not None and inp.ifrs9_stage >= 3) or (inp.dpd is not None and inp.dpd >= 90):
        ews_score = FORCED_VERY_HIGH_SCORE
        band = "VERY_HIGH"
        overrides.append("ifrs9_stage3_or_90dpd_forces_very_high")
    if inp.confirmed_sanctions_match:
        ews_score = FORCED_VERY_HIGH_SCORE
        band = "VERY_HIGH"
        overrides.append("confirmed_sanctions_forces_very_high_routed_to_compliance")
    if inp.cross_default_acceleration_served:
        ews_score = FORCED_VERY_HIGH_SCORE
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
        anchor=anchor_score, notch_result=notch_result,
        ews_score=round(ews_score, 6), ews_band=band,
        expected_action=EXPECTED_ACTION[band], overrides_applied=tuple(overrides),
    )
