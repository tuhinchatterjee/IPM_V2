"""The definitions every retail chart, table and paragraph has to agree on.

The failure this exists for
---------------------------
A screen said the 30+ DPD rate was 7.51%. Another said 4.9%. Both were right:
one weighted by exposure, one counted accounts, and neither said which. A
reader comparing them concluded the book had improved between two panels of
the same page.

Worse is the pairing the contract singles out: a DPD PREVALENCE rate — the
share of the book that is late at a month-end — put beside a MODEL PD, which
is the probability of an event over the next twelve months. They are not the
same kind of number. One is a stock at a date, the other is a flow over a
window, and "observed default rate exceeds predicted PD" means nothing at all
unless both sides use the same event, horizon, population and weighting.

So each metric is written down once, with its numerator, its denominator, the
population it is eligible over, its horizon and its weighting; and an analysis
records the ID it used rather than the arithmetic it happened to do.

What is NOT here
----------------
Thresholds. A PSI above 0.25 is "material" by a policy this demo carries, not
by arithmetic. The policy is versioned separately so that reading a number and
judging it stay separable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

REGISTRY_VERSION = "retail-metric-registry-1.0.0"

#: Demo policy, not a regulatory constant. Named so that a report can say
#: whose judgement it is.
THRESHOLD_POLICY_VERSION = "retail-metric-thresholds-1.0.0"

STOCK = "stock at month-end"
FLOW = "event rate over a window"
DISTRIBUTION = "distribution shift"

BY_EXPOSURE = "exposure-weighted"
BY_ACCOUNT = "account-count"
BY_CUSTOMER = "distinct customers"


@dataclass(frozen=True)
class Definition:
    """One metric, pinned hard enough that two screens cannot disagree."""

    metric_id: str
    name: str
    kind: str
    weighting: str
    numerator: str
    denominator: str
    population: str
    horizon: str
    #: The governed metric in the catalogue that computes this, where one
    #: exists. Empty when the metric is a statistic rather than a book ratio.
    governed_metric_id: str = ""
    unit: str = "percent"
    higher_is_better: bool | None = False
    #: What a reasonable reader would otherwise assume this was.
    not_this: str = ""
    comparable_with: tuple[str, ...] = ()
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        out = {k: getattr(self, k) for k in (
            "metric_id", "name", "kind", "weighting", "numerator",
            "denominator", "population", "horizon", "governed_metric_id",
            "unit", "higher_is_better", "not_this", "version")}
        out["comparable_with"] = list(self.comparable_with)
        out["registry_version"] = REGISTRY_VERSION
        return out


DEFINITIONS: tuple[Definition, ...] = (
    Definition(
        "ret.dpd30.exposure", "30+ DPD rate, exposure-weighted", STOCK,
        BY_EXPOSURE,
        "Gross carrying amount on facilities 30 or more days past due at the "
        "month-end",
        "Gross carrying amount of all facilities at the month-end",
        "All open retail facilities in scope", "point in time",
        governed_metric_id="retail.dpd30_rate",
        not_this="Not a default rate and not a probability. It is the share "
                 "of the book that is late on one date.",
        comparable_with=("ret.dpd30.accounts",)),
    Definition(
        "ret.dpd30.accounts", "30+ DPD rate, by account count", STOCK,
        BY_ACCOUNT,
        "Count of facilities 30 or more days past due at the month-end",
        "Count of all facilities at the month-end",
        "All open retail facilities in scope", "point in time",
        governed_metric_id="retail.dpd30_count_rate",
        not_this="Not the exposure-weighted rate. A book of many small late "
                 "accounts moves this one and not the other.",
        comparable_with=("ret.dpd30.exposure",)),
    Definition(
        "ret.default_entry.monthly", "Monthly default-entry rate", FLOW,
        BY_ACCOUNT,
        "Facilities not in default at the previous month-end that are in "
        "default at this month-end",
        "Facilities not in default at the previous month-end",
        "Facilities present in both months (matched)", "one month",
        not_this="Not the share of the book in default, which is a stock. "
                 "This counts entries during the month.",
        comparable_with=("ret.odr.12m",)),
    Definition(
        "ret.default.stock", "Facilities in default", STOCK, BY_ACCOUNT,
        "Facilities flagged in default at the month-end",
        "Facilities at the month-end",
        "All open retail facilities in scope", "point in time",
        governed_metric_id="retail.default_rate_current",
        not_this="Not an entry rate. A facility counted here may have "
                 "defaulted years ago."),
    Definition(
        "ret.odr.12m", "Observed default rate, 12 month", FLOW, BY_ACCOUNT,
        "Observation accounts that entered default within 12 months of the "
        "observation month",
        "Observation accounts eligible at the observation month",
        "Accounts not already in default at observation, whose 12-month "
        "window has fully elapsed",
        "12 months from the observation month",
        not_this="Not comparable with any DPD prevalence rate: different "
                 "event, different horizon, different denominator. This is "
                 "the only rate a 12-month PD may be compared with.",
        comparable_with=("ret.pd.mean_12m",)),
    Definition(
        "ret.pd.mean_12m", "Mean predicted 12-month PD", FLOW, BY_ACCOUNT,
        "Sum of predicted 12-month PD over eligible observation accounts",
        "Count of eligible observation accounts",
        "The same accounts as ret.odr.12m at the same observation month",
        "12 months from the observation month",
        governed_metric_id="retail.average_pd_current",
        higher_is_better=False,
        not_this="Not a rate that has happened. It is the model's "
                 "expectation for the same accounts ret.odr.12m measures.",
        comparable_with=("ret.odr.12m",)),
    Definition(
        "ret.stage2.share", "Stage 2 share of exposure", STOCK, BY_EXPOSURE,
        "Gross carrying amount in Stage 2 at the month-end",
        "Gross carrying amount of all facilities at the month-end",
        "All open retail facilities in scope", "point in time",
        governed_metric_id="retail.stage2.share"),
    Definition(
        "ret.ecl.coverage", "ECL coverage", STOCK, BY_EXPOSURE,
        "Probability-weighted expected credit loss at the month-end",
        "Gross carrying amount at the month-end",
        "All open retail facilities in scope", "point in time",
        governed_metric_id="retail.ecl_coverage",
        not_this="The weighted ECL after overlay. The base-scenario ECL and "
                 "the pre-overlay figure are separate metrics."),
    Definition(
        "ret.score_band.share.accounts", "Score-band share, by account",
        STOCK, BY_ACCOUNT,
        "Facilities in the band at the month-end",
        "Facilities with a score at the month-end",
        "Facilities carrying a score from the named scorecard version",
        "point in time", higher_is_better=None,
        not_this="Facilities without a score are excluded from the "
                 "denominator, not counted as a band."),
    Definition(
        "ret.score_band.share.exposure", "Score-band share, by exposure",
        STOCK, BY_EXPOSURE,
        "Gross carrying amount in the band at the month-end",
        "Gross carrying amount of facilities with a score",
        "Facilities carrying a score from the named scorecard version",
        "point in time", higher_is_better=None),
    Definition(
        "ret.psi.score", "Population Stability Index, score", DISTRIBUTION,
        BY_ACCOUNT,
        "Σ (p_current − p_reference) × ln(p_current / p_reference) over the "
        "reference score bins",
        "—  (an index, not a ratio)",
        "Scored facilities in each of the two populations",
        "two named populations", unit="index",
        not_this="Not a p-value and not a pass mark. The bands that call an "
                 "index material are demo policy "
                 f"({THRESHOLD_POLICY_VERSION})."),
    Definition(
        "ret.csi.characteristic", "Characteristic Stability Index",
        DISTRIBUTION, BY_ACCOUNT,
        "The same sum as ret.psi.score, computed on ONE model input's "
        "reference bins rather than on the score",
        "—  (an index, not a ratio)",
        "Facilities with the characteristic present in both populations",
        "two named populations", unit="index",
        not_this="Not the score PSI. CSI is per input variable; a screen that "
                 "uses 'CSI' for a score-level number is using the wrong ID."),
)

BY_ID: dict[str, Definition] = {one.metric_id: one for one in DEFINITIONS}


def get(metric_id: str) -> Definition | None:
    return BY_ID.get(metric_id)


def catalogue() -> list[dict[str, Any]]:
    return [one.to_dict() for one in DEFINITIONS]


def comparable(left: str, right: str) -> bool:
    """Whether two metrics may honestly be put in the same sentence."""
    one, other = BY_ID.get(left), BY_ID.get(right)
    if one is None or other is None:
        return False
    if one.metric_id == other.metric_id:
        return True
    return (other.metric_id in one.comparable_with
            or one.metric_id in other.comparable_with)


def refuse_comparison(left: str, right: str) -> str:
    """Why these two may not be compared, in a sentence a reader can act on."""
    one, other = BY_ID.get(left), BY_ID.get(right)
    if one is None or other is None:
        return f"{left!r} or {right!r} is not a registered metric."
    if comparable(left, right):
        return ""
    return (f"{one.name} is a {one.kind} ({one.weighting}, {one.horizon}); "
            f"{other.name} is a {other.kind} ({other.weighting}, "
            f"{other.horizon}). They measure different events over different "
            f"windows, so the difference between them is not a finding.")


# ------------------------------------------------------------------ indices

#: Added to an empty reference or current share before taking the logarithm.
#: A bin that is empty on one side makes the index infinite, which is not a
#: reading of the data — it is a division the arithmetic cannot perform. The
#: smoothing is disclosed rather than hidden because it changes the answer.
ZERO_BIN_SMOOTHING = 1e-6


def stability_index(reference: list[float], current: list[float],
                    *, smoothing: float = ZERO_BIN_SMOOTHING
                    ) -> dict[str, Any]:
    """PSI / CSI over matched bins: Σ (pc − pr) × ln(pc / pr).

    Both inputs are COUNTS in the same bins, in the same order. They are
    normalised here so a caller cannot pass shares that do not sum to one.
    """
    if len(reference) != len(current):
        raise ValueError("reference and current must use the same bins")
    ref_total = float(sum(reference))
    cur_total = float(sum(current))
    if ref_total <= 0 or cur_total <= 0:
        return {"index": None, "bins": [],
                "because": "one of the two populations is empty, so there is "
                           "no distribution to compare."}
    smoothed = 0
    rows: list[dict[str, Any]] = []
    total = 0.0
    for n, (r, c) in enumerate(zip(reference, current, strict=True)):
        pr, pc = r / ref_total, c / cur_total
        if pr <= 0 or pc <= 0:
            pr, pc = max(pr, smoothing), max(pc, smoothing)
            smoothed += 1
        part = (pc - pr) * math.log(pc / pr)
        total += part
        rows.append({"bin": n, "reference_count": r, "current_count": c,
                     "reference_share": round(pr, 6),
                     "current_share": round(pc, 6),
                     "contribution": round(part, 6)})
    return {"index": round(total, 6), "bins": rows,
            "smoothed_bins": smoothed, "smoothing": smoothing,
            "note": (f"{smoothed} bin(s) were empty on one side and were "
                     f"floored at {smoothing} before the logarithm."
                     if smoothed else ""),
            "registry_version": REGISTRY_VERSION}


#: Demo policy bands. Stated as policy, with an owner, because they are.
BANDS: tuple[tuple[float, str], ...] = (
    (0.10, "stable"), (0.25, "watch"), (float("inf"), "material"))


def band(index: float | None) -> str:
    if index is None:
        return "not available"
    for edge, name in BANDS:
        if index < edge:
            return name
    return "material"
