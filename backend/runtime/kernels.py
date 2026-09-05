"""
The allowlisted numerical kernels.

The rule
--------
The language model never sends code. It sends the *name* of an operation and its
parameters, and this module decides whether such an operation exists and runs the
implementation the bank has approved. There is no `eval`, no `exec`, no import by
name, no filesystem and no network anywhere in the path.

That distinction is the whole point. A product that lets a model write Python
against the credit book has to trust the model on every request forever. A
product that lets it choose from a list has to trust the list, once, and the list
is reviewable.

Where kernels sit
-----------------
A kernel never sees the raw book. It runs on the *result* of the SQL that
precedes it — a few thousand rows at most, already filtered and aggregated by
DuckDB. That ordering matters for performance, but it matters more for
governance: the population a statistic describes was selected by a validated
plan, and the Trace shows the selection above the statistic.

What is deliberately missing
----------------------------
No clustering, no neural anything, no automatic feature selection. Those produce
numbers a credit committee cannot interrogate, and this phase has no validation
framework behind them. When one exists they can be added here, one function at a
time, each with its own tests.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.runtime.ir import Operation, OpType, PlanError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Kernel:
    """One approved numerical operation."""

    name: str
    summary: str
    #: The columns it adds to the result, so validation can carry the schema.
    outputs: tuple[str, ...]
    run: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]
    #: What it does NOT tell you. Shown beside the result, because a statistic
    #: without its caveat is how a correlation becomes a cause.
    limitations: str = ""


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise PlanError(f"The kernel needs a column called '{column}'.")
    return pd.to_numeric(frame[column], errors="coerce")


# ---------------------------------------------------------------- correlation


def _correlation(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Pearson or Spearman between two columns, with n and a caveat."""
    x_name = str(params.get("x") or "")
    y_name = str(params.get("y") or "")
    method = str(params.get("method") or "pearson").lower()
    if method not in ("pearson", "spearman", "kendall"):
        raise PlanError(
            f"'{method}' is not a correlation the runtime computes. Use pearson, "
            "spearman or kendall."
        )

    pair = pd.DataFrame({"x": _numeric(frame, x_name), "y": _numeric(frame, y_name)})
    pair = pair.dropna()
    n = int(len(pair))
    if n < 3:
        return pd.DataFrame([{
            "x": x_name, "y": y_name, "method": method, "n": n,
            "coefficient": None, "r_squared": None,
            "note": "Too few paired observations to compute a correlation.",
        }])

    coefficient = float(pair["x"].corr(pair["y"], method=method))
    return pd.DataFrame([{
        "x": x_name, "y": y_name, "method": method, "n": n,
        "coefficient": round(coefficient, 6),
        "r_squared": round(coefficient ** 2, 6) if method == "pearson" else None,
        "note": "Association, not causation. Nothing here establishes direction.",
    }])


# ----------------------------------------------------------------- regression


def _regression(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Ordinary least squares, one row per coefficient.

    Implemented with numpy's least-squares rather than a statistics package, so
    what is computed is visible in twenty lines and every figure below can be
    checked by hand from the same inputs.
    """
    target = str(params.get("target") or params.get("y") or "")
    features = params.get("features") or params.get("x") or []
    if isinstance(features, str):
        features = [features]
    features = [str(f) for f in features]
    if not target or not features:
        raise PlanError("A regression needs a target and at least one feature.")

    data = pd.DataFrame({name: _numeric(frame, name) for name in [target, *features]})
    data = data.dropna()
    n = int(len(data))
    if n <= len(features) + 1:
        return pd.DataFrame([{
            "term": "(insufficient data)", "coefficient": None, "std_error": None,
            "t_statistic": None, "n": n, "r_squared": None,
            "note": f"{n} complete rows for {len(features)} features is not enough "
                    "to fit a line anybody should read.",
        }])

    y = data[target].to_numpy(dtype=float)
    design = np.column_stack([np.ones(n), data[features].to_numpy(dtype=float)])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)

    fitted = design @ coefficients
    residuals = y - fitted
    dof = n - design.shape[1]
    sigma_squared = float(residuals @ residuals) / dof if dof > 0 else float("nan")

    try:
        covariance = sigma_squared * np.linalg.inv(design.T @ design)
        errors = np.sqrt(np.diag(covariance))
    except np.linalg.LinAlgError:  # collinear features
        errors = np.full(design.shape[1], float("nan"))

    total = float(((y - y.mean()) ** 2).sum())
    r_squared = 1.0 - (float(residuals @ residuals) / total) if total > 0 else None

    rows = []
    for index, term in enumerate(["(intercept)", *features]):
        error = float(errors[index])
        coefficient = float(coefficients[index])
        rows.append({
            "term": term,
            "coefficient": round(coefficient, 6),
            "std_error": round(error, 6) if math.isfinite(error) else None,
            "t_statistic": (round(coefficient / error, 4)
                            if math.isfinite(error) and error else None),
            "n": n,
            "r_squared": round(r_squared, 6) if r_squared is not None else None,
            "note": "Ordinary least squares. Fitted, not validated — no "
                    "out-of-sample test has been run.",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- trend


def _trend(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Direction and slope of one series over an ordered axis."""
    column = str(params.get("column") or params.get("of") or "")
    over = str(params.get("over") or params.get("x") or "")
    values = _numeric(frame, column)

    if over and over in frame.columns:
        ordered = frame.assign(_v=values).sort_values(over)
        series = ordered["_v"].dropna()
        labels = ordered.loc[series.index, over].astype(str).tolist()
    else:
        series = values.dropna()
        labels = [str(i) for i in range(len(series))]

    n = int(len(series))
    if n < 3:
        return pd.DataFrame([{
            "column": column, "n": n, "slope_per_period": None,
            "direction": "unknown", "first": None, "last": None,
            "change": None, "change_pct": None,
            "note": "Fewer than three points is not a trend.",
        }])

    y = series.to_numpy(dtype=float)
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    first, last = float(y[0]), float(y[-1])

    return pd.DataFrame([{
        "column": column,
        "n": n,
        "from": labels[0],
        "to": labels[-1],
        "first": round(first, 6),
        "last": round(last, 6),
        "change": round(last - first, 6),
        "change_pct": round(100.0 * (last - first) / first, 4) if first else None,
        "slope_per_period": round(float(slope), 6),
        "intercept": round(float(intercept), 6),
        "direction": "rising" if slope > 0 else "falling" if slope < 0 else "flat",
        "note": "A straight line through the points. It describes the period "
                "shown and forecasts nothing.",
    }])


# -------------------------------------------------------------------- outlier


def _outlier(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Flag unusual values, by the interquartile rule or by z-score."""
    column = str(params.get("column") or params.get("of") or "")
    method = str(params.get("method") or "iqr").lower()
    if method not in ("iqr", "zscore"):
        raise PlanError(f"'{method}' is not an outlier rule. Use iqr or zscore.")

    values = _numeric(frame, column)
    out = frame.copy()

    if method == "iqr":
        multiplier = float(params.get("multiplier") or 1.5)
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        spread = q3 - q1
        low, high = q1 - multiplier * spread, q3 + multiplier * spread
        out["is_outlier"] = ((values < low) | (values > high)).fillna(False)
        out["outlier_score"] = ((values - values.median()) / spread).round(4) \
            if spread else 0.0
    else:
        threshold = float(params.get("threshold") or 3.0)
        mean, deviation = values.mean(), values.std()
        score = (values - mean) / deviation if deviation else values * 0
        out["is_outlier"] = (score.abs() > threshold).fillna(False)
        out["outlier_score"] = score.round(4)

    return out


# ------------------------------------------------------------------ stat test


def _stat_test(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """A two-sample comparison of means, with its own caveat attached."""
    test = str(params.get("test") or "t_test").lower()
    if test not in ("t_test", "welch"):
        raise PlanError(
            f"'{test}' is not a test the runtime provides. Use t_test or welch."
        )

    column = str(params.get("column") or params.get("of") or "")
    group = str(params.get("by") or params.get("group") or "")
    if group not in frame.columns:
        raise PlanError(f"A statistical test needs a grouping column; '{group}' is absent.")

    values = _numeric(frame, column)
    groups = [g for g, _ in frame.groupby(group, observed=True)]
    if len(groups) != 2:
        return pd.DataFrame([{
            "test": test, "column": column, "by": group,
            "groups": len(groups), "statistic": None, "p_value": None,
            "note": f"This test compares exactly two groups; {len(groups)} were found.",
        }])

    a = values[frame[group] == groups[0]].dropna().to_numpy(dtype=float)
    b = values[frame[group] == groups[1]].dropna().to_numpy(dtype=float)
    if len(a) < 2 or len(b) < 2:
        return pd.DataFrame([{
            "test": test, "column": column, "by": group, "groups": 2,
            "statistic": None, "p_value": None,
            "note": "Each group needs at least two observations.",
        }])

    from scipy import stats  # imported here: SciPy is only needed for this kernel

    result = stats.ttest_ind(a, b, equal_var=(test == "t_test"))
    return pd.DataFrame([{
        "test": test,
        "column": column,
        "by": group,
        "group_a": str(groups[0]), "n_a": int(len(a)), "mean_a": round(float(a.mean()), 6),
        "group_b": str(groups[1]), "n_b": int(len(b)), "mean_b": round(float(b.mean()), 6),
        "statistic": round(float(result.statistic), 6),
        "p_value": round(float(result.pvalue), 8),
        "note": "A p-value is not an effect size, and this population was not "
                "randomly assigned.",
    }])


# ------------------------------------------------------------------- scenario


def _scenario(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Apply declared multiplicative or additive shocks to named columns.

    Deliberately mechanical. It does not model anything: it multiplies what is
    there by what the user said, and shows both. Anything cleverer would be a
    stress model, and a stress model needs validation this phase has not done.
    """
    shocks = params.get("shocks") or params.get("shock") or {}
    if not isinstance(shocks, dict) or not shocks:
        raise PlanError(
            "A scenario needs 'shocks': a column and the multiplier or amount to "
            "apply to it."
        )

    out = frame.copy()
    for column, shock in shocks.items():
        column = str(column)
        base = _numeric(out, column)
        if isinstance(shock, dict):
            multiplier = float(shock.get("multiply", 1.0))
            addition = float(shock.get("add", 0.0))
        else:
            multiplier, addition = float(shock), 0.0
        out[f"{column}_base"] = base
        out[f"{column}_stressed"] = base * multiplier + addition
        out[f"{column}_impact"] = out[f"{column}_stressed"] - base
    out["scenario"] = str(params.get("name") or "scenario")
    return out



# ------------------------------------------------------------- discrimination


def _discrimination(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Gini, AUC, KS or the calibration ratio, on the rows the plan selected.

    A kernel rather than SQL because none of these is an aggregate: a Gini is a
    property of how the score RANKS the population, and there is no sum that
    recovers it. It has to see every row.

    It delegates to `backend.scorecard.metrics`, which computes these for the
    model validation module. Two implementations of one statistic is how a
    validation report and a dashboard come to disagree about the same
    scorecard, and neither can say which is right.
    """
    from backend.scorecard import metrics as scorecard

    if params.get("_truncated"):
        raise PlanError(
            f"This statistic reads every row, and the query returned the "
            f"maximum {int(params.get('_row_limit') or 0):,} rows — so it "
            "would be measured on part of the population. Narrow the period "
            "or the scope so the whole population fits.")

    statistic = str(params.get("statistic") or "gini").lower()
    target = str(params.get("target") or "")
    if not target:
        raise PlanError("Discrimination needs an outcome column to measure "
                        "against.")

    try:
        if statistic == "calibration_ratio":
            predicted = str(params.get("pd_column") or "")
            if not predicted:
                raise PlanError(
                    "A calibration ratio needs the column holding the "
                    "predicted probability of default.")
            found = scorecard.calibration(frame, pd_column=predicted,
                                          target=target)
            if not found.observed:
                raise PlanError(
                    "The observed default rate is zero for these rows, so a "
                    "predicted-over-observed ratio has no value.")
            return pd.DataFrame([{
                "statistic": statistic,
                "value": float(found.predicted / found.observed),
                "observations": int(found.observations),
                "events": int(round(found.observed * found.observations)),
                "score_direction": "",
                "evidence": found.evidence,
                "note": (f"Predicted {found.predicted:.4%} against observed "
                         f"{found.observed:.4%}."),
            }])

        score = str(params.get("score") or "")
        if not score:
            raise PlanError("Discrimination needs a score column to rank on.")
        if statistic not in ("gini", "auc", "ks"):
            raise PlanError(
                f"'{statistic}' is not a discrimination statistic CreditProbe "
                "computes. It provides: gini, auc, ks, calibration_ratio.")
        direction = str(params.get("direction") or "")
        if not direction:
            raise PlanError(
                "Discrimination needs to be told which way the score runs. "
                "Without it a Gini comes back with the right magnitude and "
                "possibly the wrong sign.")
        found = scorecard.discrimination(
            frame, score=score, target=target, score_direction=direction)
        value = {"gini": found.gini, "auc": found.auc, "ks": found.ks}[statistic]
        return pd.DataFrame([{
            "statistic": statistic,
            "value": float(value),
            "observations": int(found.observations),
            "events": int(found.events),
            "score_direction": found.score_direction,
            "evidence": found.evidence,
            # The sample size, and only the sample size. The AUC belongs in
            # the answer, not in the caveat beside it — and the display
            # contract governs figures a reader sees, which this is.
            "note": (f"{found.events:,} defaults in "
                     f"{found.observations:,} rows."),
        }])
    except scorecard.MetricError as e:
        # An immature cohort, or a sample with no defaults in it. Both are
        # facts about the data, and both must reach the reader as sentences
        # rather than as a number computed some other way.
        raise PlanError(str(e)) from e


KERNELS: dict[str, Kernel] = {
    "correlation": Kernel(
        "correlation", "Association between two numeric columns.",
        ("x", "y", "method", "n", "coefficient", "r_squared", "note"),
        _correlation,
        "Measures association only. It cannot show which way the influence runs, "
        "and a third factor moving both looks identical.",
    ),
    "regression": Kernel(
        "regression", "Ordinary least squares fit, one row per term.",
        ("term", "coefficient", "std_error", "t_statistic", "n", "r_squared", "note"),
        _regression,
        "Fitted on the data given. No out-of-sample validation, no test for the "
        "assumptions behind least squares.",
    ),
    "trend": Kernel(
        "trend", "Direction and slope of a series over an ordered axis.",
        ("column", "n", "from", "to", "first", "last", "change", "change_pct",
         "slope_per_period", "intercept", "direction", "note"),
        _trend,
        "Describes the period shown. It is not a forecast.",
    ),
    "outlier": Kernel(
        "outlier", "Flag unusual values by the interquartile rule or z-score.",
        ("is_outlier", "outlier_score"),
        _outlier,
        "Unusual is not wrong. A large exposure may be the bank's biggest client.",
    ),
    "stat_test": Kernel(
        "stat_test", "Compare the means of two groups.",
        ("test", "column", "by", "group_a", "n_a", "mean_a", "group_b", "n_b",
         "mean_b", "statistic", "p_value", "note"),
        _stat_test,
        "Significance is not materiality, and this population was not randomly "
        "assigned.",
    ),
    "scenario": Kernel(
        "scenario", "Apply declared shocks to named columns.",
        ("scenario",),
        _scenario,
        "Applies the shock stated and nothing else. No behavioural response, no "
        "second-round effect, no model.",
    ),
    "discrimination": Kernel(
        "discrimination",
        "Gini, AUC, KS or the predicted-over-observed calibration ratio.",
        ("statistic", "value", "observations", "events", "score_direction",
         "evidence", "note"),
        _discrimination,
        "Measured on the rows given, which must have a realised outcome. It "
        "says how well the score ranks, not whether the predicted level is "
        "right — that is the calibration ratio, and they can disagree.",
    ),
}


#: Which kernel each operation uses when the plan does not name one.
_DEFAULT_KERNEL: dict[OpType, str] = {
    OpType.CORRELATION: "correlation",
    OpType.REGRESSION: "regression",
    OpType.TREND: "trend",
    OpType.OUTLIER: "outlier",
    OpType.STAT_TEST: "stat_test",
    OpType.SCENARIO: "scenario",
    OpType.DISCRIMINATION: "discrimination",
}


def kernel_for(op: Operation) -> Kernel:
    """The approved kernel for an operation. Refuses anything else by name."""
    requested = str(op.params.get("kernel") or "").lower()
    name = requested or _DEFAULT_KERNEL.get(op.op, "")
    kernel = KERNELS.get(name)
    if kernel is None:
        raise PlanError(
            f"{op.id}: '{name or op.op}' is not a numerical operation CreditProbe "
            f"provides. Approved operations: {', '.join(sorted(KERNELS))}."
        )
    return kernel


def describe_kernel(kernel: Kernel, op: Operation) -> tuple[str, ...]:
    """The columns a kernel adds, so validation can carry the schema forward.

    OUTLIER and SCENARIO annotate the rows they were given rather than replacing
    them, so their outputs are additions; the rest return a summary table.
    """
    if kernel.name in ("outlier", "scenario"):
        return kernel.outputs
    return kernel.outputs


def run_kernel(kernel: Kernel, frame: pd.DataFrame,
               params: dict[str, Any]) -> pd.DataFrame:
    """Execute an approved kernel. The only place a kernel is ever called."""
    try:
        return kernel.run(frame, params)
    except PlanError:
        raise
    except Exception as e:
        logger.exception("Kernel %s failed", kernel.name)
        raise PlanError(
            f"The {kernel.name} calculation could not be completed: {e}"
        ) from e


def catalogue() -> list[dict[str, Any]]:
    """Every approved kernel, for the runtime documentation screen."""
    return [
        {
            "name": k.name,
            "summary": k.summary,
            "outputs": list(k.outputs),
            "limitations": k.limitations,
        }
        for k in sorted(KERNELS.values(), key=lambda k: k.name)
    ]


__all__ = ["KERNELS", "Kernel", "catalogue", "describe_kernel", "kernel_for", "run_kernel"]
