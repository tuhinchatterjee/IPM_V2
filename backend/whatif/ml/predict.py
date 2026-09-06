"""
Using the model on a scenario, and the anchoring that keeps the book honest.

The anchoring rule, and why it is not optional
-----------------------------------------------
The model predicts an ECL RATE. It would be easy — and wrong — to multiply that
rate by exposure and call it the What-If ECL, because then the BASELINE would
also come from the model, and the baseline is supposed to be the number the
bank reported. A model that is 3% out would restate the book by 3% before any
scenario was applied, and every conversation would start by arguing about a
figure nobody asked to change.

So the model is used only for the RATIO:

    baseline_rate = model(features as reported)
    shocked_rate  = model(features under the scenario)
    ML factor     = shocked_rate / baseline_rate
    What-If ECL   = REPORTED ECL x ML factor

The reported ECL, management overlay and all, stays the anchor. The model's
absolute level cancels, so a systematic bias in it cannot move the baseline —
only its RESPONSE to the shock survives, which is the only thing it was brought
in to supply.

Where the ratio cannot be formed
--------------------------------
A borrower the model prices at essentially zero has no ratio: dividing by it
produces a number with no meaning and a spectacular magnitude. Those rows fall
back to the Delta factor, and the count is reported rather than absorbed. A
fallback nobody is told about is indistinguishable from a bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.whatif.ml import features as ft
from backend.whatif.ml import registry as rg

PREDICT_VERSION = "1.0.0"

#: A predicted rate below this is treated as unpriceable rather than divided by.
FLOOR = 1e-6

#: How far outside the training range a feature may go before the answer says so.
OOD_TOLERANCE = 0.02


class PredictionError(ValueError):
    """A prediction that must not be made."""


@dataclass
class MLResult:
    """What the ML methodology produced, and how much of it to trust."""

    factors: pd.Series
    baseline_rate: pd.Series
    shocked_rate: pd.Series
    fell_back: int = 0
    out_of_distribution: list[dict[str, Any]] = field(default_factory=list)
    model_version: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def in_distribution(self) -> bool:
        return not self.out_of_distribution

    def to_dict(self) -> dict[str, Any]:
        return {"model_version": self.model_version,
                "rows": int(len(self.factors)),
                "mean_factor": round(float(self.factors.mean()), 6)
                if len(self.factors) else 1.0,
                "fell_back_to_delta": self.fell_back,
                "out_of_distribution": self.out_of_distribution,
                "in_distribution": self.in_distribution,
                "warnings": list(self.warnings)}


def _shocked_frame(work: pd.DataFrame) -> pd.DataFrame:
    """The book as the scenario leaves it, in the columns the model reads.

    The engine writes its results into `*_stressed` columns. The model was
    trained on the plain names, so the stressed values are copied over them —
    on a COPY, so nothing downstream sees a book that has been quietly
    overwritten.
    """
    moved = work.copy()
    for stressed, plain in (("pd_stressed", "pd_12m"),
                            ("lgd_stressed", "lgd"),
                            ("ead_stressed", "ead"),
                            ("stage_stressed", "stage"),
                            ("ccf_stressed", "ccf")):
        if stressed in moved.columns:
            moved[plain] = moved[stressed]
    # The lifetime PD follows the twelve-month PD under a shock; the governed
    # extension is the same one the measurement uses.
    if "pd_stressed" in moved.columns:
        from backend.ifrs9 import policy

        moved["pd_lifetime"] = policy.lifetime_pd(
            pd.to_numeric(moved["pd_stressed"], errors="coerce").fillna(0.0) / 100.0
        ) * 100.0
    if "notches_moved" in moved.columns:
        moved["rating_change_notches"] = moved["notches_moved"]
    return moved


def _check_distribution(matrix: ft.Matrix, ranges: dict[str, Any]
                        ) -> list[dict[str, Any]]:
    """Which shocked features have left the range the model was trained on.

    Reported per feature with how far outside, because "the model is less
    certain" is not actionable and "the shocked lifetime PD is above anything
    seen in development" is.
    """
    out: list[dict[str, Any]] = []
    for name in matrix.X.columns:
        band = ranges.get(name)
        if not band:
            continue
        low, high = float(band.get("min", 0.0)), float(band.get("max", 0.0))
        span = (high - low) or 1.0
        values = matrix.X[name]
        above = float((values > high + span * OOD_TOLERANCE).mean())
        below = float((values < low - span * OOD_TOLERANCE).mean())
        if above > 0.01 or below > 0.01:
            out.append({
                "feature": name,
                "share_above_pct": round(above * 100.0, 2),
                "share_below_pct": round(below * 100.0, 2),
                "trained_range": [round(low, 6), round(high, 6)],
                "shocked_max": round(float(values.max()), 6),
                "shocked_min": round(float(values.min()), 6),
                "message": (
                    f"{max(above, below) * 100:.1f}% of the shocked population "
                    f"has {name} outside the range this model was developed on "
                    f"({low:.4g} to {high:.4g}). ML uncertainty is higher here; "
                    "the Delta Model is a useful comparison.")})
    return out


def factors(work: pd.DataFrame, *, version: str = "",
            delta_factors: pd.Series | None = None) -> MLResult:
    """The ML shock factor per borrower.

    `work` is the engine's frame after every shock has been applied, so it
    carries both the reported columns and the `*_stressed` ones.
    """
    chosen = version or rg.active_version()
    if not chosen:
        raise PredictionError(
            "No ML model has been activated, so the ML methodology cannot be "
            "used. Train and activate one, or choose the Delta Model.")
    model = rg.load_booster(chosen)
    stored = rg.card(chosen)
    encoding = ft.Encoding.from_dict(stored.encoding)

    baseline_matrix = ft.build(work, encoding=encoding)
    shocked_matrix = ft.build(_shocked_frame(work), encoding=encoding)
    if baseline_matrix.rows != shocked_matrix.rows:  # pragma: no cover
        raise PredictionError(
            "The baseline and shocked populations differ in size, so a "
            "per-borrower ratio cannot be formed.")

    base = pd.Series(model.predict(baseline_matrix.X), index=baseline_matrix.X.index)
    moved = pd.Series(model.predict(shocked_matrix.X), index=shocked_matrix.X.index)
    base = base.clip(lower=0.0)
    moved = moved.clip(lower=0.0)

    usable = base > FLOOR
    factor = pd.Series(np.ones(len(base)), index=base.index)
    factor[usable] = moved[usable] / base[usable]

    fell_back = int((~usable).sum())
    warnings: list[str] = []
    if fell_back and delta_factors is not None:
        aligned = delta_factors.reindex(factor.index)
        factor[~usable] = aligned[~usable].fillna(1.0)
        warnings.append(
            f"{fell_back:,} borrower(s) are priced by the model at effectively "
            "zero, so no ML ratio could be formed. The Delta factor was used "
            "for those rows.")
    elif fell_back:
        warnings.append(
            f"{fell_back:,} borrower(s) are priced by the model at effectively "
            "zero and were left unchanged.")

    result = MLResult(factors=factor, baseline_rate=base, shocked_rate=moved,
                      fell_back=fell_back, model_version=chosen,
                      warnings=warnings)
    result.out_of_distribution = _check_distribution(shocked_matrix, stored.ranges)
    for entry in result.out_of_distribution:
        warnings.append(entry["message"])
    return result


def apply(work: pd.DataFrame, *, version: str = "",
          reported: str = "final_ecl",
          delta_factors: pd.Series | None = None) -> tuple[pd.DataFrame, MLResult]:
    """The ML methodology applied: reported ECL moved by the model's ratio."""
    result = factors(work, version=version, delta_factors=delta_factors)
    out = work.copy()
    aligned = result.factors.reindex(out.index).fillna(1.0)
    baseline = pd.to_numeric(out.get(reported), errors="coerce").fillna(0.0)
    out["ml_factor"] = aligned
    out["ml_baseline_rate"] = result.baseline_rate.reindex(out.index)
    out["ml_shocked_rate"] = result.shocked_rate.reindex(out.index)
    out["ecl_baseline"] = baseline
    out["ecl_stressed"] = baseline * aligned
    out["ecl_increase"] = out["ecl_stressed"] - out["ecl_baseline"]
    out["ecl_increase_pct"] = np.where(
        baseline > 0, out["ecl_increase"] / baseline.replace(0, np.nan) * 100.0, 0.0)
    return out, result


def one(features: dict[str, Any], *, version: str = "") -> dict[str, Any]:
    """Score a single made-up borrower — the worked example on the ML page."""
    chosen = version or rg.active_version()
    if not chosen:
        raise PredictionError("No ML model has been activated.")
    model = rg.load_booster(chosen)
    stored = rg.card(chosen)
    encoding = ft.Encoding.from_dict(stored.encoding)
    frame = pd.DataFrame([features])
    matrix = ft.build(frame, encoding=encoding)
    if matrix.rows == 0:
        raise PredictionError(
            "That borrower has no exposure, so it has no ECL rate to predict.")
    rate = float(model.predict(matrix.X)[0])
    return {"model_version": chosen, "predicted_rate": round(rate, 8),
            "features": matrix.X.iloc[0].to_dict()}


__all__ = [
    "FLOOR", "MLResult", "OOD_TOLERANCE", "PREDICT_VERSION",
    "PredictionError", "apply", "factors", "one",
]
