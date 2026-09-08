"""The five post-anchor notch modifiers — Tab 06 Section E of the corrected
workbook.

Five things that do not belong in a weighted average, because they are not
measures of severity — they are measures of how much to trust or extend the
anchor (Tab 06 Section E): Network contagion, Direction of travel, Evidence
quality, Data staleness, Management and governance. Each is minus one, zero
or plus one notch. The net is capped at plus or minus two, and each notch is
worth 8 points:

    final_before_caps = MIN(100, MAX(0, anchor + 8 * net_notches_capped))

This mechanism does not exist in the earlier, incorrect workbook draft this
module replaces (that draft had no notch step at all — its combination was
pure multiplication). Every applied notch is recorded with its reason, so a
score can always be read back as an audit trail, per Tab 06 Section G.
"""

from __future__ import annotations

from dataclasses import dataclass

POINTS_PER_NOTCH = 8
NET_NOTCH_CAP = 2

NOTCH_KEYS: tuple[str, ...] = (
    "network_contagion", "direction_of_travel", "evidence_quality",
    "data_staleness", "management_and_governance",
)

#: Tab 06 Section E, verbatim: what each notch means at -1 / 0 / +1.
NOTCH_CRITERIA: dict[str, dict[int, str]] = {
    "network_contagion": {
        -1: "No material connected-party exposure",
        0: "Connected parties stable",
        1: "A connected party is in confirmed distress and the dependency is material",
    },
    "direction_of_travel": {
        -1: "Improving for two or more consecutive months",
        0: "Flat",
        1: "Deteriorating for two or more consecutive months",
    },
    "evidence_quality": {
        -1: "All driving signals from tier 1 sources or bank systems",
        0: "Mixed tier 1 and tier 2",
        1: "Score driven by tier 3 or unverified sources",
    },
    "data_staleness": {
        -1: "All key inputs current",
        0: "Minor gaps",
        1: "Financials over 12 months old, or key feeds stale",
    },
    "management_and_governance": {
        -1: "Experienced team, clean audit history, responsive",
        0: "Neutral",
        1: "Auditor change, senior departures, or unresponsive to information requests",
    },
}


@dataclass(frozen=True)
class NotchResult:
    values: dict[str, int]  # each in {-1, 0, 1}
    net_notches_raw: int
    net_notches_capped: int
    final_before_caps: float
    reasons: dict[str, str]


def apply_notches(anchor: float, values: dict[str, int]) -> NotchResult:
    """Tab 06 Section E: sum the five notches, cap the net at +/-2, apply
    8 points per notch, clamp the final result to [0, 100]."""
    for key, value in values.items():
        if key not in NOTCH_KEYS:
            raise ValueError(f"unknown notch {key!r}")
        if value not in (-1, 0, 1):
            raise ValueError(f"notch {key!r} must be -1, 0 or 1, got {value!r}")

    net_raw = sum(values.get(k, 0) for k in NOTCH_KEYS)
    net_capped = max(-NET_NOTCH_CAP, min(NET_NOTCH_CAP, net_raw))
    final_before_caps = max(0.0, min(100.0, anchor + POINTS_PER_NOTCH * net_capped))

    reasons = {
        k: NOTCH_CRITERIA[k][values.get(k, 0)] for k in NOTCH_KEYS
    }

    return NotchResult(
        values={k: values.get(k, 0) for k in NOTCH_KEYS},
        net_notches_raw=net_raw, net_notches_capped=net_capped,
        final_before_caps=final_before_caps, reasons=reasons,
    )
