"""
The retail scorecards: application and behavioural, and the arithmetic that
lets a risk officer take one row apart.

A scorecard here is a *specification*, not a fitted artefact with hidden
weights. Each model declares its features, the bin boundaries, the weight of
evidence attached to every bin including the missing bin, a coefficient per
feature, an intercept, and the points scaling. From those, and only those, the
row's transformed values, points, log-odds, predicted probability, score and
band are all recomputed. That is what makes "reconstruct this customer's score
from its raw inputs" a calculation rather than a promise.

Conventions, stated once because half the bugs in scorecard code are a sign:

* Weight of evidence is `ln(P(good in bin) / P(bad in bin))`, so **higher WoE is
  safer**.
* `logit = intercept - sum(coef * woe)` is the log-odds of the BAD outcome, so a
  safer row has a lower logit.
* `score = offset - factor * logit`, so **higher score is lower default risk**.
  `score_direction` records that, and every metric that needs an orientation
  reads it rather than guessing from the data.
* `points = factor * coef * woe`, and `score = base_points + sum(points)`
  exactly. If that identity fails, the row is wrong, not the test.

Every model, bin boundary and coefficient below is SYNTHETIC. They are not
ANB's scorecards, not a bureau's scorecard, and the score range is a
demonstration scale rather than a claim about any real one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backend.retail.taxonomy import (
    AUTO_LOAN, CREDIT_CARD, HOME_LOAN, PERSONAL_LOAN, PRODUCT_CODES,
)

APPLICATION_MODEL_PREFIX = "app"
BEHAVIOURAL_MODEL_PREFIX = "beh"

#: Higher score = lower risk. Recorded on every row and read by every metric.
SCORE_DIRECTION = "HIGHER_IS_SAFER"

MISSING_BIN = "MISSING"

# --------------------------------------------------------------------------
# Points scaling — the demonstration scale.
# --------------------------------------------------------------------------

BASE_SCORE = 600.0
#: Good:bad odds at the base score.
BASE_ODDS_GOOD = 30.0
#: Points to double the odds.
PDO = 40.0

FACTOR = PDO / math.log(2.0)
OFFSET = BASE_SCORE - FACTOR * math.log(BASE_ODDS_GOOD)

SCORE_MIN, SCORE_MAX = 300.0, 900.0

#: Score bands. Fixed cut points on the demonstration scale, shared by both
#: scorecards so a band means the same thing on either.
SCORE_BAND_EDGES: tuple[float, ...] = (540.0, 580.0, 620.0, 660.0, 700.0)
SCORE_BAND_LABELS: tuple[str, ...] = ("E", "D", "C", "B", "A", "A+")


def score_band(score: float | None) -> str | None:
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return None
    for i, edge in enumerate(SCORE_BAND_EDGES):
        if score < edge:
            return SCORE_BAND_LABELS[i]
    return SCORE_BAND_LABELS[-1]


def score_band_array(scores: np.ndarray) -> np.ndarray:
    out = np.full(scores.shape, SCORE_BAND_LABELS[-1], dtype=object)
    for i in range(len(SCORE_BAND_EDGES) - 1, -1, -1):
        out = np.where(scores < SCORE_BAND_EDGES[i], SCORE_BAND_LABELS[i], out)
    out = np.where(np.isnan(scores), None, out)
    return out


# --------------------------------------------------------------------------
# Feature specification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Feature:
    """One model input, with everything needed to transform and explain it.

    `short` is the flattened column prefix: a feature named `income` on the
    application model produces `app_income_raw`, `app_income_transformed`,
    `app_income_bin`, `app_income_missing_flag` and `app_income_points`.
    """

    short: str
    source: str  # canonical column the raw value is read from
    business_name: str
    kind: str  # "numeric" | "categorical"
    coefficient: float
    #: numeric: ascending upper edges, len(labels) == len(edges) + 1
    edges: tuple[float, ...] = ()
    labels: tuple[str, ...] = ()
    #: WoE per bin label. Higher is safer.
    woe: dict[str, float] = field(default_factory=dict)
    #: WoE applied when the raw value is absent. Missing is not automatically
    #: benign: these are deliberately set at or below the population average.
    woe_missing: float = -0.25
    unit: str | None = None
    definition: str = ""

    def __post_init__(self) -> None:
        if self.kind == "numeric":
            if len(self.labels) != len(self.edges) + 1:
                raise ValueError(
                    f"{self.short}: {len(self.labels)} labels for {len(self.edges)} edges; "
                    "a numeric feature needs exactly one more label than edges"
                )
            if list(self.edges) != sorted(self.edges):
                raise ValueError(f"{self.short}: bin edges are not ascending")
        missing_woe = set(self.labels) - set(self.woe)
        if missing_woe:
            raise ValueError(f"{self.short}: no WoE for bins {sorted(missing_woe)}")

    # -- transformation ----------------------------------------------------

    def bin_of(self, values: pd.Series) -> np.ndarray:
        """Bin label per row; `MISSING_BIN` where the raw value is absent."""
        if self.kind == "numeric":
            v = pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64")
            idx = np.searchsorted(np.asarray(self.edges, dtype="float64"), v, side="right")
            idx = np.clip(idx, 0, len(self.labels) - 1)
            out = np.asarray(self.labels, dtype=object)[idx]
            return np.where(np.isnan(v), MISSING_BIN, out)
        v = values.astype(object).to_numpy()
        known = set(self.labels)
        return np.array(
            [x if (x is not None and x == x and x in known) else MISSING_BIN for x in v],
            dtype=object,
        )

    def woe_of(self, bins: np.ndarray) -> np.ndarray:
        lookup = dict(self.woe)
        lookup[MISSING_BIN] = self.woe_missing
        return np.array([lookup[b] for b in bins], dtype="float64")

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.short,
            "source_column": self.source,
            "business_name": self.business_name,
            "kind": self.kind,
            "unit": self.unit,
            "definition": self.definition,
            "coefficient": self.coefficient,
            "bin_edges": list(self.edges),
            "bins": list(self.labels),
            "woe": dict(self.woe),
            "woe_missing": self.woe_missing,
        }


@dataclass(frozen=True)
class Scorecard:
    """A complete, reconstructable model specification."""

    model_id: str
    model_version: str
    transform_version: str
    prefix: str  # "app" | "beh"
    product_code: str
    subject_grain: str  # "facility" | "customer"
    target_event: str
    horizon_months: int
    target_definition_id: str
    intercept: float
    features: tuple[Feature, ...]
    description: str = ""

    @property
    def base_points(self) -> float:
        return OFFSET - FACTOR * self.intercept

    def column_names(self) -> list[str]:
        out: list[str] = []
        for f in self.features:
            out += [
                f"{self.prefix}_{f.short}_raw",
                f"{self.prefix}_{f.short}_transformed",
                f"{self.prefix}_{f.short}_bin",
                f"{self.prefix}_{f.short}_missing_flag",
                f"{self.prefix}_{f.short}_points",
            ]
        return out

    def required_sources(self) -> list[str]:
        return [f.source for f in self.features]

    # -- scoring -----------------------------------------------------------

    def score_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """Flattened per-feature columns plus logit, PD, score and band.

        Returned as a separate frame with the caller's index so the canonical
        table is assembled once, explicitly, rather than mutated in place by
        five different functions.
        """
        n = len(df)
        out = pd.DataFrame(index=df.index)
        logit = np.full(n, self.intercept, dtype="float64")
        points_total = np.zeros(n, dtype="float64")
        missing_count = np.zeros(n, dtype="int32")

        for f in self.features:
            if f.source not in df.columns:
                raise KeyError(
                    f"model {self.model_id} needs '{f.source}' for feature "
                    f"'{f.short}' and the canonical frame does not carry it"
                )
            raw = df[f.source]
            bins = f.bin_of(raw)
            woe = f.woe_of(bins)
            miss = (bins == MISSING_BIN)
            pts = FACTOR * f.coefficient * woe

            p = self.prefix
            out[f"{p}_{f.short}_raw"] = (
                pd.to_numeric(raw, errors="coerce") if f.kind == "numeric" else raw.astype(object)
            )
            out[f"{p}_{f.short}_transformed"] = woe
            out[f"{p}_{f.short}_bin"] = bins
            out[f"{p}_{f.short}_missing_flag"] = miss
            out[f"{p}_{f.short}_points"] = pts

            logit -= f.coefficient * woe
            points_total += pts
            missing_count += miss.astype("int32")

        score = np.clip(OFFSET - FACTOR * logit, SCORE_MIN, SCORE_MAX)
        pd_hat = 1.0 / (1.0 + np.exp(-logit))

        out[f"{self.prefix}_score_logit"] = logit
        out[f"{self.prefix}_score_base_points"] = self.base_points
        out[f"{self.prefix}_score_points_total"] = points_total
        out[f"{self.prefix}_score_unclipped"] = OFFSET - FACTOR * logit
        out[f"{self.prefix}_score_value"] = score
        out[f"{self.prefix}_predicted_pd_12m"] = pd_hat
        out[f"{self.prefix}_score_band_value"] = score_band_array(score)
        out[f"{self.prefix}_input_missing_count"] = missing_count
        return out

    def reconstruct(self, row: pd.Series) -> dict[str, Any]:
        """Re-derive one row's score from its stored raw inputs.

        Used by the reconciliation gate and by the Cockpit answer that shows a
        customer the raw input, the transformation and the points behind their
        score.
        """
        frame = self.score_frame(pd.DataFrame([row]))
        got = frame.iloc[0]
        contributions = [
            {
                "feature": f.short,
                "business_name": f.business_name,
                "raw": got[f"{self.prefix}_{f.short}_raw"],
                "bin": got[f"{self.prefix}_{f.short}_bin"],
                "transformed_woe": float(got[f"{self.prefix}_{f.short}_transformed"]),
                "coefficient": f.coefficient,
                "points": float(got[f"{self.prefix}_{f.short}_points"]),
                "missing": bool(got[f"{self.prefix}_{f.short}_missing_flag"]),
            }
            for f in self.features
        ]
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "transform_version": self.transform_version,
            "target_event": self.target_event,
            "horizon_months": self.horizon_months,
            "score_direction": SCORE_DIRECTION,
            "base_points": self.base_points,
            "contributions": contributions,
            "points_total": float(got[f"{self.prefix}_score_points_total"]),
            "logit": float(got[f"{self.prefix}_score_logit"]),
            "predicted_pd_12m": float(got[f"{self.prefix}_predicted_pd_12m"]),
            "score": float(got[f"{self.prefix}_score_value"]),
            "score_unclipped": float(got[f"{self.prefix}_score_unclipped"]),
            "score_band": got[f"{self.prefix}_score_band_value"],
            "scale": {
                "base_score": BASE_SCORE, "base_odds_good": BASE_ODDS_GOOD, "pdo": PDO,
                "factor": FACTOR, "offset": OFFSET,
                "note": "Synthetic demonstration scale. Not a real scorecard's range.",
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "transform_version": self.transform_version,
            "prefix": self.prefix,
            "product_code": self.product_code,
            "subject_grain": self.subject_grain,
            "target_event": self.target_event,
            "horizon_months": self.horizon_months,
            "target_definition_id": self.target_definition_id,
            "score_direction": SCORE_DIRECTION,
            "intercept": self.intercept,
            "base_points": self.base_points,
            "scaling": {"base_score": BASE_SCORE, "base_odds_good": BASE_ODDS_GOOD, "pdo": PDO,
                        "factor": FACTOR, "offset": OFFSET,
                        "score_min": SCORE_MIN, "score_max": SCORE_MAX},
            "score_bands": {"edges": list(SCORE_BAND_EDGES), "labels": list(SCORE_BAND_LABELS)},
            "features": [f.to_dict() for f in self.features],
            "description": self.description,
            "is_synthetic": True,
        }
