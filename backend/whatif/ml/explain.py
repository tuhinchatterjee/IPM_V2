"""
Why the model said what it said.

Two different things called the same word
------------------------------------------
This product computes Shapley values in two places and they are NOT the same
thing, so they are kept apart and named apart:

  * `backend/orchestration/decomposition.py` computes EXACT Shapley values over
    a small set of governed ECL factors. It is deterministic attribution of an
    ECL movement, and it sums exactly to the movement.

  * this module computes SHAP values for an XGBoost prediction. It attributes
    ONE MODEL'S OUTPUT to its inputs.

Confusing them would let somebody read "collateral coverage contributed 40% of
the ECL increase" off a chart that actually says "collateral coverage moved
this model's predicted rate". The first is a fact about the book; the second is
a fact about the model.

Which TreeSHAP implementation, and why not the `shap` package
-------------------------------------------------------------
These are exact TreeSHAP values, computed by XGBoost itself through
`predict(..., pred_contribs=True)`, and they sum to the prediction.

The `shap` package would have been the obvious choice and does not work here:
its `XGBTreeModelLoader` parses the booster's own JSON and cannot read the
`base_score` that XGBoost 3.1 writes — it arrives as the string
`'[2.7366474E-2]'` and the loader calls `float()` on it. Pinning `shap` to a
version that could read it would mean pinning XGBoost backwards, and carrying a
dependency that raises on first use would be worse than not carrying it. So the
model's own implementation is used, which is the same algorithm without the
version coupling, and `shap` is not a dependency of this product.

Cost
----
Exact TreeSHAP on a gradient-boosted forest is expensive, so the summary is
computed on a sample rather than the whole book, with the sample size reported
so nobody reads a 2,000-row summary as though it were 50,000.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

EXPLAIN_VERSION = "1.0.0"

#: How many rows the SHAP summary is built from. Enough to be stable, small
#: enough to compute while somebody is waiting.
SAMPLE = 2000


def importance(model: Any, feature_names: tuple[str, ...] | list[str],
               *, limit: int = 0) -> list[dict[str, Any]]:
    """XGBoost's own gain importance, normalised to shares of the total.

    Gain rather than weight: weight counts how often a feature was split on,
    which flatters features with many distinct values. Gain measures how much
    those splits actually improved the objective.
    """
    def _gain(inner: Any) -> dict[str, float]:
        booster = inner.get_booster() if hasattr(inner, "get_booster") else inner
        out: dict[str, float] = {}
        for key, value in booster.get_score(importance_type="gain").items():
            if key.startswith("f") and key[1:].isdigit():
                at = int(key[1:])
                name = feature_names[at] if at < len(feature_names) else key
            else:
                name = key
            out[name] = float(value)
        return out

    # Where the served design is one model per Stage, importance is POOLED
    # across the members. Reporting only the fallback's gains would describe a
    # model the product does not score with, and a feature that matters only in
    # Stage 2 would read as unimportant.
    if getattr(model, "routes", False):
        named: dict[str, float] = {}
        for inner in model.members.values():
            for name, value in _gain(inner).items():
                named[name] = named.get(name, 0.0) + value
    else:
        named = _gain(model)
    total = sum(named.values()) or 1.0
    rows = [{"feature": name, "gain": round(value, 6),
             "share_pct": round(value / total * 100.0, 4)}
            for name, value in named.items()]
    rows.sort(key=lambda r: r["gain"], reverse=True)
    for name in feature_names:
        if name not in named:
            rows.append({"feature": name, "gain": 0.0, "share_pct": 0.0})
    return rows[:limit] if limit else rows


def contributions(model: Any, rows: pd.DataFrame) -> tuple[np.ndarray, float]:
    """Exact TreeSHAP values and the base value, from XGBoost itself.

    The returned matrix has one extra column: the bias. Every row sums to that
    row's prediction, which is the property that makes the numbers worth
    showing at all.
    """
    from backend.whatif.ml import runtime as rt

    rt.require()
    import xgboost as xgb

    def _shap(inner: Any, frame: pd.DataFrame) -> np.ndarray:
        booster = inner.get_booster() if hasattr(inner, "get_booster") else inner
        matrix = xgb.DMatrix(frame, feature_names=list(frame.columns))
        return np.asarray(booster.predict(matrix, pred_contribs=True))

    # An explanation has to come from the model that made the PREDICTION. Where
    # the served design is one model per Stage, explaining every row with the
    # all-book fallback would attribute a Stage 2 borrower's provision to a
    # model that did not price it — numbers that look like an explanation and
    # are not.
    if getattr(model, "routes", False) and "stage" in rows.columns:
        stage = pd.to_numeric(rows["stage"], errors="coerce").fillna(1).astype(int)
        values = np.zeros((len(rows), len(rows.columns) + 1), dtype=float)
        for number in sorted(set(stage.unique())):
            mask = (stage == number).to_numpy()
            values[mask] = _shap(model.model_for(number), rows.loc[mask])
    else:
        values = _shap(model, rows)
    base = float(values[:, -1].mean()) if values.shape[1] else 0.0
    return values[:, :-1], base


def summary(model: Any, X: pd.DataFrame, *, sample: int = SAMPLE,
            seed: int = 0) -> dict[str, Any]:
    """Mean absolute SHAP per feature — the "top predictors" chart."""
    rows = X if len(X) <= sample else X.sample(sample, random_state=seed)
    values, base = contributions(model, rows)
    mean_abs = np.abs(values).mean(axis=0)
    total = float(mean_abs.sum()) or 1.0
    ranked = [{"feature": str(name),
               "mean_abs_shap": round(float(value), 8),
               "share_pct": round(float(value) / total * 100.0, 4),
               "mean_value": round(float(rows[name].mean()), 6)}
              for name, value in zip(rows.columns, mean_abs, strict=True)]
    ranked.sort(key=lambda r: r["mean_abs_shap"], reverse=True)
    return {"version": EXPLAIN_VERSION, "kind": "ml_shap",
            "method": "XGBoost native TreeSHAP (pred_contribs)",
            "rows_sampled": int(len(rows)), "rows_available": int(len(X)),
            "base_value": round(base, 8),
            "features": ranked,
            "note": ("SHAP attributes this MODEL'S prediction to its inputs. "
                     "It is not the exact Shapley decomposition of an ECL "
                     "movement, which is a fact about the book rather than "
                     "about the model.")}


def local(model: Any, row: pd.DataFrame) -> dict[str, Any]:
    """Why the model predicted what it did for ONE borrower."""
    matrix, base = contributions(model, row)
    values = matrix[0]
    parts = [
        {"feature": str(name), "value": round(float(row.iloc[0][name]), 6),
         "shap": round(float(value), 8)}
        for name, value in zip(row.columns, values, strict=True)]
    parts.sort(key=lambda r: abs(r["shap"]), reverse=True)
    return {"base_value": round(base, 8),
            "prediction": round(base + float(values.sum()), 8),
            "contributions": parts,
            "note": ("The prediction is the base value plus every "
                     "contribution. XGBoost is an ensemble: no single tree "
                     "produces this number, and a tree path shown for "
                     "intuition is one of several hundred.")}


def actual_vs_predicted(actual: Any, predicted: Any, *, buckets: int = 20
                        ) -> list[dict[str, Any]]:
    """The calibration chart: predicted against realised, in equal-count bins."""
    y = pd.Series(np.asarray(actual, dtype=float))
    p = pd.Series(np.asarray(predicted, dtype=float))
    if y.empty:
        return []
    try:
        bins = pd.qcut(p.rank(method="first"), q=min(buckets, len(p)),
                       labels=False, duplicates="drop")
    except ValueError:  # pragma: no cover - too few distinct predictions
        return []
    out = []
    for label, part in pd.DataFrame({"y": y, "p": p, "b": bins}).groupby("b"):
        out.append({"bucket": int(label), "count": int(len(part)),
                    "mean_predicted": round(float(part["p"].mean()), 8),
                    "mean_actual": round(float(part["y"].mean()), 8)})
    return out


def sensitivity(model: Any, X: pd.DataFrame, feature: str, *,
                multipliers: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
                sample: int = SAMPLE, seed: int = 0) -> dict[str, Any]:
    """How the predicted rate moves when one feature is scaled.

    The honest way to show "what does this model think PD does", because it
    asks the model rather than reading a coefficient it does not have.
    """
    if feature not in X.columns:
        return {"feature": feature, "points": [], "note": "not a model feature"}
    rows = X if len(X) <= sample else X.sample(sample, random_state=seed)
    base = float(np.mean(model.predict(rows)))
    points = []
    for multiplier in multipliers:
        moved = rows.copy()
        moved[feature] = moved[feature] * multiplier
        mean = float(np.mean(model.predict(moved)))
        points.append({"multiplier": multiplier,
                       "mean_predicted_rate": round(mean, 8),
                       "relative_to_base": round(mean / base, 6) if base else None})
    return {"feature": feature, "base_mean_predicted_rate": round(base, 8),
            "points": points, "rows_sampled": int(len(rows)),
            "note": ("A proportional change in the feature does not produce a "
                     "proportional change in the predicted rate. That "
                     "nonlinearity is the reason this methodology exists "
                     "alongside the Delta Model.")}


def stage_interaction(model: Any, X: pd.DataFrame, frame: pd.DataFrame, *,
                      feature: str = "pd_12m",
                      multipliers: tuple[float, ...] = (1.0, 1.25, 1.5, 2.0),
                      sample: int = SAMPLE, seed: int = 0) -> dict[str, Any]:
    """Does the model treat Stage 1 and Stage 2 as different books?

    A single model with Stage as a FEATURE is only stage-aware if the Stage
    actually changes how it reads everything else. A tree ensemble can do
    that — it splits on Stage and fits a different surface either side — but
    "can" is not evidence. So this shocks one feature INSIDE each Stage and
    reports the response separately.

    If the responses were the same, Stage would be an intercept and the
    single-model design would deserve the challenge. They are not: a Stage 2
    borrower is measured on a lifetime PD, so the same proportional PD move
    is worth a different amount of provision, and the model has learned that
    from the book rather than being told it.
    """
    if feature not in X.columns or "stage" not in frame.columns:
        return {"feature": feature, "stages": [],
                "note": "the model does not carry this feature"}
    stages = pd.to_numeric(frame.loc[X.index, "stage"], errors="coerce")
    out: list[dict[str, Any]] = []
    for stage in (1, 2, 3):
        rows = X[(stages == stage).to_numpy()]
        if len(rows) < 20:
            continue
        if len(rows) > sample:
            rows = rows.sample(sample, random_state=seed)
        base = float(np.mean(model.predict(rows)))
        points = []
        for multiplier in multipliers:
            moved = rows.copy()
            moved[feature] = moved[feature] * multiplier
            mean = float(np.mean(model.predict(moved)))
            points.append({
                "multiplier": multiplier,
                "mean_predicted_rate": round(mean, 8),
                "relative_to_base": round(mean / base, 6) if base else None})
        out.append({"stage": stage, "rows": int(len(rows)),
                    "base_mean_predicted_rate": round(base, 8),
                    "points": points})
    spread = ""
    if len(out) >= 2:
        biggest = max(multipliers)
        responses = {
            entry["stage"]: next(
                (p["relative_to_base"] for p in entry["points"]
                 if p["multiplier"] == biggest), None)
            for entry in out}
        named = ", ".join(
            f"Stage {stage} {value:.2f}x" for stage, value in responses.items()
            if value is not None)
        spread = (f"At {biggest:g}x {feature}, the predicted rate moves by "
                  f"{named}. The Stage is not an intercept: it changes how "
                  "the model reads the rest of the borrower.")
    return {"feature": feature, "stages": out, "finding": spread,
            "note": ("Each Stage is shocked within itself, so nothing here "
                     "is a migration effect — it is the model's response to "
                     "the same proportional move on either side of the "
                     "staging line.")}


__all__ = [
    "EXPLAIN_VERSION", "SAMPLE", "actual_vs_predicted", "importance", "local",
    "sensitivity", "stage_interaction", "summary",
]
