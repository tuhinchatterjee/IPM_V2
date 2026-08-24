"""
Prototype backtesting: does the signal actually rank facilities correctly?

Everything here is measured OUT OF TIME. The model is fitted on early quarters
and tested on later ones it has never seen, because a model tested on the data
it was fitted on will always look good and will always be lying. That is the
single most common way a risk model gets into production carrying a number
nobody should have believed.

The measures
------------
    AUC          the chance that a randomly chosen facility that DID migrate
                 scored higher than one that did not. 0.5 is a coin toss.
    KS           the largest gap between the cumulative distributions of
                 migrating and non-migrating facilities.
    Decile lift  the observed migration rate in the worst-scoring tenth of the
                 book, against the rate across the whole of it. This is the one
                 a credit officer actually uses: "if I only look at the worst
                 decile, how much of next quarter's trouble do I catch?"
    Calibration  predicted rate against observed rate, by band. Discrimination
                 says the order is right; calibration says the level is.

Every one of them is computed here from first principles, in a few lines each,
so a reviewer can check the arithmetic rather than trust a library.

Nothing in this module makes a model validated. Backtesting is evidence for a
validation, not a substitute for one — see `lifecycle.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.early_warning.model import BANDS, band_for


def auc(scores: np.ndarray, outcome: np.ndarray) -> float:
    """Area under the ROC curve, via the rank-sum identity.

    Equivalent to the Mann-Whitney statistic: the AUC is the probability that a
    randomly drawn event outranks a randomly drawn non-event, and that is a
    counting exercise on ranks rather than an integration.
    """
    positives = outcome > 0.5
    n_pos, n_neg = int(positives.sum()), int((~positives).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    # Ties share the average of the ranks they span, or the measure would
    # depend on the order rows happened to arrive in.
    sorted_scores = scores[order]
    start = 0
    for i in range(1, len(sorted_scores) + 1):
        if i == len(sorted_scores) or sorted_scores[i] != sorted_scores[start]:
            if i - start > 1:
                ranks[order[start:i]] = (start + 1 + i) / 2.0
            start = i
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def ks(scores: np.ndarray, outcome: np.ndarray) -> float:
    """Kolmogorov-Smirnov separation between events and non-events."""
    positives = outcome > 0.5
    if positives.sum() == 0 or (~positives).sum() == 0:
        return float("nan")
    order = np.argsort(-scores, kind="mergesort")
    event = positives[order].astype(float)
    cumulative_event = np.cumsum(event) / max(event.sum(), 1)
    cumulative_other = np.cumsum(1 - event) / max((1 - event).sum(), 1)
    return float(np.max(np.abs(cumulative_event - cumulative_other)))


@dataclass
class DecileRow:
    decile: int
    facilities: int
    events: int
    rate_pct: float
    #: How many times the book-wide rate this decile's rate is.
    lift: float
    #: Share of ALL events that fall in this decile and the ones above it.
    cumulative_capture_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "decile": self.decile,
            "facilities": self.facilities,
            "events": self.events,
            "rate_pct": round(self.rate_pct, 3),
            "lift": round(self.lift, 3),
            "cumulative_capture_pct": round(self.cumulative_capture_pct, 2),
        }


def deciles(scores: np.ndarray, outcome: np.ndarray) -> list[DecileRow]:
    """The book split into ten equal groups, worst-scoring first."""
    n = len(scores)
    if n < 10:
        return []
    order = np.argsort(-scores, kind="mergesort")
    ranked = outcome[order]
    total_events = float(ranked.sum())
    overall = total_events / n if n else 0.0

    rows: list[DecileRow] = []
    seen = 0.0
    edges = np.linspace(0, n, 11).astype(int)
    for i in range(10):
        chunk = ranked[edges[i]:edges[i + 1]]
        events = float(chunk.sum())
        seen += events
        size = max(len(chunk), 1)
        rate = events / size
        rows.append(DecileRow(
            decile=i + 1,
            facilities=len(chunk),
            events=int(events),
            rate_pct=100.0 * rate,
            lift=(rate / overall) if overall > 0 else float("nan"),
            cumulative_capture_pct=(100.0 * seen / total_events) if total_events else 0.0,
        ))
    return rows


@dataclass
class BandRow:
    band: str
    facilities: int
    events: int
    predicted_pct: float
    observed_pct: float

    @property
    def gap_pp(self) -> float:
        return self.observed_pct - self.predicted_pct

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "facilities": self.facilities,
            "events": self.events,
            "predicted_pct": round(self.predicted_pct, 3),
            "observed_pct": round(self.observed_pct, 3),
            "gap_pp": round(self.gap_pp, 3),
        }


def calibration(probabilities: np.ndarray, outcome: np.ndarray) -> list[BandRow]:
    """Predicted against observed, by score band."""
    percent = 100.0 * probabilities
    labels = np.array([band_for(p) for p in percent])
    rows: list[BandRow] = []
    for band, _ in BANDS:
        mask = labels == band
        count = int(mask.sum())
        if count == 0:
            continue
        rows.append(BandRow(
            band=band,
            facilities=count,
            events=int(outcome[mask].sum()),
            predicted_pct=float(percent[mask].mean()),
            observed_pct=100.0 * float(outcome[mask].mean()),
        ))
    return rows


@dataclass
class PeriodResult:
    period: str
    facilities: int
    events: int
    auc: float
    ks: float
    top_decile_capture_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "facilities": self.facilities,
            "events": self.events,
            "auc": None if np.isnan(self.auc) else round(self.auc, 4),
            "ks": None if np.isnan(self.ks) else round(self.ks, 4),
            "top_decile_capture_pct": round(self.top_decile_capture_pct, 2),
        }


@dataclass
class BacktestResult:
    """What an out-of-time test found. Evidence, not a validation."""

    target_id: str
    fitted_periods: list[str]
    tested_periods: list[str]
    facilities: int
    events: int
    base_rate_pct: float
    auc: float
    ks: float
    deciles: list[DecileRow] = field(default_factory=list)
    calibration: list[BandRow] = field(default_factory=list)
    by_period: list[PeriodResult] = field(default_factory=list)

    @property
    def top_decile_capture_pct(self) -> float:
        return self.deciles[0].cumulative_capture_pct if self.deciles else 0.0

    @property
    def verdict(self) -> str:
        """A sentence about what the numbers mean. Deliberately unflattering.

        A prototype that ranks well is still a prototype, and the sentence says
        so every time rather than only when the numbers are poor.
        """
        if np.isnan(self.auc):
            return (
                "There were no transitions in the test window, so nothing about "
                "this model's discrimination has been established."
            )
        if self.auc < 0.60:
            quality = (
                "barely better than chance. On this evidence the factor set is "
                "not capturing what drives these migrations"
            )
        elif self.auc < 0.70:
            quality = "modest — the ordering is real but weak"
        elif self.auc < 0.80:
            quality = "reasonable for a first specification"
        else:
            quality = "strong on this data, which is synthetic and generated with a known structure"
        return (
            f"Out of time, on {self.facilities:,} facilities it never saw, the "
            f"signal separates migrations from non-migrations with an AUC of "
            f"{self.auc:.3f} — {quality}. The worst-scoring tenth of the book "
            f"contains {self.top_decile_capture_pct:.0f}% of the quarter's "
            f"transitions. This is a prototype result on synthetic data and is "
            f"not a validation."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "fitted_periods": self.fitted_periods,
            "tested_periods": self.tested_periods,
            "facilities": self.facilities,
            "events": self.events,
            "base_rate_pct": round(self.base_rate_pct, 4),
            "auc": None if np.isnan(self.auc) else round(self.auc, 4),
            "ks": None if np.isnan(self.ks) else round(self.ks, 4),
            "top_decile_capture_pct": round(self.top_decile_capture_pct, 2),
            "deciles": [d.to_dict() for d in self.deciles],
            "calibration": [c.to_dict() for c in self.calibration],
            "by_period": [p.to_dict() for p in self.by_period],
            "verdict": self.verdict,
            "is_validation": False,
        }


__all__ = [
    "BacktestResult",
    "BandRow",
    "DecileRow",
    "PeriodResult",
    "auc",
    "calibration",
    "deciles",
    "ks",
]
