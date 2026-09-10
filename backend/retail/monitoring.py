"""
Scorecard monitoring: discrimination, calibration, stability, and the
counts that say when none of them can honestly be computed.

The rules this module will not bend:

* **Orientation is declared, not inferred.** The score is higher-is-safer, so
  the positive class (default) is ranked by the NEGATED score. `Gini = 2*AUC-1`
  and an inverted scorecard produces a negative Gini rather than an absolute
  value that hides it.
* **An unknown outcome is not a good.** Rows whose performance window has not
  elapsed are excluded and counted, never swept into the non-default class.
* **One application is counted once.** An application score repeated on
  twenty-five monthly rows is one observation at origination, not twenty-five.
* **Not enough evidence is an answer.** A single-class sample, a segment with
  four defaults, an empty cohort: each returns "Insufficient evidence" with the
  counts, not a fabricated metric or a confidence interval around nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

SCORE_DIRECTION = "HIGHER_IS_SAFER"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

#: Minimum evidence before a discrimination metric is reported at all. A demo
#: setting, configurable, and not a regulatory adequacy standard.
MIN_SAMPLE = 100
MIN_DEFAULTS = 20
THRESHOLD_POLICY_VERSION = "retail-monitoring-thresholds-1.0.0"


@dataclass
class MetricResult:
    """A metric, or a documented reason there isn't one."""

    name: str
    value: float | None
    status: str = "OK"
    detail: str = ""
    sample_count: int = 0
    default_count: int = 0
    distinct_customer_count: int = 0
    uncertainty: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.name, "value": self.value, "status": self.status,
            "detail": self.detail, "sample_count": self.sample_count,
            "default_count": self.default_count,
            "distinct_customer_count": self.distinct_customer_count,
            "uncertainty": self.uncertainty, **self.extras,
        }


def _clean(score: Sequence[float], outcome: Sequence[Any]) -> tuple[np.ndarray, np.ndarray, int]:
    """Drop rows with no score or no known outcome, and say how many went."""
    s = pd.to_numeric(pd.Series(list(score)), errors="coerce").to_numpy(dtype="float64")
    y_raw = pd.Series(list(outcome))
    known = y_raw.notna().to_numpy() & ~np.isnan(s)
    dropped = int((~known).sum())
    return s[known], y_raw[known].astype(bool).to_numpy(), dropped


def auc(score: Sequence[float], outcome: Sequence[Any], *,
        min_sample: int = MIN_SAMPLE, min_defaults: int = MIN_DEFAULTS,
        customer_ids: Sequence[Any] | None = None) -> MetricResult:
    """ROC-AUC with the positive class oriented by the declared score direction.

    Ties are handled by the rank-based (Mann-Whitney) form, which gives tied
    pairs a half-credit rather than counting or discarding them.
    """
    s, y, dropped = _clean(score, outcome)
    n, d = len(s), int(y.sum())
    distinct = len(set(customer_ids)) if customer_ids is not None else 0
    if n == 0:
        return MetricResult("auc", None, INSUFFICIENT,
                            "No rows with both a score and a known outcome.", n, d, distinct)
    if d == 0 or d == n:
        return MetricResult("auc", None, INSUFFICIENT,
                            f"One-class sample: {d} defaults in {n} rows. Discrimination is "
                            "undefined without both classes.", n, d, distinct)
    if n < min_sample or d < min_defaults:
        return MetricResult("auc", None, INSUFFICIENT,
                            f"{n} rows and {d} defaults; the configured minimum is {min_sample} "
                            f"rows and {min_defaults} defaults.", n, d, distinct)

    # Higher score = safer, so rank the NEGATED score for the default class.
    risk = -s
    order = np.argsort(risk, kind="mergesort")
    ranks = np.empty(n, dtype="float64")
    sorted_risk = risk[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_risk[j + 1] == sorted_risk[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    pos_rank_sum = ranks[y].sum()
    n_pos, n_neg = d, n - d
    value = (pos_rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return MetricResult("auc", float(value), "OK",
                        f"Positive class is default; score direction {SCORE_DIRECTION}.",
                        n, d, distinct)


def gini(score: Sequence[float], outcome: Sequence[Any], **kw: Any) -> MetricResult:
    """`2 * AUC - 1`. An inverted scorecard gives a NEGATIVE Gini and says so."""
    a = auc(score, outcome, **kw)
    if a.value is None:
        return MetricResult("gini", None, a.status, a.detail, a.sample_count,
                            a.default_count, a.distinct_customer_count)
    value = 2.0 * a.value - 1.0
    detail = a.detail
    if value < 0:
        detail += (" The Gini is negative: this score ranks the wrong way round on this "
                   "population. It has not been made positive by taking an absolute value.")
    return MetricResult("gini", float(value), "OK", detail, a.sample_count,
                        a.default_count, a.distinct_customer_count)


def ks(score: Sequence[float], outcome: Sequence[Any], *,
       min_sample: int = MIN_SAMPLE, min_defaults: int = MIN_DEFAULTS) -> MetricResult:
    """Kolmogorov-Smirnov separation from the cumulative good and bad curves."""
    s, y, _ = _clean(score, outcome)
    n, d = len(s), int(y.sum())
    if d == 0 or d == n:
        return MetricResult("ks", None, INSUFFICIENT,
                            f"One-class sample: {d} defaults in {n} rows.", n, d)
    if n < min_sample or d < min_defaults:
        return MetricResult("ks", None, INSUFFICIENT,
                            f"{n} rows and {d} defaults; minimum {min_sample}/{min_defaults}.", n, d)
    order = np.argsort(s, kind="mergesort")
    s_sorted, y_sorted = s[order], y[order]
    # Ties share one step: the curves may only move at a distinct score value.
    bad = np.cumsum(y_sorted) / max(d, 1)
    good = np.cumsum(~y_sorted) / max(n - d, 1)
    last_of_tie = np.append(s_sorted[1:] != s_sorted[:-1], True)
    diff = np.abs(bad - good)[last_of_tie]
    return MetricResult("ks", float(diff.max()), "OK",
                        "Cumulative bad minus cumulative good, evaluated at distinct score values.",
                        n, d)


def bootstrap_ci(
    score: Sequence[float], outcome: Sequence[Any], *, statistic: str = "auc",
    draws: int = 400, alpha: float = 0.05, seed: int = 20260910,
    clusters: Sequence[Any] | None = None,
) -> dict[str, Any] | None:
    """A percentile bootstrap interval, clustered by customer when asked.

    Behavioural monitoring repeats the same customer across months. Resampling
    ROWS would treat those repeats as independent borrowers and produce an
    interval far too tight, so the customer is the resampling unit when
    `clusters` is supplied.
    """
    s, y, _ = _clean(score, outcome)
    if len(s) == 0 or y.sum() == 0 or y.all():
        return None
    rng = np.random.default_rng(seed)
    fn = {"auc": auc, "gini": gini, "ks": ks}[statistic]

    if clusters is not None:
        keys = pd.Series(list(clusters))[: len(s)] if len(clusters) >= len(s) else None
        if keys is None:
            clusters = None

    values: list[float] = []
    if clusters is None:
        n = len(s)
        for _ in range(draws):
            idx = rng.integers(0, n, size=n)
            r = fn(s[idx], y[idx], min_sample=1, min_defaults=1)
            if r.value is not None:
                values.append(r.value)
        unit = "row"
    else:
        groups = pd.Series(list(clusters)[: len(s)])
        by = {k: np.where(groups.to_numpy() == k)[0] for k in groups.unique()}
        keys = list(by)
        for _ in range(draws):
            pick = rng.integers(0, len(keys), size=len(keys))
            idx = np.concatenate([by[keys[i]] for i in pick])
            r = fn(s[idx], y[idx], min_sample=1, min_defaults=1)
            if r.value is not None:
                values.append(r.value)
        unit = "customer"

    if len(values) < draws // 4:
        return None
    lo, hi = np.percentile(values, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "method": "percentile bootstrap",
        "resampling_unit": unit,
        "draws": len(values),
        "confidence": 1 - alpha,
        "lower": float(lo),
        "upper": float(hi),
    }


def band_table(
    score: Sequence[float], outcome: Sequence[Any], bands: Sequence[Any],
) -> pd.DataFrame:
    """Counts, defaults and bad rate per score band, with ranking reversals flagged."""
    df = pd.DataFrame({"band": list(bands), "score": list(score), "outcome": list(outcome)})
    df = df.loc[df["outcome"].notna() & df["band"].notna()]
    if df.empty:
        return pd.DataFrame(columns=["band", "count", "defaults", "bad_rate", "reversal"])
    grouped = df.groupby("band", sort=True).agg(
        count=("outcome", "size"),
        defaults=("outcome", lambda s: int(s.astype(bool).sum())),
        mean_score=("score", "mean"),
    ).reset_index()
    grouped["bad_rate"] = grouped["defaults"] / grouped["count"]
    grouped = grouped.sort_values("mean_score").reset_index(drop=True)
    # Higher score = safer, so the bad rate should fall as the score rises.
    grouped["reversal"] = grouped["bad_rate"].diff().fillna(0.0) > 0
    return grouped


def psi(
    reference: Sequence[Any], current: Sequence[Any], *,
    bins: Sequence[Any] | None = None, smoothing: float = 1e-4,
) -> MetricResult:
    """Population stability against a DECLARED reference population.

    Both distributions use the reference's frozen bins, missing is its own
    category rather than a dropped row, and the zero-bin treatment is a stated
    smoothing constant rather than a silent division.
    """
    ref = pd.Series(list(reference)).fillna("MISSING").astype(str)
    cur = pd.Series(list(current)).fillna("MISSING").astype(str)
    categories = list(bins) if bins is not None else sorted(set(ref) | set(cur))
    if not categories:
        return MetricResult("psi", None, INSUFFICIENT, "No categories to compare.", 0, 0)

    r = ref.value_counts().reindex(categories).fillna(0.0)
    c = cur.value_counts().reindex(categories).fillna(0.0)
    if r.sum() == 0 or c.sum() == 0:
        return MetricResult("psi", None, INSUFFICIENT,
                            "One of the two populations is empty.", int(len(cur)), 0)
    rp = (r / r.sum()).clip(lower=smoothing)
    cp = (c / c.sum()).clip(lower=smoothing)
    value = float(((cp - rp) * np.log(cp / rp)).sum())
    return MetricResult(
        "psi", value, "OK",
        f"Against the declared reference population, {len(categories)} frozen bins including "
        f"MISSING, zero bins floored at {smoothing}. A PSI boundary is a configured monitoring "
        "threshold, not a universal regulatory pass or fail.",
        int(len(cur)), 0,
        extras={"bins": categories,
                "reference_share": rp.round(6).to_dict(),
                "current_share": cp.round(6).to_dict()},
    )


def calibration(
    predicted: Sequence[float], outcome: Sequence[Any], *, n_bands: int = 10,
) -> dict[str, Any]:
    """Observed against expected defaults, by predicted-probability band.

    The predicted probability must answer the SAME target and horizon as the
    observed outcome. Substituting an IFRS 9 PD for a missing application-score
    PD would compare two different questions, so the caller passes the model's
    own PD and this function does not go looking for another one.
    """
    df = pd.DataFrame({"p": pd.to_numeric(pd.Series(list(predicted)), errors="coerce"),
                       "y": pd.Series(list(outcome))})
    df = df.loc[df["p"].notna() & df["y"].notna()]
    if df.empty:
        return {"status": INSUFFICIENT, "detail": "No rows with both a prediction and an outcome.",
                "sample_count": 0}
    df["y"] = df["y"].astype(bool)
    try:
        df["band"] = pd.qcut(df["p"], q=min(n_bands, df["p"].nunique()), duplicates="drop")
    except ValueError:
        df["band"] = "ALL"
    g = df.groupby("band", observed=True).agg(
        count=("y", "size"), observed=("y", "sum"), expected=("p", "sum"),
        mean_predicted=("p", "mean")).reset_index()
    g["observed_rate"] = g["observed"] / g["count"]
    g["band"] = g["band"].astype(str)
    total_obs, total_exp = int(df["y"].sum()), float(df["p"].sum())
    return {
        "status": "OK",
        "sample_count": int(len(df)),
        "observed_defaults": total_obs,
        "expected_defaults": round(total_exp, 2),
        "observed_to_expected": (round(total_obs / total_exp, 4) if total_exp > 0 else None),
        "bands": g.to_dict("records"),
        "brier_score": float(((df["p"] - df["y"].astype(float)) ** 2).mean()),
        "note": (
            "The Brier score is shown alongside the calibration curve, not as a calibration "
            "statistic: it mixes calibration with discrimination and cannot separate them."
        ),
    }


def application_cohort(frame: pd.DataFrame) -> pd.DataFrame:
    """Each application once, at origination, with a fully observed outcome.

    An application score does not change across the twenty-five monthly rows of
    the facility it scored. Counting it once per row would multiply a cohort of
    four hundred applications into ten thousand observations and shrink every
    confidence interval accordingly.
    """
    at_origination = frame.loc[frame["months_on_book"] == 0]
    eligible = at_origination.loc[
        at_origination["monitoring_eligible_flag"].fillna(False).astype(bool)
        & at_origination["performance_window_complete_flag"].fillna(False).astype(bool)
    ]
    return eligible.drop_duplicates("application_id")


def behavioural_landmarks(frame: pd.DataFrame, months: Iterable[str] | None = None) -> pd.DataFrame:
    """Monthly landmark cohorts for behavioural monitoring.

    Rows repeat the same customer across months and their twelve-month outcome
    windows overlap. That is handled by declaring the landmark explicitly and by
    clustering the uncertainty on the customer, not by pretending each row is an
    independent borrower.
    """
    out = frame.loc[
        frame["monitoring_eligible_flag"].fillna(False).astype(bool)
        & frame["performance_window_complete_flag"].fillna(False).astype(bool)
        & frame["behavioural_score"].notna()
    ]
    if months is not None:
        out = out.loc[out["reporting_month"].isin(list(months))]
    return out


def evidence_envelope(
    *, question: str, model_id: str, model_version: str, target: str, horizon_months: int,
    evaluation_as_of: Any, cohort_dates: Sequence[Any], metrics: Sequence[MetricResult],
    exclusions: dict[str, int], reference_definition: str, dataset_hashes: Sequence[str],
    findings: Sequence[str], limitations: Sequence[str],
) -> dict[str, Any]:
    """The audit-ready result object every monitoring answer must carry."""
    sample = max((m.sample_count for m in metrics), default=0)
    defaults = max((m.default_count for m in metrics), default=0)
    distinct = max((m.distinct_customer_count for m in metrics), default=0)
    return {
        "question": question,
        "model": {"model_id": model_id, "model_version": model_version},
        "target": target,
        "horizon_months": horizon_months,
        "evaluation_as_of": evaluation_as_of,
        "prediction_cohort_dates": [str(d) for d in cohort_dates],
        "sample_count": sample,
        "distinct_customer_count": distinct,
        "default_count": defaults,
        "exclusions": dict(exclusions),
        "reference_definition": reference_definition,
        "metrics": [m.to_dict() for m in metrics],
        "uncertainty": {m.name: m.uncertainty for m in metrics if m.uncertainty},
        "threshold_policy_version": THRESHOLD_POLICY_VERSION,
        "findings": list(findings),
        "limitations": list(limitations),
        "calculation_evidence_refs": [f"retail_facility_month@{h}" for h in dataset_hashes],
        "data_snapshot_hashes": list(dataset_hashes),
        "code_version": "backend/retail/monitoring.py@retail-monitoring-1.0.0",
        "disclosure": (
            "Computed on synthetic demonstration data. These are not ANB findings, not an "
            "independent validation, and no documentary evidence has been supplied."
        ),
    }
